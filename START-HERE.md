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

MCP Doctor runs the server self-test, runs the MCP handshake smoke test, writes
`openclaw.mcp.generated.json`, prints the OpenClaw registration command, and can
open the OpenClaw config folder.

To let it register the server through the OpenClaw CLI:

```powershell
.\mcp_doctor.ps1 -RegisterOpenClaw
```

## First Prompts

Start read-only:

```text
Use the vortex-skyrimse MCP to detect my Skyrim SE/Vortex environment and list the highest-risk problems. Do not apply changes.
```

Then check whether Vortex's active profile is really deployed:

```text
Use skyrim_modded_play_report to tell me why my modded Skyrim SE setup is not launching with the expected Vortex profile. Do not apply changes.
```

For redundant mods and conflicts:

```text
Use the vortex-skyrimse MCP to find missing masters, likely redundant mods, and sensitive file conflicts. Do not apply changes yet.
```

## Safety Rules

- Most tools are read-only.
- `apply_ini_fixes` writes only when `dry_run=false`.
- `vortex_clone_profile` and `vortex_set_profile_mods` write only when `apply=true`.
- Close Vortex before profile writes.
- Reopen Vortex afterward, pick the intended profile, then deploy mods before launching Skyrim.

## Quick Test

```powershell
py -3 .\server.py --self-test
py -3 .\tests\smoke_mcp.py
```
