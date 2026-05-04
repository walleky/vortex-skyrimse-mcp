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

Write one safe first-response report:

```powershell
py -3 .\server.py --safe-session
```

Write the broadest one-button Skyrim diagnostics report:

```powershell
py -3 .\server.py --skyrim-diagnostics
```

Write a smaller report for a slower OpenClaw model:

```powershell
py -3 .\server.py --skyrim-diagnostics --performance-mode slow_model
```

Generate the collection knowledge report:

```powershell
py -3 .\server.py --mod-knowledge
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

That preview does not change Vortex. Applying a restore requires `--apply`, and Vortex should be closed first.

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

## Safety

Direct CLI mode uses the same tool implementations and safety rules as MCP mode. Read-only tools stay read-only. Write-capable tools still require explicit write arguments such as `dry_run=false` or `apply=true`.

Profile write tools create backups before `--apply` by default. Use `--no-backup-before-apply` only for advanced recovery when you already have a known-good backup.

`in_game_issue_report` is read-only. It searches for likely cause candidates but does not edit plugins, delete objects, or disable mods.

By default it uses the balanced issue scan: mod names, plugin names, readmes,
plugin strings, important file paths, and limited config/text files. Add
`--deep-scan-files` only when you need a slower second pass.

Use `--performance-mode slow_model` when an OpenClaw model is slow or confused
by long JSON. Use `--performance-mode fast` only for a rough first pass.

The scan cache is enabled by default. Use `--no-scan-cache` for a fresh scan if
you just changed many mod files or suspect stale diagnostics.
