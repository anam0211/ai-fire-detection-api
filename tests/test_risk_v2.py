"""Behavioral tests for the temperature/IR API and its public backend contract."""

import csv

from fastapi.testclient import TestClient
import numpy as np
import pytest

from risk_v2 import api as candidate_api
from risk_v2.engine import ModelUnavailable, Policy, RiskEngine, load_artifact, load_policy
from scripts.evaluate_risk_v2 import evaluate
from scripts.train_temperature_v2 import demo_sessions, read_sessions, train, training_windows

TEST_KEY = "test-only-v2-key-do-not-use-in-production-123456"
HEADERS = {"X-API-Key": TEST_KEY}


@pytest.fixture
def engine():
    return RiskEngine(load_artifact())


def series(engine, temperatures, ir=0, start=0, step=1, device="a"):
    for index, temperature in enumerate(temperatures):
        result = engine.process(device, float(temperature), ir, start + index * step)
    return result


def test_frozen_original_and_all_synthetic_scenarios():
    report = evaluate()
    assert report["original_model_sha256"] == "9986dbd0f66591b8a406a0450fad0ddc83fd726155ec650d9638ff4a90637bd2"
    assert report["passed"] == report["total"]
    assert report["field_validated"] is False


@pytest.mark.parametrize("temperature,level", [(64.99, "UNKNOWN"), (65, "MEDIUM"),
                                               (84.99, "MEDIUM"), (85, "HIGH"), (100, "HIGH"), (120, "HIGH")])
def test_thermal_warning_does_not_wait_for_model(engine, temperature, level):
    result = engine.process("new", temperature, 0, 0)
    assert result["risk_level"] == level
    assert result["ai"]["ready"] is False
    assert result["alarm_suggested"] is (level in ("MEDIUM", "HIGH"))


def test_ir_needs_timed_confirmation_and_heat_for_high(engine):
    assert engine.process("a", 78, 1, 0)["risk_level"] == "MEDIUM"
    assert engine.process("a", 78, 1, 0.1)["risk_level"] == "MEDIUM"
    assert engine.process("a", 78, 1, 0.2)["risk_level"] == "MEDIUM"
    assert engine.process("a", 78, 1, 2)["risk_level"] == "HIGH"
    result = series(engine, [29.2] * 10, ir=1, device="room")
    assert result["risk_level"] == "LOW"
    assert result["alarm_suggested"] is False


def test_network_burst_cannot_fake_temperature_rate(engine):
    burst = series(engine, np.linspace(30, 33, 10), step=0.01)
    assert burst["assessment"]["temperature_rise_c_per_min"] is None
    assert burst["risk_level"] == "LOW"
    realistic = series(engine, np.linspace(30, 33, 10), device="b")
    assert realistic["risk_level"] == "MEDIUM"
    assert realistic["assessment"]["temperature_rise_c_per_min"] == pytest.approx(20)


def test_one_small_sensor_jump_is_not_a_rapid_heat_alarm(engine):
    result = series(engine, [30] * 9 + [30.6])
    assert "RAPID_TEMPERATURE_RISE" not in result["assessment"]["reasons"]
    assert result["alarm_suggested"] is False


def test_ir_flicker_does_not_latch_high(engine):
    series(engine, [78, 78], ir=1)
    engine.process("a", 78, 0, 2)
    result = engine.process("a", 78, 1, 3)
    assert result["risk_level"] == "MEDIUM"
    assert "IR_UNCONFIRMED" in result["assessment"]["reasons"]


def test_cooling_requires_duration_and_samples(engine):
    assert engine.process("a", 100, 0, 0)["risk_level"] == "HIGH"
    assert engine.process("a", 60, 0, 1)["status"] == "RECOVERY_HOLD"
    assert engine.process("a", 50, 0, 2)["risk_level"] == "HIGH"
    assert engine.process("a", 50, 0, 3)["risk_level"] == "HIGH"
    assert engine.process("a", 50, 0, 6.9)["risk_level"] == "HIGH"
    result = engine.process("a", 50, 0, 7)
    assert result["risk_level"] == "UNKNOWN"
    assert "COOLING_CONFIRMED" in result["assessment"]["reasons"]


def test_renewed_hazard_resets_cooling(engine):
    engine.process("a", 100, 0, 0)
    engine.process("a", 30, 0, 1)
    engine.process("a", 30, 0, 2)
    engine.process("a", 100, 0, 3)
    assert engine.process("a", 30, 0, 6)["risk_level"] == "HIGH"
    assert engine.devices["a"].clear_since == 6


def test_state_and_recovery_are_isolated_per_device(engine):
    engine.process("hot", 100, 0, 0)
    result = series(engine, [29.2] * 10, device="room")
    assert result["risk_level"] == "LOW"
    assert engine.devices["hot"].risk == "HIGH"
    assert len(engine.devices["hot"].samples) == 1


def test_offline_resets_ir_confirmation_model_window_and_latch(engine):
    series(engine, [78, 78, 78], ir=1)
    result = engine.process("a", 29.2, 1, 12)
    assert result["risk_level"] == "LOW"
    assert result["ai"]["ready"] is False
    assert len(engine.devices["a"].samples) == 1
    assert "IR_UNCONFIRMED" in result["assessment"]["reasons"]


@pytest.mark.parametrize("bad", [np.array([np.nan]), np.array([np.inf]), np.array([0, 1])])
def test_model_failure_does_not_hide_thermal_alarm_or_append_failed_sample(engine, monkeypatch, bad):
    series(engine, [29.2] * 9)
    original = engine.model.decision_function
    monkeypatch.setattr(engine.model, "decision_function", lambda _: bad)
    with pytest.raises(ModelUnavailable):
        engine.process("a", 29.2, 0, 9)
    assert len(engine.devices["a"].samples) == 9
    assert engine.model_error is True
    hot = engine.process("a", 100, 0, 9)
    assert hot["risk_level"] == "HIGH"
    assert hot["ai"]["result"] == "MODEL_ERROR"
    assert hot["ai"]["score"] is None
    assert hot["alarm_suggested"] is True
    monkeypatch.setattr(engine.model, "decision_function", original)
    engine.process("a", 100, 0, 10)
    assert engine.model_error is False


def test_unconfirmed_ai_anomaly_is_evidence_not_fire_risk(engine):
    result = series(engine, [10] * 10)
    assert result["ai"]["result"] == "ANOMALY"
    assert result["risk_level"] == "LOW"
    assert result["alarm_suggested"] is False


def test_policy_rejects_invalid_order_and_nonfinite_thresholds():
    config = load_policy().model_dump()
    with pytest.raises(ValueError):
        Policy.model_validate({**config, "danger_temperature_c": 40})
    with pytest.raises(ValueError):
        Policy.model_validate({**config, "rise_warning_c_per_min": float("nan")})


@pytest.mark.parametrize("temperature,ir,expected", [
    (29.2, 1, "LOW"), (55, 1, "LOW"), (60, 0, "LOW"),
    (64.99, 0, "LOW"), (65, 0, "MEDIUM"), (65, 1, "MEDIUM"),
    (74.99, 1, "MEDIUM"), (75, 1, "HIGH"), (84.99, 0, "MEDIUM"),
    (85, 0, "HIGH"), (100, 0, "HIGH"), (120, 0, "HIGH"),
])
def test_kitchen_demo_profile_separates_cooking_from_thermal_hazard(temperature, ir, expected):
    engine = RiskEngine(load_artifact())
    result = series(engine, [temperature] * 10, ir=ir)
    assert result["risk_level"] == expected
    assert result["alarm_suggested"] is (expected in ("MEDIUM", "HIGH"))
    assert result["assessment"]["policy_version"] == "near-heat-demo-v2"


def test_kitchen_ir_does_not_turn_moderate_rise_at_room_temperature_into_high():
    engine = RiskEngine(load_artifact())
    result = series(engine, np.linspace(30, 33, 10), ir=1)
    assert result["risk_level"] == "MEDIUM"
    assert "PERSISTENT_IR_WITH_HEAT" not in result["assessment"]["reasons"]


def test_kitchen_high_clears_after_sustained_cooling():
    engine = RiskEngine(load_artifact())
    engine.process("a", 100, 0, 0)
    for second in range(1, 6):
        assert engine.process("a", 50, 0, second)["risk_level"] == "HIGH"
    assert engine.process("a", 50, 0, 6)["risk_level"] == "UNKNOWN"


def test_kitchen_persistence_is_not_proved_by_burst_ir_requests():
    engine = RiskEngine(load_artifact())
    result = series(engine, [78] * 10, ir=1, step=0.01)
    assert result["risk_level"] == "MEDIUM"
    assert "IR_UNCONFIRMED" in result["assessment"]["reasons"]


def test_training_has_session_separation_and_no_fire_accuracy_claim():
    _, report = train(demo_sessions(), "synthetic_demo")
    sets = [set(part["sessions"]) for part in report["splits"].values()]
    assert not (sets[0] & sets[1] or sets[0] & sets[2] or sets[1] & sets[2])
    assert report["field_validated"] is False
    assert report["provenance"] == "synthetic_demo"
    assert report["splits"]["test"]["normal_false_positive_rate"] < 0.1


def test_training_cannot_bridge_abnormal_samples_or_network_gap():
    sessions = {f"s{i}": [(float(t), 29.2, True) for t in range(100)] for i in range(7)}
    sessions["s0"][9] = (9, 100, False)
    sessions["s1"] = [(float(t if t < 9 else t + 30), 29.2, True) for t in range(100)]
    x, groups = training_windows(sessions)
    assert len(x) == 68  # 9 + 9 + 5*10; two interrupted partial windows discarded.


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["session_id", "timestamp_ms", "temperature", "infrared", "label"])
        writer.writerows(rows)


def test_training_csv_allows_labeled_cooking_ir_and_rejects_duplicate_times(tmp_path):
    path = tmp_path / "sensor.csv"
    write_csv(path, [["a", 0, 29, 1, "normal"]])
    assert read_sessions(path)["a"][0][2] is True
    write_csv(path, [["a", 0, 29, 2, "normal"]])
    with pytest.raises(ValueError, match="Invalid"):
        read_sessions(path)
    write_csv(path, [["a", 0, 29, 0, "normal"], ["a", 0, 30, 0, "normal"]])
    with pytest.raises(ValueError, match="Duplicate"):
        read_sessions(path)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("API_KEY", TEST_KEY)
    monkeypatch.setenv("DASHBOARD_ORIGINS", "https://dashboard.example.com")
    with TestClient(candidate_api.create_app()) as value:
        yield value


def post(client, temperature=29.2, infrared=0, device="a"):
    return client.post("/api/v1/sensor-data", headers=HEADERS, json={
        "device_id": device, "temperature": temperature, "infrared": infrared,
    })


def test_v2_api_auth_contract_and_immediate_temperature_danger(client):
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/status/a").status_code == 401
    assert client.get("/api/v1/status/a", headers=HEADERS).status_code == 404
    result = post(client, 100).json()
    assert result["status"] == "THERMAL_DANGER"
    assert result["risk_level"] == "HIGH"
    assert result["ai"]["ready"] is False
    assert result["assessment"]["experimental"] is True
    assert result["assessment"]["training_provenance"] == "synthetic_demo"
    assert client.get("/api/v1/status/a", headers=HEADERS).json() == result
    schema = client.get("/openapi.json").json()
    assert "THERMAL_DANGER" in schema["components"]["schemas"]["SensorStatus"]["properties"]["status"]["enum"]


@pytest.mark.parametrize("temperature,infrared", [(float("inf"), 0), (126, 0), ("30", 0), (30, True), (30, 2)])
def test_v2_api_validation_does_not_commit(client, temperature, infrared):
    if not isinstance(temperature, float) or np.isfinite(temperature):
        response = post(client, temperature, infrared)
    else:
        response = client.post("/api/v1/sensor-data", headers=HEADERS,
                               content='{"device_id":"a","temperature":Infinity,"infrared":0}')
    assert response.status_code == 422
    assert client.app.state.engine.devices == {}


def test_v2_api_offline_and_reconnect(client, monkeypatch):
    post(client)
    last = client.app.state.latest["a"][0]
    monkeypatch.setattr(candidate_api.time, "monotonic", lambda: last + 10)
    assert client.get("/api/v1/status/a", headers=HEADERS).json()["online"] is False
    result = post(client).json()
    assert result["status"] == "COLLECTING"
    assert result["assessment"]["observation_seconds"] == 0


def test_v2_cors_rejects_unlisted_origin(client):
    headers = {"Origin": "https://unlisted.example.com", "Access-Control-Request-Method": "POST"}
    response = client.options("/api/v1/sensor-data", headers=headers)
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_public_entrypoint_uses_near_heat_profile(monkeypatch):
    import api
    monkeypatch.setenv("API_KEY", TEST_KEY)
    with TestClient(api.create_app()) as client:
        result = post(client, 29.2, 1).json()
        assert result["risk_level"] == "LOW"
        assert result["alarm_suggested"] is False
        assert result["assessment"]["policy_version"] == "near-heat-demo-v2"
        assert client.get("/openapi.json").json()["info"]["version"] == "2.0.0-demo"


@pytest.mark.parametrize("temperature,ir,duration,expected", [
    (29.2, 1, 20, "LOW"), (64.9, 1, 20, "LOW"),
    (65, 1, 0, "MEDIUM"), (74.9, 1, 20, "MEDIUM"),
    (75, 1, 2, "HIGH"), (85, 0, 0, "HIGH"),
])
def test_selected_backend_table(client, monkeypatch, temperature, ir, duration, expected):
    clock = [100.0]
    monkeypatch.setattr(candidate_api.time, "monotonic", lambda: clock[0])
    result = post(client, temperature, ir).json()
    for second in range(1, duration + 1):
        clock[0] += 1
        result = post(client, temperature, ir).json()
    assert result["risk_level"] == expected
    assert result["alarm_suggested"] is (expected in ("MEDIUM", "HIGH"))


def test_backend_fusion_below_75_requires_real_rise_and_time(client, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(candidate_api.time, "monotonic", lambda: clock[0])
    for i in range(7):
        result = post(client, 65 + i * 0.5, 1).json()
        if i < 5:
            assert result["risk_level"] == "MEDIUM"
        clock[0] += 1
    assert result["risk_level"] == "HIGH"
    assert "RAPID_TEMPERATURE_RISE" in result["assessment"]["reasons"]


def test_candidate_checksum_is_verified_before_loading(tmp_path):
    from risk_v2.engine import MODEL_FILE
    import json
    candidate = tmp_path / "candidate.joblib"
    candidate.write_bytes(MODEL_FILE.read_bytes() + b'tampered')
    candidate.with_suffix(".training.json").write_text(json.dumps({"artifact_sha256": "wrong"}))
    with pytest.raises(ValueError, match="checksum"):
        load_artifact(candidate)
