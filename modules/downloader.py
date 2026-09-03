"""
Video Downloader Module using yt-dlp
Supports downloading from YouTube, TikTok, Douyin, Bilibili, Facebook, Instagram, X/Twitter, etc.
"""

import os
import re
import subprocess
import json
from typing import Dict, Any, Optional


def sanitize_filename(name: str) -> str:
    """Sanitize string to be safe for filenames."""
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name.strip()[:100] or "video"


def download_video_from_url(url: str, output_dir: str) -> Dict[str, Any]:
    """
    Downloads video from URL using yt-dlp to output_dir.
    Returns metadata dict with title, duration, filepath, thumbnail.
    """
    os.makedirs(output_dir, exist_ok=True)

    # 1. Fetch info first
    info_cmd = [
        "yt-dlp",
        "--dump-json",
        "--no-playlist",
        url
    ]
    info_res = subprocess.run(info_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if info_res.returncode != 0:
        raise RuntimeError(f"ไม่สามารถอ่านข้อมูลวิดีโอจากลิงก์ได้: {info_res.stderr[:300]}")

    info_data = json.loads(info_res.stdout)
    title = info_data.get("title", "video")
    clean_title = sanitize_filename(title)
    duration = float(info_data.get("duration") or 0.0)
    thumbnail = info_data.get("thumbnail", "")

    # 2. Download video
    out_template = os.path.join(output_dir, f"{clean_title}_%(id)s.%(ext)s")
    dl_cmd = [
        "yt-dlp",
        "-f", "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "-o", out_template,
        url
    ]

    dl_res = subprocess.run(dl_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if dl_res.returncode != 0:
        raise RuntimeError(f"ดาวน์โหลดวิดีโอล้มเหลว: {dl_res.stderr[:300]}")

    # Find the downloaded file
    downloaded_files = [
        os.path.join(output_dir, f)
        for f in os.listdir(output_dir)
        if f.startswith(clean_title) and f.endswith(".mp4")
    ]

    if not downloaded_files:
        # Check any newly created mp4 in output_dir
        all_mp4s = [
            os.path.join(output_dir, f)
            for f in os.listdir(output_dir)
            if f.endswith(".mp4")
        ]
        if all_mp4s:
            downloaded_files = sorted(all_mp4s, key=os.path.getmtime, reverse=True)

    if not downloaded_files:
        raise RuntimeError("ไม่พบไฟล์วิดีโอที่ดาวน์โหลดเสร็จสมบูรณ์")

    final_filepath = downloaded_files[0]

    return {
        "title": title,
        "clean_title": clean_title,
        "duration": duration,
        "thumbnail": thumbnail,
        "filepath": final_filepath
    }
