$ErrorActionPreference = "Stop"

$Scripts = @(
  "install_windows.ps1",
  "mcp_doctor.ps1",
  "make_mod_knowledge.ps1",
  "vortex_skyrimse_menu.ps1",
  "scripts\capture_popup_evidence.ps1"
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
if (($MenuOutput -join "`n") -notmatch "Deployment Doctor") {
  throw "Menu did not list the Deployment Doctor action."
}
if (($MenuOutput -join "`n") -notmatch "Launch Doctor") {
  throw "Menu did not list the Launch Doctor action."
}
if (($MenuOutput -join "`n") -notmatch "Reversible Automation Plan") {
  throw "Menu did not list the reversible automation action."
}
if (($MenuOutput -join "`n") -notmatch "SKSE Runtime Doctor") {
  throw "Menu did not list the SKSE Runtime Doctor action."
}
if (($MenuOutput -join "`n") -notmatch "Report Viewer") {
  throw "Menu did not list the report viewer action."
}
if (($MenuOutput -join "`n") -notmatch "Live Evidence Summary") {
  throw "Menu did not list the live evidence summary action."
}
if (($MenuOutput -join "`n") -notmatch "Known Mod Rules") {
  throw "Menu did not list the known mod rules action."
}
if (($MenuOutput -join "`n") -notmatch "MO2 Diagnostics") {
  throw "Menu did not list the MO2 diagnostics action."
}
if (($MenuOutput -join "`n") -notmatch "Runtime Log Watch") {
  throw "Menu did not list the runtime log watch action."
}
if (($MenuOutput -join "`n") -notmatch "Capture Popup Evidence") {
  throw "Menu did not list the capture popup evidence action."
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
if (($MenuOutput -join "`n") -notmatch "Skyrim issue case packet") {
  throw "Menu did not list the Skyrim issue case packet action."
}
if (($MenuOutput -join "`n") -notmatch "Skyrim issue case status") {
  throw "Menu did not list the Skyrim issue case status action."
}
if (($MenuOutput -join "`n") -notmatch "Append issue case note") {
  throw "Menu did not list the issue case note action."
}
if (($MenuOutput -join "`n") -notmatch "Safe experiment plan") {
  throw "Menu did not list the safe experiment plan action."
}
if (($MenuOutput -join "`n") -notmatch "What should I do now") {
  throw "Menu did not list the what-now action."
}
if (($MenuOutput -join "`n") -notmatch "Live Skyrim bridge status") {
  throw "Menu did not list the live bridge status action."
}
if (($MenuOutput -join "`n") -notmatch "Import case evidence") {
  throw "Menu did not list the case evidence import action."
}
if (($MenuOutput -join "`n") -notmatch "Bundle issue case") {
  throw "Menu did not list the case bundle action."
}
if (($MenuOutput -join "`n") -notmatch "Import case inbox") {
  throw "Menu did not list the case inbox import action."
}
if (($MenuOutput -join "`n") -notmatch "Clone profile and apply fixes") {
  throw "Menu did not list the safe profile fix action."
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
