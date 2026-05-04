# Skyrim Runtime Logs

This MCP can read recent Skyrim SE runtime logs and turn them into an
OpenClaw-friendly problem report. The main tool is:

```text
skyrim_runtime_log_report
```

It is read-only. It does not edit mods, deploy Vortex, or change Skyrim.

## What It Reads

When the folders exist, the tool scans recent tails from:

- `Documents\My Games\Skyrim Special Edition\Logs\Script\Papyrus*.log`
- `Documents\My Games\Skyrim Special Edition\SKSE\*.log`
- `Skyrim Special Edition\Data\SKSE\Plugins\*.log`
- `Skyrim Special Edition\Data\NetScriptFramework\Crash\*.txt`
- CrashLogger or Trainwreck-style `.log`/`.txt` files found in the same areas

It looks for terms such as:

- `error`
- `warning`
- `fatal`
- `exception`
- `crash`
- `failed`
- `missing`
- `not found`
- `not configured properly`
- `Address Library`
- SKSE/plugin/DLL load failures

It returns short matching lines only, not whole logs. It also groups repeated
lines into `issueGroups` so OpenClaw can start from likely root-cause patterns
instead of reading log spam line by line.

## How It Finds The Mod

The report extracts referenced filenames from log lines, such as:

```text
Popup UI Mod\config\popup.json
SomePlugin.dll
SomeQuestScript.pex
BrokenPatch.esp
```

Then it indexes the Vortex Skyrim SE staging folder and tries to map those
references back to staged mods. If a line looks config-related, it also returns
`configCandidates` so OpenClaw can read the exact file before proposing a fix.
Candidate configs are validated with `config_file_report` by default, so parse
errors, empty files, placeholder values, loose key/value configs, and obvious
`configured=false` style settings are surfaced directly. For the simple
configured-flag cases, the report may include `suggestedTextPatches` with exact
old/new text for a dry-run `apply_config_text_patch`.

The report also includes `freshLogStatus`. If the newest log is older than the
freshness window, reproduce the problem once and rerun the report.

## Safe Fix Flow

For a popup like "file was not configured properly":

1. Launch Skyrim, reproduce the popup once, then quit.
2. Ask OpenClaw to run `skyrim_runtime_log_report` with your plain description.
3. Start with `issueGroups` and `freshLogStatus`.
4. If `configCandidates` appears, OpenClaw should inspect the candidate validation and then run `config_file_report` or `read_text_file` on the candidate path.
5. If `suggestedTextPatches` exists and the setting makes sense, OpenClaw may propose `apply_config_text_patch` with `dry_run=true`.
6. Apply only after you approve. The patch tool creates a backup by default.
7. Open Vortex, deploy if the edited file is staged by a mod, then test.

`apply_config_text_patch` replaces exact text only. It refuses unknown binary
formats, refuses paths outside detected Vortex/Skyrim roots unless explicitly
allowed, refuses missing `old_text`, and refuses multiple matches unless
`allow_multiple=true`.

## Direct CLI Examples

```powershell
py -3 .\server.py --runtime-logs --description "popup says file was not configured properly"
```

Write the result to JSON:

```powershell
py -3 .\server.py --runtime-logs --description "popup after loading a save" --output-json .\runtime-logs.json
```

Read a candidate config:

```powershell
py -3 .\server.py --tool config_file_report --path "C:\path\to\config\popup.json"
py -3 .\server.py --tool read_text_file --path "C:\path\to\config\popup.json"
```

Preview an exact config patch:

```powershell
py -3 .\server.py --tool apply_config_text_patch --path "C:\path\to\config\popup.json" --old-text "configured=false" --new-text "configured=true"
```

Apply after approval:

```powershell
py -3 .\server.py --tool apply_config_text_patch --path "C:\path\to\config\popup.json" --old-text "configured=false" --new-text "configured=true" --apply
```

## OpenClaw Prompt

```text
Use skyrim_runtime_log_report for my popup problem: "file was not configured properly".
Read any configCandidates with config_file_report, then read_text_file if needed.
If a small config fix is obvious, propose apply_config_text_patch as a dry run first.
Do not edit plugins, delete mods, or disable anything without asking me.
```

## Notes

- Papyrus logs can be noisy. Repeated errors and SKSE/crash/config findings
  matter more than one warning line.
- Crash or DLL load failures often explain symptoms better than downstream
  Papyrus warnings.
- This MCP cannot see the live game window. For visible popups, logs plus a
  plain-language description are the current low-hassle path.
