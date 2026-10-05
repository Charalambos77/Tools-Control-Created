# Tools Control — start on Windows.
#   .\start.ps1            normal start, opens http://127.0.0.1:8450
#   .\start.ps1 -Admin     as administrator (not needed normally)
#   .\start.ps1 -Demo      pretend chats, skills and MCP servers (your real setup is not touched)
param([switch]$Admin, [switch]$Demo, [int]$Port = 8450)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if ($Admin) {
  $me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
  if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $args2 = "-NoExit -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Admin -Port $Port"
    if ($Demo) { $args2 += " -Demo" }
    Start-Process powershell -Verb RunAs -ArgumentList $args2
    exit
  }
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
  Write-Host "First start: creating the Python environment..."
  if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .venv } else { python -m venv .venv }
}
$py = ".venv\Scripts\python.exe"
$stamp = ".venv\requirements.stamp"
$want = (Get-FileHash requirements.txt).Hash
if (-not (Test-Path $stamp) -or (Get-Content $stamp) -ne $want) {
  & $py -m pip install --upgrade pip -q
  & $py -m pip install -r requirements.txt -q
  Set-Content $stamp $want
}

if ($Demo) { $env:TC_DEMO = "1" } else { Remove-Item Env:TC_DEMO -ErrorAction SilentlyContinue }
Start-Job -ScriptBlock { param($p) Start-Sleep 2; Start-Process "http://127.0.0.1:$p" } -ArgumentList $Port | Out-Null
Write-Host "Tools Control on http://127.0.0.1:$Port  (Ctrl+C to stop)"
& $py -m uvicorn tctl.main:app --host 127.0.0.1 --port $Port --log-level warning
