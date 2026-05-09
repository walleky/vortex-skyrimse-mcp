param(
  [Parameter(Mandatory = $true)]
  [string]$CaseDir,
  [string]$TesseractPath = "",
  [string]$Note = "",
  [int]$DelaySeconds = 0,
  [switch]$NoOcr,
  [switch]$IncludeClipboardText
)

$ErrorActionPreference = "Stop"

function New-SafeStamp {
  return (Get-Date).ToString("yyyyMMdd-HHmmss")
}

function Find-Tesseract {
  param([string]$ExplicitPath)
  if ($ExplicitPath) {
    if (!(Test-Path -LiteralPath $ExplicitPath)) {
      throw "TesseractPath was not found: $ExplicitPath"
    }
    return (Resolve-Path -LiteralPath $ExplicitPath).Path
  }
  foreach ($Name in @("tesseract.exe", "tesseract")) {
    $Command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($Command) {
      return $Command.Source
    }
  }
  return $null
}

function Capture-Screenshot {
  param([string]$OutputPath)
  Add-Type -AssemblyName System.Windows.Forms
  Add-Type -AssemblyName System.Drawing
  $Bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
  $Bitmap = New-Object System.Drawing.Bitmap $Bounds.Width, $Bounds.Height
  $Graphics = [System.Drawing.Graphics]::FromImage($Bitmap)
  try {
    $Graphics.CopyFromScreen($Bounds.Left, $Bounds.Top, 0, 0, $Bounds.Size)
    $Bitmap.Save($OutputPath, [System.Drawing.Imaging.ImageFormat]::Png)
  }
  finally {
    $Graphics.Dispose()
    $Bitmap.Dispose()
  }
}

function Run-Ocr {
  param(
    [string]$Executable,
    [string]$ImagePath
  )
  if (!$Executable) {
    return @{
      Status = "not_available"
      Text = ""
      Error = "Tesseract was not found on PATH. Install Tesseract or pass -TesseractPath."
    }
  }
  $ErrFile = [System.IO.Path]::GetTempFileName()
  try {
    $Text = & $Executable $ImagePath stdout --psm 6 2>$ErrFile
    $ErrorText = Get-Content -LiteralPath $ErrFile -Raw -ErrorAction SilentlyContinue
    if ($LASTEXITCODE -ne 0) {
      return @{
        Status = "failed"
        Text = ""
        Error = ($ErrorText.Trim())
      }
    }
    return @{
      Status = "ok"
      Text = (($Text -join "`n").Trim())
      Error = ($ErrorText.Trim())
    }
  }
  finally {
    Remove-Item -LiteralPath $ErrFile -Force -ErrorAction SilentlyContinue
  }
}

$ResolvedCaseDir = Resolve-Path -LiteralPath $CaseDir -ErrorAction SilentlyContinue
if (!$ResolvedCaseDir) {
  throw "CaseDir was not found. Create an issue case first, then pass its folder path."
}
if (!(Test-Path -LiteralPath $ResolvedCaseDir.Path -PathType Container)) {
  throw "CaseDir is not a folder: $CaseDir"
}

$IncomingDir = Join-Path $ResolvedCaseDir.Path "incoming"
New-Item -ItemType Directory -Force -Path $IncomingDir | Out-Null

if ($DelaySeconds -gt 0) {
  Write-Host "Waiting $DelaySeconds second(s). Put the popup on screen now..."
  Start-Sleep -Seconds $DelaySeconds
}

$Stamp = New-SafeStamp
$PngPath = Join-Path $IncomingDir "popup-screenshot-$Stamp.png"
$JsonPath = Join-Path $IncomingDir "popup-ocr-$Stamp.json"

Capture-Screenshot -OutputPath $PngPath

$Ocr = @{
  Status = "skipped"
  Text = ""
  Error = ""
}
if (!$NoOcr) {
  $Tesseract = Find-Tesseract -ExplicitPath $TesseractPath
  $Ocr = Run-Ocr -Executable $Tesseract -ImagePath $PngPath
}

$ClipboardText = ""
if ($IncludeClipboardText) {
  try {
    $ClipboardText = (Get-Clipboard -Raw -ErrorAction Stop).Trim()
  }
  catch {
    $ClipboardText = ""
  }
}

$BestText = ""
if ($Ocr.Text) {
  $BestText = $Ocr.Text
}
elseif ($ClipboardText) {
  $BestText = $ClipboardText
}

$Payload = [ordered]@{
  evidence_type = if ($BestText) { "popup_ocr" } else { "screenshot_note" }
  source = "capture_popup_evidence.ps1"
  captured_at = (Get-Date).ToString("o")
  screenshot_path = $PngPath
  ocr_text = $BestText
  popup_text = $BestText
  note = if ($Note) { $Note } else { "Screenshot captured for Skyrim popup/visible issue evidence." }
  tesseract_status = $Ocr.Status
  tesseract_error = $Ocr.Error
  clipboard_used = [bool](!$Ocr.Text -and $ClipboardText)
}

$Payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $JsonPath -Encoding UTF8

Write-Host "Wrote screenshot: $PngPath" -ForegroundColor Green
Write-Host "Wrote evidence JSON: $JsonPath" -ForegroundColor Green
if ($BestText) {
  Write-Host "Captured text:" -ForegroundColor Green
  Write-Host $BestText
}
else {
  Write-Host "No OCR text captured. The screenshot path is still saved for OpenClaw as screenshot_note evidence." -ForegroundColor Yellow
}
Write-Host "Next: run skyrim_case_inbox_import for this case folder, then skyrim_case_evidence_report." -ForegroundColor Cyan
