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
Write-Host "Add this MCP server config to $ClientName:"
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
