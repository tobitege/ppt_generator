param(
    [int]$Port = 8501,
    [switch]$AllProjectInstances,
    [switch]$Force,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path $PSScriptRoot).Path

function Get-ProcessInfo {
    param([int]$ProcessId)
    return Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
}

$pidSet = [System.Collections.Generic.HashSet[int]]::new()

if ($AllProjectInstances) {
    $all = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue
    $matches = $all | Where-Object {
        $_.CommandLine -and
        $_.CommandLine -match "(?i)streamlit" -and
        $_.CommandLine -match "(?i)main.py" -and
        $_.CommandLine -like "*$projectRoot*"
    }
    foreach ($m in $matches) {
        $null = $pidSet.Add([int]$m.ProcessId)
    }
} else {
    $listeners = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        $null = $pidSet.Add([int]$listener.OwningProcess)
    }
}

$pids = @($pidSet)
if ($pids.Count -eq 0) {
    if ($AllProjectInstances) {
        Write-Host "No running Streamlit processes found for this project."
    } else {
        Write-Host "No listening process found on port $Port."
    }
    return
}

foreach ($procId in $pids) {
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    $info = Get-ProcessInfo -ProcessId $procId
    $cmd = if ($info -and $info.CommandLine) { $info.CommandLine } else { "" }
    $isLikelyStreamlit = ($cmd -match "(?i)streamlit") -or ($cmd -match "(?i)main.py")

    Write-Host ""
    Write-Host "PID:  $procId"
    Write-Host "Name: $($proc.ProcessName)"
    if ($cmd) {
        Write-Host "Cmd:  $cmd"
    }

    if (-not $isLikelyStreamlit -and -not $Force) {
        Write-Warning "Skipping PID ${procId}: process does not look like this project's Streamlit app. Use -Force to stop anyway."
        continue
    }

    if ($DryRun) {
        Write-Host "Dry run: would stop PID $procId"
        continue
    }

    Stop-Process -Id $procId -Force:$Force
    Write-Host "Stopped PID $procId"
}
