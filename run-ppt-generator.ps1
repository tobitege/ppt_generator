param(
    [ValidateSet("ollama", "lm_studio", "openai_compat")]
    [string]$Provider = "lm_studio",

    [string]$BaseUrl,
    [string]$Model,
    [string]$ApiKey,

    [string]$Temperature = "0.4",
    [int]$TimeoutSeconds = 300,
    [int]$RetryCount = 2,
    [double]$RetryDelaySeconds = 1.5,
    [double]$RequestDelaySeconds = 0.75,
    [int]$Port = 8501,

    [switch]$Headless,
    [switch]$InstallDeps,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$venvStreamlit = Join-Path $projectRoot ".venv\Scripts\streamlit.exe"
$requirements = Join-Path $projectRoot "requirements.txt"
$hasUv = $null -ne (Get-Command uv -ErrorAction SilentlyContinue)

if (-not (Test-Path $venvPython)) {
    Write-Host "Creating .venv..."
    if ($hasUv) {
        uv venv (Join-Path $projectRoot ".venv")
    } else {
        python -m venv (Join-Path $projectRoot ".venv")
    }
}

if ($InstallDeps -or -not (Test-Path $venvStreamlit)) {
    Write-Host "Installing dependencies..."
    if ($hasUv) {
        uv pip install --python $venvPython -r $requirements
    } else {
        & $venvPython -m pip install -r $requirements
    }
}

if ($Provider -eq "ollama") {
    if (-not $BaseUrl) { $BaseUrl = "http://127.0.0.1:11434" }
    if (-not $Model) { $Model = "dolphin2.1-mistral" }

    $env:PPT_LLM_PROVIDER = "ollama"
    $env:PPT_OLLAMA_BASE_URL = $BaseUrl
    $env:PPT_OLLAMA_MODEL = $Model
    $env:PPT_OLLAMA_TEMPERATURE = $Temperature
    $env:PPT_LLM_TIMEOUT_SECONDS = [string]$TimeoutSeconds
    $env:PPT_LLM_RETRIES = [string]$RetryCount
    $env:PPT_LLM_RETRY_DELAY_SECONDS = [string]$RetryDelaySeconds
    $env:PPT_REQUEST_DELAY_SECONDS = [string]$RequestDelaySeconds
} elseif ($Provider -eq "lm_studio") {
    if (-not $BaseUrl) { $BaseUrl = "http://127.0.0.1:1234" }
    if (-not $Model) { $Model = "dolphin-2.1-mistral-7b" }

    $env:PPT_LLM_PROVIDER = "lm_studio"
    $env:PPT_LLM_BASE_URL = $BaseUrl
    $env:PPT_LLM_MODEL = $Model
    $env:PPT_LLM_TEMPERATURE = $Temperature
    $env:PPT_LLM_TIMEOUT_SECONDS = [string]$TimeoutSeconds
    $env:PPT_LLM_RETRIES = [string]$RetryCount
    $env:PPT_LLM_RETRY_DELAY_SECONDS = [string]$RetryDelaySeconds
    $env:PPT_REQUEST_DELAY_SECONDS = [string]$RequestDelaySeconds
} else {
    if (-not $BaseUrl) { $BaseUrl = "https://api.openai.com/v1" }
    if (-not $Model) { $Model = "gpt-4o-mini" }

    $env:PPT_LLM_PROVIDER = "openai_compat"
    $env:PPT_LLM_BASE_URL = $BaseUrl
    $env:PPT_LLM_MODEL = $Model
    $env:PPT_LLM_TEMPERATURE = $Temperature
    $env:PPT_LLM_TIMEOUT_SECONDS = [string]$TimeoutSeconds
    $env:PPT_LLM_RETRIES = [string]$RetryCount
    $env:PPT_LLM_RETRY_DELAY_SECONDS = [string]$RetryDelaySeconds
    $env:PPT_REQUEST_DELAY_SECONDS = [string]$RequestDelaySeconds
}

if ($ApiKey) {
    $env:PPT_LLM_API_KEY = $ApiKey
}

Write-Host "Provider: $($env:PPT_LLM_PROVIDER)"
Write-Host "Base URL: $BaseUrl"
Write-Host "Model:    $Model"
if ($ApiKey) {
    Write-Host "API Key:  provided"
}
Write-Host "Temp:     $Temperature"
Write-Host "Timeout:  $TimeoutSeconds s"
Write-Host "Retries:  $RetryCount (delay ${RetryDelaySeconds}s)"
Write-Host "ReqDelay: ${RequestDelaySeconds}s"
Write-Host "Port:     $Port"

if ($DryRun) {
    Write-Host "Dry run enabled. Not starting Streamlit."
    return
}

Push-Location $projectRoot
try {
    $streamlitArgs = @(
        "run", "main.py",
        "--server.port", "$Port",
        "--server.showEmailPrompt", "false"
    )
    if ($Headless) {
        $streamlitArgs += @("--server.headless", "true")
    }

    & $venvStreamlit @streamlitArgs
} finally {
    Pop-Location
}
