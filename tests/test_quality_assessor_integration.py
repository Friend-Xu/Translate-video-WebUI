"""Integration test: QualityAssessor on existing workspace."""
import sys, os, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

from pipeline.quality_assessor import QualityAssessor

ws = "source_file/test_project"
assessor = QualityAssessor(
    ws_dir=ws, semantic_threshold=0.70,
    naturalness_threshold=3.0, naturalness_enabled=True,
    source_lang="ja",
)
report = assessor.run()

if not report:
    print("FAIL: empty report")
    sys.exit(1)

s = report["summary"]
print(f"\nQuality Report Summary:")
print(f"  Total: {s['total']}")
print(f"  PASS: {s['tier_pass']}  GLANCE: {s['tier_glance']}  REVIEW: {s['tier_review']}  CRITICAL: {s['tier_critical']}")
print(f"  PPL Baseline: {s['naturalness_baseline_ppl']}")
print(f"  Coverage: {s['dimension_coverage']}")

for e in report["entries"][:3]:
    print(f"\n  #{e['index']} tier={e['tier']} reason={e['tierReason']}")
    for dim in ["semantic", "naturalness", "structural"]:
        d = e["scores"][dim]
        print(f"    {dim}: value={d['value']} flagged={d['flagged']} {d.get('detail','')}")

qr_path = os.path.join(ws, "02_translate", "quality_report.json")
if os.path.isfile(qr_path):
    print(f"\nquality_report.json: {os.path.getsize(qr_path)} bytes ✓")
else:
    print(f"\nFAIL: not found at {qr_path}")
    sys.exit(1)

print("\nPASS")
