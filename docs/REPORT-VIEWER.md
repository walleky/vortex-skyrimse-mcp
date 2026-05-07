# Local Report Viewer

`report_viewer_index` creates a static HTML page for the reports this MCP writes.
It is meant for users and OpenClaw agents who do not want to hunt through many
JSON, Markdown, CSV, log, script, and zip files by hand.

It is read-only. It does not open Vortex, launch Skyrim, deploy mods, edit
profiles, write load order, or change any report file other than the HTML viewer
it creates.

## Quick Use

From the local menu:

```powershell
.\vortex_skyrimse_menu.ps1 -Action report-viewer
```

Then open:

```text
Documents\vortex-skyrimse-mcp-reports\report-viewer.html
```

Direct CLI:

```powershell
py -3 .\server.py --report-viewer
```

With an explicit reports folder:

```powershell
py -3 .\server.py --report-viewer --report-dir "$env:USERPROFILE\Documents\vortex-skyrimse-mcp-reports"
```

With an explicit output HTML path:

```powershell
py -3 .\server.py --report-viewer --report-dir ".\reports" --output-path ".\reports\report-viewer.html"
```

## What It Indexes

The viewer scans the reports folder for:

- `.json`
- `.md` and `.markdown`
- `.csv`
- `.txt`
- `.log`
- `.jsonl`
- `.pas`
- `.zip`

It sorts newest files first, groups by file extension, detects report kinds from
filenames, and adds a small summary where possible.

For JSON reports, it tries to pull common summary fields such as:

- `deploymentState`
- `launchState`
- `runtimeState`
- `highestSeverity`
- `findingCount`
- `okToLaunchNow`
- `profileToSkyrimLinked`
- `recommendedLaunchRoute`

For Markdown reports, it previews headings. For CSV reports, it previews
columns. For zip files, it lists entry counts and a few names.

## OpenClaw Workflow

Use this when the user says something like:

```text
Show me all the reports this MCP made and tell me what looks important.
```

Recommended calls:

```text
report_viewer_index
```

Then read `output_path` from the result. If the user asks for a summary, read
the newest high-value source reports directly too, usually:

```text
deployment_doctor_report
skyrim_launch_doctor_report
skse_runtime_doctor_report
skyrim_diagnostics_report
bug_report_bundle
```

The HTML viewer is a navigation aid, not the source of truth. Use it to find
the right file quickly, then read the JSON/Markdown report when exact evidence
matters.

## Arguments

| Argument | Default | Meaning |
| --- | --- | --- |
| `report_dir` | `Documents\vortex-skyrimse-mcp-reports` | Folder to index. |
| `output_path` | `<report_dir>\report-viewer.html` | HTML file to write. |
| `include_subdirs` | `true` | Include issue-case folders and logs under the report folder. |
| `max_files` | `300` | Maximum indexed files. |
| `max_preview_bytes` | `20000` | Maximum preview text per text-like file. |

## Safety Notes

- The tool writes one HTML file only.
- It can preview local report text in that HTML file, so do not post the viewer
  publicly without checking it.
- Use `bug_report_bundle` with `redact_user_paths=true` when you need a safer
  file to share outside your machine.
- Regenerate the viewer after creating new reports; it is a static snapshot.
