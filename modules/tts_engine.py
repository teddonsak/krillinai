"""
AI TTS Dubbing Module
Supports:
1. Edge-TTS (Free, no API key required) - Thai Niwat & Premwadee
2. ElevenLabs API (with Tone Presets: High Energy, Storyteller, News, Casual, Mystery)
3. MiniMax API (T2A v2 with Emotions: Happy, Excited, Neutral, Sad, etc.)
"""

import os
import re
import json
import asyncio
import subprocess
import httpx
from typing import List, Dict, Any, Optional

# Edge-TTS voices
EDGE_VOICES = {
    "th-TH-NiwatNeural": {"name": "ไทย: นิวัฒน์ (ชาย - ธรรมชาติ/ทางการ)", "gender": "male", "lang": "th"},
    "th-TH-PremwadeeNeural": {"name": "ไทย: เปรมวดี (หญิง - สดใส/เป็นมิตร)", "gender": "female", "lang": "th"},
    "en-US-AndrewMultilingualNeural": {"name": "English: Andrew (Multilingual Male)", "gender": "male", "lang": "en"},
    "en-US-AvaMultilingualNeural": {"name": "English: Ava (Multilingual Female)", "gender": "female", "lang": "en"},
    "zh-CN-YunxiNeural": {"name": "中文: 云希 (男声 - 热情/解说)", "gender": "male", "lang": "zh"},
    "zh-CN-XiaoxiaoNeural": {"name": "中文: 晓晓 (女声 - 温暖/亲切)", "gender": "female", "lang": "zh"},
    "ja-JP-KeitaNeural": {"name": "日本語: けいた (男性)", "gender": "male", "lang": "ja"},
    "ja-JP-NanamiNeural": {"name": "日本語: ななみ (女性)", "gender": "female", "lang": "ja"},
}

# ElevenLabs Tone Presets
ELEVENLABS_TONE_PRESETS = {
    "high_energy": {
        "name": "⚡ ตื่นเต้น เร้าใจ (TikTok / Shorts Hype)",
        "stability": 0.35,
        "similarity_boost": 0.85,
        "style": 0.55,
        "use_speaker_boost": True
    },
    "storyteller": {
        "name": "🎙️ เล่าเรื่อง สารคดี (Storyteller / Documentary)",
        "stability": 0.65,
        "similarity_boost": 0.80,
        "style": 0.25,
        "use_speaker_boost": True
    },
    "news": {
        "name": "📢 ทางการ ผู้ประกาศข่าว (News / Professional)",
        "stability": 0.75,
        "similarity_boost": 0.80,
        "style": 0.10,
        "use_speaker_boost": True
    },
    "casual": {
        "name": "💬 เป็นกันเอง สบายๆ (Casual / Friendly Vlog)",
        "stability": 0.48,
        "similarity_boost": 0.75,
        "style": 0.35,
        "use_speaker_boost": True
    },
    "mystery": {
        "name": "🤫 ลึกลับ ระทึกขวัญ (Mystery / Suspense)",
        "stability": 0.60,
        "similarity_boost": 0.75,
        "style": 0.50,
        "use_speaker_boost": True
    }
}

# ElevenLabs Popular Voices (Supports Multilingual v2 including Thai)
ELEVENLABS_POPULAR_VOICES = {
    "21m00Tcm4TlvDq8ikWAM": {"name": "Rachel (หญิง - นุ่มนวล ชัดเจน)", "gender": "female"},
    "AZnzlk1XvdvUeBnXmlld": {"name": "Domi (หญิง - แข็งแกร่ง น่าดึงดูด)", "gender": "female"},
    "EXAVITQu4vr4xnSDxMaL": {"name": "Bella (หญิง - สดใส มีพลัง)", "gender": "female"},
    "ErXwobaYiN019PkySvjV": {"name": "Antoni (ชาย - สุภาพ ชวนฟัง)", "gender": "male"},
    "VR6AewLTigWG4xSOukaG": {"name": "Arnold (ชาย - ทรงพลัง คมเข้ม)", "gender": "male"},
    "pNInz6obpgDQGcFmaJgB": {"name": "Adam (ชาย - ผู้บรรยาย สารคดี)", "gender": "male"}
}

# MiniMax Emotion options
MINIMAX_EMOTIONS = {
    "neutral": "😐 ปกติ (Neutral)",
    "happy": "😄 มีความสุข (Happy)",
    "excited": "🤩 ตื่นเต้นเร้าใจ (Excited)",
    "sad": "😢 เศร้าซึ้ง (Sad)",
    "angry": "😠 ดุดัน จริงจัง (Angry)",
    "fearful": "😨 ประหม่า ตื่นตระหนก (Fearful)"
}

MINIMAX_POPULAR_VOICES = {
    "presenter_male": {"name": "ผู้ประกาศชาย (Presenter Male)", "gender": "male"},
    "presenter_female": {"name": "ผู้ประกาศหญิง (Presenter Female)", "gender": "female"},
    "audiobook_male_1": {"name": "นักเล่าหนังสือเสียง ชาย (Audiobook Male)", "gender": "male"},
    "audiobook_female_1": {"name": "นักเล่าหนังสือเสียง หญิง (Audiobook Female)", "gender": "female"},
    "male-qn-qingse": {"name": "ชายหนุ่มสดใส (Youth Male)", "gender": "male"},
    "female-shaonv": {"name": "หญิงสาวน่ารัก (Sweet Female)", "gender": "female"}
}


async def generate_edge_tts(
    text: str,
    output_path: str,
    voice: str = "th-TH-NiwatNeural",
    speed: float = 1.0,
    pitch: int = 0,
    volume: int = 0
) -> bool:
    """Generate audio using free Edge-TTS."""
    import edge_tts

    rate_str = f"{int((speed - 1.0) * 100):+d}%"
    pitch_str = f"{pitch:+d}Hz"
    vol_str = f"{volume:+d}%"

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate_str,
        pitch=pitch_str,
        volume=vol_str
    )
    await communicate.save(output_path)
    return os.path.exists(output_path) and os.path.getsize(output_path) > 0


def generate_elevenlabs_tts(
    text: str,
    output_path: str,
    api_key: str,
    voice_id: str = "pNInz6obpgDQGcFmaJgB",
    tone_preset: str = "high_energy",
    model_id: str = "eleven_multilingual_v2",
    custom_stability: Optional[float] = None,
    custom_similarity: Optional[float] = None,
    custom_style: Optional[float] = None
) -> bool:
    """Generate audio using ElevenLabs API with Tone Preset."""
    if not api_key:
        raise ValueError("กรุณาระบุ ElevenLabs API Key")

    preset = ELEVENLABS_TONE_PRESETS.get(tone_preset, ELEVENLABS_TONE_PRESETS["high_energy"])
    stability = custom_stability if custom_stability is not None else preset["stability"]
    similarity_boost = custom_similarity if custom_similarity is not None else preset["similarity_boost"]
    style = custom_style if custom_style is not None else preset["style"]

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key.strip(),
        "Content-Type": "application/json"
    }
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost,
            "style": style,
            "use_speaker_boost": True
        }
    }

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"ElevenLabs API Error ({resp.status_code}): {resp.text}")
        with open(output_path, "wb") as f:
            f.write(resp.content)

    return os.path.exists(output_path) and os.path.getsize(output_path) > 0


def generate_minimax_tts(
    text: str,
    output_path: str,
    api_key: str,
    group_id: str = "",
    voice_id: str = "presenter_male",
    model: str = "speech-01-turbo",
    emotion: str = "happy",
    speed: float = 1.0,
    pitch: int = 0,
    vol: float = 1.0
) -> bool:
    """Generate audio using MiniMax API (T2A v2)."""
    if not api_key:
        raise ValueError("กรุณาระบุ MiniMax API Key")

    url = "https://api.minimax.chat/v1/t2a_v2"
    params = {}
    if group_id.strip():
        params["GroupId"] = group_id.strip()

    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "text": text,
        "stream": False,
        "voice_setting": {
            "voice_id": voice_id,
            "speed": speed,
            "vol": vol,
            "pitch": pitch,
            "emotion": emotion
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1
        }
    }

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(url, headers=headers, params=params, json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"MiniMax API Error ({resp.status_code}): {resp.text}")

        data = resp.json()
        if data.get("base_resp", {}).get("status_code", 0) != 0:
            msg = data.get("base_resp", {}).get("status_msg", "Unknown error")
            raise RuntimeError(f"MiniMax Error: {msg}")

        # MiniMax returns hex-encoded audio in data.audio
        audio_hex = data.get("data", {}).get("audio", "")
        if not audio_hex:
            raise RuntimeError("MiniMax did not return audio data")

        audio_bytes = bytes.fromhex(audio_hex)
        with open(output_path, "wb") as f:
            f.write(audio_bytes)

    return os.path.exists(output_path) and os.path.getsize(output_path) > 0


async def synthesize_speech(
    text: str,
    output_path: str,
    provider: str = "edge",
    # Edge params
    edge_voice: str = "th-TH-NiwatNeural",
    edge_speed: float = 1.0,
    edge_pitch: int = 0,
    # ElevenLabs params
    elevenlabs_api_key: str = "",
    elevenlabs_voice_id: str = "pNInz6obpgDQGcFmaJgB",
    elevenlabs_tone: str = "high_energy",
    # MiniMax params
    minimax_api_key: str = "",
    minimax_group_id: str = "",
    minimax_voice_id: str = "presenter_male",
    minimax_emotion: str = "excited",
    minimax_speed: float = 1.0
) -> bool:
    """Universal dispatcher for TTS synthesis."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    if provider == "elevenlabs":
        return generate_elevenlabs_tts(
            text=text,
            output_path=output_path,
            api_key=elevenlabs_api_key,
            voice_id=elevenlabs_voice_id,
            tone_preset=elevenlabs_tone
        )
    elif provider == "minimax":
        return generate_minimax_tts(
            text=text,
            output_path=output_path,
            api_key=minimax_api_key,
            group_id=minimax_group_id,
            voice_id=minimax_voice_id,
            emotion=minimax_emotion,
            speed=minimax_speed
        )
    else:
        # Default: Edge-TTS
        return await generate_edge_tts(
            text=text,
            output_path=output_path,
            voice=edge_voice,
            speed=edge_speed,
            pitch=edge_pitch
        )


async def generate_dubbed_audio_track(
    segments: List[Dict[str, Any]],
    total_video_duration: float,
    output_audio_path: str,
    temp_dir: str,
    provider: str = "edge",
    **tts_kwargs
) -> bool:
    """
    Generate a synchronized multi-segment dubbed audio track from translated subtitle segments.
    Uses FFmpeg to place each spoken segment at its respective timestamp.
    """
    os.makedirs(temp_dir, exist_ok=True)
    chunk_files = []

    # 1. Synthesize audio for each segment
    for idx, seg in enumerate(segments):
        txt = str(seg.get("text", "")).strip()
        if not txt:
            continue
        start_t = float(seg.get("start", 0.0))
        chunk_path = os.path.join(temp_dir, f"dub_chunk_{idx:04d}.mp3")

        try:
            ok = await synthesize_speech(
                text=txt,
                output_path=chunk_path,
                provider=provider,
                **tts_kwargs
            )
            if ok and os.path.exists(chunk_path):
                chunk_files.append({
                    "path": chunk_path,
                    "start": start_t
                })
        except Exception as e:
            print(f"[TTS Warning] Segment {idx} failed: {e}")

    if not chunk_files:
        return False

    # 2. Mix into continuous timeline using FFmpeg adelay filter
    inputs = []
    filter_complex_parts = []

    for i, c in enumerate(chunk_files):
        inputs.extend(["-i", c["path"]])
        delay_ms = int(c["start"] * 1000)
        filter_complex_parts.append(f"[{i}:a]adelay={delay_ms}|{delay_ms}[a{i}]")

    mix_inputs = "".join(f"[a{i}]" for i in range(len(chunk_files)))
    filter_complex_parts.append(
        f"{mix_inputs}amix=inputs={len(chunk_files)}:duration=longest:dropout_transition=0:normalize=0[aout]"
    )

    full_filter = ";".join(filter_complex_parts)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", full_filter,
        "-map", "[aout]",
        "-c:a", "libmp3lame",
        "-q:a", "2",
        output_audio_path
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        # Fallback: simple concat if adelay fails
        print(f"[FFmpeg Warning] adelay failed, falling back to simple mix: {res.stderr[:200]}")
        concat_list = os.path.join(temp_dir, "concat.txt")
        with open(concat_list, "w", encoding="utf-8") as f:
            for c in chunk_files:
                f.write(f"file '{os.path.abspath(c['path']).replace(chr(92), '/')}'\n")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
            "-c:a", "libmp3lame", "-q:a", "2", output_audio_path
        ], capture_output=True)

    return os.path.exists(output_audio_path) and os.path.getsize(output_audio_path) > 0
