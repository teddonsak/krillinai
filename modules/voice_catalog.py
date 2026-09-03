"""Fetch live voice libraries from ElevenLabs and MiniMax."""
from typing import Any, Dict, List
import httpx

EL_FALLBACK = [
    {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel", "gender": "female", "labels": "premade"},
    {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella", "gender": "female", "labels": "premade"},
    {"id": "ErXwobaYiN019PkySvjV", "name": "Antoni", "gender": "male", "labels": "premade"},
    {"id": "pNInz6obpgDQGcFmaJgB", "name": "Adam", "gender": "male", "labels": "premade"},
    {"id": "VR6AewLTigWG4xSOukaG", "name": "Arnold", "gender": "male", "labels": "premade"},
    {"id": "AZnzlk1XvdvUeBnXmlld", "name": "Domi", "gender": "female", "labels": "premade"},
]

MM_FALLBACK = [
    {"id": "presenter_male", "name": "Presenter Male", "gender": "male"},
    {"id": "presenter_female", "name": "Presenter Female", "gender": "female"},
    {"id": "audiobook_male_1", "name": "Audiobook Male", "gender": "male"},
    {"id": "audiobook_female_1", "name": "Audiobook Female", "gender": "female"},
    {"id": "male-qn-qingse", "name": "Youth Male", "gender": "male"},
    {"id": "female-shaonv", "name": "Sweet Female", "gender": "female"},
]


async def fetch_elevenlabs_voices(api_key: str) -> Dict[str, Any]:
    if not api_key.strip():
        return {"ok": False, "source": "fallback", "voices": EL_FALLBACK, "error": "no_key"}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": api_key.strip(), "Accept": "application/json"},
            )
        if r.status_code != 200:
            return {"ok": False, "source": "fallback", "voices": EL_FALLBACK, "error": f"http_{r.status_code}"}
        data = r.json()
        voices = []
        for v in data.get("voices") or []:
            labels = v.get("labels") or {}
            gender = labels.get("gender") or ""
            voices.append({
                "id": v.get("voice_id") or "",
                "name": v.get("name") or "voice",
                "gender": gender,
                "labels": ", ".join(f"{k}:{val}" for k, val in labels.items())[:80],
                "category": v.get("category") or "",
            })
        voices = [x for x in voices if x["id"]]
        if not voices:
            return {"ok": False, "source": "fallback", "voices": EL_FALLBACK, "error": "empty"}
        return {"ok": True, "source": "elevenlabs", "voices": voices}
    except Exception as e:
        return {"ok": False, "source": "fallback", "voices": EL_FALLBACK, "error": str(e)}


async def fetch_minimax_voices(api_key: str, group_id: str = "") -> Dict[str, Any]:
    if not api_key.strip():
        return {"ok": False, "source": "fallback", "voices": MM_FALLBACK, "error": "no_key"}
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }
    urls = []
    if group_id.strip():
        urls.append(f"https://api.minimax.chat/v1/get_voice?GroupId={group_id.strip()}")
        urls.append(f"https://api.minimax.io/v1/get_voice?GroupId={group_id.strip()}")
    urls.extend([
        "https://api.minimax.chat/v1/get_voice",
        "https://api.minimax.io/v1/get_voice",
    ])
    last_err = "unknown"
    for url in urls:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.post(url, headers=headers, json={"voice_type": "all"})
            if r.status_code != 200:
                last_err = f"http_{r.status_code}"
                continue
            data = r.json()
            raw = []
            if isinstance(data, dict):
                raw = (
                    data.get("system_voice")
                    or data.get("voice_list")
                    or (data.get("data") or {}).get("system_voice")
                    or (data.get("data") or {}).get("voice_list")
                    or []
                )
            voices = []
            for v in raw:
                if not isinstance(v, dict):
                    continue
                vid = v.get("voice_id") or v.get("voice_name") or v.get("id") or ""
                name = v.get("voice_name") or v.get("name") or vid
                if vid:
                    voices.append({"id": vid, "name": name, "gender": v.get("gender") or ""})
            if voices:
                return {"ok": True, "source": "minimax", "voices": voices}
            last_err = "empty"
        except Exception as e:
            last_err = str(e)
    return {"ok": False, "source": "fallback", "voices": MM_FALLBACK, "error": last_err}
