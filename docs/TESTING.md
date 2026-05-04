# Testing

Use this when you want to verify the MCP before changing a real Vortex profile
or after pulling an update from GitHub.

## Easy Button

From the repo root:

```powershell
py -3 .\tests\run_all.py
```

On Linux/macOS:

```bash
python3 tests/run_all.py
```

If PowerShell is not installed, the runner skips the PowerShell helper checks.
To skip them explicitly:

```bash
python3 tests/run_all.py --skip-powershell
```

## What The Runner Checks

- Python syntax for the server and tests
- `server.py --self-test`
- MCP stdio initialize, tools/list, and tools/call
- synthetic Skyrim/Vortex fixture integration tests
- focused config/runtime regressions
- PowerShell helper parsing and local menu smoke checks, when available

## Focused Config/Runtime Test

Run only the newest regression layer:

```bash
python3 tests/config_runtime_mcp.py
```

This test covers:

- JSON, XML, INI, loose key/value, YAML/plain text config reporting
- invalid config parse findings
- root-restricted config reads
- exact-text patch suggestions for `configured=false`, `configured=0`, and
  `configured=no` style settings
- refusal to patch repeated text unless `allow_multiple=true`
- runtime log `issueGroups`
- stale/fresh runtime log detection
- automatic config candidate validation
- `validate_config_candidates=false`

## CI

GitHub Actions runs `tests/run_all.py --skip-powershell`, then runs the
PowerShell helper check under `pwsh`, and finally runs MCP Doctor. The same core
checks should pass locally before a release.

## MCP Doctor With Explicit Python

If `py` or `python` is not on `PATH`, pass the interpreter path:

```powershell
.\mcp_doctor.ps1 -PythonCommand "C:\Path\To\python.exe"
```

You can also set:

```powershell
$env:VORTEX_SKYRIMSE_MCP_PYTHON = "C:\Path\To\python.exe"
.\mcp_doctor.ps1
```

## OpenClaw Prompt

```text
Run the local test suite for this repo. Use tests/run_all.py. If it fails,
summarize the first failing step and the exact command that failed. Do not edit
Vortex profiles or Skyrim files.
```
