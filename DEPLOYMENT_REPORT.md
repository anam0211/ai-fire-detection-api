# AI Fire API deployment - 2026-11-07

- Repository: https://github.com/anam0211/ai-fire-detection-api (main, public).
- HTTPS base URL: https://ai-fire-detection-api.onrender.com
- Swagger: https://ai-fire-detection-api.onrender.com/docs
- Render Dashboard: https://dashboard.render.com/web/srv-dbnj5gou01pc73ctfp20
- Workspace: My Workspace (tea-dbnj25m417fc73dtc3og).
- Service: srv-dbnj5gou01pc73ctfp20; Python, Free, Singapore, one instance/worker.
- Deploy: dep-dbnj5hgu01pc73ctfqv0; LIVE at 21:17:57 on 2026-11-07 (Asia/Saigon).
- Running source commit: 50f67669cb95f82a59878ca807a0d76669591a07. Subsequent documentation commits do not change runtime/model. Auto-deploy is off.

## Actual service configuration

Created directly through Render MCP. No Blueprint was created; render.yaml remains a template for future Blueprint deployments. Editing it does not update this service automatically.

Build: `sha256sum -c model.sha256 && pip install -r requirements.txt`.
Start: `python api.py`, bound to 0.0.0.0:10000 using Render's PORT.
Observed build runtime: Python 3.13.18, scikit-learn 1.6.1.

API_KEY was generated randomly and stored in Render Environment and the ignored local .env file. It was not committed or printed. The API does not load .env automatically. Load API_KEY into the environment before running the Python smoke test; the backend web client uses AI_API_URL and AI_API_KEY. Obtain the key privately from Render Environment or local .env; do not put it in frontend code or Git.

DASHBOARD_ORIGINS is empty. Backend/ESP32 requests can use the API key; direct browser access requires configuring the actual dashboard origin. Real Dashboard and ESP32 hardware have not been tested.

The current MCP creation tool does not expose an HTTP health-check path. This service uses the default TCP check; /health was separately verified over HTTPS. Health Check Path can be set to /health in Render Settings.

## Verification

- Local: 66 tests passed, one TestClient deprecation warning. Real HTTP and Node client tests passed.
- Original model: 748139 bytes; SHA-256: 9986dbd0f66591b8a406a0450fad0ddc83fd726155ec650d9638ff4a90637bd2.
- GitHub model download matches the original hash. Render build log: model.joblib: OK.
- HTTPS certificate and hostname verified using the default trust store; TLS 1.3.
- GET /health, /docs, /openapi.json: HTTP 200.
- HTTPS smoke test with --interval 1 --check-offline: PASS health, missing/invalid key (401), unknown device (404), 10-sample warmup, NORMAL, independent devices, ANOMALY, IR priority, validation (422), offline timeout and fresh window on reconnect.
- NORMAL score: 0.11054322; temperature jump to 120 C: ANOMALY score -0.01766559.
- Node client over HTTPS: PASS health, auth, 404, warmup, NORMAL, ANOMALY, IR, GET and validation.
- Dedicated test devices: smoke_5c850c161e87_* and web_test_6ac0f8983620*. No real device IDs were used.
- No error-level runtime logs found in the deployment/test interval inspected.

Repeat after loading the respective API key environment variables:

```powershell
python scripts/smoke_test.py --base-url https://ai-fire-detection-api.onrender.com --interval 1 --check-offline
$env:AI_API_URL = "https://ai-fire-detection-api.onrender.com"
node web_client/verify.mjs
```

A Free service can spin down after 15 minutes without inbound traffic. RAM state is lost on restart, redeploy or spin-down. The original model limitations documented in TEST_REPORT.md remain; passing interface tests does not establish real-world fire detection accuracy.
