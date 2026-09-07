param(
  [int]$Port = 8765,
  [string]$ProxyUrl = $env:AGNES_PROXY_URL
)

$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  throw "Missing .venv. Run: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
}

# Agnes is outside the Philips network and must pass through the corporate
# Zscaler gateway on managed devices. Explicit caller settings always win.
if ([string]::IsNullOrWhiteSpace($ProxyUrl)) {
  $ProxyUrl = $env:HTTPS_PROXY
}
if ([string]::IsNullOrWhiteSpace($ProxyUrl)) {
  $ProxyUrl = "http://apac.zscaler.proxy.pgn.philips.com:10015"
}
if (-not [string]::IsNullOrWhiteSpace($ProxyUrl)) {
  $env:HTTP_PROXY = $ProxyUrl
  $env:HTTPS_PROXY = $ProxyUrl
  $env:ALL_PROXY = $ProxyUrl
  if ([string]::IsNullOrWhiteSpace($env:NO_PROXY)) {
    $env:NO_PROXY = "localhost,127.0.0.1,::1,.philips.com,.philips.com.cn"
  }
}

Set-Location -LiteralPath $projectDir
& $python -m uvicorn app:app --host 127.0.0.1 --port $Port
