# 🛡️ AI Trading Copilot & Deterministic Risk Management Engine

> **Phiên bản:** `v1.0.0-PROD-SPEC` | **Tác giả:** Hoàng Xuân Bách  
> **Mục tiêu kỹ thuật:** Zero Fluff, Risk-First, Capital Preservation  
> **Thị trường:** Crypto Derivatives & Spot (Binance Futures & Spot)  
> **Ngôn ngữ & Runtime:** Python 3.11+ / NumPy / Pandas / CCXT / Ollama / SQLite

---

## 📖 1. Tổng Quan & Triết Lý Thiết Kế Cốt Lõi (Decoupled Architecture)

Hệ thống được thiết kế theo nguyên lý **Tách Rời Tuyệt Đối** giữa hai thành phần:

1. **Tầng Toán Học Xác Định (Deterministic Math Layer - 100% Python Code):**  
   Toàn bộ các phép tính toán liên quan đến số học tuyệt đối: Kéo nến, tính Wilder's RSI (10, 14, 30), Adaptive ATR (14), EMA đa khung, LuxAlgo Trendlines with Breaks (biên độ xác nhận 0.2%), khoảng đệm dừng lỗ thích ứng (Adaptive Stop Loss Buffer) và công thức tính khối lượng vào lệnh (Position Sizing) **ĐƯỢC THỰC THI 100% BẰNG CODE THUẦN**. Tuyệt đối không cho phép LLM can thiệp vào các phép toán số học này.

2. **Tầng Trí Tuệ Suy Luận (Cognitive Reasoning Layer - Devil's Advocate):**  
   LLM được cấp một vai trò duy nhất: Đóng vai **Trưởng Ban Quản Trị Rủi Ro (Chief Risk Officer)**. LLM nhận payload JSON đã được chuẩn hóa bởi tầng toán học, sau đó thực hiện suy luận logic, phản biện bẫy giá, rà soát cấu trúc thị trường đa khung thời gian, và có quyền **PHỦ QUYẾT (VETO)** lệnh nếu phát hiện rủi ro tiềm ẩn.
   
> **NGUYÊN TẮC 'DEVIL'S ADVOCATE':**  
> AI trong hệ thống này **KHÔNG ĐƯỢC PHÉP** đóng vai người cổ vũ. Nhiệm vụ tối thượng là bảo toàn vốn bằng cách luôn tìm ra ít nhất 2 lý do kỹ thuật để từ chối (`REJECT`) kế hoạch vào lệnh. Chỉ khi tất cả các lý do phủ quyết đều bị bác bỏ bởi cấu trúc giá thuyết phục, lệnh mới được phê duyệt (`APPROVE`).

---

## 🏛️ 2. Kiến Trúc Hệ Thống Phân Tầng (5 Tiers)

```
┌────────────────────────────────────────────────────────┐
│ Tier 1: Data Feed (ccxt / Direct Binance REST)        │
│ 300-Candle Ring Buffer (15m, 1h, 4h) + Circuit Breaker │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│ Tier 2: Quant Indicator Engine (NumPy / Pandas)        │
│ LuxAlgo Trendlines (0.2% break), Multi-RSI, ATR, FVG  │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│ Tier 3: Deterministic Risk Engine                      │
│ Fixed Risk 1% ($2.00 on $200), Adaptive SL, Scale-out  │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│ Tier 4: Cognitive AI Copilot (Ollama / OpenRouter)     │
│ 4 Hard Veto Rules + Chief Risk Officer Gatekeeper      │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│ Tier 5: Dispatcher & Storage                           │
│ SQLite (trades.db) + Telegram Bot + Rich Terminal UI   │
└────────────────────────────────────────────────────────┘
```

---

## 📂 3. Cấu Trúc Thư Mục Dự Án

```
trading_copilot/
├── config/
│   ├── settings.yaml          # Cấu hình API keys, rủi ro vốn ($200/1%), ngưỡng SL/TP
│   └── prompt_templates.py    # System Prompt & Serializer JSON Schema 4.1/4.2
├── core/
│   ├── data_feed.py           # Kéo nến Binance, Ring Buffer 300 nến, Exponential Backoff
│   ├── indicator_engine.py    # LuxAlgo Trendlines, RSI (10, 14, 30), ATR, Pinbar, Waterfall
│   ├── risk_engine.py         # Tính toán vị thế, Adaptive SL Buffer, Scale-Out Take Profit
│   └── copilot_agent.py       # Tích hợp Ollama/OpenRouter, 4 Hard Veto Rules, Offline Fallback
├── storage/
│   ├── database.py            # SQLite database quản lý trade_signals và active_positions
│   └── trades.db              # File cơ sở dữ liệu cục bộ
├── guardrails/
│   └── risk_guardrails.py     # 4 Vòng bảo vệ vốn: Daily Loss, Max Positions, Breakeven, Anti-Tilt
├── alerts/
│   └── telegram_bot.py        # Gửi cảnh báo Telegram Bot & giao diện thẻ Terminal ANSI
├── indicators/
│   └── copilot_engine.pine    # Pine Script v6 (TradingView): Buy/Sell, Dual Tracking Line, On-Chart Commentary
├── web/
│   └── dashboard.py           # Web Dashboard & Indicator Studio (Dual-line Canvas Chart & Commentary)
├── main_daemon.py             # File điều phối trung tâm & giao diện dòng lệnh CLI
├── test_system.py             # Bộ kiểm thử tự động 100% test cases (18/18 Tests Passed)
└── requirements.txt           # Danh mục thư viện phụ thuộc
```

---

## 🧮 4. Công Thức Quản Trị Rủi Ro & Toán Học Xác Định

### 4.1 Mức Rủi Ro Cố Định (Fixed Fractional Risk)
Mỗi lệnh chỉ chịu rủi ro tối đa đúng **1% vốn hiện có**:
$$\text{Max Risk USD} = \text{Vốn} \times 1\% = \$200.00 \times 1\% = \$2.00 \text{ USD}$$

### 4.2 Khoảng Đệm Dừng Lỗ Thích Ứng (Adaptive Stop Loss Buffer)
Chống triệt để hiện tượng quét râu nến (wick grab):
```python
Khoang_dem_Buffer = 1.2 * ATR_15m

# Đối với vị thế Long:
Stop_Loss = Swing_Low_5_nen - Khoang_dem_Buffer
Khoang_cach_SL = Entry - Stop_Loss

# Cưỡng chế giãn cách tối thiểu 1.0 ATR:
Nếu Khoang_cach_SL < (1.0 * ATR_15m):
    Stop_Loss = Entry - (1.5 * ATR_15m)  # Cưỡng chế giãn SL tránh râu quét
```

### 4.3 Công Thức Tính Khối Lượng Vị Thế (Position Sizing)
$$\text{Quantity Coins} = \frac{\text{Số Tiền Rủi Ro (\$2.00)}}{|\text{Entry} - \text{Stop Loss}|}$$
$$\text{Giá Trị Vị Thế} = \text{Quantity Coins} \times \text{Entry}$$
$$\text{Đòn Bẩy Cần Thiết} = \frac{\text{Giá Trị Vị Thế}}{\text{Vốn Khả Dụng (\$200.00)}}$$

### 4.4 Phân Bổ Chốt Lời Đa Tầng (Scale-Out Plan)
- **TP1 (1.5R):** Đóng 50% khối lượng, tự động kích hoạt dời Stop Loss về hòa vốn (Breakeven $0.00 rủi ro).
- **TP2 (2.5R):** Đóng 30% khối lượng.
- **TP3 (4.0R):** Thả trôi 20% khối lượng còn lại theo Trailing Stop.

---

## 🛡️ 5. Bộ Quy Tắc 4 Vòng Bảo Vệ (Guardrails) & Hard Veto Rules

### 4 Vòng Bảo Vệ Tài Khoản:
1. **Daily Loss Circuit Breaker:** Khi lỗ lũy kế trong ngày đạt **$4.00 USD (2% vốn)** $\rightarrow$ Khóa quyền phát tín hiệu trong 24 giờ.
2. **Max Open Positions:** Giới hạn tối đa **2 vị thế** mở đồng thời $\rightarrow$ Từ chối cơ hội mới cho đến khi 1 vị thế đóng hoặc đạt Breakeven.
3. **Risk-Free Breakeven Rule:** Khi giá đạt lợi nhuận $\ge 1.0R$ ($\ge \$2.00$) $\rightarrow$ Tự động đôn SL về đúng giá Entry.
4. **Anti-Tilt Cooldown:** Khi dính 2 lệnh Stop Loss liên tiếp $\rightarrow$ Tự động ngắt scanner trong 60 phút làm nguội tâm lý.

### 4 Quy Tắc Phủ Quyết Cứng Của AI (Hard Veto):
- **VETO 1 (Ngược xu hướng vĩ mô):** Nghiêm cấm Long nếu EMA200 khung 1h dốc xuống và giá nằm dưới EMA200 1h.
- **VETO 2 (Bắt dao rơi):** Nghiêm cấm Long khi nến đang xả thác nước (3 nến đỏ dốc đứng) chưa có nến xác nhận rút chân (Pinbar).
- **VETO 3 (Tương quan danh mục):** Nghiêm cấm mở thêm lệnh mới nếu tài khoản đang duy trì $\ge 2$ vị thế.
- **VETO 4 (Vùng mù tin tức vĩ mô):** Từ chối lệnh trong cửa sổ $\pm 30$ phút quanh tin tức CPI / FOMC / NFP.

---

## 📈 6. Tính Năng Chỉ Báo Pine Script v6 & Dual Tracking Line (TradePilot-Style)

Hệ thống cung cấp tệp chỉ báo TradingView hoàn chỉnh tại [`indicators/copilot_engine.pine`](file:///C:/Users/Bach%20Hoang/.gemini/antigravity/scratch/trading_copilot/indicators/copilot_engine.pine) với các tính năng vượt trội:

1. **Đường Chỉ Báo Thứ Hai Bám Đáy (Second Indicator Line Beneath):**
   - Chạy mượt mà trực tiếp bên dưới nến và đường chỉ báo chính (`mainTrendLine`), bám sát biến động thị trường theo thời gian thực tương tự setup trên `traderpilotai.com`.
   - Kết hợp dải mây động (**Tracking Cloud Ribbon**) đổi màu xanh khi thị trường tăng trưởng lành mạnh và chuyển đỏ cảnh báo khi áp lực bán gia tăng.

2. **Tín Hiệu Mua/Bán & Phản Biện AI (Buy/Sell Signals):**
   - Nhãn `BUY LIMIT` (màu xanh lá) chỉ xuất hiện khi cấu trúc nến vững chắc và được Tầng AI phê duyệt (`APPROVED`).
   - Nhãn `BUY REJECTED` (màu đỏ) cảnh báo ngay lập tức nếu nhịp mua phạm phải bẫy giá hoặc các **Hard Veto Rules** (VETO 1: Ngược EMA200 1h dốc xuống; VETO 2: Thác nến xả Waterfall bắt dao rơi).

3. **Bảng Bình Luận & Rủi Ro Real-Time (On-Chart Table):**
   - Đặt cố định góc trên bên phải biểu đồ TradingView, hiển thị phán quyết thời gian thực của Trưởng Ban Quản Trị Rủi Ro (Chief Risk Officer): Phán quyết, Mức rủi ro cố định $2.00 USD, RSI đa chu kỳ (10, 14, 30), ATR đệm SL, và bình luận cảnh báo bẫy giá.

### Hướng Dẫn Cài Đặt Vào TradingView:
1. Mở bất kỳ biểu đồ nào trên [TradingView](https://www.tradingview.com/chart/).
2. Nhấn vào tab **Pine Editor** ở thanh công cụ dưới đáy màn hình.
3. Dán toàn bộ mã từ [`indicators/copilot_engine.pine`](file:///C:/Users/Bach%20Hoang/.gemini/antigravity/scratch/trading_copilot/indicators/copilot_engine.pine) (hoặc nhấn nút *"Sao Chép Mã Pine Script"* trên Web Dashboard).
4. Nhấn **Add to chart** để kích hoạt biểu đồ và nhận tín hiệu.

---

## 🚀 7. Hướng Dẫn Cài Đặt & Sử Dụng Hệ Thống

### 6.1 Cài Đặt Thư Viện
```bash
cd trading_copilot
pip install -r requirements.txt
```

### 6.2 Chạy Bộ Kiểm Thử (Unit Tests)
```bash
python test_system.py
```
> Kết quả: Kiểm tra thành công 100% các công thức toán học, thuật toán chỉ báo, 4 Hard Veto, SQLite Database và Guardrails.

### 6.3 Các Lệnh Dòng Lệnh (CLI Commands)

1. **Quét thị trường 1 chu kỳ ngay lập tức:**
   ```bash
   python main_daemon.py scan
   ```
   Hệ thống sẽ kéo nến Binance cho BTC, ETH, SOL; tính chỉ báo; lập proposal; AI phản biện; ghi vào SQLite và in thẻ kết quả.

2. **Kiểm tra trạng thái tài khoản & Guardrails:**
   ```bash
   python main_daemon.py status
   ```
   Hiển thị vốn khả dụng, lãi/lỗ ngày, trạng thái circuit breaker, vị thế mở và trading journal.

3. **Khởi động chế độ quét nền tự động (Daemon):**
   ```bash
   python main_daemon.py daemon --interval 60
   ```

4. **Khởi động Web Dashboard giao diện người dùng:**
   ```bash
   python main_daemon.py web --port 8000
   ```
   Mở trình duyệt tại: `http://127.0.0.1:8000`

---

## 📡 7. Cấu Hình Telegram Bot & LLM (settings.yaml)

Trong file `config/settings.yaml`:
```yaml
account:
  equity_usd: 200.00
  fixed_risk_percent: 1.0

guardrails:
  daily_loss_limit_usd: 4.00
  anti_tilt_consecutive_losses: 2
  cooldown_minutes: 60
  breakeven_trigger_r: 1.0

llm:
  provider: "ollama"            # Hoặc "openrouter"
  ollama:
    base_url: "http://localhost:11434/api/generate"
    model: "qwen2.5-coder:7b"   # Hoặc deepseek-r1:latest

alerts:
  telegram:
    enabled: true
    bot_token: "YOUR_TELEGRAM_BOT_TOKEN"
    chat_id: "YOUR_CHAT_ID"
```

---

## ☁️ 8. Hướng Dẫn Triển Khai Lên Render (Render.com)

Dự án đã tích hợp sẵn tệp cấu hình Blueprint [`render.yaml`](file:///C:/Users/Bach%20Hoang/.gemini/antigravity/scratch/trading_copilot/render.yaml) giúp bạn triển khai chỉ với 1 cú click:

1. Đăng nhập vào [Render.com](https://dashboard.render.com).
2. Nhấn nút **New +** &rarr; Chọn **Web Service** (hoặc **Blueprint**).
3. Kết nối với GitHub repository: `https://github.com/bchhngsaygez/AI-Trading-Copilot.git`.
4. Thiết lập các thông số chính:
   - **Environment:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python main_daemon.py web`
5. *(Tùy chọn)* Trong tab **Environment**, bạn có thể thêm các biến môi trường:
   - `TELEGRAM_BOT_TOKEN` & `TELEGRAM_CHAT_ID`: Để nhận cảnh báo qua Telegram.
   - `OPENROUTER_API_KEY`: Để dùng mô hình AI đám mây (DeepSeek-R1 / Qwen) thay vì offline fallback.
   - `ENABLE_SCANNER`: `true` (Tự động quét nến Binance liên tục trong background thread song song với Web Dashboard).
6. Nhấn **Create Web Service**. Sau 1-2 phút, Render sẽ cấp cho bạn tên miền trực tuyến dạng:  
   `https://ai-trading-copilot.onrender.com` để truy cập Web Dashboard mọi lúc mọi nơi!
