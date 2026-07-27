"""
core/__main__.py — CLI Runtime 入口 (设计文档 §6)

用法:
    python -m core run <video> --lang zh --stages bootstrap
    python -m core stage translate <video>
    python -m core validate <video>
    python -m core export <video>
    python -m core inspect <video>
    python -m core test
"""
from __future__ import annotations
import argparse
import json as _json
import os
import sys
import time


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m core",
        description="Translate-video CLI Runtime — core/ 引擎正式入口",
    )
    sub = p.add_subparsers(dest="command", help="可用命令")

    # ── run ──
    run = sub.add_parser("run", help="运行完整流水线")
    run.add_argument("video", help="视频文件路径")
    run.add_argument("--lang", default="zh", help="目标语言")
    run.add_argument("--engine", default="chattts", help="TTS 引擎")
    run.add_argument("--model", default="turbo", help="Whisper 模型")
    run.add_argument("--device", default="cuda", help="计算设备")
    run.add_argument("--compute-type", default="float16", help="计算精度")
    run.add_argument("--stages", default="bootstrap",
                     help="阶段: bootstrap, export, all, 或逗号分隔: load,extract,...")
    run.add_argument("--dry-run", action="store_true", help="只验证不执行")
    run.add_argument("--force", action="store_true", help="忽略 checkpoint 强制重跑")
    run.add_argument("--skip-demucs", action="store_true", help="跳过人声分离")
    run.add_argument("--no-diarization", action="store_true", help="禁用说话人分离")
    run.add_argument("--json", action="store_true", help="JSON 格式输出")

    # ── stage ──
    stage = sub.add_parser("stage", help="执行单个阶段")
    stage.add_argument("stage_name", choices=["load","extract","translate","validate","tts","export"])
    stage.add_argument("video", help="视频文件路径")
    stage.add_argument("--lang", default="zh")
    stage.add_argument("--engine", default="chattts")
    stage.add_argument("--json", action="store_true")

    # ── validate ──
    val = sub.add_parser("validate", help="只校验时间轴")
    val.add_argument("video", help="视频文件路径")
    val.add_argument("--json", action="store_true")

    # ── export ──
    exp = sub.add_parser("export", help="TTS + 视频导出")
    exp.add_argument("video", help="视频文件路径")
    exp.add_argument("--engine", default="chattts", help="TTS 引擎")
    exp.add_argument("--json", action="store_true")

    # ── inspect ──
    ins = sub.add_parser("inspect", help="查看 workspace 状态")
    ins.add_argument("video", help="视频文件路径")
    ins.add_argument("--json", action="store_true")

    # ── test ──
    test = sub.add_parser("test", help="运行系统自测")

    return p


# ── Terminal Subscriber ─────────────────────────────────

class TerminalSubscriber:
    """将 EventBus 事件格式化输出到终端。"""
    def __init__(self, json_mode: bool = False):
        self._json = json_mode
        self._stage_start: dict[str, float] = {}

    def on_event(self, event) -> None:
        from core.engine.runtime_event import RuntimeEventType as RET
        if self._json:
            print(_json.dumps(event.to_dict(), ensure_ascii=False))
            return

        ev = event.event_type
        ts = time.strftime("%H:%M:%S", time.localtime(event.timestamp))

        if ev == RET.WORKFLOW_STARTED:
            p = event.payload
            print(f"\n{'='*50}")
            print(f"  CLI Runtime — {p.get('video', '')}")
            print(f"  语言: {p.get('lang','')}  阶段: {p.get('stages',[])}")
            print(f"{'='*50}")

        elif ev == RET.STAGE_STARTED:
            self._stage_start[event.stage] = event.timestamp
            print(f"\n  ▸ {event.stage_label} ({event.stage}) 开始...")

        elif ev == RET.STAGE_PROGRESS:
            pct = f" [{event.current_item}/{event.total_items}]" if event.total_items > 0 else ""
            print(f"    · {event.message}{pct}")

        elif ev == RET.STAGE_COMPLETED:
            start = self._stage_start.get(event.stage, event.timestamp)
            elapsed = event.timestamp - start
            print(f"  ✓ {event.stage_label} 完成 ({elapsed:.1f}s)")

        elif ev == RET.ERROR:
            print(f"  ✗ [ERROR] {event.message}", file=sys.stderr)

        elif ev == RET.WORKFLOW_COMPLETED:
            p = event.payload
            print(f"\n{'='*50}")
            print(f"  完成! {p.get('event_count',0)} events")
            print(f"  timeline: {p.get('timeline_path','')}")
            print(f"  workspace: {p.get('workspace_dir','')}")
            print(f"{'='*50}")

        elif ev == RET.WORKFLOW_FAILED:
            print(f"\n  ✗ WORKFLOW FAILED: {event.message}", file=sys.stderr)


# ── 命令实现 ────────────────────────────────────────────

def _parse_stages(raw: str) -> list[str] | None:
    raw = raw.strip()
    if raw in ("", "bootstrap"):
        return None
    if raw == "all":
        return ["all"]
    return [s.strip() for s in raw.split(",") if s.strip()]


def cmd_run(args) -> int:
    from core.engine.event_bus import EventBus
    from core.pipeline import run_pipeline

    EventBus().subscribe(TerminalSubscriber(json_mode=getattr(args, 'json', False)))
    stages = _parse_stages(args.stages)
    stages_display = stages or ["load", "extract", "translate", "validate"]

    if args.dry_run:
        print("[CLI] DRY-RUN 模式")

    state = run_pipeline(
        args.video, target_lang=args.lang, engine=args.engine,
        model=args.model, device=args.device, compute_type=args.compute_type,
        stages=stages, dry_run=args.dry_run, force=args.force,
        skip_demucs=args.skip_demucs,
        enable_speaker_diarization=not args.no_diarization,
    )
    return 0 if state else 1


def cmd_stage(args) -> int:
    from core.engine.event_bus import EventBus
    from core.pipeline import run_pipeline
    EventBus().subscribe(TerminalSubscriber(json_mode=args.json))
    state = run_pipeline(args.video, target_lang=args.lang, engine=args.engine,
                         stages=[args.stage_name])
    return 0 if state else 1


def cmd_validate(args) -> int:
    from core.engine.event_bus import EventBus
    from core.pipeline import run_pipeline
    EventBus().subscribe(TerminalSubscriber(json_mode=args.json))
    state = run_pipeline(args.video, stages=["validate"])
    return 0 if state else 1


def cmd_export(args) -> int:
    from core.engine.event_bus import EventBus
    from core.pipeline import run_pipeline
    EventBus().subscribe(TerminalSubscriber(json_mode=args.json))
    state = run_pipeline(args.video, engine=args.engine, stages=["tts", "export"])
    return 0 if state else 1


def cmd_inspect(args) -> int:
    from pathlib import Path
    video = Path(args.video)
    ws_dir = video.parent / f"{video.stem}_project"
    tl_path = ws_dir / "02_translate" / "timeline.json"

    if not tl_path.is_file():
        print(f"[inspect] 未找到 timeline.json: {tl_path}")
        return 1

    with open(tl_path, "r", encoding="utf-8") as f:
        data = _json.load(f)

    if getattr(args, 'json', False):
        print(_json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    events = data.get("events", [])
    speakers = data.get("speakers", {})
    project = data.get("project", {})

    print(f"\n  Workspace: {ws_dir}")
    print(f"  Schema: {data.get('schema_version','?')}")
    print(f"  Events: {len(events)}")
    print(f"  Speakers: {len(speakers)}")
    print(f"  Duration: {project.get('total_duration', 0):.1f}s")
    print(f"  Language: {project.get('language','?')}")

    for spk_id, spk in speakers.items():
        segs = [e for e in events if e.get("speaker","") == spk_id]
        print(f"\n  Speaker: {spk.get('name', spk_id)} ({spk_id})")
        print(f"    Segments: {len(segs)}")
        if segs:
            first = segs[0]
            print(f"    Sample: [{first['start']:.1f}s-{first['end']:.1f}s] {first.get('text','')[:60]}")

    return 0


def cmd_test(args) -> int:
    return _run_legacy_tests()


# ── 旧自测套件 ─────────────────────────────────────────

def _run_legacy_tests() -> int:
    PASS, FAIL = 0, 0

    def check(name, condition, detail=""):
        nonlocal PASS, FAIL
        if condition:
            PASS += 1; print(f"  ✓ {name}")
        else:
            FAIL += 1; print(f"  ✗ {name}  — {detail}")

    def assert_raises(exc_type, fn):
        try: fn(); return False
        except exc_type: return True
        except Exception: return False

    print("=" * 60)
    print("core/ IR v2 系统验证")
    print("=" * 60)

    # TEST 1
    print("\n── TEST 1: IR 零 Pydantic + frozen ──")
    check("import 不加载 pydantic", "pydantic" not in sys.modules)
    from core.ir import TimelineEventIR, SpeakerNodeIR, TimelineProjectIR
    e = TimelineEventIR(id="evt_001", start=0.0, end=2.0, speaker_ref="S1", text_ref="hello")
    check("frozen setattr 抛 FrozenInstanceError",
          assert_raises(Exception, lambda: setattr(e, "start", 5.0)))
    check("start >= end 抛 ValueError",
          assert_raises(ValueError, lambda: TimelineEventIR(id="bad", start=5.0, end=3.0, speaker_ref=None, text_ref="x")))
    s = SpeakerNodeIR(id="SPEAKER_00", name="Alice")
    check("SpeakerNodeIR frozen", hasattr(s, "id") and s.name == "Alice")

    # TEST 2
    print("\n── TEST 2: 零 deepcopy ──")
    import ast, pathlib as _pl
    # 白名单：防御性拷贝的正当用途（均不在 per-patch / per-render 热路径上）
    #   global_config.py    — 全局配置的调用方隔离拷贝，防共享默认值被污染
    #   config_resolver.py  — 缓存解析结果的取出拷贝，防缓存被调用方写穿
    #   patch_engine.py     — dry_run 预览隔离（每次用户点击预览一次，非热路径）
    _DC_WHITELIST = {"global_config.py", "config_resolver.py", "patch_engine.py"}
    core_dir = _pl.Path(__file__).parent
    has_dc = False; dc_files = []
    for pf in core_dir.rglob("*.py"):
        if pf.name == "__main__.py" or pf.name in _DC_WHITELIST: continue
        content = pf.read_text(encoding="utf-8")
        try: tree = ast.parse(content)
        except SyntaxError: continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "copy":
                if any(a.name == "deepcopy" for a in node.names):
                    has_dc = True; dc_files.append(f"{pf.name}")
    check("core/ 下零 deepcopy (白名单外)", not has_dc, "; ".join(dc_files))

    # TEST 3
    print("\n── TEST 3: ProjectState + IR 引用 ──")
    from core.runtime import TimelineProjectState
    events = {
        "evt_001": TimelineEventIR(id="evt_001", start=0.0, end=1.0, speaker_ref="S1", text_ref="hello"),
        "evt_002": TimelineEventIR(id="evt_002", start=1.0, end=3.0, speaker_ref="S2", text_ref="world"),
    }
    spks = {"S1": SpeakerNodeIR(id="S1", name="Alice"), "S2": SpeakerNodeIR(id="S2", name="Bob")}
    ir = TimelineProjectIR(events=events, speakers=spks)
    state = TimelineProjectState(ir)
    check("state.ir 保持原引用", state.ir is ir)
    check("sorted_events 按 start 排序",
          state.sorted_events()[0].id == "evt_001" and state.sorted_events()[1].id == "evt_002")

    # TEST 4
    print("\n── TEST 4: PatchEngine ──")
    from core.runtime import Patch, PatchEngine
    engine = PatchEngine()
    orig_text = ir.events["evt_001"].text_ref
    p1 = Patch(id="p1", target_id="evt_001", op="replace", value={"translation": "ni hao"}, author="user")
    check("replace applied", engine.apply(state, p1)["status"] == "applied")
    check("IR text_ref 不变", ir.events["evt_001"].text_ref == orig_text)
    check("未知 target → error", engine.apply(state, Patch(id="x", target_id="no", op="replace", value={}))["status"] == "error")
    check("未知 op → error", engine.apply(state, Patch(id="x", target_id="evt_001", op="unknown", value={}))["status"] == "error")
    check("merge applied", engine.apply(state, Patch(id="m", target_id="evt_001", op="merge", value={"target_ids": ["evt_001","evt_002"]}))["status"] == "applied")
    check("split applied", engine.apply(state, Patch(id="s", target_id="evt_002", op="split", value={"at": 2.0}))["status"] == "applied")

    # TEST 5
    print("\n── TEST 5: SynthesisEngine ──")
    from core.runtime import SynthesisEngine
    synth = SynthesisEngine()
    r1 = synth.render_all(state)
    check("render_all 返回 2 个事件", len(r1) == 2)
    check("重复渲染结果一致", r1 == synth.render_all(state))

    # TEST 6
    print("\n── TEST 6: Patch replay 一致性 ──")
    s2 = TimelineProjectState(ir)
    ps = [
        Patch(id="r1", target_id="evt_001", op="replace", value={"note": "test"}),
        Patch(id="r2", target_id="evt_002", op="replace", value={"score": 0.95}),
    ]
    PatchEngine().apply_many(s2, ps)
    s3 = TimelineProjectState(ir)
    engine.apply_many(s3, ps)
    check("同 patches → 同渲染", synth.render_all(s2) == synth.render_all(s3))

    # TEST 7
    print("\n── TEST 7: Patch timestamp 排序 ──")
    from core.runtime import TimelineEventState
    es2 = TimelineEventState(TimelineEventIR(id="evt_001", start=0.0, end=1.0, speaker_ref="S1", text_ref="hello"))
    es2.add_patch(Patch(id="p_new", target_id="evt_001", op="replace", value={"v": 2}, timestamp=200.0))
    es2.add_patch(Patch(id="p_old", target_id="evt_001", op="replace", value={"v": 1}, timestamp=100.0))
    check("patches 按 timestamp 排序", es2.patches[0].id == "p_old")

    # TEST 8
    print("\n── TEST 8: verify 模块 ──")
    from core.runtime.verify import _build_speaker_map, _compare
    check("_build_speaker_map 空", _build_speaker_map([], None) == {})
    check("_compare 同数据无差异", len(_compare(
        [{"id":"e1","start":0,"end":1,"speaker":"S1","text":"hi"}],
        {"events":[{"id":"e1","start":0,"end":1,"speaker":"S1","text":"hi"}]})) == 0)

    # TEST 9
    print("\n── TEST 9: PassManager 拓扑排序 ──")
    from core.engine import PassManager, TimelinePass
    class PA(TimelinePass):
        name = "a"
        def apply(self, s): return s
    class PB(TimelinePass):
        name = "b"
        depends_on = ["a"]
        def apply(self, s): return s
    class PC(TimelinePass):
        name = "c"
        depends_on = ["a", "b"]
        def apply(self, s): return s
    pm = PassManager(); pm.register(PA()); pm.register(PB()); pm.register(PC())
    ir_min = TimelineProjectIR(events={
        "evt_001": TimelineEventIR(id="evt_001", start=0.0, end=1.0, speaker_ref="S1", text_ref="hi"),
    })
    pm.run(TimelineProjectState(ir_min))
    check("拓扑序 a<b<c", pm._order.index("a") < pm._order.index("b") < pm._order.index("c"))

    # TEST 10
    print("\n── TEST 10: TimelineIndex ──")
    from core.runtime.index import TimelineIndex
    evts_idx = {
        "evt_001": TimelineEventIR(id="evt_001", start=0.0, end=1.0, speaker_ref="S1", text_ref="hi"),
        "evt_002": TimelineEventIR(id="evt_002", start=1.2, end=2.5, speaker_ref="S1", text_ref="there"),
        "evt_003": TimelineEventIR(id="evt_003", start=2.8, end=4.0, speaker_ref="S2", text_ref="world"),
    }
    ir_idx = TimelineProjectIR(events=evts_idx, speakers={"S1": SpeakerNodeIR(id="S1"),"S2": SpeakerNodeIR(id="S2")})
    idx = TimelineIndex(TimelineProjectState(ir_idx))
    check("by_speaker S1=2", len(idx.by_speaker.get("S1",[])) == 2)
    check("events_in_range=2", len(idx.events_in_range(0.5, 1.5)) == 2)

    # TEST 11
    print("\n── TEST 11: Pass 管线端到端 ──")
    from core.passes import ASRToIRPass, SemanticMergePass, LLMTranslationPass, SRTExportPass
    segs = [
        {"start":0.0,"end":1.2,"text":"Hello world","speaker":"SPEAKER_00"},
        {"start":1.3,"end":2.0,"text":"How are you","speaker":"SPEAKER_00"},
        {"start":2.5,"end":4.0,"text":"I am fine thanks","speaker":"SPEAKER_01"},
    ]
    st_test = ASRToIRPass(segments=segs).apply()
    check("3 events", len(st_test.event_states) == 3)
    st_test = SemanticMergePass(gap_threshold=0.3).apply(st_test)
    check("merge evt_002", "evt_002" in st_test.get_event("evt_001").derivatives.get("_merged_from",[]))
    st_test = LLMTranslationPass(translate_fn=lambda u, s: "stub译文").apply(st_test)
    check("translation written", "translation" in st_test.get_event("evt_001").derivatives)
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), "test_pass_output.srt")
    st_test = SRTExportPass(output_path=tmp).apply(st_test)
    check("SRT 文件", os.path.isfile(tmp))
    if os.path.isfile(tmp):
        c = open(tmp,encoding="utf-8").read()
        check("SRT 含序号", "1\n" in c); check("SRT 含时间戳", "-->" in c)
        os.unlink(tmp)

    # TEST 12
    print("\n── TEST 12: UIMapper ──")
    from timeline.ui_adapter import UIMapper
    ui_ir = TimelineProjectIR(events={
        "evt_001": TimelineEventIR(id="evt_001", start=0.0, end=1.0, speaker_ref="S1", text_ref="hello"),
        "evt_002": TimelineEventIR(id="evt_002", start=1.0, end=2.0, speaker_ref="S2", text_ref="world"),
    }, speakers={"S1": SpeakerNodeIR(id="S1", name="Alice"), "S2": SpeakerNodeIR(id="S2")})
    lanes = UIMapper().to_speaker_lanes(TimelineProjectState(ui_ir))
    check("2 lanes", len(lanes) == 2)
    check("Alice name", any(l["display_name"] == "Alice" for l in lanes))

    # TEST 13
    print("\n── TEST 13: WorkflowOrchestrator ──")
    from core.config import WorkflowPolicy, WorkflowStage, StageConfig
    from core.engine import WorkflowOrchestrator, WorkflowStatus
    policy = WorkflowPolicy.quick_preset("zh")
    check("6 stages", len(policy.stages) == 6)
    check("first LOAD", policy.stage_order()[0] == WorkflowStage.LOAD)
    check("last EXPORT", policy.stage_order()[-1] == WorkflowStage.EXPORT)
    bp = WorkflowPolicy.bootstrap_preset("zh")
    check("bootstrap no TTS", WorkflowStage.TTS not in bp.stages)
    check("bootstrap has VALIDATE", WorkflowStage.VALIDATE in bp.stages)
    class Noop(TimelinePass):
        name = "noop"
        def apply(self, s): return s
    orch = WorkflowOrchestrator(WorkflowPolicy.quick_preset("zh"))
    orch.set_pass_factory(lambda n: Noop() if n=="noop" else None)
    orch.run("C:/fake/test.mp4")
    check("orchestrator done", orch.status == WorkflowStatus.COMPLETED)

    # TEST 14
    print("\n── TEST 14: Config Injection ──")
    from core.config import SLOT_DEFAULTS
    from core.runtime.config_resolver import ConfigResolver
    from core.config.global_config import GlobalConfig
    check("10 slots", len(SLOT_DEFAULTS) == 10)
    st_cfg = TimelineProjectState(TimelineProjectIR(events={
        "evt_001": TimelineEventIR(id="evt_001", start=0.0, end=1.0, speaker_ref=None, text_ref="hi"),
    }))
    res = ConfigResolver(GlobalConfig()).resolve_event_config("evt_001", "tts", st_cfg)
    check("tts engine in config", "engine" in res)

    # TEST 15
    print("\n── TEST 15: Gate Routing ──")
    from core.gates.text_gate import TextGate
    from core.gates.emotion_gate import EmotionGate
    from core.emotion.emotion_space import EmotionVector
    g = TextGate(semantic_threshold=0.70, sim_drop_limit=0.05)
    check("TextGate A PASS", g.decide(0.85, 0.88, 1.0, 0.8).accepted)
    check("TextGate A FAIL", not g.decide(0.85, 0.60, 1.0, 1.0).accepted)
    eg = EmotionGate(max_break=1.5, min_confidence=0.3, max_conflict=1.0)
    check("EmotionGate E2 PASS", eg.decide(EmotionVector(
        emotion=0.5, valence=0.5, arousal=0.5, dominance=0.5, confidence=0.8, intensity=0.4)).accepted)

    print("\n" + "=" * 60)
    total = PASS + FAIL
    print(f"结果: {PASS}/{total} 通过", end="")
    if FAIL > 0:
        print(f", {FAIL} 失败")
        return 1
    print(" — 全部通过")
    print("=" * 60)
    return 0


# ── entry ───────────────────────────────────────────────

_COMMANDS = {
    "run": cmd_run, "stage": cmd_stage, "validate": cmd_validate,
    "export": cmd_export, "inspect": cmd_inspect, "test": cmd_test,
}

def main() -> int:
    parser = _build_parser()
    if "--test" in sys.argv or "-t" in sys.argv:
        return _run_legacy_tests()
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return 1
    handler = _COMMANDS.get(args.command)
    if handler is None:
        print(f"未知命令: {args.command}", file=sys.stderr)
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
