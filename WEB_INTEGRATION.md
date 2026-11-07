# Giao cho người làm backend web

Web đã nhận số liệu thiết bị: chỉ cần chuyển **mỗi mẫu mới** từ backend web sang API AI, lấy response để hiển thị. Người làm web không cần Python hoặc model.

```text
Thiết bị → Backend web → POST API AI → Backend web → Dashboard
```

## Thông tin kết nối

| Thông tin | Giá trị |
| --- | --- |
| URL cloud | Chưa deploy/xác minh; thay bằng URL HTTPS thực sau deploy Render. |
| URL thử local | `http://127.0.0.1:8000` nếu cùng máy; máy khác dùng IP LAN của máy chạy API. |
| Biến môi trường trên backend web | `AI_API_URL`, `AI_API_KEY` |
| Header | `X-API-Key: <key cấp riêng>` |
| Gửi 1 mẫu mới | `POST /api/v1/sensor-data` |
| Đọc kết quả cuối, không thêm mẫu | `GET /api/v1/status/{device_id}` |
| Kiểm tra API | `GET /health`, không cần key |
| Schema đầy đủ | `openapi.json`, hoặc `/openapi.json` trên server đang chạy |

Không điền API key thật vào file bàn giao hoặc frontend. Nếu backend web gọi API thì CORS trình duyệt không áp dụng; chỉ cần cấu hình DASHBOARD_ORIGINS khi browser gọi trực tiếp. Chọn **một nguồn gửi mẫu**: backend web gửi thì ESP32 không gửi thêm cùng mẫu vào AI.

## Tích hợp nhanh bằng JavaScript phía server

Copy `web_client/ai-client.mjs` vào backend có `fetch` (đã kiểm thử Node 22.20.0), không cần npm package. Đặt URL/key trong biến môi trường server. Xem hook đầy đủ ở `web_client/example.mjs`.

```javascript
import { createAiClient } from "./ai-client.mjs";

const ai = createAiClient({
  baseUrl: process.env.AI_API_URL,
  apiKey: process.env.AI_API_KEY
});

// Đặt trong luồng đang nhận dữ liệu thiết bị, chỉ chạy một lần cho mỗi mẫu mới.
try {
  const result = await ai.sendSample({
    device_id: sensor.device_id,
    temperature: sensor.temperature,
    infrared: sensor.infrared
  });
  // Lưu result hoặc gửi qua socket cho Dashboard bằng code hiện có của web.
} catch (error) {
  // Vẫn lưu số liệu cảm biến; báo AI chưa sẵn sàng. Không gán NORMAL khi lỗi.
}
```

Body ví dụ: `{"device_id":"esp32_01","temperature":29.2,"infrared":0}`. Nhiệt độ là số °C trong [-40,125]; IR là số nguyên 0/1, với 1=có tín hiệu lửa. Không gửi chuỗi `"29.2"` hoặc boolean.

Gửi khoảng 1 mẫu/giây, tuần tự theo mỗi device; giữ nguyên ID và thứ tự dữ liệu. Không gửi lại lịch sử hoặc gửi khi refresh trang/poll trạng thái. Không tự replay POST sau timeout vì server có thể đã nhận mẫu. Client có timeout 120 giây để xử lý cold start; không có retry ngầm. Backend phải quản lý luồng theo từng thiết bị để không chồng request hoặc tích tụ mẫu cũ khi mạng chậm. API hiện chưa nhận sample_id/timestamp thiết bị để chống trùng hoặc phát hiện mẫu quá cũ.

## Response để Dashboard hiển thị

| `status` | `risk_level` | Hiển thị |
| --- | --- | --- |
| `COLLECTING` | `UNKNOWN` | Đang thu 10 mẫu, chưa có kết quả AI. |
| `NORMAL` | `LOW` | Model chưa đánh dấu bất thường. |
| `ANOMALY` | `MEDIUM` | Có bất thường, cần kiểm tra. |
| `FLAME_SIGNAL` | `HIGH` | Cảm biến IR báo tín hiệu lửa. |

Response giữ các field `device_id`, `status`, `risk_level`, `source`, `sensors`, `ai`, `alarm_suggested`, `timestamp`, `online`. `ai.ready=false` khi chưa đủ mẫu hoặc AI lỗi; `score` không phải xác suất cháy. Ngừng gửi >=10 giây thì lần gửi lại bắt đầu cửa sổ mới. GET trả `online=false` sau 10 giây không có mẫu và giữ timestamp cuối. Chưa có mẫu hoặc server vừa restart: GET trả 404.

Xử lý lỗi: 401=key sai/thiếu; 422=payload sai; 503=model lỗi. Khi IR=1 mà AI lỗi, vẫn nhận FLAME_SIGNAL với `ai.result=MODEL_ERROR`. Không có trạng thái xác nhận cháy. Model hiện **bỏ sót 100–120°C cố định**; chỉ tích hợp thử nghiệm và giữ cảnh báo nhiệt độ/IR độc lập.

## Kiểm tra kết nối từ máy backend web

Import `web_client/ai-api.postman_collection.json` và `web_client/local.postman_environment.json` vào Postman. Chọn environment, đặt `base_url` thực và `api_key` riêng. Request gửi mẫu chỉ gửi một mẫu, cần gửi đủ 10 mẫu của cùng ID để AI ready.

Hoặc dùng client kiểm thử HTTP thật:

```powershell
$env:AI_API_URL = "http://127.0.0.1:8000" # Thay bằng URL thực
# Đặt AI_API_KEY qua cấu hình riêng của backend, không commit key.
node web_client\verify.mjs
```

Script tạo ID thử mới, kiểm tra health, key sai, 404, warmup, NORMAL, ANOMALY, IR và GET. Không gửi vào ID thiết bị thật. Sau deploy phải chạy lại với HTTPS thực, không coi kiểm thử local là deploy thành công.

## Phần dành cho người vận hành API

Source deploy ở `AI_Fire_Detection_Handoff`, có `render.yaml`, `model.joblib` và requirements khóa scikit-learn 1.6.1. Xem README để chạy local/deploy. Cấp API key riêng cho backend web; key client `AI_API_KEY` phải bằng biến `API_KEY` của API. Giữ **1 worker/instance**, trạng thái đang lưu RAM và mất sau restart.

Để kiểm tra cả API và client web từ source bằng server tạm: `.\.venv\Scripts\python.exe scripts\verify_local.py --check-web-client`. Chưa push GitHub hay deploy Render trong lần chuẩn bị này; URL cloud chưa được cấp.
