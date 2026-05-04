# Nexus Mods API Integration Design

Date checked: 2026-05-04

Implementation status: Phase 1 read-only REST metadata support is implemented in
v0.2.14 for key validation, mod/file lookup, MD5 lookup, NXM parsing, local
update/source reports, `mod_knowledge_report` enrichment, and
`skyrim_diagnostics_report` integration. GraphQL, collection manifest analysis,
and Nexus account write actions remain future work.

This document explains what Nexus Mods API surfaces appear useful for this
project, how they could improve the Vortex Skyrim SE MCP, and what should stay
out of scope for safety and compatibility.

## Short Answer

This project is no longer just a tiny MCP toy. It is a local Skyrim SE/Vortex
diagnostics assistant that exposes an MCP server, direct CLI tools, report
writers, safety/undo flows, logs, and OpenClaw-oriented troubleshooting
workflows.

It is still an MCP server at its core because OpenClaw talks to it through MCP.
But practically, it is becoming a small local support platform around Vortex and
Skyrim SE. It should not become a full mod manager or a Vortex replacement.
Vortex should remain responsible for downloads, installs, deployment, conflict
rules, collections, and launching game tools.

Nexus API integration would be most useful as read-only metadata enrichment:
identify mods more reliably, check updates, understand files before they are
installed, map local staged mods back to Nexus pages/files, and help OpenClaw
explain collection contents with less guessing.

## API Surfaces

### Public REST API

The public Nexus Mods API was built alongside Vortex and replaced older mod
manager data access. Nexus describes its broad areas as mods, games, and users.

Useful REST capabilities for this MCP:

- Games:
  - list supported games
  - get specific game information
- Mods:
  - latest added mods
  - latest updated mods
  - recently updated mods for a period
  - trending mods
  - mod metadata
  - mod changelogs
  - search or lookup specific mods
- Mod files:
  - list files for a mod
  - get file details
  - generate download links for a mod file
  - look up file metadata by MD5 hash
- Users:
  - validate API key / identify current account
  - list tracked mods
  - track or untrack mods
  - list endorsements
  - endorse or abstain from endorsing a mod
- Limits:
  - read rate-limit information from the API client/headers

Important download detail: for non-premium users, API download links may require
the download key and expiry embedded in an `nxm://` link from the website's
"Download with Manager" flow. That means this MCP should not try to bypass
Vortex or Nexus download rules. If download support is ever added, it should
prefer handing `nxm://` links to Vortex or recording metadata, not secretly
pulling archives.

### Nexus Mods GraphQL API

Nexus also has a GraphQL documentation site. The useful newer pieces for this
project are search-like queries and file-content metadata.

Most interesting GraphQL capabilities:

- `mods` style searching/filtering by mod id, game domain, name, category,
  author/uploader, status, language, adult flag, support for Vortex, downloads,
  endorsements, created/updated timestamps, tags, and description.
- `modFileContents`, which can search file paths inside mod archives by mod id,
  file id, game id, file path wildcard, exact path parts, file name wildcard,
  file extension, and file size.
- collection-related objects and image/collection metadata that may help map a
  Nexus Collection to mods and bundled assets if the public schema exposes the
  needed revision/manifest fields.
- `personalApiKey`, preferences, and other account-oriented fields, which should
  be treated carefully and not logged.

The file-content query is especially valuable for this MCP. It can help answer
questions like "which Nexus mod contains a plugin named X?" or "which mod ships
this mesh/script/interface file?" before the local staged archive has been fully
inspected.

### Vortex Extension API

The Vortex API is not the same thing as the Nexus Mods web API. It is Vortex's
extension API: JavaScript extensions can register games, installers, mod types,
load order systems, tools, actions, settings pages, and interact with Vortex
state.

For this project, a Vortex extension could eventually be useful as an optional
bridge, but it is a bigger step than calling Nexus metadata APIs. A Vortex
extension could give safer in-app state and event access than scraping files or
calling Vortex.exe from outside. It could also expose a local loopback endpoint
for this MCP.

Do not start there. Start with read-only Nexus metadata support.

## Why This Helps OpenClaw

Current local diagnosis infers mod purpose from staged files, plugin headers,
readmes, file names, Vortex profile state, and logs. That works, but it can be
blind when:

- Vortex metadata is incomplete.
- A mod was imported from a local archive and lost Nexus source metadata.
- A collection contains hundreds or thousands of mods.
- Two mods have similar local names.
- A staged folder is renamed.
- OpenClaw needs update/changelog context.
- The user asks what a mod does and the local archive has weak readmes.

Nexus API enrichment would add external truth:

- official mod name, author, summary, category, version, status, adult flag
- current file list and uploaded file metadata
- changelog information
- endorsements/download counts as weak popularity signals
- latest update timestamp
- tracked/endorsed state for the user, if they opt in
- file hash matches for local downloads
- archive content metadata from GraphQL where available

This would make `mod_knowledge_report`, `in_game_issue_report`,
`safe_session_report`, and `bug_report_bundle` easier for OpenClaw to understand
without making the user type everything manually.

## Proposed Features

### Phase 1: Read-Only Metadata Layer

Add a small Nexus client module using Python standard library HTTP calls.

Status: implemented in `server.py` first to keep packaging dependency-free.

New config inputs:

- `nexus_api_key`: optional tool argument
- `NEXUS_MODS_API_KEY`: optional environment variable
- `nexus_game_domain`: default `skyrimspecialedition`
- `nexus_cache_dir`: default local MCP cache folder

New internal pieces:

- server-side Nexus helper section
- `cache.json` under the Nexus cache folder
- redaction for API keys in logs and reports
- rate-limit metadata returned from response headers
- HTTP timeout handling and soft failures

New tools:

- `nexus_validate_key`
  - Checks whether the key works and returns safe account summary only.
- `nexus_mod_lookup`
  - Given game domain and mod id, returns mod metadata.
- `nexus_mod_files`
  - Given game domain and mod id, returns current file list.
- `nexus_file_info`
  - Given game domain, mod id, and file id, returns file metadata.
- `nexus_file_by_md5`
  - Given an archive hash, finds possible Nexus source files.
- `nexus_update_report`
  - Compares local Vortex metadata to current Nexus mod/file metadata.
- `nexus_enrich_mod_inventory`
  - Adds Nexus metadata to `inventory_mods` and `mod_knowledge_report`.

Implemented integration uses `include_nexus_metadata=true` on
`mod_knowledge_report`, `safe_session_report`, `skyrim_modded_play_report`, and
`bug_report_bundle`. The broad `skyrim_diagnostics_report` includes Nexus
metadata automatically when a key is configured.

Phase 1 should not download files, install mods, endorse mods, or change tracked
mods.

### Phase 2: Collection Awareness

Goal: make Nexus Collections more explainable without replacing Vortex.

Partial implementation now exists:

- `vortex_collection_report` reads collection-like state exposed by Vortex CLI.
- `collection_local_match_report` compares a supplied manifest-like JSON file to
  locally staged Nexus mod/file metadata.
- These tools remain read-only and do not install collection mods.

Possible tools:

- `nexus_collection_lookup`
  - Given a collection slug/id, fetch collection metadata if available.
- `nexus_collection_manifest_report`
  - Extract mod ids, file ids, external resources, bundled assets, and notes.
- `collection_local_match_report`
  - Compare a collection manifest against Vortex staging/profile state.

Useful outputs:

- missing mods/files
- mods in Vortex that are not part of the collection
- collection mods disabled in the selected profile
- external/manual resources that Vortex cannot fetch automatically
- bundled generated assets that should not be confused with normal Nexus mods

Safety rule: this phase should report, not auto-install.

### Phase 3: Optional NXM Diagnostics

Goal: make "Download with Manager" and imported archives less confusing.

Possible tools:

- `nexus_parse_nxm_link`
  - Parse `nxm://` into game domain, mod id, file id, key, and expiry.
- `nexus_nxm_diagnose`
  - Check whether the link is expired, malformed, wrong game, or missing file
    metadata.
- `vortex_nxm_handoff_plan`
  - Explain how Vortex should receive the link and what OpenClaw should watch
    for in logs.

If a future write-capable downloader exists, it must be explicit, respect Nexus
membership/download rules, and avoid stealing Vortex metadata. For this project,
the safer design is to hand the link to Vortex and use the API only to verify
metadata.

### Phase 4: Optional User Actions

Only after the read-only layer is stable:

- track/untrack a mod
- endorse/abstain from endorsing a mod

These are account actions. They should require:

- explicit user approval
- dry-run preview where possible
- no hidden batch changes
- no key logging
- clear audit log

## Tool Integration Matrix

| Existing Tool | Nexus API Improvement |
| --- | --- |
| `inventory_mods` | Add official Nexus names, mod ids, file ids, authors, versions, categories, and source URLs when metadata is available. |
| `mod_knowledge_report` | Use official summaries, categories, changelogs, file lists, and update dates to explain what mods do. |
| `in_game_issue_report` | Use Nexus file-content metadata to search plugin/script/mesh/interface paths even when local evidence is weak. |
| `safe_session_report` | Add a compact Nexus metadata health section: key status, stale mods, missing metadata, collection mismatch. |
| `bug_report_bundle` | Include redacted Nexus metadata diagnostics without including API keys. |
| `vortex_profile_deployment_report` | Compare enabled profile mods to Nexus/source metadata and collection expectations. |
| `redundant_mod_report` | Use Nexus mod/file ids and MD5 lookup to distinguish true duplicates from patches/translations. |

## Data Model

Suggested local normalized shape:

```json
{
  "gameDomain": "skyrimspecialedition",
  "modId": 12345,
  "fileId": 67890,
  "source": "nexus",
  "name": "Example Mod",
  "author": "Author",
  "category": "Gameplay",
  "version": "1.2.3",
  "updatedAt": "2026-05-01T00:00:00Z",
  "fileName": "Example-67890-1-2-3.7z",
  "sizeBytes": 1234567,
  "md5": "optional-if-known",
  "status": "published",
  "available": true,
  "containsAdultContent": false,
  "url": "https://www.nexusmods.com/skyrimspecialedition/mods/12345",
  "cache": {
    "fetchedAt": "2026-05-04T00:00:00Z",
    "ttlSeconds": 86400
  }
}
```

For local Vortex mods, attach this under a `nexus` field rather than replacing
the local evidence:

```json
{
  "mod": "Local Staged Folder Name",
  "vortexModId": "example-mod-id",
  "localEvidence": {},
  "nexus": {}
}
```

## Cache And Performance

Large collections need careful caching.

Rules:

- Cache mod metadata for 24 hours by default.
- Cache file lists for 24 hours by default.
- Cache failed lookups briefly, such as 15 minutes, to avoid retry loops.
- Never cache API keys in report JSON.
- Never log request headers.
- Include `cacheHit`, `fetchedAt`, and `rateLimitRemaining` summaries in tool
  output.
- Use `performance_mode=slow_model` to return only the highest-signal metadata.

The first implementation should be slow but safe. Then add cache indexes:

- by `gameDomain/modId`
- by `gameDomain/modId/fileId`
- by archive MD5
- by Vortex mod id
- by local staging folder path hash

## Security And Acceptable Use

Nexus API support must follow Nexus's acceptable-use policy:

- Do not impersonate Vortex or another application.
- Do not use another application's API key.
- Use a personal API key only for testing or personal use.
- Register the application before public-facing use.
- Send real application name/version headers.
- Do not scrape or fetch data en masse to rehost it.
- Do not store user API keys on a remote server.
- Do not log API keys.
- Respect rate limits and HTTP 429 responses.

Recommended headers for this project:

```text
Application-Name: vortex-skyrimse-mcp
Application-Version: <server version>
APIKEY: <user key, redacted from logs>
```

If/when the project becomes public-facing with API support, it should be
registered with Nexus Mods instead of relying on users' personal keys.

## Failure Handling

All Nexus calls should fail soft.

Examples:

- No API key: return `available=false` and explain how to add one.
- Invalid key: return a clear authentication finding, but keep local diagnosis.
- Rate limited: return partial cached data and a retry-after hint if available.
- Nexus offline: keep local reports working.
- Adult/hidden/deleted mod unavailable: report status, do not crash.
- Collection/private data unavailable: explain permission limits.

The MCP should never block local Vortex/Skyrim diagnosis just because Nexus is
offline.

## User Experience

No-hassle setup should look like this:

1. User runs MCP Doctor.
2. Doctor says Nexus API support is optional.
3. If user wants it, Doctor asks for a key or points them to the Nexus API Access
   page.
4. The key is stored locally only, preferably in a user-owned config file or
   OS credential store.
5. Reports show "Nexus metadata: available/unavailable/cached/rate-limited".

OpenClaw prompt:

```text
Use safe_session_report with performance_mode=slow_model and include Nexus metadata if available. Start with local setup/deployment findings, then mention stale or missing Nexus metadata. Do not apply changes.
```

## What Not To Build Yet

- Do not build a full downloader before read-only metadata is stable.
- Do not bypass Vortex Collections.
- Do not auto-install collection mods.
- Do not auto-update mods.
- Do not auto-endorse mods.
- Do not use Nexus data as the only reason to disable/delete mods.
- Do not rely on private/unstable GraphQL fields for destructive decisions.
- Do not store API keys in bug bundles.

## Recommended Implementation Order

1. Add docs and config model.
2. Add key validation and redaction tests.
3. Add read-only REST client with rate-limit handling.
4. Add `nexus_mod_lookup`, `nexus_mod_files`, and `nexus_file_by_md5`.
5. Enrich `mod_knowledge_report`.
6. Add `nexus_update_report`.
7. Add GraphQL file-content search behind an explicit flag.
8. Explore collection manifest lookup after the public schema is confirmed.
9. Consider a Vortex extension bridge only if Vortex CLI/file-state access keeps
   limiting reliability.

## Sources Checked

- Nexus Mods API launch article:
  https://www.nexusmods.com/ecosystem/news/13921
- Nexus Mods API Acceptable Use Policy:
  https://help.nexusmods.com/article/114-api-acceptable-use-policy
- Nexus Mods public API docs:
  https://app.swaggerhub.com/apis-docs/NexusMods/nexus-mods_public_api_params_in_form_data/1.0
- Official `node-nexus-api` client:
  https://github.com/Nexus-Mods/node-nexus-api
- Nexus Mods GraphQL docs:
  https://graphql.nexusmods.com/
- Vortex extension API:
  https://github.com/Nexus-Mods/vortex-api
