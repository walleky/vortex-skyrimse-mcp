# xEdit and SSEEdit Diagnostics

`xedit_diagnostics_report` is a read-only helper for xEdit/SSEEdit workflows.
It does not launch xEdit, clean plugins, save records, or edit mods.

Its job is to help OpenClaw answer:

- which plugin should I inspect for this FormID?
- is SSEEdit/xEdit installed somewhere obvious?
- does `plugins.txt` point this FormID prefix at a likely plugin?
- what plugin-header evidence is already visible from local files?

## Basic Use

From OpenClaw:

```text
Use xedit_diagnostics_report with form_id 0100ABCD. Do not edit plugins.
```

From PowerShell:

```powershell
py -3 .\server.py --tool xedit_diagnostics_report --form-id 0100ABCD
```

If detection misses xEdit:

```powershell
py -3 .\server.py --tool xedit_diagnostics_report --xedit-exe "C:\Tools\SSEEdit\SSEEdit.exe" --form-id 0100ABCD
```

The local menu also has:

```powershell
.\vortex_skyrimse_menu.ps1 -Action xedit -FormId 0100ABCD
```

## How It Works

The tool searches for `SSEEdit.exe`, `xEdit.exe`, and `TES5Edit.exe` in:

- the Skyrim SE folder
- nearby `SSEEdit` or `xEdit` folders
- common Documents tool folders
- `PATH`

For an 8-character FormID, it reads `plugins.txt`, maps the first two hex
digits to the enabled plugin index, and returns a best-effort plugin hint.

## Important Limits

The FormID hint is not proof.

ESL/light plugins, injected records, runtime-created references, and compacted
FormIDs can make the prefix incomplete. Use the hint as a first xEdit target,
then verify the record in xEdit or in game.

## Agent Guidance

When the user says "there is a bed outside the tavern room" or "what added this
object?", prefer this order:

1. Run `in_game_issue_report` from the user's natural description.
2. If the user has a FormID, pass it to `xedit_diagnostics_report`.
3. Tell the user the plugin target is a read-only inspection target.
4. Do not recommend cleaning or saving plugin edits from this report alone.
5. Use a cloned Vortex profile for disable tests before removing anything.
