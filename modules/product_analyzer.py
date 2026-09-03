"""Product video analyzer: Gemini vision must name the actual product."""
import os, re, json, subprocess
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Dict, Any, List, Optional

SCRIPT_STYLES = [
    "ป้ายยา", "รีวิว", "แกะกล่อง", "เคล็ดลับ", "สอนวิธีใช้", "ข้อควรระวัง",
    "ปัญหา", "บอกโปร", "ให้ความรู้", "เรื่องเล่า", "สายฮา", "กำหนดเอง",
]

STYLE_DESCRIPTIONS = {
    "ป้ายยา": "ขายของแบบฮาร์ดเซลล์ ชื่อสินค้าชัด บอกจุดเด่น ราคา/โปร แล้วปิดด้วยตะกร้า",
    "รีวิว": "รีวิวสินค้าชิ้นนั้น เรียกชื่อแบรนด์/รุ่น บอกข้อดีข้อเสียสั้น ๆ",
    "แกะกล่อง": "เปิดกล่องสินค้าชิ้นนั้น เรียกชื่อขณะแกะ",
    "เคล็ดลับ": "ทิปการใช้สินค้าชิ้นนั้น",
    "สอนวิธีใช้": "สอนทีละขั้นกับสินค้าชิ้นนั้น",
    "ข้อควรระวัง": "เตือนวิธีใช้สินค้าชิ้นนั้น",
    "ปัญหา": "pain point แล้วเสนอสินค้าชิ้นนั้นเป็นคำตอบ",
    "บอกโปร": "เน้นโปร/ราคา ของสินค้าชิ้นนั้น",
    "ให้ความรู้": "ความรู้สั้น ๆ แล้วยกสินค้าชิ้นนั้นเป็นตัวอย่าง",
    "เรื่องเล่า": "เล่าเรื่องที่สินค้าชิ้นนั้นเป็นพระเอก",
    "สายฮา": "มุกสั้น แต่ยังต้องมีชื่อสินค้า",
    "กำหนดเอง": "โทนอิสระ แต่ต้องต้องมีชื่อสินค้า",
}

GENERIC_NAMES = {
    "", "สินค้า", "สินค้าแนะนำ", "สินค้าในคลิป", "ไอเทม", "ไอเทมเด็ด",
    "ไม่ระบุ", "unknown", "product", "this product", "สินค้าทั่วไป",
}


def extract_video_keyframes(video_path: str, output_dir: str, num_frames: int = 6) -> List[str]:
    os.makedirs(output_dir, exist_ok=True)
    cmd_dur = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", video_path]
    res_dur = subprocess.run(cmd_dur, capture_output=True, text=True)
    try:
        duration = float((res_dur.stdout or "").strip())
    except Exception:
        duration = 10.0
    duration = max(1.0, duration)
    frame_paths = []
    timestamps = [duration * (i + 0.15) / num_frames for i in range(num_frames)]
    for idx, ts in enumerate(timestamps):
        out_frame = os.path.join(output_dir, f"frame_{idx:02d}.jpg")
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{ts:.2f}", "-i", video_path, "-vframes", "1", "-q:v", "2", out_frame],
            capture_output=True,
        )
        if os.path.exists(out_frame) and os.path.getsize(out_frame) > 0:
            frame_paths.append(out_frame)
    return frame_paths


def _strip_fence(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"^```\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def _is_generic(name: str) -> bool:
    n = (name or "").strip().lower()
    return (not n) or n in {x.lower() for x in GENERIC_NAMES} or len(n) < 2


def _ensure_name_in_lines(name: str, lines: List[str], style: str) -> List[str]:
    name = (name or "").strip()
    clean = [l.strip() for l in lines if l and l.strip()]
    if not clean:
        clean = [
            f"หยุดเลื่อน! นี่คือ {name}",
            f"{name} ใช้แล้วรู้เลยว่าทำไมคนถึงพูดถึง",
            f"จุดเด่นของ {name} ตอบโจทย์การใช้จริง",
            f"อยากได้ {name} กดตะกร้าใต้คลิปเลย",
        ]
    if name and not any(name.lower() in l.lower() for l in clean):
        clean[0] = f"{name} — {clean[0]}"
        if len(clean) > 3:
            clean[-1] = f"จัดเลย {name} กดตะกร้าได้เลย"
    return clean[:6]


def analyze_with_gemini(frame_paths: List[str], script_style: str, duration: float, api_key: str) -> Dict[str, Any]:
    import google.generativeai as genai
    from PIL import Image

    genai.configure(api_key=api_key.strip())
    images = [Image.open(p) for p in frame_paths if os.path.exists(p)]
    if not images:
        raise ValueError("ตัดเฟรมจากคลิปไม่ได้")

    style_guide = STYLE_DESCRIPTIONS.get(script_style, STYLE_DESCRIPTIONS["ป้ายยา"])
    prompt = f"""You are a Thai TikTok Shop affiliate copywriter.
Look at these {len(images)} video frames. Identify the REAL product on screen.

HARD RULES:
- product_name MUST be the actual brand + model or common Thai product name visible or clearly implied (packaging, logo, on-screen text, distinctive object).
- NEVER use generic names like สินค้า, ไอเทมเด็ด, สินค้าแนะนำ, รีวิว.
- NEVER put the style name "{script_style}" as if it were the product.
- Every script_lines item MUST contain the product_name at least once.
- Thai spoken language, 3-5 short lines, total about {duration:.0f} seconds.
- Style: {script_style} — {style_guide}
- Line 1 = hook with product name. Last line = CTA (ตะกร้า / ลิงก์ใต้คลิป).

Return ONLY JSON:
{{
  "product_name": "ชื่อแบรนด์หรือรุ่นจริง",
  "product_summary": "สินค้านี้คืออะไร 1 ประโยค",
  "script_style": "{script_style}",
  "script_lines": ["...", "...", "...", "..."],
  "full_script": "รวมบรรทัด"
}}
"""

    last_err = None
    text = ""
    candidates = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-flash-latest",
        "gemini-2.0-flash-lite",
        "gemini-2.5-flash-lite",
    ]
    try:
        listed = []
        for m in genai.list_models():
            methods = getattr(m, "supported_generation_methods", None) or []
            name = getattr(m, "name", "") or ""
            short = name.split("/")[-1]
            if "generateContent" in methods and "flash" in short.lower() and "embed" not in short.lower():
                listed.append(short)
        if listed:
            # prefer flash, keep unique order listed then fallbacks
            seen = []
            for n in listed + candidates:
                if n not in seen:
                    seen.append(n)
            candidates = seen[:8]
    except Exception as e:
        last_err = e

    for model_name in candidates:
        try:
            model = genai.GenerativeModel(model_name)
            def _run(m=model):
                return m.generate_content([prompt, *images], request_options={"timeout": 25})
            with ThreadPoolExecutor(max_workers=1) as pool:
                response = pool.submit(_run).result(timeout=30)
            text = _strip_fence(getattr(response, "text", None) or "")
            if text:
                break
        except Exception as e:
            last_err = e
            continue
    if not text:
        raise RuntimeError(
            "เชื่อมต่อโมเดล Gemini ไม่ได้: {} — ใส่ชื่อสินค้าที่ช่องด้านล่างเพื่อข้าม หรือตรวจคีย์ที่ตั้งค่า".format(last_err)
        )

    try:
        parsed = json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise RuntimeError("Gemini ไม่ได้ส่ง JSON ชื่อสินค้า")
        parsed = json.loads(m.group(0))

    name = str(parsed.get("product_name") or "").strip()
    lines = parsed.get("script_lines") or []
    if isinstance(lines, str):
        lines = [x.strip() for x in re.split(r"[\n\r]+", lines) if x.strip()]
    if _is_generic(name):
        name = str(parsed.get("product_summary") or "").strip()[:40]
    if _is_generic(name):
        raise RuntimeError("Gemini หาชื่อสินค้าจากคลิปไม่เจอ")
    lines = _ensure_name_in_lines(name, list(lines), script_style)
    parsed["product_name"] = name
    parsed["script_style"] = script_style
    parsed["script_lines"] = lines
    parsed["full_script"] = "\n".join(lines)
    parsed["product_summary"] = parsed.get("product_summary") or name
    return parsed


def generate_product_script(
    video_path: Optional[str] = None,
    mode: str = "auto",
    script_style: str = "ป้ายยา",
    duration: float = 15.0,
    product_name: str = "",
    product_features: str = "",
    product_price: str = "",
    product_target: str = "",
    manual_script: str = "",
    gemini_api_key: str = "",
    openai_api_key: str = "",
    temp_dir: str = r"d:\KrillinAI\storage\temp",
) -> Dict[str, Any]:
    if mode == "manual" and manual_script.strip():
        lines = [l.strip() for l in re.split(r"[\n\r]+", manual_script.strip()) if l.strip()]
        return {
            "mode": "manual",
            "product_name": product_name or "สคริปต์ที่เขียนเอง",
            "script_style": script_style,
            "script_lines": lines,
            "full_script": "\n".join(lines),
        }

    if mode == "product_info" or product_name.strip():
        name = product_name.strip()
        if _is_generic(name):
            raise ValueError("ใส่ชื่อสินค้าก่อน เช่น ชื่อแบรนด์หรือรุ่น")
        feats = product_features.strip() or "ใช้ดี จุดเด่นชัด"
        deal = product_price.strip() or "ดูราคาที่ตะกร้า"
        lines = [
            f"หยุดเลื่อน! นี่ {name} ที่คนพูดถึงทั้งฟีด",
            f"{name} เด่นตรง {feats}",
            f"ใครกำลังหาของแนวนี้ {name} ตอบโจทย์กว่าที่คิด",
            f"{deal} — จัด {name} กดตะกร้าใต้คลิปเลย",
        ]
        if script_style == "แกะกล่อง":
            lines[1] = f"แกะกล่อง {name} มาดูกันว่าข้างในมีอะไร"
        if script_style == "บอกโปร":
            lines[2] = f"โปรนี้ของ {name}: {deal}"
        return {
            "mode": "product_info",
            "product_name": name,
            "script_style": script_style,
            "script_lines": lines,
            "full_script": "\n".join(lines),
        }

    if video_path and os.path.exists(video_path) and gemini_api_key.strip():
        frames_dir = os.path.join(temp_dir, "product_frames")
        frames = extract_video_keyframes(video_path, frames_dir, num_frames=6)
        result = analyze_with_gemini(frames, script_style, duration, gemini_api_key)
        extra = product_name.strip()
        if extra and _is_generic(result.get("product_name", "")):
            result["product_name"] = extra
            result["script_lines"] = _ensure_name_in_lines(extra, result.get("script_lines") or [], script_style)
            result["full_script"] = "\n".join(result["script_lines"])
        result["mode"] = "auto"
        return result

    raise ValueError(
        "วิเคราะห์คลิปไม่ได้ จึงยังไม่มีชื่อสินค้า — ใส่คีย์ Gemini ที่ตั้งค่า หรือไปแท็บข้อมูลสินค้าแล้วกรอกชื่อแบรนด์/รุ่น"
    )
