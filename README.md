# Crypto-Panda: Hệ Thống Quét Thị Trường Crypto & Cảnh Báo Tự Động

[Kho GitHub](https://github.com/sjmoran/crypto-panda)
[Giấy phép: CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)
[Phiên bản Python](https://www.python.org/downloads/)
[Kiểm thử]()

---

## Crypto-Panda là gì?

Đây là một công cụ quét thị trường crypto mã nguồn mở: chấm điểm coin bằng các tín hiệu định lượng đã backtest, phân tích tin tức bằng LLM cho danh sách coin đã lọc, sau đó gửi email báo cáo hằng ngày với nhận định AI, mức chốt lời và cảnh báo catalyst.

Hệ thống được xây theo kiến trúc 2 giai đoạn để giảm chi phí (~$100/tháng), bằng cách chỉ chạy các tác vụ tốn tiền trên những coin đã được tiền sàng lọc.

---

## Tính năng


| Tính năng                    | Mô tả                                                                                                                                     |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| **Chấm Điểm 2 Giai Đoạn**    | Giai đoạn 1: tín hiệu định lượng cho toàn bộ coin (miễn phí). Giai đoạn 2: phân tích tin tức bằng LLM chỉ cho shortlist (~$0.20/lần chạy) |
| **Đa Vũ Trụ Coin**           | Phân tích và trọng số tách riêng cho large-cap (1-50), mid-cap (51-200), small-cap (201-1000)                                             |
| **Trọng Số Theo Bằng Chứng** | Trọng số tín hiệu được rút ra từ hơn 5,600 quan sát backtest, không dựa trên phỏng đoán                                                   |
| **Phân Tích Tin Tức LLM**    | Phân tích sentiment hiểu ngữ cảnh crypto, phát hiện catalyst (list sàn, hack, kiện tụng), nhận diện rủi ro                                |
| **Tốc Độ Tin Tức**           | Phát hiện coin đang được chú ý bất thường (dùng số lượng bài báo làm chỉ báo)                                                             |
| **Mức Thoát Lệnh**           | Take-profit và trailing stop-loss theo từng coin, có scale theo biến động                                                                 |
| **Chế Độ Thị Trường**        | Phát hiện bull/bear/sideways bằng giao cắt MA 50/200 của BTC                                                                              |
| **Bình Luận AI**             | LLM tạo phân tích theo từng coin (OpenAI, Anthropic, Ollama, hoặc endpoint tương thích)                                                   |
| **Backtester**               | Hơn 4 năm dữ liệu kiểm định với mô phỏng phát hiện tăng tốc đã điều chỉnh theo biến động và chiến lược thoát lệnh                         |
| **Lưu Trữ Tin Tức**          | Sentiment tin tức hằng ngày được lưu vào Aurora PostgreSQL để backtest về sau                                                             |


---

## Bắt đầu nhanh

```bash
git clone https://github.com/sjmoran/crypto-panda.git
cd crypto-panda
pip install -r requirements.txt
cp .env.example .env   # Điền API key

# Quét hằng ngày — toàn bộ nhóm vốn hóa
python daily_scanner.py --universe all --top-coins 200 --min-weighted-score 35

# Báo cáo đầy đủ hằng tuần
python monitor.py

# Backtest
python backtester.py --universe small --weeks 100 --top-coins 50
```

## Desktop UI (Electron)

Giao diện desktop viết bằng Electron để vận hành Daily/Backtest/Monitor, quản lý `.env`, xem log/artifact, health check và lịch sử job.

Chạy app:

```bash
npm install
npm start
```

Build bản Windows:

```bash
npm run build:win
```

---

## Các chế độ chạy


| Chế độ                  | Lệnh                                                | Chức năng                                   | Tần suất           |
| ----------------------- | --------------------------------------------------- | ------------------------------------------- | ------------------ |
| **Quét hằng ngày**      | `python daily_scanner.py --universe all`            | Quét đa vũ trụ + phân tích tin tức bằng LLM | Hằng ngày qua cron |
| **Tập trung small-cap** | `python daily_scanner.py --universe small`          | Xếp hạng riêng nhóm 201-1000                | Hằng ngày          |
| **Báo cáo tuần**        | `python monitor.py`                                 | Phân tích đầy đủ + báo cáo LLM + Excel      | Hằng tuần          |
| **Backtester**          | `python backtester.py --universe small --weeks 100` | Kiểm định tín hiệu trên dữ liệu lịch sử     | Theo nhu cầu       |
| **Email test**          | `python send_test_email.py`                         | Báo cáo mẫu bằng dữ liệu mock               | Theo nhu cầu       |


---

## Kiến trúc 2 giai đoạn

```
Giai đoạn 1: Chấm điểm TOÀN BỘ 200+ coin (tín hiệu định lượng miễn phí)
  ├── CoinPaprika bulk ticker (1 API call cho toàn bộ coin)
  ├── CoinPaprika dữ liệu lịch sử theo từng coin (~200 calls)
  ├── Fear & Greed Index (1 call)
  ├── 11 tín hiệu: giá, khối lượng, RSI, tăng trưởng, FNG, đặc trưng ticker
  ├── 0 lần gọi news, 0 lần gọi LLM
  └── Đầu ra: danh sách xếp hạng → lọc top ~20

Giai đoạn 2: Phân tích tin tức bằng LLM chỉ cho TOP ~20
  ├── Google News RSS theo từng coin (~20 lần fetch, miễn phí)
  ├── Phân tích LLM (~$0.01/coin):
  │   ├── Sentiment theo ngữ cảnh crypto (-1.0 đến +1.0)
  │   ├── Phát hiện catalyst (exchange_listing, hack, lawsuit, ...)
  │   ├── Tóm tắt 1 câu + rủi ro chính
  │   └── Điểm độ tin cậy
  ├── News velocity (số lượng bài báo làm tín hiệu mức độ chú ý)
  ├── Điều chỉnh điểm: (sentiment × 2 × confidence) + catalyst_bonus + velocity_bonus
  └── Fallback: dùng VADER nếu LLM không khả dụng

Giai đoạn 3: Bình luận AI + Gửi email (~1 lần gọi LLM)
```

**Nguyên tắc:** Tác vụ tốn kém chỉ chạy trên coin đã được sàng lọc trước.

---

## Hệ thống chấm điểm

### Giai đoạn 1: Tín hiệu định lượng (thang 16 điểm)

11 tín hiệu được chấm điểm từ dữ liệu giá/khối lượng/ticker. Trọng số thay đổi theo từng universe dựa trên backtest.


| Nhóm       | Tín hiệu                        | Khoảng | Trọng số Large-Cap  | Trọng số Small-Cap  | Đã backtest?     |
| ---------- | ------------------------------- | ------ | ------------------- | ------------------- | ---------------- |
| Giá        | Điểm biến động giá              | 0-3    | -1.0 (nghịch chiều) | +1.5 (momentum)     | Có               |
| Giá        | Tăng trưởng tuần ổn định        | 0-1    | +1.0                | **+3.0** (tốt nhất) | Có               |
| Giá        | Tăng trưởng tháng ổn định       | 0-1    | **+3.0** (tốt nhất) | +0.5                | Có               |
| Giá        | Xung đột xu hướng               | 0-2    | +1.5                | -1.0 (bất lợi)      | Có               |
| Khối lượng | Điểm biến động khối lượng       | 0-3    | +1.5                | +1.5                | Có               |
| Khối lượng | Tăng trưởng khối lượng bền vững | 0-1    | +0.5                | +1.0                | Có               |
| Kỹ thuật   | Điểm RSI                        | 0-1    | **+3.0**            | +0.5                | Có               |
| Thị trường | Fear & Greed                    | 0-1    | +1.0                | +0.5                | Không            |
| Ticker     | Spike khối lượng 24h            | 0-1    | +1.0                | +3.0                | Không (chỉ live) |
| Ticker     | Khoảng cách tới ATH             | 0-1    | +0.5                | +2.0                | Không (chỉ live) |
| Ticker     | Momentum đa khung thời gian     | 0-1    | -0.5 (nghịch chiều) | +1.5                | Không (chỉ live) |


**Phát hiện chính:** Tín hiệu cho large-cap và small-cap cho kết quả NGƯỢC NHAU. Bám momentum gây hại ở large-cap nhưng có lợi ở small-cap. Nhịp bật RSI vùng quá bán mạnh với large-cap nhưng yếu với small-cap.

### Giai đoạn 2: Xác nhận tin tức (dùng LLM)

Chỉ áp dụng cho coin trong shortlist. Điều chỉnh weighted score tối đa ±4.0.


| Thành phần             | Chức năng                                                                               | Mức điều chỉnh               |
| ---------------------- | --------------------------------------------------------------------------------------- | ---------------------------- |
| **LLM Sentiment**      | Phân tích 20 tiêu đề Google News với ngữ cảnh crypto                                    | sentiment × 2.0 × confidence |
| **Phát hiện Catalyst** | List sàn (+1.5), hợp tác (+0.5), hack (-2.0), kiện tụng (-1.5), quy định pháp lý (-1.0) | Theo từng catalyst           |
| **News Velocity**      | 15+ bài = chú ý cao (+0.5), 8+ bài = mức trung bình (+0.2)                              | Bonus                        |
| **Fallback**           | Dùng sentiment từ VADER khi LLM không khả dụng                                          | sentiment × 2.0              |


---

## Kết quả backtest

### Large-Cap (4 năm: May 2022 - Sep 2024, 22 coin, 2,518 quan sát)


| Chỉ số                | Equal-Weighted | Evidence-Weighted        |
| --------------------- | -------------- | ------------------------ |
| Tương quan 7d         | 0.021          | **0.054** (tốt hơn 2.6x) |
| Lợi nhuận top 20% 7d  | +1.15%/tuần    | **+1.99%/tuần**          |
| Lợi nhuận top 20% 30d | +3.25%/tháng   | **+4.29%/tháng**         |


**Tín hiệu tốt nhất:** Tăng trưởng tháng (+1.20%), xung đột xu hướng (+1.52%), RSI (+0.89%).

### Small-Cap (2 năm: Apr 2024 - Mar 2026, 50 coin, 3,140 quan sát)


| Chỉ số                           | Kết quả                                                 |
| -------------------------------- | ------------------------------------------------------- |
| Tương quan điểm số 7d            | **0.068** (mạnh nhất trong các universe)                |
| Chênh lệch top 20% vs bottom 20% | **+2.77%/tuần**                                         |
| Lợi nhuận đỉnh trung bình 30d    | **+18.40%** (nhưng điểm cuối chỉ -0.21%)                |
| Chiến lược thoát tốt nhất        | **Trailing stop (+1.11%)** — chiến lược duy nhất có lãi |


**Tín hiệu tốt nhất:** Tăng trưởng tuần (+2.31%), khối lượng (+0.81%), momentum giá (+0.68%).

### Thị trường giảm (Oct 2025 - Mar 2026, 584 quan sát)


| Chỉ số                                | Kết quả    |
| ------------------------------------- | ---------- |
| Top 20% weighted + thoát lệnh kết hợp | **+3.48%** |
| Bottom 20% weighted                   | **-6.02%** |
| Độ chênh (spread)                     | **+9.50%** |


### Điểm rút ra chính

1. **Chấm điểm theo bằng chứng có hiệu quả** — vượt equal-weighted trong 4 năm
2. **Tín hiệu đảo chiều theo nhóm vốn hóa** — một bộ trọng số KHÔNG dùng chung cho tất cả
3. **Timing thoát lệnh quan trọng hơn vào lệnh** — thiếu stop-loss có thể bỏ lỡ 10-18% lợi nhuận
4. **Phần lớn tín hiệu là nhiễu** — chỉ 3-4/11 tín hiệu tương quan ổn định với lợi nhuận
5. **Đơn giản hiệu quả hơn** — bỏ Santiment, keyword, tweet giúp cải thiện hiệu năng

---

## Triết lý chi phí

Bản v1 tiêu tốn $170/tháng. Hiện còn ~$100/tháng nhưng kết quả tốt hơn. Mỗi dependency đều phải chứng minh giá trị, nếu không sẽ bị loại bỏ.

**Đã loại bỏ (không có giá trị đo được trong backtest):**

- Santiment API ($100/tháng) — chỉ số on-chain không có tương quan
- CryptoNews API ($0-30/tháng) — thay bằng Google News RSS miễn phí
- Điểm tweet — chỉ đếm số lượng tweet, không phản ánh chất lượng
- Khớp từ khóa surge — fuzzy matching, nhiều false positive
- Digest score — chỉ phát hiện có/không
- Event score — chỉ kiểm tra "có sự kiện"

**Những gì còn lại:**


| Nguồn               | Chi phí          | Lý do giữ lại                                                                      |
| ------------------- | ---------------- | ---------------------------------------------------------------------------------- |
| CoinPaprika Starter | $99/tháng        | 5 năm lịch sử + ticker realtime. Cấp dữ liệu cho toàn bộ tín hiệu có thể backtest. |
| Google News RSS     | Miễn phí         | 20 tiêu đề/coin. Chỉ dùng ở giai đoạn 2 (~20 truy vấn/lần chạy).                   |
| Alternative.me      | Miễn phí         | Fear & Greed Index (1 call/lần chạy).                                              |
| CoinGecko           | Miễn phí         | Fallback khi không có key CoinPaprika.                                             |
| VADER               | Miễn phí (local) | Fallback khi LLM không khả dụng.                                                   |
| LLM                 | ~$1-3/lần chạy   | Phân tích tin tức + bình luận. Hoặc $0 nếu dùng Ollama local.                      |
| Brevo SMTP          | Miễn phí         | 300 email/ngày.                                                                    |
| **Tổng**            | **~$100/tháng**  |                                                                                    |


---

## Kiến trúc

```
daily_scanner.py          # Hằng ngày: quét 2 giai đoạn, tin tức LLM, gửi email
monitor.py                # Hằng tuần: phân tích đầy đủ, báo cáo LLM, Excel
backtester.py             # Kiểm định tín hiệu trên hơn 4 năm dữ liệu

coin_analysis.py          # Engine chấm điểm + phân tích tin tức LLM + Google News
coin_universe.py          # Trọng số theo từng universe, mục tiêu thoát, dải xếp hạng
features.py               # Spike khối lượng, khoảng cách ATH, momentum đa khung
api_clients.py            # CoinPaprika, Fear & Greed
report_generation.py      # Trừu tượng LLM, email HTML, Excel
data_management.py        # Aurora PostgreSQL + lưu sentiment tin tức
config.py                 # Cấu hình
logging_config.py         # Logging dùng chung
plotting.py               # Biểu đồ
send_test_email.py        # Test với dữ liệu mock
```

**14 module, ~5,200 dòng, 22 bài test unit.**

---

## Biến môi trường

Xem `[.env.example](.env.example)`. Các biến chính:


| Biến                              | Bắt buộc          | Mô tả                                         |
| --------------------------------- | ----------------- | --------------------------------------------- |
| `COIN_PAPRIKA_API_KEY`            | Có                | CoinPaprika Pro ($99/tháng)                   |
| `OPENAI_API_KEY`                  | Cho tính năng LLM | Hoặc đặt `LLM_PROVIDER` để dùng provider khác |
| `LLM_PROVIDER`                    | Không             | `openai` (mặc định), `anthropic`, `ollama`    |
| `LLM_MODEL`                       | Không             | Mặc định: `gpt-4.1`                           |
| `LLM_BASE_URL`                    | Không             | Endpoint tùy chỉnh cho Ollama, vLLM           |
| `EMAIL_FROM`                      | Có                | Địa chỉ gửi đã xác thực                       |
| `EMAIL_TO`                        | Có                | Người nhận                                    |
| `SMTP_SERVER`                     | Có                | Ví dụ `smtp-relay.brevo.com`                  |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | Có                | Thông tin xác thực SMTP                       |


---

## Miễn trừ trách nhiệm

> **PHẦN MỀM NÀY KHÔNG PHẢI LỜI KHUYÊN TÀI CHÍNH VÀ KHÔNG NÊN ĐƯỢC DÙNG LÀM CƠ SỞ CHO QUYẾT ĐỊNH ĐẦU TƯ.**
>
> Crypto-Panda chỉ là **công cụ phục vụ mục đích học tập và nghiên cứu**. Hệ thống chấm điểm, kết quả backtest và các đầu ra do AI tạo ra chỉ nhằm cung cấp thông tin tham khảo. Tác giả không phải cố vấn tài chính được cấp phép.
>
> **Rủi ro chính:**
>
> - Backtest không đảm bảo kết quả tương lai. Tương quan còn yếu (0.02-0.07) và có thể không duy trì.
> - Thị trường crypto biến động cực mạnh. Bạn có thể mất toàn bộ vốn đầu tư.
> - Coin small-cap có thêm rủi ro: thanh khoản thấp, thao túng giá, rug pull, mất trắng.
> - Phân tích do LLM tạo có thể chứa lỗi hoặc hallucination.
> - Phần mềm không kèm bảo hành và được cung cấp theo trạng thái "as is".
>
> Bạn hoàn toàn tự chịu trách nhiệm cho quyết định của mình. Luôn DYOR và tham khảo cố vấn tài chính có chuyên môn. Không đầu tư số tiền bạn không thể chấp nhận mất.

---

## Giấy phép

Dự án được cấp phép theo [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). Xem thêm tại [LICENSE](LICENSE).

---

## Lời cảm ơn

- [CoinPaprika API](https://api.coinpaprika.com/)
- [CoinGecko API](https://www.coingecko.com/en/api)
- [Google News RSS](https://news.google.com/)
- [Fear and Greed Index](https://alternative.me/crypto/fear-and-greed-index/)
- [OpenAI](https://openai.com/) / [Anthropic](https://anthropic.com/)

