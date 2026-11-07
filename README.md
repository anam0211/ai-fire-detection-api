# AI Fire Detection API — bàn giao FastAPI / Render

API phục vụ model Isolation Forest có sẵn để ESP32 và Dashboard chỉ cần gọi URL HTTP/HTTPS. Không cần chạy model trên máy của người tích hợp. Model được giữ nguyên, không huấn luyện lại.

**Giao nhanh cho backend web đã nhận số liệu thiết bị:** gửi `AI_Fire_Web_Integration.zip` cùng URL/key thực sau deploy. Xem [WEB_INTEGRATION.md](WEB_INTEGRATION.md); có client JavaScript, ví dụ gắn vào luồng nhận mẫu, Postman và `openapi.json` mô tả cả request/response. Gói web không cần model/Python. Tạo lại gói bằng `python scripts/build_web_handoff.py`.

`AI_Fire_API_Render.zip` là gói source triển khai đầy đủ, gồm model gốc và cấu hình Render; giải nén rồi đưa nội dung lên repo theo hướng dẫn phía dưới. Tạo lại cả gói source và gói web bằng `python scripts/build_handoff.py` từ source gốc. ZIP sinh ra không cần đưa vào Git.

**Trạng thái:** đã kiểm thử local bằng model thật và HTTP thật; chưa deploy Render, chưa có URL cloud đã xác minh. Xem [TEST_REPORT.md](TEST_REPORT.md).

## Những gì được giữ nguyên và thay đổi

Giữ ba endpoint `GET /health`, `POST /api/v1/sensor-data`, `GET /api/v1/status/{device_id}` và chín trường JSON: `device_id`, `status`, `risk_level`, `source`, `sensors`, `ai`, `alarm_suggested`, `timestamp`, `online`. Giữ cửa sổ trượt 10 mẫu **riêng cho từng thiết bị**, bốn đặc trưng float32 và quy tắc `decision_function < 0` là `ANOMALY`. Không thêm ngưỡng nhiệt độ để thay quyết định của model.

Thay đổi cần thiết cho triển khai Internet:

- Hai endpoint dữ liệu yêu cầu header `X-API-Key`; thiếu/sai trả `401`. `/health` công khai để Render kiểm tra. Swagger `/docs`, `/redoc` và schema `/openapi.json` công khai nhưng gọi dữ liệu vẫn cần key.
- Chỉ chấp nhận số JSON hữu hạn cho nhiệt độ, số nguyên JSON `0/1` cho IR; không tự đổi chuỗi/bool thành số. Dữ liệu lỗi trả `422`, không sửa lịch sử. Trường dư vẫn được bỏ qua như trước.
- Lỗi suy luận trả `503`, không ghi mẫu gây lỗi vào lịch sử. Riêng mẫu `infrared=1` vẫn trả `200 FLAME_SIGNAL`, với `ai.result=MODEL_ERROR`, `ai.ready=false`, `ai.score=null` nếu AI lỗi. Đây là giá trị bổ sung duy nhất cho `ai.result`.
- `/health` trả `503` sau lỗi suy luận, trở về `200` sau lần suy luận thành công hoặc khởi động lại thành công. Thiếu/hỏng/sai phiên bản model làm startup thất bại với thông báo rõ trong log.
- CORS lấy từ `DASHBOARD_ORIGINS`, cắt khoảng trắng và chỉ nhận origin cụ thể, không dùng `*`.
- Khi thiết bị không gửi mẫu trong ít nhất 10 giây, mẫu tiếp theo bắt đầu cửa sổ mới. AI thu lại 10 mẫu; không ghép dữ liệu trước và sau khi offline. IR=1 vẫn trả `FLAME_SIGNAL` ngay.

## Cài và chạy local (Windows PowerShell)

Mở terminal trong thư mục có `api.py` và `model.joblib`. Python **3.13** đã được kiểm thử; dùng môi trường mới nếu môi trường cũ đang có scikit-learn 1.9.x.

```powershell
cd D:\fire_ai_colab_bundle\fire_ai_colab\AI_Fire_Detection_Handoff
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:API_KEY = & .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
$env:DASHBOARD_ORIGINS = "http://localhost:5173,http://localhost:3000"
$env:PORT = "8000"
.\.venv\Scripts\python.exe api.py
```

URL local: `http://127.0.0.1:8000`; Swagger: `http://127.0.0.1:8000/docs`. Trong Swagger bấm **Authorize**, nhập key hiện có trong `$env:API_KEY`. Giữ key riêng; đừng gửi qua query string hoặc commit Git.

`.env.example` chỉ là mẫu tài liệu, **không tự được nạp**. Cấu hình bằng biến môi trường PowerShell hoặc Environment của Render. Không cần bật PowerShell activation để chạy các lệnh trên.

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
$headers = @{ "X-API-Key" = $env:API_KEY }
$body = @{ device_id="esp32_01"; temperature=29.2; infrared=0 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/sensor-data -Headers $headers -ContentType application/json -Body $body
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/status/esp32_01 -Headers $headers
```

Nếu dùng terminal thứ hai, đặt **cùng key** đã cấp cho server vào biến môi trường của terminal đó. Gửi khoảng một mẫu/giây; sau 10 mẫu hợp lệ AI mới sẵn sàng.

## Chạy kiểm thử

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\verify_local.py
```

`verify_local.py` mở server tạm bằng key ngẫu nhiên và PORT khả dụng, chạy smoke test qua HTTP thật (kể cả offline sau 10 giây), rồi dừng server đó. Không ảnh hưởng server bạn đang chạy. Test dùng model gốc cho NORMAL/ANOMALY; chỉ mock trong các ca lỗi có chủ đích.

Kiểm thử một server đang chạy hoặc URL Render sau deploy:

```powershell
# API_KEY phải là key của chính server được kiểm thử.
.\.venv\Scripts\python.exe scripts\smoke_test.py --base-url http://127.0.0.1:8000 --check-offline
.\.venv\Scripts\python.exe scripts\smoke_test.py --base-url https://YOUR-SERVICE.onrender.com --interval 1 --check-offline
```

Smoke test dùng `device_id` ngẫu nhiên có tiền tố `smoke_`; nó tạo dữ liệu thử trên API đích và không gửi vào ID thiết bị thật. Timeout mặc định 120 giây cho mỗi request. Không replay POST tự động sau timeout vì server có thể đã nhận mẫu.

## Đưa source lên GitHub — người sở hữu thực hiện

Nên tạo repo riêng từ **nội dung** `AI_Fire_Detection_Handoff` để tránh lẫn các dự án khác. Tạo một repository GitHub trống, không kèm README tự sinh. Các lệnh sau chỉ là hướng dẫn; chưa được chạy thay bạn:

```powershell
cd D:\fire_ai_colab_bundle\fire_ai_colab\AI_Fire_Detection_Handoff
git init
git branch -M main
git add --dry-run .
git add .
git diff --cached --name-only
git ls-files --error-unmatch model.joblib
git status --short
# Sau khi kiểm tra staging không có secrets, .venv, dữ liệu riêng:
git commit -m "Prepare AI Fire Detection API for Render"
git remote add origin https://github.com/YOUR-ORG/YOUR-REPO.git
git push -u origin main
```

`model.joblib` khoảng 748 KB, phải có trong commit; không cần Git LFS. `.gitignore` không loại model. `.venv*`, cache, `.env`, `secrets.h`, khóa/cert riêng và CSV ngoài file mô phỏng được loại. Nếu một secret đã được track từ trước, `.gitignore` không gỡ nó: xoay key và xử lý trước khi push.

## Deploy Render

Repo khuyến nghị chứa `render.yaml`, `.python-version`, `api.py`, `model.joblib` ở root. Blueprint dùng cấu hình trong [tài liệu Render](https://render.com/docs/blueprint-spec), tạo một Python Web Service; deploy là thao tác thủ công của chủ dự án.

1. Trên Render chọn **New → Blueprint**, kết nối repository, chọn `render.yaml`.
2. Nhập `DASHBOARD_ORIGINS` là domain thật, ví dụ `https://dashboard.example.com`, không có dấu `/` cuối. Nhiều origin ngăn cách bằng dấu phẩy. Có thể để rỗng nếu không có browser gọi trực tiếp.
3. `API_KEY` được Blueprint sinh tự động; lấy key trong phần Environment và cấp riêng cho bên tích hợp. Nếu tạo Web Service thủ công, phải tự sinh key ít nhất 32 ký tự.
4. Cấu hình build `pip install -r requirements.txt`, start `python api.py`, health `/health`, một instance. `.python-version` chọn Python 3.13 theo [cơ chế chọn Python của Render](https://render.com/docs/python-version); không đặt biến `PYTHON_VERSION` xung đột.
5. Đọc log: startup phải nạp thành công model; `/health` trả `200`. Start script đọc PORT Render cung cấp và bind `0.0.0.0`. Render cung cấp HTTPS cho Web Service theo [hướng dẫn FastAPI](https://render.com/docs/deploy-fastapi).
6. Ghi lại URL Render cấp, ví dụ `https://YOUR-SERVICE.onrender.com`. Chạy smoke test HTTPS ở trên, kiểm tra CORS từ domain Dashboard thật, rồi kiểm tra ESP32 thực tế. Chỉ xác nhận deploy thành công khi các bước này đạt.

Nếu tạo Web Service thủ công: Runtime `Python 3`, các lệnh như bước 4; thiết lập hai biến `API_KEY`, `DASHBOARD_ORIGINS` như [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md). Nếu đặt source trong subfolder của repo lớn, đặt **Root Directory** đúng thư mục chứa `api.py`, `model.joblib`, `.python-version`; Blueprint có thể cần `rootDir` tương ứng. Repo bàn giao độc lập không cần cấu hình này.

Blueprint tắt tự động deploy (`autoDeployTrigger: off`). Cấu hình mặc định dùng plan Free; kiểm tra khả dụng/chi phí trên tài khoản trước khi tạo. Free service có thể ngủ khi không hoạt động, xem [giới hạn Render Free](https://render.com/docs/free). Cold start, restart, redeploy đều có thể làm mất trạng thái RAM; thành viên tích hợp cần chờ thu lại 10 mẫu. Không dùng nhiều worker/instance với phiên bản lưu RAM này. Khi cần mở rộng hoặc lưu bền, phải chuyển trạng thái chung sang Redis/database qua một thay đổi riêng.

## Model và giới hạn đã quan sát

- SHA-256 model gốc và bản bàn giao: `9986dbd0f66591b8a406a0450fad0ddc83fd726155ec650d9638ff4a90637bd2`.
- Artifact: scikit-learn 1.6.1, 150 cây, contamination 0.05, `window_size=10`, chu kỳ huấn luyện 1000 ms. `requirements.txt` khóa phiên bản runtime đã thử. NumPy/SciPy/joblib là phiên bản đã kiểm thử với artifact; không có bản ghi đầy đủ các dependency khi train để khẳng định môi trường giống hoàn toàn.
- Model nạp bằng `Path(__file__).resolve().parent / "model.joblib"`, không phụ thuộc thư mục terminal. Chỉ nạp artifact đáng tin cậy. Theo [scikit-learn 1.6](https://scikit-learn.org/1.6/model_persistence.html), dùng model khác phiên bản scikit-learn không được hỗ trợ.
- `ANOMALY` nghĩa là bất thường theo model, không phải xác nhận cháy. `FLAME_SIGNAL` là tín hiệu trực tiếp của cảm biến IR, không phải kết luận AI. `score` không phải xác suất cháy.
- Kiểm thử thật cho thấy bước nhảy từ khoảng 29°C lên 120°C có score âm; **10 mẫu cố định 100°C lại cho score dương / NORMAL**. `NORMAL` không xác nhận an toàn. Không sửa model/ngưỡng để che giới hạn này. ESP32 cần logic cảnh báo nhiệt độ/IR độc lập đã được kiểm thử phù hợp với hệ thống thực.
- Cửa sổ theo **số mẫu**, bắt đầu lại sau khoảng ngừng gửi >=10 giây. API chưa kiểm tra chính xác chu kỳ 1 Hz; client nên gửi khoảng 1 mẫu/giây và kiểm soát dữ liệu cảm biến lỗi.
- RAM chỉ lưu 10 mẫu gần nhất và một trạng thái cho mỗi ID; chưa có hạn mức tổng số ID, rate limiting hay phân quyền từng thiết bị. Key chung cho phép gọi mọi ID. Cấp key chỉ cho thành viên tin cậy và đặt gateway/rate limiting nếu cần sử dụng rộng.

`train_fire_ai_colab.ipynb` được giữ làm tài liệu nguồn; không chạy notebook trong quy trình deploy/bàn giao vì nó có lệnh huấn luyện và ghi model. `example_normal_SIMULATED.csv` là dữ liệu mô phỏng, chỉ dùng kiểm thử kỹ thuật, không chứng minh độ chính xác phát hiện cháy.

## Tài liệu và bộ bàn giao

- [API_DOCUMENTATION.md](API_DOCUMENTATION.md): request/response, status và lỗi.
- [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md): ESP32, Dashboard, fetch, HTTPS.
- [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md): các biến cần cấp.
- [TEST_REPORT.md](TEST_REPORT.md): kết quả và phạm vi kiểm chứng thực tế.
- `examples/dashboard_fetch.js`, `examples/esp32_http_https/`: ví dụ tích hợp.
- `scripts/smoke_test.py`: kiểm thử URL local hoặc HTTPS, chỉ cần Python standard library.
- `scripts/build_handoff.py`: chạy từ source gốc để tạo/cập nhật bộ bàn giao bằng allowlist, không copy môi trường ảo, secret hoặc file tạm. `HANDOFF_MANIFEST.json` ghi SHA-256 từng file trong bộ bàn giao.

Sau deploy, bàn giao **URL thật, X-API-Key qua kênh riêng, device_id, origin Dashboard đã cho phép và ngày/kết quả smoke test HTTPS**. Hiện URL cloud vẫn chưa được cấp/xác minh.
