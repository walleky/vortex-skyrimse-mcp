# Start Here

This is the short path for using the Vortex Skyrim SE MCP with OpenClaw or another stdio MCP client.

## Install

Open PowerShell:

```powershell
cd $env:USERPROFILE\Documents
git clone https://github.com/walleky/vortex-skyrimse-mcp.git
cd vortex-skyrimse-mcp
.\install_windows.ps1
```

Copy the printed MCP config into OpenClaw, then restart OpenClaw.

## No-Hassle Doctor

For the easiest check, double-click:

```text
MCP-Doctor.cmd
```

Or run:

```powershell
.\mcp_doctor.ps1
```

## No-OpenClaw Mod Map

To open the local helper menu, double-click:

```text
Vortex-SkyrimSE-Menu.cmd
```

To make the Markdown collection report directly, double-click:

```text
Make-Mod-Knowledge.cmd
```

Or run:

```powershell
.\make_mod_knowledge.ps1
```

This calls the same `mod_knowledge_report` tool without needing OpenClaw.

MCP Doctor runs the server self-test, runs the MCP handshake smoke test, writes
`openclaw.mcp.generated.json`, prints the OpenClaw registration command, and can
open the OpenClaw config folder. It also writes a transcript log under the MCP
log folder.

To let it register the server through the OpenClaw CLI:

```powershell
.\mcp_doctor.ps1 -RegisterOpenClaw
```

## First Prompts

Start read-only:

```text
Use skyrim_diagnostics_report to write a no-change first report with setup validation, profile backup if possible, modded play health, logs, and Nexus metadata if available. Summarize the top findings and do not apply changes.
```

If OpenClaw is using a slower model or the collection is huge:

```text
Use skyrim_diagnostics_report with performance_mode=slow_model. Read the summary, findings, and nextActions first. Do not apply changes.
```

Or start with only setup:

```text
Use the vortex-skyrimse MCP to run validate_setup, then detect my Skyrim SE/Vortex environment and list the highest-risk problems. Do not apply changes.
```

Then check whether Vortex's active profile is really deployed:

```text
Use skyrim_modded_play_report to tell me why my modded Skyrim SE setup is not launching with the expected Vortex profile. Do not apply changes.
```

Optional Nexus metadata:

```powershell
setx NEXUS_MODS_API_KEY "paste-your-key-here"
```

Close and reopen OpenClaw after setting the variable. The MCP uses your
explicit key only; it does not copy Vortex's key.

To validate the key:

```powershell
py -3 .\server.py --tool nexus_validate_key
```

For redundant mods and conflicts:

```text
Use the vortex-skyrimse MCP to find missing masters, likely redundant mods, and sensitive file conflicts. Do not apply changes yet.
```

For a big collection knowledge map:

```text
Use the vortex-skyrimse MCP to run mod_knowledge_report. Write the Markdown report, summarize the top removal-review candidates, and do not apply changes.
```

For something weird inside the game:

```text
Use skyrim_diagnostics_report with this issue: there is a bed outside the tavern room in the Whiterun Bannered Mare. Include in-game issue candidates and do not apply changes.
```

For annoying popups, just say "popup", "notification", "warning", or similar in the description. The first scan is balanced and checks local file/path/config clues automatically. Exact popup text or a screenshot/OCR can help later, but it is not required for the first scan.

Before changing a Vortex profile:

```text
Use vortex_profile_backup with include_all_profiles=true and tell me where the backup was written. Then show any requested profile change as a dry run first.
```

## Bug Reports

If OpenClaw gets stuck or a tool fails:

```text
Use the vortex-skyrimse MCP to run log_status and bug_report_bundle with zip_output=true and redact_user_paths=true. Then summarize the highest-risk findings and tell me where the zip was written. Do not apply changes.
```

The bundle redacts normal user profile paths by default, but it may still include mod/plugin names and unusual custom paths. Review it before posting publicly.

## Safety Rules

- Most tools are read-only.
- `apply_ini_fixes` writes only when `dry_run=false`.
- `vortex_clone_profile` and `vortex_set_profile_mods` write only when `apply=true`.
- Profile write tools create a profile backup before `apply=true` by default.
- `vortex_profile_restore_plan` previews undo actions by default.
- Close Vortex before profile writes.
- Reopen Vortex afterward, pick the intended profile, then deploy mods before launching Skyrim.

## Quick Test

```powershell
py -3 .\server.py --self-test
py -3 .\tests\smoke_mcp.py
```
