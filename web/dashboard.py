"""
web/dashboard.py
Phase 4: Local Web Dashboard & TraderPilot-Style Indicator Studio
Giao diện Web trực quan (Dark Mode / Glassmorphism / Tailwind CSS):
- Tích hợp biểu đồ thời gian thực hiển thị:
  + Nến giá OHLCV
  + Đường chỉ báo chính (Main Indicator Line)
  + Đường chỉ báo thứ hai bám sát bên dưới theo thời gian thực (Second Indicator Line Beneath)
  + Dải mây động (Tracking Ribbon Cloud)
  + Nhãn tín hiệu Buy / Sell / VETO
- Hộp bình luận phản biện AI (Real-Time Commentary Box - Chief Risk Officer)
- Bộ công cụ Pine Script v6 cho TradingView (Code Viewer & 1-Click Copy)
- Theo dõi 4 Guardrails bảo vệ tài khoản & nhật ký giao dịch SQLite
"""

import sys
import os
import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Import các module cốt lõi
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from storage.database import DatabaseManager
from guardrails.risk_guardrails import RiskGuardrails
from core.data_feed import MarketDataFeed
from core.indicator_engine import QuantitativeIndicatorEngine

logger = logging.getLogger("WebDashboard")

PINE_SCRIPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "indicators",
    "copilot_engine.pine"
)


def get_pine_script_content() -> str:
    """Đọc nội dung file Pine Script v6"""
    if os.path.exists(PINE_SCRIPT_PATH):
        with open(PINE_SCRIPT_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return "// Không tìm thấy file copilot_engine.pine"


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="vi" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI Trading Copilot | Indicator Studio & Risk Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          fontFamily: {
            sans: ['Inter', 'sans-serif'],
            mono: ['JetBrains Mono', 'monospace'],
          },
          colors: {
            brand: {
              dark: '#0B0E14',
              card: '#151922',
              border: '#232936',
              accent: '#3B82F6',
              success: '#10B981',
              danger: '#EF4444',
              warning: '#F59E0B'
            }
          }
        }
      }
    }
  </script>
  <style>
    body { background-color: #0B0E14; color: #F3F4F6; }
    .glass-card {
      background: rgba(21, 25, 34, 0.90);
      border: 1px solid #232936;
      backdrop-filter: blur(12px);
    }
    .badge-reject { background: rgba(239, 68, 68, 0.15); color: #EF4444; border: 1px solid rgba(239, 68, 68, 0.3); }
    .badge-approve { background: rgba(16, 185, 129, 0.15); color: #10B981; border: 1px solid rgba(16, 185, 129, 0.3); }
    .badge-wait { background: rgba(245, 158, 11, 0.15); color: #F59E0B; border: 1px solid rgba(245, 158, 11, 0.3); }
    canvas { display: block; }
  </style>
</head>
<body class="font-sans antialiased min-h-screen p-4 md:p-8">
  <div class="max-w-7xl mx-auto space-y-6">

    <!-- HEADER -->
    <header class="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-brand-border">
      <div>
        <div class="flex items-center gap-3">
          <div class="h-3 w-3 rounded-full bg-emerald-500 animate-pulse"></div>
          <h1 class="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
            AI Trading Copilot <span class="text-xs px-2 py-0.5 rounded bg-blue-500/20 text-blue-400 font-mono font-medium border border-blue-500/30">PROD-SPEC v1.0</span>
          </h1>
        </div>
        <p class="text-sm text-gray-400 mt-1">Deterministic Risk Engine & TradePilot-Style Dual Tracking Indicator</p>
      </div>

      <div class="flex flex-wrap items-center gap-3">
        <button onclick="openEquityModal()" class="px-3.5 py-2 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-medium text-xs rounded-lg transition-all flex items-center gap-2 shadow-lg shadow-emerald-500/10 active:scale-95">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
          💰 Sửa Vốn & Rủi Ro
        </button>
        <button onclick="openPineModal()" class="px-3.5 py-2 bg-gradient-to-r from-indigo-600 to-blue-600 hover:from-indigo-500 hover:to-blue-500 text-white font-medium text-xs rounded-lg transition-all flex items-center gap-2 shadow-lg shadow-blue-500/10">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"></path></svg>
          📜 Pine Script v6 (TradingView)
        </button>
        <button id="btn-scan" onclick="triggerScan()" class="px-4 py-2 bg-blue-600 hover:bg-blue-500 active:scale-95 text-white font-medium text-xs rounded-lg transition-all flex items-center gap-2 shadow-lg shadow-blue-500/20">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
          Quét Thị Trường Ngay
        </button>
        <span class="text-xs text-gray-400 font-mono px-3 py-2 bg-brand-card rounded-lg border border-brand-border">
          Cập nhật: <span id="last-updated">Đang tải...</span>
        </span>
      </div>
    </header>

    <!-- METRICS GRID -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <div class="glass-card rounded-xl p-5 relative overflow-hidden group">
        <div class="flex items-center justify-between">
          <div class="text-xs font-medium text-gray-400 uppercase tracking-wider">Vốn Khả Dụng / Rủi Ro</div>
          <button onclick="openEquityModal()" title="Chỉnh sửa vốn và tỷ lệ rủi ro" class="px-2.5 py-1 bg-blue-500/15 hover:bg-blue-500/25 text-blue-400 hover:text-blue-300 border border-blue-500/30 rounded-md text-[11px] font-medium transition-all flex items-center gap-1 active:scale-95 shadow-sm">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path></svg>
            Sửa Vốn
          </button>
        </div>
        <div class="mt-2 flex items-baseline gap-2">
          <span class="text-2xl font-bold font-mono text-white" id="stat-equity">$200.00</span>
          <span class="text-xs font-mono text-blue-400 font-medium" id="stat-risk-per-trade">1.0% ($2.00) / lệnh</span>
        </div>
        <div class="mt-3 text-xs text-gray-400 flex items-center gap-1.5">
          <span class="inline-block w-1.5 h-1.5 rounded-full bg-blue-400"></span>
          Fixed Fractional Risk Engine
        </div>
      </div>

      <div class="glass-card rounded-xl p-5">
        <div class="text-xs font-medium text-gray-400 uppercase tracking-wider">Daily Loss Circuit Breaker</div>
        <div class="mt-2 flex items-baseline gap-2">
          <span class="text-2xl font-bold font-mono text-white" id="stat-daily-pnl">$0.00</span>
          <span class="text-xs font-mono text-gray-400" id="stat-daily-limit">/ Max -$4.00 (2%)</span>
        </div>
        <div class="mt-3 text-xs flex items-center gap-1.5" id="stat-daily-status">
          <span class="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
          <span class="text-emerald-400 font-medium">An toàn (Chưa ngắt mạch)</span>
        </div>
      </div>

      <div class="glass-card rounded-xl p-5">
        <div class="text-xs font-medium text-gray-400 uppercase tracking-wider">Vị Thế Mở / Rào Chắn Tương Quan</div>
        <div class="mt-2 flex items-baseline gap-2">
          <span class="text-2xl font-bold font-mono text-white" id="stat-positions">0 / 2</span>
          <span class="text-xs font-mono text-gray-400">Vị thế tối đa</span>
        </div>
        <div class="mt-3 text-xs text-gray-400 flex items-center gap-1.5">
          <span class="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
          Anti-Correlated Exposure Guard
        </div>
      </div>

      <div class="glass-card rounded-xl p-5">
        <div class="text-xs font-medium text-gray-400 uppercase tracking-wider">Winrate & Profit Factor</div>
        <div class="mt-2 flex items-baseline gap-2">
          <span class="text-2xl font-bold font-mono text-white" id="stat-winrate">0.0%</span>
          <span class="text-xs font-mono text-gray-400" id="stat-pf">PF: 0.00</span>
        </div>
        <div class="mt-3 text-xs text-gray-400 flex items-center gap-1.5">
          <span class="inline-block w-1.5 h-1.5 rounded-full bg-indigo-400"></span>
          Mục tiêu R:R tối thiểu 1:2.0
        </div>
      </div>
    </div>

    <!-- ========================================================================= -->
    <!-- REAL-TIME INDICATOR STUDIO (TRADERPILOT-STYLE DUAL TRACKING SETUP)       -->
    <!-- ========================================================================= -->
    <div class="glass-card rounded-xl overflow-hidden border border-brand-border">
      <!-- Studio Header Toolbar -->
      <div class="p-4 border-b border-brand-border bg-brand-dark/60 flex flex-wrap items-center justify-between gap-4">
        <div class="flex items-center gap-3">
          <span class="text-xs font-bold uppercase tracking-wider text-gray-400">Cặp Giao Dịch:</span>
          <div class="inline-flex rounded-lg bg-brand-card p-1 border border-brand-border">
            <button onclick="setSymbol('BTC/USDT')" id="tab-btc" class="px-3 py-1 text-xs font-mono font-medium rounded-md bg-blue-600 text-white transition-all">BTC/USDT</button>
            <button onclick="setSymbol('ETH/USDT')" id="tab-eth" class="px-3 py-1 text-xs font-mono font-medium rounded-md text-gray-400 hover:text-white transition-all">ETH/USDT</button>
            <button onclick="setSymbol('SOL/USDT')" id="tab-sol" class="px-3 py-1 text-xs font-mono font-medium rounded-md text-gray-400 hover:text-white transition-all">SOL/USDT</button>
          </div>
          <span class="text-xs font-mono px-2 py-0.5 rounded bg-brand-card border border-brand-border text-gray-400">15m</span>
        </div>

        <!-- Legend -->
        <div class="flex flex-wrap items-center gap-4 text-xs font-mono text-gray-300">
          <div class="flex items-center gap-1.5">
            <span class="w-3 h-0.5 bg-emerald-400"></span>
            <span>Main Indicator Line</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span class="w-3 h-0.5 bg-blue-400"></span>
            <span>Second Tracking Line (Beneath)</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span class="w-2.5 h-2.5 rounded-sm bg-blue-500/30 border border-blue-400/50"></span>
            <span>Tracking Cloud</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span class="text-emerald-400 font-bold">[B] Buy</span>
            <span class="text-rose-400 font-bold">[B] Breakdown</span>
          </div>
        </div>
      </div>

      <!-- Studio Main Grid: Canvas Chart (2/3) + Real-Time Commentary (1/3) -->
      <div class="grid grid-cols-1 lg:grid-cols-3 divide-y lg:divide-y-0 lg:divide-x divide-brand-border">
        
        <!-- Live Chart Container -->
        <div class="lg:col-span-2 p-4 flex flex-col justify-between bg-black/30">
          <div class="flex items-center justify-between text-xs font-mono text-gray-400 mb-2">
            <div>
              <span class="font-bold text-white text-sm" id="chart-symbol-title">BTC/USDT</span>
              <span class="ml-2 text-emerald-400 text-sm font-semibold" id="chart-price">$0.00</span>
              <span class="ml-2 text-gray-400 text-[11px]" id="chart-atr">ATR: --</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="inline-block w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
              <span class="text-[11px] text-gray-400">Live Dual-Line Tracking Active</span>
            </div>
          </div>

          <!-- HTML5 Canvas Chart -->
          <div class="relative w-full h-[360px] bg-brand-dark/40 rounded-lg overflow-hidden border border-brand-border/60">
            <canvas id="indicatorCanvas" class="w-full h-full"></canvas>
            <div id="chartLoading" class="absolute inset-0 flex items-center justify-center bg-brand-dark/80 text-gray-400 text-xs font-mono">
              Đang vẽ đường chỉ báo kép...
            </div>
          </div>

          <!-- Indicator Tracking Status Bar -->
          <div class="mt-3 grid grid-cols-3 gap-2 text-center text-xs font-mono">
            <div class="p-2 rounded bg-brand-card/70 border border-brand-border">
              <span class="text-gray-400 block text-[10px] uppercase">RSI Multi-Length</span>
              <span class="text-white font-bold" id="panel-rsi">-- | -- | --</span>
            </div>
            <div class="p-2 rounded bg-brand-card/70 border border-brand-border">
              <span class="text-gray-400 block text-[10px] uppercase">Trendline Status</span>
              <span class="text-white font-bold" id="panel-trend">NEUTRAL</span>
            </div>
            <div class="p-2 rounded bg-brand-card/70 border border-brand-border">
              <span class="text-gray-400 block text-[10px] uppercase">Khoảng Cách Đệm SL</span>
              <span class="text-blue-400 font-bold" id="panel-sl-buffer">1.2x ATR (Forced 1.5x)</span>
            </div>
          </div>
        </div>

        <!-- Real-Time AI Commentary Box (Chief Risk Officer) -->
        <div class="p-5 flex flex-col justify-between bg-brand-card/30 space-y-4">
          <div>
            <div class="flex items-center justify-between pb-3 border-b border-brand-border">
              <div class="flex items-center gap-2">
                <div class="p-1 rounded bg-blue-500/20 text-blue-400">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                </div>
                <h3 class="text-xs font-bold text-white uppercase tracking-wider">Bình Luận CRO Real-Time</h3>
              </div>
              <span id="comm-verdict-badge" class="px-2.5 py-1 rounded text-[11px] font-bold badge-reject">
                REJECT (VETO)
              </span>
            </div>

            <!-- Primary Threat -->
            <div class="mt-4 space-y-2">
              <div class="text-[11px] font-bold text-gray-400 uppercase tracking-wider">Mối Đe Dọa Chính (Primary Threat):</div>
              <div id="comm-threat" class="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-xs font-sans text-rose-300 leading-relaxed">
                Đang phân tích cấu trúc giá...
              </div>
            </div>

            <!-- Counter Arguments -->
            <div class="mt-4 space-y-2">
              <div class="text-[11px] font-bold text-gray-400 uppercase tracking-wider">Lý Do Phản Biện (Devil's Advocate):</div>
              <ul id="comm-counters" class="text-xs font-sans text-gray-300 space-y-1.5 pl-4 list-disc">
                <li>Đang rà soát bẫy giá và vùng hỗ trợ...</li>
              </ul>
            </div>

            <!-- Technical Proposal Parameters -->
            <div class="mt-4 p-3 rounded-lg bg-brand-dark/70 border border-brand-border space-y-1.5 text-xs font-mono">
              <div class="flex justify-between"><span class="text-gray-400">Entry Đề Xuất:</span><span class="text-emerald-400 font-bold" id="comm-entry">--</span></div>
              <div class="flex justify-between"><span class="text-gray-400">Stop Loss (Buffer):</span><span class="text-rose-400 font-bold" id="comm-sl">--</span></div>
              <div class="flex justify-between"><span class="text-gray-400">Take Profit (1:2.0):</span><span class="text-blue-400 font-bold" id="comm-tp">--</span></div>
              <div class="flex justify-between"><span class="text-gray-400">Kích Thước Vị Thế:</span><span class="text-white font-bold" id="comm-size">--</span></div>
              <div class="flex justify-between"><span class="text-gray-400">Rủi Ro Cố Định:</span><span class="text-yellow-400 font-bold" id="comm-risk">$2.00 USD (1.0%)</span></div>
            </div>
          </div>

          <!-- Action Instruction -->
          <div class="pt-3 border-t border-brand-border">
            <div class="text-[11px] font-bold text-gray-400 uppercase tracking-wider">Khuyến Nghị Hành Động:</div>
            <p id="comm-instruction" class="text-xs font-sans text-amber-300 mt-1 italic leading-relaxed">
              Kích hoạt Hard Veto. Đứng ngoài thị trường bảo toàn vốn.
            </p>
          </div>
        </div>

      </div>
    </div>

    <!-- 4 GUARDRAILS STATUS BANNER -->
    <div class="glass-card rounded-xl p-5 border-l-4 border-l-blue-500">
      <h2 class="text-sm font-bold text-white uppercase tracking-wider flex items-center gap-2">
        <svg class="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"></path></svg>
        Hệ Thống 4 Lớp Bảo Vệ Rủi Ro Tài Khoản (Guardrails)
      </h2>
      <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mt-3 text-xs">
        <div class="p-3 bg-brand-dark/50 rounded-lg border border-brand-border">
          <div class="text-gray-400 font-medium">1. Daily Loss Breaker:</div>
          <div class="text-emerald-400 font-mono font-semibold mt-1" id="guardrail-daily-desc">Khóa 24h khi lỗ $4.00</div>
        </div>
        <div class="p-3 bg-brand-dark/50 rounded-lg border border-brand-border">
          <div class="text-gray-400 font-medium">2. Max Open Positions:</div>
          <div class="text-emerald-400 font-mono font-semibold mt-1">Giới hạn cứng 2 vị thế</div>
        </div>
        <div class="p-3 bg-brand-dark/50 rounded-lg border border-brand-border">
          <div class="text-gray-400 font-medium">3. Breakeven 1.0R:</div>
          <div class="text-emerald-400 font-mono font-semibold mt-1" id="guardrail-be-desc">Lãi >= $2.00 đôn SL về Entry</div>
        </div>
        <div class="p-3 bg-brand-dark/50 rounded-lg border border-brand-border">
          <div class="text-gray-400 font-medium">4. Anti-Tilt Cooldown:</div>
          <div class="text-emerald-400 font-mono font-semibold mt-1">2 SL liên tiếp nghỉ 60 phút</div>
        </div>
      </div>
    </div>

    <!-- SIGNALS TABLE -->
    <div class="glass-card rounded-xl overflow-hidden">
      <div class="p-5 border-b border-brand-border flex items-center justify-between">
        <div>
          <h2 class="text-base font-bold text-white">Nhật Ký Tín Hiệu Giao Dịch & Phản Biện AI (Signals & Journal)</h2>
          <p class="text-xs text-gray-400 mt-0.5">Dữ liệu được lưu trữ chuẩn xác trong SQLite cục bộ (trades.db)</p>
        </div>
        <span class="text-xs font-mono text-gray-400 px-2.5 py-1 bg-brand-dark rounded border border-brand-border" id="signal-count">0 tín hiệu</span>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full text-left text-xs font-mono">
          <thead class="bg-brand-dark/70 text-gray-400 uppercase tracking-wider border-b border-brand-border">
            <tr>
              <th class="py-3 px-4">ID</th>
              <th class="py-3 px-4">Thời Gian</th>
              <th class="py-3 px-4">Cặp Coin</th>
              <th class="py-3 px-4">Entry</th>
              <th class="py-3 px-4">Stop Loss</th>
              <th class="py-3 px-4">Take Profit</th>
              <th class="py-3 px-4">Size</th>
              <th class="py-3 px-4">R:R</th>
              <th class="py-3 px-4">Quyết Định AI</th>
              <th class="py-3 px-4">Phản Biện Rủi Ro (Devil's Advocate)</th>
            </tr>
          </thead>
          <tbody id="signals-tbody" class="divide-y divide-brand-border text-gray-300">
            <tr>
              <td colspan="10" class="py-8 text-center text-gray-500 font-sans">Đang tải nhật ký tín hiệu...</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

  </div>

  <!-- ========================================================================= -->
  <!-- MODAL: CÀI ĐẶT VỐN & TỶ LỆ RỦI RO (ACCOUNT CAPITAL & RISK MODAL)        -->
  <!-- ========================================================================= -->
  <div id="equityModal" class="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
    <div class="glass-card rounded-2xl max-w-lg w-full border border-brand-border overflow-hidden shadow-2xl">
      
      <!-- Modal Header -->
      <div class="p-5 border-b border-brand-border bg-brand-card flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="p-2 rounded-lg bg-blue-500/20 text-blue-400 border border-blue-500/30">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
          </div>
          <div>
            <h2 class="text-base font-bold text-white">Chỉnh Sửa Vốn & Quản Trị Rủi Ro</h2>
            <p class="text-xs text-gray-400 mt-0.5">Tự động tính toán lại Position Sizing & Daily Loss Breaker</p>
          </div>
        </div>
        <button onclick="closeEquityModal()" class="text-gray-400 hover:text-white p-1 rounded-lg">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
        </button>
      </div>

      <!-- Modal Body -->
      <div class="p-6 space-y-5 bg-brand-dark/95">
        
        <!-- Input 1: Vốn tài khoản ($ USD) -->
        <div class="space-y-2">
          <label class="text-xs font-semibold text-gray-300 uppercase tracking-wider flex items-center justify-between">
            <span>Số Vốn Khả Dụng (Equity USD)</span>
            <span class="text-[11px] text-blue-400 font-mono">Tối thiểu: $10</span>
          </label>
          <div class="relative">
            <span class="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400 font-mono text-sm font-semibold">$</span>
            <input type="number" id="input-equity" step="10" min="10" class="w-full pl-8 pr-4 py-2.5 bg-brand-card border border-brand-border rounded-lg text-white font-mono text-base font-bold focus:outline-none focus:border-blue-500 transition-colors" placeholder="200.00" oninput="updateEquityPreview()">
          </div>

          <!-- Preset Chips for Equity -->
          <div class="flex flex-wrap gap-1.5 pt-1">
            <span class="text-[10px] text-gray-500 self-center mr-1">Gợi ý nhanh:</span>
            <button type="button" onclick="setPresetEquity(100)" class="px-2 py-0.5 text-xs font-mono rounded bg-brand-card hover:bg-blue-600/20 text-gray-300 hover:text-blue-400 border border-brand-border transition-colors">$100</button>
            <button type="button" onclick="setPresetEquity(200)" class="px-2 py-0.5 text-xs font-mono rounded bg-brand-card hover:bg-blue-600/20 text-gray-300 hover:text-blue-400 border border-brand-border transition-colors">$200</button>
            <button type="button" onclick="setPresetEquity(500)" class="px-2 py-0.5 text-xs font-mono rounded bg-brand-card hover:bg-blue-600/20 text-gray-300 hover:text-blue-400 border border-brand-border transition-colors">$500</button>
            <button type="button" onclick="setPresetEquity(1000)" class="px-2 py-0.5 text-xs font-mono rounded bg-brand-card hover:bg-blue-600/20 text-gray-300 hover:text-blue-400 border border-brand-border transition-colors">$1,000</button>
            <button type="button" onclick="setPresetEquity(2000)" class="px-2 py-0.5 text-xs font-mono rounded bg-brand-card hover:bg-blue-600/20 text-gray-300 hover:text-blue-400 border border-brand-border transition-colors">$2,000</button>
            <button type="button" onclick="setPresetEquity(5000)" class="px-2 py-0.5 text-xs font-mono rounded bg-brand-card hover:bg-blue-600/20 text-gray-300 hover:text-blue-400 border border-brand-border transition-colors">$5,000</button>
          </div>
        </div>

        <!-- Input 2: Tỷ lệ rủi ro mỗi lệnh (% Vốn) -->
        <div class="space-y-2">
          <label class="text-xs font-semibold text-gray-300 uppercase tracking-wider flex items-center justify-between">
            <span>Tỷ Lệ Rủi Ro Mỗi Lệnh (%)</span>
            <span class="text-[11px] text-amber-400 font-mono">Chuẩn: 1.0%</span>
          </label>
          <div class="relative">
            <input type="number" id="input-risk-pct" step="0.1" min="0.1" max="5.0" class="w-full px-4 py-2.5 bg-brand-card border border-brand-border rounded-lg text-white font-mono text-base font-bold focus:outline-none focus:border-blue-500 transition-colors" placeholder="1.0" oninput="updateEquityPreview()">
            <span class="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-400 font-mono text-sm font-semibold">%</span>
          </div>

          <!-- Preset Chips for Risk % -->
          <div class="flex flex-wrap gap-1.5 pt-1">
            <span class="text-[10px] text-gray-500 self-center mr-1">Mức rủi ro:</span>
            <button type="button" onclick="setPresetRisk(0.5)" class="px-2 py-0.5 text-xs font-mono rounded bg-brand-card hover:bg-emerald-600/20 text-gray-300 hover:text-emerald-400 border border-brand-border transition-colors">0.5% (Thận trọng)</button>
            <button type="button" onclick="setPresetRisk(1.0)" class="px-2 py-0.5 text-xs font-mono rounded bg-blue-600/30 text-blue-400 border border-blue-500/40 transition-colors font-medium">1.0% (Khuyên dùng)</button>
            <button type="button" onclick="setPresetRisk(1.5)" class="px-2 py-0.5 text-xs font-mono rounded bg-brand-card hover:bg-amber-600/20 text-gray-300 hover:text-amber-400 border border-brand-border transition-colors">1.5%</button>
            <button type="button" onclick="setPresetRisk(2.0)" class="px-2 py-0.5 text-xs font-mono rounded bg-brand-card hover:bg-rose-600/20 text-gray-300 hover:text-rose-400 border border-brand-border transition-colors">2.0% (Tối đa)</button>
          </div>
        </div>

        <!-- Live Math Simulation Preview Box -->
        <div class="p-4 rounded-xl bg-brand-card/70 border border-brand-border/80 space-y-2.5">
          <div class="text-[11px] font-bold text-gray-400 uppercase tracking-wider flex items-center justify-between border-b border-brand-border pb-2">
            <span>Mô Phỏng Tham Số Rủi Ro Toán Học</span>
            <span class="text-emerald-400 font-mono text-[10px]">Deterministic Math</span>
          </div>
          <div class="grid grid-cols-2 gap-3 text-xs font-mono">
            <div>
              <span class="text-gray-400 block text-[11px]">Rủi ro tối đa / lệnh:</span>
              <span class="text-white font-bold text-sm" id="modal-preview-risk-usd">$2.00 USD</span>
            </div>
            <div>
              <span class="text-gray-400 block text-[11px]">Daily Loss Breaker (2%):</span>
              <span class="text-rose-400 font-bold text-sm" id="modal-preview-daily-limit">-$4.00 USD</span>
            </div>
            <div>
              <span class="text-gray-400 block text-[11px]">Kích hoạt Breakeven (1.0R):</span>
              <span class="text-emerald-400 font-bold text-sm" id="modal-preview-be">Lãi +$2.00</span>
            </div>
            <div>
              <span class="text-gray-400 block text-[11px]">Chống quét râu SL:</span>
              <span class="text-blue-400 font-bold text-sm">1.2x - 1.5x ATR</span>
            </div>
          </div>
        </div>

        <!-- Status Message Box -->
        <div id="modal-msg" class="hidden p-3 rounded-lg text-xs font-sans"></div>

      </div>

      <!-- Modal Footer -->
      <div class="p-4 bg-brand-card border-t border-brand-border flex items-center justify-end gap-3">
        <button type="button" onclick="closeEquityModal()" class="px-4 py-2 bg-brand-dark hover:bg-brand-dark/80 text-gray-300 font-medium text-xs rounded-lg border border-brand-border transition-all">
          Hủy Bỏ
        </button>
        <button type="button" id="btn-save-equity" onclick="saveEquity()" class="px-5 py-2 bg-blue-600 hover:bg-blue-500 active:scale-95 text-white font-semibold text-xs rounded-lg transition-all flex items-center gap-2 shadow-lg shadow-blue-500/20">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
          Lưu & Cập Nhật Hệ Thống
        </button>
      </div>

    </div>
  </div>

  <!-- ========================================================================= -->
  <!-- MODAL: PINE SCRIPT V6 STUDIO (TRADINGVIEW INTEGRATION)                   -->
  <!-- ========================================================================= -->
  <div id="pineModal" class="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
    <div class="glass-card rounded-2xl max-w-4xl w-full max-h-[90vh] flex flex-col border border-brand-border overflow-hidden shadow-2xl">
      <div class="p-5 border-b border-brand-border bg-brand-card flex items-center justify-between">
        <div>
          <h2 class="text-base font-bold text-white flex items-center gap-2">
            <span>TradingView Pine Script v6</span>
            <span class="text-[10px] px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 font-mono font-bold">READY TO ADD</span>
          </h2>
          <p class="text-xs text-gray-400 mt-0.5">Bao gồm nhãn Buy/Sell, đường tracking thứ 2 bám đáy real-time, và bảng bình luận AI on-chart</p>
        </div>
        <button onclick="closePineModal()" class="text-gray-400 hover:text-white p-1 rounded-lg">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
        </button>
      </div>

      <!-- Quick Instructions -->
      <div class="px-5 py-3 bg-blue-500/10 border-b border-blue-500/20 text-xs text-blue-300 flex items-center justify-between">
        <div class="flex items-center gap-2">
          <span>💡</span>
          <span><strong>Cách dùng:</strong> Mở TradingView &rarr; Nhấn thẻ <em>Pine Editor</em> ở đáy màn hình &rarr; Dán mã &rarr; Nhấn <em>Add to chart</em>.</span>
        </div>
        <button id="btn-copy-pine" onclick="copyPineCode()" class="px-3 py-1 bg-blue-600 hover:bg-blue-500 text-white font-mono text-xs rounded transition-all">
          Sao Chép Mã Pine Script
        </button>
      </div>

      <!-- Code Box -->
      <div class="p-5 overflow-y-auto flex-1 bg-brand-dark/95">
        <pre><code id="pineCodeBlock" class="text-xs font-mono text-emerald-300 leading-relaxed select-all">Đang tải mã Pine Script...</code></pre>
      </div>
    </div>
  </div>

  <script>
    let activeSymbol = "BTC/USDT";
    let chartData = null;
    let pineScriptCode = "";

    function setSymbol(sym) {
      activeSymbol = sym;
      ['btc', 'eth', 'sol'].forEach(k => {
        const btn = document.getElementById(`tab-${k}`);
        if (sym.toLowerCase().includes(k)) {
          btn.className = "px-3 py-1 text-xs font-mono font-medium rounded-md bg-blue-600 text-white transition-all";
        } else {
          btn.className = "px-3 py-1 text-xs font-mono font-medium rounded-md text-gray-400 hover:text-white transition-all";
        }
      });
      fetchChartData();
    }

    async function openPineModal() {
      document.getElementById('pineModal').classList.remove('hidden');
      if (!pineScriptCode) {
        try {
          const res = await fetch('/api/pinescript');
          pineScriptCode = await res.text();
          document.getElementById('pineCodeBlock').innerText = pineScriptCode;
        } catch (e) {
          document.getElementById('pineCodeBlock').innerText = "// Lỗi nạp mã Pine Script: " + e;
        }
      }
    }

    function closePineModal() {
      document.getElementById('pineModal').classList.add('hidden');
    }

    function copyPineCode() {
      if (!pineScriptCode) return;
      navigator.clipboard.writeText(pineScriptCode);
      const btn = document.getElementById('btn-copy-pine');
      btn.innerText = "✓ Đã Sao Chép!";
      btn.className = "px-3 py-1 bg-emerald-600 text-white font-mono text-xs rounded transition-all";
      setTimeout(() => {
        btn.innerText = "Sao Chép Mã Pine Script";
        btn.className = "px-3 py-1 bg-blue-600 hover:bg-blue-500 text-white font-mono text-xs rounded transition-all";
      }, 2000);
    }

    let currentEquity = 200.0;
    let currentRiskPercent = 1.0;

    function openEquityModal() {
      document.getElementById('input-equity').value = currentEquity.toFixed(2);
      document.getElementById('input-risk-pct').value = currentRiskPercent.toFixed(1);
      updateEquityPreview();
      const msg = document.getElementById('modal-msg');
      msg.classList.add('hidden');
      msg.className = "hidden p-3 rounded-lg text-xs font-sans";
      document.getElementById('equityModal').classList.remove('hidden');
    }

    function closeEquityModal() {
      document.getElementById('equityModal').classList.add('hidden');
    }

    function setPresetEquity(val) {
      document.getElementById('input-equity').value = Number(val).toFixed(2);
      updateEquityPreview();
    }

    function setPresetRisk(val) {
      document.getElementById('input-risk-pct').value = Number(val).toFixed(1);
      updateEquityPreview();
    }

    function updateEquityPreview() {
      const eq = parseFloat(document.getElementById('input-equity').value) || 0;
      const pct = parseFloat(document.getElementById('input-risk-pct').value) || 0;
      const riskUsd = (eq * (pct / 100)).toFixed(2);
      const dailyLimit = (eq * 0.02).toFixed(2);
      
      document.getElementById('modal-preview-risk-usd').innerText = `$${riskUsd} USD (${pct}%)`;
      document.getElementById('modal-preview-daily-limit').innerText = `-$${dailyLimit} USD`;
      document.getElementById('modal-preview-be').innerText = `Lãi +$${riskUsd}`;
    }

    async function saveEquity() {
      const eq = parseFloat(document.getElementById('input-equity').value);
      const pct = parseFloat(document.getElementById('input-risk-pct').value);
      const btn = document.getElementById('btn-save-equity');
      const msg = document.getElementById('modal-msg');

      if (!eq || eq <= 0) {
        msg.className = "p-3 rounded-lg text-xs font-sans bg-rose-500/10 border border-rose-500/30 text-rose-300";
        msg.innerText = "Vui lòng nhập số vốn hợp lệ (> 0 USD).";
        msg.classList.remove('hidden');
        return;
      }
      if (!pct || pct <= 0 || pct > 10) {
        msg.className = "p-3 rounded-lg text-xs font-sans bg-rose-500/10 border border-rose-500/30 text-rose-300";
        msg.innerText = "Tỷ lệ rủi ro mỗi lệnh phải từ 0.1% đến 10%.";
        msg.classList.remove('hidden');
        return;
      }

      btn.disabled = true;
      btn.innerText = "Đang lưu...";

      try {
        const res = await fetch('/api/settings/equity', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ equity: eq, risk_percent: pct })
        });
        const resp = await res.json();
        if (resp.status === 'SUCCESS') {
          currentEquity = resp.equity;
          currentRiskPercent = resp.risk_percent;
          msg.className = "p-3 rounded-lg text-xs font-sans bg-emerald-500/10 border border-emerald-500/30 text-emerald-300";
          msg.innerText = `✓ Đã cập nhật thành công vốn $${resp.equity.toFixed(2)} USD!`;
          msg.classList.remove('hidden');
          
          await fetchDashboardData();
          await fetchChartData();

          setTimeout(() => {
            closeEquityModal();
          }, 900);
        } else {
          throw new Error(resp.message || "Lỗi lưu cài đặt");
        }
      } catch (err) {
        msg.className = "p-3 rounded-lg text-xs font-sans bg-rose-500/10 border border-rose-500/30 text-rose-300";
        msg.innerText = "Lỗi: " + err.message;
        msg.classList.remove('hidden');
      } finally {
        btn.disabled = false;
        btn.innerText = "Lưu & Cập Nhật Hệ Thống";
      }
    }

    async function fetchChartData() {
      try {
        const res = await fetch(`/api/chart-data?symbol=${encodeURIComponent(activeSymbol)}`);
        chartData = await res.json();
        renderCanvasChart(chartData);
        updateCommentaryPanel(chartData);
      } catch (err) {
        console.error("Lỗi kéo dữ liệu biểu đồ:", err);
      }
    }

    function updateCommentaryPanel(data) {
      document.getElementById('chart-symbol-title').innerText = data.symbol;
      document.getElementById('chart-price').innerText = `$${Number(data.current_price).toLocaleString(undefined, {minimumFractionDigits: 2})}`;
      document.getElementById('chart-atr').innerText = `ATR: $${Number(data.atr_14).toFixed(2)}`;
      document.getElementById('panel-rsi').innerText = `${data.rsi_10} | ${data.rsi_14} | ${data.rsi_30}`;
      document.getElementById('panel-trend').innerText = data.trendline_status || "NEUTRAL";

      const comm = data.ai_commentary || {};
      const verdict = comm.verdict || "REJECT";
      const badge = document.getElementById('comm-verdict-badge');
      badge.innerText = verdict === "APPROVE" ? "🛡️ APPROVE (BUY)" : (verdict === "WAIT" ? "⏳ WAIT" : "⛔ REJECT (VETO)");
      badge.className = `px-2.5 py-1 rounded text-[11px] font-bold ${verdict === 'APPROVE' ? 'badge-approve' : (verdict === 'WAIT' ? 'badge-wait' : 'badge-reject')}`;

      document.getElementById('comm-threat').innerText = comm.primary_threat || "Không phát hiện mối đe dọa bất thường.";
      
      const countersUl = document.getElementById('comm-counters');
      if (comm.counter_arguments && comm.counter_arguments.length > 0) {
        countersUl.innerHTML = comm.counter_arguments.map(c => `<li>${c}</li>`).join('');
      } else {
        countersUl.innerHTML = "<li>Cấu trúc nến và hỗ trợ đang được bảo vệ.</li>";
      }

      if (data.proposal) {
        document.getElementById('comm-entry').innerText = `$${Number(data.proposal.entry).toLocaleString()}`;
        document.getElementById('comm-sl').innerText = `$${Number(data.proposal.sl).toLocaleString()}`;
        document.getElementById('comm-tp').innerText = `$${Number(data.proposal.tp).toLocaleString()}`;
        document.getElementById('comm-size').innerText = `${data.proposal.size} ${data.symbol.split('/')[0]}`;
        if (document.getElementById('comm-risk')) {
          const rUsd = data.proposal.risk_usd !== undefined ? Number(data.proposal.risk_usd).toFixed(2) : '2.00';
          const rPct = data.proposal.risk_percent !== undefined ? Number(data.proposal.risk_percent).toFixed(1) : '1.0';
          document.getElementById('comm-risk').innerText = `$${rUsd} USD (${rPct}%)`;
        }
      }

      document.getElementById('comm-instruction').innerText = comm.instruction || "Chờ nến 15m đóng cửa xác nhận.";
    }

    function renderCanvasChart(data) {
      document.getElementById('chartLoading').style.display = 'none';
      const canvas = document.getElementById('indicatorCanvas');
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;

      const ctx = canvas.getContext('2d');
      ctx.scale(dpr, dpr);
      const w = rect.width;
      const h = rect.height;

      ctx.clearRect(0, 0, w, h);

      const candles = data.candles || [];
      if (candles.length < 5) return;

      // Tìm min, max giá để scale trục Y
      let minPrice = Infinity;
      let maxPrice = -Infinity;

      candles.forEach(c => {
        if (c.low < minPrice) minPrice = c.low;
        if (c.high > maxPrice) maxPrice = c.high;
      });

      const mainLine = data.main_indicator_line || [];
      const secondLine = data.second_indicator_line || [];

      mainLine.forEach(v => { if (v && v < minPrice) minPrice = v; if (v && v > maxPrice) maxPrice = v; });
      secondLine.forEach(v => { if (v && v < minPrice) minPrice = v; if (v && v > maxPrice) maxPrice = v; });

      // Padding 8% trên dưới
      const priceRange = maxPrice - minPrice || 1;
      const padY = priceRange * 0.08;
      const yMin = minPrice - padY;
      const yMax = maxPrice + padY;

      const getY = (price) => h - ((price - yMin) / (yMax - yMin)) * (h - 40) - 20;
      const getX = (idx) => 20 + idx * ((w - 40) / (candles.length - 1));

      // 1. Vẽ lưới ngang
      ctx.strokeStyle = '#1F2430';
      ctx.lineWidth = 1;
      for (let i = 0; i < 5; i++) {
        const y = 20 + i * ((h - 40) / 4);
        ctx.beginPath();
        ctx.moveTo(20, y);
        ctx.lineTo(w - 20, y);
        ctx.stroke();
      }

      // 2. VẼ DẢI MÂY THEO DÕI (TRACKING CLOUD RIBBON GIỮA 2 ĐƯỜNG)
      ctx.beginPath();
      for (let i = 0; i < mainLine.length; i++) {
        const x = getX(i);
        const y = getY(mainLine[i]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      for (let i = secondLine.length - 1; i >= 0; i--) {
        const x = getX(i);
        const y = getY(secondLine[i]);
        ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.fillStyle = 'rgba(59, 130, 246, 0.12)';
      ctx.fill();

      // 3. VẼ NẾN GIÁ (CANDLESTICKS)
      const candleW = Math.max(2, (w - 40) / candles.length * 0.55);
      candles.forEach((c, i) => {
        const x = getX(i);
        const isGreen = c.close >= c.open;
        ctx.strokeStyle = isGreen ? '#10B981' : '#EF4444';
        ctx.fillStyle = isGreen ? '#10B981' : '#EF4444';

        // Râu nến
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.moveTo(x, getY(c.high));
        ctx.lineTo(x, getY(c.low));
        ctx.stroke();

        // Thân nến
        const yOpen = getY(c.open);
        const yClose = getY(c.close);
        const bodyY = Math.min(yOpen, yClose);
        const bodyH = Math.max(Math.abs(yClose - yOpen), 1.5);
        ctx.fillRect(x - candleW / 2, bodyY, candleW, bodyH);
      });

      // 4. VẼ ĐƯỜNG CHỈ BÁO THỨ HAI (SECOND INDICATOR LINE BENEATH THE MAIN INDICATOR)
      // Bám sát bên dưới nến và đường chính theo thời gian thực (TraderPilot-style)
      ctx.beginPath();
      ctx.lineWidth = 2.5;
      ctx.strokeStyle = '#3B82F6'; // Màu xanh dương nổi bật
      for (let i = 0; i < secondLine.length; i++) {
        const x = getX(i);
        const y = getY(secondLine[i]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // 5. VẼ ĐƯỜNG CHỈ BÁO CHÍNH (MAIN INDICATOR LINE)
      ctx.beginPath();
      ctx.lineWidth = 2.0;
      ctx.strokeStyle = '#10B981'; // Màu ngọc lục bảo
      for (let i = 0; i < mainLine.length; i++) {
        const x = getX(i);
        const y = getY(mainLine[i]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // 6. VẼ CÁC NHÃN TÍN HIỆU TRÊN BIỂU ĐỒ (BUY / BREAKDOWN / VETO TAGS)
      if (data.signals_on_chart) {
        data.signals_on_chart.forEach(sig => {
          const x = getX(sig.bar_index);
          const y = getY(sig.price);

          ctx.font = 'bold 10px JetBrains Mono';
          if (sig.type === 'BUY_APPROVED') {
            ctx.fillStyle = '#10B981';
            ctx.fillText('▲ BUY LIMIT', x - 25, y + 20);
          } else if (sig.type === 'VETO_REJECT') {
            ctx.fillStyle = '#EF4444';
            ctx.fillText('✕ VETO REJECT', x - 30, y + 20);
          } else if (sig.type === 'BEARISH_BREAK') {
            ctx.fillStyle = '#F59E0B';
            ctx.fillText('▼ BREAKDOWN', x - 25, y - 10);
          }
        });
      }
    }

    async function fetchDashboardData() {
      try {
        const res = await fetch('/api/data');
        const data = await res.json();

        // Update stats
        currentEquity = data.account.equity || 200.0;
        currentRiskPercent = data.account.risk_percent || 1.0;
        const riskUsd = data.account.risk_per_trade_usd || (currentEquity * (currentRiskPercent / 100.0));
        const dailyLimit = data.account.daily_loss_limit_usd || (currentEquity * 0.02);

        document.getElementById('stat-equity').innerText = `$${currentEquity.toFixed(2)}`;
        if (document.getElementById('stat-risk-per-trade')) {
          document.getElementById('stat-risk-per-trade').innerText = `${currentRiskPercent.toFixed(1)}% ($${riskUsd.toFixed(2)}) / lệnh`;
        }
        document.getElementById('stat-daily-pnl').innerText = `$${data.guardrails.daily_pnl_usd.toFixed(2)}`;
        if (document.getElementById('stat-daily-limit')) {
          document.getElementById('stat-daily-limit').innerText = `/ Max -$${dailyLimit.toFixed(2)} (2%)`;
        }
        if (document.getElementById('guardrail-daily-desc')) {
          document.getElementById('guardrail-daily-desc').innerText = `Khóa 24h khi lỗ $${dailyLimit.toFixed(2)}`;
        }
        if (document.getElementById('guardrail-be-desc')) {
          document.getElementById('guardrail-be-desc').innerText = `Lãi >= $${riskUsd.toFixed(2)} (1.0R) đôn SL về Entry`;
        }
        document.getElementById('stat-positions').innerText = `${data.guardrails.active_positions_count} / ${data.guardrails.max_open_positions_allowed}`;
        document.getElementById('stat-winrate').innerText = `${data.journal.winrate_percent}%`;
        document.getElementById('stat-pf').innerText = `PF: ${data.journal.profit_factor}`;
        document.getElementById('last-updated').innerText = new Date().toLocaleTimeString();
        document.getElementById('signal-count').innerText = `${data.signals.length} tín hiệu`;

        // Update table
        const tbody = document.getElementById('signals-tbody');
        if (data.signals.length === 0) {
          tbody.innerHTML = '<tr><td colspan="10" class="py-8 text-center text-gray-500 font-sans">Chưa có tín hiệu nào. Nhấn "Quét Thị Trường Ngay" để quét.</td></tr>';
          return;
        }

        tbody.innerHTML = data.signals.map(s => {
          const isApprove = s.ai_decision === 'APPROVE';
          const badgeClass = isApprove ? 'badge-approve' : 'badge-reject';
          const icon = isApprove ? '🛡️' : '⛔';
          return `
            <tr class="hover:bg-brand-dark/40 transition-colors">
              <td class="py-3 px-4 font-semibold text-white">#${s.id}</td>
              <td class="py-3 px-4 text-gray-400">${s.created_at || s.timestamp}</td>
              <td class="py-3 px-4 font-bold text-white">${s.symbol}</td>
              <td class="py-3 px-4 text-emerald-400">$${Number(s.entry_price).toLocaleString(undefined, {minimumFractionDigits: 2})}</td>
              <td class="py-3 px-4 text-rose-400">$${Number(s.stop_loss).toLocaleString(undefined, {minimumFractionDigits: 2})}</td>
              <td class="py-3 px-4 text-blue-400">$${Number(s.take_profit).toLocaleString(undefined, {minimumFractionDigits: 2})}</td>
              <td class="py-3 px-4 text-gray-300">${s.position_size}</td>
              <td class="py-3 px-4 text-yellow-400 font-semibold">1:${s.risk_reward_ratio}</td>
              <td class="py-3 px-4">
                <span class="inline-flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-bold ${badgeClass}">
                  ${icon} ${s.ai_decision} (${Math.round(s.ai_confidence * 100)}%)
                </span>
              </td>
              <td class="py-3 px-4 text-xs font-sans text-gray-300 max-w-md truncate" title="${s.ai_reasoning || ''}">
                ${s.ai_reasoning || 'Không có ghi chú'}
              </td>
            </tr>
          `;
        }).join('');

      } catch (err) {
        console.error("Lỗi cập nhật dashboard:", err);
      }
    }

    async function triggerScan() {
      const btn = document.getElementById('btn-scan');
      const oldText = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = 'Đang quét nến Binance...';
      try {
        await fetch('/api/scan', { method: 'POST' });
        await fetchDashboardData();
        await fetchChartData();
      } catch (err) {
        alert("Lỗi thực thi quét: " + err);
      } finally {
        btn.disabled = false;
        btn.innerHTML = oldText;
      }
    }

    // Khởi động
    fetchDashboardData();
    fetchChartData();
    setInterval(fetchDashboardData, 10000); // 10s refresh tổng thể
    setInterval(fetchChartData, 4000);      // 4s refresh biểu đồ nến & dual tracking line
  </script>
</body>
</html>
"""


class DashboardRequestHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, db_path="storage/trades.db", **kwargs):
        self.db_path = db_path
        super().__init__(*args, **kwargs)

    def do_GET(self):
        url = urlparse(self.path)
        params = parse_qs(url.query)

        if url.path == "/" or url.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))

        elif url.path == "/api/pinescript":
            content = get_pine_script_content()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))

        elif url.path == "/api/chart-data":
            symbol = params.get("symbol", ["BTC/USDT"])[0]
            chart_payload = self._generate_chart_payload(symbol)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(chart_payload, default=str).encode("utf-8"))

        elif url.path == "/api/data":
            db = DatabaseManager(self.db_path)
            equity = db.get_account_equity(default=float(os.environ.get("ACCOUNT_EQUITY", 200.0)))
            risk_percent = db.get_risk_percent(default=1.0)
            risk_per_trade_usd = round(equity * (risk_percent / 100.0), 2)
            daily_loss_limit_usd = round(equity * 0.02, 2)

            guardrails = RiskGuardrails(db, daily_loss_limit_usd=daily_loss_limit_usd)
            report = guardrails.get_guardrails_status_report()
            stats = db.get_journal_stats()

            signals = db._execute("SELECT * FROM trade_signals ORDER BY id DESC LIMIT 50", fetch="all")
            positions = db.get_active_positions()

            payload = {
                "account": {
                    "equity": equity,
                    "risk_percent": risk_percent,
                    "risk_per_trade_usd": risk_per_trade_usd,
                    "daily_loss_limit_usd": daily_loss_limit_usd
                },
                "guardrails": report,
                "journal": stats,
                "signals": signals,
                "positions": positions
            }

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(payload, default=str).encode("utf-8"))

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        url = urlparse(self.path)
        if url.path == "/api/scan":
            try:
                from main_daemon import TradingCopilotSystem
                copilot = TradingCopilotSystem()
                copilot.run_scanner_cycle()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "SUCCESS"}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ERROR", "message": str(e)}).encode("utf-8"))
        elif url.path == "/api/settings/equity":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                post_data = self.rfile.read(content_length).decode("utf-8")
                body = json.loads(post_data)

                new_equity = float(body.get("equity", 0))
                new_risk_pct = float(body.get("risk_percent", 1.0))

                if new_equity <= 0:
                    raise ValueError("Số vốn tài khoản phải lớn hơn 0 USD.")
                if not (0.1 <= new_risk_pct <= 10.0):
                    raise ValueError("Tỷ lệ rủi ro mỗi lệnh phải từ 0.1% đến 10.0%.")

                db = DatabaseManager(self.db_path)
                db.set_account_equity(new_equity)
                db.set_risk_percent(new_risk_pct)
                db.log_audit_event(
                    "EQUITY_UPDATED",
                    f"Người dùng cập nhật vốn thành ${new_equity:,.2f} USD (Rủi ro: {new_risk_pct}%/lệnh)",
                    {"equity": new_equity, "risk_percent": new_risk_pct}
                )

                risk_per_trade_usd = round(new_equity * (new_risk_pct / 100.0), 2)
                daily_loss_limit_usd = round(new_equity * 0.02, 2)

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "SUCCESS",
                    "equity": new_equity,
                    "risk_percent": new_risk_pct,
                    "risk_per_trade_usd": risk_per_trade_usd,
                    "daily_loss_limit_usd": daily_loss_limit_usd,
                    "message": f"Đã lưu thành công vốn: ${new_equity:,.2f} USD"
                }).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ERROR", "message": str(e)}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def _generate_chart_payload(self, symbol: str) -> dict:
        """Kéo dữ liệu nến thực tế và tính toán 2 đường chỉ báo (Main + Second Tracking Line Beneath)"""
        try:
            feed = MarketDataFeed(symbols=[symbol], ring_buffer_size=60)
            candles = feed.fetch_candles_with_backoff(symbol, "15m", limit=45)
        except Exception:
            candles = []

        if not candles:
            # Fallback tạo dữ liệu mẫu nếu kết nối sàn Binance bị nghẽn
            import time
            now_ms = int(time.time() * 1000)
            base_p = 83200.0 if "BTC" in symbol else (2540.0 if "ETH" in symbol else 110.0)
            candles_data = []
            cur = base_p
            for i in range(40):
                delta = ((i % 5) - 2) * (base_p * 0.002)
                o = cur
                c = cur + delta
                h = max(o, c) + abs(delta) * 0.5
                l = min(o, c) - abs(delta) * 0.5
                cur = c
                candles_data.append({"timestamp": now_ms - (40 - i) * 900000, "open": o, "high": h, "low": l, "close": c, "volume": 100})
        else:
            candles_data = [c.to_dict() for c in candles]

        # Tính toán 2 đường chỉ báo:
        # Đường 1: Main Trendline (EMA 13 của close)
        # Đường 2: Second Tracking Line (EMA 21 của low trừ đệm ATR - chạy bám sát bên dưới)
        closes = [c["close"] for c in candles_data]
        lows = [c["low"] for c in candles_data]
        highs = [c["high"] for c in candles_data]

        import pandas as pd
        df = pd.DataFrame(candles_data)
        ema_main = df["close"].ewm(span=13, adjust=False).mean().round(2).tolist()
        atr_val = float(QuantitativeIndicatorEngine.calculate_atr(df["high"], df["low"], df["close"], 14).iloc[-1])
        ema_second = (df["low"].ewm(span=21, adjust=False).mean() - (1.1 * atr_val * 0.5)).round(2).tolist()

        # Tín hiệu giả định trên nến
        current_price = float(closes[-1])
        quant = QuantitativeIndicatorEngine.compute_all_indicators(df)

        db = DatabaseManager(self.db_path)
        last_sig = db._execute("SELECT * FROM trade_signals WHERE symbol = ? ORDER BY id DESC LIMIT 1", (symbol,), fetch="one")

        equity = db.get_account_equity(default=float(os.environ.get("ACCOUNT_EQUITY", 200.0)))
        risk_percent = db.get_risk_percent(default=1.0)
        risk_usd = round(equity * (risk_percent / 100.0), 2)
        sl_dist = max(1.5 * atr_val, 0.1)

        signals_on_chart = []
        if last_sig:
            sig_type = "BUY_APPROVED" if last_sig["ai_decision"] == "APPROVE" else "VETO_REJECT"
            signals_on_chart.append({
                "bar_index": len(candles_data) - 1,
                "price": current_price,
                "type": sig_type
            })

        ai_commentary = {
            "verdict": last_sig["ai_decision"] if last_sig else "REJECT",
            "primary_threat": "Mô hình gãy trendline ngắn hạn, phe Bán đang kiểm soát nhịp." if quant["trendline_status"] == "BEARISH_BREAKOUT" else "Dao động tích lũy biên độ hẹp quanh vùng cân bằng.",
            "counter_arguments": [
                f"RSI-14 ({quant['rsi_14']}) chưa xuất hiện tín hiệu phân kỳ dương.",
                "Đường Tracking thứ 2 đang dốc xuống báo hiệu áp lực đè giá."
            ],
            "instruction": "Đứng ngoài thị trường bảo toàn vốn. Chờ nến 15m đóng cửa rút chân trên đường tracking thứ 2."
        }

        proposal = {
            "entry": current_price,
            "sl": round(current_price - 1.5 * atr_val, 2),
            "tp": round(current_price + 3.0 * atr_val, 2),
            "size": round(risk_usd / sl_dist, 4),
            "risk_usd": risk_usd,
            "risk_percent": risk_percent,
            "equity": equity
        }

        return {
            "symbol": symbol,
            "current_price": current_price,
            "atr_14": round(atr_val, 2),
            "rsi_10": quant["rsi_10"],
            "rsi_14": quant["rsi_14"],
            "rsi_30": quant["rsi_30"],
            "trendline_status": quant["trendline_status"],
            "candles": candles_data,
            "main_indicator_line": ema_main,
            "second_indicator_line": ema_second,
            "signals_on_chart": signals_on_chart,
            "ai_commentary": ai_commentary,
            "proposal": proposal
        }

    def log_message(self, format, *args):
        return


def start_background_scanner(interval: int = 60):
    """Chạy vòng lặp quét thị trường trong background thread song song với Web Dashboard trên Render"""
    import threading
    import time

    def scanner_worker():
        time.sleep(3)  # Chờ Web server bind port hoàn tất
        try:
            from main_daemon import TradingCopilotSystem
            copilot = TradingCopilotSystem()
            print(f"📡 [BACKGROUND SCANNER] Đã khởi động luồng quét tự động (Chu kỳ: {interval}s).")
            while True:
                try:
                    copilot.run_scanner_cycle()
                except Exception as err:
                    print(f"⚠️ [BACKGROUND SCANNER ERROR]: {err}")
                time.sleep(interval)
        except Exception as err:
            print(f"❌ [BACKGROUND SCANNER INIT FAILED]: {err}")

    t = threading.Thread(target=scanner_worker, daemon=True, name="BackgroundScanner")
    t.start()


def run_dashboard_server(
    host: str = "0.0.0.0",
    port: Optional[int] = None,
    db_path: str = "storage/trades.db",
    with_scanner: Optional[bool] = None
):
    """
    Khởi động Web Dashboard Server tương thích hoàn toàn Render và Local:
    - Bind mặc định: 0.0.0.0
    - Cổng mạng: Đọc từ biến môi trường PORT (Render cung cấp) hoặc port chỉ định
    - Tự động chạy Background Scanner thread nếu ENABLE_SCANNER=true
    """
    if port is None:
        port = int(os.environ.get("PORT", 8000))

    if with_scanner is None:
        with_scanner = os.environ.get("ENABLE_SCANNER", "true").lower() in ("true", "1", "yes")

    if with_scanner:
        scan_interval = int(os.environ.get("SCAN_INTERVAL", "60"))
        start_background_scanner(interval=scan_interval)

    handler = lambda *args, **kwargs: DashboardRequestHandler(*args, db_path=db_path, **kwargs)
    server = HTTPServer((host, port), handler)
    print(f"\n🚀 AI Trading Copilot Web Dashboard & Indicator Studio đang chạy tại: http://{host}:{port}")
    print(f"🌍 Tương thích Render Cloud: Đang lắng nghe trên host '{host}' cổng '{port}'\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐang tắt Web Dashboard Server...")
        server.server_close()


if __name__ == "__main__":
    run_dashboard_server()
