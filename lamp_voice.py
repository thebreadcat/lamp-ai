"""Lamp voice — local Whisper STT (optional openai-whisper + ffmpeg)."""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from workshop import load_config

DEFAULT_WHISPER_MODEL = "tiny"
MAX_AUDIO_BYTES = 12 * 1024 * 1024  # 12 MB


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def whisper_cli_available() -> bool:
    return shutil.which("whisper") is not None


def whisper_python_available() -> bool:
    try:
        import whisper  # noqa: F401
        return True
    except ImportError:
        return False


def whisper_model(cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    return (cfg.get("whisper_model") or DEFAULT_WHISPER_MODEL).strip() or DEFAULT_WHISPER_MODEL


def voice_status(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    cli = whisper_cli_available()
    py = whisper_python_available()
    ff = ffmpeg_available()
    model = whisper_model(cfg)
    return {
        "ffmpeg": ff,
        "whisper_cli": cli,
        "whisper_python": py,
        "whisper_available": ff and (cli or py),
        "model": model,
        "stt_engine": "whisper" if (ff and (cli or py)) else "browser",
        "hint": (
            "pip install openai-whisper && install ffmpeg (brew install ffmpeg)"
            if not (ff and (cli or py))
            else None
        ),
    }


def _suffix_for_mime(mime: str) -> str:
    m = (mime or "").lower().split(";")[0].strip()
    return {
        "audio/webm": ".webm",
        "audio/ogg": ".ogg",
        "audio/mp4": ".m4a",
        "audio/mpeg": ".mp3",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
    }.get(m, ".webm")


def _transcribe_cli(path: Path, model: str, language: str = "en") -> dict:
    out_dir = Path(tempfile.mkdtemp(prefix="lamp-whisper-"))
    try:
        cmd = [
            "whisper",
            str(path),
            "--model",
            model,
            "--language",
            language,
            "--output_format",
            "txt",
            "--output_dir",
            str(out_dir),
        ]
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "whisper failed").strip()
            return {"ok": False, "error": err[:500]}
        txts = sorted(out_dir.glob("*.txt"))
        if not txts:
            return {"ok": False, "error": "no transcription output"}
        text = txts[0].read_text(encoding="utf-8", errors="replace").strip()
        return {"ok": True, "text": text, "engine": "whisper-cli"}
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


_whisper_model_cache = {}


def _transcribe_python(path: Path, model: str, language: str = "en") -> dict:
    try:
        import whisper
    except ImportError:
        return {"ok": False, "error": "openai-whisper not installed"}
    try:
        if model not in _whisper_model_cache:
            _whisper_model_cache[model] = whisper.load_model(model)
        wmodel = _whisper_model_cache[model]
        result = wmodel.transcribe(str(path), language=language or None)
        text = (result.get("text") or "").strip()
        return {"ok": True, "text": text, "engine": "whisper-python"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}


def transcribe_bytes(
    data: bytes,
    mime: str = "audio/webm",
    language: str = "en",
    cfg: dict | None = None,
) -> dict:
    cfg = cfg or load_config()
    if not data:
        return {"ok": False, "error": "empty audio"}
    if len(data) > MAX_AUDIO_BYTES:
        return {"ok": False, "error": "recording too large (max 12MB)"}
    if not ffmpeg_available():
        return {
            "ok": False,
            "error": "ffmpeg not found — install ffmpeg for Whisper (see github.com/openai/whisper)",
        }
    if not (whisper_cli_available() or whisper_python_available()):
        return {
            "ok": False,
            "error": "Whisper not found — pip install openai-whisper",
        }

    model = whisper_model(cfg)
    suffix = _suffix_for_mime(mime)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(data)
            tmp_path = Path(f.name)
        if whisper_cli_available():
            out = _transcribe_cli(tmp_path, model, language=language)
            if out.get("ok"):
                return out
            if whisper_python_available():
                return _transcribe_python(tmp_path, model, language=language)
            return out
        return _transcribe_python(tmp_path, model, language=language)
    finally:
        if tmp_path and tmp_path.exists():
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def clean_transcript(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text
