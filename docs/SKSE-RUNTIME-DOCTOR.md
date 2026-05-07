# SKSE Runtime Doctor

`skse_runtime_doctor_report` is the quickest answer to:

> Does my Skyrim runtime match the SKSE version I installed?

It is read-only. It does not install SKSE, edit files, deploy mods, or launch
Skyrim.

## What It Checks

- `SkyrimSE.exe` file version, when Windows exposes it.
- SKSE loader evidence:
  - `skse64_loader.exe`
  - `skse64_<runtime>.dll`
  - SKSE scripts under `Data\Scripts`
- Whether the SKSE runtime DLL target matches the Skyrim runtime.
- Known official SKSE mapping:
  - Steam AE runtime `1.6.1170` -> SKSE `2.2.6`
  - GOG AE runtime `1.6.1179` -> SKSE `2.2.6`
  - SE/downgraded runtime `1.5.97` -> SKSE `2.0.20`
  - VR runtime `1.4.15` -> SKSE `2.0.12`
- Address Library `versionlib-*.bin` evidence in deployed and staged files.
- Deployed SKSE plugin DLL count.

## Direct CLI

```powershell
py -3 .\server.py --skse-doctor
```

Write a readable Markdown report:

```powershell
py -3 .\server.py --skse-doctor --output-path ".\skse-runtime-doctor.md" --output-json ".\skse-runtime-doctor.json"
```

If detection picked the wrong Skyrim folder:

```powershell
py -3 .\server.py --skse-doctor --skyrim-dir "C:\SteamLibrary\steamapps\common\Skyrim Special Edition"
```

## Local Menu

```powershell
.\vortex_skyrimse_menu.ps1 -Action skse-doctor
```

## OpenClaw Prompt

```text
Use skse_runtime_doctor_report. Tell me whether my Skyrim runtime, SKSE DLL target, SKSE scripts, and Address Library evidence match. Do not install, deploy, or launch anything.
```

## How To Read It

- `summary.runtimeState=ready`: core runtime/SKSE evidence is consistent.
- `summary.runtimeState=review`: no hard mismatch, but something needs human
  review, such as missing version evidence or missing Address Library evidence.
- `summary.runtimeState=blocked`: core SKSE evidence is missing or mismatched.
- `summary.skyrimRuntime`: detected `SkyrimSE.exe` runtime, such as `1.6.1170`.
- `summary.skseTargetRuntime`: inferred from `skse64_<runtime>.dll`, such as
  `1.5.97`.
- `summary.runtimeMatchesSkse=false`: install the matching SKSE build or restore
  the intended Skyrim runtime before launching.

## Important Notes

`skse64_steam_loader.dll` is not treated as a hard requirement because newer SKSE
builds removed the need for it. It is still useful evidence when present.

Exact compatibility of individual SKSE plugin DLL mods still depends on each
plugin author. This report checks the core runtime pairing and Address Library
evidence first.

Sources:

- https://skse.silverlock.org/
- https://www.nexusmods.com/skyrimspecialedition/mods/30379
