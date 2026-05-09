# Direct CLI Mode

The project can run without OpenClaw or another MCP client. `server.py` still works as an MCP stdio server by default, but command-line flags let you call the same tools directly from PowerShell.

## Quick Commands

List tools:

```powershell
py -3 .\server.py --list-tools
```

Detect the local setup:

```powershell
py -3 .\server.py --tool validate_setup
py -3 .\server.py --tool detect_environment
```

When OpenClaw runs inside WSL2 and the game tools are Windows apps:

```bash
python3 server.py --wsl-bridge
python3 server.py --tool validate_setup
```

Ask for the safest workflow from a plain problem:

```powershell
py -3 .\server.py --workflow-guide --problem "mods downloaded but not working"
```

Write one safe first-response report:

```powershell
py -3 .\server.py --safe-session
```

Write the broadest one-button Skyrim diagnostics report:

```powershell
py -3 .\server.py --skyrim-diagnostics
```

Run Mod Organizer 2 diagnostics:

```powershell
py -3 .\server.py --mo2-diagnostics
```

With an explicit MO2 instance/profile:

```powershell
py -3 .\server.py --mo2-diagnostics --mo2-instance-dir "C:\path\to\MO2 instance" --mo2-profile "Default"
```

Check whether the selected Vortex profile is actually deployed:

```powershell
py -3 .\server.py --deployment-doctor
```

Keep a readable Deployment Doctor report:

```powershell
py -3 .\server.py --deployment-doctor --output-path ".\deployment-doctor.md" --output-json ".\deployment-doctor.json"
```

Compare after deploying in Vortex:

```powershell
py -3 .\server.py --deployment-doctor --baseline-path ".\deployment-doctor-before.json" --output-path ".\deployment-doctor-after.md" --output-json ".\deployment-doctor-after.json"
```

Check whether the next launch should use SKSE, Steam/vanilla, or wait:

```powershell
py -3 .\server.py --launch-doctor
```

Keep a readable Launch Doctor report:

```powershell
py -3 .\server.py --launch-doctor --output-path ".\launch-doctor.md" --output-json ".\launch-doctor.json"
```

Check SKSE/runtime compatibility:

```powershell
py -3 .\server.py --skse-doctor
```

Keep a readable SKSE Runtime Doctor report:

```powershell
py -3 .\server.py --skse-doctor --output-path ".\skse-runtime-doctor.md" --output-json ".\skse-runtime-doctor.json"
```

Plan risky automation without applying changes:

```powershell
py -3 .\server.py --automation-plan --request "disable redundant mods, sort load order, and keep it revertable"
```

Check what OpenClaw should do while Vortex is open:

```powershell
py -3 .\server.py --vortex-open-status
```

Write a smaller report for a slower OpenClaw model:

```powershell
py -3 .\server.py --skyrim-diagnostics --performance-mode slow_model
```

Generate the collection knowledge report:

```powershell
py -3 .\server.py --mod-knowledge
```

Run common stack/dependency rules:

```powershell
py -3 .\server.py --known-rules
```

Check the local scan cache:

```powershell
py -3 .\server.py --tool scan_cache_status
```

Triage an in-game object problem:

```powershell
py -3 .\server.py --tool in_game_issue_report --description "bed outside tavern room" --location "Whiterun Bannered Mare" --object "bed"
```

Include the same issue inside a safe session:

```powershell
py -3 .\server.py --safe-session --description "bed outside tavern room" --location "Whiterun Bannered Mare" --object "bed"
```

With stronger console evidence:

```powershell
py -3 .\server.py --tool in_game_issue_report --description "bad bed placement" --location "Whiterun Bannered Mare" --object "bed" --form-id "1200ABCD" --base-object "CommonBed01"
```

Get a read-only xEdit/SSEEdit target hint from the same FormID:

```powershell
py -3 .\server.py --tool xedit_diagnostics_report --form-id "1200ABCD"
```

Generate a read-only xEdit inspection script and parse its CSV after running it
inside xEdit:

```powershell
py -3 .\server.py --tool xedit_inspection_script --description "bed outside tavern room" --location "Whiterun Bannered Mare" --object "bed" --form-id "1200ABCD"
py -3 .\server.py --tool xedit_inspection_result_report --report-path "C:\path\to\OpenClawSkyrimInspector.csv" --allow-any-path
```

Create a one-folder issue investigation packet:

```powershell
py -3 .\server.py --issue-case --description "bed outside tavern room" --location "Whiterun Bannered Mare" --object "bed" --form-id "1200ABCD"
py -3 .\server.py --issue-case --description "popup after loading a save" --include-runtime-logs --case-dir ".\reports\popup-case"
```

After running the generated xEdit script from a case folder:

```powershell
py -3 .\server.py --issue-case-status --case-dir ".\reports\popup-case"
py -3 .\server.py --issue-case-status --case-dir ".\reports\popup-case" --report-path "C:\path\to\xedit-inspection.csv"
```

Case notes, next-step summary, and safe experiment plan:

```powershell
py -3 .\server.py --case-note --case-dir ".\reports\popup-case" --note-kind test --note "Disabled nothing yet; xEdit points at PopupMod.esp."
py -3 .\server.py --what-now --case-dir ".\reports\popup-case"
py -3 .\server.py --safe-experiment-plan --case-dir ".\reports\popup-case" --target-mod "Popup UI Mod"
py -3 .\server.py --live-bridge-status --case-dir ".\reports\popup-case"
```

Import live/captured evidence and bundle the case:

```powershell
py -3 .\server.py --case-evidence --case-dir ".\reports\popup-case" --evidence-kind popup_ocr --ocr-text "file was not configured properly"
py -3 .\server.py --case-evidence --case-dir ".\reports\bed-case" --evidence-kind console --reference-form-id "0100ABCD" --base-form-id "00001234" --cell "WhiterunBanneredMare"
.\scripts\capture_popup_evidence.ps1 -CaseDir ".\reports\popup-case" -DelaySeconds 3
py -3 .\server.py --case-inbox --case-dir ".\reports\popup-case"
py -3 .\server.py --case-inbox --case-dir ".\reports\popup-case" --inbox-dir ".\reports\popup-case\incoming" --dry-run
py -3 .\server.py --case-bundle --case-dir ".\reports\popup-case"
```

The default inbox is `<case folder>\incoming`. Helper tools can drop `.json`,
`.txt`, `.log`, or `.md` files there. Re-running `--case-inbox` skips files that
already appear in `live-evidence-index.json`.

Triage an annoying popup:

```powershell
py -3 .\server.py --tool in_game_issue_report --description "annoying popup after loading a save"
```

The default issue scan is balanced: it checks names, plugins, readmes, plugin
strings, important file paths, and a small number of config/text files.

Exact popup text is optional second-pass evidence:

```powershell
py -3 .\server.py --tool in_game_issue_report --description "popup after loading a save" --popup-text "paste exact popup text here"
```

If the first result is weak, use the slower deep scan:

```powershell
py -3 .\server.py --tool in_game_issue_report --description "annoying popup after loading a save" --scan-mode deep
```

Read Skyrim runtime logs for a popup/config error:

```powershell
py -3 .\server.py --runtime-logs --description "popup says file was not configured properly"
```

If the report returns `configCandidates`, read the exact file:

```powershell
py -3 .\server.py --tool config_file_report --path "C:\path\to\config\popup.json"
py -3 .\server.py --tool read_text_file --path "C:\path\to\config\popup.json"
```

`config_file_report` is read-only. Check `healthFindings` and
`suggestedTextPatches`; the suggestions are exact old/new text for a dry-run
patch, not permission to write.

Preview an exact config patch:

```powershell
py -3 .\server.py --tool apply_config_text_patch --path "C:\path\to\config\popup.json" --old-text "configured=false" --new-text "configured=true"
```

Apply only after approval:

```powershell
py -3 .\server.py --tool apply_config_text_patch --path "C:\path\to\config\popup.json" --old-text "configured=false" --new-text "configured=true" --apply
```

Return compact JSON for a slower model:

```powershell
py -3 .\server.py --tool in_game_issue_report --description "annoying popup after loading a save" --response-mode compact
```

Or double-click:

```text
Vortex-SkyrimSE-Menu.cmd
Make-Mod-Knowledge.cmd
```

`Vortex-SkyrimSE-Menu.cmd` opens a menu for the common report actions. `Make-Mod-Knowledge.cmd` goes straight to the collection knowledge report.

## Nexus Metadata

Nexus support is optional and read-only. Set `NEXUS_MODS_API_KEY` or pass a key
file. The MCP does not copy Vortex's key.

```powershell
py -3 .\server.py --tool nexus_validate_key
py -3 .\server.py --skyrim-diagnostics --include-nexus-metadata
py -3 .\server.py --tool nexus_update_report --include-nexus-metadata
```

For a key file:

```powershell
py -3 .\server.py --tool nexus_validate_key --nexus-api-key-file "$env:USERPROFILE\.vortex-skyrimse-mcp\nexus-api-key.txt"
```

## Collection Diagnostics

Inspect Vortex collection-like state:

```powershell
py -3 .\server.py --tool vortex_collection_report
```

Compare a manifest-like JSON file to local Nexus metadata:

```powershell
py -3 .\server.py --tool collection_local_match_report --collection-manifest-path "C:\path\collection.json"
```

These commands are read-only. They do not install, update, remove, or deploy
collection mods.

## Useful Safe Session Options

```powershell
py -3 .\server.py --safe-session --no-profile-backup
```

Use this when Vortex CLI is unavailable or locked. The report still includes setup, play health, optional issue triage, and logs.

```powershell
py -3 .\server.py --safe-session --output-path .\safe-session.md --session-json-path .\safe-session.json
```

Use explicit output paths when attaching the report to a bug or keeping a baseline before experiments.

Include optional xEdit or collection context:

```powershell
py -3 .\server.py --skyrim-diagnostics --include-xedit-report --form-id "1200ABCD"
py -3 .\server.py --skyrim-diagnostics --include-collection-report
```

## Useful Mod Knowledge Options

```powershell
py -3 .\server.py --mod-knowledge --hash-files
```

`--hash-files` is slower but gives stronger duplicate evidence.

```powershell
py -3 .\server.py --mod-knowledge --staging-dir "D:\Vortex Mods\skyrimse\mods"
```

Use explicit paths when detection misses a custom setup.

```powershell
py -3 .\server.py --mod-knowledge --no-profile-state
```

Use this when Vortex CLI is slow, locked, or unavailable. The report will still inspect staged files, conflicts, plugins, readmes, and duplicate evidence.

## Profile Backup And Restore Preview

Create a profile backup before experiments:

```powershell
py -3 .\server.py --tool vortex_profile_backup --include-all-profiles --backup-path .\profile-backup.json
```

Preview restoring from that backup:

```powershell
py -3 .\server.py --tool vortex_profile_restore_plan --backup-path .\profile-backup.json
```

That preview does not change Vortex. Applying a restore requires `--apply`.
Vortex should be closed when possible. If you want Vortex left open, run
`--vortex-open-status` first, then pass `--allow-running-vortex` and read
`postApplyVerification` in the JSON result.

Clone the active profile and preview a fix on the clone only:

```powershell
py -3 .\server.py --safe-profile-fix --new-profile-name "OpenClaw Fixed Test" --disable-mod-id "exact-vortex-mod-id"
```

After reviewing the preview, apply the clone-only fix:

```powershell
py -3 .\server.py --safe-profile-fix --new-profile-name "OpenClaw Fixed Test" --disable-mod-id "exact-vortex-mod-id" --apply
```

If Vortex must stay open while you watch the profile appear, make that explicit:

```powershell
py -3 .\server.py --safe-profile-fix --new-profile-name "OpenClaw Fixed Test" --disable-mod-id "exact-vortex-mod-id" --apply --allow-running-vortex --output-json .\safe-profile-fix-result.json
```

This creates a backup by default, writes a new profile, changes only that new
profile's mod enabled state, and leaves the original profile alone. Open Vortex
afterward, select the clone, deploy mods, and test.

When `--allow-running-vortex` is used, the result includes
`postApplyVerification`. If Vortex does not visibly update, switch profiles or
restart Vortex, then deploy mods.

## JSON Arguments

For advanced calls, pass tool arguments as JSON:

```powershell
py -3 .\server.py --tool bug_report_bundle --args-json "{`"zip_output`":true,`"redact_user_paths`":true}"
```

For easier quoting, use a file:

```json
{
  "zip_output": true,
  "redact_user_paths": true
}
```

Then run:

```powershell
py -3 .\server.py --tool bug_report_bundle --args-file .\bug-report-args.json
```

## Saving Tool Results

Some tools write their own report files, such as `mod_knowledge_report`. You can also save the direct JSON result:

```powershell
py -3 .\server.py --mod-knowledge --output-json .\last-tool-result.json
```

## Report Viewer

Create a static HTML index of generated reports:

```powershell
py -3 .\server.py --report-viewer
```

Use a custom folder:

```powershell
py -3 .\server.py --report-viewer --report-dir "$env:USERPROFILE\Documents\vortex-skyrimse-mcp-reports"
```

The viewer writes `report-viewer.html` by default. It previews report files only;
it does not open Vortex, deploy mods, launch Skyrim, or edit profiles.

## Case Evidence Summary

After importing popup OCR, console FormID, cell, object, or screenshot-note
evidence into an issue case folder:

```powershell
py -3 .\server.py --case-evidence-report --case-dir "$env:USERPROFILE\Documents\vortex-skyrimse-mcp-reports\issue-case-YYYYMMDD-HHMMSS"
```

This writes `live-evidence-summary.md` in the case folder and returns suggested
next diagnostic calls. It does not change Vortex, Skyrim, plugins, profiles, or
mods.

## Safety

Direct CLI mode uses the same tool implementations and safety rules as MCP mode. Read-only tools stay read-only. Write-capable tools still require explicit write arguments such as `dry_run=false` or `apply=true`.

Profile write tools create backups before `--apply` by default. Use `--no-backup-before-apply` only for advanced recovery when you already have a known-good backup.

`in_game_issue_report` is read-only. It searches for likely cause candidates but does not edit plugins, delete objects, or disable mods.

`skyrim_runtime_log_report` is read-only. `apply_config_text_patch` is write-capable but exact-text only, dry-run by default, restricted to detected Vortex/Skyrim roots, and backed up by default.

By default it uses the balanced issue scan: mod names, plugin names, readmes,
plugin strings, important file paths, and limited config/text files. Add
`--deep-scan-files` only when you need a slower second pass.

Use `--performance-mode slow_model` when an OpenClaw model is slow or confused
by long JSON. Use `--performance-mode fast` only for a rough first pass.

The scan cache is enabled by default. Use `--no-scan-cache` for a fresh scan if
you just changed many mod files or suspect stale diagnostics.

Use `--scan-cache-max-entries 5000` only if `scan_cache_status` shows a cache
that is too large for the machine. The default is 10,000 entries.
