import json
import os
from datetime import datetime, timezone
from uuid import uuid4


_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
_HISTORY_DIR = os.path.join(_ROOT_DIR, ".presentation_history")
_INDEX_PATH = os.path.join(_HISTORY_DIR, "index.json")
_MAX_HISTORY_ITEMS = 50


def _ensure_history_dir():
    os.makedirs(_HISTORY_DIR, exist_ok=True)


def _safe_text(value):
    return str(value or "").strip()


def _sort_entries(entries):
    return sorted(
        entries,
        key=lambda item: _safe_text(item.get("created_at")),
        reverse=True,
    )


def _read_index():
    _ensure_history_dir()
    if not os.path.exists(_INDEX_PATH):
        return []
    try:
        with open(_INDEX_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, list):
            return _sort_entries([item for item in data if isinstance(item, dict)])
    except Exception:
        pass
    return []


def _write_index(entries):
    _ensure_history_dir()
    with open(_INDEX_PATH, "w", encoding="utf-8") as handle:
        json.dump(_sort_entries(entries), handle, ensure_ascii=True, indent=2)


def _entry_path(name):
    return os.path.join(_HISTORY_DIR, name)


def _trim_history(entries):
    if len(entries) <= _MAX_HISTORY_ITEMS:
        return entries
    keep = entries[:_MAX_HISTORY_ITEMS]
    to_delete = entries[_MAX_HISTORY_ITEMS:]
    for entry in to_delete:
        for key in ("ppt_file", "trace_file"):
            path = _entry_path(_safe_text(entry.get(key)))
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
    return keep


def load_presentation_history():
    return _read_index()


def save_presentation_run(topic, download_name, ppt_bytes, trace_data, run_meta=None):
    _ensure_history_dir()
    run_meta = run_meta if isinstance(run_meta, dict) else {}

    created_at = datetime.now(timezone.utc).isoformat()
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"
    ppt_file = f"{run_id}.pptx"
    trace_file = f"{run_id}.trace.json"

    with open(_entry_path(ppt_file), "wb") as handle:
        handle.write(ppt_bytes or b"")

    trace_payload = {
        "topic": _safe_text(topic),
        "created_at": created_at,
        "meta": run_meta,
        "trace": trace_data if isinstance(trace_data, dict) else {},
    }
    with open(_entry_path(trace_file), "w", encoding="utf-8") as handle:
        json.dump(trace_payload, handle, ensure_ascii=True, indent=2)

    entry = {
        "id": run_id,
        "created_at": created_at,
        "topic": _safe_text(topic),
        "download_name": _safe_text(download_name),
        "ppt_file": ppt_file,
        "trace_file": trace_file,
        "provider": _safe_text(run_meta.get("provider")),
        "model": _safe_text(run_meta.get("model")),
        "content_slide_count": int(run_meta.get("content_slide_count") or 0),
        "size_bytes": int(len(ppt_bytes or b"")),
    }

    entries = _read_index()
    entries.insert(0, entry)
    entries = _trim_history(_sort_entries(entries))
    _write_index(entries)
    return entry


def read_presentation_bytes(entry):
    path = _entry_path(_safe_text((entry or {}).get("ppt_file")))
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except Exception:
        return None


def read_presentation_trace(entry):
    path = _entry_path(_safe_text((entry or {}).get("trace_file")))
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except Exception:
        return None
