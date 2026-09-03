"""
KrillinAI + OpenShorts Unified Server (Thai Edition)
Backend API Server built with FastAPI
"""

import os
import sys
import uuid
import json
import time
import shutil
import asyncio
import re
import subprocess
from typing import Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Configure stdout/stderr for UTF-8 on Windows
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# Add current dir to python path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from modules.downloader import download_video_from_url
from modules.transcribe_translate import transcribe_video, translate_segments_with_llm, extract_audio, tokenize_words_with_timing
from modules.tts_engine import synthesize_speech, generate_dubbed_audio_track, EDGE_VOICES, ELEVENLABS_TONE_PRESETS, MINIMAX_EMOTIONS
from modules.openshorts_subtitles import generate_openshorts_ass, generate_standard_srt, SAFE_MARGIN_V, SUBTITLE_PRESETS
from modules.video_render import render_short_video, probe_video_info
from modules.product_analyzer import generate_product_script, SCRIPT_STYLES, STYLE_DESCRIPTIONS
from modules.voice_catalog import fetch_elevenlabs_voices, fetch_minimax_voices

# Paths
UPLOAD_DIR = os.path.join(BASE_DIR, "storage", "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "storage", "outputs")
TEMP_DIR = os.path.join(BASE_DIR, "storage", "temp")
WEB_DIR = os.path.join(BASE_DIR, "web")

for d in (UPLOAD_DIR, OUTPUT_DIR, TEMP_DIR, WEB_DIR):
    os.makedirs(d, exist_ok=True)

app = FastAPI(title="KrillinAI + OpenShorts Thai Studio", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global task tracker
tasks_db: Dict[str, Dict[str, Any]] = {}
executor = ThreadPoolExecutor(max_workers=3)


def update_task_progress(task_id: str, step: str, progress: int, message: str, data: Optional[Dict[str, Any]] = None):
    if task_id in tasks_db:
        tasks_db[task_id]["step"] = step
        tasks_db[task_id]["progress"] = progress
        tasks_db[task_id]["message"] = message
        tasks_db[task_id]["logs"].append(f"[{time.strftime('%H:%M:%S')}] {message}")
        if data:
            tasks_db[task_id]["data"].update(data)


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = os.path.join(WEB_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>KrillinAI + OpenShorts Thai Studio Running</h1>"


# Mount storage directory for static video/audio streaming
app.mount("/storage", StaticFiles(directory=os.path.join(BASE_DIR, "storage")), name="storage")


@app.get("/api/config-presets")
async def get_config_presets():
    """Returns available presets for voices, tones, emotions, and subtitle styles."""
    return {
        "edge_voices": EDGE_VOICES,
        "elevenlabs_tones": ELEVENLABS_TONE_PRESETS,
        "minimax_emotions": MINIMAX_EMOTIONS,
        "default_safe_margin": SAFE_MARGIN_V
    }



@app.post("/api/voices")
async def list_voices(payload: Dict[str, Any]):
    provider = (payload.get("provider") or "").strip().lower()
    api_key = payload.get("api_key") or ""
    group_id = payload.get("group_id") or ""
    if provider == "elevenlabs":
        return await fetch_elevenlabs_voices(api_key)
    if provider == "minimax":
        return await fetch_minimax_voices(api_key, group_id)
    raise HTTPException(status_code=400, detail="provider must be elevenlabs or minimax")

@app.post("/api/upload-video")
async def upload_video(file: UploadFile = File(...)):
    """Upload a local video file."""
    task_id = str(uuid.uuid4())[:8]
    ext = os.path.splitext(file.filename)[1] or ".mp4"
    saved_filename = f"upload_{task_id}{ext}"
    saved_path = os.path.join(UPLOAD_DIR, saved_filename)

    with open(saved_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    info = probe_video_info(saved_path)

    # Check audio volume level to see if it is silent
    is_silent = False
    if info.get("has_audio"):
        try:
            cmd = ["ffmpeg", "-i", saved_path, "-af", "volumedetect", "-vn", "-sn", "-dn", "-f", "null", "NUL"]
            res = subprocess.run(cmd, capture_output=True, text=True)
            for line in res.stderr.splitlines():
                if "max_volume:" in line:
                    vol_str = line.split("max_volume:")[1].replace("dB", "").strip()
                    if float(vol_str) <= -70.0:
                        is_silent = True
                    break
        except Exception:
            pass
    else:
        is_silent = True

    return {
        "success": True,
        "task_id": task_id,
        "filename": file.filename,
        "filepath": saved_path,
        "duration": info["duration"],
        "width": info["width"],
        "height": info["height"],
        "fps": info["fps"],
        "is_silent": is_silent
    }


@app.post("/api/download-url")
async def download_url(payload: Dict[str, Any]):
    """Download video from URL (YouTube, TikTok, Douyin, etc.)."""
    url = payload.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="กรุณาระบุ URL วิดีโอ")

    try:
        data = download_video_from_url(url, UPLOAD_DIR)
        info = probe_video_info(data["filepath"])
        return {
            "success": True,
            "title": data["title"],
            "filepath": data["filepath"],
            "thumbnail": data["thumbnail"],
            "duration": info["duration"],
            "width": info["width"],
            "height": info["height"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/tts/preview")
async def tts_preview(payload: Dict[str, Any]):
    """Audio preview for voices and tone styles."""
    text = payload.get("text", "สวัสดีครับ นี่คือตัวอย่างเสียงพากย์ AI สไตล์ใหม่")
    provider = payload.get("provider", "edge")
    preview_id = str(uuid.uuid4())[:8]
    out_audio = os.path.join(TEMP_DIR, f"preview_{preview_id}.mp3")

    try:
        ok = await synthesize_speech(
            text=text,
            output_path=out_audio,
            provider=provider,
            edge_voice=payload.get("edge_voice", "th-TH-NiwatNeural"),
            edge_speed=float(payload.get("edge_speed", 1.0)),
            edge_pitch=int(payload.get("edge_pitch", 0)),
            elevenlabs_api_key=payload.get("elevenlabs_api_key", ""),
            elevenlabs_voice_id=payload.get("elevenlabs_voice_id", "pNInz6obpgDQGcFmaJgB"),
            elevenlabs_tone=payload.get("elevenlabs_tone", "high_energy"),
            minimax_api_key=payload.get("minimax_api_key", ""),
            minimax_group_id=payload.get("minimax_group_id", ""),
            minimax_voice_id=payload.get("minimax_voice_id", "presenter_male"),
            minimax_emotion=payload.get("minimax_emotion", "excited"),
            minimax_speed=float(payload.get("minimax_speed", 1.0))
        )
        if ok:
            return {"success": True, "audio_url": f"/storage/temp/preview_{preview_id}.mp3"}
        else:
            raise RuntimeError("ไม่สามารถสร้างไฟล์เสียงตัวอย่างได้")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/analyze-product")
async def analyze_product_endpoint(payload: Dict[str, Any]):
    """Analyze video frames or product info to generate viral Thai script."""
    video_path = payload.get("video_filepath", "")
    mode = payload.get("product_mode", "auto")
    style = payload.get("script_style", "ป้ายยา")
    duration = float(payload.get("duration", 15.0))
    gemini_key = payload.get("gemini_api_key", "")
    name = payload.get("product_name", "")
    feats = payload.get("product_features", "")
    price = payload.get("product_price", "")
    manual_script = payload.get("manual_script", "")

    try:
        res = generate_product_script(
            video_path=video_path,
            mode=mode,
            script_style=style,
            duration=duration,
            product_name=name,
            product_features=feats,
            product_price=price,
            manual_script=manual_script,
            gemini_api_key=gemini_key,
            temp_dir=TEMP_DIR
        )
        return {"success": True, "data": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ProcessPipelineRequest(BaseModel):
    # Video source
    video_source_type: str = "url"     # 'url' or 'upload'
    video_url: Optional[str] = ""
    video_filepath: Optional[str] = ""

    # ASR Transcription & Translation Controls (Can be toggled ON/OFF)
    enable_asr: bool = True
    whisper_model: str = "base"         # 'tiny', 'base', 'small', 'medium'
    source_language: str = "auto"

    # Translation
    translation_mode: str = "translate" # 'none' (ไม่แปลภาษา), 'translate' (แปลภาษา), 'bilingual' (Bilingual)
    target_language: str = "th"
    enable_translation: bool = True
    llm_api_key: Optional[str] = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    segment_mode: str = "natural"       # 'none', 'natural', 'word_count', 'sentence'

    # AI Dubbing (TTS)
    enable_tts: bool = True
    tts_provider: str = "edge"          # 'edge', 'elevenlabs', 'minimax'
    edge_voice: str = "th-TH-NiwatNeural"
    edge_speed: float = 1.0
    edge_pitch: int = 0

    # ElevenLabs
    elevenlabs_api_key: Optional[str] = ""
    elevenlabs_voice_id: str = "pNInz6obpgDQGcFmaJgB"
    elevenlabs_tone: str = "high_energy"

    # MiniMax
    minimax_api_key: Optional[str] = ""
    minimax_group_id: Optional[str] = ""
    minimax_voice_id: str = "presenter_male"
    minimax_emotion: str = "excited"
    minimax_speed: float = 1.0

    # Audio ducking
    original_audio_volume: float = 0.15

    # Subtitles (OpenShorts style)
    enable_subtitles: bool = True
    subtitle_preset: str = "มาตรฐาน"    # 'มาตรฐาน', 'มินิมอล', 'ตัวหนาเด่น', 'นีออนเขียว', 'คาราโอเกะ', etc.
    subtitle_font: str = "Prompt"
    subtitle_font_size: int = 44
    subtitle_font_color: str = "#FFFFFF"
    subtitle_highlight_color: str = "#FFE500"
    subtitle_border_color: str = "#000000"
    subtitle_border_width: int = 4
    subtitle_effect: str = "pop"        # 'pop', 'glow', 'box', 'none'
    subtitle_alignment: str = "bottom"
    subtitle_margin_v: int = SAFE_MARGIN_V
    ai_highlight: bool = True

    # Video Render Layout & Aspect Ratio
    aspect_ratio: str = "9:16"          # '9:16', '1:1', '16:9', '4:5'
    layout_mode: str = "blur_9_16"      # 'blur_9_16', 'crop_9_16', 'krillin_title', 'original'
    major_title: Optional[str] = ""
    minor_title: Optional[str] = ""

    # Product & Script Analysis
    product_mode: str = "auto"          # 'auto', 'product_info', 'manual', 'asr'
    script_style: str = "ป้ายยา"         # from 12 styles
    product_name: Optional[str] = ""
    product_features: Optional[str] = ""
    product_price: Optional[str] = ""
    gemini_api_key: Optional[str] = ""
    custom_script: Optional[str] = ""


def run_pipeline_worker(task_id: str, req: ProcessPipelineRequest):
    """Background worker executing the complete pipeline."""
    task_dir = os.path.join(TEMP_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)

    try:
        # Step 1: Obtain video file
        update_task_progress(task_id, "download", 10, "กำลังเตรียมไฟล์วิดีโอ...")
        if req.video_source_type == "url":
            update_task_progress(task_id, "download", 15, f"กำลังดาวน์โหลดวิดีโอจากลิงก์: {req.video_url}...")
            dl_res = download_video_from_url(req.video_url, task_dir)
            video_path = dl_res["filepath"]
        else:
            video_path = req.video_filepath
            if not video_path or not os.path.exists(video_path):
                raise ValueError("ไม่พบไฟล์วิดีโอที่อัปโหลด")

        video_info = probe_video_info(video_path)
        total_duration = max(1.0, video_info["duration"])
        update_task_progress(task_id, "download", 25, f"เตรียมวิดีโอสำเร็จ ความยาว {total_duration:.1f} วินาที")

        # Step 2: Determine Script & Dubbing Mode
        translated_segments = []

        product_mode = req.product_mode
        if (req.product_name or "").strip() and product_mode == "auto":
            product_mode = "product_info"
            update_task_progress(task_id, "script", 32, "ข้าม Gemini เพราะใส่ชื่อสินค้า: " + (req.product_name or "").strip())
        if product_mode in ("auto", "product_info") or (product_mode == "manual" and req.custom_script and req.custom_script.strip()):
            if product_mode == "manual" and req.custom_script.strip():
                update_task_progress(task_id, "script", 35, "กำลังจัดไทม์ไลน์บทพูดตามที่เขียนเอง...")
                raw_lines = [l.strip() for l in re.split(r'[\n\r]+', req.custom_script.strip()) if l.strip()]
            elif product_mode == "product_info":
                update_task_progress(task_id, "script", 35, f"กำลังสร้างสคริปต์สินค้าจากข้อมูลที่ระบุ (แนว {req.script_style})...")
                res = generate_product_script(
                    mode="product_info",
                    script_style=req.script_style,
                    duration=total_duration,
                    product_name=req.product_name or "",
                    product_features=req.product_features or "",
                    product_price=req.product_price or ""
                )
                raw_lines = res.get("script_lines", [])
            else:
                # Auto: 45s vision timeout, then ASR. Own pool (never the global executor).
                update_task_progress(task_id, "script", 35, f"AI กำลังวิเคราะห์สินค้าจากภาพวิดีโอ & แต่งสคริปต์แนว '{req.script_style}'...")
                res = {}
                try:
                    from concurrent.futures import ThreadPoolExecutor as _VisionPool
                    with _VisionPool(max_workers=1) as _vision_pool:
                        fut = _vision_pool.submit(
                            generate_product_script,
                            video_path=video_path,
                            mode="auto",
                            script_style=req.script_style,
                            duration=total_duration,
                            gemini_api_key=req.gemini_api_key or "",
                            temp_dir=task_dir,
                        )
                        res = fut.result(timeout=45)
                    prod_title = (res or {}).get("product_name", "")
                    if prod_title:
                        update_task_progress(task_id, "script", 45, f"ตรวจพบสินค้า: {prod_title}")
                    raw_lines = (res or {}).get("script_lines", [])
                except Exception:
                    update_task_progress(task_id, "script", 40, "วิเคราะห์ภาพไม่สำเร็จหรือหมดเวลา กำลังถอดเสียงจากคลิปแทน...")
                    raw_lines = []
                    try:
                        audio_path = os.path.join(task_dir, "extracted_audio.wav")
                        extract_audio(video_path, audio_path)
                        asr_res = transcribe_video(
                            audio_path,
                            model_size=req.whisper_model,
                            language=req.source_language if req.source_language != "auto" else None,
                        )
                        raw_lines = [
                            (s.get("text") or "").strip()
                            for s in (asr_res.get("segments") or [])
                            if (s.get("text") or "").strip()
                        ]
                        if raw_lines:
                            update_task_progress(task_id, "script", 48, f"ใช้บทจากเสียงในคลิป ({len(raw_lines)} ประโยค)")
                    except Exception:
                        raw_lines = []

            if not raw_lines:
                raise RuntimeError("วิเคราะห์ภาพและถอดเสียงไม่ได้ — ใส่ชื่อสินค้าที่ช่องข้อมูลสินค้า หรือเขียนสคริปต์เอง")

            step_dur = total_duration / max(1, len(raw_lines))
            for i, line in enumerate(raw_lines):
                s_start = round(i * step_dur + 0.2, 2)
                s_end = round(min(total_duration - 0.1, (i + 1) * step_dur - 0.1), 2)
                if s_end <= s_start:
                    s_end = s_start + 1.2
                translated_segments.append({
                    "id": i,
                    "start": s_start,
                    "end": s_end,
                    "text": line,
                    "words": tokenize_words_with_timing(line, s_start, s_end)
                })
            update_task_progress(task_id, "script", 55, f"สร้างบทพูดและไทม์สแตมป์สำเร็จ ({len(translated_segments)} ประโยค)")

        elif req.enable_asr:
            # Mode 'asr' (Translate original speech)
            update_task_progress(task_id, "asr", 30, "กำลังแยกเสียงและถอดเสียงด้วย Faster-Whisper...")
            audio_path = os.path.join(task_dir, "extracted_audio.wav")
            extract_audio(video_path, audio_path)

            asr_res = transcribe_video(
                audio_path,
                model_size=req.whisper_model,
                language=req.source_language if req.source_language != "auto" else None
            )
            segments = asr_res["segments"]
            detected_lang = asr_res["language"]

            if not segments:
                # Auto fallback to product analyzer if video is silent
                update_task_progress(task_id, "script", 35, f"ไม่พบเสียงพูดเดิม ระบบสลับเป็นโหมด AI วิเคราะห์สินค้าแนว '{req.script_style}' อัตโนมัติ...")
                res = generate_product_script(
                    video_path=video_path,
                    mode="auto",
                    script_style=req.script_style,
                    duration=total_duration,
                    gemini_api_key=req.gemini_api_key or "",
                    temp_dir=task_dir
                )
                raw_lines = res.get("script_lines", [])
                step_dur = total_duration / max(1, len(raw_lines))
                for i, line in enumerate(raw_lines):
                    s_start = round(i * step_dur + 0.2, 2)
                    s_end = round(min(total_duration - 0.1, (i + 1) * step_dur - 0.1), 2)
                    if s_end <= s_start:
                        s_end = s_start + 1.2
                    translated_segments.append({
                        "id": i,
                        "start": s_start,
                        "end": s_end,
                        "text": line,
                        "words": tokenize_words_with_timing(line, s_start, s_end)
                    })
            else:
                update_task_progress(task_id, "asr", 45, f"ถอดเสียงสำเร็จ ตรวจพบภาษา: {detected_lang} ({len(segments)} ประโยค)")

                # Step 3: Translation
                translated_segments = segments
                should_translate = req.enable_translation and req.translation_mode != "none"
                if should_translate and (detected_lang != req.target_language or req.target_language == "th"):
                    update_task_progress(task_id, "translate", 50, "กำลังแปลเนื้อหาเป็นภาษาไทยพร้อมจัดรูปประโยคสละสลวย...")
                    translated_segments = translate_segments_with_llm(
                        segments,
                        target_lang=req.target_language,
                        api_key=req.llm_api_key or "",
                        base_url=req.llm_base_url,
                        model=req.llm_model
                    )
                    update_task_progress(task_id, "translate", 65, "แปลภาษาไทยเรียบร้อยแล้ว")
        else:
            update_task_progress(task_id, "asr", 45, "ข้ามการถอดเสียงและแปลภาษา (ปิดระบบ ASR)...")

        # Step 4: Generate Subtitles (OpenShorts style)
        ass_path = None
        srt_path = os.path.join(OUTPUT_DIR, f"{task_id}_subtitles.srt")
        if translated_segments:
            generate_standard_srt(translated_segments, srt_path)

        if req.enable_subtitles and translated_segments:
            update_task_progress(task_id, "subtitles", 70, f"กำลังสร้างซับไตเติ้ลสไตล์: {req.subtitle_preset}...")
            ass_path = os.path.join(task_dir, "openshorts_subtitles.ass")

            font_name = req.subtitle_font
            font_size = req.subtitle_font_size
            font_color = req.subtitle_font_color
            highlight_color = req.subtitle_highlight_color
            border_color = req.subtitle_border_color
            border_width = req.subtitle_border_width
            effect = req.subtitle_effect

            # If a named preset was chosen, merge its style
            if req.subtitle_preset in SUBTITLE_PRESETS:
                pre = SUBTITLE_PRESETS[req.subtitle_preset]
                font_name = pre.get("font_name", font_name)
                font_color = pre.get("font_color", font_color)
                highlight_color = pre.get("highlight_color", highlight_color)
                border_color = pre.get("border_color", border_color)
                border_width = pre.get("border_width", border_width)
                effect = pre.get("effect", effect)

            generate_openshorts_ass(
                translated_segments,
                ass_path,
                font_name=font_name,
                font_size=font_size,
                font_color=font_color,
                highlight_color=highlight_color,
                border_color=border_color,
                border_width=border_width,
                effect=effect,
                alignment=req.subtitle_alignment,
                margin_v=req.subtitle_margin_v
            )

        # Step 5: AI Dubbing (TTS)
        dubbed_audio_path = None
        if req.enable_tts and translated_segments:
            update_task_progress(task_id, "tts", 75, f"กำลังสร้างเสียงพากย์ AI ด้วยระบบ {req.tts_provider.upper()}...")
            dubbed_audio_path = os.path.join(task_dir, "dubbed_track.mp3")

            tts_kwargs = {
                "edge_voice": req.edge_voice,
                "edge_speed": req.edge_speed,
                "edge_pitch": req.edge_pitch,
                "elevenlabs_api_key": req.elevenlabs_api_key,
                "elevenlabs_voice_id": req.elevenlabs_voice_id,
                "elevenlabs_tone": req.elevenlabs_tone,
                "minimax_api_key": req.minimax_api_key,
                "minimax_group_id": req.minimax_group_id,
                "minimax_voice_id": req.minimax_voice_id,
                "minimax_emotion": req.minimax_emotion,
                "minimax_speed": req.minimax_speed
            }

            # Run async loop for TTS in thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            ok = loop.run_until_complete(
                generate_dubbed_audio_track(
                    translated_segments,
                    total_duration,
                    dubbed_audio_path,
                    temp_dir=os.path.join(task_dir, "tts_chunks"),
                    provider=req.tts_provider,
                    **tts_kwargs
                )
            )
            loop.close()

            if ok:
                update_task_progress(task_id, "tts", 85, "สร้างเสียงพากย์และซิงค์ไทม์ไลน์เรียบร้อยแล้ว")
            else:
                update_task_progress(task_id, "tts", 85, "[แจ้งเตือน] ไม่สามารถสร้างเสียงพากย์ได้ จะใช้วิดีโอปกติ")
                dubbed_audio_path = None

        # Step 6: Final Video Render with Aspect Ratio
        update_task_progress(task_id, "render", 90, f"กำลังเรนเดอร์วิดีโอ (สัดส่วน {req.aspect_ratio}, โหมด: {req.layout_mode})...")
        final_video_name = f"{task_id}_final_shorts.mp4"
        final_video_path = os.path.join(OUTPUT_DIR, final_video_name)

        render_short_video(
            input_video=video_path,
            output_video=final_video_path,
            layout_mode=req.layout_mode,
            ass_subtitle_path=ass_path,
            dubbed_audio_path=dubbed_audio_path,
            original_audio_volume=req.original_audio_volume,
            major_title=req.major_title or "",
            minor_title=req.minor_title or "",
            aspect_ratio=req.aspect_ratio
        )

        update_task_progress(
            task_id, "completed", 100, "ประมวลผลสำเร็จพร้อมดาวน์โหลดแล้ว!",
            data={
                "video_url": f"/storage/outputs/{final_video_name}",
                "srt_url": f"/storage/outputs/{task_id}_subtitles.srt",
                "audio_url": f"/storage/outputs/{task_id}_dubbed.mp3" if dubbed_audio_path else "",
                "segments": translated_segments
            }
        )

    except Exception as e:
        err_msg = traceback.format_exc()
        print(f"[Pipeline Error] {err_msg}")
        update_task_progress(task_id, "error", 0, f"เกิดข้อผิดพลาด: {str(e)}")


@app.post("/api/pipeline")
async def start_pipeline(req: ProcessPipelineRequest, background_tasks: BackgroundTasks):
    """Start unified video processing pipeline."""
    task_id = str(uuid.uuid4())[:8]
    tasks_db[task_id] = {
        "id": task_id,
        "step": "queued",
        "progress": 0,
        "message": "กำลังเริ่มคิวงาน...",
        "logs": [f"[{time.strftime('%H:%M:%S')}] สร้างคิวงานสำเร็จ รหัส: {task_id}"],
        "data": {}
    }

    # Run in background
    executor.submit(run_pipeline_worker, task_id, req)

    return {"success": True, "task_id": task_id}


@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Get real-time task progress and logs."""
    if task_id not in tasks_db:
        raise HTTPException(status_code=404, detail="ไม่พบงานนี้ในระบบ")
    return tasks_db[task_id]


if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("  KrillinAI + OpenShorts Thai Studio")
    print("  เปิดเบราว์เซอร์ใช้งานได้ที่: http://127.0.0.1:8888")
    print("=" * 60)
    uvicorn.run(app, host="127.0.0.1", port=8888)
