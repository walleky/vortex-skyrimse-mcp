# OpenClaw From WSL2

Use this when OpenClaw runs inside WSL2 but Vortex, Steam, and Skyrim Special
Edition are installed as normal Windows apps. The same path bridge also works
for read-only Mod Organizer 2 profile scans.

## Short Version

From WSL:

```bash
cd /mnt/c/Users/<you>/Documents/vortex-skyrimse-mcp
bash install_wsl.sh
```

Copy the printed MCP config into OpenClaw and restart OpenClaw.

Then test:

```bash
python3 /mnt/c/Users/<you>/Documents/vortex-skyrimse-mcp/server.py --wsl-bridge
python3 /mnt/c/Users/<you>/Documents/vortex-skyrimse-mcp/server.py --tool validate_setup
```

## Example OpenClaw Config

```json
{
  "mcpServers": {
    "vortex-skyrimse": {
      "command": "python3",
      "args": [
        "/mnt/c/Users/<you>/Documents/vortex-skyrimse-mcp/server.py"
      ],
      "env": {
        "VORTEX_SKYRIMSE_MCP_WSL_MOUNT_ROOT": "/mnt",
        "VORTEX_SKYRIMSE_MCP_WINDOWS_USERPROFILE": "/mnt/c/Users/<you>"
      }
    }
  }
}
```

If your repo is cloned in WSL home instead of Windows Documents, use that WSL
path for `server.py`. The server will still read Windows Skyrim/Vortex files
through `/mnt/c`.

## What The Bridge Does

When the server detects WSL2, it maps Windows paths to WSL paths:

```text
C:\Users\<you>\AppData\Roaming\Vortex
  -> /mnt/c/Users/<you>/AppData/Roaming/Vortex

C:\Program Files (x86)\Steam
  -> /mnt/c/Program Files (x86)/Steam

D:\SteamLibrary
  -> /mnt/d/SteamLibrary
```

This affects:

- Vortex AppData detection.
- Vortex staging folder guesses.
- Steam root and Steam library detection.
- Skyrim SE game folder detection.
- `plugins.txt` and `loadorder.txt` under Windows LocalAppData.
- Windows Documents/My Games detection.
- Vortex.exe discovery.
- Vortex process checks through `tasklist.exe` when Windows interop is enabled.
- MO2 instance/profile folders under Windows LocalAppData when using
  `mo2_*` tools.

## What Needs Windows Interop

Read-only filesystem scans only need Windows drives mounted under `/mnt`.

Profile tools need Windows interop because they call `Vortex.exe --get` or
`Vortex.exe --set` instead of editing Vortex state files directly. That is the
safer route because Vortex owns its own state.

If `wsl_bridge_report` says Windows interop is missing, these may not work until
interop is enabled:

- `vortex_profile_report`
- `vortex_profile_backup`
- `vortex_clone_profile`
- `vortex_safe_profile_fix`
- `vortex_set_profile_mods`
- profile sections inside broader reports

The rest of the file/log/mod diagnostics can still work if `/mnt/c` is mounted.
MO2 read-only tools also only need the Windows drive mounted, unless you are
launching MO2 itself outside the MCP.

## If Detection Misses Your Windows User

Set the profile explicitly before launching OpenClaw from WSL:

```bash
export VORTEX_SKYRIMSE_MCP_WINDOWS_USERPROFILE=/mnt/c/Users/<you>
```

Or put it in the MCP config `env` block:

```json
"env": {
  "VORTEX_SKYRIMSE_MCP_WSL_MOUNT_ROOT": "/mnt",
  "VORTEX_SKYRIMSE_MCP_WINDOWS_USERPROFILE": "/mnt/c/Users/<you>"
}
```

## If Steam Or Skyrim Is On Another Drive

The bridge maps drive letters automatically, so `D:\SteamLibrary` becomes
`/mnt/d/SteamLibrary`. Make sure WSL can see that drive:

```bash
ls /mnt/d
```

If it cannot, mount or expose the drive to WSL first, then rerun:

```bash
python3 server.py --wsl-bridge
```

## Best First Prompt For OpenClaw

```text
Use wsl_bridge_report, then validate_setup. Tell me whether OpenClaw running in WSL can see Windows Vortex, Steam, Skyrim SE, staging, plugins.txt, SKSE, and whether profile tools can call Vortex.exe. Do not apply changes.
```

Then:

```text
Use skyrim_diagnostics_report with performance_mode=slow_model. Summarize the top findings and next actions. Do not apply changes.
```

For MO2 from WSL2:

```text
Use mo2_modded_play_report with mo2_instance_dir "/mnt/c/Users/<you>/AppData/Local/ModOrganizer/Skyrim Special Edition". Tell me whether the selected profile, plugins, missing masters, and SKSE route look ready. Do not apply changes.
```
