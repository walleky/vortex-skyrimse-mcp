# Direct CLI Mode

The project can run without OpenClaw or another MCP client. `server.py` still works as an MCP stdio server by default, but command-line flags let you call the same tools directly from PowerShell.

## Quick Commands

List tools:

```powershell
py -3 .\server.py --list-tools
```

Detect the local setup:

```powershell
py -3 .\server.py --tool detect_environment
```

Generate the collection knowledge report:

```powershell
py -3 .\server.py --mod-knowledge
```

Or double-click:

```text
Make-Mod-Knowledge.cmd
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
