# xEdit and SSEEdit Diagnostics

`xedit_diagnostics_report`, `xedit_inspection_script`, and
`xedit_inspection_result_report` are read-only helpers for xEdit/SSEEdit
workflows. They do not clean plugins, save records, or edit mods.

Its job is to help OpenClaw answer:

- which plugin should I inspect for this FormID?
- is SSEEdit/xEdit installed somewhere obvious?
- does `plugins.txt` point this FormID prefix at a likely plugin?
- what plugin-header evidence is already visible from local files?
- can I generate a read-only xEdit script to export matching records?
- what plugins/signatures appear in the exported xEdit CSV?

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

Generate a read-only xEdit inspection script:

```powershell
py -3 .\server.py --tool xedit_inspection_script --description "bed outside tavern room" --location "Whiterun Bannered Mare" --object "bed" --form-id 0100ABCD
```

Then in xEdit/SSEEdit:

1. Load the active Skyrim SE load order or the candidate plugin(s).
2. Select the candidate plugin or records.
3. Apply the generated script.
4. Do not save plugin changes when closing xEdit.
5. Parse the generated CSV:

```powershell
py -3 .\server.py --tool xedit_inspection_result_report --report-path "C:\path\to\OpenClawSkyrimInspector.csv" --allow-any-path
```

## How It Works

The tool searches for `SSEEdit.exe`, `xEdit.exe`, and `TES5Edit.exe` in:

- the Skyrim SE folder
- nearby `SSEEdit` or `xEdit` folders
- common Documents tool folders
- `PATH`

For an 8-character FormID, it reads `plugins.txt`, maps the first two hex
digits to the enabled plugin index, and returns a best-effort plugin hint.

`xedit_inspection_script` writes a Pascal `.pas` script. The generated script
uses xEdit read APIs such as record signature, FormID, EditorID, `FULL`, base
record, model path, VMAD/script data, and full path. It writes matching selected
records to CSV. The MCP also runs a static safety check to block obvious
mutating xEdit calls in generated scripts.

`xedit_inspection_result_report` reads the CSV and summarizes:

- repeated source plugins
- repeated record signatures such as `REFR`, `CELL`, `MESG`, or `QUST`
- matched search terms
- preview rows for OpenClaw

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
3. If candidates are still ambiguous, run `xedit_inspection_script`.
4. Ask the user to apply the script in xEdit to selected candidate plugins or records.
5. Run `xedit_inspection_result_report` on the generated CSV.
6. Tell the user the plugin target is a read-only inspection target.
7. Do not recommend cleaning or saving plugin edits from this report alone.
8. Use a cloned Vortex profile for disable tests before removing anything.

## Sources

- xEdit scripting docs: https://tes5edit.github.io/docs/13-Scripting-Functions.html
- xEdit project README and game-mode command arguments: https://github.com/TES5Edit/TES5Edit
