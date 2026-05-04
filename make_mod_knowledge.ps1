param(
  [string]$OutputPath = "",
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
  throw "Python 3 was not found. Install Python for Windows, then rerun this script."
}

$Server = Join-Path $PSScriptRoot "server.py"
if (!(Test-Path -LiteralPath $Server)) {
  throw "server.py was not found beside make_mod_knowledge.ps1."
}

$Python = Find-Python
$RunArgs = @()
$RunArgs += $Python.Args
$RunArgs += $Server
$RunArgs += "--mod-knowledge"
$RunArgs += "--max-mods"
$RunArgs += "$MaxMods"

if ($OutputPath) {
  $RunArgs += "--output-path"
  $RunArgs += $OutputPath
}
if ($StagingDir) {
  $RunArgs += "--staging-dir"
  $RunArgs += $StagingDir
}
if ($SkyrimDir) {
  $RunArgs += "--skyrim-dir"
  $RunArgs += $SkyrimDir
}
if ($VortexExe) {
  $RunArgs += "--vortex-exe"
  $RunArgs += $VortexExe
}
if ($ProfileId) {
  $RunArgs += "--profile-id"
  $RunArgs += $ProfileId
}
if ($HashFiles) {
  $RunArgs += "--hash-files"
}
if ($NoProfileState) {
  $RunArgs += "--no-profile-state"
}
if ($NoConflicts) {
  $RunArgs += "--no-conflicts"
}
if ($NoReadmeExcerpts) {
  $RunArgs += "--no-readme-excerpts"
}

Write-Host ""
Write-Host "Creating Skyrim SE mod knowledge report..." -ForegroundColor Cyan
Write-Host "Running: $($Python.Command) $($RunArgs -join ' ')"
Write-Host ""

& $Python.Command @RunArgs
if ($LASTEXITCODE -ne 0) {
  throw "mod_knowledge_report failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Done. Ask OpenClaw to read the Markdown report and summarize the removal-review candidates."
