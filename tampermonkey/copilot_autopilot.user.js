// ==UserScript==
// @name         AI Trading Copilot - Auto-Pilot Assistant
// @namespace    https://ai-trading-copilot-gpq8.onrender.com/
// @version      1.0.0
// @description  Tự động bắt tín hiệu APPROVE, phát chuông báo và tự động thực thi lệnh (Bypass TradingView Paywall)
// @author       AI Trading Copilot Team
// @match        https://ai-trading-copilot-gpq8.onrender.com/*
// @match        http://localhost:8080/*
// @match        http://127.0.0.1:8080/*
// @match        https://www.tradingview.com/chart/*
// @grant        GM_notification
// @grant        GM_xmlhttpRequest
// @connect      ai-trading-copilot-gpq8.onrender.com
// @connect      localhost
// @run-at       document-end
// ==/UserScript==

(function() {
    'use strict';

    console.log("🚀 [AI Copilot Auto-Pilot] Userscript đã khởi động thành công!");

    // Cấu hình URL Web Copilot Backend
    const COPILOT_HOST = window.location.hostname.includes("tradingview.com")
        ? "https://ai-trading-copilot-gpq8.onrender.com"
        : window.location.origin;

    // Bộ nhớ đệm chống spam lệnh trùng lặp (Cooldown cache)
    const processedSignals = new Set();
    let isAutoPilotActive = true;

    // =========================================================================
    // 1. ÂM THANH CHUÔNG BÁO HIỆU (AUDIO CHIME TING TING)
    // =========================================================================
    function playChimeSound(type = 'success') {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();

            osc.connect(gain);
            gain.connect(ctx.destination);

            if (type === 'success') {
                // Tiếng Ting Ting 2 nốt vui tươi
                osc.type = 'sine';
                osc.frequency.setValueAtTime(587.33, ctx.currentTime); // D5
                osc.frequency.setValueAtTime(880.00, ctx.currentTime + 0.15); // A5
                gain.gain.setValueAtTime(0.3, ctx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.6);
                osc.start();
                osc.stop(ctx.currentTime + 0.6);
            } else {
                // Tiếng cảnh báo trầm
                osc.type = 'triangle';
                osc.frequency.setValueAtTime(300, ctx.currentTime);
                gain.gain.setValueAtTime(0.2, ctx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
                osc.start();
                osc.stop(ctx.currentTime + 0.4);
            }
        } catch (e) {
            console.warn("Không phát được âm thanh audio:", e);
        }
    }

    // =========================================================================
    // 2. GIAO DIỆN BẢNG ĐIỀU KHIỂN NỔI (FLOATING WIDGET)
    // =========================================================================
    function injectFloatingUI() {
        if (document.getElementById('copilot-floating-widget')) return;

        const widget = document.createElement('div');
        widget.id = 'copilot-floating-widget';
        widget.style.cssText = `
            position: fixed;
            bottom: 24px;
            right: 24px;
            z-index: 999999;
            background: rgba(15, 23, 42, 0.92);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(59, 130, 246, 0.4);
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.6), 0 0 15px rgba(59, 130, 246, 0.2);
            border-radius: 12px;
            padding: 10px 14px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            color: #f8fafc;
            font-size: 12px;
            display: flex;
            align-items: center;
            gap: 10px;
            user-select: none;
            transition: all 0.3s ease;
        `;

        widget.innerHTML = `
            <div style="display:flex; align-items:center; gap:6px;">
                <span id="copilot-status-dot" style="width:10px; height:10px; border-radius:50%; background:#10B981; display:inline-block; box-shadow:0 0 8px #10B981;"></span>
                <span style="font-weight:700; letter-spacing:0.5px; font-size:11px;">COPILOT AUTO-PILOT</span>
            </div>
            <button id="copilot-toggle-btn" style="
                background: #2563EB;
                color: #fff;
                border: none;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
                cursor: pointer;
                transition: background 0.2s;
            ">ĐANG BẬT</button>
            <span id="copilot-last-action" style="color:#94a3b8; font-size:10px; max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">Đang lắng nghe...</span>
        `;

        document.body.appendChild(widget);

        const btn = document.getElementById('copilot-toggle-btn');
        const dot = document.getElementById('copilot-status-dot');
        const statusText = document.getElementById('copilot-last-action');

        btn.addEventListener('click', () => {
            isAutoPilotActive = !isAutoPilotActive;
            if (isAutoPilotActive) {
                btn.innerText = "ĐANG BẬT";
                btn.style.background = "#2563EB";
                dot.style.background = "#10B981";
                dot.style.boxShadow = "0 0 8px #10B981";
                statusText.innerText = "Đang lắng nghe...";
                playChimeSound('success');
            } else {
                btn.innerText = "TẠM TẮT";
                btn.style.background = "#475569";
                dot.style.background = "#EF4444";
                dot.style.boxShadow = "0 0 8px #EF4444";
                statusText.innerText = "Đã dừng quét";
                playChimeSound('alert');
            }
        });
    }

    function updateWidgetStatus(text, color = '#38bdf8') {
        const statusText = document.getElementById('copilot-last-action');
        if (statusText) {
            statusText.innerText = text;
            statusText.style.color = color;
        }
    }

    // =========================================================================
    // 3. XỬ LÝ TRÊN TRANG WEB COPILOT (RENDER / LOCALHOST DASHBOARD)
    // =========================================================================
    function monitorCopilotDashboard() {
        if (!isAutoPilotActive) return;

        // Quét bảng tín hiệu tìm kèo APPROVE
        const rows = document.querySelectorAll('#signals-tbody tr');
        rows.forEach(row => {
            const text = row.innerText;
            if (text.includes("APPROVE")) {
                const cols = row.querySelectorAll('td');
                if (cols.length >= 8) {
                    const signalId = cols[0]?.innerText?.replace('#', '').trim();
                    const symbol = cols[2]?.innerText?.trim();
                    const entry = cols[3]?.innerText?.trim();
                    const sl = cols[4]?.innerText?.trim();
                    const tp = cols[5]?.innerText?.trim();

                    const key = `${signalId}_${symbol}_${entry}`;

                    // Nếu là tín hiệu mới chưa từng xử lý
                    if (signalId && !processedSignals.has(key)) {
                        processedSignals.add(key);

                        console.log(`🎯 [AUTO-PILOT DETECTED APPROVE]: Kèo #${signalId} ${symbol} tại ${entry}!`);
                        playChimeSound('success');
                        updateWidgetStatus(`Đã bắt APPROVE ${symbol}!`, '#10b981');

                        // Đảm bảo nút Auto-Trade trên Web Dashboard đã được BẬT
                        const autoTradeToggle = document.getElementById('btn-autotrade-toggle');
                        if (autoTradeToggle && autoTradeToggle.innerText.includes("TẮT")) {
                            console.log("⚡ Auto-Pilot tự động kích hoạt chế độ Auto-Trade trên Web!");
                            autoTradeToggle.click();
                        }

                        // Kích hoạt đồng bộ TP/SL lên sàn nếu có
                        const syncBtn = document.getElementById('btn-sync-tpsl');
                        if (syncBtn) {
                            setTimeout(() => syncBtn.click(), 1500);
                        }
                    }
                }
            }
        });
    }

    // =========================================================================
    // 4. XỬ LÝ TRÊN TRANG TRADINGVIEW (TRADINGVIEW.COM/CHART)
    // =========================================================================
    function monitorTradingView() {
        if (!isAutoPilotActive) return;

        // Bắt các thông báo Pop-up Toast hoặc Alert Notification trên TradingView
        const alertToasts = document.querySelectorAll('[data-role="toast"], .tv-alert-dialog, [class*="toast-"]');
        alertToasts.forEach(toast => {
            const content = toast.innerText || '';
            if (content.includes("AI Copilot") || content.includes("BUY Signal APPROVED") || content.includes("APPROVE")) {
                const key = content.slice(0, 50);
                if (!processedSignals.has(key)) {
                    processedSignals.add(key);
                    console.log("🚨 [TRADINGVIEW ALERT INTERCEPTED]:", content);
                    playChimeSound('success');
                    updateWidgetStatus("Đã bắt Alert TradingView!", '#10b981');

                    // Bắn Webhook về Server Render hoàn toàn miễn phí
                    if (typeof GM_xmlhttpRequest !== 'undefined') {
                        GM_xmlhttpRequest({
                            method: "POST",
                            url: `${COPILOT_HOST}/api/webhook/tradingview`,
                            headers: { "Content-Type": "application/json" },
                            data: JSON.stringify({
                                source: "Tampermonkey_TradingView_Interceptor",
                                alert_message: content,
                                timestamp: new Date().toISOString()
                            }),
                            onload: function(res) {
                                console.log("✅ Đã chuyển tiếp Alert TradingView về Web Copilot thành công:", res.responseText);
                            }
                        });
                    }
                }
            }
        });
    }

    // =========================================================================
    // 5. VÒNG LẶP CHÍNH (MAIN LOOP)
    // =========================================================================
    window.addEventListener('load', () => {
        setTimeout(injectFloatingUI, 1500);

        setInterval(() => {
            injectFloatingUI();
            if (window.location.hostname.includes("tradingview.com")) {
                monitorTradingView();
            } else {
                monitorCopilotDashboard();
            }
        }, 2000); // Quét mỗi 2 giây
    });

})();
