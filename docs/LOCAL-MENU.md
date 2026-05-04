# Local Helper Menu

The local helper menu is for users who do not want to remember command-line flags or set up OpenClaw first.

Run:

```powershell
.\vortex_skyrimse_menu.ps1
```

Or double-click:

```text
Vortex-SkyrimSE-Menu.cmd
```

## Menu Actions

1. Environment diagnosis
2. Mod knowledge Markdown report
3. Modded play diagnosis
4. Bug report zip
5. Log status
6. List available tools

Reports are written to:

```text
Documents\vortex-skyrimse-mcp-reports
```

Use `-ReportDir` if you want another folder.

Unless you already set `VORTEX_SKYRIMSE_MCP_LOG_DIR`, menu-run logs are written under the same reports folder in `logs`.

## Noninteractive Use

Run one action directly:

```powershell
.\vortex_skyrimse_menu.ps1 -Action knowledge
.\vortex_skyrimse_menu.ps1 -Action bug
.\vortex_skyrimse_menu.ps1 -Action play
```

Custom paths:

```powershell
.\vortex_skyrimse_menu.ps1 -Action knowledge -StagingDir "D:\Vortex Mods\skyrimse\mods" -SkyrimDir "C:\SteamLibrary\steamapps\common\Skyrim Special Edition"
```

Stronger duplicate evidence:

```powershell
.\vortex_skyrimse_menu.ps1 -Action knowledge -HashFiles
```

If Vortex profile state is slow or locked:

```powershell
.\vortex_skyrimse_menu.ps1 -Action knowledge -NoProfileState
```

## Safety

The menu runs read-only report actions. It does not delete mods, change Vortex profiles, sort load order, or write INI fixes.
