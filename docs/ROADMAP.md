# Improvement Notes

These are useful next steps, ordered by value and risk.

## Best Next Improvements

1. Add sample sanitized `bug_report_bundle` output so OpenClaw agents can learn the shape without touching a user's machine.
2. Add optional ZIP packaging for bug reports, including the JSON bundle and selected log files.
3. Add richer Vortex collection detection if Vortex exposes collection state through stable CLI paths.
4. Add more plugin metadata parsing for ESP/ESM headers beyond masters, such as plugin version and record counts.
5. Add a safe "profile diff narrative" tool that explains profile differences in plain English.
6. Add a "known risky mod categories" report for DLL plugins, animation frameworks, body/skeleton mods, UI replacers, and script-heavy mods.
7. Add a synthetic test fixture folder with fake Vortex staging, fake plugins.txt, and fake profiles so more behavior can be tested in CI.

## What Not To Automate Yet

- Do not auto-delete redundant mods.
- Do not auto-sort load order.
- Do not auto-write Vortex conflict rules.
- Do not auto-disable mods from broad guesses.

Those actions can break saves. Keep them as reports or dry-run plans until the evidence is strong and the user approves.

## Code Health Improvements

- Split `server.py` into modules once it becomes painful to navigate:
  - `paths.py`
  - `logging_support.py`
  - `vortex_cli.py`
  - `mods.py`
  - `plugins.py`
  - `profiles.py`
  - `mcp_server.py`
- Keep the current single-file shape while rapid iteration is more useful than packaging polish.
- Expand `tests/smoke_mcp.py` into fixture-based tests before making larger refactors.

## OpenClaw Experience Improvements

- Teach OpenClaw to call `bug_report_bundle` automatically after any tool exception.
- Teach OpenClaw to read `docs/OPENCLAW-AGENT-GUIDE.md` before applying any profile or INI write.
- Prefer one-shot `skyrim_modded_play_report` for first diagnosis, then narrower tools.
- Keep final answers short and action-oriented for nontechnical users.
