# Biến môi trường và thông số tích hợp

| Biến | Bắt buộc | Giá trị / cách dùng |
| --- | --- | --- |
| `API_KEY` | Có | Secret ít nhất 32 ký tự, không có khoảng trắng đầu/cuối. Server từ chối startup nếu thiếu/ngắn. Sinh bằng `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Blueprint tự sinh; nếu tạo service thủ công thì tự đặt. Client gửi bằng `X-API-Key`. |
| `DASHBOARD_ORIGINS` | Cần đặt trên cloud khi browser gọi trực tiếp | Danh sách origin ngăn bởi dấu phẩy, ví dụ `https://dashboard.example.com,http://localhost:5173`. Không path, query, wildcard hoặc `/` cuối. Mặc định local: `http://localhost:5173,http://localhost:3000`. Chuỗi rỗng tắt cấp quyền CORS cho browser khác origin. |
| `PORT` | Render tự cấp | Script `python api.py` bind `0.0.0.0:<PORT>`. Local mặc định `8000`; không ghi đè giá trị Render cấp. |
| `PYTHONUNBUFFERED` | Không | Blueprint đặt `1` để log Python xuất ngay. |
| `PYTHON_VERSION` | Không cần | `.python-version` đã chọn `3.13`. Nếu tài khoản Render đã có biến này, xóa hoặc đặt đúng Python 3.13.x; biến môi trường có độ ưu tiên cao hơn file. |
| `API_BASE_URL` | Chỉ tiện cho smoke test | URL API local hoặc cloud thực. Client tự giữ cấu hình base URL; đây không phải biến thay đổi địa chỉ server FastAPI. Có thể thay bằng tham số `--base-url`. |

Không có biến để đổi model path, window, features hoặc score threshold: các giá trị này được khóa theo artifact đã huấn luyện. Khởi động lại/redeploy khi thay `API_KEY` hoặc CORS. Key không xuất trong log ứng dụng, không lưu trong repo hoặc handoff manifest.

`.env.example` không chứa key, chỉ là mẫu. API **không dùng python-dotenv**, không tự đọc `.env`. Windows đặt bằng `$env:NAME = "value"`; Render đặt trong Environment của service. Giữ key giống nhau giữa API, script kiểm thử và client được cấp quyền. Xoay key bằng cách cập nhật server và tất cả client; bản hiện tại chỉ hỗ trợ một key chung tại một thời điểm.

| Thông số người tích hợp cần nhận | Giá trị |
| --- | --- |
| Base URL local | `http://127.0.0.1:8000` |
| Base URL cloud | **Chưa được cấp/xác minh**; lấy URL HTTPS thực từ Render sau deploy. |
| POST | `/api/v1/sensor-data` |
| GET trạng thái | `/api/v1/status/{device_id}` |
| Health | `/health` (không key) |
| Header xác thực | `X-API-Key: <cấp riêng>` |
| Body POST | `device_id`, `temperature` (°C), `infrared` (số nguyên 0/1) |
| Chu kỳ gửi | Khoảng 1 Hz, tuần tự theo từng device |
| Warmup / offline | 10 mẫu riêng mỗi ID / offline khi không có mẫu >= 10 giây; lần gửi lại bắt đầu cửa sổ mới. |
| `device_id` ví dụ | `esp32_01`, phải trùng ID Dashboard đọc |
| Origin Dashboard | Chủ dự án phải cấu hình domain thật trong `DASHBOARD_ORIGINS`. |
| Kiểm chứng cloud | Chỉ xác nhận khi smoke test HTTPS, browser CORS và ESP32 thực đã đạt. |
