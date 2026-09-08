param(
  [Parameter(Mandatory = $true)][string]$InputWorkbook,
  [Parameter(Mandatory = $true)][string]$TemplatePptx,
  [string]$Sku = "S3203/08",
  [ValidateSet("JD", "ALI", "OFFLINE")][string[]]$Channels = @("JD"),
  [ValidateRange(3, 24)][int]$Months = 12,
  [string]$ConfirmedMappings
)

$AgentDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $AgentDirectory ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
  throw "Missing .venv. Install requirements before running the agent."
}
$Arguments = @("cli.py", "--input", $InputWorkbook, "--template", $TemplatePptx, "--sku", $Sku, "--channels") + $Channels + @("--months", $Months)
if ($ConfirmedMappings) { $Arguments += @("--confirmed-mappings", $ConfirmedMappings) }
Push-Location $AgentDirectory
try { & $Python @Arguments } finally { Pop-Location }
