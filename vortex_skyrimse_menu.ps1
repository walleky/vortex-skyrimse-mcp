param(
  [string]$Action = "",
  [switch]$ListActions,
  [string]$ReportDir = "",
  [string]$StagingDir = "",
  [string]$SkyrimDir = "",
  [string]$VortexExe = "",
  [string]$ProfileId = "",
  [int]$MaxMods = 500,
  [switch]$HashFiles,
  [switch]$NoProfileState,
  [switch]$NoConflicts,
  [switch]$NoReadmeExcerpts
)

$ErrorActionPreference = "Stop"

function Find-Python {
  if (Get-Command py -ErrorAction SilentlyContinue) {
    return @{
      Command = "py"
      Args = @("-3")
    }
  }
  if (Get-Command python -ErrorAction SilentlyContinue) {
    return @{
      Command = "python"
      Args = @()
    }
  }
  throw "Python 3 was not found. Install Python for Windows, then rerun this menu."
}

function Get-DefaultReportDir {
  if ($ReportDir) {
    return $ReportDir
  }
  $documents = Join-Path $env:USERPROFILE "Documents"
  if (!(Test-Path -LiteralPath $documents)) {
    $documents = $PSScriptRoot
  }
  return Join-Path $documents "vortex-skyrimse-mcp-reports"
}

function New-TimeStamp {
  return Get-Date -Format "yyyyMMdd-HHmmss"
}

function Get-CommonArgs {
  $args = @()
  if ($StagingDir) {
    $args += "--staging-dir"
    $args += $StagingDir
  }
  if ($SkyrimDir) {
    $args += "--skyrim-dir"
    $args += $SkyrimDir
  }
  if ($VortexExe) {
    $args += "--vortex-exe"
    $args += $VortexExe
  }
  if ($ProfileId) {
    $args += "--profile-id"
    $args += $ProfileId
  }
  if ($MaxMods -gt 0) {
    $args += "--max-mods"
    $args += "$MaxMods"
  }
  if ($HashFiles) {
    $args += "--hash-files"
  }
  if ($NoProfileState) {
    $args += "--no-profile-state"
  }
  if ($NoConflicts) {
    $args += "--no-conflicts"
  }
  if ($NoReadmeExcerpts) {
    $args += "--no-readme-excerpts"
  }
  return $args
}

function Invoke-Server {
  param([string[]]$Arguments)

  $runArgs = @()
  $runArgs += $script:Python.Args
  $runArgs += $script:Server
  $runArgs += $Arguments
  Write-Host ""
  Write-Host "Running: $($script:Python.Command) $($runArgs -join ' ')" -ForegroundColor DarkGray
  & $script:Python.Command @runArgs
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed with exit code $LASTEXITCODE"
  }
}

function Write-JsonArgs {
  param(
    [string]$Name,
    [hashtable]$Data
  )

  $path = Join-Path $script:ReportDir ("{0}-{1}.args.json" -f $Name, (New-TimeStamp))
  $Data | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $path -Encoding UTF8
  return $path
}

function Show-Actions {
  Write-Host ""
  Write-Host "Vortex Skyrim SE Helper Menu" -ForegroundColor Cyan
  Write-Host "Reports folder: $script:ReportDir"
  Write-Host ""
  Write-Host "1. Environment diagnosis"
  Write-Host "2. Mod knowledge Markdown report"
  Write-Host "3. Modded play diagnosis"
  Write-Host "4. Bug report zip"
  Write-Host "5. Log status"
  Write-Host "6. List available tools"
  Write-Host "Q. Quit"
}

function Invoke-MenuAction {
  param([string]$Selected)

  $stamp = New-TimeStamp
  $common = Get-CommonArgs
  switch ($Selected.Trim().ToLowerInvariant()) {
    { $_ -in @("1", "environment", "detect") } {
      $out = Join-Path $script:ReportDir "environment-$stamp.json"
      Invoke-Server (@("--tool", "detect_environment", "--output-json", $out) + $common)
      Write-Host "Wrote JSON result: $out" -ForegroundColor Green
      return
    }
    { $_ -in @("2", "knowledge", "mods") } {
      $md = Join-Path $script:ReportDir "mod-knowledge-$stamp.md"
      $json = Join-Path $script:ReportDir "mod-knowledge-$stamp.result.json"
      Invoke-Server (@("--mod-knowledge", "--output-path", $md, "--output-json", $json) + $common)
      Write-Host "Wrote Markdown report: $md" -ForegroundColor Green
      Write-Host "Wrote JSON result: $json" -ForegroundColor Green
      return
    }
    { $_ -in @("3", "play", "diagnosis") } {
      $out = Join-Path $script:ReportDir "modded-play-$stamp.json"
      Invoke-Server (@("--tool", "skyrim_modded_play_report", "--output-json", $out) + $common)
      Write-Host "Wrote JSON result: $out" -ForegroundColor Green
      return
    }
    { $_ -in @("4", "bug", "bundle") } {
      $bundle = Join-Path $script:ReportDir "bug-report-$stamp.json"
      $argsFile = Write-JsonArgs "bug-report" @{
        output_path = $bundle
        zip_output = $true
        redact_user_paths = $true
        include_logs = $true
        include_vortex_profiles = $true
        include_vortex_deployment = $true
        include_play_report = $true
      }
      $out = Join-Path $script:ReportDir "bug-report-$stamp.result.json"
      Invoke-Server (@("--tool", "bug_report_bundle", "--args-file", $argsFile, "--output-json", $out) + $common)
      Write-Host "Wrote bug report JSON and zip beside: $bundle" -ForegroundColor Green
      Write-Host "Wrote JSON result: $out" -ForegroundColor Green
      return
    }
    { $_ -in @("5", "logs", "log") } {
      $out = Join-Path $script:ReportDir "log-status-$stamp.json"
      Invoke-Server @("--tool", "log_status", "--output-json", $out)
      Write-Host "Wrote JSON result: $out" -ForegroundColor Green
      return
    }
    { $_ -in @("6", "tools", "list") } {
      Invoke-Server @("--list-tools")
      return
    }
    { $_ -in @("q", "quit", "exit") } {
      return
    }
    default {
      Write-Host "Unknown menu action: $Selected" -ForegroundColor Yellow
      return
    }
  }
}

$script:Server = Join-Path $PSScriptRoot "server.py"
if (!(Test-Path -LiteralPath $script:Server)) {
  throw "server.py was not found beside vortex_skyrimse_menu.ps1."
}

$script:Python = Find-Python
$script:ReportDir = Get-DefaultReportDir
New-Item -ItemType Directory -Force -Path $script:ReportDir | Out-Null
if (!$env:VORTEX_SKYRIMSE_MCP_LOG_DIR) {
  $env:VORTEX_SKYRIMSE_MCP_LOG_DIR = Join-Path $script:ReportDir "logs"
}

if ($ListActions) {
  Show-Actions
  exit 0
}

if ($Action) {
  Invoke-MenuAction $Action
  exit 0
}

while ($true) {
  Show-Actions
  $choice = Read-Host "Choose an action"
  if ($choice.Trim().ToLowerInvariant() -in @("q", "quit", "exit")) {
    break
  }
  Invoke-MenuAction $choice
  Write-Host ""
  Read-Host "Press Enter to return to the menu" | Out-Null
}
