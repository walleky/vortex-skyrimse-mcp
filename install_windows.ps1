param(
  [string]$ClientName = "openclaw",
  [string]$ConfigOut = ""
)

$ErrorActionPreference = "Stop"

$Server = Join-Path $PSScriptRoot "server.py"
if (!(Test-Path -LiteralPath $Server)) {
  throw "server.py was not found beside this installer."
}

$PythonCommand = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
  $PythonCommand = "py"
  $Args = @("-3", $Server)
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
  $PythonCommand = "python"
  $Args = @($Server)
} else {
  throw "Python was not found. Install Python 3 for Windows, then rerun this script."
}

$Snippet = [ordered]@{
  mcpServers = [ordered]@{
    "vortex-skyrimse" = [ordered]@{
      command = $PythonCommand
      args = $Args
    }
  }
}

$Json = $Snippet | ConvertTo-Json -Depth 8

Write-Host ""
Write-Host "Vortex Skyrim SE MCP server is ready."
Write-Host ""
Write-Host "Add this MCP server config to ${ClientName}:"
Write-Host ""
Write-Host $Json
Write-Host ""

if ($ConfigOut) {
  $Parent = Split-Path -Parent $ConfigOut
  if ($Parent) {
    New-Item -ItemType Directory -Force -Path $Parent | Out-Null
  }
  Set-Content -LiteralPath $ConfigOut -Value $Json -Encoding UTF8
  Write-Host "Wrote config snippet to: $ConfigOut"
}

Write-Host "Quick test:"
Write-Host "  $PythonCommand $($Args -join ' ') --self-test"
Write-Host ""
Write-Host "No-hassle doctor:"
Write-Host "  .\mcp_doctor.ps1"
Write-Host "  .\MCP-Doctor.cmd"
Write-Host ""
Write-Host "Direct CLI examples:"
Write-Host "  $PythonCommand $($Args -join ' ') --skyrim-diagnostics"
Write-Host "  $PythonCommand $($Args -join ' ') --safe-session"
Write-Host "  $PythonCommand $($Args -join ' ') --tool validate_setup"
Write-Host "  $PythonCommand $($Args -join ' ') --tool detect_environment"
Write-Host "  $PythonCommand $($Args -join ' ') --tool nexus_validate_key"
Write-Host "  $PythonCommand $($Args -join ' ') --tool in_game_issue_report --description `"annoying popup after loading a save`""
Write-Host "  $PythonCommand $($Args -join ' ') --tool in_game_issue_report --description `"bed outside tavern room`" --location `"Whiterun Bannered Mare`" --object `"bed`""
Write-Host "  .\vortex_skyrimse_menu.ps1"
Write-Host "  .\Vortex-SkyrimSE-Menu.cmd"
Write-Host "  .\make_mod_knowledge.ps1"
Write-Host "  .\Make-Mod-Knowledge.cmd"
Write-Host ""
Write-Host "First prompt:"
Write-Host "  Use skyrim_diagnostics_report to write a no-change first report with setup validation, profile backup if possible, modded play health, logs, and Nexus metadata if available. Summarize the top findings and do not apply changes."
Write-Host ""
Write-Host "Optional Nexus metadata:"
Write-Host "  Set NEXUS_MODS_API_KEY or use --nexus-api-key-file. This server does not copy Vortex's key."
Write-Host ""
Write-Host "Collection knowledge prompt:"
Write-Host "  Use the vortex-skyrimse MCP to run mod_knowledge_report. Summarize the top removal-review candidates. Do not apply changes."
Write-Host ""
Write-Host "Bug-report helper prompt:"
Write-Host "  Use the vortex-skyrimse MCP to run log_status and bug_report_bundle with zip_output=true and redact_user_paths=true. Do not apply changes."
