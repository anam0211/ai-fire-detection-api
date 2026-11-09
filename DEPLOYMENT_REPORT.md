# AI Fire API v2 — triển khai 09/11/2026

- Trạng thái: **LIVE**, bản API `2.0.0-demo`, policy `near-heat-demo-v2`.
- URL giữ nguyên: https://ai-fire-detection-api.onrender.com
- Swagger/schema: /docs, /openapi.json.
- Repo: https://github.com/anam0211/ai-fire-detection-api, main.
- Render: srv-dbnj5gou01pc73ctfp20, Free, Singapore, My Workspace.
- Deploy: `dep-dbona5u417fc738qh4qg`; live lúc **14:25:22 ngày 09/11/2026 (Asia/Saigon)**.
- Source chạy trên Render: `7688e0db8db42799ee3341edb4c50909a64e2449`.
- Các commit cập nhật báo cáo sau deploy không đổi runtime/model. Auto-deploy vẫn tắt.
- API key giữ nguyên; kiểm thử HTTPS dùng key local đã cấp, không thay biến môi trường trên Render.

Entrypoint vẫn `python api.py`, nay phục vụ v2 qua risk_v2.api. Model gốc model.joblib giữ nguyên hash, được Render xác minh khi build. Model nhiệt độ mới lưu riêng; checksum candidate được xác minh trước khi nạp lúc startup.

## Kết quả xác minh v2

- **121 test PASS**, 1 deprecation warning TestClient.
- **21/21 kịch bản mô phỏng** trong risk_v2/evaluation.json đạt kỳ vọng.
- HTTP local và client Node PASS trước khi push.
- HTTPS xác minh hostname/chứng chỉ thành công, TLS 1.3.
- OpenAPI live trả version 2.0.0-demo và schema có assessment.
- Smoke test HTTPS --interval 1 --check-offline PASS: health, thiếu/sai key, 404, normal sau 10 mẫu, thiết bị độc lập, nhiệt độ cao không IR HIGH, IR đơn lẻ LOW/không còi, IR+nhiệt 65°C MEDIUM, IR xác nhận+nhiệt 75°C HIGH, IR xác nhận+tăng nhanh từ 65°C lên HIGH dưới 75°C, validation, offline và cửa sổ mới khi kết nối lại.
- Client Node qua HTTPS PASS, gồm trạng thái IR-only LOW và phối hợp IR/nhiệt theo thời gian thực lên HIGH.
- /docs HTTP 200. Không thấy log error trong khoảng triển khai/kiểm thử đã kiểm tra.
- ID thử cloud: smoke_7abae19f0393_* và web_test_a072d25b719e*; không gửi vào ID thiết bị thật.

Model gốc SHA-256: `9986dbd0f66591b8a406a0450fad0ddc83fd726155ec650d9638ff4a90637bd2`.
Model candidate v2 SHA-256: `ce58e4321ca0948642a8b1f5e7fe021d8a1a1eb9d98bda17b8c88104d6647fae`.

## Bàn giao backend

URL, key, endpoint và request body giữ nguyên. Backend đọc risk_level/alarm_suggested/online, không bật còi chỉ từ FLAME_SIGNAL. Response thêm assessment và các enum status/source mới. Hướng dẫn hiện hành: [WEB_INTEGRATION.md](WEB_INTEGRATION.md), [API_DOCUMENTATION.md](API_DOCUMENTATION.md), openapi.json và web_client.

Profile v2 dùng nhiệt/IR theo bảng đã được chủ dự án chọn; model train bằng mô phỏng, chưa hiệu chuẩn từ số đo thực tế. Cảnh báo và dữ liệu RAM mất khi restart; LOW/NORMAL không bảo đảm an toàn. Chi tiết hysteresis/offline nằm trong tài liệu API. Service hiện dùng TCP health check mặc định; /health đã kiểm tra riêng qua HTTPS.

---

## Lịch sử triển khai v1 — 07/11/2026

Nội dung bên dưới mô tả bản v1 trước khi được thay bằng v2.

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
