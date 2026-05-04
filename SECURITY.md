# Security Policy

## Supported Versions

Security fixes target the latest released version on the `main` branch.

## Reporting A Vulnerability

Please open a GitHub issue if the vulnerability does not expose private user
data. If it includes secrets, private paths, or private mod information, avoid
posting the raw logs publicly.

Good reports include:

- version
- operating system
- MCP client
- which tool was called
- whether a Nexus API key was configured
- a redacted `bug_report_bundle` zip when safe

## Secrets

The MCP must never log:

- Nexus API keys
- request headers containing keys
- token-like tool arguments

`NEXUS_MODS_API_KEY`, `nexus_api_key`, `api_key`, `token`, `authorization`, and
similar fields are redacted from compact logs. Bug-report bundles also redact
normal user profile paths by default.

## High-Risk Actions

This project intentionally avoids automatic:

- mod deletion
- mod updates
- Nexus downloads
- collection installs
- deployment
- load-order sorting
- conflict-rule writes
- plugin record edits

Write-capable tools are narrow, opt-in, and documented in
[docs/SAFETY-UNDO.md](docs/SAFETY-UNDO.md).
