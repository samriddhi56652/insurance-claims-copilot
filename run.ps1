# Runs the API and the Streamlit dashboard together, no Docker needed.
# Usage:  .\run.ps1     (Ctrl+C to stop both)

$ErrorActionPreference = "Stop"
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Error "No .venv found. Create it first:  py -3 -m venv .venv ; .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}

Write-Host "Starting API      -> http://localhost:8000  (docs at /docs)" -ForegroundColor Cyan
$api = Start-Process -FilePath $py -ArgumentList "main.py" -PassThru -NoNewWindow

try {
    Start-Sleep -Seconds 3
    Write-Host "Starting dashboard -> http://localhost:8501" -ForegroundColor Cyan
    $env:API_BASE_URL = "http://localhost:8000"
    & $py -m streamlit run app.py --server.port 8501
}
finally {
    Write-Host "`nStopping API..." -ForegroundColor Yellow
    if ($api -and -not $api.HasExited) { Stop-Process -Id $api.Id -Force }
}
