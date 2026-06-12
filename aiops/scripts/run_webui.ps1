<#
.SYNOPSIS
  One-command launcher for the TraceFlix-AIOps React + FastAPI dashboard (Windows/PowerShell).

.DESCRIPTION
  Native PowerShell equivalent of scripts/run_webui.sh — no bash required.
  Resolves Python, checks node/npm, installs backend + frontend deps on first
  run, then builds and serves (prod) or starts backend + Vite hot-reload (dev).

.EXAMPLE
  ./scripts/run_webui.ps1            # prod: build SPA, serve all on one port
  ./scripts/run_webui.ps1 -Dev       # dev: backend + Vite hot-reload (2 procs)
  $env:PORT=8080; ./scripts/run_webui.ps1   # override backend port (default 8000)
#>
[CmdletBinding()]
param([switch]$Dev)

$ErrorActionPreference = 'Stop'

# --- resolve aiops root (this script lives in aiops/scripts) ---
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$port = if ($env:PORT) { $env:PORT } else { '8000' }

# --- resolve a Python interpreter (name differs across setups) ---
$python = $env:PYTHON
if (-not $python) {
  foreach ($c in 'python', 'python3', 'py') {
    if (Get-Command $c -ErrorAction SilentlyContinue) { $python = $c; break }
  }
}
if (-not $python) { throw 'ERROR: no Python interpreter found (python/python3/py).' }

# --- prerequisites ---
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'ERROR: node not found on PATH.' }
if (-not (Get-Command npm  -ErrorAction SilentlyContinue)) { throw 'ERROR: npm not found on PATH.' }

# --- backend deps (probe via find_spec: exits non-zero silently, never a traceback) ---
& $python -c 'import importlib.util as u, sys; sys.exit(0 if u.find_spec(''fastapi'') and u.find_spec(''uvicorn'') else 1)'
if ($LASTEXITCODE -ne 0) {
  Write-Host '[*] Installing backend deps (fastapi, uvicorn)...'
  & $python -m pip install -q -r requirements.txt
}

# --- frontend deps ---
if (-not (Test-Path 'webui/frontend/node_modules')) {
  Write-Host '[*] Installing frontend deps (npm install)...'
  Push-Location 'webui/frontend'
  npm install --no-audit --no-fund
  Pop-Location
}

if ($Dev) {
  Write-Host "[*] DEV mode - backend :$port  +  Vite hot-reload :5173"
  $back  = Start-Process -PassThru -NoNewWindow $python `
    -ArgumentList @('-m', 'uvicorn', 'webui.backend.app:app', '--reload', '--port', $port)
  $front = Start-Process -PassThru -NoNewWindow 'npm' `
    -ArgumentList @('run', 'dev') -WorkingDirectory (Join-Path $root 'webui/frontend')
  Write-Host "[*] Open http://localhost:5173   (API on :$port, proxied via /api)"
  try {
    Wait-Process -Id $back.Id, $front.Id
  } finally {
    Write-Host "`n[*] stopping..."
    foreach ($p in $back, $front) {
      if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    }
  }
} else {
  Write-Host '[*] PROD mode - building SPA, then serving everything on one port'
  Push-Location 'webui/frontend'
  npm run build
  Pop-Location
  Write-Host ''
  Write-Host "[*] Open  http://localhost:$port"
  & $python -m uvicorn webui.backend.app:app --port $port
}
