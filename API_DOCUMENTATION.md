# API Documentation — 2.0.0-demo

Base URL: https://ai-fire-detection-api.onrender.com. Schema đầy đủ: `openapi.json` hoặc `/openapi.json`; Swagger `/docs`.

## Xác thực

Hai endpoint /api/v1/* dùng header `X-API-Key`; thiếu/sai trả 401. /health, /docs và /openapi.json công khai. CORS lấy từ DASHBOARD_ORIGINS; backend/ESP32 không cần CORS. Key chung truy cập mọi device_id.

## POST /api/v1/sensor-data

```json
{"device_id":"esp32_01","temperature":65,"infrared":1}
```

- device_id: 1–64 ký tự A–Z, a–z, 0–9, dấu gạch dưới/gạch ngang.
- temperature: số JSON hữu hạn trong [-40,125] °C; từ chối chuỗi, bool, null, NaN/Infinity.
- infrared: số nguyên JSON 0 hoặc 1; từ chối bool, 1.0, chuỗi và giá trị khác.
- Trường dư được bỏ qua. Không nhận timestamp thiết bị; dùng thời gian server nhận mẫu.
- Gửi tuần tự khoảng 1 Hz, một nguồn/mỗi ID, không replay backlog hoặc nhân đôi mẫu khi Dashboard refresh.

Response giữ 9 trường v1 và thêm assessment. Ví dụ mẫu đầu nhiệt 65°C + IR:

```json
{
  "device_id": "esp32_01",
  "status": "FLAME_SIGNAL",
  "risk_level": "MEDIUM",
  "source": "SENSOR_FUSION",
  "sensors": {"temperature":65,"infrared":1},
  "ai": {"model":"IsolationForest","ready":false,"result":"INSUFFICIENT_DATA","score":null},
  "alarm_suggested": true,
  "timestamp": "2026-11-09T00:00:00+00:00",
  "online": true,
  "assessment": {
    "reasons": ["ELEVATED_TEMPERATURE","IR_UNCONFIRMED"],
    "temperature_rise_c_per_min": null,
    "observation_seconds": 0,
    "policy_version": "near-heat-demo-v2",
    "model_version": "temperature-v2-synthetic_demo",
    "training_provenance": "synthetic_demo",
    "experimental": true
  }
}
```

Timestamp minh họa. Thời gian quan sát và score phản ánh cửa sổ thực.

## Policy được chọn

| Điều kiện | risk_level | status/source chủ yếu |
| --- | --- | --- |
| Nhiệt ≥85°C | HIGH ngay | THERMAL_DANGER / THERMAL_RULE |
| IR liên tiếp ≥3 mẫu trong ≥2 giây và nhiệt ≥75°C | HIGH | FLAME_SIGNAL / SENSOR_FUSION |
| IR xác nhận, nhiệt ≥65°C, tốc độ tăng ≥20°C/phút và tổng tăng ≥2°C | HIGH | FLAME_SIGNAL / SENSOR_FUSION |
| Nhiệt ≥65°C, chưa đạt điều kiện HIGH | MEDIUM | THERMAL_WARNING hoặc FLAME_SIGNAL |
| Tăng ≥12°C/phút và tổng tăng ≥2°C | Ít nhất MEDIUM | THERMAL_WARNING |
| AI âm ≥3 lần liên tiếp, nhiệt ≥55°C, tổng tăng ≥2°C và xu hướng tăng | Ít nhất MEDIUM | ANOMALY |
| IR=1, nhiệt ổn định <65°C, chưa có cảnh báo khác | LOW, không đề xuất còi | FLAME_SIGNAL / DIRECT_SENSOR |
| Chưa đủ 10 mẫu, không có IR hoặc điều kiện cảnh báo | UNKNOWN | COLLECTING / SYSTEM |
| Đủ mẫu nhưng không có cảnh báo được xác nhận | LOW | NORMAL hoặc ANOMALY / AI |

Điều kiện ưu tiên từ trên xuống. IR đơn lẻ không được nâng HIGH, kể cả kéo dài. `alarm_suggested=true` khi risk MEDIUM/HIGH, false khi LOW/UNKNOWN. Đây là gợi ý để backend thực hiện cảnh báo; API không điều khiển còi trực tiếp.

Tốc độ tăng tính hồi quy theo thời gian server nhận mẫu, chỉ có kết quả nếu cửa sổ kéo dài 5–30 giây. Với cửa sổ quá ngắn/dài, trường tốc độ là null; ngưỡng nhiệt tuyệt đối vẫn hoạt động.

Hysteresis: khi điều kiện tức thời giảm mức, API giữ mức cũ bằng RECOVERY_HOLD cho đến khi nhiệt ≤55°C, IR=0, hết dấu hiệu tăng nhiệt/AI warming, đủ ≥3 mẫu và ≥5 giây xác nhận. Nếu nguy cơ trở lại, bộ đếm nguội bắt đầu lại. Vì vậy mức đang giữ có thể cao hơn hàng tương ứng trong bảng.

AI dùng 10 mẫu riêng từng ID với temp_mean, temp_max, temp_change, temp_std float32. Model không dùng IR làm đặc trưng nhiệt. Score âm là bất thường, không phải xác suất cháy. Policy nhiệt/IR độc lập có thể trả HIGH khi AI chưa đủ mẫu hoặc model nói NORMAL.

## Enum và field

- status: COLLECTING, NORMAL, ANOMALY, FLAME_SIGNAL, THERMAL_WARNING, THERMAL_DANGER, RECOVERY_HOLD.
- risk_level: UNKNOWN, LOW, MEDIUM, HIGH.
- source: SYSTEM, AI, DIRECT_SENSOR, THERMAL_RULE, SENSOR_FUSION, HYSTERESIS.
- ai.result: INSUFFICIENT_DATA, NORMAL, ANOMALY, MODEL_ERROR.
- assessment.reasons: các mã lý do để giải thích; không dùng như enum cố định cho điều khiển còi. Các mã gồm HIGH_TEMPERATURE, PERSISTENT_IR_WITH_HEAT, ELEVATED_TEMPERATURE, RAPID_TEMPERATURE_RISE, IR_CONFIRMED, IR_UNCONFIRMED, IR_ALONE_NEAR_EXPECTED_HEAT_SOURCE, AI_ANOMALY_WITH_WARMING, AI_ANOMALY_UNCORROBORATED, RECOVERY_HOLD, COOLING_CONFIRMED, NO_CORROBORATED_HAZARD.

## GET /api/v1/status/{device_id}

Trả trạng thái cuối, chỉ tính lại online=(thời gian từ mẫu cuối <10 giây). GET không tạo mẫu, không đổi timestamp. Đúng 10 giây là offline. Trạng thái cuối vẫn giữ; mất kết nối không phải hết cảnh báo.

Nếu khoảng ngừng gửi ≥10 giây, mẫu POST tiếp theo bắt đầu cửa sổ và counters mới; cảnh báo nhiệt tuyệt đối vẫn đánh giá ngay. ID chưa gửi hoặc RAM vừa bị xóa: 404. Chỉ dùng 1 worker/instance.

## GET /health và lỗi

Health OK: `{"ok":true,"model":"IsolationForest","window_size":10}`.

Nếu lần suy luận gần nhất lỗi: HTTP 503, ok=false. Suy luận thành công tiếp theo khôi phục health. Nếu model lỗi trong POST, vẫn trả đánh giá độc lập từ nhiệt/IR hoặc mức cảnh báo cần giữ, ai.result=MODEL_ERROR, ready=false, score=null. Nếu không có bằng chứng độc lập để phục vụ request thì trả 503 và không ghi mẫu. Thiếu/hỏng model hoặc checksum sai làm startup thất bại.

401: key sai/thiếu; 404: chưa có dữ liệu; 422: dữ liệu sai; 503: model không sẵn sàng. Không ghi lại input/secret trong lỗi validation. Không tự retry POST sau timeout.

Model v2 được train bằng dữ liệu mô phỏng và các ngưỡng là cấu hình thử nghiệm được chọn, chưa hiệu chuẩn/kiểm chứng cháy thực. LOW/NORMAL không xác nhận an toàn.
