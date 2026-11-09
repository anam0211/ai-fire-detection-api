# Tích hợp backend web — API nhiệt độ/IR v2

Base URL: **https://ai-fire-detection-api.onrender.com**. Swagger: https://ai-fire-detection-api.onrender.com/docs.

Backend chỉ cần gọi HTTP, không cần cài Python/model. Dùng URL và key đã cấp trước đó; không đưa key vào frontend hoặc Git.

```env
AI_API_URL=https://ai-fire-detection-api.onrender.com
AI_API_KEY=<key cấp riêng>
```

## Gửi mỗi mẫu mới

```http
POST /api/v1/sensor-data
Content-Type: application/json
X-API-Key: <AI_API_KEY>

{"device_id":"esp32_01","temperature":29.2,"infrared":0}
```

Một nguồn gửi cho mỗi device_id; tuần tự khoảng một mẫu/giây. IR phải chuẩn hóa 1=có tín hiệu lửa, 0=không; không gửi điện áp active-LOW raw. Temperature phải là số đo hợp lệ từ DS18B20, không gửi sentinel lỗi.

## Đọc kết quả

`GET /api/v1/status/esp32_01` với cùng header key chỉ đọc trạng thái cuối, không thêm mẫu.

Dùng **risk_level, alarm_suggested, online** để hiển thị/xử lý. Không suy ra mức nguy hiểm từ `FLAME_SIGNAL` hoặc score âm.

| Tình huống | Mức |
| --- | --- |
| Flame đơn lẻ, nhiệt ổn định dưới 65°C | LOW, alarm_suggested=false |
| Flame + nhiệt từ 65°C | Ít nhất MEDIUM, alarm_suggested=true |
| ≥3 mẫu flame liên tiếp trong ≥2 giây + nhiệt ≥75°C | HIGH |
| Flame xác nhận + nhiệt ≥65°C, tăng ≥20°C/phút và tổng tăng ≥2°C | HIGH |
| Nhiệt ≥85°C, bất kể flame | HIGH ngay |

Cảnh báo nhiệt hoạt động trước khi AI đủ 10 mẫu. Tăng nhiệt phải có cửa sổ quan sát 5–30 giây, tính theo thời gian server nhận mẫu; không gửi dồn để thử tốc độ tăng nhiệt.

Sau cảnh báo, có thể trả `RECOVERY_HOLD` và giữ mức cũ. Chỉ hạ mức khi nhiệt ≤55°C, IR=0 và hết dấu hiệu tăng nhiệt, đủ ít nhất 3 mẫu và 5 giây xác nhận. `online=false` là mất dữ liệu, không đồng nghĩa đã an toàn.

## Client Node

Copy `web_client/ai-client.mjs` vào backend Node có fetch; không cần npm dependency.

```javascript
import { createAiClient } from "./ai-client.mjs";

const ai = createAiClient({
  baseUrl: process.env.AI_API_URL,
  apiKey: process.env.AI_API_KEY,
});

const result = await ai.sendSample({
  device_id: "esp32_01",
  temperature: 65,
  infrared: 1,
});

console.log(result.risk_level, result.alarm_suggested);
console.log(result.assessment.reasons);
// Lưu response hoặc gửi qua socket tới Dashboard.
// await ai.getStatus("esp32_01") chỉ đọc, không gửi lại mẫu.
```

Hook đầy đủ: `web_client/example.mjs`. Kiểm tra từ backend sau khi đặt URL/key:

```powershell
node web_client/verify.mjs
```

Postman collection và environment không có key thật nằm trong `web_client`; đặt base_url và api_key riêng trước khi chạy.

## Thay đổi cần cập nhật phía backend

Request, URL và header giữ nguyên. Response thêm `assessment`, gồm reasons, temperature_rise_c_per_min, observation_seconds, policy_version, model_version, training_provenance và experimental.

Status hợp lệ: COLLECTING, NORMAL, ANOMALY, FLAME_SIGNAL, THERMAL_WARNING, THERMAL_DANGER, RECOVERY_HOLD. Source: SYSTEM, AI, DIRECT_SENSOR, THERMAL_RULE, SENSOR_FUSION, HYSTERESIS.

`ai.ready=false` không có nghĩa risk thấp: nhiệt 85°C vẫn HIGH ngay. `ai.result` và risk độc lập. API trả gợi ý, backend/ESP32 mới thực hiện còi/thông báo.

401: kiểm tra key. 422: kiểm tra payload. 503/timeout: hiển thị mất kết nối hoặc lỗi AI, không thay bằng NORMAL. Không tự retry POST sau timeout vì server có thể đã nhận mẫu. Chờ mẫu mới.

Trạng thái RAM mất khi server sleep/restart. GET có thể trả 404 sau restart hoặc trước mẫu đầu. Khi khoảng ngừng gửi ≥10 giây, mẫu tiếp theo mở cửa sổ mới. Ngưỡng v2 là profile thử nghiệm được chọn; chưa đánh giá độ chính xác cháy thực tế.
