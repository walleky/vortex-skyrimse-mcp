# In-Game Diagnosis

This covers questions like:

- "Why is there a bed outside the tavern room in the Whiterun tavern?"
- "Which mod added this object?"
- "Why do I keep getting this popup?"

## What Works Now

Use:

```text
safe_session_report with issue details, or in_game_issue_report for only the issue scan
```

Give it as much plain evidence as possible:

```json
{
  "description": "There is a bed outside the tavern room and it blocks the path.",
  "location": "Whiterun Bannered Mare",
  "object": "bed"
}
```

For popups:

```json
{
  "description": "I keep getting an annoying popup after loading a save."
}
```

You do not need to type the exact popup message for the first pass. If you say
`popup`, `pop-up`, `notification`, `warning`, `alert`, `prompt`, `dialog`,
`MCM message`, or similar, the MCP automatically switches to popup triage and
looks for UI/interface, script, SKSE, config, FOMOD, and MCM-style evidence.
Exact text or screenshot/OCR is optional second-pass evidence when the first
candidate list is weak.

The tool searches staged mods for:

- mod names
- plugin filenames
- readable plugin strings
- readmes and config files
- important file paths
- a small number of relevant config/text files in the first pass
- UI/interface, script, SKSE, FOMOD, and MCM-style popup evidence
- Vortex profile enabled/disabled state when available

It returns likely candidate mods, evidence snippets, confidence, and a safe test plan.

## Why FormID Matters

For misplaced objects, the strongest evidence is the object's FormID.

In Skyrim:

1. Open the console with `~`.
2. Click the bad object.
3. Write down the reference ID, base ID/name if shown, and the cell/location.
4. Give that to OpenClaw.

The first two hex digits of many FormIDs often point to the plugin's load-order slot. That is not perfect for ESL/light plugins, but it is still useful evidence. OpenClaw should combine it with `plugins.txt`, load order, and this report.

You can pass that evidence directly:

```json
{
  "description": "Bad bed placement",
  "location": "Whiterun Bannered Mare",
  "object": "bed",
  "form_id": "1200ABCD",
  "base_object": "CommonBed01",
  "cell": "WhiterunBanneredMare"
}
```

The report includes a rough FormID/load-order hint when `plugins.txt` is available.

## Scan Modes

The default scan mode is `balanced`. It is meant to be more useful on the first
try without crawling every text/config file in a large collection.

- `quick`: names, plugins, readmes, and plugin strings.
- `balanced`: quick scan plus important file paths and a small number of relevant config/text files.
- `deep`: slower scan that reads more text/config files.

Use `scan_mode=deep` or `deep_scan_files=true` only when the first pass is weak.
The result includes `diagnosticQuality`, `nextBestInputs`, and timeout/partial
scan status so OpenClaw can explain what evidence is missing.

## Safe Fix Flow

OpenClaw should not delete mods or edit records automatically.

Safer path:

1. Run `safe_session_report` with the issue details.
2. If needed, run `in_game_issue_report` again with `scan_mode=deep`.
3. Confirm a profile backup exists, or run `vortex_profile_backup`.
4. Inspect the top candidate in xEdit/SSEEdit if available.
5. Clone the Vortex profile.
6. Disable one candidate in the cloned profile as a dry run first.
7. Apply only after approval.
8. Deploy in Vortex and test.

## What A True Live Skyrim MCP Needs

This MCP cannot see Skyrim's 3D scene by itself. It reads files and Vortex state.

A future live bridge would need one or more of these:

- screenshot/OCR capture for visible popups
- SKSE plugin reporting current cell, loaded area, crosshair reference FormID, base object, and active UI/message events
- console-log bridge that can export clicked reference details
- read-only xEdit/SSEEdit integration for cell and record lookup

That would make questions like "what object am I looking at?" much stronger. Until then, plain popup descriptions work for the first pass, while exact popup text, screenshots/OCR, and console FormIDs make second-pass diagnosis stronger.
