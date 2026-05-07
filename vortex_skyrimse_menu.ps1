param(
  [string]$Action = "",
  [switch]$ListActions,
  [string]$ReportDir = "",
  [string]$StagingDir = "",
  [string]$SkyrimDir = "",
  [string]$VortexExe = "",
  [string]$ProfileId = "",
  [string]$BackupPath = "",
  [string]$DeploymentBaselinePath = "",
  [string]$IssueDescription = "",
  [string]$IssueLocation = "",
  [string]$IssueObject = "",
  [string]$FormId = "",
  [string]$Cell = "",
  [string]$BaseObject = "",
  [string]$PopupText = "",
  [string]$XeditExe = "",
  [string]$PluginName = "",
  [string]$XeditScriptPath = "",
  [string]$XeditReportPath = "",
  [string]$CollectionManifestPath = "",
  [string]$ConfigPath = "",
  [string]$Problem = "",
  [string]$WorkflowKey = "",
  [string]$IssueCaseDir = "",
  [string]$CaseNote = "",
  [string]$CaseNoteKind = "observation",
  [string]$EvidenceText = "",
  [string]$EvidenceKind = "manual",
  [string]$OcrText = "",
  [string]$ReferenceFormId = "",
  [string]$BaseFormId = "",
  [string]$ScreenshotPath = "",
  [string]$EvidenceConfidence = "",
  [string]$InboxDir = "",
  [string]$ExperimentTargetMod = "",
  [string]$ExperimentTargetModId = "",
  [string]$TestProfileName = "OpenClaw Safe Test",
  [string]$SafeProfileName = "OpenClaw Fixed Test",
  [string]$EnableModIds = "",
  [string]$DisableModIds = "",
  [switch]$ApplyProfileFix,
  [int]$MaxMods = 500,
  [int]$XeditMaxRecords = 2000,
  [int]$XeditMaxPreviewRows = 50,
  [switch]$HashFiles,
  [switch]$NoProfileState,
  [switch]$NoConflicts,
  [switch]$NoReadmeExcerpts,
  [switch]$NoProfileBackup,
  [switch]$NoLogs,
  [switch]$NoRuntimeLogs,
  [switch]$NoPlayReport,
  [switch]$IncludeNexusMetadata,
  [switch]$IncludeXeditReport,
  [switch]$IncludeCollectionReport,
  [switch]$IncludeAllWorkflows,
  [string]$NexusApiKeyFile = "",
  [int]$NexusMaxLookupMods = 80,
  [string]$PythonCommand = "",
  [switch]$NoNexusCache,
  [switch]$NoScanCache
)

$ErrorActionPreference = "Stop"

function Find-Python {
  $explicit = $PythonCommand
  if (!$explicit -and $env:VORTEX_SKYRIMSE_MCP_PYTHON) {
    $explicit = $env:VORTEX_SKYRIMSE_MCP_PYTHON
  }
  if ($explicit) {
    if ($explicit -ieq "py") {
      return @{
        Command = "py"
        Args = @("-3")
      }
    }
    return @{
      Command = $explicit
      Args = @()
    }
  }
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
  if ($IncludeXeditReport) {
    $args += "--include-xedit-report"
  }
  if ($IncludeCollectionReport) {
    $args += "--include-collection-report"
  }
  if ($XeditExe) {
    $args += "--xedit-exe"
    $args += $XeditExe
  }
  if ($PluginName) {
    $args += "--plugin-name"
    $args += $PluginName
  }
  if ($Problem) {
    $args += "--problem"
    $args += $Problem
  }
  if ($WorkflowKey) {
    $args += "--workflow-key"
    $args += $WorkflowKey
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
  if ($NoScanCache) {
    $args += "--no-scan-cache"
  }
  if ($NoRuntimeLogs) {
    $args += "--no-runtime-logs"
  }
  if ($IncludeAllWorkflows) {
    $args += "--include-all-workflows"
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

function Convert-IdList {
  param([string]$Value)
  if (!$Value) {
    return @()
  }
  return @($Value -split "[,;]" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
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
  Write-Host "13. Scan cache status"
  Write-Host "14. xEdit/SSEEdit target helper"
  Write-Host "15. Vortex collection state"
  Write-Host "16. Collection manifest match"
  Write-Host "17. Workflow guide"
  Write-Host "18. Skyrim runtime logs"
  Write-Host "19. Config file validator"
  Write-Host "20. xEdit inspection script"
  Write-Host "21. xEdit inspection result"
  Write-Host "22. Skyrim issue case packet"
  Write-Host "23. Skyrim issue case status"
  Write-Host "24. Append issue case note"
  Write-Host "25. Safe experiment plan"
  Write-Host "26. What should I do now?"
  Write-Host "27. Live Skyrim bridge status"
  Write-Host "28. Import case evidence"
  Write-Host "29. Bundle issue case"
  Write-Host "30. Import case inbox"
  Write-Host "31. Clone profile and apply fixes"
  Write-Host "32. Deployment Doctor"
  Write-Host "33. Launch Doctor"
  Write-Host "34. Reversible Automation Plan"
  Write-Host "35. SKSE Runtime Doctor"
  Write-Host "36. Report Viewer"
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
        include_runtime_logs = (-not $NoRuntimeLogs)
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
        include_runtime_logs = (-not $NoRuntimeLogs)
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
        include_runtime_logs = (-not $NoRuntimeLogs)
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
    { $_ -in @("32", "deployment", "deployment-doctor", "doctor", "deploy-doctor") } {
      $md = Join-Path $script:ReportDir "deployment-doctor-$stamp.md"
      $json = Join-Path $script:ReportDir "deployment-doctor-$stamp.json"
      $argsData = @{
        output_path = $md
      }
      if ($DeploymentBaselinePath) {
        $argsData.baseline_path = $DeploymentBaselinePath
      }
      $argsFile = Write-JsonArgs "deployment-doctor" $argsData
      Invoke-Server (@("--deployment-doctor", "--args-file", $argsFile, "--output-json", $json) + $common)
      Write-Host "Wrote Deployment Doctor Markdown: $md" -ForegroundColor Green
      Write-Host "Wrote Deployment Doctor JSON: $json" -ForegroundColor Green
      Write-Host "This action did not deploy, enable, disable, sort, delete, or edit mods." -ForegroundColor Green
      return
    }
    { $_ -in @("33", "launch", "launch-doctor", "skse-launch", "skse") } {
      $md = Join-Path $script:ReportDir "launch-doctor-$stamp.md"
      $json = Join-Path $script:ReportDir "launch-doctor-$stamp.json"
      Invoke-Server (@("--launch-doctor", "--output-path", $md, "--output-json", $json) + $common)
      Write-Host "Wrote Launch Doctor Markdown: $md" -ForegroundColor Green
      Write-Host "Wrote Launch Doctor JSON: $json" -ForegroundColor Green
      Write-Host "This action did not launch Steam, Skyrim, SKSE, Vortex, or xEdit." -ForegroundColor Green
      return
    }
    { $_ -in @("34", "automation", "automation-plan", "reversible", "reversible-automation") } {
      $request = $Problem
      if (!$request -and !$script:StartedWithAction) {
        $request = Read-Host "Describe the automation you want planned safely"
      }
      $argsData = @{
        request = $request
      }
      $argsFile = Write-JsonArgs "automation-plan" $argsData
      $out = Join-Path $script:ReportDir "reversible-automation-$stamp.json"
      Invoke-Server (@("--automation-plan", "--args-file", $argsFile, "--output-json", $out) + $common)
      Write-Host "Wrote reversible automation plan: $out" -ForegroundColor Green
      Write-Host "This action did not deploy, sort, delete, uninstall, update, edit plugins, or change profiles." -ForegroundColor Green
      return
    }
    { $_ -in @("35", "skse-doctor", "skse-runtime", "runtime-doctor") } {
      $md = Join-Path $script:ReportDir "skse-runtime-doctor-$stamp.md"
      $json = Join-Path $script:ReportDir "skse-runtime-doctor-$stamp.json"
      Invoke-Server (@("--skse-doctor", "--output-path", $md, "--output-json", $json) + $common)
      Write-Host "Wrote SKSE Runtime Doctor Markdown: $md" -ForegroundColor Green
      Write-Host "Wrote SKSE Runtime Doctor JSON: $json" -ForegroundColor Green
      Write-Host "This action did not install SKSE, edit files, deploy mods, or launch Skyrim." -ForegroundColor Green
      return
    }
    { $_ -in @("36", "viewer", "report-viewer", "reports") } {
      $html = Join-Path $script:ReportDir "report-viewer.html"
      $out = Join-Path $script:ReportDir "report-viewer-$stamp.json"
      $argsFile = Write-JsonArgs "report-viewer" @{
        report_dir = $script:ReportDir
        output_path = $html
        include_subdirs = $true
      }
      Invoke-Server (@("--report-viewer", "--args-file", $argsFile, "--output-json", $out) + $common)
      Write-Host "Wrote report viewer HTML: $html" -ForegroundColor Green
      Write-Host "Wrote JSON result: $out" -ForegroundColor Green
      Write-Host "This action only indexes and previews report files." -ForegroundColor Green
      return
    }
    { $_ -in @("13", "cache", "scan-cache") } {
      $out = Join-Path $script:ReportDir "scan-cache-$stamp.json"
      Invoke-Server (@("--tool", "scan_cache_status", "--output-json", $out) + $common)
      Write-Host "Wrote scan cache status: $out" -ForegroundColor Green
      return
    }
    { $_ -in @("14", "xedit", "sseedit") } {
      $formId = $FormId
      $plugin = $PluginName
      if (!$formId -and !$plugin -and !$script:StartedWithAction) {
        $formId = Read-Host "Console-clicked FormID, if any (press Enter to skip)"
      }
      if (!$plugin -and !$script:StartedWithAction) {
        $plugin = Read-Host "Plugin filename, if known (press Enter to skip)"
      }
      $argsData = @{}
      if ($formId) {
        $argsData.form_id = $formId
      }
      if ($plugin) {
        $argsData.plugin_name = $plugin
      }
      $argsFile = Write-JsonArgs "xedit" $argsData
      $out = Join-Path $script:ReportDir "xedit-$stamp.json"
      Invoke-Server (@("--tool", "xedit_diagnostics_report", "--args-file", $argsFile, "--output-json", $out) + $common)
      Write-Host "Wrote xEdit/SSEEdit helper report: $out" -ForegroundColor Green
      Write-Host "This action did not launch xEdit or edit plugins." -ForegroundColor Green
      return
    }
    { $_ -in @("15", "collection", "collections") } {
      $out = Join-Path $script:ReportDir "vortex-collection-$stamp.json"
      Invoke-Server (@("--tool", "vortex_collection_report", "--output-json", $out) + $common)
      Write-Host "Wrote Vortex collection state report: $out" -ForegroundColor Green
      Write-Host "This action did not install, update, or remove collection mods." -ForegroundColor Green
      return
    }
    { $_ -in @("16", "collection-match", "manifest-match") } {
      $manifest = $CollectionManifestPath
      if (!$manifest) {
        if ($script:StartedWithAction) {
          throw "Pass -CollectionManifestPath with -Action collection-match."
        }
        $manifest = Read-Host "Paste the collection manifest JSON path"
      }
      $out = Join-Path $script:ReportDir "collection-match-$stamp.json"
      Invoke-Server (@("--tool", "collection_local_match_report", "--collection-manifest-path", $manifest, "--output-json", $out) + $common)
      Write-Host "Wrote collection manifest match report: $out" -ForegroundColor Green
      Write-Host "This action did not install, update, or remove collection mods." -ForegroundColor Green
      return
    }
    { $_ -in @("17", "workflow", "workflow-guide", "guide") } {
      $problemText = $Problem
      if (!$problemText -and !$WorkflowKey -and !$script:StartedWithAction) {
        $problemText = Read-Host "Describe what you are trying to fix"
      }
      $argsData = @{}
      if ($problemText) {
        $argsData.problem = $problemText
      }
      if ($WorkflowKey) {
        $argsData.workflow_key = $WorkflowKey
      }
      if ($IncludeAllWorkflows) {
        $argsData.include_all = $true
      }
      $argsFile = Write-JsonArgs "workflow-guide" $argsData
      $out = Join-Path $script:ReportDir "workflow-guide-$stamp.json"
      Invoke-Server (@("--workflow-guide", "--args-file", $argsFile, "--output-json", $out) + $common)
      Write-Host "Wrote workflow guide: $out" -ForegroundColor Green
      Write-Host "This action only recommends safe next tools; it did not inspect or change Vortex." -ForegroundColor Green
      return
    }
    { $_ -in @("18", "runtime", "runtime-logs", "skyrim-logs", "papyrus", "skse-logs") } {
      $description = $IssueDescription
      $popup = $PopupText
      if (!$description -and !$script:StartedWithAction) {
        $description = Read-Host "Optional problem/popup description (press Enter to scan logs only)"
      }
      if (!$popup -and !$script:StartedWithAction) {
        $popup = Read-Host "Exact popup text, if any (press Enter to skip)"
      }
      $argsData = @{}
      if ($description) {
        $argsData.description = $description
      }
      if ($popup) {
        $argsData.popup_text = $popup
      }
      $argsFile = Write-JsonArgs "runtime-logs" $argsData
      $out = Join-Path $script:ReportDir "skyrim-runtime-logs-$stamp.json"
      Invoke-Server (@("--runtime-logs", "--args-file", $argsFile, "--output-json", $out) + $common)
      Write-Host "Wrote Skyrim runtime log report: $out" -ForegroundColor Green
      Write-Host "This action did not edit logs, mods, configs, or Vortex." -ForegroundColor Green
      return
    }
    { $_ -in @("19", "config", "config-file", "validate-config") } {
      $config = $ConfigPath
      if (!$config) {
        if ($script:StartedWithAction) {
          throw "Pass -ConfigPath with -Action config."
        }
        $config = Read-Host "Paste the config file path"
      }
      $out = Join-Path $script:ReportDir "config-file-$stamp.json"
      Invoke-Server (@("--tool", "config_file_report", "--path", $config, "--output-json", $out) + $common)
      Write-Host "Wrote config file validation report: $out" -ForegroundColor Green
      Write-Host "This action did not edit the config file." -ForegroundColor Green
      return
    }
    { $_ -in @("20", "xedit-script", "xedit-inspection", "sseedit-script", "sseedit-inspection") } {
      $description = $IssueDescription
      $location = $IssueLocation
      $objectName = $IssueObject
      $formId = $FormId
      $cellName = $Cell
      $baseObjectName = $BaseObject
      $popup = $PopupText
      $plugin = $PluginName
      if (!$description -and !$script:StartedWithAction) {
        $description = Read-Host "Problem description, such as 'bed outside tavern room'"
      }
      if (!$location -and !$script:StartedWithAction) {
        $location = Read-Host "Location, if known (press Enter to skip)"
      }
      if (!$objectName -and !$script:StartedWithAction) {
        $objectName = Read-Host "Object or symptom, if known (press Enter to skip)"
      }
      if (!$formId -and !$script:StartedWithAction) {
        $formId = Read-Host "Console-clicked FormID, if any (press Enter to skip)"
      }
      if (!$plugin -and !$script:StartedWithAction) {
        $plugin = Read-Host "Plugin filename, if known (press Enter to skip)"
      }
      if (!$cellName -and !$script:StartedWithAction) {
        $cellName = Read-Host "Cell name/id, if known (press Enter to skip)"
      }
      if (!$baseObjectName -and !$script:StartedWithAction) {
        $baseObjectName = Read-Host "Base object name/id, if known (press Enter to skip)"
      }
      if (!$popup -and !$script:StartedWithAction) {
        $popup = Read-Host "Popup text, if relevant (press Enter to skip)"
      }
      if (!$description -and !$location -and !$objectName -and !$formId -and !$cellName -and !$baseObjectName -and !$popup -and !$plugin) {
        throw "Pass at least one clue, such as -IssueDescription, -IssueLocation, -IssueObject, -FormId, -PopupText, or -PluginName."
      }
      $scriptPath = $XeditScriptPath
      if (!$scriptPath) {
        $scriptPath = Join-Path $script:ReportDir "xedit-inspection-$stamp.pas"
      }
      $reportPath = $XeditReportPath
      if (!$reportPath) {
        $reportPath = Join-Path $script:ReportDir "xedit-inspection-$stamp.csv"
      }
      $argsData = @{
        output_path = $scriptPath
        report_path = $reportPath
        max_records = $XeditMaxRecords
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
      if ($plugin) {
        $argsData.plugin_name = $plugin
      }
      if ($XeditExe) {
        $argsData.xedit_exe = $XeditExe
      }
      $argsFile = Write-JsonArgs "xedit-inspection" $argsData
      $out = Join-Path $script:ReportDir "xedit-inspection-$stamp.result.json"
      Invoke-Server (@("--tool", "xedit_inspection_script", "--args-file", $argsFile, "--output-json", $out) + $common)
      Write-Host "Wrote xEdit/SSEEdit inspection script: $scriptPath" -ForegroundColor Green
      Write-Host "The script will write CSV evidence here after you run it in xEdit: $reportPath" -ForegroundColor Green
      Write-Host "Next: open SSEEdit, load the candidate plugin or full load order, right-click selected records/plugin, Apply Script, then choose this .pas file." -ForegroundColor Green
      Write-Host "This action wrote only a read-only inspection script; it did not launch xEdit or edit plugins." -ForegroundColor Green
      return
    }
    { $_ -in @("21", "xedit-result", "xedit-results", "xedit-csv", "sseedit-result") } {
      $report = $XeditReportPath
      if (!$report) {
        if ($script:StartedWithAction) {
          throw "Pass -XeditReportPath with -Action xedit-result."
        }
        $report = Read-Host "Paste the xEdit inspection CSV path"
      }
      $argsData = @{
        report_path = $report
        max_preview_rows = $XeditMaxPreviewRows
        allow_any_path = $true
      }
      $argsFile = Write-JsonArgs "xedit-result" $argsData
      $out = Join-Path $script:ReportDir "xedit-result-$stamp.json"
      Invoke-Server (@("--tool", "xedit_inspection_result_report", "--args-file", $argsFile, "--output-json", $out) + $common)
      Write-Host "Wrote xEdit/SSEEdit inspection result report: $out" -ForegroundColor Green
      Write-Host "This action only read the CSV and did not edit plugins." -ForegroundColor Green
      return
    }
    { $_ -in @("22", "issue-case", "case", "case-packet", "investigate", "investigation") } {
      $description = $IssueDescription
      $location = $IssueLocation
      $objectName = $IssueObject
      $formId = $FormId
      $cellName = $Cell
      $baseObjectName = $BaseObject
      $popup = $PopupText
      $plugin = $PluginName
      if (!$description -and !$script:StartedWithAction) {
        $description = Read-Host "Problem description, such as 'bed outside tavern room' or 'popup after loading a save'"
      }
      if (!$location -and !$script:StartedWithAction) {
        $location = Read-Host "Location, if known (press Enter to skip)"
      }
      if (!$objectName -and !$script:StartedWithAction) {
        $objectName = Read-Host "Object or symptom, if known (press Enter to skip)"
      }
      if (!$formId -and !$script:StartedWithAction) {
        $formId = Read-Host "Console-clicked FormID, if any (press Enter to skip)"
      }
      if (!$popup -and !$script:StartedWithAction) {
        $popup = Read-Host "Popup text, if relevant (press Enter to skip)"
      }
      if (!$description -and !$location -and !$objectName -and !$formId -and !$cellName -and !$baseObjectName -and !$popup -and !$plugin) {
        throw "Pass at least one clue, such as -IssueDescription, -IssueLocation, -IssueObject, -FormId, -PopupText, or -PluginName."
      }
      $caseDir = $IssueCaseDir
      if (!$caseDir) {
        $caseDir = Join-Path $script:ReportDir "issue-case-$stamp"
      }
      $argsData = @{
        case_dir = $caseDir
        include_runtime_logs = (-not $NoRuntimeLogs)
        max_mods = $MaxMods
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
      if ($plugin) {
        $argsData.plugin_name = $plugin
      }
      if ($XeditExe) {
        $argsData.xedit_exe = $XeditExe
      }
      $argsFile = Write-JsonArgs "issue-case" $argsData
      $out = Join-Path $script:ReportDir "issue-case-$stamp.result.json"
      Invoke-Server (@("--issue-case", "--args-file", $argsFile, "--output-json", $out) + $common)
      Write-Host "Wrote Skyrim issue case folder: $caseDir" -ForegroundColor Green
      Write-Host "Open issue-case.md in that folder first. If an xEdit script was generated, run it in SSEEdit and parse the CSV with action 21." -ForegroundColor Green
      Write-Host "This action wrote reports and a read-only inspection script only; it did not change Vortex, Skyrim, or plugins." -ForegroundColor Green
      return
    }
    { $_ -in @("23", "issue-case-status", "case-status", "status-case", "case-update", "update-case") } {
      $caseDir = $IssueCaseDir
      if (!$caseDir) {
        if ($script:StartedWithAction) {
          throw "Pass -IssueCaseDir with -Action issue-case-status."
        }
        $caseDir = Read-Host "Paste the issue case folder path"
      }
      $argsData = @{
        case_dir = $caseDir
        max_preview_rows = $XeditMaxPreviewRows
      }
      if ($XeditReportPath) {
        $argsData.report_path = $XeditReportPath
      }
      $argsFile = Write-JsonArgs "issue-case-status" $argsData
      $out = Join-Path $script:ReportDir "issue-case-status-$stamp.result.json"
      Invoke-Server (@("--issue-case-status", "--args-file", $argsFile, "--output-json", $out) + $common)
      Write-Host "Wrote Skyrim issue case status for: $caseDir" -ForegroundColor Green
      Write-Host "Open issue-case-status.md in that folder. This action only read reports/CSV evidence." -ForegroundColor Green
      return
    }
    { $_ -in @("24", "case-note", "note", "append-note") } {
      $caseDir = $IssueCaseDir
      if (!$caseDir) {
        if ($script:StartedWithAction) {
          throw "Pass -IssueCaseDir with -Action case-note."
        }
        $caseDir = Read-Host "Paste the issue case folder path"
      }
      $note = $CaseNote
      if (!$note) {
        if ($script:StartedWithAction) {
          throw "Pass -CaseNote with -Action case-note."
        }
        $note = Read-Host "Note to append"
      }
      $argsData = @{
        case_dir = $caseDir
        note = $note
        kind = $CaseNoteKind
      }
      $argsFile = Write-JsonArgs "issue-case-note" $argsData
      $out = Join-Path $script:ReportDir "issue-case-note-$stamp.result.json"
      Invoke-Server (@("--case-note", "--args-file", $argsFile, "--output-json", $out) + $common)
      Write-Host "Appended case note in: $caseDir" -ForegroundColor Green
      Write-Host "This action wrote only case notes." -ForegroundColor Green
      return
    }
    { $_ -in @("25", "safe-experiment", "experiment-plan", "safe-plan") } {
      $caseDir = $IssueCaseDir
      if (!$caseDir) {
        if ($script:StartedWithAction) {
          throw "Pass -IssueCaseDir with -Action safe-experiment."
        }
        $caseDir = Read-Host "Paste the issue case folder path"
      }
      $argsData = @{
        case_dir = $caseDir
        test_profile_name = $TestProfileName
      }
      if ($ExperimentTargetMod) {
        $argsData.target_mod = $ExperimentTargetMod
      }
      if ($ExperimentTargetModId) {
        $argsData.target_mod_id = $ExperimentTargetModId
      }
      if ($PluginName) {
        $argsData.plugin_name = $PluginName
      }
      $argsFile = Write-JsonArgs "safe-experiment" $argsData
      $out = Join-Path $script:ReportDir "safe-experiment-$stamp.result.json"
      Invoke-Server (@("--safe-experiment-plan", "--args-file", $argsFile, "--output-json", $out) + $common)
      Write-Host "Wrote safe experiment plan for: $caseDir" -ForegroundColor Green
      Write-Host "Open safe-experiment-plan.md. This action did not clone profiles or disable mods." -ForegroundColor Green
      return
    }
    { $_ -in @("26", "what-now", "next", "next-step") } {
      $caseDir = $IssueCaseDir
      if (!$caseDir) {
        if ($script:StartedWithAction) {
          throw "Pass -IssueCaseDir with -Action what-now."
        }
        $caseDir = Read-Host "Paste the issue case folder path"
      }
      $argsData = @{ case_dir = $caseDir }
      $argsFile = Write-JsonArgs "what-now" $argsData
      $out = Join-Path $script:ReportDir "what-now-$stamp.result.json"
      Invoke-Server (@("--what-now", "--args-file", $argsFile, "--output-json", $out) + $common)
      Write-Host "Wrote what-now report for: $caseDir" -ForegroundColor Green
      Write-Host "Open what-now.md. This action did not change mods or profiles." -ForegroundColor Green
      return
    }
    { $_ -in @("27", "live-bridge", "live-status", "bridge-status") } {
      $caseDir = $IssueCaseDir
      $argsData = @{}
      if ($caseDir) {
        $argsData.case_dir = $caseDir
      }
      $argsFile = Write-JsonArgs "live-bridge" $argsData
      $out = Join-Path $script:ReportDir "live-bridge-$stamp.result.json"
      Invoke-Server (@("--live-bridge-status", "--args-file", $argsFile, "--output-json", $out) + $common)
      Write-Host "Wrote live bridge status report." -ForegroundColor Green
      Write-Host "This describes what is implemented now and what a future screenshot/OCR/SKSE bridge needs." -ForegroundColor Green
      return
    }
    { $_ -in @("28", "case-evidence", "evidence", "import-evidence", "live-evidence") } {
      $caseDir = $IssueCaseDir
      if (!$caseDir) {
        if ($script:StartedWithAction) {
          throw "Pass -IssueCaseDir with -Action case-evidence."
        }
        $caseDir = Read-Host "Paste the issue case folder path"
      }
      $text = $EvidenceText
      if (!$text -and !$PopupText -and !$OcrText -and !$ReferenceFormId -and !$BaseFormId -and !$FormId -and !$Cell) {
        if ($script:StartedWithAction) {
          throw "Pass -EvidenceText, -PopupText, -OcrText, -ReferenceFormId, -BaseFormId, -FormId, or -Cell with -Action case-evidence."
        }
        $text = Read-Host "Evidence text, popup OCR, or note"
      }
      $argsData = @{
        case_dir = $caseDir
        evidence_type = $EvidenceKind
      }
      if ($text) {
        $argsData.evidence_text = $text
      }
      if ($PopupText) {
        $argsData.popup_text = $PopupText
      }
      if ($OcrText) {
        $argsData.ocr_text = $OcrText
      }
      if ($ReferenceFormId) {
        $argsData.reference_form_id = $ReferenceFormId
      } elseif ($FormId) {
        $argsData.reference_form_id = $FormId
      }
      if ($BaseFormId) {
        $argsData.base_form_id = $BaseFormId
      }
      if ($Cell) {
        $argsData.cell = $Cell
      }
      if ($IssueObject) {
        $argsData.object = $IssueObject
      }
      if ($ScreenshotPath) {
        $argsData.screenshot_path = $ScreenshotPath
      }
      if ($EvidenceConfidence) {
        $argsData.confidence = $EvidenceConfidence
      }
      $argsFile = Write-JsonArgs "case-evidence" $argsData
      $out = Join-Path $script:ReportDir "case-evidence-$stamp.result.json"
      Invoke-Server (@("--case-evidence", "--args-file", $argsFile, "--output-json", $out) + $common)
      Write-Host "Imported live/case evidence into: $caseDir" -ForegroundColor Green
      Write-Host "This action wrote only case evidence files." -ForegroundColor Green
      return
    }
    { $_ -in @("29", "case-bundle", "bundle-case", "zip-case") } {
      $caseDir = $IssueCaseDir
      if (!$caseDir) {
        if ($script:StartedWithAction) {
          throw "Pass -IssueCaseDir with -Action case-bundle."
        }
        $caseDir = Read-Host "Paste the issue case folder path"
      }
      $argsData = @{ case_dir = $caseDir }
      $argsFile = Write-JsonArgs "case-bundle" $argsData
      $out = Join-Path $script:ReportDir "case-bundle-$stamp.result.json"
      Invoke-Server (@("--case-bundle", "--args-file", $argsFile, "--output-json", $out) + $common)
      Write-Host "Bundled issue case folder: $caseDir" -ForegroundColor Green
      Write-Host "Review the zip before posting publicly; it can include mod names, paths, notes, and popup/OCR text." -ForegroundColor Green
      return
    }
    { $_ -in @("30", "case-inbox", "inbox", "import-inbox") } {
      $caseDir = $IssueCaseDir
      if (!$caseDir) {
        if ($script:StartedWithAction) {
          throw "Pass -IssueCaseDir with -Action case-inbox."
        }
        $caseDir = Read-Host "Paste the issue case folder path"
      }
      $argsData = @{ case_dir = $caseDir }
      if ($InboxDir) {
        $argsData.inbox_dir = $InboxDir
      }
      $argsFile = Write-JsonArgs "case-inbox" $argsData
      $out = Join-Path $script:ReportDir "case-inbox-$stamp.result.json"
      Invoke-Server (@("--case-inbox", "--args-file", $argsFile, "--output-json", $out) + $common)
      Write-Host "Imported new helper evidence from the case inbox." -ForegroundColor Green
      Write-Host "Default inbox: <case folder>\incoming. Reruns skip files already imported by hash." -ForegroundColor Green
      return
    }
    { $_ -in @("31", "safe-profile-fix", "clone-fix", "profile-fix") } {
      $disableIds = Convert-IdList $DisableModIds
      $enableIds = Convert-IdList $EnableModIds
      if ($disableIds.Count -eq 0 -and $enableIds.Count -eq 0) {
        if ($script:StartedWithAction) {
          throw "Pass -DisableModIds and/or -EnableModIds with -Action safe-profile-fix. Use exact Vortex mod ids."
        }
        $entered = Read-Host "Exact Vortex mod ids to disable in the clone (comma-separated)"
        $disableIds = Convert-IdList $entered
      }
      if ($disableIds.Count -eq 0 -and $enableIds.Count -eq 0) {
        throw "No mod ids were provided. Run profile mods/report first to find exact Vortex mod ids."
      }
      $argsData = @{
        new_name = $SafeProfileName
        disable_mod_ids = $disableIds
        enable_mod_ids = $enableIds
      }
      if ($ProfileId) {
        $argsData.source_profile_id = $ProfileId
      }
      if ($ApplyProfileFix) {
        $argsData.apply = $true
      }
      $argsFile = Write-JsonArgs "safe-profile-fix" $argsData
      $out = Join-Path $script:ReportDir "safe-profile-fix-$stamp.result.json"
      Invoke-Server (@("--safe-profile-fix", "--args-file", $argsFile, "--output-json", $out) + $common)
      if ($ApplyProfileFix) {
        Write-Host "Created a cloned profile and applied the requested mod-id fixes to the clone." -ForegroundColor Green
        Write-Host "Open Vortex, select the cloned profile, deploy mods, and test. The original profile was not edited." -ForegroundColor Green
      } else {
        Write-Host "Wrote cloned-profile fix preview." -ForegroundColor Green
        Write-Host "Preview only. Add -ApplyProfileFix after reviewing the result and closing Vortex." -ForegroundColor Green
      }
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
