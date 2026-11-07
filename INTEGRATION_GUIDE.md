# Hướng dẫn tích hợp ESP32 và Dashboard

Người tích hợp chỉ cần kết nối mạng, URL HTTPS, key và ID thiết bị; không cần Python/scikit-learn/model trên ESP32 hoặc máy xem Dashboard. Python chỉ cần cho người vận hành API hoặc chạy script kiểm thử tùy chọn.

## Thông tin chủ API phải cấp

| Thông tin | Ví dụ / lưu ý |
| --- | --- |
| API base URL | URL thực từ Render, dạng `https://YOUR-SERVICE.onrender.com`; ví dụ này là placeholder, chưa deploy. |
| API key | Cấp riêng, gửi bằng `X-API-Key`; không nhúng vào repo, ảnh chụp hoặc URL. |
| Device ID | `esp32_01`, duy nhất; Dashboard đọc đúng ID ESP32 gửi. |
| Dashboard origin | Ví dụ `https://dashboard.example.com`; chủ API đưa vào `DASHBOARD_ORIGINS`. Origin gồm scheme + hostname + port nếu có, không có path hoặc `/` cuối. |
| Nhịp gửi / warmup | Khoảng 1 mẫu/giây, 10 mẫu của từng ID trước khi AI sẵn sàng. |

## ESP32

Ví dụ Arduino ở `examples/esp32_http_https/esp32_http_https.ino`, dùng thư viện của Arduino-ESP32: WiFi, HTTPClient, WiFiClientSecure và FreeRTOS. Tham khảo [Wi-Fi API chính thức của Espressif](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/wifi.html).

1. Mở sketch bằng Arduino IDE, cài/chọn board ESP32 phù hợp.
2. Copy `secrets.example.h` thành `secrets.h` ở cùng thư mục, đặt Wi-Fi, base URL, API key và device ID. `secrets.h` bị Git ignore và không vào gói bàn giao.
3. Chọn `IR_PIN` đúng mạch. Ví dụ dùng DO active LOW nên chuyển `digitalRead(IR_PIN) == LOW ? 1 : 0`. Nếu cảm biến của bạn active HIGH thì đổi quy tắc này. API luôn cần `1 = có tín hiệu lửa`, không nhận raw active-LOW trực tiếp.
4. **Thay `readTemperatureC()` bằng đọc cảm biến thật.** Giá trị trả `29.2` hiện chỉ là mô phỏng kiểm thử giao tiếp; trả `NAN` khi cảm biến lỗi, không thay lỗi bằng `0`.
5. Với HTTP local, đặt `API_BASE_URL=http://<IP-LAN-của-máy-chạy-API>:8000`; ESP32 và server cùng LAN, server cho phép kết nối cổng đó. `127.0.0.1` trên ESP32 là chính ESP32. API key qua HTTP chỉ phù hợp LAN thử nghiệm được kiểm soát; cloud dùng HTTPS.
6. Với Render HTTPS, đồng bộ giờ qua NTP và điền PEM **root CA** phù hợp chuỗi chứng chỉ của hostname vào `API_ROOT_CA`. Lấy root từ kho chính thức của đơn vị cấp chứng chỉ sau khi kiểm tra issuer/fingerprint; không đoán CA cố định cho mọi service. Ví dụ để CA rỗng để ngăn gửi HTTPS khi chưa cấu hình. Không dùng `setInsecure()`.
7. Compile/upload bằng toolchain của bạn, theo dõi Serial và đối chiếu `GET status`. Bản bàn giao chưa được compile bằng Arduino CLI hoặc chạy trên phần cứng, nên chủ thiết bị cần thực hiện bước này.

Mẫu header/body gửi đi:

```http
POST /api/v1/sensor-data HTTP/1.1
Host: YOUR-SERVICE.onrender.com
Content-Type: application/json
X-API-Key: <key đã cấp>

{"device_id":"esp32_01","temperature":29.2,"infrared":0}
```

Sketch đọc mẫu khoảng 1 Hz trong `loop()`, gọi hook `localSafetyTick()` và đưa mẫu vào queue một phần tử. Task mạng lấy mẫu riêng; khi mạng chậm chỉ giữ mẫu mới nhất đang chờ, không gửi bù cả backlog và không đọc cảm biến đồng thời ở hai task. Hook local hiện chỉ log tín hiệu, **chưa phải logic điều khiển cảnh báo của dự án**; hãy nối logic local độc lập đã được thiết kế/kiểm thử vào đây.

Timeout kết nối/HTTP trong ví dụ là 5 giây. Khi Render cold start lâu hơn, một vài lần gửi có thể thất bại; client tiếp tục gửi mẫu mới ở chu kỳ tiếp theo. Nếu cần timeout dài hơn, chỉnh trong task mạng, không chặn vòng xử lý cảnh báo local. Tần suất mẫu được server nhận có thể thấp hơn 1 Hz khi mạng chậm. Chưa có timestamp/sequence từ ESP32 để server bù lại thời gian.

`401`: kiểm tra key; `422`: kiểm tra kiểu số, khoảng nhiệt độ và IR; `503`: AI đang lỗi. Mã âm của HTTPClient là lỗi transport, không phải HTTP status. Không tự gửi lại cùng POST sau timeout vì request trước có thể đã vào cửa sổ. Cảnh báo tại thiết bị phải tiếp tục khi Wi-Fi, API hoặc model không sẵn sàng.

## Dashboard JavaScript fetch

`examples/dashboard_fetch.js` là ES module, có hai hàm gửi mẫu và đọc trạng thái, timeout và kiểm tra HTTP status. Không phụ thuộc npm package. Cấp URL/key lúc chạy; không có key thật trong ví dụ.

```javascript
import { createFireApi } from "./examples/dashboard_fetch.js";

// keyEnteredAtRuntime chỉ phù hợp một Dashboard nội bộ cho người đã được cấp key.
const api = createFireApi("https://YOUR-SERVICE.onrender.com", keyEnteredAtRuntime);
const status = await api.getStatus("esp32_01");
console.log(status.status, status.online, status.ai.ready, status.timestamp);

// Dùng trên trang thử nghiệm gửi cảm biến; Dashboard chỉ xem trạng thái thì không POST.
const result = await api.sendSample("esp32_test", 29.2, 0);
```

Phiên bản fetch tối thiểu, có xử lý lỗi:

```javascript
const response = await fetch(`${baseUrl}/api/v1/status/${encodeURIComponent(deviceId)}`, {
  headers: { "X-API-Key": apiKey }
});
const body = await response.json();
if (!response.ok) throw new Error(`HTTP ${response.status}: ${JSON.stringify(body.detail)}`);
renderStatus(body);
```

API key trong trình duyệt **luôn có thể xem được** qua DevTools/network/source. CORS không làm key bí mật. Dashboard công khai nên gọi backend/proxy của Dashboard, để backend giữ `API_KEY` và cấp quyền người dùng phù hợp. Cách gọi trực tiếp chỉ dành cho nhóm nội bộ được chủ API cấp quyền chung. Không lưu key vào bundle công khai, localStorage hay Git. Không đưa key vào query string.

Chạy Dashboard qua HTTP local (ví dụ dev server `localhost:5173`) hoặc HTTPS thật; mở file HTML bằng `file://` không khớp origin cho phép. Browser sẽ gửi OPTIONS preflight khi có `X-API-Key`; API đã cho phép GET, POST và header Content-Type/X-API-Key. Origin sai sẽ bị browser chặn đọc dù gọi bằng ESP32/curl vẫn hoạt động.

Poll tuần tự khoảng 2 giây/lần: chờ request trước hoàn tất rồi đặt lần tiếp theo, tránh chồng request lúc cold start. Xử lý hiển thị:

| Tình huống | Nội dung phù hợp |
| --- | --- |
| `404` | Chưa có dữ liệu cho ID này; có thể API vừa restart. |
| `COLLECTING`, `ai.ready=false` | Đang thu 10 mẫu; chưa có kết quả AI. |
| Gửi lại sau khoảng ngừng >=10 giây | AI thu lại 10 mẫu mới, IR vẫn có hiệu lực ngay. |
| `NORMAL` | Model chưa thấy bất thường; không khẳng định an toàn. |
| `ANOMALY` | Bất thường nhiệt độ/IR; cần kiểm tra, không ghi “AI xác nhận cháy”. |
| `FLAME_SIGNAL` | Cảm biến IR có tín hiệu lửa; nguồn `DIRECT_SENSOR`. |
| `ai.result=MODEL_ERROR` | AI lỗi; tín hiệu IR vẫn được giữ nếu có. |
| `online=false` | Hiển thị mất kết nối cùng timestamp/kết quả cuối, tránh trình bày như dữ liệu mới. |
| Timeout, `503`, lỗi mạng | API/AI chưa sẵn sàng; không suy diễn thành NORMAL hoặc an toàn. |

## Kiểm thử và nghiệm thu URL cloud

Chủ API chạy script từ máy có Python (người dùng Dashboard không cần cài):

```powershell
# Đặt key Render thực vào API_KEY của terminal qua kênh cấu hình riêng.
python scripts\smoke_test.py --base-url https://YOUR-SERVICE.onrender.com --interval 1 --check-offline
```

Script xác minh health, key thiếu/sai, 404, thu 10 mẫu normal, tăng nhiệt độ bất thường, IR=1, dữ liệu sai, hai ID tách biệt và offline sau 10 giây. Script tạo ID thử riêng; không dùng ID thiết bị thật. Ghi lại URL thật, ngày, kết quả và prefix thiết bị thử.

Sau đó kiểm tra từ **origin Dashboard thật** (không chỉ curl), và từ ESP32 với CA/NTP/sensor thật. Kiểm tra mất mạng/restart: dữ liệu RAM mất khi process khởi động lại, Dashboard có thể nhận 404 rồi COLLECTING, ESP32 tiếp tục cảnh báo local. Chỉ sau khi kiểm thử HTTPS và tích hợp thực tế đạt mới ghi nhận cloud triển khai thành công. Local HTTP đã đạt không thay cho kiểm thử cloud.
