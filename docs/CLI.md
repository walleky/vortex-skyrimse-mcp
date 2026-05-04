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

Generate the collection knowledge report:

```powershell
py -3 .\server.py --mod-knowledge
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

Or double-click:

```text
Vortex-SkyrimSE-Menu.cmd
Make-Mod-Knowledge.cmd
```

`Vortex-SkyrimSE-Menu.cmd` opens a menu for the common report actions. `Make-Mod-Knowledge.cmd` goes straight to the collection knowledge report.

## Useful Safe Session Options

```powershell
py -3 .\server.py --safe-session --no-profile-backup
```

Use this when Vortex CLI is unavailable or locked. The report still includes setup, play health, optional issue triage, and logs.

```powershell
py -3 .\server.py --safe-session --output-path .\safe-session.md --session-json-path .\safe-session.json
```

Use explicit output paths when attaching the report to a bug or keeping a baseline before experiments.

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

By default it scans mod names, plugin names, plugin strings, and readmes. Add `--deep-scan-files` only when you need slower file-path/config scanning.
