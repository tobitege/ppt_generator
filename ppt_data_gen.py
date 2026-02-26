import json
import os
import re
import time

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI


def extract_items(input_string):
    if not input_string:
        return []

    # Strip leaked reasoning blocks first so we do not parse format examples
    # from inside <think>...</think>.
    cleaned_input = re.sub(r"<think>[\s\S]*?</think>", "", input_string, flags=re.IGNORECASE)

    # Find all << >> blocks and prefer the last one.
    matches = re.findall(r"<<([\s\S]+?)>>", cleaned_input)
    if not matches:
        return []
    content = matches[-1]

    # Split the content by the | separator and remove whitespace
    items = [item.strip() for item in content.split('|')]

    # Remove the quotes from each item
    items = [re.sub(r'^"|"$', '', item) for item in items]

    return items


def build_extra_instruction_block(extra_instructions):
    text = (extra_instructions or "").strip()
    if not text:
        return ""
    return f"""

    Additional user instructions (must be respected):
    {text}
    """


def build_extra_instruction_system_message(extra_instructions):
    text = (extra_instructions or "").strip()
    if not text:
        return ""
    return (
        "You must follow these additional user instructions for every response in this request.\n"
        "Priority order:\n"
        "1) Required output format constraints in the prompt\n"
        "2) Additional user instructions (style, voice, wording constraints)\n"
        "3) Default behavior\n\n"
        "Do not ignore the additional user instructions.\n\n"
        "Additional user instructions:\n"
        f"{text}"
    )


def extract_json_object(text):
    if not text:
        return {}
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?", "", candidate, flags=re.IGNORECASE).strip()
        candidate = re.sub(r"```$", "", candidate).strip()

    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return {}
    return {}


def normalize_hex_color(value):
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", text):
        return text.upper()
    return ""


def sanitize_style_guide(raw):
    if not isinstance(raw, dict):
        return {}
    style = {
        "theme_name": str(raw.get("theme_name") or "").strip(),
        "background_color": normalize_hex_color(raw.get("background_color")),
        "title_color": normalize_hex_color(raw.get("title_color")),
        "body_color": normalize_hex_color(raw.get("body_color")),
        "accent_color": normalize_hex_color(raw.get("accent_color")),
        "font_title": str(raw.get("font_title") or "").strip(),
        "font_body": str(raw.get("font_body") or "").strip(),
    }
    return {k: v for k, v in style.items() if v}


def generate_style_guide(topic, extra_instructions, llm_call):
    text = (extra_instructions or "").strip()
    if not text:
        return {}

    raw = llm_call(f"""
    You are a presentation style extraction model.

    Read the user's style instructions and convert them into a compact JSON object.
    Return JSON only, no markdown and no commentary.

    Topic: "{topic}"
    User style instructions:
    {text}

    Allowed JSON keys:
    - theme_name (string)
    - background_color (hex #RRGGBB)
    - title_color (hex #RRGGBB)
    - body_color (hex #RRGGBB)
    - accent_color (hex #RRGGBB)
    - font_title (string, common office font)
    - font_body (string, common office font)

    If a value is unknown, omit that key.
    """)

    return sanitize_style_guide(extract_json_object(raw))


def provider_defaults(provider):
    defaults = {
        "lm_studio": {
            "base_url": "http://127.0.0.1:1234/v1",
            "model": "dolphin-2.1-mistral-7b",
        },
        "ollama": {
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "dolphin2.1-mistral",
        },
        "openai_compat": {
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
        },
    }
    return defaults.get(provider, defaults["lm_studio"])


def normalize_base_url(base_url):
    value = (base_url or "").strip().rstrip("/")
    if not value:
        return value
    if not value.endswith("/v1"):
        return f"{value}/v1"
    return value


def api_error_detail(exc):
    response = getattr(exc, "response", None)
    if response is None:
        return ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = error.get("message") or error.get("code") or ""
                if message:
                    return str(message).strip()
            if isinstance(error, str) and error.strip():
                return error.strip()
            message = payload.get("message") or payload.get("detail") or ""
            if isinstance(message, str) and message.strip():
                return message.strip()
    except Exception:
        pass
    try:
        text = (response.text or "").strip()
        if text:
            return text[:400]
    except Exception:
        pass
    return ""


def provider_specific_hint(status_code, llm_config):
    if status_code == 404 and "openrouter.ai" in llm_config["base_url"]:
        return (
            " OpenRouter hint: this usually means the selected model is currently unavailable "
            "for your account/provider route. Try another fetched model (or `openrouter/auto`)."
        )
    return ""


def resolve_llm_config(user_config=None):
    config = user_config or {}

    provider = str(config.get("provider") or os.getenv("PPT_LLM_PROVIDER", "lm_studio")).strip().lower()
    if provider == "lmstudio":
        provider = "lm_studio"
    if provider not in {"lm_studio", "ollama", "openai_compat"}:
        raise ValueError("Unsupported provider. Use 'lm_studio', 'ollama', or 'openai_compat'.")

    defaults = provider_defaults(provider)

    if provider == "ollama":
        base_url = (
            config.get("base_url")
            or os.getenv("PPT_OLLAMA_BASE_URL")
            or os.getenv("PPT_LLM_BASE_URL")
            or defaults["base_url"]
        )
        model = (
            config.get("model")
            or os.getenv("PPT_OLLAMA_MODEL")
            or os.getenv("PPT_LLM_MODEL")
            or defaults["model"]
        )
        temperature = float(
            config.get("temperature")
            or os.getenv("PPT_OLLAMA_TEMPERATURE")
            or os.getenv("PPT_LLM_TEMPERATURE")
            or "0.4"
        )
    else:
        base_url = config.get("base_url") or os.getenv("PPT_LLM_BASE_URL") or defaults["base_url"]
        model = config.get("model") or os.getenv("PPT_LLM_MODEL") or defaults["model"]
        temperature = float(config.get("temperature") or os.getenv("PPT_LLM_TEMPERATURE", "0.4"))

    timeout_seconds = int(config.get("timeout_seconds") or os.getenv("PPT_LLM_TIMEOUT_SECONDS", "180"))
    retries = int(config.get("retries") or os.getenv("PPT_LLM_RETRIES", "2"))
    retry_delay_seconds = float(config.get("retry_delay_seconds") or os.getenv("PPT_LLM_RETRY_DELAY_SECONDS", "1.5"))
    request_delay_seconds = float(config.get("request_delay_seconds") or os.getenv("PPT_REQUEST_DELAY_SECONDS", "0"))

    api_key = (
        config.get("api_key")
        or os.getenv("PPT_LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or "not-needed"
    )

    normalized_base_url = normalize_base_url(base_url)
    if not normalized_base_url:
        raise RuntimeError("Base API URL is empty. Please provide a valid base URL.")

    if "api.openai.com" in normalized_base_url and api_key == "not-needed":
        raise RuntimeError("OpenAI API key is required for api.openai.com.")

    return {
        "provider": provider,
        "base_url": normalized_base_url,
        "model": model,
        "api_key": api_key,
        "temperature": temperature,
        "timeout_seconds": timeout_seconds,
        "retries": retries,
        "retry_delay_seconds": retry_delay_seconds,
        "request_delay_seconds": request_delay_seconds,
    }


def call_openai_compatible(prompt, llm_config, extra_instructions="", timeout_seconds_override=None):
    for attempt in range(llm_config["retries"] + 1):
        try:
            messages = []
            extra_system_message = build_extra_instruction_system_message(extra_instructions)
            if extra_system_message:
                messages.append({"role": "system", "content": extra_system_message})
            messages.append({"role": "user", "content": prompt})

            effective_timeout_seconds = int(timeout_seconds_override or llm_config["timeout_seconds"])
            client = OpenAI(
                api_key=llm_config["api_key"],
                base_url=llm_config["base_url"],
                timeout=effective_timeout_seconds,
                max_retries=0,
            )
            response = client.chat.completions.create(
                model=llm_config["model"],
                messages=messages,
                temperature=llm_config["temperature"],
            )
            content = (response.choices[0].message.content or "").strip()
            if content:
                return content
            raise RuntimeError("Model returned an empty response.")
        except (APITimeoutError, APIConnectionError) as exc:
            if attempt < llm_config["retries"]:
                time.sleep(llm_config["retry_delay_seconds"] * (attempt + 1))
                continue
            raise RuntimeError(
                f"LLM request failed (connection/timeout). provider={llm_config['provider']}, "
                f"base_url={llm_config['base_url']}, model={llm_config['model']}"
            ) from exc
        except APIStatusError as exc:
            if attempt < llm_config["retries"]:
                time.sleep(llm_config["retry_delay_seconds"] * (attempt + 1))
                continue
            detail = api_error_detail(exc)
            detail_suffix = f" detail={detail}" if detail else ""
            hint = provider_specific_hint(exc.status_code, llm_config)
            raise RuntimeError(
                f"LLM request failed with HTTP {exc.status_code}. provider={llm_config['provider']}, "
                f"base_url={llm_config['base_url']}, model={llm_config['model']}"
                f"{detail_suffix}{hint}"
            ) from exc
        except RuntimeError as exc:
            if attempt < llm_config["retries"]:
                time.sleep(llm_config["retry_delay_seconds"] * (attempt + 1))
                continue
            raise RuntimeError(
                f"LLM request failed after retries. provider={llm_config['provider']}, "
                f"base_url={llm_config['base_url']}, model={llm_config['model']}"
            ) from exc


def build_prompt_caller(user_config=None, extra_instructions=""):
    llm_config = resolve_llm_config(user_config)
    request_delay = llm_config["request_delay_seconds"]
    last_call_time = 0.0
    is_first_call = True

    def paced_call(prompt):
        nonlocal is_first_call, last_call_time
        if request_delay > 0 and last_call_time > 0:
            elapsed = time.monotonic() - last_call_time
            if elapsed < request_delay:
                time.sleep(request_delay - elapsed)
        timeout_override = None
        if is_first_call and llm_config["provider"] in {"lm_studio", "ollama"}:
            timeout_override = int(llm_config["timeout_seconds"]) * 2
        result = call_openai_compatible(
            prompt,
            llm_config,
            extra_instructions=extra_instructions,
            timeout_seconds_override=timeout_override,
        )
        is_first_call = False
        last_call_time = time.monotonic()
        return result

    return paced_call


def slide_data_gen(topic, slide_count=7, extra_instructions="", llm_config=None, progress_callback=None):
    def report(message, progress=None):
        if progress_callback is not None:
            progress_callback(message, progress)

    llm_call = build_prompt_caller(llm_config, extra_instructions=extra_instructions)

    slide_data = []
    requested_slide_count = max(int(slide_count), 1)
    extra_instruction_block = build_extra_instruction_block(extra_instructions)
    style_guide = {}

    point_count = int(os.getenv("PPT_POINT_COUNT", "5"))
    trace = {
        "topic": str(topic or ""),
        "requested_slide_count": requested_slide_count,
        "point_count": point_count,
        "llm_config": {
            key: value
            for key, value in (llm_config or {}).items()
            if key != "api_key"
        },
        "style_guide": {},
        "title_slide": {},
        "table_of_contents": {},
        "slides": [],
    }

    report("Applying style guide...", 0.02)
    style_prompt = f"""
    You are a presentation style extraction model.

    Read the user's style instructions and convert them into a compact JSON object.
    Return JSON only, no markdown and no commentary.

    Topic: "{topic}"
    User style instructions:
    {extra_instructions}

    Allowed JSON keys:
    - theme_name (string)
    - background_color (hex #RRGGBB)
    - title_color (hex #RRGGBB)
    - body_color (hex #RRGGBB)
    - accent_color (hex #RRGGBB)
    - font_title (string, common office font)
    - font_body (string, common office font)

    If a value is unknown, omit that key.
    """
    try:
        style_response = llm_call(style_prompt)
        style_guide = sanitize_style_guide(extract_json_object(style_response))
        trace["style_guide"] = {
            "prompt": style_prompt.strip(),
            "response": style_response,
            "parsed": style_guide,
            "error": "",
        }
    except Exception as exc:
        style_guide = {}
        trace["style_guide"] = {
            "prompt": style_prompt.strip(),
            "response": "",
            "parsed": {},
            "error": str(exc),
        }

    report("Generating title slide...", 0.05)
    title_prompt = f"""
    You are a text summarization and formatting specialized model that fetches relevant information

    For the topic "{topic}" suggest a presentation title and a presentation subtitle it should be returned in the format :
    << "title" | "subtitle >>
    {extra_instruction_block}

    example :
    << "Ethics in Design" | "Integrating Ethics into Design Processes" >>
    """
    title_response = llm_call(title_prompt)
    title_items = extract_items(title_response)
    trace["title_slide"] = {
        "prompt": title_prompt.strip(),
        "response": title_response,
        "parsed_items": title_items,
    }
    slide_data.append(title_items)

    report("Generating table of contents...", 0.15)
    toc_prompt = f"""
    You are a text summarization and formatting specialized model that fetches relevant information
            
    For the presentation titled "{slide_data[0][0]}" and with subtitle "{slide_data[0][1]}" for the topic "{topic}"
    Write a table of contents containing the title of each slide for a {requested_slide_count} slide presentation.
    Return EXACTLY {requested_slide_count} slide titles.
    It should be of the format :
    << "slide1" | "slide2" | "slide3" | ... | >>
    {extra_instruction_block}
            
    example :
    << "Introduction to Design Ethics" | "User-Centered Design" | "Transparency and Honesty" | "Data Privacy and Security" | "Accessibility and Inclusion" | "Social Impact and Sustainability" | "Ethical AI and Automation" | "Collaboration and Professional Ethics" >>          
    """
    toc_response = llm_call(toc_prompt)
    toc_items = extract_items(toc_response)
    trace["table_of_contents"] = {
        "prompt": toc_prompt.strip(),
        "response": toc_response,
        "parsed_items": toc_items,
    }

    subtopics = [item for item in toc_items if item]
    subtopics = subtopics[:requested_slide_count]
    while len(subtopics) < requested_slide_count:
        subtopics.append(f"{topic}: Key Point {len(subtopics) + 1}")

    slide_data.append(subtopics)

    total_subtopics = max(len(slide_data[1]), 1)
    for idx, subtopic in enumerate(slide_data[1], start=1):
        step_base = 0.15 + ((idx - 1) / total_subtopics) * 0.75
        report(f"Generating content for slide {idx}/{total_subtopics}: {subtopic}", step_base)

        direct_prompt = f"""
        You are a content generation model for presentation bullets.

        For the presentation titled "{slide_data[0][0]}" and with subtitle "{slide_data[0][1]}" for the topic "{topic}",
        write EXACTLY {point_count} bullet points for the slide subtopic "{subtopic}".
        Keep each point concise (about 10 words max unless user style instructions require otherwise).

        Return ONLY this format:
        << "point1" | "point2" | "point3" | ... | >>

        Do not add any extra text before or after this format.
        {extra_instruction_block}
        """
        direct_points = llm_call(direct_prompt)
        parsed_points = extract_items(direct_points)
        slide_trace = {
            "slide_number": idx,
            "subtopic": subtopic,
            "direct": {
                "prompt": direct_prompt.strip(),
                "response": direct_points,
                "parsed_points": parsed_points,
            },
            "fallback": None,
            "final_points": [],
        }

        if len(parsed_points) < point_count:
            report(f"Formatting slide {idx}/{total_subtopics}: {subtopic}", step_base + (0.75 / total_subtopics) * 0.5)
            fallback_prompt = f"""
            You are a content generation specialized model that fetches relevant information and presents it in clear concise manner

            For the presentation titled "{slide_data[0][0]}" and with subtitle "{slide_data[0][1]}" for the topic "{topic}"
            Write the contents for a slide with the subtopic {subtopic}
            Write {point_count} points. Each point 10 words maximum.
            Make the points short, concise and to the point.
            {extra_instruction_block}
            """
            data_to_clean = llm_call(fallback_prompt)

            cleanup_prompt = f"""
            You are a text formatting model.
            Extract exactly {point_count} bullet sentences from the draft and output them as:
            << "point1" | "point2" | "point3" | ... | >>

            Important:
            - Keep wording as close to the draft as possible.
            - Preserve user style/tone markers (punctuation, casing, symbols) whenever possible.
            - Do not add commentary.

            -- Beginning of the text --
            {data_to_clean}
            -- End of the text --
            {extra_instruction_block}
            """
            cleaned_data = llm_call(cleanup_prompt)
            parsed_points = extract_items(cleaned_data)
            slide_trace["fallback"] = {
                "generation_prompt": fallback_prompt.strip(),
                "generation_response": data_to_clean,
                "formatting_prompt": cleanup_prompt.strip(),
                "formatting_response": cleaned_data,
                "parsed_points": parsed_points,
            }

        if len(parsed_points) < point_count:
            parsed_points = parsed_points[:point_count]
            while len(parsed_points) < point_count:
                parsed_points.append(f"{subtopic} point {len(parsed_points) + 1}")
        else:
            parsed_points = parsed_points[:point_count]

        slide_trace["final_points"] = list(parsed_points)
        trace["slides"].append(slide_trace)
        slide_data.append([subtopic] + parsed_points)

    report("Finalizing slide content...", 0.95)
    return {"slides": slide_data, "style": style_guide, "trace": trace}
