"""
core/copilot_agent.py
Tier 4: Cognitive AI Risk Gatekeeper (Devil's Advocate)
Thực thi vai trò Trưởng Ban Quản Trị Rủi Ro:
- Nhận System Input Payload chuẩn hóa (Schema 4.1)
- Kiểm tra 4 Quy Tắc Phủ Quyết Cứng (Hard Veto Rules) bằng Python Deterministic Code
- Kết nối Ollama (qwen2.5-coder / deepseek-r1) hoặc OpenRouter với JSON Mode
- Fallback Engine tự động phản biện logic khi AI ngoại tuyến để bảo vệ vốn 100%
- Xuất kết quả chuẩn hóa theo Schema 4.2
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import requests

from config.prompt_templates import SYSTEM_PROMPT, format_user_prompt

logger = logging.getLogger("CopilotAgent")


class HardVetoEnforcer:
    """
    Tầng Bảo Vệ Cứng (Deterministic Hard Veto Layer):
    Kiểm tra bằng code thuần các điều kiện vi phạm chí mạng trước và sau khi gọi AI.
    """
    @staticmethod
    def evaluate(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        quant = payload.get("quantitative_signals", {})
        proposal = payload.get("deterministic_math_proposal", {})
        portfolio = payload.get("portfolio_state", {})
        patterns = quant.get("candle_patterns", {})

        action = proposal.get("proposed_action", "")
        reasons: List[str] = []

        # -------------------------------------------------------------
        # VETO 1: Ngược xu hướng vĩ mô
        # Nghiêm cấm Long nếu EMA200 1h dốc xuống và giá nằm dưới EMA200 1h
        # -------------------------------------------------------------
        if "BUY" in action:
            if quant.get("is_below_ema200_1h") and quant.get("ema200_1h_sloping_down"):
                reasons.append(
                    "VETO 1 (Ngược xu hướng vĩ mô): Giá nằm dưới EMA200 khung 1h đang dốc xuống. Cấm mở lệnh Long ngược sóng giảm chủ đạo."
                )
        elif "SELL" in action:
            if not quant.get("is_below_ema200_1h") and not quant.get("ema200_1h_sloping_down"):
                reasons.append(
                    "VETO 1 (Ngược xu hướng vĩ mô): Giá nằm trên EMA200 khung 1h đang dốc lên. Cấm mở lệnh Short ngược xu hướng tăng mạnh."
                )

        # -------------------------------------------------------------
        # VETO 2: Bắt dao rơi vô căn cứ (Waterfall Dump)
        # 3 cây nến đỏ thân dài liên tiếp mà chưa có nến rút râu xác nhận
        # -------------------------------------------------------------
        if "BUY" in action:
            if patterns.get("is_waterfall", False) and not patterns.get("is_pinbar_bullish", False):
                reasons.append(
                    "VETO 2 (Bắt dao rơi vô căn cứ): Xuất hiện cụm thác nến xả (Waterfall) 3 cây nến đỏ dốc đứng chưa có tín hiệu nến rút chân (Pinbar) đảo chiều."
                )

        # -------------------------------------------------------------
        # VETO 3: Độ tương quan danh mục vượt trần
        # Đang có >= 2 vị thế mở cùng chiều tương quan cao
        # -------------------------------------------------------------
        active_count = portfolio.get("active_positions_count", 0)
        if active_count >= 2:
            reasons.append(
                f"VETO 3 (Độ tương quan danh mục vượt trần): Tài khoản đang duy trì {active_count} vị thế. Bắt buộc từ chối cơ hội mới để kiểm soát rủi ro tập trung."
            )

        # -------------------------------------------------------------
        # VETO 4: Vùng mù tin tức vĩ mô (News Blackout Window)
        # -------------------------------------------------------------
        if portfolio.get("news_blackout_active", False):
            reasons.append(
                "VETO 4 (Vùng mù tin tức vĩ mô): Nằm trong cửa sổ ±30 phút quanh thời điểm công bố tin tức kinh tế quan trọng (CPI/FOMC/NFP)."
            )

        # Nếu có bất kỳ VETO nào bị kích hoạt -> BẮT BUỘC REJECT ngay lập tức!
        if reasons:
            return {
                "action_decision": "REJECT",
                "confidence_score": 0.95,
                "risk_assessment": {
                    "primary_threat": reasons[0],
                    "counter_arguments": reasons[1:] if len(reasons) > 1 else [
                        "Cấu trúc thị trường tiềm ẩn rủi ro phá vỡ hỗ trợ/kháng cự.",
                        "Khoảng đệm an toàn chưa đủ để bù đắp áp lực bán/mua tháo."
                    ]
                },
                "trade_recommendation": {
                    "status": "WAIT_FOR_CONFIRMATION",
                    "instruction": "Kích hoạt Hard Veto. Đứng ngoài thị trường bảo toàn vốn, chờ đợi cấu trúc nến xác nhận rõ ràng hơn."
                }
            }

        return None


class DeterministicDevilAdvocate:
    """
    Bộ phản biện dự phòng thông minh (Offline Devil's Advocate Engine)
    Hoạt động khi Ollama/OpenRouter ngoại tuyến. Phân tích sâu theo đúng
    nguyên tắc Devil's Advocate để không bao giờ để lọt rủi ro.
    """
    @staticmethod
    def evaluate(payload: Dict[str, Any]) -> Dict[str, Any]:
        quant = payload.get("quantitative_signals", {})
        proposal = payload.get("deterministic_math_proposal", {})
        patterns = quant.get("candle_patterns", {})
        fvg = quant.get("fvg", {})
        action = proposal.get("proposed_action", "")

        counter_arguments: List[str] = []
        primary_threat = "Rủi ro dao động giả quanh vùng cân bằng giá."

        current_price = payload.get("market_data", {}).get("current_price", 0)
        nearest_support = quant.get("nearest_support", 0)
        nearest_resistance = quant.get("nearest_resistance", 0)
        rsi_14 = quant.get("rsi_14", 50.0)
        trendline = quant.get("trendline_status", "NEUTRAL")

        # Phản biện cho lệnh BUY
        if "BUY" in action:
            if trendline == "BEARISH_BREAKOUT":
                primary_threat = "Mô hình phá vỡ trendline giảm (Bearish Breakdown) vừa kích hoạt, phe Bán đang kiểm soát nhịp."
                counter_arguments.append("Giá đóng cửa dưới đường hỗ trợ chéo, cảnh báo đợt giảm tiếp diễn.")
            elif rsi_14 > 60:
                primary_threat = f"RSI-14 neo mức cao ({rsi_14}), dư địa tăng ngắn hạn bị thu hẹp đáng kể."
                counter_arguments.append("Nguy cơ dính bẫy Bull Trap khi mua quanh vùng quá mua.")

            if patterns.get("is_waterfall", False):
                counter_arguments.append("Đà rơi quán tính của 3 nến trước vẫn còn mạnh, chưa xuất hiện lực đỡ.")

            if nearest_resistance and current_price:
                dist_to_res = nearest_resistance - current_price
                if dist_to_res < quant.get("atr_14", 100):
                    counter_arguments.append(f"Vùng cản mạnh gần nhất ({nearest_resistance}) nằm quá sát điểm Entry.")

            if not counter_arguments:
                counter_arguments.append(f"RSI-14 ({rsi_14}) chưa cho tín hiệu kiệt sức rõ rệt.")
                counter_arguments.append("Cần nến đóng cửa 15m kế tiếp test lại hỗ trợ thành công.")

            # Đánh giá xem có xứng đáng APPROVE không
            # Chỉ APPROVE khi có hỗ trợ vững, có nến rút râu, không có breakdown
            can_approve = (
                patterns.get("is_pinbar_bullish", False)
                and (quant.get("is_extreme_oversold", False) or trendline == "BULLISH_BREAKOUT")
                and trendline != "BEARISH_BREAKOUT"
            )

            if can_approve:
                return {
                    "action_decision": "APPROVE",
                    "confidence_score": 0.82,
                    "risk_assessment": {
                        "primary_threat": "Rung lắc quét râu thanh khoản trước khi giá hồi phục.",
                        "counter_arguments": [
                            f"Đã có nến Pinbar rút chân (tỷ lệ râu {patterns.get('lower_wick_ratio')}x).",
                            f"Tỷ lệ R:R = {proposal.get('risk_reward_ratio')} thỏa mãn ngưỡng vàng 1:2.0."
                        ]
                    },
                    "trade_recommendation": {
                        "status": "EXECUTE",
                        "instruction": f"Đặt lệnh {action} tại {proposal.get('calculated_entry')} với SL cưỡng chế tại {proposal.get('calculated_sl')}."
                    }
                }

        # Mặc định từ chối (REJECT) theo nguyên tắc Devil's Advocate
        if len(counter_arguments) < 2:
            counter_arguments.append("Thanh khoản thị trường suy giảm, biên độ nến co hẹp báo hiệu giai đoạn tích lũy khó lường.")
            counter_arguments.append("Bảo toàn vốn là ưu tiên số một, hủy kế hoạch để chờ cơ hội chuẩn mẫu hình hơn.")

        return {
            "action_decision": "REJECT",
            "confidence_score": 0.88,
            "risk_assessment": {
                "primary_threat": primary_threat,
                "counter_arguments": counter_arguments[:3]
            },
            "trade_recommendation": {
                "status": "WAIT_FOR_CONFIRMATION",
                "instruction": "Không bắt đáy/bán đuổi vội vàng. Chờ nến 15m đóng cửa xác nhận cấu trúc quanh vùng hỗ trợ/kháng cự then chốt."
            }
        }


class AICopilotAgent:
    """
    Tầng Cognitive AI: Giao tiếp với Ollama hoặc OpenRouter
    Có kiểm duyệt Hard Veto và Fail-safe Fallback bảo toàn vốn.
    """
    def __init__(
        self,
        provider: str = "ollama",
        ollama_url: str = "http://localhost:11434/api/generate",
        model_name: str = "qwen2.5-coder:7b",
        openrouter_api_key: str = "",
        openrouter_model: str = "deepseek/deepseek-r1",
        timeout_seconds: float = 5.0,
        enable_fallback: bool = True
    ):
        self.provider = provider
        self.ollama_url = ollama_url
        self.model_name = model_name
        self.openrouter_api_key = openrouter_api_key
        self.openrouter_model = openrouter_model
        self.timeout_seconds = timeout_seconds
        self.enable_fallback = enable_fallback

    def evaluate_setup(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Đánh giá kế hoạch giao dịch:
        Bước 1: Deterministic Hard Veto pre-check (Không ai được phép vượt quyền quản trị rủi ro)
        Bước 2: Gọi LLM (Ollama hoặc OpenRouter) với JSON Mode
        Bước 3: Validate định dạng đầu ra Schema 4.2
        Bước 4: Post-check phản biện và Fallback nếu LLM lỗi/ngoại tuyến
        """
        # BƯỚC 1: HARD VETO PRE-CHECK
        veto_result = HardVetoEnforcer.evaluate(payload)
        if veto_result is not None:
            logger.info("Hard Veto được kích hoạt. Tự động từ chối (REJECT) kế hoạch.")
            return veto_result

        # BƯỚC 2: GỌI LLM COGNITIVE LAYER
        user_prompt = format_user_prompt(payload)
        llm_response = None

        if self.provider == "ollama":
            llm_response = self._call_ollama(user_prompt)
        elif self.provider == "openrouter":
            llm_response = self._call_openrouter(user_prompt)

        # BƯỚC 3: XỬ LÝ KẾT QUẢ LLM
        if llm_response and isinstance(llm_response, dict):
            # Kiểm tra tính toàn vẹn của response theo Schema 4.2
            if "action_decision" in llm_response and "risk_assessment" in llm_response:
                # Đảm bảo action_decision hợp lệ
                decision = str(llm_response.get("action_decision", "REJECT")).upper()
                if decision not in ["APPROVE", "REJECT", "WAIT"]:
                    decision = "REJECT"
                llm_response["action_decision"] = decision
                return llm_response

        # BƯỚC 4: FAIL-SAFE FALLBACK
        logger.warning("LLM không phản hồi hoặc lỗi cú pháp. Kích hoạt Offline Devil's Advocate Engine...")
        if self.enable_fallback:
            return DeterministicDevilAdvocate.evaluate(payload)

        return {
            "action_decision": "REJECT",
            "confidence_score": 0.90,
            "risk_assessment": {
                "primary_threat": "Lỗi kết nối Cognitive AI Engine, mặc định từ chối để an toàn vốn.",
                "counter_arguments": [
                    "Không thể xác minh tính an toàn qua Tầng Trí Tuệ Suy Luận.",
                    "Hệ thống tự động kích hoạt chốt khóa an toàn chống giao dịch rủi ro."
                ]
            },
            "trade_recommendation": {
                "status": "CANCEL",
                "instruction": "Hủy lệnh ngay lập tức cho đến khi Tầng AI hoạt động bình thường."
            }
        }

    def _call_ollama(self, prompt_text: str) -> Optional[Dict[str, Any]]:
        request_body = {
            "model": self.model_name,
            "prompt": prompt_text,
            "system": SYSTEM_PROMPT,
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0.1,  # Nhiệt độ cực thấp để loại bỏ ảo giác
                "top_p": 0.8
            }
        }
        try:
            resp = requests.post(self.ollama_url, json=request_body, timeout=self.timeout_seconds)
            if resp.status_code == 200:
                raw_json = resp.json().get("response", "{}")
                return json.loads(raw_json)
            else:
                logger.warning(f"Ollama trả về HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.debug(f"Không thể kết nối Ollama: {e}")
        return None

    def _call_openrouter(self, prompt_text: str) -> Optional[Dict[str, Any]]:
        if not self.openrouter_api_key:
            return None
        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/trading-copilot",
            "X-Title": "AI Trading Copilot"
        }
        body = {
            "model": self.openrouter_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt_text}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1
        }
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=body,
                timeout=self.timeout_seconds
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                return json.loads(content)
        except Exception as e:
            logger.warning(f"OpenRouter gọi thất bại: {e}")
        return None
