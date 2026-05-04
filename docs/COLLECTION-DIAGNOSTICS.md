# Collection Diagnostics

Collection diagnostics help OpenClaw understand whether Vortex exposes useful
collection state and whether a manifest-like JSON file matches local staged
Nexus metadata.

These tools are read-only. They do not install, download, update, remove, or
deploy collection mods.

## Tools

`vortex_collection_report`

Reads collection-like state exposed by Vortex's own CLI. This can show
collection ids, names, revisions, and mod attributes when Vortex stores them in
CLI-visible state.

`collection_local_match_report`

Compares a supplied manifest-like JSON file to locally staged Nexus mod/file
metadata. It reports missing Nexus mod ids, file-id mismatches, extra local
Nexus mod ids, and expected mods that are disabled when profile state is
available.

## Basic Use

From OpenClaw:

```text
Use vortex_collection_report to inspect collection state. Do not change Vortex.
```

From PowerShell:

```powershell
py -3 .\server.py --tool vortex_collection_report
```

From the local menu:

```powershell
.\vortex_skyrimse_menu.ps1 -Action collection
```

To compare a manifest file:

```powershell
py -3 .\server.py --tool collection_local_match_report --collection-manifest-path "C:\path\collection.json"
```

or:

```powershell
.\vortex_skyrimse_menu.ps1 -Action collection-match -CollectionManifestPath "C:\path\collection.json"
```

## What Counts As A Match

The matcher looks for Nexus-style fields such as:

- `modId`
- `nexusModId`
- `mod_id`
- `fileId`
- `nexusFileId`
- `file_id`

Local metadata comes from staged mod metadata files and Vortex profile metadata
when available. If Vortex or a mod lacks Nexus source metadata, the report says
so instead of guessing.

## Agent Guidance

Use these tools when the user says:

- a collection downloaded but some mods seem inactive
- Vortex shows collection state but the game does not match it
- a large collection may have drifted from its pinned versions
- OpenClaw needs to know whether a mod came from the collection or was added
  separately

Do not auto-update collection mods from this report. Collections often pin
specific versions for compatibility.
