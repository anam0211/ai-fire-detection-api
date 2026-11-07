# Kiểm tra và sửa phần AI — 07/11/2026

## Các vấn đề đã tái hiện và sửa

1. **Môi trường `.venv` không nạp được model.** Chạy `api.load_model()` tái hiện lỗi `scikit-learn must be 1.6.1; got 1.9.1`. Đã cài dependency theo requirements vào chính `.venv`, đưa scikit-learn về 1.6.1. Không bỏ kiểm tra phiên bản hoặc nạp model bằng phiên bản khác.
2. **Cửa sổ chứa mẫu trước khi thiết bị offline.** Sau khi ngừng gửi 10 hoặc 60 giây, API vẫn dùng chín mẫu cũ với một mẫu mới để suy luận. Bốn ca regression tái hiện trước khi sửa đều thất bại. Đã sửa để mẫu đầu sau khoảng ngừng >=10 giây bắt đầu cửa sổ mới; cần thu lại 10 mẫu. IR=1 vẫn ưu tiên FLAME_SIGNAL ngay. Không ảnh hưởng lịch sử thiết bị khác.

Không đổi model, thứ tự/cách tính đặc trưng hoặc ngưỡng score. Giữ endpoint và cấu trúc JSON. Thay đổi hành vi khi kết nối lại được ghi trong API_DOCUMENTATION.md.

## Kết quả sau sửa

Chạy bằng Python 3.13.5 trong **`.venv`** của dự án:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\verify_local.py
```

- `pip check`: không có dependency bị lỗi.
- **65 passed**, một deprecation warning của Starlette TestClient về httpx; không có lỗi phiên bản model.
- HTTP thật tại cổng tạm `http://127.0.0.1:49250`: PASS health, xác thực, NORMAL sau 10 mẫu, hai thiết bị độc lập, ANOMALY, FLAME_SIGNAL, validation, offline và thu cửa sổ mới khi kết nối lại. Server tạm đã dừng.
- Bổ sung đối chiếu trực tiếp `model.predict` / `decision_function` với response API cho mẫu bình thường, 100°C cố định, 120°C cố định và bước nhảy nhiệt độ. API trả đúng kết quả artifact, không ép nhãn.
- Các test cũ về JSON, lỗi model, rollback, IR fallback, CORS, ID và đường dẫn model vẫn đạt.

Runtime ML đã kiểm thử: scikit-learn 1.6.1, NumPy 2.2.6, SciPy 1.15.3, joblib 1.4.2. Model gốc 748139 byte, SHA-256:

```text
9986dbd0f66591b8a406a0450fad0ddc83fd726155ec650d9638ff4a90637bd2
```

## Vấn đề của model chưa được sửa

Kết quả gọi trực tiếp model, độc lập với API:

| Đầu vào cửa sổ, IR=0 | Score | Nhãn model |
| --- | --- | --- |
| 10 mẫu cố định 29.2°C | 0.13320734 | NORMAL |
| 10 mẫu cố định 100°C | 0.05758513 | NORMAL |
| 10 mẫu cố định 120°C | 0.05758513 | NORMAL |
| Fixture normal rồi thay mẫu cuối bằng 120°C | -0.01766559 | ANOMALY |

Đây là giới hạn của artifact hiện tại, chưa được khắc phục bằng việc sửa môi trường/cửa sổ. Không có đủ căn cứ để tự đặt ngưỡng nhiệt độ khác hoặc đổi điểm model. Không huấn luyện lại hay ghi đè model theo yêu cầu ban đầu. Các test đạt xác minh code và giao tiếp; **không chứng minh model phát hiện đúng mọi trường hợp nhiệt độ bất thường**.

## Phạm vi xác minh

Đã kiểm thử local; chưa deploy Render hoặc kiểm thử URL HTTPS cloud, Dashboard thật hay ESP32 phần cứng. Bộ bàn giao được cập nhật từ allowlist, có manifest SHA-256; không copy virtualenv, cache hoặc secrets.

Chạy từ chính `AI_Fire_Detection_Handoff` cũng đạt **65 passed**, cùng một deprecation warning. HTTP thật tại cổng tạm `http://127.0.0.1:49681` PASS toàn bộ smoke test, gồm offline và cửa sổ mới khi kết nối lại; server đã dừng. Đã đối chiếu manifest từng file và hash model giữa source/bàn giao.

## Bàn giao API cho backend web

Bổ sung schema response trong Swagger/OpenAPI, giữ nguyên JSON/endpoint và quyết định model. `openapi.json` có enum trạng thái, toàn bộ field response và header API key. Thêm client `web_client/ai-client.mjs`, hook nhận mẫu `example.mjs`, script `verify.mjs`, template cấu hình và collection/environment Postman không chứa key thật. `WEB_INTEGRATION.md` hướng dẫn backend web gửi mỗi mẫu mới đúng một lần, không gửi lặp theo việc refresh Dashboard.

Sau bổ sung, chạy bằng `.venv`: **66 passed**, cùng một deprecation warning TestClient. `pip check` đạt. `scripts/verify_local.py --check-web-client` chạy server thật tại cổng tạm `http://127.0.0.1:52023`: smoke test Python và client Node 22.20.0 đều PASS. Client Node kiểm tra health, key sai, 404, thu mẫu, NORMAL, ANOMALY, IR, GET và validation. Server tạm đã dừng; đây không phải URL cloud.

`AI_Fire_Web_Integration.zip` chứa 9 file dành cho web, không chứa model, virtualenv hoặc key thật. Đã kiểm tra ZIP, JSON cấu hình, schema response và cú pháp JavaScript. Postman chưa được chạy bằng ứng dụng Postman; client Node đã được kiểm thử qua HTTP thật. Model gốc vẫn giữ nguyên hash. Chưa push GitHub/deploy Render, chưa có URL HTTPS cloud được xác minh.

Bản `AI_Fire_Detection_Handoff` cập nhật cũng đạt **66 passed**, cùng một cảnh báo TestClient. Kiểm thử HTTP thật và client Node từ chính bản bàn giao tại cổng tạm `http://127.0.0.1:59021` đều PASS; server đã dừng. Gói source `AI_Fire_API_Render.zip` hiện gồm 35 file allowlist và manifest, có model gốc, không có virtualenv/cache/key thật. Hash model trong ZIP và từng file của manifest đã được đối chiếu.

## Chuẩn bị push và triển khai sau khi được cho phép

Đã tạo repository Git local tại `AI_Fire_Detection_Handoff`, nhánh `main`, và commit bộ source đã kiểm tra. `.gitattributes` giữ nguyên byte của file giữa Windows/Linux để checksum trong manifest không thay đổi khi checkout. Đã kiểm tra từng file được stage khớp manifest và model giữ nguyên SHA-256. `.git` không đi vào ZIP bàn giao.

Tại bước này GitHub và Render chưa được kết nối với tài khoản qua các kết nối ứng dụng; không có GitHub/Render CLI hoặc token tương ứng trong môi trường. Đã tìm được ứng dụng hỗ trợ cả hai dịch vụ. Chưa tạo repository từ xa, chưa push hoặc deploy; chưa có URL HTTPS đã xác minh. Cần hoàn tất kết nối tài khoản để tiếp tục, không cần cấp lại quyền push/deploy.
