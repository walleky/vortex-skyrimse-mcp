# Contributing

Thanks for helping make Skyrim/Vortex troubleshooting less painful.

## Development Setup

Requirements:

- Windows PowerShell
- Python 3
- Git

Run the checks:

```powershell
py -3 -m py_compile server.py tests\smoke_mcp.py tests\fixture_mcp.py
py -3 tests\smoke_mcp.py
py -3 tests\fixture_mcp.py
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests\check_powershell.ps1
```

Run the self-test:

```powershell
py -3 .\server.py --self-test
```

## Coding Guidelines

- Keep tools read-only by default.
- Require explicit write flags for profile or INI changes.
- Prefer Vortex's CLI for Vortex state instead of direct database edits.
- Do not add auto-delete, auto-update, auto-sort, or auto-deploy behavior.
- Keep stdout clean for MCP JSON-RPC.
- Log to files under the MCP log folder.
- Redact user paths and secrets in reports, logs, and tests.
- Add fixture coverage for new tool behavior when practical.

## Documentation Guidelines

When adding a tool or changing behavior, update:

- `README.md`
- `START-HERE.md` when user workflow changes
- `docs/OPENCLAW-AGENT-GUIDE.md` when agent behavior changes
- `docs/CLI.md` for direct command-line flags
- `CHANGELOG.md`

## Nexus API Changes

Nexus API behavior must follow [docs/ADR-0001-NEXUS-API-KEYS.md](docs/ADR-0001-NEXUS-API-KEYS.md).

Do not read or reuse Vortex's key. Do not add download/install/update flows
without a separate design review.
