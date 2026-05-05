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
if (($MenuOutput -join "`n") -notmatch "Workflow guide") {
  throw "Menu did not list the workflow guide action."
}
if (($MenuOutput -join "`n") -notmatch "Skyrim runtime logs") {
  throw "Menu did not list the Skyrim runtime logs action."
}
if (($MenuOutput -join "`n") -notmatch "Config file validator") {
  throw "Menu did not list the config file validator action."
}
if (($MenuOutput -join "`n") -notmatch "xEdit inspection script") {
  throw "Menu did not list the xEdit inspection script action."
}
if (($MenuOutput -join "`n") -notmatch "xEdit inspection result") {
  throw "Menu did not list the xEdit inspection result action."
}

$PythonForMenu = $env:VORTEX_SKYRIMSE_MCP_TEST_PYTHON
if ($PythonForMenu) {
  $ActionOutput = powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "..\vortex_skyrimse_menu.ps1") -Action xedit-script -ReportDir $MenuReportDir -PythonCommand $PythonForMenu -IssueDescription "bed outside tavern room" -IssueLocation "Whiterun Bannered Mare" -IssueObject "bed" -XeditMaxRecords 5
  $ActionOutput
  $GeneratedScripts = @(Get-ChildItem -LiteralPath $MenuReportDir -Filter "xedit-inspection-*.pas" | Sort-Object LastWriteTime -Descending)
  if ($GeneratedScripts.Count -lt 1) {
    throw "Menu xEdit script action did not write a .pas script."
  }
  $ScriptText = Get-Content -LiteralPath $GeneratedScripts[0].FullName -Raw
  if ($ScriptText -notmatch "OpenClaw Skyrim inspector is read-only") {
    throw "Generated xEdit script did not include the read-only warning."
  }
  if (($ActionOutput -join "`n") -notmatch "xEdit/SSEEdit inspection script") {
    throw "Menu xEdit script action did not print the expected success text."
  }
}
