$ErrorActionPreference = "Stop"

$Scripts = @(
  "install_windows.ps1",
  "mcp_doctor.ps1",
  "make_mod_knowledge.ps1",
  "vortex_skyrimse_menu.ps1"
)

foreach ($Script in $Scripts) {
  $Path = Join-Path $PSScriptRoot "..\$Script"
  if (!(Test-Path -LiteralPath $Path)) {
    throw "Missing PowerShell script: $Script"
  }
  $Errors = $null
  [System.Management.Automation.PSParser]::Tokenize((Get-Content -LiteralPath $Path -Raw), [ref]$Errors) | Out-Null
  if ($Errors.Count -gt 0) {
    Write-Host "Parse errors in $Script"
    $Errors | Format-List
    exit 1
  }
  Write-Host "Parsed: $Script"
}

$MenuReportDir = Join-Path $PSScriptRoot "..\.local\menu-test-reports"
$MenuOutput = powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "..\vortex_skyrimse_menu.ps1") -ListActions -ReportDir $MenuReportDir
$MenuOutput
if (($MenuOutput -join "`n") -notmatch "Safe session report") {
  throw "Menu did not list the safe session report action."
}
if (($MenuOutput -join "`n") -notmatch "Collection manifest match") {
  throw "Menu did not list the collection manifest match action."
}
