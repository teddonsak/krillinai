"""
OpenShorts Subtitle Generator
Generates TikTok / Shorts / Reels style animated karaoke ASS subtitles.
Ported and enhanced from mutonby/openshorts with Thai word segmentation support (PyThaiNLP).
"""

import os
import re
from typing import List, Dict, Any, Optional

try:
    from pythainlp.tokenize import word_tokenize
    HAS_PYTHAINLP = True
except ImportError:
    HAS_PYTHAINLP = False

# Safe margin for vertical short-form platforms (TikTok, Reels, Shorts UI)
# in PlayResY=288 units (~15% of frame height)
SAFE_MARGIN_V = 43

DEFAULT_STYLE = {
    "font_name": "Prompt",
    "font_size": 42,
    "font_color": "#FFFFFF",
    "highlight_color": "#FFE500",
    "border_color": "#000000",
    "border_width": 4,
    "effect": "pop",           # 'pop', 'glow', 'box', 'none'
    "alignment": "bottom",     # 'top', 'middle', 'bottom'
    "margin_v": SAFE_MARGIN_V,
    "max_chars": 24,
    "max_duration": 2.2,
    "uppercase": False,
    "base_opacity": 0.85
}

# 18 Popular Presets from user's AI SETTINGS
SUBTITLE_PRESETS = {
    "มาตรฐาน": {"font_name": "Prompt", "font_color": "#FFFFFF", "highlight_color": "#FFE500", "border_color": "#000000", "border_width": 4, "effect": "pop"},
    "มินิมอล": {"font_name": "Prompt", "font_color": "#FFFFFF", "highlight_color": "#FFFFFF", "border_color": "#000000", "border_width": 2, "effect": "none"},
    "ตัวหนาเด่น": {"font_name": "Prompt", "font_color": "#FFE500", "highlight_color": "#FFFFFF", "border_color": "#000000", "border_width": 5, "effect": "pop"},
    "นีออนเขียว": {"font_name": "Prompt", "font_color": "#00FF66", "highlight_color": "#CCFF00", "border_color": "#003311", "border_width": 4, "effect": "glow"},
    "คาราโอเกะ": {"font_name": "Prompt", "font_color": "#FFFFFF", "highlight_color": "#FFE500", "border_color": "#000000", "border_width": 4, "effect": "pop"},
    "ป๊อปไลน์": {"font_name": "Prompt", "font_color": "#FFFFFF", "highlight_color": "#00FFFF", "border_color": "#000000", "border_width": 4, "effect": "pop"},
    "พาสเทล": {"font_name": "Prompt", "font_color": "#FFB6C1", "highlight_color": "#FFF0F5", "border_color": "#4A0033", "border_width": 4, "effect": "pop"},
    "คลาสสิก": {"font_name": "Prompt", "font_color": "#FFFFFF", "highlight_color": "#FFE500", "border_color": "#000000", "border_width": 3, "effect": "none"},
    "Hormozi": {"font_name": "Anton", "font_color": "#FFFFFF", "highlight_color": "#00FF66", "border_color": "#000000", "border_width": 6, "effect": "pop", "uppercase": True},
    "Beast": {"font_name": "Kanit", "font_color": "#FFFFFF", "highlight_color": "#FF3300", "border_color": "#000000", "border_width": 5, "effect": "pop"},
    "กล่องขาว": {"font_name": "Prompt", "font_color": "#000000", "highlight_color": "#000000", "border_color": "#FFFFFF", "border_width": 4, "effect": "box"},
    "กล่องเหลือง": {"font_name": "Prompt", "font_color": "#000000", "highlight_color": "#000000", "border_color": "#FFE500", "border_width": 4, "effect": "box"},
    "เรโทร": {"font_name": "Prompt", "font_color": "#FFCC00", "highlight_color": "#FF3366", "border_color": "#330033", "border_width": 4, "effect": "pop"},
    "เส้นขอบชัด": {"font_name": "Prompt", "font_color": "#FFFFFF", "highlight_color": "#FFE500", "border_color": "#000000", "border_width": 6, "effect": "pop"},
    "ลายมือ": {"font_name": "Kanit", "font_color": "#FFFFFF", "highlight_color": "#FFE500", "border_color": "#000000", "border_width": 3, "effect": "pop"},
    "ข่าว": {"font_name": "Prompt", "font_color": "#FFFFFF", "highlight_color": "#FFCC00", "border_color": "#001133", "border_width": 4, "effect": "none"},
    "ไฟแดง": {"font_name": "Prompt", "font_color": "#FF3333", "highlight_color": "#FFAA00", "border_color": "#330000", "border_width": 4, "effect": "glow"},
    "ไฟฟ้า": {"font_name": "Prompt", "font_color": "#00CCFF", "highlight_color": "#FFFFFF", "border_color": "#002244", "border_width": 4, "effect": "glow"}
}

_HEX_COLOR_RE = re.compile(r'^[0-9A-Fa-f]{6}$')


def _ass_time(seconds: float) -> str:
    """Format seconds into ASS timestamp H:MM:SS.cc"""
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis >= 100:
        centis = 99
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def hex_to_ass_color(hex_color: str, alpha: float = 1.0, fallback: str = "FFFFFF") -> str:
    """Convert #RRGGBB and alpha (0.0=opaque, 1.0=transparent) to ASS &HAABBGGRR&"""
    hex_digits = str(hex_color or "").lstrip('#')
    if not _HEX_COLOR_RE.match(hex_digits):
        hex_digits = fallback
    r = hex_digits[0:2]
    g = hex_digits[2:4]
    b = hex_digits[4:6]
    # In ASS, 00 is fully opaque, FF is fully transparent
    a_val = int(round((1.0 - max(0.0, min(1.0, alpha))) * 255))
    return f"&H{a_val:02X}{b}{g}{r}&".upper()


def hex_to_ass_inline_color(hex_color: str, fallback: str = "FFFFFF") -> str:
    """Convert #RRGGBB to inline \\c override &HBBGGRR&"""
    hex_digits = str(hex_color or "").lstrip('#')
    if not _HEX_COLOR_RE.match(hex_digits):
        hex_digits = fallback
    r = hex_digits[0:2]
    g = hex_digits[2:4]
    b = hex_digits[4:6]
    return f"&H{b}{g}{r}&".upper()


def _dim_hex_color(hex_color: str, opacity: float, fallback: str = "FFFFFF") -> str:
    """Fully opaque dimmed RGB color for crisp subtitle background text."""
    hex_digits = str(hex_color or "").lstrip('#')
    if not _HEX_COLOR_RE.match(hex_digits):
        hex_digits = fallback
    factor = 0.45 + 0.55 * max(0.05, min(1.0, opacity))
    r = min(255, round(int(hex_digits[0:2], 16) * factor))
    g = min(255, round(int(hex_digits[2:4], 16) * factor))
    b = min(255, round(int(hex_digits[4:6], 16) * factor))
    return f"{r:02X}{g:02X}{b:02X}"


def _escape_ass_text(text: str) -> str:
    return str(text).replace('\\', '/').replace('{', '(').replace('}', ')')


def tokenize_thai_sentence_into_words(sentence: str, start_time: float, end_time: float) -> List[Dict[str, Any]]:
    """Tokenize Thai sentence into words with interpolated timestamps."""
    if not sentence.strip():
        return []
    if HAS_PYTHAINLP:
        tokens = [t for t in word_tokenize(sentence, engine="newmm") if t.strip()]
    else:
        tokens = [t for t in sentence.split() if t.strip()]

    if not tokens:
        tokens = [sentence]

    total_len = sum(len(t) for t in tokens)
    duration = max(0.2, end_time - start_time)
    words = []
    curr_time = start_time
    for token in tokens:
        w_dur = (len(token) / max(1, total_len)) * duration
        words.append({
            "word": token,
            "start": round(curr_time, 2),
            "end": round(curr_time + w_dur, 2)
        })
        curr_time += w_dur
    return words


def build_word_blocks(segments: List[Dict[str, Any]], max_chars: int = 24, max_duration: float = 2.2) -> List[List[Dict[str, Any]]]:
    """Group words into short, rhythmic chunks suitable for vertical video."""
    all_words = []
    for seg in segments:
        words = seg.get("words", [])
        if not words:
            # Generate word timestamps from segment text
            text = seg.get("text", "")
            words = tokenize_thai_sentence_into_words(text, seg.get("start", 0.0), seg.get("end", 0.0))
        for w in words:
            word_str = str(w.get("word", "")).strip()
            if not word_str:
                continue
            all_words.append({
                "word": word_str,
                "start": float(w.get("start", 0.0)),
                "end": float(w.get("end", 0.0))
            })

    blocks = []
    current_block = []
    block_start = 0.0

    for w in all_words:
        if not current_block:
            current_block = [w]
            block_start = w["start"]
            continue

        curr_text_len = sum(len(x["word"]) for x in current_block) + len(current_block)
        curr_dur = w["end"] - block_start

        if curr_text_len + len(w["word"]) > max_chars or curr_dur > max_duration:
            blocks.append(current_block)
            current_block = [w]
            block_start = w["start"]
        else:
            current_block.append(w)

    if current_block:
        blocks.append(current_block)

    return blocks


def generate_openshorts_ass(
    segments: List[Dict[str, Any]],
    output_path: str,
    font_name: str = "Prompt",
    font_size: int = 44,
    font_color: str = "#FFFFFF",
    highlight_color: str = "#FFE500",
    border_color: str = "#000000",
    border_width: int = 4,
    effect: str = "pop",
    alignment: str = "bottom",
    margin_v: int = SAFE_MARGIN_V,
    max_chars: int = 22,
    max_duration: float = 2.0,
    base_opacity: float = 0.85,
    uppercase: bool = False
) -> bool:
    """
    Generate OpenShorts style animated karaoke ASS file.
    """
    blocks = build_word_blocks(segments, max_chars=max_chars, max_duration=max_duration)
    if not blocks:
        return False

    align_map = {"top": 8, "middle": 5, "bottom": 2}
    ass_alignment = align_map.get(str(alignment).lower(), 2)

    # Calculate font size in PlayResY=288 reference coordinates
    ref_fontsize = max(11, int(font_size * 0.40))
    outline_width = max(1, int(border_width * 0.40))

    primary_color_ass = hex_to_ass_color(_dim_hex_color(font_color, base_opacity), 1.0)
    outline_color_ass = hex_to_ass_color(border_color, 1.0)
    back_color_ass = hex_to_ass_color("#000000", 0.0)
    highlight_inline = hex_to_ass_inline_color(highlight_color, fallback="FFE500")

    # Animation effect override tags
    if effect == "pop":
        active_prefix = f"{{\\c{highlight_inline}\\fscx95\\fscy95\\t(0,100,\\fscx112\\fscy112)}}"
    elif effect == "glow":
        glow_bord = outline_width + 2
        active_prefix = f"{{\\c&HFFFFFF&\\3c{highlight_inline}\\bord{glow_bord}\\blur3}}"
    elif effect == "box":
        box_bord = outline_width + 3
        active_prefix = f"{{\\c&HFFFFFF&\\3c{highlight_inline}\\bord{box_bord}}}"
    else:
        active_prefix = f"{{\\c{highlight_inline}}}"

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 384\n"
        "PlayResY: 288\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: OpenShorts,{font_name},{ref_fontsize},{primary_color_ass},{primary_color_ass},"
        f"{outline_color_ass},{back_color_ass},1,0,0,0,100,100,0,0,1,{outline_width},0,"
        f"{ass_alignment},12,12,{margin_v},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    events = []
    for block in blocks:
        for i, word in enumerate(block):
            ev_start = block[0]["start"] if i == 0 else word["start"]
            ev_end = block[i + 1]["start"] if i < len(block) - 1 else block[-1]["end"]
            if ev_end <= ev_start:
                continue

            parts = []
            for j, other in enumerate(block):
                w_text = _escape_ass_text(other["word"])
                if uppercase:
                    w_text = w_text.upper()
                if j == i:
                    parts.append(f"{active_prefix}{w_text}{{\\r}}")
                else:
                    parts.append(w_text)

            dialogue_line = (
                f"Dialogue: 0,{_ass_time(ev_start)},{_ass_time(ev_end)},OpenShorts,,0,0,0,,"
                f"{' '.join(parts)}"
            )
            events.append(dialogue_line)

    if not events:
        return False

    with open(output_path, "w", encoding="utf-8-sig") as f:
        f.write(header + "\n".join(events) + "\n")

    return True


def generate_standard_srt(segments: List[Dict[str, Any]], output_path: str) -> bool:
    """Generate clean UTF-8 SRT subtitle file."""
    lines = []
    for idx, seg in enumerate(segments, 1):
        start = seg.get("start", 0.0)
        end = seg.get("end", 0.0)
        text = str(seg.get("text", "")).strip()
        if not text:
            continue

        def fmt(secs):
            hrs = int(secs // 3600)
            mins = int((secs % 3600) // 60)
            s = int(secs % 60)
            ms = int((secs - int(secs)) * 1000)
            return f"{hrs:02d}:{mins:02d}:{s:02d},{ms:03d}"

        lines.append(f"{idx}\n{fmt(start)} --> {fmt(end)}\n{text}\n\n")

    if not lines:
        return False

    with open(output_path, "w", encoding="utf-8-sig") as f:
        f.write("".join(lines))
    return True
