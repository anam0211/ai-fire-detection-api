from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib

from fastapi.testclient import TestClient
import numpy as np
import pytest

import legacy_api as api

# Public, non-production credentials used only by the tests.
TEST_KEY = "test-only-key-do-not-use-in-production-123456"
HEADERS = {"X-API-Key": TEST_KEY}
NORMAL_TEMPERATURES = [29.18, 29.18, 29.23, 29.24, 29.20, 29.20, 29.18, 29.18, 29.13, 29.14]
RESULT_KEYS = {
    "device_id", "status", "risk_level", "source", "sensors", "ai",
    "alarm_suggested", "timestamp", "online",
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("API_KEY", TEST_KEY)
    monkeypatch.setenv("DASHBOARD_ORIGINS", " https://dashboard.example.com, http://localhost:5173 ")
    with TestClient(api.create_app()) as test_client:
        yield test_client


def send(client, device="esp32_test", temperature=29.2, infrared=0):
    return client.post("/api/v1/sensor-data", headers=HEADERS, json={
        "device_id": device, "temperature": temperature, "infrared": infrared,
    })


def fill(client, device="esp32_test", temperatures=NORMAL_TEMPERATURES):
    responses = [send(client, device, temperature) for temperature in temperatures]
    assert all(response.status_code == 200 for response in responses)
    return [response.json() for response in responses]


def test_health_and_original_model(client):
    assert client.get("/health").json() == {"ok": True, "model": "IsolationForest", "window_size": 10}
    assert client.get("/health").status_code == 200
    assert api.sklearn.__version__ == "1.6.1"
    expected = (api.ROOT / "model.sha256").read_text().split()[0]
    assert hashlib.sha256(api.MODEL_FILE.read_bytes()).hexdigest() == expected


def test_normal_after_ten_real_model_samples(client):
    results = fill(client)
    for result in results[:9]:
        assert result["status"] == "COLLECTING"
        assert result["ai"] == {
            "model": "IsolationForest", "ready": False, "result": "INSUFFICIENT_DATA", "score": None,
        }
        assert result["alarm_suggested"] is False
    result = results[-1]
    assert set(result) == RESULT_KEYS
    assert (result["status"], result["risk_level"], result["source"]) == ("NORMAL", "LOW", "AI")
    assert result["ai"]["ready"] is True
    assert result["ai"]["result"] == "NORMAL"
    assert result["ai"]["score"] >= 0
    assert result["alarm_suggested"] is False
    assert datetime.fromisoformat(result["timestamp"]).utcoffset().total_seconds() == 0
    assert client.get("/api/v1/status/esp32_test", headers=HEADERS).json() == result


def test_anomaly_uses_real_model(client):
    fill(client)
    result = send(client, temperature=120).json()
    assert (result["status"], result["risk_level"], result["source"]) == ("ANOMALY", "MEDIUM", "AI")
    assert result["ai"]["score"] < 0
    assert result["alarm_suggested"] is True
    assert "FIRE" not in result["status"]


@pytest.mark.parametrize("warmup", [False, True])
def test_flame_signal_has_direct_sensor_priority(client, warmup):
    if warmup:
        fill(client)
    result = send(client, infrared=1).json()
    assert (result["status"], result["risk_level"], result["source"]) == ("FLAME_SIGNAL", "HIGH", "DIRECT_SENSOR")
    assert result["alarm_suggested"] is True
    assert result["ai"]["ready"] is warmup


@pytest.mark.parametrize("field,value", [
    ("temperature", -40.1), ("temperature", 125.1), ("temperature", "30"),
    ("temperature", True), ("temperature", None),
    ("infrared", -1), ("infrared", 2), ("infrared", 0.5),
    ("infrared", 1.0), ("infrared", "1"), ("infrared", True), ("infrared", None),
    ("device_id", ""), ("device_id", "a" * 65), ("device_id", "bad/id"), ("device_id", "device with spaces"),
])
def test_invalid_payload_does_not_add_history(client, field, value):
    payload = {"device_id": "invalid", "temperature": 30.0, "infrared": 0, field: value}
    response = client.post("/api/v1/sensor-data", headers=HEADERS, json=payload)
    assert response.status_code == 422
    assert "detail" in response.json()
    assert client.app.state.history == {}


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_temperature_is_422_not_500(client, value):
    response = client.post("/api/v1/sensor-data", headers={**HEADERS, "Content-Type": "application/json"},
                           content='{"device_id":"invalid","temperature":' + value + ',"infrared":0}')
    assert response.status_code == 422
    assert response.json()["detail"]


@pytest.mark.parametrize("payload", [{}, {"device_id": "missing"}, {"temperature": 30, "infrared": 0}])
def test_missing_fields(client, payload):
    assert client.post("/api/v1/sensor-data", headers=HEADERS, json=payload).status_code == 422


def test_malformed_json(client):
    assert client.post("/api/v1/sensor-data", headers={**HEADERS, "Content-Type": "application/json"},
                       content="{bad json").status_code == 422


@pytest.mark.parametrize("temperature", [-40, 125])
def test_temperature_bounds_are_inclusive(client, temperature):
    assert send(client, temperature=temperature).status_code == 200


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong-key"}])
def test_authentication_required_for_both_data_endpoints(client, headers):
    assert client.post("/api/v1/sensor-data", headers=headers, json={
        "device_id": "auth", "temperature": 30, "infrared": 0,
    }).status_code == 401
    assert client.get("/api/v1/status/auth", headers=headers).status_code == 401
    assert client.app.state.history == {}


def test_two_interleaved_devices_and_sliding_window(client):
    for i, temperature in enumerate(NORMAL_TEMPERATURES):
        a = send(client, "device_a", temperature).json()
        if i < 5:
            b = send(client, "device_b", 100).json()
            assert b["status"] == "COLLECTING"
    assert a["status"] == "NORMAL"
    assert client.get("/api/v1/status/device_b", headers=HEADERS).json()["ai"]["ready"] is False
    for _ in range(5):
        b = send(client, "device_b", 100).json()
    # Do not invent a high-temperature rule: this frozen model can classify a flat 100 C window as NORMAL.
    assert b["ai"]["score"] == pytest.approx(api.model_score(client.app.state.model, [(100, 0)] * 10))
    assert b["ai"]["ready"] is True
    assert client.get("/api/v1/status/device_a", headers=HEADERS).json() == a
    send(client, "device_a", 120)
    assert list(client.app.state.history["device_a"]) == [(t, 0) for t in NORMAL_TEMPERATURES[1:]] + [(120, 0)]
    assert list(client.app.state.history["device_b"]) == [(100, 0)] * 10


def test_concurrent_devices_keep_separate_windows(client):
    def transmit(device):
        return fill(client, device)[-1]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(transmit, ["parallel_a", "parallel_b"]))
    assert all(result["status"] == "NORMAL" for result in results)
    assert all(len(client.app.state.history[device]) == 10 for device in ["parallel_a", "parallel_b"])


def test_offline_boundary_and_unknown_device(client, monkeypatch):
    assert client.get("/api/v1/status/unknown", headers=HEADERS).status_code == 404
    assert client.get("/api/v1/status/invalid!", headers=HEADERS).status_code == 422
    send(client)
    last_time = client.app.state.latest["esp32_test"][0]
    monkeypatch.setattr(api.time, "monotonic", lambda: last_time + 9.99)
    assert client.get("/api/v1/status/esp32_test", headers=HEADERS).json()["online"] is True
    monkeypatch.setattr(api.time, "monotonic", lambda: last_time + 10)
    assert client.get("/api/v1/status/esp32_test", headers=HEADERS).json()["online"] is False


@pytest.mark.parametrize("gap", [10, 60])
@pytest.mark.parametrize("infrared", [0, 1])
def test_reconnecting_device_collects_a_fresh_window(client, monkeypatch, gap, infrared):
    fill(client, "reconnecting")
    other = fill(client, "other_device")[-1]
    last_time = client.app.state.latest["reconnecting"][0]
    monkeypatch.setattr(api.time, "monotonic", lambda: last_time + gap)

    result = send(client, "reconnecting", 120, infrared).json()
    assert result["status"] == ("FLAME_SIGNAL" if infrared else "COLLECTING")
    assert result["ai"] == {
        "model": "IsolationForest", "ready": False, "result": "INSUFFICIENT_DATA", "score": None,
    }
    assert list(client.app.state.history["reconnecting"]) == [(120, infrared)]
    assert client.app.state.latest["other_device"][1] == other
    assert len(client.app.state.history["other_device"]) == 10
    for index in range(9):
        result = send(client, "reconnecting", 120, infrared).json()
        assert result["ai"]["ready"] is (index == 8)


def test_short_gap_keeps_current_window(client, monkeypatch):
    fill(client)
    last_time = client.app.state.latest["esp32_test"][0]
    monkeypatch.setattr(api.time, "monotonic", lambda: last_time + 9.99)
    result = send(client, temperature=120).json()
    assert result["ai"]["ready"] is True
    assert result["status"] == "ANOMALY"
    assert len(client.app.state.history["esp32_test"]) == 10


@pytest.mark.parametrize("temperatures", [[29.2] * 10, [100] * 10, [120] * 10, [29.2] * 9 + [120]])
def test_api_preserves_original_model_prediction(client, temperatures):
    # Compare the API with direct artifact inference, including the model's known false negatives.
    result = fill(client, temperatures=temperatures)[-1]
    samples = np.array([(temperature, 0) for temperature in temperatures], dtype=np.float32)
    temp, ir = samples[:, 0], samples[:, 1]
    features = np.array([[temp.mean(), temp.max(), temp[-1] - temp[0], ir.mean()]], dtype=np.float32)
    model = client.app.state.model
    score = float(model.decision_function(features)[0])
    predicted = "ANOMALY" if model.predict(features)[0] == -1 else "NORMAL"
    assert result["ai"]["score"] == pytest.approx(score)
    assert result["ai"]["result"] == predicted
    assert result["status"] == predicted


def test_cors_preflight_and_error_response(client):
    headers = {"Origin": "https://dashboard.example.com", "Access-Control-Request-Method": "POST",
               "Access-Control-Request-Headers": "content-type,x-api-key"}
    allowed = client.options("/api/v1/sensor-data", headers=headers)
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == headers["Origin"]
    denied = client.options("/api/v1/sensor-data", headers={**headers, "Origin": "https://unlisted.example.com"})
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers
    unauthorized = client.get("/api/v1/status/a", headers={"Origin": headers["Origin"]})
    assert unauthorized.status_code == 401
    assert unauthorized.headers["access-control-allow-origin"] == headers["Origin"]


@pytest.mark.parametrize("failure", [RuntimeError("test internal failure"), np.array([np.nan]), np.array([np.inf]), np.array([0, 1])])
def test_model_error_rollback_direct_ir_and_recovery(client, monkeypatch, failure):
    fill(client, temperatures=NORMAL_TEMPERATURES[:9])
    original = client.app.state.model.decision_function

    def broken(_):
        if isinstance(failure, Exception):
            raise failure
        return failure

    monkeypatch.setattr(client.app.state.model, "decision_function", broken)
    failed = send(client)
    assert failed.status_code == 503
    assert failed.json() == {"detail": "Model inference unavailable"}
    assert len(client.app.state.history["esp32_test"]) == 9
    assert client.get("/health").status_code == 503
    direct = send(client, infrared=1).json()
    assert set(direct) == RESULT_KEYS
    assert direct["status"] == "FLAME_SIGNAL"
    assert direct["alarm_suggested"] is True
    assert direct["ai"] == {"model": "IsolationForest", "ready": False, "result": "MODEL_ERROR", "score": None}
    monkeypatch.setattr(client.app.state.model, "decision_function", original)
    assert send(client).status_code == 200
    assert client.get("/health").status_code == 200


def test_model_path_is_independent_of_cwd(client, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert api.MODEL_FILE.is_absolute()
    assert isinstance(api.load_model(), api.IsolationForest)


@pytest.mark.parametrize("corruption", ["missing", "unreadable", "features", "window", "version", "runtime"])
def test_model_initialization_errors_are_clear(client, monkeypatch, corruption, tmp_path):
    artifact = api.joblib.load(api.MODEL_FILE)
    if corruption == "missing":
        monkeypatch.setattr(api, "MODEL_FILE", tmp_path / "missing.joblib")
    elif corruption == "unreadable":
        def broken_load(_):
            raise ValueError("unreadable artifact")
        monkeypatch.setattr(api.joblib, "load", broken_load)
    elif corruption == "runtime":
        monkeypatch.setattr(api.sklearn, "__version__", "1.9.1")
    else:
        key = {"features": "feature_names", "window": "window_size", "version": "sklearn_version"}[corruption]
        artifact[key] = {"features": ["wrong"], "window": 9, "version": "1.5.0"}[corruption]
        monkeypatch.setattr(api.joblib, "load", lambda _: artifact)
    with pytest.raises(RuntimeError, match="Model initialization failed"):
        api.load_model()


@pytest.mark.parametrize("key", [None, "", "short", " " + TEST_KEY])
def test_missing_or_weak_api_key_fails_startup(monkeypatch, key):
    if key is None:
        monkeypatch.delenv("API_KEY", raising=False)
    else:
        monkeypatch.setenv("API_KEY", key)
    with pytest.raises(RuntimeError, match="API_KEY"):
        with TestClient(api.create_app()):
            pass


@pytest.mark.parametrize("origin", ["*", "https://dashboard.example.com/", "https://dashboard.example.com/path", "file://local"])
def test_invalid_cors_configuration_fails(monkeypatch, origin):
    monkeypatch.setenv("DASHBOARD_ORIGINS", origin)
    with pytest.raises(RuntimeError, match="DASHBOARD_ORIGINS"):
        api.create_app()


def test_openapi_advertises_api_key(client):
    schema = client.get("/openapi.json").json()
    assert schema["components"]["securitySchemes"]["APIKeyHeader"]["name"] == "X-API-Key"
    for path in ["/api/v1/sensor-data", "/api/v1/status/{device_id}"]:
        operation = next(iter(schema["paths"][path].values()))
        assert operation["security"] == [{"APIKeyHeader": []}]


def test_openapi_documents_the_response_contract(client):
    schema = client.get("/openapi.json").json()
    expected = "#/components/schemas/SensorStatus"
    for path, method in [("/api/v1/sensor-data", "post"), ("/api/v1/status/{device_id}", "get")]:
        response = schema["paths"][path][method]["responses"]["200"]
        assert response["content"]["application/json"]["schema"]["$ref"] == expected
    status = schema["components"]["schemas"]["SensorStatus"]
    assert set(status["required"]) == RESULT_KEYS
    assert status["properties"]["status"]["enum"] == ["COLLECTING", "NORMAL", "ANOMALY", "FLAME_SIGNAL"]
    assert "MODEL_ERROR" in schema["components"]["schemas"]["AIResult"]["properties"]["result"]["enum"]
