# PPT Generator

A local LLM assisted ppt generation tool

## Why  

Writing presentations for course assignments is just boilerplate work most often, especially when even the lecturers dont even care about it.
Thats why I automated the boilerplate work, just enter a topic and the tool generates a simple presentation , enough to satisfy the base course requirement.

## Running Locally

This app supports two providers:

- `ollama`
- `lm_studio` (LM Studio v1 REST API)

clone the repo and move into the directory

```sh
git clone https://github.com/Govind-S-B/ppt_generator.git
cd ppt_generator
```

install the required python dependencies

```sh
pip install -r requirements.txt
```

optional: set environment variables

```powershell
# provider switch
$env:PPT_LLM_PROVIDER="lm_studio"

# ollama provider settings (defaults shown)
$env:PPT_OLLAMA_BASE_URL="http://127.0.0.1:11434"
$env:PPT_OLLAMA_MODEL="dolphin2.1-mistral"
$env:PPT_OLLAMA_TEMPERATURE="0.4"

# lm_studio provider settings
$env:PPT_LLM_BASE_URL="http://127.0.0.1:1234"
$env:PPT_LLM_MODEL="dolphin-2.1-mistral-7b"
$env:PPT_LLM_TEMPERATURE="0.4"
$env:PPT_LLM_TIMEOUT_SECONDS="300"
$env:PPT_LLM_RETRIES="2"
$env:PPT_LLM_RETRY_DELAY_SECONDS="1.5"
$env:PPT_REQUEST_DELAY_SECONDS="0.75"

# optional: reduce generation cost/latency
$env:PPT_POINT_COUNT="4"
```

run the streamlit app

```sh
streamlit run main.py
```

In the UI, set:
- Topic
- Number of content slides
- Extra instructions (optional)

or use the PowerShell helper script

```powershell
# default script mode (LM Studio)
.\run-ppt-generator.ps1

# Ollama
.\run-ppt-generator.ps1 -Provider ollama

# stop app on default port 8501
.\stop-ppt-generator.ps1

# stop app on custom port
.\stop-ppt-generator.ps1 -Port 8502
```
