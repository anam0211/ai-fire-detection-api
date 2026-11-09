"""Export the live API schema and a secret-free integration ZIP for the web developer."""

import json
from pathlib import Path
import sys
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from api import app

WEB_FILES = (
    "WEB_INTEGRATION.md", "API_DOCUMENTATION.md", "openapi.json",
    "web_client/ai-client.mjs", "web_client/example.mjs", "web_client/verify.mjs",
    "web_client/.env.example", "web_client/ai-api.postman_collection.json",
    "web_client/local.postman_environment.json",
)


def write_json(name, value):
    (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def request_item(name, method, path, *, body=None, public=False, expected=200, description=""):
    request = {"method": method, "url": "{{base_url}}" + path, "description": description}
    if public:
        request["auth"] = {"type": "noauth"}
    if body is not None:
        request["header"] = [{"key": "Content-Type", "value": "application/json"}]
        request["body"] = {"mode": "raw", "raw": json.dumps(body, indent=2),
                           "options": {"raw": {"language": "json"}}}
    return {"name": name, "request": request, "event": [{
        "listen": "test", "script": {"type": "text/javascript", "exec": [
            f'pm.test("HTTP {expected}", function () {{ pm.response.to.have.status({expected}); }});'
        ]},
    }]}


def main():
    sample = {"device_id": "{{device_id}}", "temperature": 29.2, "infrared": 0}
    write_json("openapi.json", app.openapi())
    write_json("web_client/ai-api.postman_collection.json", {
        "info": {
            "name": "AI Fire API - Web Integration",
            "description": "Temperature/IR API v2. Keep the API key private. LOW IR alone; confirmed IR plus heat can be HIGH. See WEB_INTEGRATION.md.",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "auth": {"type": "apikey", "apikey": [
            {"key": "key", "value": "X-API-Key", "type": "string"},
            {"key": "value", "value": "{{api_key}}", "type": "string"},
            {"key": "in", "value": "header", "type": "string"},
        ]},
        "item": [
            request_item("Health (public)", "GET", "/health", public=True),
            request_item("Send one sample (repeat 10 times to warm up)", "POST", "/api/v1/sensor-data",
                         body=sample, description="Send sequentially about once per second. First nine samples return COLLECTING."),
            request_item("Read latest status", "GET", "/api/v1/status/{{device_id}}"),
            request_item("Temperature spike (after warmup)", "POST", "/api/v1/sensor-data",
                         body={**sample, "temperature": 120}),
            request_item("Direct IR signal (new test device)", "POST", "/api/v1/sensor-data",
                         body={**sample, "device_id": "{{device_id}}_ir", "infrared": 1},
                         description="IR alone at stable room temperature returns LOW, alarm_suggested=false."),
            request_item("IR + 65 C warning", "POST", "/api/v1/sensor-data",
                         body={**sample, "device_id": "{{device_id}}_warning", "temperature": 65, "infrared": 1}),
            request_item("IR + 75 C (send 3 samples over >=2 seconds)", "POST", "/api/v1/sensor-data",
                         body={**sample, "device_id": "{{device_id}}_fusion", "temperature": 75, "infrared": 1},
                         description="First sample MEDIUM; HIGH after >=3 consecutive IR samples spanning >=2 seconds. Do not burst requests."),
            request_item("85 C immediate HIGH without IR", "POST", "/api/v1/sensor-data",
                         body={**sample, "device_id": "{{device_id}}_thermal", "temperature": 85}),
            request_item("Invalid payload -> 422", "POST", "/api/v1/sensor-data",
                         body={**sample, "temperature": 126}, expected=422),
            request_item("No API key -> 401", "POST", "/api/v1/sensor-data",
                         body=sample, public=True, expected=401),
        ],
    })
    write_json("web_client/local.postman_environment.json", {
        "name": "AI Fire API - Local (fill key privately)",
        "values": [
            {"key": "base_url", "value": "http://127.0.0.1:8000", "enabled": True},
            {"key": "api_key", "value": "", "type": "secret", "enabled": True},
            {"key": "device_id", "value": "esp32_web_test", "enabled": True},
        ],
        "_postman_variable_scope": "environment",
    })
    destination = ROOT / "AI_Fire_Web_Integration.zip"
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for name in WEB_FILES:
            archive.write(ROOT / name, name)
    with ZipFile(destination) as archive:
        assert set(archive.namelist()) == set(WEB_FILES)
        assert archive.testzip() is None
    print(f"Created {destination.name}: {len(WEB_FILES)} integration files; no model, virtualenv or real API key")


if __name__ == "__main__":
    main()
