# Vercel Site

This repo includes a Vercel-ready static documentation site under `public/`.

The hosted site is not the MCP server. It is an install and workflow reference
for users and OpenClaw agents. The MCP itself must run locally because it needs
access to Windows or WSL2 paths for Skyrim SE, Vortex, Mod Organizer 2, SKSE,
logs, profiles, and generated reports.

## Deploy

From the repo root:

```powershell
vercel --prod
```

The deployment serves `public/index.html`. There is no build step and no server
function.

## What To Tell Users

Use the Vercel link as the friendly project page:

1. Open the site.
2. Click GitHub or Start Here.
3. Clone the repo locally.
4. Run `install_windows.ps1` or `install_wsl.sh`.
5. Run `mcp_doctor.ps1`.
6. Register the generated MCP config in OpenClaw.

## Privacy Boundary

The site does not receive:

- Skyrim paths
- mod lists
- Vortex or MO2 profile state
- Nexus API keys
- Papyrus/SKSE/crash logs
- generated bug bundles

Those stay on the user's machine unless the user manually shares a report.
