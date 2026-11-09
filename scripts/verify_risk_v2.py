"""Run a temporary v2 HTTP server, exercise timed scenarios and stop it reliably."""

import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node is required to check the backend client")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    key = secrets.token_urlsafe(32)
    base = f"http://127.0.0.1:{port}"
    environment = {**os.environ, "API_KEY": key, "PORT": str(port),
                   "DASHBOARD_ORIGINS": "http://localhost:5173"}

    def call(method, path, payload=None, expected=200, authenticated=True):
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["X-API-Key"] = key
        request = Request(base + path, method=method, headers=headers,
                          data=None if payload is None else json.dumps(payload).encode())
        try:
            with urlopen(request, timeout=10) as response:
                code, body = response.status, response.read()
        except HTTPError as exc:
            code, body = exc.code, exc.read()
        assert code == expected, f"{method} {path}: expected {expected}, got {code}"
        return json.loads(body)

    def post(device, temperature, ir=0):
        return call("POST", "/api/v1/sensor-data", {
            "device_id": device, "temperature": temperature, "infrared": ir,
        })

    with tempfile.TemporaryFile() as log:
        server = subprocess.Popen([sys.executable, "-m", "risk_v2.api"], cwd=ROOT,
                                  env=environment, stdout=log, stderr=subprocess.STDOUT,
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            deadline = time.monotonic() + 45
            while True:
                if server.poll() is not None:
                    raise RuntimeError("Candidate API exited during startup")
                try:
                    if call("GET", "/health", authenticated=False)["ok"]:
                        break
                except (URLError, TimeoutError):
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("Candidate API readiness timed out")
                time.sleep(0.2)
            print(f"Candidate server ready at {base}", flush=True)
            call("GET", "/api/v1/status/a", expected=401, authenticated=False)
            call("GET", "/api/v1/status/a", expected=404)
            print("PASS health, auth and unknown device", flush=True)
            for temperature in (85, 100, 120):
                result = post(f"hot_{temperature}", temperature)
                assert result["risk_level"] == "HIGH" and result["alarm_suggested"]
                assert not result["ai"]["ready"]
            assert post("ir_room", 29.2, 1)["risk_level"] == "LOW"
            assert post("cooking", 55, 1)["risk_level"] == "LOW"
            assert post("ir_heat", 78, 1)["risk_level"] == "MEDIUM"
            time.sleep(1)
            assert post("ir_heat", 78, 1)["risk_level"] == "MEDIUM"
            time.sleep(1.05)
            assert post("ir_heat", 78, 1)["risk_level"] == "HIGH"
            print("PASS temperature-only HIGH, cooking/IR-only LOW and timed heat/IR fusion", flush=True)
            for index in range(10):
                room = post("room", 29.2)
                result = post("rise", 30 + index / 3)
                if index != 9:
                    time.sleep(1)
            assert room["risk_level"] == "LOW"
            assert result["risk_level"] == "MEDIUM"
            assert "RAPID_TEMPERATURE_RISE" in result["assessment"]["reasons"]
            print("PASS normal warmup and rapid rise over actual elapsed time; devices independent", flush=True)
            call("POST", "/api/v1/sensor-data", {"device_id": "bad", "temperature": 126, "infrared": 0}, expected=422)
            time.sleep(10.2)
            assert call("GET", "/api/v1/status/room")["online"] is False
            fresh = post("room", 29.2)
            assert fresh["status"] == "COLLECTING" and not fresh["ai"]["ready"]
            print("PASS validation, offline and fresh model window on reconnect", flush=True)
            subprocess.run([node, "risk_v2/verify-client.mjs"], cwd=ROOT,
                           env={**environment, "AI_API_URL": base, "AI_API_KEY": key},
                           check=True, timeout=60)
            print("PASS v2 real HTTP verification; cloud was not changed", flush=True)
        except Exception:
            log.seek(0)
            print(log.read().decode("utf-8", errors="replace"), file=sys.stderr)
            raise
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


if __name__ == "__main__":
    main()
