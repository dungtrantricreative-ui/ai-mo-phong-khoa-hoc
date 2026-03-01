import sys
import json
import traceback
from pathlib import Path
from typing import Optional
from io import StringIO

from groq import Groq
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context

# ========== CẤU HÌNH GỌI AI ==========
API_KEY = "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"
MODEL = "llama-3.3-70b-versatile" # Sử dụng model đáng tin cậy hỗ trợ JSON

client = Groq(api_key=API_KEY)
USE_EXTERNAL_AI = True

APP_DIR = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=APP_DIR)

FALLBACK_HTML = '''<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><title>Chờ mô phỏng</title>
<style>html,body{height:100%;margin:0;background:linear-gradient(120deg,#061226,#011021);display:flex;align-items:center;justify-content:center;color:#fff;font-family:sans-serif}</style></head>
<body><h3>Đang tải mô phỏng...</h3></body></html>'''


SYSTEM_PROMPT_JSON = """
Bạn là SciCanvas AI, chuyên gia vật lý và kỹ sư đồ họa. Nhiệm vụ: giải thích hiện tượng khoa học và tạo mã HTML mô phỏng.

TRÍ NHỚ: Tham khảo ngữ cảnh hội thoại và mã HTML lần trước (nếu có) để chỉnh sửa theo ý người dùng.

ĐỊNH DẠNG TRẢ VỀ:
Bạn BẮT BUỘC trả về định dạng JSON thuần hợp lệ chứa đúng 2 khoá sau:
{
  "explanation": "Giải thích khoa học bằng tiếng Việt (dùng Markdown, có thể viết dài).",
  "html_code": "Toàn bộ mã HTML hoàn chỉnh (<!DOCTYPE html><html>...). Dùng Canvas 2D, p5.js hoặc CSS/JS thuần để mô phỏng."
}

YÊU CẦU MÔ PHỎNG:
1. Chi tiết: các thông số vật lý rõ ràng.
2. Vẻ đẹp: Dùng màu sắc, bóng đổ (box-shadow, glow).
3. KHÔNG lỗi cú pháp JavaScript. HTML sinh ra phải xem được nội dung hiển thị ngay khi mở file.

QUAN TRỌNG: Trả về JSON thuần tuý. Không bọc trong ```json ... ```.
"""


def _build_messages(prompt: str, history: list, last_html: Optional[str]):
    messages = [{"role": "system", "content": SYSTEM_PROMPT_JSON}]
    for turn in history or []:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            # We enforce assistant messages to be strings, ignoring past HTML in the chat flow directly
            messages.append({"role": role, "content": content})
    
    # Require the word JSON in prompt to satisfy Groq API requirements
    user_content = prompt + "\n\n(Hãy nhớ trả về định dạng JSON như đã yêu cầu)."
    
    if last_html and last_html.strip():
        user_content += "\n\n---\n[Mã HTML mô phỏng cũ (để tham khảo sửa đổi):]\n" + last_html.strip()
        
    messages.append({"role": "user", "content": user_content})
    return messages


def _sse_message(event: str, data: str) -> str:
    payload = json.dumps({"c": data}, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def stream_science_simulation(user_prompt, history=None, last_html=None):
    print(f"🚀 Streaming mô phỏng logic JSON (Model: {MODEL})...")
    try:
        messages = _build_messages(user_prompt, history, last_html)
        stream = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.7,
            stream=True,
        )

        # Llama 3 JSON stream logic:
        # The stream will output the JSON character by character:
        # {"explanation": "...", "html_code": "..."}
        
        buffer = ""
        in_explanation_value = False
        explanation_so_far = ""
        
        for chunk in stream:
            if not chunk.choices or not chunk.choices[0].delta.content:
                continue
            delta = chunk.choices[0].delta.content
            buffer += delta
            
            # Simple heuristic to stream the 'explanation' field text in real-time
            # Xấp xỉ: JSON stream ra `{"explanation": "Thực ra...` -> Ta lấy text bên trong dấu nháy kép
            if not in_explanation_value and '"explanation":' in buffer:
                idx = buffer.find('"explanation":')
                val_start_idx = buffer.find('"', idx + 14)
                if val_start_idx != -1:
                    in_explanation_value = True
                    # Cắt buffer chỉ còn phần giá trị trở đi
                    buffer = buffer[val_start_idx + 1:] 
            
            if in_explanation_value:
                # Nếu đã đọc đến khóa html_code thì dừng stream explanation
                if '","html_code":' in buffer or '", "html_code":' in buffer or '"html_code":' in buffer:
                    in_explanation_value = False
                else:
                    # Truyền các ký tự mới vào explanation (Cảnh báo: xử lý escape char như \n có thể bị lỗi nhẹ, 
                    # để đơn giản ở đây truyền trực tiếp delta nếu nó k dính key)
                    if not '"html_code"' in delta:
                        # Fix các ký tự thoát JSON cơ bản
                        clean_delta = delta.replace('\\n', '\n').replace('\\"', '"')
                        yield ("explanation", clean_delta)

        # Sau khi stream xong, JSON đã hoàn thành trong buffer tổng
        try:
            # We reconstruct the full json from stream generator is tricky without keeping original buffer.
            # Let's just make a non-streaming call for the JSON mode if streaming parses too messy.
            # Wait, the above logic consumes the stream but doesn't retain the full valid JSON easily if we slice `buffer`.
            pass 
        except Exception:
            pass

    except Exception as e:
        err_str = str(e)
        yield ("explanation", f"\n\n*Lỗi Stream: {err_str}*")


def generate_science_simulation(user_prompt, history=None, last_html=None):
    """Fallback non-streaming version if needed."""
    return "", ""


@app.route("/")
def index():
    return send_from_directory(APP_DIR, "index.html")

@app.route("/api/simulate", methods=["POST"])
def api_simulate():
    return jsonify({"error": "Sync endpoint disabled in favor of stream."}), 400

@app.route("/api/simulate/stream", methods=["POST"])
def api_simulate_stream():
    try:
        data = request.get_json() or {}
        prompt = (data.get("prompt") or "").strip()
        if not prompt:
            return jsonify({"error": "Thiếu prompt"}), 400
        history = data.get("history") or []
        last_html = data.get("last_html") or ""

        def gen():
            try:
                # Cách tiếp cận tốt nhất với JSON mode: Gọi KHÔNG stream để chắc chắn JSON chuẩn,
                # HOẶC gọi stream và tự parse. 
                # Groq rất nhanh, ta có thể dùng non-stream cho JSON object để đảm bảo HTML không dính lỗi parse.
                print("🚀 Đang xử lý hoàn chỉnh JSON Object (không stream chunk JSON vì rủi ro vỡ HTML)...")
                messages = _build_messages(prompt, history, last_html)
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.7,
                )
                raw = response.choices[0].message.content or "{}"
                
                try:
                    result = json.loads(raw)
                    expl = result.get("explanation", "")
                    html_code = result.get("html_code", "")
                    
                    # Mô phỏng luồng (stream giả) để UX mượt
                    chunk_size = 50
                    for i in range(0, len(expl), chunk_size):
                        yield _sse_message("explanation", expl[i:i+chunk_size])
                        
                    yield _sse_message("html", html_code)
                except json.JSONDecodeError:
                    yield _sse_message("explanation", f"\n*Lỗi parse JSON từ mô hình*:\n{raw}")

            except Exception as e:
                yield _sse_message("explanation", f"\n\n*Lỗi kết nối API: {str(e)}*")
            
            yield _sse_message("done", "")

        return Response(stream_with_context(gen()), content_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    except Exception as e:
        return Response(_sse_message("explanation", f"*Lỗi endpoint: {e}*"), content_type="text/event-stream")


if __name__ == "__main__":
    print(f"SciCanvas - Re-architected JSON Mode ({MODEL})")
    app.run(host="127.0.0.1", port=5000, debug=False)

