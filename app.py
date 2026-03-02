import json
import traceback
import re
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from groq import Groq

# ========== CONFIGURATION ==========
API_KEY = "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"
MODEL = "openai/gpt-oss-120b" 

client = Groq(api_key=API_KEY)

APP_DIR = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=str(APP_DIR))

# ========== SIÊU SYSTEM PROMPT (ÉP BUỘC TỌA ĐỘ VÀ FORMAT) ==========
SYSTEM_PROMPT = """
Bạn là SciCanvas AI. Nhiệm vụ: Giải thích khoa học và Viết code SVG mô phỏng.

QUY TẮC BẮT BUỘC:
1. ĐỊNH DẠNG TRẢ VỀ:
   Phải chia làm 2 phần riêng biệt bằng thẻ:
   <EXPLANATION>
   ... (Giải thích dùng LaTeX $$...$$ cho công thức)
   </EXPLANATION>
   <SVG>
   ... (Code SVG thô, KHÔNG ĐƯỢC DÙNG ```svg bao quanh)
   </SVG>

2. QUY TẮC TỌA ĐỘ (CHỐNG LỖI VỊ TRÍ):
   - Luôn dùng ViewBox="0 0 1000 1000".
   - Luôn đặt TÂM VŨ TRỤ ở giữa: <g transform="translate(500, 500)">.
   - Mọi hành tinh/vệ tinh quay quanh tâm phải dùng <animateTransform attributeName="transform" type="rotate" ... />.
   - KHÔNG tự tính toán sin/cos thủ công (dễ sai), hãy dùng Group xoay.

3. THẨM MỸ:
   - Nền vũ trụ màu tối #050510.
   - Hành tinh phải có Gradient 3D.
   - Có hiệu ứng Glow (Filter).
"""

def _build_messages(user_prompt: str, history: list, last_svg: str):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in (history or []):
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    
    user_content = user_prompt
    if last_svg and last_svg.strip():
        user_content += "\n\n---\n[SVG cũ:]\n" + last_svg.strip()

    messages.append({"role": "user", "content": user_content})
    return messages


@app.route("/")
def index():
    return send_from_directory(APP_DIR, "index.html")


@app.route("/api/simulate/stream", methods=["POST"])
def simulate_stream():
    data = request.get_json() or {}
    user_prompt = (data.get("prompt") or "").strip()

    if not user_prompt:
        return jsonify({"error": "Empty prompt"}), 400

    last_svg = data.get("last_svg") or ""
    history = data.get("history") or []

    messages = _build_messages(user_prompt, history, last_svg)

    def generate_events():
        try:
            stream = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=1, 
                stream=True,
               reasoning_effort="high",
            )

            full_text = ""
            last_yielded_expl_idx = 0
            explanation_started = False
            explanation_ended = False

            for chunk in stream:
                if not chunk.choices or not chunk.choices[0].delta.content:
                    continue
                delta = chunk.choices[0].delta.content
                full_text += delta

                # --- XỬ LÝ PHẦN GIẢI THÍCH ---
                if not explanation_started:
                    if "<EXPLANATION>" in full_text:
                        explanation_started = True
                        last_yielded_expl_idx = full_text.find("<EXPLANATION>") + len("<EXPLANATION>")
                    # Fallback nếu AI quên thẻ
                    elif len(full_text) > 50 and "<SVG>" not in full_text and "<svg" not in full_text: 
                        if not "<EXPLANATION>" in full_text:
                             explanation_started = True
                             last_yielded_expl_idx = 0

                if explanation_started and not explanation_ended:
                    end_tag = "</EXPLANATION>"
                    if end_tag in full_text:
                        end_idx = full_text.find(end_tag)
                        if end_idx > last_yielded_expl_idx:
                            chunk_text = full_text[last_yielded_expl_idx:end_idx]
                            yield f"event: explanation\ndata: {json.dumps({'c': chunk_text})}\n\n"
                        last_yielded_expl_idx = len(full_text)
                        explanation_ended = True
                    elif "<SVG>" in full_text: # Gặp thẻ SVG thì dừng giải thích
                        end_idx = full_text.find("<SVG>")
                        if end_idx > last_yielded_expl_idx:
                            chunk_text = full_text[last_yielded_expl_idx:end_idx]
                            yield f"event: explanation\ndata: {json.dumps({'c': chunk_text})}\n\n"
                        last_yielded_expl_idx = len(full_text)
                        explanation_ended = True
                    else:
                        safe_end = max(last_yielded_expl_idx, len(full_text) - 10)
                        if safe_end > last_yielded_expl_idx:
                            chunk_text = full_text[last_yielded_expl_idx:safe_end]
                            if chunk_text:
                                yield f"event: explanation\ndata: {json.dumps({'c': chunk_text})}\n\n"
                            last_yielded_expl_idx = safe_end

            # --- XỬ LÝ VÀ LÀM SẠCH SVG (QUAN TRỌNG NHẤT) ---
            svg_content = ""
            
            # 1. Cố gắng tìm nội dung giữa thẻ <SVG>
            if "<SVG>" in full_text and "</SVG>" in full_text:
                start = full_text.find("<SVG>") + len("<SVG>")
                end = full_text.find("</SVG>")
                svg_content = full_text[start:end]
            
            # 2. Nếu không có thẻ bao, tìm trực tiếp thẻ <svg ...>
            elif "<svg" in full_text and "</svg>" in full_text:
                start = full_text.find("<svg")
                end = full_text.find("</svg>") + len("</svg>")
                svg_content = full_text[start:end]

            if svg_content:
                # === BƯỚC LÀM SẠCH ===
                # Loại bỏ markdown code block ```svg và ```
                svg_content = svg_content.replace("```svg", "").replace("```", "").strip()
                
                # Gửi SVG sạch về client
                yield f"event: svg\ndata: {json.dumps({'c': svg_content})}\n\n"

        except Exception as e:
            traceback.print_exc()
            yield f"event: explanation\ndata: {json.dumps({'c': f'<br><br>**Lỗi:** {str(e)}'})}\n\n"

        yield f"event: done\ndata: {{}}\n\n"

    return Response(stream_with_context(generate_events()), content_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

