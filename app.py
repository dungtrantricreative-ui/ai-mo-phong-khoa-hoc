import json
import traceback
from pathlib import Path
from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from groq import Groq

# ========== CONFIGURATION ==========
API_KEY = "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"
MODEL = "llama-3.3-70b-versatile" 

client = Groq(api_key=API_KEY)

APP_DIR = Path(__file__).resolve().parent
app = Flask(__name__, template_folder=str(APP_DIR), static_folder=str(APP_DIR))

# ========== SIÊU SYSTEM PROMPT (ÉP BUỘC CẤU TRÚC TOẠ ĐỘ CHUẨN) ==========
SYSTEM_PROMPT = """
Bạn là SciCanvas AI – Kỹ sư Đồ họa SVG Siêu thực và là Nhà Vật lý học xuất chúng.

NHIỆM VỤ CỦA BẠN: 
1. Giải thích hiện tượng khoa học (bắt buộc dùng công thức LaTeX dạng $$...$$ hoặc \\[...\\] cho công thức vật lý).
2. Tạo ra mô hình SVG TUYỆT ĐẸP, BẮT BUỘC CÓ ANIMATION, và TỌA ĐỘ PHẢI CHUẨN XÁC.

═══════════════════════════════
LUẬT ĐỊNH DẠNG:
═══════════════════════════════
<EXPLANATION>
Giải thích khoa học (dùng LaTeX cho Toán học).
Dùng [→ id_cua_the_svg] để tham chiếu. VD: "Mặt Trời [→ sun]".
</EXPLANATION>

<SVG>
<svg viewBox="0 0 1000 1000" xmlns="http://www.w3.org/2000/svg">
  <!-- Code SVG ở đây -->
</svg>
</SVG>

═══════════════════════════════
BÍ QUYẾT XÂY DỰNG TỌA ĐỘ ĐỂ VẬT THỂ KHÔNG BỊ SAI LỆCH (QUAN TRỌNG NHẤT):
═══════════════════════════════
LLM thường tính sai tọa độ quỹ đạo. Vì vậy, BẠN BẮT BUỘC PHẢI làm theo cấu trúc NHÓM (Group <g>) có translate để xoay:

1. Thiết lập Tâm Vũ Trụ (Ở giữa khung hình 1000x1000):
   <g transform="translate(500, 500)"> 
     <!-- Vẽ vật trung tâm ở cx="0" cy="0" -->
     <circle id="sun" r="50"/>

     <!-- Vẽ Quỹ đạo -->
     <circle id="orbit-earth" r="250" fill="none" stroke="white" stroke-dasharray="5 5"/>

     <!-- Trái Đất quay quanh Mặt Trời -->
     <g id="earth-system">
       <animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="10s" repeatCount="indefinite"/>
       
       <!-- Dịch chuyển Trái đất ra xa tâm 250px -->
       <g transform="translate(250, 0)">
         <circle id="earth" r="20"/>

         <!-- Mặt Trăng quay quanh Trái Đất (Nested Orbit) -->
         <g id="moon-system">
           <animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="2s" repeatCount="indefinite"/>
           <circle id="moon" cx="40" cy="0" r="5"/> <!-- Dịch ra 40px từ Trái Đất -->
         </g>
       </g>
     </g>
   </g>

LUẬT KHÁC:
- Cấm vẽ các hành tinh quá nhỏ (<5px) hoặc quá to.
- Phải có Gradient 3D và Glow Filter.
- Phải dùng Background màu tối #030613.
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
        user_content += "\n\n---\n[Mã SVG LẦN TRƯỚC (Hãy sửa lại bằng cấu trúc <g transform> nếu lần trước bị sai tọa độ):]\n" + last_svg.strip()

    messages.append({"role": "user", "content": user_content})
    return messages


@app.route("/")
def index():
    return render_template("index.html")


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
                temperature=0.3, # GIỮ NHỎ HƠN 0.5 ĐỂ NÓ KHÔNG CHẾ TOẠ ĐỘ LUNG TUNG
                stream=True,
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

                if not explanation_started:
                    if "<EXPLANATION>" in full_text:
                        explanation_started = True
                        last_yielded_expl_idx = full_text.find("<EXPLANATION>") + len("<EXPLANATION>")
                    elif len(full_text) > 30 and "<EXPLANATION>" not in full_text and "<SVG>" not in full_text and "<svg" not in full_text:
                        explanation_started = True
                        last_yielded_expl_idx = 0

                if explanation_started and not explanation_ended:
                    if "</EXPLANATION>" in full_text:
                        end_idx = full_text.find("</EXPLANATION>")
                        if end_idx > last_yielded_expl_idx:
                            chunk_text = full_text[last_yielded_expl_idx:end_idx]
                            yield f"event: explanation\ndata: {json.dumps({'c': chunk_text})}\n\n"
                        last_yielded_expl_idx = len(full_text)
                        explanation_ended = True
                    elif "<SVG>" in full_text or "<svg " in full_text:
                        end_idx = full_text.find("<SVG>") if "<SVG>" in full_text else full_text.find("<svg ")
                        if end_idx > last_yielded_expl_idx:
                            chunk_text = full_text[last_yielded_expl_idx:end_idx].replace("</EXPLANATION>", "")
                            yield f"event: explanation\ndata: {json.dumps({'c': chunk_text})}\n\n"
                        last_yielded_expl_idx = len(full_text)
                        explanation_ended = True
                    else:
                        safe_end = max(last_yielded_expl_idx, len(full_text) - 15)
                        if safe_end > last_yielded_expl_idx:
                            chunk_text = full_text[last_yielded_expl_idx:safe_end]
                            if chunk_text:
                                yield f"event: explanation\ndata: {json.dumps({'c': chunk_text})}\n\n"
                            last_yielded_expl_idx = safe_end

            svg_content = ""
            if "<SVG>" in full_text and "</SVG>" in full_text:
                start = full_text.find("<SVG>") + len("<SVG>")
                end = full_text.find("</SVG>")
                svg_content = full_text[start:end].strip()
            elif "<svg" in full_text and "</svg>" in full_text:
                start = full_text.find("<svg")
                end = full_text.find("</svg>") + len("</svg>")
                svg_content = full_text[start:end].strip()

            if svg_content:
                yield f"event: svg\ndata: {json.dumps({'c': svg_content})}\n\n"

        except Exception as e:
            traceback.print_exc()
            yield f"event: explanation\ndata: {json.dumps({'c': f'<br><br>**Lỗi API:** {str(e)}'})}\n\n"

        yield f"event: done\ndata: {{}}\n\n"

    return Response(stream_with_context(generate_events()), content_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)