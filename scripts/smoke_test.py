"""Exercise a running API over real HTTP(S). Only the Python standard library is needed."""

import argparse
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

NORMAL = [29.18, 29.18, 29.23, 29.24, 29.20, 29.20, 29.18, 29.18, 29.13, 29.14]
KEYS = {"device_id", "status", "risk_level", "source", "sensors", "ai", "alarm_suggested", "timestamp", "online", "assessment"}


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("API_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--timeout", type=float, default=120, help="Seconds per request (allows cold starts)")
    parser.add_argument("--interval", type=float, default=0, help="Seconds between sensor samples; use 1 for realistic cadence")
    parser.add_argument("--check-offline", action="store_true", help="Also wait 10.2 seconds and test online=false")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    parsed = urlsplit(base)
    check(parsed.scheme in ("http", "https") and bool(parsed.hostname), "Invalid base URL")
    check(not parsed.query and not parsed.fragment and not parsed.username and not parsed.password, "Use a base URL without credentials, query or fragment")
    check(args.timeout > 0 and args.interval >= 0, "Timeout must be positive; interval must not be negative")
    key = os.getenv("API_KEY", "")
    check(bool(key), "Set API_KEY in the environment; do not put it in a command-line argument")

    def call(method, path, payload=None, expected=200, authenticated=True, extra_headers=None):
        headers = {"Accept": "application/json", **(extra_headers or {})}
        if authenticated:
            headers["X-API-Key"] = key
        data = None
        if payload is not None:
            data = json.dumps(payload, allow_nan=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(base + path, method=method, data=data, headers=headers)
        try:
            with urlopen(request, timeout=args.timeout) as response:
                code, body, response_headers = response.status, response.read(), response.headers
        except HTTPError as exc:
            code, body, response_headers = exc.code, exc.read(), exc.headers
        check(code == expected, f"{method} {path}: expected HTTP {expected}, received {code}")
        return json.loads(body) if body else {}, response_headers

    prefix = "smoke_" + uuid4().hex[:12]
    normal_id, other_id = prefix + "_normal", prefix + "_other"

    def post(device, temperature, infrared=0, *, pause=True):
        result, _ = call("POST", "/api/v1/sensor-data", {
            "device_id": device, "temperature": temperature, "infrared": infrared,
        })
        check(set(result) == KEYS, "Response JSON fields changed")
        check(result["assessment"]["policy_version"] == "near-heat-demo-v2", "Wrong active policy")
        if args.interval and pause:
            time.sleep(args.interval)
        return result

    health, _ = call("GET", "/health", authenticated=False)
    check(health == {"ok": True, "model": "IsolationForest", "window_size": 10}, "Health check failed")
    print("PASS health")
    call("GET", f"/api/v1/status/{normal_id}", expected=401, authenticated=False)
    call("GET", f"/api/v1/status/{normal_id}", expected=401, authenticated=False,
         extra_headers={"X-API-Key": "deliberately-invalid-test-key"})
    call("GET", f"/api/v1/status/{normal_id}", expected=404)
    print("PASS authentication and unknown device")

    # Interleave a hot device: thermal rules work before its own AI window fills.
    for i, temperature in enumerate(NORMAL):
        normal = post(normal_id, temperature)
        if i < 9:
            check(normal["status"] == "COLLECTING", "AI became ready before 10 samples")
        if i < 5:
            other = post(other_id, 100)
            check(other["risk_level"] == "HIGH" and not other["ai"]["ready"], "Immediate thermal rule failed")
    check(normal["status"] == "NORMAL" and normal["ai"]["score"] >= 0, "Normal fixture was not NORMAL")
    check(normal["alarm_suggested"] is False, "NORMAL suggested an alarm")
    print(f"PASS NORMAL with 10 samples; score={normal['ai']['score']:.8f}")
    other_status, _ = call("GET", f"/api/v1/status/{other_id}")
    check(other_status["ai"]["ready"] is False, "Second device borrowed the first device's window")
    for _ in range(5):
        other = post(other_id, 100)
    check(other["ai"]["ready"] is True, "Second device did not become ready after its own 10 samples")
    check(other["sensors"]["temperature"] == 100, "Second device received the first device's sample")
    unchanged, _ = call("GET", f"/api/v1/status/{normal_id}")
    check(unchanged["timestamp"] == normal["timestamp"], "Second device changed the first device's status")
    print("PASS two independent devices")
    anomaly = post(normal_id, 120)
    check(anomaly["status"] == "THERMAL_DANGER", "120 C did not produce thermal danger")
    check(anomaly["risk_level"] == "HIGH" and anomaly["source"] == "THERMAL_RULE", "Thermal semantics changed")
    print("PASS temperature-only HIGH, independent of AI score")
    flame = post(prefix + "_ir", 29.2, 1)
    check(flame["status"] == "FLAME_SIGNAL" and flame["source"] == "DIRECT_SENSOR", "Direct IR signal lost")
    check(flame["risk_level"] == "LOW" and flame["alarm_suggested"] is False, "IR alone incorrectly triggered alarm")
    print("PASS IR alone is LOW and recorded before AI is ready")
    warning = post(prefix + "_warning", 65, 1)
    check(warning["risk_level"] == "MEDIUM" and warning["alarm_suggested"], "65 C + IR did not warn")
    fusion_id = prefix + "_fusion"
    first = post(fusion_id, 75, 1)
    check(first["risk_level"] == "MEDIUM", "IR was confirmed too early")
    time.sleep(1.05)
    post(fusion_id, 75, 1)
    time.sleep(1.05)
    fused = post(fusion_id, 75, 1)
    check(fused["risk_level"] == "HIGH" and fused["source"] == "SENSOR_FUSION", "Timed IR/heat fusion failed")
    print("PASS 65 C warning and confirmed IR + 75 C HIGH")
    rise_id = prefix + "_rise"
    for i in range(6):
        rising = post(rise_id, 65 + i, 1, pause=False)
        if i < 5:
            time.sleep(1.05)
    check(rising["risk_level"] == "HIGH" and "RAPID_TEMPERATURE_RISE" in rising["assessment"]["reasons"],
          "IR + rising temperature >=65 C did not reach HIGH")
    print("PASS confirmed IR + rapid warming below 75 C HIGH")
    for payload in [
        {"device_id": prefix, "temperature": 126, "infrared": 0},
        {"device_id": prefix, "temperature": 30, "infrared": 2},
        {"device_id": prefix, "temperature": "30", "infrared": 0},
        {"device_id": prefix, "temperature": 30, "infrared": True},
    ]:
        call("POST", "/api/v1/sensor-data", payload, expected=422)
    print("PASS input validation")
    if args.check_offline:
        time.sleep(10.2)
        offline, _ = call("GET", f"/api/v1/status/{normal_id}")
        check(offline["online"] is False, "Device should be offline after 10 seconds without samples")
        print("PASS online timeout")
        fresh = post(normal_id, 29.2)
        check(fresh["status"] == "COLLECTING" and fresh["ai"]["ready"] is False
              and fresh["ai"]["score"] is None, "Reconnected device reused stale AI samples")
        print("PASS reconnect starts a fresh AI window")
    print(f"PASS live HTTP smoke test at {base}")
    print(f"Test device prefix: {prefix} (RAM only; no real device was modified)")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, URLError, TimeoutError, ValueError, KeyError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
