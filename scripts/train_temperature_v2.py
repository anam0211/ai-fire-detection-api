"""Train a versioned candidate from normal sessions; --demo is explicitly synthetic."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import IsolationForest
from sklearn.model_selection import GroupShuffleSplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from risk_v2.engine import FEATURE_NAMES, MODEL_FILE, SKLEARN_VERSION, WINDOW, features


def demo_sessions(seed=20261109):
    """A development distribution, not measured fire/non-fire observations."""
    rng = np.random.default_rng(seed)
    sessions = {}
    for index in range(160):
        t = np.arange(180, dtype=float)
        # Explicit kitchen demo assumption: stable/slowly varying ambient heat can
        # be normal up to about 60 C. This range must be replaced by actual logs.
        base = rng.uniform(18, 60)
        slope = rng.uniform(-0.006, 0.006)
        temp = (base + slope * t + rng.uniform(0.02, 0.25) * np.sin(t / rng.uniform(8, 30))
                + rng.normal(0, rng.uniform(0.02, 0.12), len(t)))
        sessions[f"synthetic_normal_{index:03d}"] = [
            (float(time), float(value), True) for time, value in zip(t, temp)
        ]
    return sessions


def read_sessions(path, normal_only=False):
    sessions = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"session_id", "timestamp_ms", "temperature", "infrared"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("CSV needs session_id,timestamp_ms,temperature,infrared")
        if "label" not in reader.fieldnames and not normal_only:
            raise ValueError("CSV needs label, or --normal-only to explicitly attest normal recordings")
        for number, row in enumerate(reader, 2):
            session = row["session_id"].strip()
            timestamp, temperature = float(row["timestamp_ms"]) / 1000, float(row["temperature"])
            ir = int(row["infrared"])
            label = row.get("label", "normal").strip().lower()
            if (not session or not np.isfinite([timestamp, temperature]).all()
                    or timestamp < 0 or not -40 <= temperature <= 125
                    or row["infrared"].strip() not in ("0", "1")
                    or label not in ("normal", "abnormal", "fire", "warning")):
                raise ValueError(f"Invalid CSV row {number}")
            # IR=1 can be intentional stove flame. Temperature-only features do
            # not learn IR as a fire label; normal/abnormal labels need review.
            sessions.setdefault(session, []).append((timestamp, temperature, label == "normal"))
    for name, values in sessions.items():
        values.sort(key=lambda row: row[0])
        if any(b[0] <= a[0] for a, b in zip(values, values[1:])):
            raise ValueError(f"Duplicate timestamp in session {name}")
    return sessions


def training_windows(sessions):
    rows, groups = [], []
    for name, values in sessions.items():
        chunk = []
        for row in values:
            # Match the intended 1 Hz input; never splice across gaps or abnormal rows.
            if not row[2] or (chunk and not 0.5 <= row[0] - chunk[-1][0] <= 2.0):
                chunk = []
            if not row[2]:
                continue
            chunk.append(row)
            if len(chunk) == WINDOW:
                rows.append(features([sample[1] for sample in chunk])[0])
                groups.append(name)
                chunk = []
    if len(rows) < 60 or len(set(groups)) < 6:
        raise ValueError("Need >=60 normal windows from >=6 independent recording sessions")
    return np.asarray(rows, dtype=np.float32), np.asarray(groups)


def train(sessions, provenance, seed=20261109):
    if sklearn.__version__ != SKLEARN_VERSION:
        raise RuntimeError(f"Use scikit-learn {SKLEARN_VERSION}, got {sklearn.__version__}")
    x, groups = training_windows(sessions)
    split = GroupShuffleSplit(n_splits=1, test_size=0.4, random_state=seed)
    train_idx, remaining = next(split.split(x, groups=groups))
    split2 = GroupShuffleSplit(n_splits=1, test_size=0.5, random_state=seed + 1)
    calibration, test = next(split2.split(x[remaining], groups=groups[remaining]))
    calibration_idx, test_idx = remaining[calibration], remaining[test]
    group_sets = [set(groups[index]) for index in (train_idx, calibration_idx, test_idx)]
    assert not (group_sets[0] & group_sets[1] or group_sets[0] & group_sets[2] or group_sets[1] & group_sets[2])
    model = IsolationForest(n_estimators=200, max_samples=256, contamination="auto",
                            random_state=seed, n_jobs=1).fit(x[train_idx])
    # Calibrate only on separate normal sessions. The held-out test is never used to tune offset.
    model.offset_ = float(np.quantile(model.score_samples(x[calibration_idx]), 0.02))
    artifact = {
        "model": model, "model_version": "temperature-v2-" + provenance,
        "feature_names": FEATURE_NAMES, "window_size": WINDOW, "sample_period_ms": 1000,
        "sklearn_version": SKLEARN_VERSION, "provenance": provenance,
        "random_seed": seed,
        "demo_context": "near_heat_source" if provenance == "synthetic_demo" else None,
    }
    metrics = {
        "provenance": provenance, "field_validated": False, "seed": seed,
        "features": FEATURE_NAMES, "normal_only_training": True,
        "calibration_target_normal_false_positive_rate": 0.02,
        "splits": {},
        "limitations": ["No measured fire recall or precision without independent labeled abnormal sessions.",
                        "Anomaly score is not fire probability; thermal/IR policy is evaluated separately.",
                        "Session separation prevents window leakage; independent real recordings are still required."],
    }
    for name, idx in (("train", train_idx), ("calibration", calibration_idx), ("test", test_idx)):
        metrics["splits"][name] = {
            "sessions": sorted(set(groups[idx])), "windows": len(idx),
            "normal_false_positive_rate": float(np.mean(model.predict(x[idx]) == -1)),
            "temperature_mean_min_c": float(x[idx, 0].min()),
            "temperature_mean_max_c": float(x[idx, 0].max()),
        }
    return artifact, metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--demo", action="store_true", help="Generate explicitly synthetic normal sessions")
    source.add_argument("--csv", type=Path, help="Private measured sensor CSV")
    parser.add_argument("--normal-only", action="store_true", help="Attest an unlabeled CSV contains only normal sessions")
    parser.add_argument("--output", type=Path, default=MODEL_FILE)
    parser.add_argument("--overwrite-candidate", action="store_true")
    args = parser.parse_args()
    target = args.output.resolve()
    if target.name == "model.joblib":
        raise ValueError("Refusing to overwrite the original model.joblib; use a versioned candidate filename")
    if target.exists() and not args.overwrite_candidate:
        raise ValueError("Candidate already exists; use a different output or --overwrite-candidate")
    provenance = "synthetic_demo" if args.demo else "real_sensor_data"
    sessions = demo_sessions() if args.demo else read_sessions(args.csv, args.normal_only)
    artifact, metrics = train(sessions, provenance)
    if args.csv:
        metrics["input_sha256"] = hashlib.sha256(args.csv.read_bytes()).hexdigest()
    target.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, target, compress=3)
    metrics["artifact_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    report = target.with_suffix(".training.json")
    report.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"artifact": str(target), "provenance": provenance,
                      "held_out_normal_fpr": metrics["splits"]["test"]["normal_false_positive_rate"],
                      "field_validated": False, "report": str(report)}, indent=2))


if __name__ == "__main__":
    main()
