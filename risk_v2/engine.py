"""Anomaly evidence and explicit, provisional thermal rules are separate decisions."""

from collections import deque
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Literal

import joblib
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
import sklearn
from sklearn.ensemble import IsolationForest
from sklearn.utils.validation import check_is_fitted

ROOT = Path(__file__).resolve().parent
MODEL_FILE = ROOT / "model_candidate_v2.joblib"
WINDOW = 10
FEATURE_NAMES = ["temp_mean", "temp_max", "temp_change", "temp_std"]
SKLEARN_VERSION = "1.6.1"


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    version: str = Field(min_length=1)
    warning_temperature_c: float
    danger_temperature_c: float = Field(le=125)
    clear_temperature_c: float = Field(ge=-40)
    rise_warning_c_per_min: float = Field(gt=0)
    minimum_rise_c: float = Field(gt=0)
    minimum_observation_seconds: float = Field(gt=0)
    maximum_observation_seconds: float = Field(gt=0)
    ir_confirmation_samples: int = Field(ge=2, le=WINDOW)
    ir_confirmation_seconds: float = Field(gt=0)
    ir_only_risk: Literal["LOW", "MEDIUM"] = "MEDIUM"
    fusion_temperature_c: float = 45.0
    fusion_rise_c_per_min: float = Field(default=8.0, gt=0)
    ai_warning_min_temperature_c: float
    ai_warning_min_rise_c: float = Field(gt=0)
    ai_confirmation_samples: int = Field(ge=2)
    clear_samples: int = Field(ge=2)
    clear_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self):
        if not self.clear_temperature_c < self.warning_temperature_c < self.danger_temperature_c:
            raise ValueError("Require clear < warning < danger temperatures")
        if self.minimum_observation_seconds >= self.maximum_observation_seconds:
            raise ValueError("Require minimum observation < maximum observation")
        if not self.warning_temperature_c <= self.fusion_temperature_c < self.danger_temperature_c:
            raise ValueError("Require warning <= fusion < danger temperatures")
        return self


def load_policy(path=ROOT / "policy.json"):
    return Policy.model_validate_json(Path(path).read_text(encoding="utf-8"))


def features(temperatures):
    a = np.asarray(temperatures, dtype=np.float32)
    return np.array([[a.mean(), a.max(), a[-1] - a[0], a.std()]], dtype=np.float32)


def load_artifact(path=MODEL_FILE):
    if sklearn.__version__ != SKLEARN_VERSION:
        raise RuntimeError(f"Use scikit-learn {SKLEARN_VERSION}")
    path = Path(path)
    report = json.loads(path.with_suffix(".training.json").read_text(encoding="utf-8"))
    if hashlib.sha256(path.read_bytes()).hexdigest() != report["artifact_sha256"]:
        raise ValueError("Candidate model checksum does not match training report")
    artifact = joblib.load(path)
    if (artifact.get("sklearn_version") != SKLEARN_VERSION
            or artifact.get("feature_names") != FEATURE_NAMES
            or artifact.get("window_size") != WINDOW
            or not artifact.get("model_version")
            or artifact.get("provenance") not in ("synthetic_demo", "real_sensor_data")):
        raise ValueError("Incompatible v2 model metadata")
    model = artifact["model"]
    if not isinstance(model, IsolationForest) or model.n_features_in_ != len(FEATURE_NAMES):
        raise ValueError("Expected fitted v2 IsolationForest")
    check_is_fitted(model)
    score(model, [29.2] * WINDOW)
    return artifact


def score(model, temperatures):
    value = np.asarray(model.decision_function(features(temperatures)))
    if value.shape != (1,) or not np.isfinite(value).all():
        raise ValueError("Expected one finite anomaly score")
    return float(value[0])


class ModelUnavailable(RuntimeError):
    pass


@dataclass
class DeviceState:
    # (server monotonic timestamp, temperature, normalized IR)
    samples: deque = field(default_factory=lambda: deque(maxlen=WINDOW))
    risk: str = "UNKNOWN"
    anomaly_count: int = 0
    clear_since: float | None = None
    clear_count: int = 0


class RiskEngine:
    """Call under the API lock; failed decisions do not commit a sample."""

    def __init__(self, artifact, policy=None):
        self.artifact = artifact
        self.model = artifact["model"]
        self.policy = policy or load_policy()
        self.devices = {}
        self.model_error = False

    def process(self, device, temperature, infrared, now):
        p = self.policy
        old = self.devices.get(device, DeviceState())
        if old.samples and now - old.samples[-1][0] >= 10:
            old = DeviceState()
        if old.samples and now < old.samples[-1][0]:
            raise ValueError("Server monotonic time must not move backwards")
        samples = deque(old.samples, maxlen=WINDOW)
        samples.append((now, temperature, infrared))
        temps = [s[1] for s in samples]
        elapsed = now - samples[0][0]
        delta = temperature - temps[0]
        rate = None
        if p.minimum_observation_seconds <= elapsed <= p.maximum_observation_seconds:
            times = np.array([s[0] - samples[0][0] for s in samples], dtype=float)
            centered = times - times.mean()
            rate = float(np.dot(centered, np.array(temps) - np.mean(temps))
                         / np.dot(centered, centered) * 60)
        rapid = rate is not None and rate >= p.rise_warning_c_per_min and delta >= p.minimum_rise_c
        ready = len(samples) == WINDOW
        ai_score, ai_result = None, "INSUFFICIENT_DATA"
        if ready:
            try:
                ai_score = score(self.model, temps)
                ai_result = "ANOMALY" if ai_score < 0 else "NORMAL"
                self.model_error = False
            except Exception:
                self.model_error = True
                ai_result, ready = "MODEL_ERROR", False
        anomalies = old.anomaly_count + 1 if ai_result == "ANOMALY" else 0
        ai_warming = (anomalies >= p.ai_confirmation_samples
                      and temperature >= p.ai_warning_min_temperature_c
                      and delta >= p.ai_warning_min_rise_c
                      and rate is not None and rate > 0)
        trailing_ir = []
        for sample in reversed(samples):
            if sample[2] != 1:
                break
            trailing_ir.append(sample)
        confirmed_ir = (len(trailing_ir) >= p.ir_confirmation_samples
                        and now - trailing_ir[-1][0] >= p.ir_confirmation_seconds)
        warm = temperature >= p.warning_temperature_c
        reasons = []
        if temperature >= p.danger_temperature_c:
            risk, status, source = "HIGH", "THERMAL_DANGER", "THERMAL_RULE"
            reasons.append("HIGH_TEMPERATURE")
        elif confirmed_ir and (temperature >= p.fusion_temperature_c
                               or (warm and rapid and rate >= p.fusion_rise_c_per_min)):
            risk, status, source = "HIGH", "FLAME_SIGNAL", "SENSOR_FUSION"
            reasons.append("PERSISTENT_IR_WITH_HEAT")
        elif warm or rapid or ai_warming or (infrared == 1 and p.ir_only_risk == "MEDIUM"):
            risk = "MEDIUM"
            status = "FLAME_SIGNAL" if infrared else "THERMAL_WARNING" if warm or rapid else "ANOMALY"
            source = "SENSOR_FUSION" if infrared and (warm or rapid) else "DIRECT_SENSOR" if infrared else "THERMAL_RULE" if warm or rapid else "AI"
        else:
            risk = "LOW" if ready or infrared else "UNKNOWN"
            status = "FLAME_SIGNAL" if infrared else ai_result if ready else "COLLECTING"
            source = "DIRECT_SENSOR" if infrared else "AI" if ready else "SYSTEM"
        if warm:
            reasons.append("ELEVATED_TEMPERATURE")
        if rapid:
            reasons.append("RAPID_TEMPERATURE_RISE")
        if infrared:
            reasons.append("IR_CONFIRMED" if confirmed_ir else "IR_UNCONFIRMED")
            if not warm and not rapid and not ai_warming and p.ir_only_risk == "LOW":
                reasons.append("IR_ALONE_NEAR_EXPECTED_HEAT_SOURCE")
        if ai_result == "ANOMALY":
            reasons.append("AI_ANOMALY_WITH_WARMING" if ai_warming else "AI_ANOMALY_UNCORROBORATED")

        # Acknowledging sustained cooling prevents alarm flicker at the threshold.
        ranks = {"UNKNOWN": 0, "LOW": 0, "MEDIUM": 1, "HIGH": 2}
        clear_since, clear_count = None, 0
        if ranks[old.risk] > ranks[risk]:
            cooling = (temperature <= p.clear_temperature_c and not infrared
                       and not rapid and not ai_warming)
            if cooling:
                clear_since = old.clear_since if old.clear_since is not None else now
                clear_count = old.clear_count + 1
            cleared = (cooling and clear_count >= p.clear_samples
                       and now - clear_since >= p.clear_seconds)
            if not cleared:
                risk, status, source = old.risk, "RECOVERY_HOLD", "HYSTERESIS"
                reasons.append("RECOVERY_HOLD")
            else:
                reasons.append("COOLING_CONFIRMED")
        if ai_result == "MODEL_ERROR" and ranks[risk] == 0 and not infrared:
            raise ModelUnavailable("Model inference unavailable")
        self.devices[device] = DeviceState(samples, risk, anomalies, clear_since, clear_count)
        return {
            "status": status, "risk_level": risk, "source": source,
            "ai": {"model": "IsolationForest", "ready": ready,
                   "result": ai_result, "score": ai_score},
            "alarm_suggested": risk in ("MEDIUM", "HIGH"),
            "assessment": {
                "reasons": reasons or ["NO_CORROBORATED_HAZARD"],
                "temperature_rise_c_per_min": None if rate is None else round(rate, 4),
                "observation_seconds": round(elapsed, 4),
                "policy_version": p.version,
                "model_version": self.artifact["model_version"],
                "training_provenance": self.artifact["provenance"],
                "experimental": True,
            },
        }
