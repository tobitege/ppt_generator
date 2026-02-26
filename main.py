import streamlit as st
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
import re
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue

from llm_profile_store import DEFAULT_PROFILES, ensure_profiles, save_profiles
from presentation_history_store import (
    load_presentation_history,
    read_presentation_bytes,
    save_presentation_run,
)
from ppt_data_gen import slide_data_gen
from ppt_gen import ppt_gen
from secure_key_store import (
    delete_api_key_for_profile,
    get_api_key_for_profile,
    set_api_key_for_profile,
)

st.set_page_config(page_title="ppt generator", page_icon=":bar_chart:", layout="wide")

PROVIDER_LABELS = {
    "LM Studio": "lm_studio",
    "Ollama": "ollama",
    "OpenAI-compatible": "openai_compat",
}

PROFILE_TEMPLATE_NAMES = sorted(DEFAULT_PROFILES.keys())
PROVIDER_NAME_OPTIONS = ["LM Studio", "Ollama", "OpenAI", "OpenRouter", "Anthropic", "Custom"]


def provider_to_label(provider):
    for label, value in PROVIDER_LABELS.items():
        if value == provider:
            return label
    return "OpenAI-compatible"


def default_provider_name(provider, provider_label):
    if provider == "lm_studio":
        return "LM Studio"
    if provider == "ollama":
        return "Ollama"
    if provider_label:
        return provider_label
    return "OpenAI-compatible"


def provider_defaults(provider):
    for _, cfg in DEFAULT_PROFILES.items():
        if cfg["provider"] == provider:
            return cfg
    return DEFAULT_PROFILES["LM Studio Local"]


def normalize_base_url(base_url):
    value = (base_url or "").strip().rstrip("/")
    if not value:
        return value
    if not value.endswith("/v1"):
        return f"{value}/v1"
    return value


def build_ppt_filename_from_topic(topic, max_length=100):
    ext = ".pptx"
    max_length = max(int(max_length), len(ext) + 1)

    value = str(topic or "").strip()
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1F]", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    value = value.replace(" ", "_")
    value = re.sub(r"_+", "_", value).strip("_.")

    if not value:
        value = "presentation"

    reserved = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    }
    if value.upper() in reserved or value.split(".", 1)[0].upper() in reserved:
        value = f"_{value}"

    stem_max = max_length - len(ext)
    value = value[:stem_max].rstrip(" ._")
    if not value:
        value = "presentation"
    if value.upper() in reserved or value.split(".", 1)[0].upper() in reserved:
        value = f"_{value}"

    return f"{value}{ext}"


def _format_history_timestamp(iso_value):
    value = str(iso_value or "").strip()
    if not value:
        return ""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = time.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
        return time.strftime("%Y-%m-%d %H:%M:%S", parsed)
    except Exception:
        return str(iso_value)


def render_presentation_history():
    history = st.session_state.get("presentation_history", [])
    st.subheader("Presentation History")
    if not history:
        st.caption("No presentations generated yet.")
        return

    for entry in history:
        run_id = str(entry.get("id") or "")
        topic = str(entry.get("topic") or "(untitled topic)")
        provider = str(entry.get("provider") or "")
        model = str(entry.get("model") or "")
        created_at = _format_history_timestamp(entry.get("created_at"))
        slide_count = int(entry.get("content_slide_count") or 0)
        download_name = str(entry.get("download_name") or "presentation.pptx")

        with st.expander(f"{topic} ({created_at})", expanded=False):
            details = [x for x in [provider, model] if x]
            if slide_count > 0:
                details.append(f"{slide_count} content slides")
            if details:
                st.caption(" | ".join(details))

            ppt_bytes = read_presentation_bytes(entry)
            if ppt_bytes:
                st.download_button(
                    "Download Presentation",
                    data=ppt_bytes,
                    file_name=download_name,
                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    key=f"history_ppt_{run_id}",
                )
            else:
                st.warning("Stored PPT file is missing.")


def fetch_available_models(base_url, api_key):
    resolved_base_url = normalize_base_url(base_url)
    resolved_api_key = (api_key or "").strip() or "not-needed"

    if "api.openai.com" in resolved_base_url and resolved_api_key == "not-needed":
        raise RuntimeError("API key is required for api.openai.com.")

    try:
        client = OpenAI(
            api_key=resolved_api_key,
            base_url=resolved_base_url,
            timeout=30,
            max_retries=0,
        )
        response = client.models.list()
        return sorted([item.id for item in response.data if getattr(item, "id", None)])
    except (APITimeoutError, APIConnectionError) as exc:
        raise RuntimeError("Model list request timed out or could not connect.") from exc
    except APIStatusError as exc:
        detail = ""
        response = getattr(exc, "response", None)
        if response is not None:
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    error = payload.get("error")
                    if isinstance(error, dict):
                        detail = str(error.get("message") or error.get("code") or "").strip()
                    elif isinstance(error, str):
                        detail = error.strip()
                    if not detail:
                        detail = str(payload.get("message") or payload.get("detail") or "").strip()
            except Exception:
                pass
            if not detail:
                try:
                    detail = str((response.text or "").strip())[:300]
                except Exception:
                    detail = ""
        suffix = f" detail={detail}" if detail else ""
        raise RuntimeError(f"Model list request failed with HTTP {exc.status_code}.{suffix}") from exc


def apply_profile(profile_name, profile_data):
    st.session_state.llm_provider = profile_data["provider"]
    st.session_state.llm_provider_label = provider_to_label(profile_data["provider"])
    st.session_state.llm_provider_name = profile_data.get("provider_name", profile_name)
    st.session_state.llm_model = profile_data["model"]
    st.session_state.llm_base_url = profile_data["base_url"]
    st.session_state.llm_temperature = float(profile_data["temperature"])
    st.session_state.llm_timeout_seconds = int(profile_data["timeout_seconds"])
    st.session_state.llm_retries = int(profile_data["retries"])
    st.session_state.llm_retry_delay_seconds = float(profile_data["retry_delay_seconds"])
    st.session_state.llm_request_delay_seconds = float(profile_data["request_delay_seconds"])
    st.session_state.available_models = []
    st.session_state.profile_name_input = profile_name
    try:
        st.session_state.llm_api_key = get_api_key_for_profile(profile_name)
        st.session_state.key_store_status = ""
    except RuntimeError as exc:
        st.session_state.llm_api_key = ""
        st.session_state.key_store_status = str(exc)
    st.session_state.last_loaded_profile_name = profile_name


def collect_profile_from_fields():
    provider = st.session_state.llm_provider
    provider_label = provider_to_label(provider)
    provider_name = (st.session_state.llm_provider_name or "").strip()
    return {
        "provider_name": provider_name or default_provider_name(provider, provider_label),
        "provider": provider,
        "base_url": normalize_base_url(st.session_state.llm_base_url),
        "model": st.session_state.llm_model.strip(),
        "temperature": float(st.session_state.llm_temperature),
        "timeout_seconds": int(st.session_state.llm_timeout_seconds),
        "retries": int(st.session_state.llm_retries),
        "retry_delay_seconds": float(st.session_state.llm_retry_delay_seconds),
        "request_delay_seconds": float(st.session_state.llm_request_delay_seconds),
    }


def persist_api_key_for_active_profile():
    profile_name = st.session_state.active_profile_name
    api_key = (st.session_state.llm_api_key or "").strip()
    try:
        if api_key:
            set_api_key_for_profile(profile_name, api_key)
            st.session_state.key_store_status = f"API key stored encrypted for profile '{profile_name}'."
        else:
            delete_api_key_for_profile(profile_name)
            st.session_state.key_store_status = f"Stored API key cleared for profile '{profile_name}'."
    except RuntimeError as exc:
        st.session_state.key_store_status = str(exc)


def on_api_key_changed():
    persist_api_key_for_active_profile()


def activate_profile_for_next_run(profile_name):
    st.session_state.active_profile_name = profile_name
    st.session_state.last_loaded_profile_name = ""


def reset_editor_for_new_profile():
    st.session_state.profile_name_input = ""
    st.session_state.llm_provider = "openai_compat"
    st.session_state.llm_provider_label = provider_to_label("openai_compat")
    st.session_state.llm_provider_name = ""
    st.session_state.llm_model = ""
    st.session_state.llm_base_url = ""
    st.session_state.llm_api_key = ""
    st.session_state.llm_temperature = 0.4
    st.session_state.llm_timeout_seconds = 180
    st.session_state.llm_retries = 2
    st.session_state.llm_retry_delay_seconds = 1.5
    st.session_state.llm_request_delay_seconds = 0.75
    st.session_state.available_models = []
    st.session_state.key_store_status = ""
    st.session_state.editor_mode = "new"
    st.session_state.confirm_delete = False
    st.session_state.confirm_delete_from_list = False


def compact_divider():
    st.markdown(
        "<hr style='margin:0.5rem 0; border:none; border-top:1px solid rgba(128,128,128,0.35);'>",
        unsafe_allow_html=True,
    )


def inject_ui_styles():
    st.markdown(
        """
<style>
html, body, [data-testid="stAppViewContainer"] {
    overflow-y: scroll !important;
    scrollbar-gutter: stable;
}

[data-baseweb="popover"] {
    border-radius: 10px !important;
}

[role="listbox"] {
    border: 2px solid #8aa4ff !important;
    box-shadow: 0 14px 30px rgba(0, 0, 0, 0.48), 0 0 0 1px rgba(138, 164, 255, 0.35) inset !important;
    background: #0f172a !important;
    border-radius: 10px !important;
}

[role="listbox"] [role="option"] {
    background: #0f172a !important;
}

[role="listbox"] [role="option"][aria-selected="true"] {
    background: rgba(138, 164, 255, 0.24) !important;
}

[role="listbox"] [role="option"]:hover {
    background: rgba(138, 164, 255, 0.14) !important;
}

.generation-timer {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.35rem;
    margin-top: 0.35rem;
    font-size: 0.82rem;
    color: rgba(240, 245, 255, 0.92);
}

.generation-watch {
    display: inline-flex;
    animation: watchPulse 1.3s ease-in-out infinite;
    transform-origin: center;
}

@keyframes watchPulse {
    0% { opacity: 0.55; transform: scale(0.95); }
    50% { opacity: 1; transform: scale(1.08); }
    100% { opacity: 0.55; transform: scale(0.95); }
}
</style>
""",
        unsafe_allow_html=True,
    )


def render_generation_timer(target, started_at):
    elapsed_seconds = max(0, int(time.monotonic() - started_at))
    minutes, seconds = divmod(elapsed_seconds, 60)
    target.markdown(
        (
            f'<div class="generation-timer">'
            f'<span class="generation-watch">⌚</span>'
            f'<span>{minutes:02d}:{seconds:02d}</span>'
            f"</div>"
        ),
        unsafe_allow_html=True,
    )


def init_state():
    if "profiles" not in st.session_state:
        st.session_state.profiles = ensure_profiles()
    if not st.session_state.profiles:
        st.session_state.profiles = dict(DEFAULT_PROFILES)
        save_profiles(st.session_state.profiles)

    profile_names = sorted(st.session_state.profiles.keys())
    if "active_profile_name" not in st.session_state or st.session_state.active_profile_name not in st.session_state.profiles:
        st.session_state.active_profile_name = profile_names[0]
    if "profile_name_input" not in st.session_state:
        st.session_state.profile_name_input = st.session_state.active_profile_name
    if "available_models" not in st.session_state:
        st.session_state.available_models = []
    if "pending_model_name" not in st.session_state:
        st.session_state.pending_model_name = ""
    if "profile_template_name" not in st.session_state:
        st.session_state.profile_template_name = PROFILE_TEMPLATE_NAMES[0]
    if "show_profile_editor" not in st.session_state:
        st.session_state.show_profile_editor = False
    if "profile_details_expanded" not in st.session_state:
        st.session_state.profile_details_expanded = False
    if "editor_mode" not in st.session_state:
        st.session_state.editor_mode = "edit"
    if "confirm_delete" not in st.session_state:
        st.session_state.confirm_delete = False
    if "confirm_delete_from_list" not in st.session_state:
        st.session_state.confirm_delete_from_list = False
    if "key_store_status" not in st.session_state:
        st.session_state.key_store_status = ""
    if "last_loaded_profile_name" not in st.session_state:
        st.session_state.last_loaded_profile_name = ""
    if "presentation_history" not in st.session_state:
        st.session_state.presentation_history = load_presentation_history()

    if st.session_state.last_loaded_profile_name != st.session_state.active_profile_name:
        apply_profile(
            st.session_state.active_profile_name,
            st.session_state.profiles[st.session_state.active_profile_name],
        )


init_state()

# Apply deferred model picks before widgets using `llm_model` are instantiated.
if st.session_state.pending_model_name:
    st.session_state.llm_model = st.session_state.pending_model_name
    st.session_state.pending_model_name = ""

st.title("PPT Generator")
st.caption("Generation can take a few minutes because multiple model calls are made per presentation.")
inject_ui_styles()

st.sidebar.header("Configuration")
profile_names = sorted(st.session_state.profiles.keys())
active_profile_name = st.session_state.active_profile_name
if active_profile_name not in profile_names:
    active_profile_name = profile_names[0]
    st.session_state.active_profile_name = active_profile_name
selected_profile = st.sidebar.selectbox(
    "Model profile",
    profile_names,
    index=profile_names.index(active_profile_name),
    help="This is the profile used when you click Generate.",
)
if selected_profile != st.session_state.active_profile_name:
    st.session_state.active_profile_name = selected_profile
    apply_profile(selected_profile, st.session_state.profiles[selected_profile])
    st.session_state.editor_mode = "edit"
    st.session_state.confirm_delete = False
    st.session_state.confirm_delete_from_list = False

with st.sidebar.expander("Profiles", expanded=False):
    st.caption("Select a profile to edit, or add a new one.")
    for row_start in range(0, len(profile_names), 2):
        row = st.columns(2)
        for col_index in range(2):
            idx = row_start + col_index
            if idx >= len(profile_names):
                continue
            name = profile_names[idx]
            is_selected = name == st.session_state.active_profile_name
            button_type = "primary" if is_selected else "secondary"
            if row[col_index].button(
                name,
                key=f"profile_pill_{name}",
                use_container_width=True,
                type=button_type,
            ):
                st.session_state.active_profile_name = name
                apply_profile(name, st.session_state.profiles[name])
                st.session_state.show_profile_editor = True
                st.session_state.profile_details_expanded = True
                st.session_state.editor_mode = "edit"
                st.session_state.confirm_delete = False
                st.session_state.confirm_delete_from_list = False
                st.rerun()

    compact_divider()
    if st.button("Add Profile", type="primary", use_container_width=True):
        reset_editor_for_new_profile()
        st.session_state.show_profile_editor = True
        st.session_state.profile_details_expanded = True
        st.info("Fill out the empty form and save a new profile.")
    st.caption(f"Selected: {st.session_state.active_profile_name}")
    profile_action_col_1, profile_action_col_2 = st.columns(2)
    if profile_action_col_1.button("Edit profile", use_container_width=True):
        selected_name = st.session_state.active_profile_name
        apply_profile(selected_name, st.session_state.profiles[selected_name])
        st.session_state.show_profile_editor = True
        st.session_state.profile_details_expanded = True
        st.session_state.editor_mode = "edit"
        st.session_state.confirm_delete = False
        st.session_state.confirm_delete_from_list = False
        st.rerun()
    if profile_action_col_2.button("Delete selected", use_container_width=True):
        st.session_state.confirm_delete_from_list = True
        st.session_state.confirm_delete = False

    if st.session_state.confirm_delete_from_list:
        st.warning(f"Delete profile '{st.session_state.active_profile_name}' permanently?")
        confirm_col, cancel_col = st.columns(2)
        if confirm_col.button("Confirm delete selected", type="primary", use_container_width=True):
            name = st.session_state.active_profile_name
            if len(st.session_state.profiles) <= 1:
                st.warning("At least one profile is required.")
            else:
                st.session_state.profiles.pop(name, None)
                save_profiles(st.session_state.profiles)
                try:
                    delete_api_key_for_profile(name)
                except RuntimeError as exc:
                    st.session_state.key_store_status = str(exc)
                next_name = sorted(st.session_state.profiles.keys())[0]
                activate_profile_for_next_run(next_name)
                st.session_state.confirm_delete_from_list = False
                st.session_state.show_profile_editor = False
                st.session_state.profile_details_expanded = False
                st.success(f"Deleted profile '{name}'.")
                st.rerun()
        if cancel_col.button("Cancel delete selected", use_container_width=True):
            st.session_state.confirm_delete_from_list = False
            st.rerun()

if st.session_state.show_profile_editor:
    with st.sidebar.expander("Profile Details", expanded=st.session_state.profile_details_expanded):
        if st.session_state.editor_mode == "new":
            st.caption("Create a new profile from an empty form.")
        else:
            st.caption(f"Editing profile: {st.session_state.active_profile_name}")
        st.text_input("Save as profile name", key="profile_name_input")
        known_provider_names = PROVIDER_NAME_OPTIONS[:-1]
        current_provider_name = (st.session_state.get("llm_provider_name") or "").strip()
        if current_provider_name in known_provider_names:
            provider_index = PROVIDER_NAME_OPTIONS.index(current_provider_name)
        else:
            provider_index = PROVIDER_NAME_OPTIONS.index("Custom")

        selected_provider_name = st.selectbox(
            "Provider",
            PROVIDER_NAME_OPTIONS,
            index=provider_index,
            key="llm_provider_name_select",
        )
        if selected_provider_name == "Custom":
            custom_default = current_provider_name if current_provider_name not in known_provider_names else ""
            custom_provider_name = st.text_input(
                "Custom provider name",
                value=custom_default,
                key="llm_provider_name_custom",
            )
            st.session_state.llm_provider_name = custom_provider_name.strip()
        else:
            st.session_state.llm_provider_name = selected_provider_name

        model_options = list(st.session_state.available_models)
        if st.session_state.llm_model not in model_options:
            model_options = [st.session_state.llm_model] + model_options
        model_options = [option for option in model_options if option is not None]
        if not model_options:
            model_options = [""]
        selected_model_index = 0
        if st.session_state.llm_model in model_options:
            selected_model_index = model_options.index(st.session_state.llm_model)
        st.selectbox(
            "Model",
            options=model_options,
            index=selected_model_index,
            key="llm_model",
            accept_new_options=True,
            placeholder="Type model name or pick from fetched models",
        )

        if st.button("Fetch models", use_container_width=True):
            persist_api_key_for_active_profile()
            try:
                st.session_state.available_models = fetch_available_models(
                    st.session_state.llm_base_url,
                    st.session_state.llm_api_key,
                )
                st.rerun()
            except Exception as exc:
                st.warning(str(exc))
                st.session_state.available_models = []

        provider_names = list(PROVIDER_LABELS.keys())
        canonical_provider_label = provider_to_label(st.session_state.llm_provider)
        if st.session_state.get("llm_provider_label") != canonical_provider_label:
            st.session_state.llm_provider_label = canonical_provider_label
        selected_label = st.selectbox("Provider protocol", provider_names, key="llm_provider_label")
        selected_provider = PROVIDER_LABELS[selected_label]
        if selected_provider != st.session_state.llm_provider:
            st.session_state.llm_provider = selected_provider
            defaults = provider_defaults(selected_provider)
            st.session_state.llm_base_url = defaults["base_url"]
            st.session_state.pending_model_name = defaults["model"]
            st.session_state.available_models = []
            st.rerun()

        st.text_input("Base API URL", key="llm_base_url")
        st.number_input(
            "LLM response timeout (seconds)",
            min_value=10,
            max_value=3600,
            step=10,
            key="llm_timeout_seconds",
        )
        if st.session_state.llm_provider in {"lm_studio", "ollama"}:
            st.caption("Local provider selected: first reply can use up to 2x this timeout.")
        st.text_input(
            "API key (encrypted per profile)",
            type="password",
            key="llm_api_key",
            on_change=on_api_key_changed,
        )
        if st.button("Clear API key", use_container_width=True):
            st.session_state.llm_api_key = ""
            persist_api_key_for_active_profile()

        with st.expander("Templates", expanded=False):
            st.selectbox(
                "Template",
                PROFILE_TEMPLATE_NAMES,
                key="profile_template_name",
                help="Applies preset values into the current editor fields.",
            )
            if st.button("Use protocol defaults", use_container_width=True):
                defaults = provider_defaults(st.session_state.llm_provider)
                st.session_state.llm_provider_name = default_provider_name(
                    st.session_state.llm_provider,
                    provider_to_label(st.session_state.llm_provider),
                )
                st.session_state.llm_base_url = defaults["base_url"]
                st.session_state.pending_model_name = defaults["model"]
                st.rerun()
            if st.button("Apply template", use_container_width=True):
                template_name = st.session_state.profile_template_name
                template_data = DEFAULT_PROFILES[template_name]
                st.session_state.llm_provider = template_data["provider"]
                st.session_state.llm_provider_name = template_data.get("provider_name", template_name)
                st.session_state.pending_model_name = template_data["model"]
                st.session_state.llm_base_url = template_data["base_url"]
                st.session_state.llm_temperature = float(template_data["temperature"])
                st.session_state.llm_timeout_seconds = int(template_data["timeout_seconds"])
                st.session_state.llm_retries = int(template_data["retries"])
                st.session_state.llm_retry_delay_seconds = float(template_data["retry_delay_seconds"])
                st.session_state.llm_request_delay_seconds = float(template_data["request_delay_seconds"])
                st.session_state.available_models = []
                st.success(f"Template '{template_name}' applied.")
                st.rerun()

        with st.expander("Request Tuning", expanded=False):
            st.number_input("Temperature", min_value=0.0, max_value=2.0, step=0.1, key="llm_temperature")
            st.number_input("Retries", min_value=0, max_value=10, step=1, key="llm_retries")
            st.number_input("Retry delay (seconds)", min_value=0.0, max_value=30.0, step=0.5, key="llm_retry_delay_seconds")
            st.number_input("Request delay (seconds)", min_value=0.0, max_value=30.0, step=0.1, key="llm_request_delay_seconds")

        save_col, delete_col, close_col = st.columns(3)
        if save_col.button("Save", use_container_width=True):
            name = (st.session_state.profile_name_input or "").strip()
            if not name:
                st.warning("Profile name cannot be empty.")
            else:
                st.session_state.profiles[name] = collect_profile_from_fields()
                save_profiles(st.session_state.profiles)
                st.session_state.active_profile_name = name
                persist_api_key_for_active_profile()
                st.session_state.last_loaded_profile_name = name
                st.session_state.editor_mode = "edit"
                st.session_state.confirm_delete = False
                st.session_state.confirm_delete_from_list = False
                st.success(f"Saved profile '{name}'.")
                st.rerun()

        delete_disabled = st.session_state.editor_mode == "new"
        if delete_col.button("Delete", use_container_width=True, disabled=delete_disabled):
            st.session_state.confirm_delete = True

        if close_col.button("Close", use_container_width=True):
            st.session_state.show_profile_editor = False
            st.session_state.profile_details_expanded = False
            st.session_state.confirm_delete = False
            st.session_state.confirm_delete_from_list = False
            st.rerun()

        if st.session_state.confirm_delete and st.session_state.editor_mode != "new":
            st.warning(f"Delete profile '{st.session_state.active_profile_name}' permanently?")
            confirm_col, cancel_col = st.columns(2)
            if confirm_col.button("Confirm delete", type="primary", use_container_width=True):
                name = st.session_state.active_profile_name
                if len(st.session_state.profiles) <= 1:
                    st.warning("At least one profile is required.")
                else:
                    st.session_state.profiles.pop(name, None)
                    save_profiles(st.session_state.profiles)
                    try:
                        delete_api_key_for_profile(name)
                    except RuntimeError as exc:
                        st.session_state.key_store_status = str(exc)
                    next_name = sorted(st.session_state.profiles.keys())[0]
                    activate_profile_for_next_run(next_name)
                    st.session_state.confirm_delete = False
                    st.session_state.confirm_delete_from_list = False
                    st.session_state.show_profile_editor = False
                    st.session_state.profile_details_expanded = False
                    st.success(f"Deleted profile '{name}'.")
                    st.rerun()
            if cancel_col.button("Cancel", use_container_width=True):
                st.session_state.confirm_delete = False
                st.rerun()

        if st.session_state.key_store_status:
            st.caption(st.session_state.key_store_status)
else:
    st.sidebar.caption("Open 'Profiles' and click a profile or 'Add Profile' to edit details.")

api_key_state = "set" if (st.session_state.llm_api_key or "").strip() else "not set"
st.sidebar.caption(
    f"Active: {st.session_state.active_profile_name} | "
    f"{st.session_state.llm_provider_name} | "
    f"{normalize_base_url(st.session_state.llm_base_url)} | API key {api_key_state}"
)

with st.form("generate_form", clear_on_submit=False):
    topic = st.text_input("Enter a topic:")
    content_slide_count = st.number_input(
        "Number of content slides",
        min_value=1,
        max_value=20,
        value=7,
        step=1,
        help="This count excludes title, overview, and thank-you slides.",
    )
    extra_instructions = st.text_area(
        "Extra instructions (optional)",
        placeholder="e.g. Keep it technical, focus on risks, max 2 bullets per slide.",
    )
    submitted = st.form_submit_button("Generate")

progress_message = st.empty()
progress_bar = st.empty()
progress_timer = st.empty()

if submitted:
    if not topic.strip():
        progress_timer.empty()
        st.warning("Please enter a topic.")
    else:
        try:
            progress_message.info("Generating...")
            progress = progress_bar.progress(0)
            generation_started_at = time.monotonic()
            render_generation_timer(progress_timer, generation_started_at)

            persist_api_key_for_active_profile()
            llm_config = {
                "provider": st.session_state.llm_provider,
                "base_url": st.session_state.llm_base_url.strip(),
                "model": st.session_state.llm_model.strip(),
                "api_key": st.session_state.llm_api_key.strip(),
                "temperature": float(st.session_state.llm_temperature),
                "timeout_seconds": int(st.session_state.llm_timeout_seconds),
                "retries": int(st.session_state.llm_retries),
                "retry_delay_seconds": float(st.session_state.llm_retry_delay_seconds),
                "request_delay_seconds": float(st.session_state.llm_request_delay_seconds),
            }

            progress_events = Queue()

            def queue_progress(message, value=None):
                progress_events.put((message, value))

            def run_generation():
                data = slide_data_gen(
                    topic,
                    slide_count=int(content_slide_count),
                    extra_instructions=extra_instructions,
                    llm_config=llm_config,
                    progress_callback=queue_progress,
                )
                queue_progress("Building PPTX file...", 0.98)
                return data, ppt_gen(data)

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(run_generation)
                while not future.done():
                    while True:
                        try:
                            message, value = progress_events.get_nowait()
                        except Empty:
                            break
                        if message:
                            progress_message.info(message)
                        if value is not None:
                            progress.progress(min(max(value, 0.0), 1.0))
                    render_generation_timer(progress_timer, generation_started_at)
                    time.sleep(0.2)

                while True:
                    try:
                        message, value = progress_events.get_nowait()
                    except Empty:
                        break
                    if message:
                        progress_message.info(message)
                    if value is not None:
                        progress.progress(min(max(value, 0.0), 1.0))
                generated_data, ppt_file = future.result()

            progress.progress(1.0)
            render_generation_timer(progress_timer, generation_started_at)
            progress_message.success("Presentation is ready.")
        except Exception as exc:
            progress_bar.empty()
            progress_timer.empty()
            progress_message.error(str(exc))
            st.info(
                "Check the profile + LLM settings in the sidebar (provider, model, base URL, API key)."
            )
        else:
            file_name = build_ppt_filename_from_topic(topic, max_length=100)
            ppt_bytes = ppt_file.getvalue() if hasattr(ppt_file, "getvalue") else bytes(ppt_file)
            safe_meta = {
                "provider": llm_config.get("provider", ""),
                "base_url": llm_config.get("base_url", ""),
                "model": llm_config.get("model", ""),
                "temperature": llm_config.get("temperature", 0.4),
                "timeout_seconds": llm_config.get("timeout_seconds", 180),
                "retries": llm_config.get("retries", 2),
                "retry_delay_seconds": llm_config.get("retry_delay_seconds", 1.5),
                "request_delay_seconds": llm_config.get("request_delay_seconds", 0.0),
                "content_slide_count": int(content_slide_count),
                "extra_instructions": str(extra_instructions or ""),
            }
            history_error = ""
            try:
                save_presentation_run(
                    topic=topic,
                    download_name=file_name,
                    ppt_bytes=ppt_bytes,
                    trace_data=(generated_data or {}).get("trace", {}),
                    run_meta=safe_meta,
                )
                st.session_state.presentation_history = load_presentation_history()
            except Exception as exc:
                history_error = str(exc)
            st.download_button(
                label="Download Presentation",
                data=ppt_bytes,
                file_name=file_name,
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
            if history_error:
                st.warning(f"Presentation generated, but history save failed: {history_error}")
            else:
                st.caption("Saved to Presentation History.")

render_presentation_history()
