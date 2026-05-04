# Vortex Skyrim SE MCP

[![CI](https://github.com/walleky/vortex-skyrimse-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/walleky/vortex-skyrimse-mcp/actions/workflows/ci.yml)

Local MCP server for Windows Vortex + Skyrim Special Edition diagnostics.

It is built for an MCP client such as OpenClaw, Claude Desktop, Cursor, or any
stdio MCP client. The server is dependency-free Python and talks newline-delimited
JSON-RPC over stdin/stdout.

## What It Can Do

- Find Steam, Skyrim SE, Vortex AppData, Vortex staging folders, `plugins.txt`,
  `loadorder.txt`, SKSE, and common missing-path problems.
- Inventory Vortex-staged Skyrim SE mods.
- Read mod evidence: files, readmes, FOMOD XML, plugins, masters, BSA archives,
  SKSE DLL plugins, scripts, meshes, textures, UI files.
- Detect likely redundant mods:
  - duplicate plugin names
  - duplicate Nexus IDs when metadata is present
  - file-set subsets, optionally using SHA-256 hashes
- Detect loose-file conflicts between staged mods.
- Detect missing masters and enabled plugins that are missing on disk.
- Inspect Skyrim INI settings and apply a narrow safe set of INI fixes with
  backups. INI writes are dry-run by default.
- Read Vortex profiles through Vortex's own CLI, show the active-profile guess,
  list enabled/disabled mods per profile, compare profiles, and clone a profile
  for safer testing.
- Check whether plugins from the selected Vortex profile appear in Skyrim
  `Data` and are enabled in `plugins.txt`.
- Produce a one-shot modded play report that combines environment, SKSE, audio
  archive, profile deployment, plugin, and INI checks into prioritized findings.
- Enable or disable exact Vortex mod ids in a selected profile only when
  `apply=true`. This is dry-run by default and never deletes mods.
- Write a JSON report that another agent can analyze.
- Write MCP logs by area (`server`, `tool`, `vortex-cli`, `support`) and create
  a bug-report bundle with recent log tails.

## Documentation

- [START-HERE.md](START-HERE.md): short install, first prompts, and MCP Doctor.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): code map and runtime flow.
- [docs/OPENCLAW-AGENT-GUIDE.md](docs/OPENCLAW-AGENT-GUIDE.md): how an OpenClaw agent should use the tools safely.
- [docs/LOGGING.md](docs/LOGGING.md): log folder, channels, and inspection commands.
- [docs/BUG-REPORTING.md](docs/BUG-REPORTING.md): support bundle and issue-reporting guide.
- [docs/MOD-KNOWLEDGE.md](docs/MOD-KNOWLEDGE.md): collection knowledge reports and safe removal review.
- [docs/SAMPLE-BUG-BUNDLE.md](docs/SAMPLE-BUG-BUNDLE.md): sanitized example support bundle shape.
- [docs/ROADMAP.md](docs/ROADMAP.md): improvement notes and what not to automate yet.

## What It Will Not Do Automatically

It does not blindly delete mods, disable plugins, rewrite conflict rules, or sort
load order. Vortex conflict rules and load-order changes are high-risk because
the wrong winner can break a save. Profile write tools require exact mod ids and
are dry-run unless `apply=true`.

## Install

Short version: see [START-HERE.md](START-HERE.md).

1. Install Python 3 for Windows if you do not already have it.
2. Download or clone this repo somewhere stable, for example:

```powershell
cd $env:USERPROFILE\Documents
git clone https://github.com/walleky/vortex-skyrimse-mcp.git
cd vortex-skyrimse-mcp
```

Or keep the folder at:

```text
C:\Users\<you>\Documents\vortex-skyrimse-mcp
```

3. In PowerShell:

```powershell
cd C:\Users\<you>\Documents\vortex-skyrimse-mcp
.\install_windows.ps1
```

The installer prints an MCP config snippet.

## MCP Doctor

For a no-hassle check, run:

```powershell
.\mcp_doctor.ps1
```

Or double-click:

```text
MCP-Doctor.cmd
```

MCP Doctor runs the self-test, runs the MCP stdio smoke test, writes
`openclaw.mcp.generated.json`, prints the OpenClaw registration command, and can
open the OpenClaw config folder. To register through the OpenClaw CLI:

```powershell
.\mcp_doctor.ps1 -RegisterOpenClaw
```

## MCP Client Config

Generic stdio MCP config:

```json
{
  "mcpServers": {
    "vortex-skyrimse": {
      "command": "py",
      "args": [
        "-3",
        "C:\\Users\\<you>\\Documents\\vortex-skyrimse-mcp\\server.py"
      ]
    }
  }
}
```

Restart OpenClaw after adding the server.

## First OpenClaw Prompts

Try:

```text
Use the vortex-skyrimse MCP to detect my Skyrim SE/Vortex environment and list the highest-risk problems.
```

Then:

```text
Use the vortex-skyrimse MCP to find missing masters, likely redundant mods, and sensitive file conflicts. Do not apply changes yet.
```

For profiles:

```text
Use the vortex-skyrimse MCP to list my Skyrim SE Vortex profiles, identify the active one, and show enabled mods on that profile.
```

To make a safer test profile:

```text
Use vortex_clone_profile to clone my active Skyrim SE profile as "OpenClaw Safe Test". Keep it as a dry run first.
```

For deployment/profile mismatch:

```text
Use vortex_profile_deployment_report to check whether my active Skyrim SE Vortex profile is actually deployed and enabled in plugins.txt. Do not apply changes.
```

For a single no-hassle diagnosis:

```text
Use skyrim_modded_play_report to tell me why my modded Skyrim SE setup is not launching with the expected Vortex profile. Do not apply changes.
```

For a large collection map:

```text
Use mod_knowledge_report to write a Markdown report explaining what each Skyrim SE mod appears to do, how it fits into the collection, and which mods are safe candidates to review for disabling. Do not apply changes.
```

For INI fixes:

```text
Use the vortex-skyrimse MCP to show Skyrim INI fixes as a dry run.
```

To apply only the narrow INI fixes:

```text
Use apply_ini_fixes with dry_run=false and make_backup=true.
```

## Tools

- `detect_environment`
- `inventory_mods`
- `analyze_conflicts`
- `redundant_mod_report`
- `plugin_report`
- `mod_evidence`
- `mod_knowledge_report`
- `ini_report`
- `apply_ini_fixes`
- `read_text_file`
- `vortex_cli_get`
- `vortex_profile_report`
- `vortex_profile_mods`
- `vortex_compare_profiles`
- `vortex_profile_deployment_report`
- `vortex_clone_profile`
- `vortex_set_profile_mods`
- `skyrim_modded_play_report`
- `suggest_conflict_fixes`
- `log_status`
- `bug_report_bundle`
- `write_report`

Every path-taking tool accepts explicit override paths, which helps if Vortex is
using a custom staging folder.

## Path Overrides

Useful Windows paths:

```text
Vortex AppData:
%APPDATA%\Vortex

Typical Vortex Skyrim SE staging:
%APPDATA%\Vortex\skyrimse\mods

Skyrim SE Steam folder:
C:\Program Files (x86)\Steam\steamapps\common\Skyrim Special Edition

Plugins file:
%LOCALAPPDATA%\Skyrim Special Edition\plugins.txt

Skyrim INIs:
%USERPROFILE%\Documents\My Games\Skyrim Special Edition
```

If detection misses your setup, pass `skyrim_dir`, `staging_dir`,
`vortex_appdata`, `local_appdata`, or `my_games_dir` to the relevant tool.

## Safety Model

- `detect_environment`, `inventory_mods`, `analyze_conflicts`,
  `redundant_mod_report`, `plugin_report`, `mod_evidence`,
  `mod_knowledge_report`, `ini_report`,
  `read_text_file`, `vortex_cli_get`, `vortex_profile_report`,
  `vortex_profile_mods`, `vortex_compare_profiles`,
  `vortex_profile_deployment_report`, `skyrim_modded_play_report`,
  `suggest_conflict_fixes`, `log_status`, `bug_report_bundle`, and
  `write_report` do not modify Vortex or Skyrim.
- `apply_ini_fixes` can write INI files only when `dry_run=false`.
- `apply_ini_fixes` creates backups by default.
- `vortex_clone_profile` and `vortex_set_profile_mods` can write Vortex profile
  state only when `apply=true`.
- Close Vortex before profile writes. Reopen Vortex afterward, select the wanted
  profile, then deploy mods before launching Skyrim.
- The write tools refuse `apply=true` while `Vortex.exe` is running unless
  `allow_running_vortex=true` is passed for advanced recovery work.
- Profile writes use Vortex.exe `--set` instead of editing Vortex's database
  files directly.
- Large profile clones are written in smaller CLI batches to avoid Windows
  command-line length failures on big Nexus Collections.
- `read_text_file` refuses to read outside detected Vortex/Skyrim roots unless
  `allow_any_path=true`.

## Vortex Profile Notes

Vortex profiles let different playthroughs have different enabled mod lists, and
Vortex can clone profiles in its own UI. This MCP mirrors that safety idea for
OpenClaw: first inspect, then clone, then apply exact profile changes only after
you approve them.

If OpenClaw wants to experiment, the safer flow is:

1. Run `vortex_profile_report`.
2. Run `vortex_clone_profile` with `apply=false`.
3. Close Vortex.
4. Run `vortex_clone_profile` with `apply=true`.
5. Reopen Vortex, enable the new profile, deploy mods, and test Skyrim.

For exact mod toggles, run `vortex_profile_mods` first and copy the exact `id`
values into `vortex_set_profile_mods`. Do not guess mod ids.

If Skyrim launches but the mods do not show up, run
`vortex_profile_deployment_report`. It checks the common mismatch: Vortex says a
mod is enabled on a profile, but the plugin is not deployed into Skyrim `Data` or
is not enabled in `%LOCALAPPDATA%\Skyrim Special Edition\plugins.txt`.

For the broadest first pass, run `skyrim_modded_play_report`. It adds SKSE,
missing audio archive, missing master, stale `plugins.txt`, and INI checks, then
sorts the findings by severity.

## Manual Smoke Test

```powershell
py -3 .\server.py --self-test
```

MCP handshake test:

```powershell
'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"manual","version":"1"}}}' | py -3 .\server.py
```

You should get a JSON-RPC response with `serverInfo.name` equal to
`vortex-skyrimse-mcp`.

## Notes For Maintainers

This server intentionally avoids a dependency on Vortex internals. Current Vortex
state persistence has changed over time, and broad state writes are risky. The
profile tools use Vortex's public CLI path for `--get`/`--set` and keep writes
small, explicit, and dry-run by default.

Sources used for protocol behavior:

- MCP stdio transport requires UTF-8 JSON-RPC messages delimited by newlines:
  https://modelcontextprotocol.io/specification/2025-03-26/basic/transports
- MCP tools are listed with `tools/list` and invoked with `tools/call`:
  https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- Vortex profiles are documented as separate mod lists/settings/saves:
  https://github.com/Nexus-Mods/Vortex/wiki/MODDINGWIKI-Users-General-Setting-up-Profiles
