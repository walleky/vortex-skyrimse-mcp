# ADR 0001: Nexus API Key Ownership

Status: Accepted

Date: 2026-05-04

## Context

The MCP can use Nexus Mods metadata to improve Skyrim SE/Vortex diagnostics.
Vortex itself also talks to Nexus, but Vortex's authentication and application
state are owned by Vortex.

The user goal is low friction, but also stability, compatibility, and clear
recovery when something goes wrong.

## Decision

The MCP uses its own explicitly configured Nexus API key.

Accepted key sources:

- `NEXUS_MODS_API_KEY`
- `nexus_api_key_file`
- `nexus_api_key` direct tool argument for private testing

The MCP must not copy, read, scrape, borrow, or reuse Vortex's key.

The MCP must treat Nexus support as optional. Local Vortex/Skyrim diagnostics
continue without a key.

## Consequences

Benefits:

- easier to explain to users and OpenClaw
- easier to revoke or rotate credentials
- avoids impersonating Vortex
- reduces breakage when Vortex internals change
- keeps bug bundles and logs safer

Costs:

- users who want Nexus metadata must configure a key
- download/collection actions remain Vortex-owned
- private or account-limited Nexus data may be unavailable unless the user's key
  has access

## Guardrails

- Never log API keys or request headers.
- Redact `NEXUS_MODS_API_KEY`, `nexus_api_key`, token-like fields, and user paths.
- Do not include keys in bug-report bundles.
- Do not auto-download, auto-update, endorse, track, deploy, or delete mods.
- Respect rate limits and fail softly.

## Related Docs

- [NEXUS-API.md](NEXUS-API.md)
- [NEXUS-MODS-API-DESIGN.md](NEXUS-MODS-API-DESIGN.md)
- [SAFETY-UNDO.md](SAFETY-UNDO.md)
