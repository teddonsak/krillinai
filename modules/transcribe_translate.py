"""
Transcription & Translation Module
Extracts audio, transcribes with Faster-Whisper (with word-level timestamps),
and translates to Thai or target language using LLM (OpenAI/DeepSeek) or free translator.
"""

import os
import re
import json
import subprocess
import httpx
from typing import List, Dict, Any, Optional, Tuple

try:
    from pythainlp.tokenize import word_tokenize
    HAS_PYTHAINLP = True
except ImportError:
    HAS_PYTHAINLP = False

# Global model cache so we don't reload whisper every job
_WHISPER_MODEL = None
_WHISPER_MODEL_SIZE = None


def extract_audio(video_path: str, output_audio_path: str) -> bool:
    """Extract clean 16kHz mono audio with normalization for Whisper ASR."""
    os.makedirs(os.path.dirname(os.path.abspath(output_audio_path)), exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,volume=1.5",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        output_audio_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not os.path.exists(output_audio_path):
        # Fallback simple extraction
        cmd_simple = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", output_audio_path
        ]
        subprocess.run(cmd_simple, capture_output=True)
    return os.path.exists(output_audio_path)


def transcribe_video(
    audio_or_video_path: str,
    model_size: str = "base",
    language: Optional[str] = None,
    device: str = "cpu",
    compute_type: str = "int8"
) -> Dict[str, Any]:
    """
    Transcribe audio with Faster-Whisper and extract word-level timestamps.
    Automatically retries without VAD if initial result yields 0 segments.
    """
    global _WHISPER_MODEL, _WHISPER_MODEL_SIZE
    from faster_whisper import WhisperModel

    if _WHISPER_MODEL is None or _WHISPER_MODEL_SIZE != model_size:
        print(f"[ASR] Loading Faster-Whisper model: {model_size} on {device} ({compute_type})...")
        _WHISPER_MODEL = WhisperModel(model_size, device=device, compute_type=compute_type)
        _WHISPER_MODEL_SIZE = model_size

    # Pass 1: With VAD
    segments_gen, info = _WHISPER_MODEL.transcribe(
        audio_or_video_path,
        language=language if language and language != "auto" else None,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5
    )

    detected_language = info.language
    detected_prob = info.language_probability

    parsed_segments = []
    for s in segments_gen:
        words = []
        if s.words:
            for w in s.words:
                words.append({
                    "word": w.word.strip(),
                    "start": round(w.start, 2),
                    "end": round(w.end, 2),
                    "probability": round(w.probability, 2)
                })

        parsed_segments.append({
            "id": s.id,
            "start": round(s.start, 2),
            "end": round(s.end, 2),
            "text": s.text.strip(),
            "words": words
        })

    # Pass 2: If VAD yielded 0 segments, retry without VAD
    if not parsed_segments:
        print("[ASR] 0 segments with VAD, retrying without VAD filter...")
        segments_gen, info = _WHISPER_MODEL.transcribe(
            audio_or_video_path,
            language=language if language and language != "auto" else None,
            word_timestamps=True,
            vad_filter=False,
            beam_size=5
        )
        for s in segments_gen:
            if s.text.strip():
                words = []
                if s.words:
                    for w in s.words:
                        words.append({
                            "word": w.word.strip(),
                            "start": round(w.start, 2),
                            "end": round(w.end, 2),
                            "probability": round(w.probability, 2)
                        })
                parsed_segments.append({
                    "id": s.id,
                    "start": round(s.start, 2),
                    "end": round(s.end, 2),
                    "text": s.text.strip(),
                    "words": words
                })

    return {
        "language": detected_language,
        "language_probability": round(detected_prob, 2),
        "duration": round(info.duration, 2),
        "segments": parsed_segments
    }


def translate_with_free_service(text: str, target_lang: str = "th", source_lang: str = "auto") -> str:
    """Free Google Translate endpoint fallback."""
    if not text.strip():
        return ""
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": source_lang,
            "tl": target_lang,
            "dt": "t",
            "q": text
        }
        with httpx.Client(timeout=15.0) as client:
            res = client.get(url, params=params)
            if res.status_code == 200:
                data = res.json()
                translated_parts = [item[0] for item in data[0] if item and item[0]]
                return "".join(translated_parts).strip()
    except Exception as e:
        print(f"[Translate Warning] Free translate failed: {e}")
    return text


def translate_segments_with_llm(
    segments: List[Dict[str, Any]],
    target_lang: str = "th",
    api_key: str = "",
    base_url: str = "https://api.openai.com/v1",
    model: str = "gpt-4o-mini"
) -> List[Dict[str, Any]]:
    """
    Context-aware translation using OpenAI / DeepSeek / Compatible LLM.
    Preserves subtitle timing and creates natural conversational Thai phrasing.
    """
    if not api_key:
        # Fallback to free translator
        return translate_segments_with_fallback(segments, target_lang=target_lang)

    lang_map = {
        "th": "ภาษาไทย (Thai - สำนวนธรรมชาติ กระชับ เหมาะกับคำบรรยายวิดีโอสั้น TikTok)",
        "en": "English",
        "zh": "Simplified Chinese",
        "ja": "Japanese"
    }
    target_lang_desc = lang_map.get(target_lang, target_lang)

    # Batch segments into manageable chunks (up to 30 per call)
    batch_size = 25
    translated_all = []

    for i in range(0, len(segments), batch_size):
        chunk = segments[i:i + batch_size]
        items_to_translate = [{"id": s.get("id", idx), "text": s["text"]} for idx, s in enumerate(chunk)]

        prompt = (
            f"You are a professional subtitle translator for short-form viral videos (TikTok, YouTube Shorts, Reels).\n"
            f"Translate the following subtitles to {target_lang_desc}.\n"
            f"Guidelines:\n"
            f"- Make it sound natural, engaging, and spoken (casual conversational tone for Thai, no stiff robotic text).\n"
            f"- Keep sentences concise so viewers can read easily.\n"
            f"- Return ONLY a valid JSON array of objects with keys 'id' and 'translated_text'. Do not include markdown code block backticks.\n\n"
            f"Input:\n{json.dumps(items_to_translate, ensure_ascii=False)}"
        )

        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are an expert subtitle and video dubbing translator. Output only JSON."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3
        }

        try:
            with httpx.Client(timeout=60.0) as client:
                res = client.post(f"{base_url.rstrip('/')}/chat/completions", headers=headers, json=payload)
                if res.status_code == 200:
                    resp_json = res.json()
                    content = resp_json["choices"][0]["message"]["content"].strip()
                    # Clean possible markdown formatting
                    content = re.sub(r"^```json\s*", "", content)
                    content = re.sub(r"^```\s*", "", content)
                    content = re.sub(r"\s*```$", "", content)
                    parsed_res = json.loads(content)

                    # Map translations back
                    trans_dict = {item["id"]: item.get("translated_text", "") for item in parsed_res if isinstance(item, dict)}
                    for s in chunk:
                        sid = s.get("id")
                        t_text = trans_dict.get(sid) or translate_with_free_service(s["text"], target_lang=target_lang)
                        s_copy = dict(s)
                        s_copy["original_text"] = s["text"]
                        s_copy["text"] = t_text
                        # Regenerate word tokens for Thai
                        s_copy["words"] = tokenize_words_with_timing(t_text, s["start"], s["end"])
                        translated_all.append(s_copy)
                    continue
        except Exception as e:
            print(f"[LLM Translation Warning] Failed on batch: {e}. Falling back to free translator.")

        # Fallback for this chunk
        for s in chunk:
            t_text = translate_with_free_service(s["text"], target_lang=target_lang)
            s_copy = dict(s)
            s_copy["original_text"] = s["text"]
            s_copy["text"] = t_text
            s_copy["words"] = tokenize_words_with_timing(t_text, s["start"], s["end"])
            translated_all.append(s_copy)

    return translated_all


def translate_segments_with_fallback(segments: List[Dict[str, Any]], target_lang: str = "th") -> List[Dict[str, Any]]:
    """Translate all segments using Google Translate free endpoint."""
    translated_all = []
    for s in segments:
        orig = s["text"]
        t_text = translate_with_free_service(orig, target_lang=target_lang)
        s_copy = dict(s)
        s_copy["original_text"] = orig
        s_copy["text"] = t_text
        s_copy["words"] = tokenize_words_with_timing(t_text, s["start"], s["end"])
        translated_all.append(s_copy)
    return translated_all


def tokenize_words_with_timing(text: str, start: float, end: float) -> List[Dict[str, Any]]:
    """Assign proportional timestamps to translated words."""
    if not text.strip():
        return []
    if HAS_PYTHAINLP:
        tokens = [t for t in word_tokenize(text, engine="newmm") if t.strip()]
    else:
        tokens = [t for t in text.split() if t.strip()]

    if not tokens:
        tokens = [text]

    total_chars = sum(len(t) for t in tokens)
    dur = max(0.1, end - start)
    words = []
    curr = start
    for t in tokens:
        w_dur = (len(t) / max(1, total_chars)) * dur
        words.append({
            "word": t,
            "start": round(curr, 2),
            "end": round(curr + w_dur, 2)
        })
        curr += w_dur
    return words
