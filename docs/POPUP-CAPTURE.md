# Popup Screenshot/OCR Capture

`scripts/capture_popup_evidence.ps1` is an optional local helper for the thing
users hate doing: typing popup text by hand.

It captures the visible desktop, saves a screenshot into an issue case
`incoming` folder, and writes a small JSON evidence file that
`skyrim_case_inbox_import` can import. If Tesseract OCR is installed, it also
stores OCR text as `popup_ocr` evidence.

It is read-only for Skyrim, Vortex, MO2, plugins, profiles, and saves. It only
writes files into the case folder you give it.

## Requirements

- Windows PowerShell.
- An existing issue case folder from `skyrim_issue_case_packet`.
- Optional: [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) on PATH,
  or pass `-TesseractPath`.

Without Tesseract, the helper still writes screenshot-note evidence with the
PNG path. OpenClaw can keep the screenshot path in the case and ask for OCR only
if needed.

## Local Menu

The easiest path:

```powershell
.\vortex_skyrimse_menu.ps1 -Action capture-popup -IssueCaseDir "$env:USERPROFILE\Documents\vortex-skyrimse-mcp-reports\issue-case-YYYYMMDD-HHMMSS"
```

The menu waits briefly, captures the screen, imports the JSON evidence, and
writes a live evidence summary result.

Useful options:

```powershell
.\vortex_skyrimse_menu.ps1 -Action capture-popup -IssueCaseDir "C:\path\issue-case" -CaptureDelaySeconds 5
.\vortex_skyrimse_menu.ps1 -Action capture-popup -IssueCaseDir "C:\path\issue-case" -TesseractPath "C:\Program Files\Tesseract-OCR\tesseract.exe"
.\vortex_skyrimse_menu.ps1 -Action capture-popup -IssueCaseDir "C:\path\issue-case" -NoOcr
```

## Direct Helper

```powershell
.\scripts\capture_popup_evidence.ps1 -CaseDir "C:\path\issue-case" -DelaySeconds 3
```

Or double-click/run through:

```text
Capture-Popup-Evidence.cmd -CaseDir "C:\path\issue-case" -DelaySeconds 3
```

After direct helper use, import:

```powershell
py -3 .\server.py --case-inbox --case-dir "C:\path\issue-case"
py -3 .\server.py --case-evidence-report --case-dir "C:\path\issue-case"
```

## OpenClaw Workflow

```text
Use skyrim_issue_case_packet for my popup problem and give me the case folder.
Tell me to run Capture-Popup-Evidence.cmd with that case folder while the popup is visible.
Then call skyrim_case_inbox_import, skyrim_case_evidence_report, and skyrim_case_what_now.
```

If the user already ran menu action 41, OpenClaw can start with:

```text
Use skyrim_case_evidence_report on the case folder. Read latestPopupText and suggestedToolArgs, then continue diagnosis without asking me to retype the popup.
```

## Privacy

The screenshot captures the visible desktop, not only Skyrim. Close or hide
private windows first. Do not post the PNG publicly unless you reviewed it.

For public bug reports, prefer `bug_report_bundle` with redaction and leave
screenshots out unless they are needed.
