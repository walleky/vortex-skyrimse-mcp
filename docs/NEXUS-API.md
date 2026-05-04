# Nexus Mods API

Nexus API support is optional read-only metadata for OpenClaw and local
diagnostics. It helps identify mods, compare local versions with Nexus metadata,
parse `nxm://` links, and explain a large Skyrim SE collection with less
guessing.

It does not download, install, update, endorse, track, deploy, sort, or delete
mods. Vortex remains responsible for downloads, installs, collections,
deployment, conflict rules, and launching tools.

## Key Decision

Use this MCP's own explicitly configured Nexus API key. Do not read, copy, or
borrow Vortex's key.

Why:

- Vortex's key/state is Vortex-owned implementation detail.
- Borrowing it can impersonate Vortex and is fragile across Vortex updates.
- OpenClaw logs and support bundles must never expose hidden application keys.
- A user-provided key is easier to explain, revoke, rotate, and audit.

Preferred sources, in order:

1. `NEXUS_MODS_API_KEY` environment variable.
2. `nexus_api_key_file` tool argument or `--nexus-api-key-file`.
3. `nexus_api_key` direct tool argument, only for private one-off testing.

## Setup

Environment variable:

```powershell
setx NEXUS_MODS_API_KEY "paste-your-key-here"
```

Close and reopen OpenClaw, PowerShell, or any app that launches the MCP after
using `setx`.

Key file:

```powershell
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.vortex-skyrimse-mcp" | Out-Null
Set-Content -LiteralPath "$env:USERPROFILE\.vortex-skyrimse-mcp\nexus-api-key.txt" -Value "paste-your-key-here" -NoNewline
```

Then pass:

```powershell
py -3 .\server.py --tool nexus_validate_key --nexus-api-key-file "$env:USERPROFILE\.vortex-skyrimse-mcp\nexus-api-key.txt"
```

For OpenClaw, tell it:

```text
Use nexus_validate_key with nexus_api_key_file=<path to my key file>. Do not log or print the key.
```

## Quick Checks

Validate the key:

```powershell
py -3 .\server.py --tool nexus_validate_key
```

Run one Skyrim diagnostic pass with Nexus metadata:

```powershell
py -3 .\server.py --skyrim-diagnostics --include-nexus-metadata
```

Lookup one mod:

```powershell
py -3 .\server.py --tool nexus_mod_lookup --args-json "{`"mod_id`":266}"
```

Compare local staged Vortex mods to current Nexus metadata:

```powershell
py -3 .\server.py --tool nexus_update_report --include-nexus-metadata
```

Parse an NXM link without downloading:

```powershell
py -3 .\server.py --tool nexus_parse_nxm_link --args-json "{`"nxm_link`":`"nxm://skyrimspecialedition/mods/123/files/456?key=abc&expires=9999999999`"}"
```

## MCP Tools

`nexus_validate_key`

Checks whether the configured key works. It returns a safe account summary and
rate-limit metadata. It never returns the key.

`nexus_mod_lookup`

Returns normalized metadata for one Nexus mod id, such as name, author, summary,
category, version, status, adult flag, update time, and URL.

`nexus_mod_files`

Lists current file metadata for one mod id.

`nexus_file_info`

Reads metadata for one file id under one mod id.

`nexus_file_by_md5`

Looks up possible Nexus source metadata for a local archive MD5 hash.

`nexus_parse_nxm_link`

Parses game domain, mod id, file id, key presence, and expiry from an `nxm://`
link. It does not download.

`nexus_update_report`

Scans local Vortex staging metadata and selected Vortex profile metadata for
Nexus mod ids, then compares local versions with current Nexus metadata.

`skyrim_diagnostics_report`

Runs the broad no-change Skyrim diagnostics report. If a Nexus key is configured,
it includes Nexus metadata by default. You can also force it with
`include_nexus_metadata=true`.

## Cache

Nexus metadata is cached locally for 24 hours by default.

Default cache locations:

```text
%LOCALAPPDATA%\vortex-skyrimse-mcp\nexus-cache
%APPDATA%\vortex-skyrimse-mcp\nexus-cache
~\.vortex-skyrimse-mcp\nexus-cache
```

Override:

```powershell
$env:VORTEX_SKYRIMSE_MCP_NEXUS_CACHE_DIR = "D:\vortex-skyrimse-mcp\nexus-cache"
```

Per-call options:

- `nexus_cache_ttl_seconds`
- `nexus_cache_dir`
- `nexus_use_cache=false`
- CLI flag `--no-nexus-cache`

## Failure Handling

All Nexus API failures should be soft failures.

- No key: local Skyrim/Vortex diagnostics still work.
- Invalid key: report the authentication problem without printing the key.
- Rate limited: use cached data when present, otherwise return partial results.
- Nexus unavailable: keep local reports working.
- Missing local metadata: report `missingSourceMetadata`, because local/manual
  imports may not have Nexus ids.
- Lookup limit reached: report `skippedLookupLimitCount`; increase
  `nexus_max_lookup_mods` for a slower fuller pass.

## OpenClaw Prompt

```text
Use skyrim_diagnostics_report with performance_mode=slow_model and include Nexus metadata if available. Start with local setup/deployment findings, then mention stale Nexus metadata or missing source metadata. Do not apply changes.
```

## Sources

- Nexus Mods API launch article: https://www.nexusmods.com/ecosystem/news/13921
- Nexus Mods API acceptable use policy: https://help.nexusmods.com/article/114-api-acceptable-use-policy
- Nexus Mods public API docs: https://app.swaggerhub.com/apis-docs/NexusMods/nexus-mods_public_api_params_in_form_data/1.0
- Official `node-nexus-api` client: https://github.com/Nexus-Mods/node-nexus-api
- Nexus Mods GraphQL docs: https://graphql.nexusmods.com/
- Vortex extension API: https://github.com/Nexus-Mods/vortex-api
