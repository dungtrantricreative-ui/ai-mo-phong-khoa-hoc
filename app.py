import json
import traceback
from pathlib import Path
from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from groq import Groq

# ========== CONFIGURATION ==========
API_KEY = "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"
MODEL = "qwen/qwen3-32b"

client = Groq(api_key=API_KEY)

APP_DIR = Path(__file__).resolve().parent
app = Flask(__name__, template_folder=str(APP_DIR / "templates"), static_folder=str(APP_DIR / "static"))


# ========== SYSTEM PROMPT ==========
SYSTEM_PROMPT = """
Bạn là SciCanvas AI – chuyên gia vật lý, thiên văn, hóa học, sinh học và kỹ sư đồ họa SVG hàng đầu.

NHIỆM VỤ: Giải thích hiện tượng khoa học CHI TIẾT và tạo mô phỏng SVG tương tác, animation mượt mà.

═══════════════════════════════
ĐỊNH DẠNG TRẢ VỀ (BẮT BUỘC):
═══════════════════════════════

<EXPLANATION>
Giải thích khoa học bằng Markdown tiếng Việt.
Dùng annotation marker [→ element-id] để tham chiếu phần tử SVG trên canvas.
Ví dụ: "Trái Đất [→ earth] quay quanh Mặt Trời [→ sun] theo quỹ đạo elip [→ orbit-path]."
</EXPLANATION>

<SVG>
<svg viewBox="0 0 800 600" xmlns="http://www.w3.org/2000/svg">
  <!-- Toàn bộ SVG code ở đây -->
</svg>
</SVG>

═══════════════════════════════
QUY TẮC SVG (QUAN TRỌNG):
═══════════════════════════════

1. LUÔN dùng <svg viewBox="0 0 800 600"> với xmlns="http://www.w3.org/2000/svg".
2. MỖI phần tử quan trọng PHẢI có thuộc tính id rõ ràng (VD: id="earth", id="sun", id="electron-1").
3. PHẢI dùng <defs> cho gradient, filter glow, pattern:
   - Filter glow: <filter id="glow"><feGaussianBlur stdDeviation="3" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
   - Gradient: <radialGradient>, <linearGradient>
4. Animation: Dùng <animate>, <animateTransform>, <animateMotion> của SVG SMIL hoặc CSS @keyframes bên trong <style>.
5. Background: Luôn có <rect> nền tối (VD: fill="#0a0e27") phủ toàn bộ viewBox.
6. Thẩm mỹ: Dùng màu sắc sinh động, glow, shadow, gradient. Mô phỏng phải ĐẸP MẮT.
7. Chi tiết vật lý: Kích thước, tốc độ, quỹ đạo phải phản ánh đúng nguyên lý khoa học.
8. KHÔNG dùng JavaScript bên trong SVG. Chỉ dùng SVG thuần + CSS animation.
9. SVG phải tự chạy animation ngay khi render, không cần tương tác.

═══════════════════════════════
QUY TẮC GIẢI THÍCH (QUAN TRỌNG):
═══════════════════════════════

1. Giải thích PHẢI tham chiếu canvas: dùng [→ id] để chỉ vào phần tử SVG cụ thể.
2. Mỗi đoạn giải thích nên liên kết ít nhất 1-2 phần tử SVG để người đọc biết đang nói về phần nào.
3. Dùng Markdown (## heading, **bold**, danh sách) để cấu trúc rõ ràng.
4. Viết chi tiết: công thức, số liệu, đơn vị vật lý nếu có.

═══════════════════════════════
VÍ DỤ MẪU CHO PROMPT "Mô phỏng nguyên tử Hydro":
═══════════════════════════════

<EXPLANATION>
## Mô hình nguyên tử Hydro

Nguyên tử Hydro là nguyên tử đơn giản nhất, gồm:

- **Hạt nhân (proton)** [→ nucleus]: Mang điện tích dương (+1e), nằm ở trung tâm. Khối lượng ≈ 1.67 × 10⁻²⁷ kg.
- **Electron** [→ electron]: Mang điện tích âm (-1e), quay quanh hạt nhân theo quỹ đạo [→ orbit]. Bán kính Bohr ≈ 0.529 Å.

Lực hút Coulomb giữ electron trên quỹ đạo: F = ke²/r²
</EXPLANATION>

<SVG>
<svg viewBox="0 0 800 600" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <radialGradient id="nucleus-grad" cx="50%" cy="50%">
      <stop offset="0%" stop-color="#ff6b6b"/>
      <stop offset="100%" stop-color="#c0392b"/>
    </radialGradient>
    <filter id="glow">
      <feGaussianBlur stdDeviation="4" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <style>
      @keyframes orbit-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
      .orbit-group { animation: orbit-spin 3s linear infinite; transform-origin: 400px 300px; }
    </style>
  </defs>
  <rect width="800" height="600" fill="#0a0e27"/>
  <circle id="orbit" cx="400" cy="300" r="120" fill="none" stroke="rgba(100,180,255,0.3)" stroke-width="1" stroke-dasharray="5,5"/>
  <circle id="nucleus" cx="400" cy="300" r="20" fill="url(#nucleus-grad)" filter="url(#glow)"/>
  <g class="orbit-group">
    <circle id="electron" cx="520" cy="300" r="8" fill="#4fc3f7" filter="url(#glow)"/>
  </g>
</svg>
</SVG>

TRÍ NHỚ: Luôn tham khảo mã SVG cũ (nếu được cung cấp) để sửa đổi/bổ sung theo ý người dùng thay vì tạo mới hoàn toàn.
"""


def _build_messages(user_prompt: str, history: list, last_svg: str):
    """Build the message list for the Groq API call."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Add conversation history (max 6 turns = 12 messages)
    for turn in (history or []):
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    
    # Build user message with optional previous SVG
    user_content = user_prompt
    if last_svg and last_svg.strip():
        user_content += "\n\n---\n[Mã SVG mô phỏng lần trước (tham khảo để sửa đổi/bổ sung):]:\n" + last_svg.strip()

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
        print(f"🚀 Stream SVG cho: {user_prompt[:50]}...")
        try:
            stream = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0.7,
                stream=True,
            )

            full_text = ""
            last_yielded_expl_idx = 0
            explanation_started = False
            explanation_ended = False

            for chunk in stream:
                if not chunk.choices or not chunk.choices[0].delta.content:
                    continue
                full_text += chunk.choices[0].delta.content

                # --- Stream EXPLANATION in real-time ---
                if not explanation_started and "<EXPLANATION>" in full_text:
                    explanation_started = True
                    last_yielded_expl_idx = full_text.find("<EXPLANATION>") + len("<EXPLANATION>")

                if explanation_started and not explanation_ended:
                    if "</EXPLANATION>" in full_text:
                        # Yield remaining explanation text before closing tag
                        end_idx = full_text.find("</EXPLANATION>")
                        if end_idx > last_yielded_expl_idx:
                            chunk_text = full_text[last_yielded_expl_idx:end_idx]
                            yield f"event: explanation\ndata: {json.dumps({'c': chunk_text})}\n\n"
                        last_yielded_expl_idx = len(full_text)
                        explanation_ended = True
                    else:
                        # Hold back 15 chars to avoid splitting </EXPLANATION> tag
                        safe_end = max(last_yielded_expl_idx, len(full_text) - 15)
                        if safe_end > last_yielded_expl_idx:
                            chunk_text = full_text[last_yielded_expl_idx:safe_end]
                            if chunk_text:
                                yield f"event: explanation\ndata: {json.dumps({'c': chunk_text})}\n\n"
                            last_yielded_expl_idx = safe_end

            # --- Extract SVG after stream completes ---
            svg_content = ""
            if "<SVG>" in full_text and "</SVG>" in full_text:
                start = full_text.find("<SVG>") + len("<SVG>")
                end = full_text.find("</SVG>")
                svg_content = full_text[start:end].strip()
            elif "<SVG>" in full_text:
                # Truncated - take what we have
                start = full_text.find("<SVG>") + len("<SVG>")
                svg_content = full_text[start:].strip()

            if svg_content:
                yield f"event: svg\ndata: {json.dumps({'c': svg_content})}\n\n"

        except Exception as e:
            traceback.print_exc()
            yield f"event: explanation\ndata: {json.dumps({'c': f'<br><br>**Lỗi kết nối Groq API:** {str(e)}'})}\n\n"

        yield f"event: done\ndata: {{}}\n\n"

    return Response(stream_with_context(generate_events()), content_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    print(f"🌟 SciCanvas SVG Edition – Khởi động (Model: {MODEL})")
    app.run(host="127.0.0.1", port=5000, debug=True)

