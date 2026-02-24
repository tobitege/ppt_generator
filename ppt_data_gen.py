import os
import re
import time

import requests


def extract_items(input_string):
    # Find the text inside the << >>
    content = re.search(r'<<(.+?)>>', input_string)

    if content:
        content = content.group(1)
    else:
        return []

    # Split the content by the | separator and remove whitespace
    items = [item.strip() for item in content.split('|')]

    # Remove the quotes from each item
    items = [re.sub(r'^"|"$', '', item) for item in items]

    return items


def call_lmstudio(prompt):
    base_url = os.getenv("PPT_LLM_BASE_URL", "http://127.0.0.1:1234").rstrip("/")
    model = os.getenv("PPT_LLM_MODEL", "dolphin-2.1-mistral-7b")
    temperature = float(os.getenv("PPT_LLM_TEMPERATURE", "0.4"))
    timeout = int(os.getenv("PPT_LLM_TIMEOUT_SECONDS", "300"))
    retries = int(os.getenv("PPT_LLM_RETRIES", "2"))
    retry_delay = float(os.getenv("PPT_LLM_RETRY_DELAY_SECONDS", "1.5"))

    for attempt in range(retries + 1):
        try:
            response = requests.post(
                f"{base_url}/api/v1/chat",
                json={
                    "model": model,
                    "input": prompt,
                    "temperature": temperature,
                },
                timeout=(10, timeout),
            )
            response.raise_for_status()
            data = response.json()

            output = data.get("output", [])
            if isinstance(output, list):
                for item in output:
                    if isinstance(item, dict) and item.get("type") == "message":
                        content = item.get("content", "")
                        if content and content.strip():
                            return content
            raise RuntimeError(
                "LM Studio returned an empty response. "
                "This can happen if the request is canceled or times out on the server."
            )
        except RuntimeError as exc:
            if attempt < retries:
                time.sleep(retry_delay * (attempt + 1))
                continue
            raise RuntimeError(
                "LM Studio request failed after retries. "
                f"Provider=lm_studio, base_url={base_url}, model={model}. "
                "Try increasing PPT_LLM_TIMEOUT_SECONDS or reducing model/server load."
            ) from exc
        except requests.exceptions.RequestException as exc:
            if attempt < retries:
                time.sleep(retry_delay * (attempt + 1))
                continue
            raise RuntimeError(
                "LM Studio request failed. "
                f"Provider=lm_studio, base_url={base_url}, model={model}. "
                "Verify LM Studio server is running, model is loaded, and timeout is high enough."
            ) from exc


def build_ollama_caller():
    from langchain.llms import Ollama

    base_url = os.getenv("PPT_OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("PPT_OLLAMA_MODEL", "dolphin2.1-mistral")
    temperature = os.getenv("PPT_OLLAMA_TEMPERATURE", os.getenv("PPT_LLM_TEMPERATURE", "0.4"))

    llm = Ollama(
        model=model,
        base_url=base_url,
        temperature=temperature,
    )

    def call_ollama(prompt):
        try:
            return llm(prompt)
        except requests.exceptions.RequestException as exc:
            lm_studio_url = os.getenv("PPT_LLM_BASE_URL", "http://127.0.0.1:1234").rstrip("/")
            raise RuntimeError(
                "Ollama request failed. "
                f"Provider=ollama, base_url={base_url}, model={model}. "
                "If you run LM Studio instead, set PPT_LLM_PROVIDER=lm_studio "
                f"and PPT_LLM_BASE_URL={lm_studio_url}."
            ) from exc

    return call_ollama


def build_prompt_caller():
    provider = os.getenv("PPT_LLM_PROVIDER", "ollama").strip().lower()
    if provider == "ollama":
        base_caller = build_ollama_caller()
    elif provider in {"lm_studio", "lmstudio"}:
        base_caller = call_lmstudio
    else:
        raise ValueError(
            f"Unsupported provider '{provider}'. Use 'ollama' or 'lm_studio'."
        )

    request_delay = float(os.getenv("PPT_REQUEST_DELAY_SECONDS", "0"))
    last_call_time = 0.0

    def paced_call(prompt):
        nonlocal last_call_time
        if request_delay > 0 and last_call_time > 0:
            elapsed = time.monotonic() - last_call_time
            if elapsed < request_delay:
                time.sleep(request_delay - elapsed)
        result = base_caller(prompt)
        last_call_time = time.monotonic()
        return result

    return paced_call


def slide_data_gen(topic):
    llm_call = build_prompt_caller()

    slide_data = []

    point_count = int(os.getenv("PPT_POINT_COUNT", "5"))

    slide_data.append(extract_items(llm_call(f"""
    You are a text summarization and formatting specialized model that fetches relevant information

    For the topic "{topic}" suggest a presentation title and a presentation subtitle it should be returned in the format :
    << "title" | "subtitle >>

    example :
    << "Ethics in Design" | "Integrating Ethics into Design Processes" >>
    """)))

    slide_data.append(extract_items(llm_call(f"""
    You are a text summarization and formatting specialized model that fetches relevant information
            
    For the presentation titled "{slide_data[0][0]}" and with subtitle "{slide_data[0][1]}" for the topic "{topic}"
    Write a table of contents containing the title of each slide for a 7 slide presentation
    It should be of the format :
    << "slide1" | "slide2" | "slide3" | ... | >>
            
    example :
    << "Introduction to Design Ethics" | "User-Centered Design" | "Transparency and Honesty" | "Data Privacy and Security" | "Accessibility and Inclusion" | "Social Impact and Sustainability" | "Ethical AI and Automation" | "Collaboration and Professional Ethics" >>          
    """)))

    for subtopic in slide_data[1]:

        data_to_clean = llm_call(f"""
        You are a content generation specialized model that fetches relevant information and presents it in clear concise manner
                
        For the presentation titled "{slide_data[0][0]}" and with subtitle "{slide_data[0][1]}" for the topic "{topic}"
        Write the contents for a slide with the subtopic {subtopic}
        Write {point_count} points. Each point 10 words maximum.
        Make the points short, concise and to the point.
        """)

        cleaned_data = llm_call(f"""
        You are a text summarization and formatting specialized model that fetches relevant information and formats it into user specified formats
        Given below is a text draft for a presentation slide containing {point_count} points , extract the {point_count} sentences and format it as :
                    
        << "point1" | "point2" | "point3" | ... | >>
                    
        example :
        << "Foster a collaborative and inclusive work environment." | "Respect intellectual property rights and avoid plagiarism." | "Uphold professional standards and codes of ethics." | "Be open to feedback and continuous learning." >>

        -- Beginning of the text --
        {data_to_clean}
        -- End of the text --         
        """)

        slide_data.append([subtopic] + extract_items(cleaned_data))

    return slide_data
