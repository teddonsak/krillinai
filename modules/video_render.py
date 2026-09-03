"""
Video Rendering & Layout Engine
Reframes video to 9:16 vertical (YouTube Shorts / TikTok / Douyin)
Embeds OpenShorts-style animated karaoke ASS subtitles
Mixes dubbed TTS audio with smart audio ducking
"""

import os
import re
import json
import subprocess
from typing import Dict, Any, Optional, Tuple


def probe_video_info(video_path: str) -> Dict[str, Any]:
    """Get video width, height, duration, and fps using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        video_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {res.stderr}")

    data = json.loads(res.stdout)
    video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)

    width = int(video_stream.get("width", 1920)) if video_stream else 1920
    height = int(video_stream.get("height", 1080)) if video_stream else 1080

    # Parse duration
    dur_str = data.get("format", {}).get("duration") or (video_stream.get("duration") if video_stream else "0")
    duration = float(dur_str or 0.0)

    # Parse fps
    fps_str = video_stream.get("r_frame_rate", "30/1") if video_stream else "30/1"
    if "/" in fps_str:
        num, den = fps_str.split("/")
        fps = round(float(num) / float(den), 2) if float(den) > 0 else 30.0
    else:
        fps = float(fps_str or 30.0)

    return {
        "width": width,
        "height": height,
        "duration": duration,
        "fps": fps,
        "has_audio": audio_stream is not None,
        "is_vertical": height > width
    }


def escape_ffmpeg_filter_path(path: str) -> str:
    """Safely escape path for FFmpeg filter arguments on Windows."""
    p = os.path.abspath(path).replace('\\', '/')
    return p.replace(':', '\\:').replace("'", "\\'")


def render_short_video(
    input_video: str,
    output_video: str,
    layout_mode: str = "blur_9_16",   # 'blur_9_16', 'crop_9_16', 'krillin_title', 'original'
    ass_subtitle_path: Optional[str] = None,
    dubbed_audio_path: Optional[str] = None,
    original_audio_volume: float = 0.15,  # Background ducking volume (0.15 = 15%)
    major_title: str = "",
    minor_title: str = "",
    target_width: int = 1080,
    target_height: int = 1920,
    aspect_ratio: str = "9:16"
) -> bool:
    """
    Complete render pipeline:
    1. Video reframing (9:16, 1:1, 16:9, 4:5 with Blur background, Center crop, or Krillin banner)
    2. Burns OpenShorts animated karaoke ASS subtitles
    3. Mixes dubbed audio with original audio ducking
    """
    aspect_map = {
        "9:16": (1080, 1920),
        "1:1": (1080, 1080),
        "16:9": (1920, 1080),
        "4:5": (1080, 1350)
    }
    if aspect_ratio in aspect_map:
        target_width, target_height = aspect_map[aspect_ratio]

    os.makedirs(os.path.dirname(os.path.abspath(output_video)), exist_ok=True)
    info = probe_video_info(input_video)
    orig_w, orig_h = info["width"], info["height"]

    inputs = ["-i", input_video]
    filter_chains = []

    # 1. Video Reframing Filter
    if layout_mode == "blur_9_16" and orig_w >= orig_h:
        # Blurred background (scale + crop + blur) + foreground sharp in center
        vfilter = (
            f"[0:v]split=2[bg_in][fg_in];"
            f"[bg_in]scale={target_width}:{target_height}:force_original_aspect_ratio=increase,"
            f"crop={target_width}:{target_height},"
            f"boxblur=luma_radius=min(h\\,w)/18:luma_power=2[bg];"
            f"[fg_in]scale={target_width}:-2:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[vbase]"
        )
        curr_v = "[vbase]"
        filter_chains.append(vfilter)

    elif layout_mode == "crop_9_16":
        # Direct center crop to 9:16
        crop_w = int(orig_h * 9 / 16)
        if crop_w > orig_w:
            crop_w = orig_w
        crop_x = (orig_w - crop_w) // 2
        vfilter = f"[0:v]crop={crop_w}:{orig_h}:{crop_x}:0,scale={target_width}:{target_height}[vbase]"
        curr_v = "[vbase]"
        filter_chains.append(vfilter)

    elif layout_mode == "krillin_title":
        # KrillinAI banner style (720x1280 or 1080x1920 with top black title banner)
        pad_top = int(target_height * 0.18)
        font_path = "C:/Windows/Fonts/tahoma.ttf" if os.path.exists("C:/Windows/Fonts/tahoma.ttf") else "Arial"
        font_escaped = escape_ffmpeg_filter_path(font_path)

        draw_title = ""
        if major_title:
            draw_title += (
                f",drawtext=text='{major_title}':fontfile='{font_escaped}':fontsize=48:"
                f"fontcolor=yellow:x=(w-text_w)/2:y={int(pad_top * 0.35)}:box=0"
            )
        if minor_title:
            draw_title += (
                f",drawtext=text='{minor_title}':fontfile='{font_escaped}':fontsize=32:"
                f"fontcolor=white:x=(w-text_w)/2:y={int(pad_top * 0.70)}:box=0"
            )

        vfilter = (
            f"[0:v]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
            f"pad={target_width}:{target_height}:(ow-iw)/2:{pad_top}:black"
            f"{draw_title}[vbase]"
        )
        curr_v = "[vbase]"
        filter_chains.append(vfilter)

    else:
        # Original layout
        curr_v = "[0:v]"

    # 2. Burn ASS Subtitles
    if ass_subtitle_path and os.path.exists(ass_subtitle_path):
        ass_escaped = escape_ffmpeg_filter_path(ass_subtitle_path)
        sub_filter = f"{curr_v}ass=filename='{ass_escaped}'[vsub]"
        filter_chains.append(sub_filter)
        curr_v = "[vsub]"

    # 3. Audio Mixing & Ducking
    has_orig_audio = info["has_audio"]
    has_dub_audio = dubbed_audio_path and os.path.exists(dubbed_audio_path)

    if has_dub_audio:
        inputs.extend(["-i", dubbed_audio_path])
        if has_orig_audio:
            # Duck original audio and mix with dubbed audio
            filter_chains.append(
                f"[0:a]volume={original_audio_volume}[a_orig];"
                f"[1:a]volume=1.0[a_dub];"
                f"[a_orig][a_dub]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            )
            audio_map = ["[aout]"]
        else:
            audio_map = ["1:a"]
    elif has_orig_audio:
        audio_map = ["0:a"]
    else:
        audio_map = []

    # Assemble complete command
    full_filter_str = ";".join(filter_chains)
    cmd = ["ffmpeg", "-y", *inputs]

    if full_filter_str:
        cmd.extend(["-filter_complex", full_filter_str])
        cmd.extend(["-map", curr_v])
    else:
        cmd.extend(["-map", "0:v"])

    if audio_map:
        cmd.extend(["-map", audio_map[0]])

    cmd.extend([
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        output_video
    ])

    print(f"[Render] Running FFmpeg command: {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg render error: {res.stderr}")

    return os.path.exists(output_video) and os.path.getsize(output_video) > 0
