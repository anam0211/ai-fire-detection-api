# AI Fire API — DS18B20 và cảm biến IR

API cho backend nhận mẫu IoT, trả mức cảnh báo theo nhiệt độ, diễn biến tăng nhiệt, IR và model Isolation Forest. Cấu hình v2 hiện tại theo bảng được chốt ngày 09/11/2026.

- Base URL: https://ai-fire-detection-api.onrender.com
- Swagger: https://ai-fire-detection-api.onrender.com/docs
- Repo: https://github.com/anam0211/ai-fire-detection-api
- Backend bắt đầu từ [WEB_INTEGRATION.md](WEB_INTEGRATION.md); hợp đồng chi tiết: [API_DOCUMENTATION.md](API_DOCUMENTATION.md).
- Thông tin deploy và kết quả HTTPS: [DEPLOYMENT_REPORT.md](DEPLOYMENT_REPORT.md).

## Mức cảnh báo

| Tình huống | risk_level |
| --- | --- |
| Chỉ có flame, nhiệt ổn định dưới 65°C | LOW, chưa đề xuất bật còi |
| Flame + nhiệt từ 65°C | Ít nhất MEDIUM |
| Flame liên tiếp ≥3 mẫu trong ≥2 giây + nhiệt ≥75°C | HIGH |
| Flame đã xác nhận + nhiệt ≥65°C, tăng ≥20°C/phút và tổng tăng ≥2°C | HIGH |
| Nhiệt ≥85°C | HIGH ngay, dù có flame hay không |

Nhiệt từ 65°C không IR, tăng nhiệt nhanh hoặc AI bất thường liên tiếp kèm tăng nhiệt cũng có thể đề xuất cảnh báo MEDIUM. Sau cảnh báo, hệ thống giữ mức cho tới khi đủ điều kiện nguội/xác nhận; xem tài liệu API.

MEDIUM/HIGH có `alarm_suggested=true`. Backend đọc `risk_level`, `alarm_suggested` và `online`; không bật còi chỉ vì `status=FLAME_SIGNAL`.

## Giao tiếp

Giữ `POST /api/v1/sensor-data`, `GET /api/v1/status/{device_id}`, `GET /health`, cùng header `X-API-Key`. Body vẫn là `device_id`, `temperature`, `infrared`. Gửi mỗi mẫu mới một lần, tuần tự khoảng 1 Hz; không replay backlog.

Response giữ các field v1 và thêm `assessment` giải thích lý do, tốc độ tăng nhiệt và phiên bản policy/model. Có status/source mới; backend dùng enum chặt phải cập nhật theo `openapi.json`.

Backend cần hai biến môi trường: `AI_API_URL` và `AI_API_KEY`. API key cấp riêng; không đưa lên frontend/Git. API không tự nạp file .env. CORS chỉ cần cấu hình khi browser gọi trực tiếp.

## Chạy và kiểm thử

Python 3.13, scikit-learn 1.6.1 theo requirements. Đặt API_KEY riêng trong môi trường trước khi chạy:

```powershell
python -m pip install -r requirements-dev.txt
python api.py
```

Server bind 0.0.0.0 và đọc PORT; mặc định 8000. Chỉ dùng một worker/instance vì lưu trạng thái trong RAM.

```powershell
python -m pytest -q
python scripts/verify_local.py --check-web-client
python scripts/evaluate_risk_v2.py
python scripts/smoke_test.py --base-url https://ai-fire-detection-api.onrender.com --interval 1 --check-offline
```

Script smoke dùng API_KEY trong môi trường và device_id thử riêng. `verify_local.py` tự sinh key/cổng tạm rồi dừng server, không sửa key cloud.

## Model và phạm vi

Model nhiệt độ mới nằm ở `risk_v2/model_candidate_v2.joblib`, train bằng dữ liệu mô phỏng; ngưỡng nhiệt là policy độc lập trong `risk_v2/policy.json`. Đây chưa phải hệ thống đã hiệu chuẩn bằng số đo bếp thực. AI score là điểm bất thường, không phải xác suất cháy.

Model gốc `model.joblib` giữ nguyên SHA-256 `9986dbd0f66591b8a406a0450fad0ddc83fd726155ec650d9638ff4a90637bd2`; code v1 lưu tại `legacy_api.py` để so sánh. API mới chạy qua `api.py` → `risk_v2.api`, không chạy notebook train lúc deploy.

Xem [risk_v2/README.md](risk_v2/README.md) về dữ liệu train và hiệu chỉnh. Free service có thể ngủ/restart, mất trạng thái RAM; khi kết nối lại cần thu cửa sổ AI mới. LOW/NORMAL không bảo đảm không có cháy.

## Bàn giao

`python scripts/build_handoff.py` tạo ZIP source theo allowlist và manifest, luôn kiểm tra model gốc. `python scripts/build_web_handoff.py` tạo ZIP dành cho backend, không chứa model hoặc API key. Không chạy lại bộ đóng gói v1 cũ từ thư mục cha để ghi đè repo v2.
