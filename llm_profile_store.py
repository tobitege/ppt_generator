import json
import os
from pathlib import Path


DEFAULT_PROFILES = {
    "LM Studio Local": {
        "provider_name": "LM Studio",
        "provider": "lm_studio",
        "base_url": "http://127.0.0.1:1234/v1",
        "model": "dolphin-2.1-mistral-7b",
        "temperature": 0.4,
        "timeout_seconds": 180,
        "retries": 2,
        "retry_delay_seconds": 1.5,
        "request_delay_seconds": 0.75,
    },
    "Ollama Local": {
        "provider_name": "Ollama",
        "provider": "ollama",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "dolphin2.1-mistral",
        "temperature": 0.4,
        "timeout_seconds": 180,
        "retries": 2,
        "retry_delay_seconds": 1.5,
        "request_delay_seconds": 0.75,
    },
    "OpenAI": {
        "provider_name": "OpenAI",
        "provider": "openai_compat",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "temperature": 0.4,
        "timeout_seconds": 180,
        "retries": 2,
        "retry_delay_seconds": 1.5,
        "request_delay_seconds": 0.75,
    },
    "OpenRouter": {
        "provider_name": "OpenRouter",
        "provider": "openai_compat",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini",
        "temperature": 0.4,
        "timeout_seconds": 180,
        "retries": 2,
        "retry_delay_seconds": 1.5,
        "request_delay_seconds": 0.75,
    },
}

REQUIRED_FIELDS = {
    "provider",
    "base_url",
    "model",
    "temperature",
    "retries",
    "retry_delay_seconds",
    "request_delay_seconds",
}

PROVIDER_NAME_DEFAULTS = {
    "lm_studio": "LM Studio",
    "ollama": "Ollama",
    "openai_compat": "OpenAI-compatible",
}


def profile_store_path():
    override = os.getenv("PPT_PROFILE_STORE_PATH", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / ".llm_profiles.json"


def _default_provider_name(provider, profile_name):
    fallback = PROVIDER_NAME_DEFAULTS.get(provider, "OpenAI-compatible")
    if profile_name:
        return profile_name
    return fallback


def _sanitize_profiles(raw_profiles):
    cleaned = {}
    if not isinstance(raw_profiles, dict):
        return cleaned

    for name, cfg in raw_profiles.items():
        if not isinstance(name, str):
            continue
        profile_name = name.strip()
        if not profile_name:
            continue
        if not isinstance(cfg, dict):
            continue
        if not REQUIRED_FIELDS.issubset(cfg.keys()):
            continue
        provider = str(cfg["provider"]).strip()
        provider_name = str(cfg.get("provider_name") or "").strip()
        if not provider_name:
            provider_name = _default_provider_name(provider, profile_name)
        cleaned[profile_name] = {
            "provider_name": provider_name,
            "provider": provider,
            "base_url": str(cfg["base_url"]).strip(),
            "model": str(cfg["model"]).strip(),
            "temperature": float(cfg["temperature"]),
            "timeout_seconds": int(cfg.get("timeout_seconds", 180)),
            "retries": int(cfg["retries"]),
            "retry_delay_seconds": float(cfg["retry_delay_seconds"]),
            "request_delay_seconds": float(cfg["request_delay_seconds"]),
        }
    return cleaned


def load_profiles():
    path = profile_store_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return _sanitize_profiles(raw)


def save_profiles(profiles):
    path = profile_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_profiles = _sanitize_profiles(profiles)
    path.write_text(json.dumps(safe_profiles, indent=2), encoding="utf-8")


def ensure_profiles():
    profiles = load_profiles()
    if profiles:
        return profiles
    profiles = dict(DEFAULT_PROFILES)
    save_profiles(profiles)
    return profiles
