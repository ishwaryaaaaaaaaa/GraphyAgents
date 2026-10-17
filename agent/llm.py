"""One safe LLM client: cached, throttled, retried, and switchable off.

The LLM only reads a sentence and writes a sentence. It never decides what is true.
LLM_MODE=off (the default) makes `ask` raise LLMUnavailable so callers use their fallback;
all tests run in this mode. Provider: Gemini via google-genai. Set LLM_MODEL in .env
(check Google AI Studio for the current model name; the default may be out of date).
"""
import hashlib
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = Path(os.getenv("LLM_CACHE", ROOT / ".llm_cache.json"))
LOG_PATH = Path(os.getenv("LLM_LOG", ROOT / ".llm_calls.jsonl"))
DEFAULT_MODEL = "gemini-2.5-flash"
BACKOFF = (1, 2, 4, 8)   # seconds to wait after each 429, then give up
MIN_GAP = 1.0            # seconds between live requests: free tiers have per-minute limits

_last_call = 0.0
_cache = None


class LLMUnavailable(RuntimeError):
    """The LLM is off, has no key, or kept failing. Callers must have a fallback."""


def mode():
    return os.getenv("LLM_MODE", "off").lower()


def model():
    return os.getenv("LLM_MODEL") or DEFAULT_MODEL


def _load_cache():
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _save_cache():
    try:
        CACHE_PATH.write_text(json.dumps(_cache, indent=1), encoding="utf-8")
    except OSError:
        pass  # a read-only checkout must not break the agent


def _log(prompt, seconds, cached, outcome):
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": round(time.time()), "chars": len(prompt), "seconds":
                                round(seconds, 2), "cached": cached, "outcome": outcome,
                                "model": model()}) + "\n")
    except OSError:
        pass


def _call_gemini(prompt, schema=None):
    """The only function that touches the network. Tests replace it."""
    from google import genai

    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise LLMUnavailable("GEMINI_API_KEY is not set")
    config: dict = {"temperature": 0}
    if schema is not None:
        config["response_mime_type"] = "application/json"
        config["response_json_schema"] = schema
    resp = genai.Client(api_key=key).models.generate_content(
        model=model(), contents=prompt, config=config)
    return resp.text or ""


def _is_rate_limit(exc):
    code = getattr(exc, "code", None)
    text = str(exc)
    return code in (429, 503) or "429" in text or "RESOURCE_EXHAUSTED" in text


def ask(prompt, schema=None, sleep=time.sleep):
    """Return the model's text. Cached by prompt, so eval reruns are free and repeatable."""
    global _last_call
    if mode() == "off":
        raise LLMUnavailable("LLM_MODE=off")

    cache = _load_cache()
    key = hashlib.sha256(json.dumps([model(), prompt, schema], sort_keys=True).encode()).hexdigest()
    if key in cache:
        _log(prompt, 0.0, True, "hit")
        return cache[key]

    start = time.time()
    for attempt in range(len(BACKOFF) + 1):
        wait = MIN_GAP - (time.time() - _last_call)
        if wait > 0:
            sleep(wait)
        _last_call = time.time()
        try:
            text = _call_gemini(prompt, schema)
            cache[key] = text
            _save_cache()
            _log(prompt, time.time() - start, False, "ok")
            return text
        except LLMUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - provider errors vary; classify below
            if _is_rate_limit(exc) and attempt < len(BACKOFF):
                sleep(BACKOFF[attempt])
                continue
            _log(prompt, time.time() - start, False, f"error:{type(exc).__name__}")
            raise LLMUnavailable(f"LLM call failed: {exc}") from exc
    raise LLMUnavailable("LLM kept rate-limiting")
