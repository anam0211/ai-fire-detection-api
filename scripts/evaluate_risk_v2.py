"""Compare the frozen v1 model/policy with v2 on explicit synthetic scenarios."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import legacy_api as v1
from risk_v2.engine import RiskEngine, load_artifact


def scenarios():
    return [
        ("room_29", [29.2] * 10, [0] * 10, "LOW"),
        ("warm_room_38", [38.0] * 10, [0] * 10, "LOW"),
        ("stable_45", [45.0] * 10, [0] * 10, "LOW"),
        ("cooking_55_with_ir", [55.0] * 10, [1] * 10, "LOW"),
        ("stable_60_no_ir", [60.0] * 10, [0] * 10, "LOW"),
        ("stable_65_no_ir", [65.0] * 10, [0] * 10, "MEDIUM"),
        ("stable_85_no_ir", [85.0] * 10, [0] * 10, "HIGH"),
        ("stable_100_no_ir", [100.0] * 10, [0] * 10, "HIGH"),
        ("stable_120_no_ir", [120.0] * 10, [0] * 10, "HIGH"),
        ("single_ir_room", [29.2], [1], "LOW"),
        ("persistent_ir_room", [29.2] * 10, [1] * 10, "LOW"),
        ("ir_plus_mild_heat", [48.0] * 10, [1] * 10, "LOW"),
        ("ir_plus_65_heat", [65.0] * 10, [1] * 10, "MEDIUM"),
        ("ir_plus_78_heat", [78.0] * 10, [1] * 10, "HIGH"),
        ("rapid_rise_no_ir", list(np.linspace(30, 33, 10)), [0] * 10, "MEDIUM"),
        ("rapid_rise_plus_ir_low_temp", list(np.linspace(30, 33, 10)), [1] * 10, "MEDIUM"),
        ("rapid_rise_plus_ir_high_temp", list(np.linspace(65, 69, 10)), [1] * 10, "HIGH"),
        ("falling_temperature", list(np.linspace(33, 30, 10)), [0] * 10, "LOW"),
        ("cold_room", [10.0] * 10, [0] * 10, "LOW"),
        ("small_noise", [30.0, 30.2, 29.9, 30.1, 30.0, 30.1, 29.8, 30.0, 30.1, 30.0], [0] * 10, "LOW"),
        ("sudden_120", [29.2] * 9 + [120.0], [0] * 10, "HIGH"),
    ]


def evaluate():
    original, artifact = v1.load_model(), load_artifact()
    results = []
    for name, temperatures, irs, expected in scenarios():
        old_score = v1.model_score(original, list(zip(temperatures, irs))) if len(temperatures) == 10 else None
        # Preserve the actual v1 branch order.
        old_risk = ("HIGH" if irs[-1] else "MEDIUM" if old_score is not None and old_score < 0
                    else "LOW" if old_score is not None else "UNKNOWN")
        engine = RiskEngine(artifact)
        for index, (temperature, ir) in enumerate(zip(temperatures, irs)):
            decision = engine.process(name, float(temperature), ir, float(index))
        results.append({"scenario": name, "input_last_temperature_c": temperatures[-1],
                        "input_last_ir": irs[-1], "v1_risk": old_risk, "v1_score": old_score,
                        "v2_risk": decision["risk_level"], "v2_score": decision["ai"]["score"],
                        "expected_demo_risk": expected, "passed": decision["risk_level"] == expected,
                        "reasons": decision["assessment"]["reasons"]})
    return {
        "synthetic_scenarios_only": True, "field_validated": False,
        "policy_version": "near-heat-demo-v2",
        "original_model_sha256": hashlib.sha256(v1.MODEL_FILE.read_bytes()).hexdigest(),
        "model_version": artifact["model_version"], "scenarios": results,
        "passed": sum(row["passed"] for row in results), "total": len(results),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "risk_v2" / "evaluation.json")
    args = parser.parse_args()
    report = evaluate()
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for row in report["scenarios"]:
        print(f"{row['scenario']}: v1={row['v1_risk']} -> v2={row['v2_risk']} {'PASS' if row['passed'] else 'FAIL'}")
    print(f"Synthetic policy scenarios passed: {report['passed']}/{report['total']}; not field accuracy")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
