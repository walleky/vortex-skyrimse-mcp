# Performance Modes

This MCP is designed to work on very large Skyrim SE collections, but huge
outputs can slow down smaller OpenClaw models. Use performance modes to reduce
how much the model has to read.

## Recommended Default For Slower Models

Ask OpenClaw to use:

```text
safe_session_report with performance_mode=slow_model
```

Or from PowerShell:

```powershell
py -3 .\server.py --safe-session --performance-mode slow_model
```

`slow_model` keeps the balanced first scan for in-game issues, but returns
compact candidate summaries, fewer evidence snippets, fewer log files, and skips
the optional profile backup unless you explicitly ask for it.

## Modes

`normal`

Default behavior. Good when the OpenClaw model can handle normal JSON reports.

`slow_model`

Best first choice for weaker models. Keeps useful evidence, but trims nested
details and avoids large optional sections. Use this when OpenClaw seems slow,
forgets the question, or gets distracted by long output.

`fast`

Smallest and quickest rough pass. Uses `scan_mode=quick`, fewer candidates, and
shorter time budgets. Use it to find obvious problems quickly, then rerun a
narrower tool with `slow_model` or `normal` if needed.

`thorough`

Larger output and more evidence for stronger models or maintainer debugging.
Use it after a compact first pass points to a specific area.

## Response Modes

`response_mode=standard` returns full tool details.

`response_mode=compact` returns the short OpenClaw-friendly shape for
`in_game_issue_report`, and trims the play-health section inside
`safe_session_report` and `bug_report_bundle`.

Compact issue candidates keep:

- mod name
- confidence and score
- Vortex mod id when known
- enabled state when known
- inferred role/categories/removal risk
- top plugins
- a small evidence preview list
- scan mode and diagnostic quality

Compact issue candidates intentionally drop large fields such as full local
paths and long evidence arrays.

## OpenClaw Strategy

For large collections:

1. Start with `safe_session_report performance_mode=slow_model`.
2. Read `summary`, `findings`, and `nextActions` before reading nested sections.
3. If the issue is in game, read `sections.inGameIssue.diagnosticQuality` and
   `sections.inGameIssue.nextBestInputs`.
4. Only run `scan_mode=deep` after the first result says the evidence is weak.
5. Run `mod_knowledge_report` only when you need a collection-wide map or safe
   removal review, because it is intentionally broader.

## What Improves Speed

- Use `performance_mode=slow_model` for most OpenClaw conversations.
- Use `--no-profile-state` if Vortex CLI is slow or Vortex is open/locked.
- Use `--no-logs` if logs are not relevant.
- Use `--max-mods 200` for rough triage on massive collections.
- Use exact evidence when you have it: FormID, cell name, base object, popup
  text, or screenshot/OCR text.
- Use `scan_mode=quick` only for rough triage; use balanced or deep for final
  diagnosis.

## What Not To Do

Do not run `mod_knowledge_report --hash-files` as the first step on a huge
collection. It is useful, but it is intentionally slower.

Do not ask OpenClaw to read every generated JSON section at once. Have it start
with the summary and follow the `nextActions`.
