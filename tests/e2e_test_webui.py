"""
End-to-end test: WebUI pipeline via urllib only.
Tests POST /api/pipeline/run -> SSE /api/pipeline/{id}/logs -> GET status -> checkpoint.
"""
import json
import time
import urllib.request
import urllib.error
import sys
import os

SERVER = "http://127.0.0.1:8000"
TEST_VIDEO = "D:/Workspace/Translate_video/source_file/test.mp4"
CHECKPOINT_PATH = "D:/Workspace/Translate_video/source_file/test_project/checkpoint.json"
TIMEOUT = 120


def main():
    results = {"errors": [], "sse_messages": 0, "parse_errors": 0, "final_status": None}

    # 1. POST /api/pipeline/run
    payload = json.dumps({
        "video_path": TEST_VIDEO,
        "lang": "en",
        "target_lang": "zh-CN",
        "model": "turbo",
        "device": "cuda",
        "compute_type": "float16",
        "engine": "chattts",
        "skip_extract": True,
        "skip_translate": True,
        "force": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{SERVER}/api/pipeline/run",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            job_id = data.get("job_id")
            print(f"[1] POST /api/pipeline/run -> job_id={job_id}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[FAIL] POST returned HTTP {e.code}: {body}")
        results["errors"].append(f"HTTP {e.code}: {body}")
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return
    except Exception as e:
        print(f"[FAIL] POST exception: {e}")
        results["errors"].append(str(e))
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return

    # 2. SSE: GET /api/pipeline/{job_id}/logs
    sse_url = f"{SERVER}/api/pipeline/{job_id}/logs"
    print(f"[2] Connecting SSE: {sse_url}")

    sse_req = urllib.request.Request(sse_url)
    sse_lines = []
    try:
        with urllib.request.urlopen(sse_req, timeout=TIMEOUT) as resp:
            buffer = b""
            start_time = time.time()
            done_received = False
            while not done_received:
                chunk = resp.read(4096)
                if not chunk:
                    time.sleep(0.1)
                    if time.time() - start_time > TIMEOUT:
                        print("[SSE] Timeout reached")
                        results["errors"].append("SSE timeout")
                        break
                    continue
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line_str = line.decode("utf-8", errors="replace").strip()
                    if not line_str:
                        continue
                    sse_lines.append(line_str)
                    if line_str.startswith("data:"):
                        data_str = line_str[5:].strip()
                        try:
                            parsed = json.loads(data_str)
                            results["sse_messages"] += 1
                            if parsed.get("event") == "done":
                                done_received = True
                                print(f"[SSE] Received 'done' event")
                                break
                        except json.JSONDecodeError:
                            results["parse_errors"] += 1
                            print(f"[SSE JSON ERROR] {line_str[:120]}")
                    if time.time() - start_time > TIMEOUT:
                        print("[SSE] Timeout while reading")
                        results["errors"].append("SSE reading timeout")
                        break
    except urllib.error.HTTPError as e:
        print(f"[SSE] HTTP error: {e.code}")
        results["errors"].append(f"SSE HTTP {e.code}")
    except Exception as e:
        print(f"[SSE] Exception: {e}")
        results["errors"].append(f"SSE exception: {e}")

    print(f"[SSE] Total raw lines: {len(sse_lines)}")
    print(f"[SSE] Parsed messages: {results['sse_messages']}")
    print(f"[SSE] Parse errors: {results['parse_errors']}")

    if sse_lines:
        print("[SSE] Last 5 lines:")
        for line in sse_lines[-5:]:
            print(f"  {line[:200]}")

    # 3. Poll status
    status_url = f"{SERVER}/api/pipeline/{job_id}/status"
    print(f"[3] Polling status: {status_url}")
    start = time.time()
    while time.time() - start < TIMEOUT:
        try:
            with urllib.request.urlopen(status_url, timeout=5) as resp:
                status_data = json.loads(resp.read())
                status = status_data.get("status")
                progress = status_data.get("progress", 0)
                step = status_data.get("current_step", "")
                if status != "running":
                    print(f"[3] Final status: {status}, progress={progress}, step='{step}'")
                    results["final_status"] = status_data
                    break
        except Exception as e:
            print(f"[Status poll error] {e}")
        time.sleep(1)

    if results["final_status"] is None:
        try:
            with urllib.request.urlopen(status_url, timeout=5) as resp:
                results["final_status"] = json.loads(resp.read())
        except Exception:
            pass
        print(f"[3] Poll timeout, last known: {json.dumps(results['final_status'], ensure_ascii=False)}")
        results["errors"].append("Status poll timeout")

    # 4. Check for error messages in SSE
    error_lines = [l for l in sse_lines if "[ERROR]" in l or "error" in l.lower()]
    if error_lines:
        print(f"[4] Error lines in SSE ({len(error_lines)}):")
        for l in error_lines[:10]:
            print(f"  {l[:200]}")
    else:
        print("[4] No error lines in SSE logs")

    # 5. Checkpoint file
    if os.path.exists(CHECKPOINT_PATH):
        try:
            with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
                checkpoint = json.load(f)
            print(f"[5] Checkpoint exists: {json.dumps(checkpoint, indent=2, ensure_ascii=False)}")
            results["checkpoint"] = checkpoint
        except Exception as e:
            print(f"[5] Checkpoint read error: {e}")
            results["checkpoint"] = {"error": str(e)}
    else:
        print(f"[5] No checkpoint file at {CHECKPOINT_PATH}")

    # Summary
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"  Job ID:            {job_id}")
    print(f"  SSE messages:      {results['sse_messages']}")
    print(f"  JSON parse errors: {results['parse_errors']}")
    final = results.get("final_status", {}) or {}
    print(f"  Final status:      {final.get('status', 'UNKNOWN')}")
    print(f"  Progress:          {final.get('progress', 'N/A')}")
    print(f"  Current step:      {final.get('current_step', 'N/A')}")
    print(f"  Has checkpoint:    {bool(results.get('checkpoint'))}")
    if results["errors"]:
        print(f"  Errors:            {results['errors']}")
    print("=" * 50)

    print("\n##JSON_RESULT_START##")
    print(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    print("##JSON_RESULT_END##")


if __name__ == "__main__":
    main()
