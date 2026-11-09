# AI v2 thử nghiệm cho cảm biến gần bếp / nguồn nhiệt

Ngày 09/11/2026. Theo yêu cầu hiện tại, **chưa có dữ liệu cảm biến thật**: đây là bản train và kiểm thử bằng dữ liệu mô phỏng, chưa hiệu chuẩn tại vị trí lắp. V2 được chọn làm API cho backend theo bảng nhiệt/IR; xem [báo cáo triển khai](../DEPLOYMENT_REPORT.md) cho trạng thái cloud.

Model mới: `model_candidate_v2.joblib`. Model v1 ở `../model.joblib` giữ nguyên SHA-256 `9986dbd0f66591b8a406a0450fad0ddc83fd726155ec650d9638ff4a90637bd2`.

## Cách đánh giá

Model Isolation Forest được train lại trên 160 phiên normal mô phỏng, nhiệt độ nền khoảng 18–60°C và dao động/tăng giảm chậm. Đây là **giả định để phát triển phần mềm**, không phải khẳng định khoảng nhiệt độ đó an toàn tại bếp của bạn.

AI dùng 4 đặc trưng nhiệt độ trên 10 mẫu: trung bình, lớn nhất, chênh lệch cuối–đầu và độ lệch chuẩn. **IR không phải đầu vào của model nhiệt độ**. Điểm AI chỉ nói cửa sổ khác dữ liệu normal đến đâu, không phải xác suất cháy hay cấp độ nguy hiểm. Ngưỡng cảnh báo thuộc lớp policy riêng, không phải các ngưỡng model tự học.

Profile mặc định nằm trong [policy.json](policy.json), phiên bản `near-heat-demo-v2`:

| Tình huống trong profile demo | Kết quả |
| --- | --- |
| Chưa đủ mẫu, chưa thấy dấu hiệu cần cảnh báo | `UNKNOWN`, `COLLECTING` |
| Nhiệt ổn định dưới 65°C; có thể có IR từ bếp | `LOW`; IR vẫn được ghi nhận bằng `FLAME_SIGNAL` |
| Nhiệt độ hiện tại từ 65°C đến dưới 85°C | Ít nhất `MEDIUM`, cảnh báo nhiệt |
| Nhiệt độ hiện tại từ 85°C | `HIGH` ngay, không chờ AI hoặc IR |
| IR liên tiếp ít nhất 3 mẫu và kéo dài ít nhất 2 giây, kèm nhiệt độ từ 75°C | `HIGH` |
| IR đã xác nhận, nhiệt độ từ 65°C và tăng ít nhất 20°C/phút, tăng tổng ít nhất 2°C | `HIGH` |
| Nhiệt tăng ít nhất 12°C/phút, tăng tổng ít nhất 2°C trong cửa sổ quan sát hợp lệ | Ít nhất `MEDIUM` |
| AI báo bất thường ít nhất 3 lần liên tiếp, nhiệt từ 55°C, tăng tổng ít nhất 2°C và có xu hướng tăng | Ít nhất `MEDIUM` |
| Chỉ có điểm AI âm, không có bằng chứng tăng nhiệt đi kèm | Ghi nhận `ANOMALY`, không tự bật cảnh báo |

Thứ tự ưu tiên: nhiệt độ nguy hiểm → phối hợp IR/nhiệt → cảnh báo nhiệt/tăng nhiệt/AI được xác nhận → quan sát. Một hàng `LOW` trong bảng có thể được nâng lên bởi điều kiện khác. IR đơn lẻ không tự bật còi trong profile gần bếp, vì bếp đang hoạt động có thể tạo tín hiệu này. Điều đó cũng có thể bỏ sót lửa mới xuất hiện chưa làm nóng cảm biến; bản demo không thay thế hệ thống báo cháy độc lập.

`MEDIUM` và `HIGH` trả `alarm_suggested=true`; `LOW`/`UNKNOWN` trả false. Không dùng riêng `status=FLAME_SIGNAL` để bật còi. `LOW` không xác nhận an toàn.

Tốc độ tăng nhiệt tính bằng hồi quy tuyến tính theo **thời gian server nhận mẫu thực**, chỉ dùng khi cửa sổ kéo dài 5–30 giây. Gửi dồn 10 request không giả thành 10 giây đo. Đây vẫn là thời gian nhận qua mạng, chưa phải thời gian đo tại thiết bị: không replay backlog, không gửi lại POST mù sau timeout. Mỗi thiết bị gửi tuần tự khoảng 1 mẫu/giây từ một nguồn duy nhất.

Sau cảnh báo, chỉ hạ mức khi nhiệt không quá 55°C, hết IR và hết dấu hiệu tăng nhiệt, đủ ít nhất 3 mẫu và 5 giây xác nhận. Trước đó trả `RECOVERY_HOLD`. Mất mẫu từ 10 giây sẽ offline và xóa cửa sổ/counters khi kết nối lại; GET vẫn trả dữ liệu cuối với `online=false` để bên nhận xử lý mất kết nối, không coi là hết nguy hiểm. Trạng thái riêng cho từng thiết bị.

## Kết quả đã chạy

- `pytest -q`: **121 passed**, một deprecation warning TestClient; gồm kiểm tra entrypoint công khai và chính xác các trường hợp trong bảng backend đã chọn.
- [evaluation.json](evaluation.json): **21/21 kịch bản mô phỏng** đạt kỳ vọng policy, so sánh trực tiếp với model/policy v1. Bao gồm nấu ở 55°C + IR, 65/85/100/120°C không IR, IR chớp, tăng nhiệt, giảm nhiệt và nhiễu nhỏ.
- Train/calibration/test tách theo phiên: 96/32/32 phiên, tương ứng 1728/576/576 cửa sổ không chồng lặp. Không dùng test để chọn ngưỡng điểm AI.
- [model_candidate_v2.training.json](model_candidate_v2.training.json): 7/576 cửa sổ normal test mô phỏng có điểm AI âm (**1,22%**). Đây là false-positive của **model bất thường**, không phải tỷ lệ còi báo giả và không đo recall cháy thực tế.
- HTTP thật local: health, xác thực, nhiệt độ nguy hiểm ngay trước warmup, IR gần bếp, IR/nhiệt theo thời gian thật, 10 mẫu normal, tăng nhiệt theo thời gian, validation, offline và kết nối lại.
- Client Node hiện có giao tiếp được với v2; script kiểm chứng riêng ở `verify-client.mjs`.

Các kịch bản kiểm tra hành vi code theo profile demo, không phải tập cháy thực được gán nhãn độc lập. **Chưa đo độ chính xác/độ nhạy phát hiện cháy ngoài thực tế.**

## Chạy thử local

Chạy từ root repo `AI_Fire_Detection_Handoff`, dùng môi trường Python đã có ở thư mục cha:

```powershell
..\.venv-handoff\Scripts\python.exe -m pytest -q
..\.venv-handoff\Scripts\python.exe scripts\evaluate_risk_v2.py
..\.venv-handoff\Scripts\python.exe scripts\verify_risk_v2.py
```

`verify_risk_v2.py` tự tạo key thử, mở cổng trống, chạy kiểm thử và dừng server. Không gọi URL Render, không sửa `.env` và không in API key. Cần Node để kiểm tra client backend. `scripts/verify_local.py --check-web-client` kiểm tra entrypoint `api.py` dùng khi deploy.

Muốn giữ server để thử tích hợp, đặt `API_KEY` ít nhất 32 ký tự trong môi trường rồi chạy:

```powershell
..\.venv-handoff\Scripts\python.exe -m risk_v2.api
```

Mặc định: `http://127.0.0.1:8001`, Swagger `/docs`. `.env` không tự nạp. Không đổi URL/key của backend đang dùng cloud sang bản local nếu chưa chủ động chuyển môi trường thử nghiệm.

Input và các endpoint giữ như v1. Output bổ sung `assessment`: lý do, tốc độ tăng nhiệt, thời gian quan sát, phiên bản policy/model và nguồn dữ liệu train. Thêm các `status` `THERMAL_WARNING`, `THERMAL_DANGER`, `RECOVERY_HOLD` và `source` tương ứng. Backend phải chấp nhận các enum mới trước khi dùng v2. `ai.result` vẫn độc lập với risk: model có thể nói NORMAL nhưng policy nhiệt trả HIGH.

Nếu model lỗi, thông tin nhiệt/IR độc lập vẫn được đánh giá và `ai.result=MODEL_ERROR`; health trả 503. Nếu không có bằng chứng nhiệt/IR hoặc trạng thái cảnh báo cần giữ, request lỗi 503 và không ghi thêm mẫu. Không tự train tại startup.

## Thu dữ liệu thật và train tiếp

Trước khi chốt ngưỡng, cần biết **loại cảm biến, dải đo, sai số, khoảng cách tới bếp** và nhiệt độ thực khi bếp hoạt động bình thường. Nếu cảm biến không đo được tới các ngưỡng demo, không dùng profile này. Không đặt 65/75/85°C như ngưỡng chung cho mọi bếp hoặc cảm biến.

Ghi CSV theo [sensor-log.csv.example](sensor-log.csv.example): `session_id,timestamp_ms,temperature,infrared,label`. Ghi nhiều phiên độc lập khi bếp tắt, bật/nấu bình thường, tăng/giảm công suất và nguội dần. `label=normal` được phép có IR=1 nếu đó là hoạt động bếp bình thường đã kiểm tra. Các nhãn `warning`, `abnormal`, `fire` không được dùng như normal để train. Không tạo tình huống cháy nguy hiểm để lấy dữ liệu; dùng nguồn đo thử được kiểm soát hoặc dữ liệu đã xác minh.

Pipeline yêu cầu ít nhất 6 phiên và 60 cửa sổ normal hợp lệ; đây là mức tối thiểu để chạy pipeline, chưa bảo đảm dữ liệu đủ đại diện. Mỗi cửa sổ 10 mẫu, khoảng cách mẫu 0,5–2 giây; không nối qua khoảng ngừng hoặc mẫu abnormal. Toàn bộ phiên được tách riêng cho train/calibration/test. CSV thật nên nằm trong `data/` đã bị Git ignore.

```powershell
..\.venv-handoff\Scripts\python.exe scripts\train_temperature_v2.py --csv data\measured_sessions.csv --overwrite-candidate
```

CSV cần cột label. Với file đã kiểm tra chỉ chứa normal nhưng chưa có label, dùng thêm `--normal-only`. Lệnh trên chỉ thay artifact candidate, luôn từ chối ghi đè `model.joblib`. Train bằng dữ liệu thật vẫn ghi `field_validated=false`: cần tập kiểm chứng độc lập có cả normal và bất thường, đánh giá báo giả, bỏ sót và thời gian phản ứng, rồi hiệu chỉnh policy tại chỗ.

Muốn tái tạo bản mô phỏng:

```powershell
..\.venv-handoff\Scripts\python.exe scripts\train_temperature_v2.py --demo --overwrite-candidate
```

## Tài liệu tham chiếu

- [scikit-learn 1.6 IsolationForest](https://scikit-learn.org/1.6/modules/generated/sklearn.ensemble.IsolationForest.html): thuật toán phát hiện bất thường, ý nghĩa điểm và offset.
- [System Sensor 5600, hướng dẫn của nhà sản xuất](https://prod-edam.honeywell.com/content/dam/honeywell-edam/hbt/en-us/documents/manuals-and-guides/user-manuals/5600_Series_Manual_I56-2175.pdf): các model khác nhau có nhiệt độ kích hoạt và nhiệt độ môi trường lắp đặt khác nhau. Điều này cho thấy cần chọn theo thiết bị/môi trường; **không chứng nhận các ngưỡng demo trong repo**.
