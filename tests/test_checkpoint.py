"""
Test PipelineCheckpoint — unified checkpoint/resume system.

Covers:
  1. State machine: pending → running → completed / failed
  2. Atomic JSON write + round-trip
  3. Crash recovery: stale 'running' → 'failed'
  4. Downstream invalidation
  5. Progress calculation
  6. Extra state for granular resume
  7. File hashing helpers
  8. Video fingerprint
  9. verify_files disk scan
  10. Backward compat: missing checkpoint → fresh state
"""
import json
import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "pipeline"))

from pipeline.checkpoint import (
    PipelineCheckpoint,
    atomic_write_json,
    _file_sha256,
    _video_fingerprint,
    _params_fingerprint,
)


class TestAtomicWrite:
    def test_write_and_read(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "test.json")
            atomic_write_json(p, {"key": "value", "nested": {"a": 1}})
            assert os.path.isfile(p)
            with open(p, "r") as f:
                data = json.load(f)
            assert data["key"] == "value"
            assert data["nested"]["a"] == 1

    def test_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "test.json")
            atomic_write_json(p, {"v": 1})
            atomic_write_json(p, {"v": 2})
            with open(p, "r") as f:
                data = json.load(f)
            assert data["v"] == 2

    def test_creates_parent_dir(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "sub", "deep", "test.json")
            atomic_write_json(p, {"ok": True})
            assert os.path.isfile(p)


class TestFileHashing:
    def test_sha256_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "data.bin")
            with open(p, "wb") as f:
                f.write(b"hello world " * 100)
            h1 = _file_sha256(p)
            h2 = _file_sha256(p)
            assert h1 == h2
            assert len(h1) == 64

    def test_sha256_different_content(self):
        with tempfile.TemporaryDirectory() as d:
            p1 = os.path.join(d, "a.bin")
            p2 = os.path.join(d, "b.bin")
            with open(p1, "wb") as f:
                f.write(b"aaa")
            with open(p2, "wb") as f:
                f.write(b"bbb")
            assert _file_sha256(p1) != _file_sha256(p2)

    def test_sha256_missing_file(self):
        assert _file_sha256("/nonexistent/file.bin") == ""

    def test_video_fingerprint_small(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "video.mp4")
            with open(p, "wb") as f:
                f.write(b"fake mp4 content " * 1000)
            fp = _video_fingerprint(p)
            assert len(fp) == 64

    def test_video_fingerprint_large(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "big.mp4")
            # > 2 MiB → hash first + last 1 MiB + size
            with open(p, "wb") as f:
                f.write(b"HEADER" + b"x" * (1 << 20))
                f.write(b"BODY" * 500_000)
                f.write(b"TAILER" + b"y" * (1 << 20))
            fp = _video_fingerprint(p)
            assert len(fp) == 64

    def test_params_fingerprint_sort_keys(self):
        fp1 = _params_fingerprint({"lang": "ja", "model": "turbo"})
        fp2 = _params_fingerprint({"model": "turbo", "lang": "ja"})
        assert fp1 == fp2
        fp3 = _params_fingerprint({"lang": "en", "model": "turbo"})
        assert fp1 != fp3


class TestStateMachine:
    def test_fresh_all_pending(self):
        ck = PipelineCheckpoint.load("/tmp/_test_ws")
        assert not ck.is_step_done("extract")
        assert not ck.is_step_done("translate")
        assert not ck.is_step_done("tts")

    def test_start_complete_cycle(self):
        ck = PipelineCheckpoint.load("/tmp/_test_ws2")
        ck.start_step("extract")
        assert ck.is_step_running("extract")
        ck.complete_step("extract", output_hashes={"source_srt": "abc123"})
        assert ck.is_step_done("extract")
        assert ck._get_step("extract").output_hashes["source_srt"] == "abc123"

    def test_fail_application_clears_extra(self):
        ck = PipelineCheckpoint.load("/tmp/_test_ws3")
        ck.start_step("translate")
        ck.update_extra("translate", last_batch=42)
        ck.fail_step("translate", "API error", error_type="APPLICATION")
        assert ck._get_step("translate").status == "failed"
        assert ck._get_step("translate").extra_state == {}

    def test_fail_infrastructure_preserves_extra(self):
        ck = PipelineCheckpoint.load("/tmp/_test_ws4")
        ck.start_step("translate")
        ck.update_extra("translate", last_batch=42)
        ck.fail_step("translate", "OOM killed", error_type="INFRASTRUCTURE")
        assert ck._get_step("translate").status == "failed"
        assert ck._get_step("translate").extra_state.get("last_batch") == 42

    def test_retry_after_failure(self):
        ck = PipelineCheckpoint.load("/tmp/_test_ws5")
        ck.start_step("extract")
        ck.fail_step("extract", "temp error", error_type="APPLICATION")
        ck.start_step("extract")  # retry
        ck.complete_step("extract")
        assert ck.is_step_done("extract")
        assert ck._get_step("extract").error == ""


class TestNodeTracking:
    def test_node_lifecycle(self):
        ck = PipelineCheckpoint.load("/tmp/_test_nodes")
        ck.start_step("extract")
        ck.start_node("N1")
        assert not ck.is_node_done("extract", "N1")
        ck.complete_node("N1", output_hashes={"audio.wav": "hash123"})
        assert ck.is_node_done("extract", "N1")

    def test_all_extract_nodes(self):
        ck = PipelineCheckpoint.load("/tmp/_test_nodes2")
        ck.start_step("extract")
        for nid in ("N1", "N1.5", "N2", "N2.5", "N3", "N4"):
            ck.start_node(nid)
            ck.complete_node(nid)
            assert ck.is_node_done("extract", nid)

    def test_node_hashes_persisted(self):
        ck = PipelineCheckpoint.load("/tmp/_test_nodes3")
        ck.start_step("extract")
        ck.complete_node("N2", output_hashes={"audio.wav": "sha256:abc"})
        n = ck._get_step("extract").nodes["N2"]
        assert n.output_hashes["audio.wav"] == "sha256:abc"


class TestCrashRecovery:
    def test_detect_stale_running(self):
        ck = PipelineCheckpoint.load("/tmp/_test_crash")
        ck.start_step("translate")
        assert ck.is_step_running("translate")
        crashed = ck.recover_from_crash()
        assert "translate" in crashed
        assert ck._get_step("translate").status == "failed"
        assert ck._get_step("translate").error_type == "INFRASTRUCTURE"

    def test_no_false_positive(self):
        ck = PipelineCheckpoint.load("/tmp/_test_crash2")
        ck.complete_step("extract")
        ck.complete_step("translate")
        ck.complete_step("tts")
        crashed = ck.recover_from_crash()
        assert crashed == []


class TestDownstreamInvalidation:
    def test_rerun_extract_invalidates_all(self):
        ck = PipelineCheckpoint.load("/tmp/_test_inval")
        ck.complete_step("extract")
        ck.complete_step("translate")
        ck.complete_step("tts")
        ck.start_step("extract")
        assert not ck.is_step_done("translate")
        assert not ck.is_step_done("tts")

    def test_rerun_translate_preserves_extract(self):
        ck = PipelineCheckpoint.load("/tmp/_test_inval2")
        ck.complete_step("extract")
        ck.complete_step("translate")
        ck.complete_step("tts")
        ck.start_step("translate")
        assert ck.is_step_done("extract")
        assert not ck.is_step_done("tts")


class TestExtraState:
    def test_get_set(self):
        ck = PipelineCheckpoint.load("/tmp/_test_extra")
        ck.set_extra("translate", "groups_done", 45)
        assert ck.get_extra("translate", "groups_done") == 45

    def test_default_value(self):
        ck = PipelineCheckpoint.load("/tmp/_test_extra2")
        assert ck.get_extra("translate", "no_key", "fallback") == "fallback"

    def test_update_multiple(self):
        ck = PipelineCheckpoint.load("/tmp/_test_extra3")
        ck.update_extra("tts", segs_done=30, segs_total=120)
        assert ck.get_extra("tts", "segs_done") == 30
        assert ck.get_extra("tts", "segs_total") == 120


class TestProgress:
    def test_idle_zero(self):
        ck = PipelineCheckpoint.load("/tmp/_test_prog")
        p = ck.progress()
        assert p["current_step"] == "idle"
        assert p["pct"] == 0.0

    def test_all_completed(self):
        ck = PipelineCheckpoint.load("/tmp/_test_prog2")
        ck.steps["extract"].status = "completed"
        ck.steps["translate"].status = "completed"
        ck.steps["tts"].status = "completed"
        p = ck.progress()
        assert p["pct"] == 100.0

    def test_translate_in_progress(self):
        ck = PipelineCheckpoint.load("/tmp/_test_prog3")
        ck.steps["extract"].status = "completed"
        ck.steps["translate"].status = "running"
        ck.update_extra("translate", groups_done=30, groups_total=100)
        p = ck.progress()
        assert p["current_step"] == "translate"
        assert p["done"] == 1 + 30


class TestVerifyFiles:
    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            ck = PipelineCheckpoint.load(d)
            ck.complete_step("extract", output_hashes={"source_srt": "abc"})
            issues = ck.verify_files({"source_srt": os.path.join(d, "no.srt")})
            assert len(issues) == 1
            assert issues[0][2] == "missing"
            assert ck._get_step("extract").status == "failed"

    def test_valid_files_pass(self):
        with tempfile.TemporaryDirectory() as d:
            fpath = os.path.join(d, "good.srt")
            with open(fpath, "w") as f:
                f.write("test content")
            h = _file_sha256(fpath)
            ck = PipelineCheckpoint.load(d)
            ck.complete_step("extract", output_hashes={"source_srt": h})
            assert ck.verify_files({"source_srt": fpath}) == []

    def test_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            fpath = os.path.join(d, "changed.srt")
            with open(fpath, "w") as f:
                f.write("content")
            ck = PipelineCheckpoint.load(d)
            ck.complete_step("extract", output_hashes={"source_srt": "wrong"})
            issues = ck.verify_files({"source_srt": fpath})
            assert len(issues) == 1
            assert issues[0][2] == "hash_mismatch"


class TestCleanTmpFiles:
    def test_removes_tmp_only(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "valid.mp4"), "w").close()
            open(os.path.join(d, "stale.tmp"), "w").close()
            open(os.path.join(d, ".hidden.tmp"), "w").close()
            n = PipelineCheckpoint.clean_tmp_files(d)
            assert n == 2
            assert os.path.isfile(os.path.join(d, "valid.mp4"))
            assert not os.path.isfile(os.path.join(d, "stale.tmp"))


class TestSaveLoad:
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            ws = os.path.join(d, "test_project")
            os.makedirs(ws)
            ck = PipelineCheckpoint.load(ws)
            ck.init_from_video("/tmp/v.mp4", {"lang": "ja"})
            ck.start_step("extract")
            ck.complete_node("N1")
            ck.complete_step("extract", output_hashes={"source_srt": "abc"})
            ck.save()
            ck2 = PipelineCheckpoint.load(ws)
            assert ck2.is_step_done("extract")
            assert ck2.is_node_done("extract", "N1")
            assert ck2.video_hash == ck.video_hash

    def test_nonexistent_creates_fresh(self):
        ck = PipelineCheckpoint.load("/tmp/_nope_xyz")
        assert not ck.is_step_done("extract")
        assert ck.video_hash == ""

    def test_corrupt_file_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            cp = os.path.join(d, "checkpoint.json")
            with open(cp, "w") as f:
                f.write("{invalid json {{{")
            ck = PipelineCheckpoint.load(d)
            assert not ck.is_step_done("extract")  # didn't crash


class TestVideoChangeDetection:
    def test_no_change(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "v.mp4")
            with open(p, "wb") as f:
                f.write(b"test content")
            ck = PipelineCheckpoint.load(d)
            ck.init_from_video(p)
            assert not ck.check_video_changed(p)

    def test_change_detected(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "v1.mp4")
            with open(p, "wb") as f:
                f.write(b"original")
            ck = PipelineCheckpoint.load(d)
            ck.init_from_video(p)
            with open(p, "wb") as f:
                f.write(b"modified content")
            ck2 = PipelineCheckpoint.load(d)
            ck2.video_hash = ck.video_hash
            assert ck2.check_video_changed(p)
