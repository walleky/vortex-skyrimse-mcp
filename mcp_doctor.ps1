param(
  [string]$ClientName = "OpenClaw",
  [string]$ConfigOut = "",
  [switch]$RegisterOpenClaw,
  [switch]$OpenConfigFolder
)

$ErrorActionPreference = "Stop"

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "== $Message" -ForegroundColor Cyan
}

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
  throw "Python 3 was not found. Install Python for Windows, then rerun MCP Doctor."
}

function Invoke-Checked {
  param(
    [string]$Command,
    [string[]]$Arguments,
    [string]$Label
  )

  Write-Host "Running: $Command $($Arguments -join ' ')"
  & $Command @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "$Label failed with exit code $LASTEXITCODE"
  }
}

function Resolve-TildePath {
  param([string]$Path)

  if (!$Path) {
    return $Path
  }
  if ($Path -eq "~") {
    return $env:USERPROFILE
  }
  if ($Path.StartsWith("~/") -or $Path.StartsWith("~\")) {
    return Join-Path $env:USERPROFILE $Path.Substring(2)
  }
  return $Path
}

function Get-McpLogDir {
  if ($env:VORTEX_SKYRIMSE_MCP_LOG_DIR) {
    return Resolve-TildePath $env:VORTEX_SKYRIMSE_MCP_LOG_DIR
  }
  $base = $env:LOCALAPPDATA
  if (!$base) {
    $base = $env:APPDATA
  }
  if (!$base) {
    $base = $env:USERPROFILE
  }
  return Join-Path $base "vortex-skyrimse-mcp\logs"
}

function Get-OpenClawConfigFolder {
  $openclaw = Get-Command openclaw -ErrorAction SilentlyContinue
  if ($openclaw) {
    try {
      $configFile = (& openclaw config file 2>$null | Select-Object -First 1)
      if ($configFile) {
        $configFile = $configFile.Trim()
        if ($configFile) {
          $configFile = Resolve-TildePath $configFile
          return Split-Path -Parent $configFile
        }
      }
    } catch {
      Write-Host "OpenClaw CLI was found, but 'openclaw config file' did not return a path."
    }
  }

  if ($env:OPENCLAW_CONFIG_PATH) {
    return Split-Path -Parent $env:OPENCLAW_CONFIG_PATH
  }

  return Join-Path $env:USERPROFILE ".openclaw"
}

$script:TranscriptStarted = $false
$script:DoctorLogPath = $null
$LogDir = Get-McpLogDir
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$script:DoctorLogPath = Join-Path $LogDir ("doctor-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
try {
  Start-Transcript -Path $script:DoctorLogPath -Force | Out-Null
  $script:TranscriptStarted = $true
} catch {
  Write-Host "Warning: could not start MCP Doctor transcript: $($_.Exception.Message)"
}

trap {
  if ($script:TranscriptStarted) {
    try {
      Stop-Transcript | Out-Null
      Write-Host "MCP Doctor log: $script:DoctorLogPath"
    } catch {
    }
  }
  throw
}

$Server = Join-Path $PSScriptRoot "server.py"
$SmokeTest = Join-Path $PSScriptRoot "tests\smoke_mcp.py"

if (!(Test-Path -LiteralPath $Server)) {
  throw "server.py was not found beside MCP Doctor."
}
if (!(Test-Path -LiteralPath $SmokeTest)) {
  throw "tests\smoke_mcp.py was not found beside MCP Doctor."
}

$Python = Find-Python
$ServerArgs = @()
$ServerArgs += $Python.Args
$ServerArgs += $Server

$ServerDefinition = [ordered]@{
  command = $Python.Command
  args = $ServerArgs
}

$GenericSnippet = [ordered]@{
  mcpServers = [ordered]@{
    "vortex-skyrimse" = $ServerDefinition
  }
}

if (!$ConfigOut) {
  $ConfigOut = Join-Path $PSScriptRoot "openclaw.mcp.generated.json"
}

Write-Step "Vortex Skyrim SE MCP Doctor"
Write-Host "Server: $Server"
Write-Host "Python: $($Python.Command) $($Python.Args -join ' ')"
Write-Host "Log folder: $LogDir"
Write-Host "Doctor log: $script:DoctorLogPath"

Write-Step "Self-test"
$SelfTestArgs = @()
$SelfTestArgs += $Python.Args
$SelfTestArgs += $Server
$SelfTestArgs += "--self-test"
Invoke-Checked $Python.Command $SelfTestArgs "server.py --self-test"

Write-Step "MCP stdio smoke test"
$SmokeArgs = @()
$SmokeArgs += $Python.Args
$SmokeArgs += $SmokeTest
Invoke-Checked $Python.Command $SmokeArgs "MCP smoke test"

Write-Step "Config snippet"
$SnippetJson = $GenericSnippet | ConvertTo-Json -Depth 8
Set-Content -LiteralPath $ConfigOut -Value $SnippetJson -Encoding UTF8
Write-Host "Wrote generic MCP config snippet:"
Write-Host "  $ConfigOut"
Write-Host ""
Write-Host $SnippetJson

$OpenClawServerJson = $ServerDefinition | ConvertTo-Json -Depth 8 -Compress
$OpenClawConfigFolder = Get-OpenClawConfigFolder

Write-Step "OpenClaw"
if (Get-Command openclaw -ErrorAction SilentlyContinue) {
  Write-Host "OpenClaw CLI: found"
  Write-Host "OpenClaw config folder: $OpenClawConfigFolder"
  Write-Host ""
  Write-Host "Manual register command:"
  Write-Host "  openclaw mcp set vortex-skyrimse '$OpenClawServerJson'"

  if ($RegisterOpenClaw) {
    Write-Host ""
    Write-Host "Registering MCP server through OpenClaw..."
    & openclaw mcp set vortex-skyrimse $OpenClawServerJson
    if ($LASTEXITCODE -ne 0) {
      throw "openclaw mcp set failed with exit code $LASTEXITCODE"
    }
    Write-Host "Registered vortex-skyrimse in OpenClaw."
  }
} else {
  Write-Host "OpenClaw CLI: not found"
  Write-Host "OpenClaw config folder guess: $OpenClawConfigFolder"
  Write-Host "Copy the generated JSON snippet into your MCP client config."
}

if ($OpenConfigFolder) {
  New-Item -ItemType Directory -Force -Path $OpenClawConfigFolder | Out-Null
  Invoke-Item $OpenClawConfigFolder
}

Write-Step "Done"
Write-Host "Restart $ClientName after adding or changing MCP config."
Write-Host "Logs:"
Write-Host "  $LogDir"
$DirectPython = ("$($Python.Command) $($Python.Args -join ' ')").Trim()
Write-Host "Direct CLI:"
Write-Host "  $DirectPython `"$Server`" --tool validate_setup"
Write-Host "  $DirectPython `"$Server`" --tool detect_environment"
Write-Host "  $DirectPython `"$Server`" --tool in_game_issue_report --description `"bed outside tavern room`" --location `"Whiterun Bannered Mare`" --object `"bed`""
Write-Host "  .\vortex_skyrimse_menu.ps1"
Write-Host "  .\make_mod_knowledge.ps1"
Write-Host "First prompt:"
Write-Host "  Use the vortex-skyrimse MCP to run validate_setup, then detect my Skyrim SE/Vortex environment and list the highest-risk problems. Do not apply changes."
Write-Host "Collection knowledge prompt:"
Write-Host "  Use the vortex-skyrimse MCP to run mod_knowledge_report. Summarize the top removal-review candidates. Do not apply changes."
Write-Host "Bug report prompt:"
Write-Host "  Use the vortex-skyrimse MCP to run log_status and bug_report_bundle with zip_output=true and redact_user_paths=true. Then summarize the highest-risk findings and tell me where the zip was written. Do not apply changes."

if ($script:TranscriptStarted) {
  Stop-Transcript | Out-Null
  $script:TranscriptStarted = $false
  Write-Host "MCP Doctor log: $script:DoctorLogPath"
}
