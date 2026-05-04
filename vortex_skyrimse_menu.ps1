param(
  [string]$Action = "",
  [switch]$ListActions,
  [string]$ReportDir = "",
  [string]$StagingDir = "",
  [string]$SkyrimDir = "",
  [string]$VortexExe = "",
  [string]$ProfileId = "",
  [string]$BackupPath = "",
  [string]$IssueDescription = "",
  [string]$IssueLocation = "",
  [string]$IssueObject = "",
  [string]$FormId = "",
  [string]$Cell = "",
  [string]$BaseObject = "",
  [string]$PopupText = "",
  [int]$MaxMods = 500,
  [switch]$HashFiles,
  [switch]$NoProfileState,
  [switch]$NoConflicts,
  [switch]$NoReadmeExcerpts,
  [switch]$NoProfileBackup,
  [switch]$NoLogs,
  [switch]$NoPlayReport,
  [switch]$IncludeNexusMetadata,
  [string]$NexusApiKeyFile = "",
  [int]$NexusMaxLookupMods = 80,
  [switch]$NoNexusCache
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
  if ($IncludeNexusMetadata) {
    $args += "--include-nexus-metadata"
  }
  if ($NexusApiKeyFile) {
    $args += "--nexus-api-key-file"
    $args += $NexusApiKeyFile
  }
  if ($NexusMaxLookupMods -gt 0) {
    $args += "--nexus-max-lookup-mods"
    $args += "$NexusMaxLookupMods"
  }
  if ($NoNexusCache) {
    $args += "--no-nexus-cache"
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
  Write-Host "1. Validate setup"
  Write-Host "2. Create Vortex profile backup"
  Write-Host "3. Preview restore from backup"
  Write-Host "4. Environment diagnosis"
  Write-Host "5. Mod knowledge Markdown report"
  Write-Host "6. Modded play diagnosis"
  Write-Host "7. Bug report zip"
  Write-Host "8. Log status"
  Write-Host "9. List available tools"
  Write-Host "10. In-game issue triage"
  Write-Host "11. Safe session report"
  Write-Host "12. Skyrim diagnostics report"
  Write-Host "Q. Quit"
}

function Invoke-MenuAction {
  param([string]$Selected)

  $stamp = New-TimeStamp
  $common = Get-CommonArgs
  switch ($Selected.Trim().ToLowerInvariant()) {
    { $_ -in @("1", "validate", "setup", "check") } {
      $out = Join-Path $script:ReportDir "setup-validation-$stamp.json"
      Invoke-Server (@("--tool", "validate_setup", "--output-json", $out) + $common)
      Write-Host "Wrote JSON result: $out" -ForegroundColor Green
      return
    }
    { $_ -in @("2", "backup", "profile-backup") } {
      $backup = Join-Path $script:ReportDir "profile-backup-$stamp.json"
      $out = Join-Path $script:ReportDir "profile-backup-$stamp.result.json"
      Invoke-Server (@("--tool", "vortex_profile_backup", "--backup-path", $backup, "--include-all-profiles", "--output-json", $out) + $common)
      Write-Host "Wrote profile backup: $backup" -ForegroundColor Green
      Write-Host "Wrote JSON result: $out" -ForegroundColor Green
      return
    }
    { $_ -in @("3", "restore", "restore-preview", "undo") } {
      $backup = $BackupPath
      if (!$backup) {
        if ($script:StartedWithAction) {
          throw "Pass -BackupPath with -Action restore. Example: .\vortex_skyrimse_menu.ps1 -Action restore -BackupPath C:\path\profile-backup.json"
        }
        $backup = Read-Host "Paste the profile backup JSON path"
      }
      $argsFile = Write-JsonArgs "restore-preview" @{
        backup_path = $backup
        apply = $false
        disable_extra_mods = $false
      }
      $out = Join-Path $script:ReportDir "restore-preview-$stamp.json"
      Invoke-Server (@("--tool", "vortex_profile_restore_plan", "--args-file", $argsFile, "--output-json", $out) + $common)
      Write-Host "Wrote restore preview: $out" -ForegroundColor Green
      Write-Host "This preview did not change Vortex." -ForegroundColor Green
      return
    }
    { $_ -in @("4", "environment", "detect") } {
      $out = Join-Path $script:ReportDir "environment-$stamp.json"
      Invoke-Server (@("--tool", "detect_environment", "--output-json", $out) + $common)
      Write-Host "Wrote JSON result: $out" -ForegroundColor Green
      return
    }
    { $_ -in @("5", "knowledge", "mods") } {
      $md = Join-Path $script:ReportDir "mod-knowledge-$stamp.md"
      $json = Join-Path $script:ReportDir "mod-knowledge-$stamp.result.json"
      Invoke-Server (@("--mod-knowledge", "--output-path", $md, "--output-json", $json) + $common)
      Write-Host "Wrote Markdown report: $md" -ForegroundColor Green
      Write-Host "Wrote JSON result: $json" -ForegroundColor Green
      return
    }
    { $_ -in @("6", "play", "diagnosis") } {
      $out = Join-Path $script:ReportDir "modded-play-$stamp.json"
      Invoke-Server (@("--tool", "skyrim_modded_play_report", "--output-json", $out) + $common)
      Write-Host "Wrote JSON result: $out" -ForegroundColor Green
      return
    }
    { $_ -in @("7", "bug", "bundle") } {
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
    { $_ -in @("8", "logs", "log") } {
      $out = Join-Path $script:ReportDir "log-status-$stamp.json"
      Invoke-Server @("--tool", "log_status", "--output-json", $out)
      Write-Host "Wrote JSON result: $out" -ForegroundColor Green
      return
    }
    { $_ -in @("9", "tools", "list") } {
      Invoke-Server @("--list-tools")
      return
    }
    { $_ -in @("10", "ingame", "in-game", "issue", "triage") } {
      $description = $IssueDescription
      $location = $IssueLocation
      $objectName = $IssueObject
      $formId = $FormId
      $cellName = $Cell
      $baseObjectName = $BaseObject
      $popup = $PopupText
      if (!$description) {
        if ($script:StartedWithAction) {
          throw "Pass -IssueDescription with -Action ingame. Example: .\vortex_skyrimse_menu.ps1 -Action ingame -IssueDescription `"bed outside tavern room`" -IssueLocation `"Whiterun Bannered Mare`" -IssueObject `"bed`""
        }
        $description = Read-Host "Describe the in-game problem"
      }
      if (!$location -and !$script:StartedWithAction) {
        $location = Read-Host "Location, if known (press Enter to skip)"
      }
      if (!$objectName -and !$script:StartedWithAction) {
        $objectName = Read-Host "Object or thing, if known (press Enter to skip)"
      }
      if (!$popup -and !$script:StartedWithAction) {
        $popup = Read-Host "Exact popup text, if any (press Enter to skip)"
      }
      if (!$formId -and !$script:StartedWithAction) {
        $formId = Read-Host "Console-clicked FormID, if any (press Enter to skip)"
      }
      $argsData = @{
        description = $description
      }
      if ($location) {
        $argsData.location = $location
      }
      if ($objectName) {
        $argsData.object = $objectName
      }
      if ($formId) {
        $argsData.form_id = $formId
      }
      if ($cellName) {
        $argsData.cell = $cellName
      }
      if ($baseObjectName) {
        $argsData.base_object = $baseObjectName
      }
      if ($popup) {
        $argsData.popup_text = $popup
      }
      $argsFile = Write-JsonArgs "in-game-issue" $argsData
      $out = Join-Path $script:ReportDir "in-game-issue-$stamp.json"
      Invoke-Server (@("--tool", "in_game_issue_report", "--args-file", $argsFile, "--output-json", $out) + $common)
      Write-Host "Wrote in-game issue triage: $out" -ForegroundColor Green
      return
    }
    { $_ -in @("11", "safe", "session", "safe-session", "safe-session-report") } {
      $md = Join-Path $script:ReportDir "safe-session-$stamp.md"
      $json = Join-Path $script:ReportDir "safe-session-$stamp.json"
      $description = $IssueDescription
      $location = $IssueLocation
      $objectName = $IssueObject
      $formId = $FormId
      $cellName = $Cell
      $baseObjectName = $BaseObject
      $popup = $PopupText
      if (!$description -and !$script:StartedWithAction) {
        $description = Read-Host "Optional in-game problem to include (press Enter to skip)"
      }
      if ($description -and !$location -and !$script:StartedWithAction) {
        $location = Read-Host "Location, if known (press Enter to skip)"
      }
      if ($description -and !$objectName -and !$script:StartedWithAction) {
        $objectName = Read-Host "Object or thing, if known (press Enter to skip)"
      }
      if ($description -and !$popup -and !$script:StartedWithAction) {
        $popup = Read-Host "Exact popup text, if any (press Enter to skip)"
      }
      if ($description -and !$formId -and !$script:StartedWithAction) {
        $formId = Read-Host "Console-clicked FormID, if any (press Enter to skip)"
      }
      $argsData = @{
        output_path = $md
        session_json_path = $json
        include_profile_backup = (-not $NoProfileBackup)
        include_all_profiles = $true
        include_play_report = (-not $NoPlayReport)
        include_logs = (-not $NoLogs)
        redact_user_paths = $true
      }
      if ($description) {
        $argsData.description = $description
      }
      if ($location) {
        $argsData.location = $location
      }
      if ($objectName) {
        $argsData.object = $objectName
      }
      if ($formId) {
        $argsData.form_id = $formId
      }
      if ($cellName) {
        $argsData.cell = $cellName
      }
      if ($baseObjectName) {
        $argsData.base_object = $baseObjectName
      }
      if ($popup) {
        $argsData.popup_text = $popup
      }
      $argsFile = Write-JsonArgs "safe-session" $argsData
      $out = Join-Path $script:ReportDir "safe-session-$stamp.result.json"
      Invoke-Server (@("--safe-session", "--args-file", $argsFile, "--output-json", $out) + $common)
      Write-Host "Wrote safe session Markdown: $md" -ForegroundColor Green
      Write-Host "Wrote safe session JSON: $json" -ForegroundColor Green
      Write-Host "Wrote JSON result: $out" -ForegroundColor Green
      Write-Host "This action did not deploy, disable, delete, or edit mods." -ForegroundColor Green
      return
    }
    { $_ -in @("12", "diagnostics", "skyrim-diagnostics", "skyrim") } {
      $md = Join-Path $script:ReportDir "skyrim-diagnostics-$stamp.md"
      $json = Join-Path $script:ReportDir "skyrim-diagnostics-$stamp.json"
      $description = $IssueDescription
      $location = $IssueLocation
      $objectName = $IssueObject
      $formId = $FormId
      $cellName = $Cell
      $baseObjectName = $BaseObject
      $popup = $PopupText
      if (!$description -and !$script:StartedWithAction) {
        $description = Read-Host "Optional in-game problem to include (press Enter to skip)"
      }
      $argsData = @{
        output_path = $md
        session_json_path = $json
        include_profile_backup = (-not $NoProfileBackup)
        include_all_profiles = $true
        include_play_report = (-not $NoPlayReport)
        include_logs = (-not $NoLogs)
        redact_user_paths = $true
      }
      if ($description) {
        $argsData.description = $description
      }
      if ($location) {
        $argsData.location = $location
      }
      if ($objectName) {
        $argsData.object = $objectName
      }
      if ($formId) {
        $argsData.form_id = $formId
      }
      if ($cellName) {
        $argsData.cell = $cellName
      }
      if ($baseObjectName) {
        $argsData.base_object = $baseObjectName
      }
      if ($popup) {
        $argsData.popup_text = $popup
      }
      $argsFile = Write-JsonArgs "skyrim-diagnostics" $argsData
      $out = Join-Path $script:ReportDir "skyrim-diagnostics-$stamp.result.json"
      Invoke-Server (@("--skyrim-diagnostics", "--args-file", $argsFile, "--output-json", $out) + $common)
      Write-Host "Wrote Skyrim diagnostics Markdown: $md" -ForegroundColor Green
      Write-Host "Wrote Skyrim diagnostics JSON: $json" -ForegroundColor Green
      Write-Host "Wrote JSON result: $out" -ForegroundColor Green
      Write-Host "This action did not deploy, disable, delete, update, or edit mods." -ForegroundColor Green
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

$script:ReportDir = Get-DefaultReportDir
$script:StartedWithAction = [bool]$Action
New-Item -ItemType Directory -Force -Path $script:ReportDir | Out-Null
if (!$env:VORTEX_SKYRIMSE_MCP_LOG_DIR) {
  $env:VORTEX_SKYRIMSE_MCP_LOG_DIR = Join-Path $script:ReportDir "logs"
}

if ($ListActions) {
  Show-Actions
  exit 0
}

$script:Python = Find-Python

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
