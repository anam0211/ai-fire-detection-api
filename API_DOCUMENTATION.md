# API Documentation — v1

Base URL local: `http://127.0.0.1:8000`. Base URL cloud: dùng URL HTTPS do Render thực sự cấp sau deploy, chưa có URL đã xác minh trong lần bàn giao này. Không thêm dấu `/` cuối vào biến base URL trong ví dụ.

## Xác thực và CORS

Hai endpoint `/api/v1/*` yêu cầu `X-API-Key: <key đã được cấp>`. Không gửi key trong body/query string. `/health`, `/docs`, `/redoc`, `/openapi.json` công khai. Swagger có nút Authorize để đặt header. CORS chỉ cho browser origin được cấu hình trong `DASHBOARD_ORIGINS`; ESP32 không chịu CORS. CORS không thay thế xác thực hay phân quyền. Cùng một key hiện truy cập được mọi `device_id`.

## GET /health

Không cần API key. Chỉ trả healthy sau khi nạp và thử suy luận model thành công tại startup.

`200 OK`:

```json
{"ok": true, "model": "IsolationForest", "window_size": 10}
```

Sau lỗi suy luận, `503 Service Unavailable`:

```json
{"ok": false, "model": "IsolationForest", "window_size": 10, "detail": "Model inference unavailable"}
```

Health trở về `200` sau suy luận thành công tiếp theo. Thiếu/hỏng artifact hoặc scikit-learn khác 1.6.1 khiến startup dừng và ghi lỗi trong log; khi đó chưa có API phục vụ HTTP. Không tự train hay tạo model thay thế.

## POST /api/v1/sensor-data

Header: `Content-Type: application/json`, `X-API-Key: <key>`.

```json
{"device_id": "esp32_01", "temperature": 29.2, "infrared": 0}
```

| Field | Yêu cầu |
| --- | --- |
| `device_id` | Chuỗi 1–64 ký tự, chỉ `A-Z a-z 0-9 _ -`; ID phải duy nhất và ổn định giữa ESP32 và Dashboard. |
| `temperature` | Số JSON hữu hạn, trong `[-40, 125]` °C; chấp nhận `30` hoặc `30.5`, từ chối `"30"`, bool, null, NaN, Infinity. |
| `infrared` | Số nguyên JSON chính xác `0` hoặc `1`; từ chối `1.0`, `"1"`, bool, null. `1` nghĩa là cảm biến thấy tín hiệu lửa, không phải mức điện áp raw. |

Cả ba field đều bắt buộc. Field dư bị bỏ qua như API cũ. API dùng thời gian nhận mẫu, không nhận timestamp thiết bị. Mẫu được tính theo thứ tự server xử lý; không có sequence number hay loại mẫu trùng. Chỉ gửi tuần tự từ một nguồn cho mỗi ID.

`200 OK` trong chín mẫu đầu (`infrared=0`):

```json
{
  "device_id": "esp32_01",
  "status": "COLLECTING",
  "risk_level": "UNKNOWN",
  "source": "SYSTEM",
  "sensors": {"temperature": 29.2, "infrared": 0},
  "ai": {"model": "IsolationForest", "ready": false, "result": "INSUFFICIENT_DATA", "score": null},
  "alarm_suggested": false,
  "timestamp": "2026-11-07T11:00:00+00:00",
  "online": true
}
```

Ví dụ `200 OK` sau 10 mẫu fixture normal; timestamp minh họa, score từ model thật:

```json
{
  "device_id": "esp32_01",
  "status": "NORMAL",
  "risk_level": "LOW",
  "source": "AI",
  "sensors": {"temperature": 29.14, "infrared": 0},
  "ai": {"model": "IsolationForest", "ready": true, "result": "NORMAL", "score": 0.11054322360111468},
  "alarm_suggested": false,
  "timestamp": "2026-11-07T11:00:09+00:00",
  "online": true
}
```

## Phân loại và ý nghĩa JSON

| Điều kiện, theo thứ tự ưu tiên | `status` | `risk_level` | `source` | `alarm_suggested` |
| --- | --- | --- | --- | --- |
| Mẫu hiện tại có IR=1, kể cả khi chưa đủ 10 mẫu | `FLAME_SIGNAL` | `HIGH` | `DIRECT_SENSOR` | `true` |
| IR=0, đủ mẫu, score < 0 | `ANOMALY` | `MEDIUM` | `AI` | `true` |
| IR=0, đủ mẫu, score >= 0 | `NORMAL` | `LOW` | `AI` | `false` |
| IR=0, chưa đủ 10 mẫu | `COLLECTING` | `UNKNOWN` | `SYSTEM` | `false` |

`sensors` là mẫu mới nhất. `ai.result` độc lập với `status`: khi IR=1, trạng thái luôn ưu tiên `FLAME_SIGNAL`, còn AI vẫn có thể trả NORMAL/ANOMALY/INSUFFICIENT_DATA. `ai.ready` nói AI có kết quả sử dụng được từ cửa sổ hiện tại. `ai.score` là điểm `decision_function`, **không phải xác suất hoặc phần trăm cháy**.

Các đặc trưng giữ nguyên: `temp_mean`, `temp_max`, `temp_change = nhiệt độ cuối - đầu`, `flame_ratio` trên 10 mẫu gần nhất, dtype float32. Một device không sử dụng mẫu của device khác. Nếu khoảng cách từ mẫu được chấp nhận cuối tới mẫu mới >=10 giây, mẫu mới bắt đầu cửa sổ riêng và AI thu lại 10 mẫu. Chu kỳ dự kiến khoảng 1 giây/mẫu; API chưa kiểm tra chính xác chu kỳ này.

`timestamp` là UTC ISO-8601 tại lần POST thành công; `online=true` trong POST. `alarm_suggested` chỉ là gợi ý để hệ thống tích hợp xử lý phù hợp. **ANOMALY không xác nhận cháy; NORMAL không xác nhận an toàn.** Model gốc đã cho NORMAL với 10 mẫu cố định 100°C trong kiểm thử kỹ thuật. `FLAME_SIGNAL` cũng chỉ là tín hiệu cảm biến cần được đánh giá theo thiết kế hệ thống.

## GET /api/v1/status/{device_id}

Cần `X-API-Key`. ID tuân thủ cùng quy tắc như POST. `200 OK` trả đúng chín trường JSON của lần POST thành công cuối, cập nhật riêng `online` thành `(thời gian từ mẫu cuối < 10 giây)`. Đúng mốc 10 giây là offline. GET không thêm mẫu hay cập nhật timestamp. Dữ liệu cũ vẫn giữ nguyên để Dashboard biết đây là trạng thái cuối trước khi mất kết nối.

Khi thiết bị gửi lại sau khi offline, API không dùng cửa sổ cũ: trả `COLLECTING` / `INSUFFICIENT_DATA` cho tới khi nhận đủ 10 mẫu mới. IR=1 vẫn ưu tiên `FLAME_SIGNAL` trong giai đoạn thu mẫu. Thay đổi này ngăn AI suy luận từ các mẫu thuộc hai phiên gửi cách xa nhau; giữ nguyên cấu trúc JSON và thuật toán model.

Thiết bị chưa gửi mẫu hoặc server vừa restart: `404`:

```json
{"detail": "No samples received for this device"}
```

Lịch sử và trạng thái nằm trong RAM, mất khi sleep/restart/redeploy. Chỉ dùng **1 worker / 1 instance**; không chia tải nhiều instance nếu chưa chuyển sang kho trạng thái chung.

## HTTP status và lỗi

| HTTP | Khi nào | Hành động tích hợp |
| --- | --- | --- |
| `200` | Thành công, kể cả COLLECTING và FLAME_SIGNAL khi AI lỗi | Đọc cả `status`, `ai`, `online`. |
| `401` | Thiếu/sai API key trên endpoint dữ liệu | Kiểm tra key; không retry liên tục. |
| `404` | Chưa có mẫu cho device, hoặc đường dẫn không tồn tại | Kiểm tra ID, server restart và dữ liệu đã gửi. |
| `422` | Body/ID/số liệu/JSON không hợp lệ | Sửa payload; mẫu bị từ chối không vào cửa sổ. |
| `503` | Lỗi suy luận với IR=0; hoặc health đang lỗi | Ghi nhận API/AI chưa sẵn sàng, giữ cảnh báo độc lập tại thiết bị. |
| `400` trên preflight | Origin, method hoặc header CORS không được phép | Sửa cấu hình origin/request. |

Lỗi key: `{"detail":"Missing or invalid X-API-Key"}`. Lỗi model: `{"detail":"Model inference unavailable"}`; chi tiết exception nằm ở server log, không trả stack trace/path ra client.

Ví dụ lỗi validation (giá trị gốc và context được lược bỏ để không phản chiếu secret hoặc NaN):

```json
{"detail": [{"type": "less_than_equal", "loc": ["body", "temperature"], "msg": "Input should be less than or equal to 125"}]}
```

Lỗi suy luận không ghi lịch sử/trạng thái mới nếu IR=0. Nếu IR=1 thì vẫn ghi và trả chín trường JSON với `status=FLAME_SIGNAL`, `risk_level=HIGH`, `source=DIRECT_SENSOR`, `alarm_suggested=true`, và:

```json
{"model": "IsolationForest", "ready": false, "result": "MODEL_ERROR", "score": null}
```

Đây là nội dung của field `ai`, không phải một response đầy đủ mới. Bổ sung `MODEL_ERROR` để tránh báo NORMAL khi model lỗi và không làm mất tín hiệu trực tiếp từ IR. Sau lỗi model, `/health` trả 503 cho tới lần suy luận tốt tiếp theo hoặc restart thành công.

Timeout/mất mạng/502 do nền tảng có thể xảy ra ngoài API. Không tự replay cùng POST sau timeout: không có idempotency key, nên cùng mẫu có thể được đếm hai lần. Chuyển sang mẫu hiện tại ở chu kỳ tiếp theo và xử lý cảnh báo local độc lập.
