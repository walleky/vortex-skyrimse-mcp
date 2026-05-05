#!/usr/bin/env python3
"""
Vortex Skyrim SE MCP server for Windows.

This is a dependency-free MCP stdio server. It exposes safe tools for an MCP
client to inspect a Vortex-managed Skyrim Special Edition install, diagnose
deployment/plugin/INI issues, and build conflict/redundancy reports.

Write actions are intentionally narrow and dry-run by default.
"""

from __future__ import annotations

import argparse
import configparser
import csv
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

try:
    import winreg  # type: ignore
except Exception:  # pragma: no cover - non-Windows test hosts
    winreg = None


SERVER_NAME = "vortex-skyrimse-mcp"
SERVER_VERSION = "0.2.24"
PROTOCOL_VERSION = "2025-06-18"
SKYRIM_APP_ID = "489830"
GAME_ID = "skyrimse"
NEXUS_GAME_DOMAIN = "skyrimspecialedition"
MAX_DEFAULT_TEXT_BYTES = 200_000
MAX_DEFAULT_FILES = 40_000
MAX_VORTEX_CLI_CHARS = 24_000
LOG_ENV_VAR = "VORTEX_SKYRIMSE_MCP_LOG_DIR"
LOG_TAIL_DEFAULT_BYTES = 80_000
NEXUS_API_BASE = "https://api.nexusmods.com/v1"
NEXUS_GRAPHQL_URL = "https://api.nexusmods.com/v2/graphql"
NEXUS_API_KEY_ENV_VAR = "NEXUS_MODS_API_KEY"
NEXUS_CACHE_ENV_VAR = "VORTEX_SKYRIMSE_MCP_NEXUS_CACHE_DIR"
NEXUS_DEFAULT_CACHE_TTL_SECONDS = 24 * 60 * 60
SCAN_CACHE_ENV_VAR = "VORTEX_SKYRIMSE_MCP_SCAN_CACHE_DIR"
SCAN_DEFAULT_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
XEDIT_EXE_NAMES = ("SSEEdit.exe", "xEdit.exe", "TES5Edit.exe")
RUNTIME_LOG_SUFFIXES = {".log", ".txt"}
CONFIG_PATCH_SUFFIXES = {".ini", ".json", ".toml", ".yaml", ".yml", ".xml", ".txt", ".cfg", ".conf", ".properties"}
RUNTIME_LOG_ERROR_TERMS = {
    "access violation",
    "address library",
    "cannot",
    "could not",
    "crash",
    "dll",
    "error",
    "exception",
    "failed",
    "fatal",
    "file was not configured",
    "file was not configured properly",
    "missing",
    "not configured",
    "not configured properly",
    "not found",
    "runtime",
    "warning",
}
RUNTIME_REFERENCE_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z0-9_ @#()[\].+\\/-]{1,180}\."
    r"(?:esp|esm|esl|dll|pex|psc|ini|json|toml|yaml|yml|xml|txt|swf|bsa))",
    re.IGNORECASE,
)
SENSITIVE_FIELD_NAMES = {
    "apikey",
    "api_key",
    "key",
    "nexus_api_key",
    "nexusapikey",
    "token",
    "authorization",
}


class ToolError(Exception):
    """Business error returned as a MCP tool error."""


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr, flush=True)


def now_stamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def iso_now() -> str:
    return _dt.datetime.now().isoformat(timespec="milliseconds")


def expand_path(value: Optional[str]) -> Optional[Path]:
    if not value:
        return None
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def default_log_dir(override: Optional[str] = None) -> Path:
    override_path = expand_path(override)
    if override_path:
        return override_path
    env_path = os.environ.get(LOG_ENV_VAR)
    if env_path:
        return expand_path(env_path) or Path(env_path)
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return (Path(base) / SERVER_NAME / "logs").resolve()
    return (Path.home() / f".{SERVER_NAME}" / "logs").resolve()


def is_sensitive_key_name(key: object) -> bool:
    lowered = str(key).lower().replace("-", "_")
    return lowered in SENSITIVE_FIELD_NAMES or lowered.endswith("_token") or lowered.endswith("_api_key")


def compact_for_log(value: Any, max_string: int = 1200, max_items: int = 30, depth: int = 0) -> Any:
    if depth > 4:
        return "<max-depth>"
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        return value if len(value) <= max_string else value[:max_string] + f"...<truncated {len(value) - max_string} chars>"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                result["..."] = f"{len(value) - max_items} more keys"
                break
            result[str(key)] = "<redacted>" if is_sensitive_key_name(key) else compact_for_log(item, max_string, max_items, depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        seq = list(value)
        result = [compact_for_log(item, max_string, max_items, depth + 1) for item in seq[:max_items]]
        if len(seq) > max_items:
            result.append(f"... {len(seq) - max_items} more items")
        return result
    return str(value)


def summarize_result_for_log(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        summary: Dict[str, Any] = {
            "type": "object",
            "keys": list(value.keys())[:40],
        }
        for key in ("issues", "findings", "actions", "profiles", "mods", "conflicts"):
            item = value.get(key)
            if isinstance(item, list):
                summary[f"{key}Count"] = len(item)
            elif isinstance(item, dict):
                summary[f"{key}Count"] = len(item)
        return summary
    if isinstance(value, list):
        return {"type": "array", "count": len(value)}
    return {"type": type(value).__name__}


def log_event(channel: str, event: str, data: Optional[Dict[str, Any]] = None) -> None:
    try:
        log_dir = default_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        safe_channel = re.sub(r"[^a-zA-Z0-9_.-]+", "-", channel).strip("-") or "server"
        log_path = log_dir / f"{safe_channel}-{_dt.datetime.now().strftime('%Y%m%d')}.jsonl"
        entry: Dict[str, Any] = {
            "ts": iso_now(),
            "server": SERVER_NAME,
            "version": SERVER_VERSION,
            "pid": os.getpid(),
            "channel": safe_channel,
            "event": event,
        }
        if data:
            entry["data"] = compact_for_log(data)
        with log_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:  # pragma: no cover - logging must not break MCP stdio
        if os.environ.get(LOG_ENV_VAR):
            eprint(f"{SERVER_NAME}: logging failed: {exc}")


def tail_file_text(path: Path, max_bytes: int = LOG_TAIL_DEFAULT_BYTES) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(max(0, size - max_bytes))
            data = handle.read(max_bytes)
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def recent_log_files(log_dir: Path, max_files: int = 12) -> List[Path]:
    if not log_dir.exists():
        return []
    files = [path for path in log_dir.glob("*.log") if path.is_file()]
    files.extend(path for path in log_dir.glob("*.jsonl") if path.is_file())
    files = sorted(set(files), key=lambda item: item.stat().st_mtime, reverse=True)
    return files[:max_files]


def log_file_summary(path: Path, include_tail: bool = False, max_tail_bytes: int = LOG_TAIL_DEFAULT_BYTES) -> Dict[str, Any]:
    stat = path.stat()
    result: Dict[str, Any] = {
        "path": str(path),
        "channel": log_channel_from_name(path.name),
        "name": path.name,
        "sizeBytes": stat.st_size,
        "modifiedAt": _dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }
    if include_tail:
        result["tail"] = tail_file_text(path, max_tail_bytes)
    return result


def log_channel_from_name(name: str) -> str:
    stem = Path(name).stem
    match = re.match(r"(.+)-\d{8}(?:-\d{6})?$", stem)
    return match.group(1) if match else stem


def redaction_replacements() -> List[Tuple[str, str]]:
    raw_pairs = [
        (os.environ.get("USERPROFILE"), "%USERPROFILE%"),
        (os.environ.get("LOCALAPPDATA"), "%LOCALAPPDATA%"),
        (os.environ.get("APPDATA"), "%APPDATA%"),
        (str(Path.home()), "%USERPROFILE%"),
        (os.environ.get(NEXUS_API_KEY_ENV_VAR), "%NEXUS_MODS_API_KEY%"),
    ]
    seen: set[str] = set()
    pairs: List[Tuple[str, str]] = []
    for raw, replacement in raw_pairs:
        if not raw:
            continue
        variants = {raw, raw.replace("/", "\\"), raw.replace("\\", "/"), raw.replace("\\", "\\\\")}
        for variant in variants:
            key = variant.lower()
            if len(variant) < 4 or key in seen:
                continue
            seen.add(key)
            pairs.append((variant, replacement))
    pairs.sort(key=lambda item: len(item[0]), reverse=True)
    return pairs


def redact_text(text: str) -> str:
    result = text
    for raw, replacement in redaction_replacements():
        result = re.sub(re.escape(raw), replacement, result, flags=re.IGNORECASE)
    return result


def redact_paths_in_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Path):
        return redact_text(str(value))
    if isinstance(value, dict):
        return {key: redact_paths_in_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_paths_in_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_paths_in_value(item) for item in value]
    return value


def bug_report_readme_text() -> str:
    return (
        "Vortex Skyrim SE MCP bug report\n"
        "\n"
        "Attach the JSON file in this zip to the GitHub issue, or ask OpenClaw to read it.\n"
        "If logs are included, they are recent tails, not full historical logs.\n"
        "The JSON may include local paths, mod names, plugin names, and MCP prompts.\n"
        "Review before posting publicly.\n"
    )


def write_bug_report_zip(
    zip_path: Path,
    output_path: Path,
    bundle: Dict[str, Any],
    log_files: List[Path],
    max_log_bytes: int,
    include_log_tails: bool = True,
    redact: bool = True,
) -> Dict[str, Any]:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    entries = ["README-BUG-REPORT.txt", output_path.name]
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README-BUG-REPORT.txt", bug_report_readme_text())
        archive.writestr(output_path.name, json.dumps(bundle, indent=2, ensure_ascii=False, default=str))
        if include_log_tails:
            for path in log_files:
                try:
                    arcname = f"logs/{path.name}.tail.txt"
                    tail = tail_file_text(path, max_log_bytes)
                    archive.writestr(arcname, redact_text(tail) if redact else tail)
                    entries.append(arcname)
                except OSError:
                    continue
    return {"zip_path": str(zip_path), "entries": entries}


def path_exists(path: Optional[Path]) -> bool:
    return bool(path and path.exists())


def read_text(path: Path, max_bytes: int = MAX_DEFAULT_TEXT_BYTES) -> str:
    data = path.read_bytes()[:max_bytes]
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def read_text_with_encoding(path: Path, max_bytes: int = MAX_DEFAULT_TEXT_BYTES) -> Tuple[str, str, bool]:
    size = path.stat().st_size
    truncated = size > max_bytes
    with path.open("rb") as handle:
        sample = handle.read(max_bytes)
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return sample.decode(enc), enc, truncated
        except UnicodeDecodeError:
            continue
    return sample.decode("utf-8", errors="replace"), "utf-8", truncated


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def rel_to(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)


def is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def json_content(data: Any, is_error: bool = False) -> Dict[str, Any]:
    text = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": data,
        "isError": is_error,
    }


def text_content(text: str, is_error: bool = False) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def registry_value(root: Any, subkey: str, name: str) -> Optional[str]:
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(root, subkey) as key:
            value, _kind = winreg.QueryValueEx(key, name)
            if value:
                return str(value)
    except OSError:
        return None
    return None


def find_steam_root() -> Optional[Path]:
    candidates: List[str] = []
    if winreg is not None:
        candidates.extend(
            value
            for value in [
                registry_value(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                registry_value(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamExe"),
                registry_value(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            ]
            if value
        )
    candidates.extend(
        [
            r"C:\Program Files (x86)\Steam",
            r"C:\Program Files\Steam",
        ]
    )

    for candidate in candidates:
        path = Path(candidate)
        if path.name.lower() == "steam.exe":
            path = path.parent
        if (path / "steamapps").exists():
            return path.resolve()
    return None


def acf_value(text: str, key: str) -> Optional[str]:
    match = re.search(rf'"{re.escape(key)}"\s+"([^"]+)"', text, flags=re.IGNORECASE)
    return match.group(1) if match else None


def steam_libraries(steam_root: Optional[Path]) -> List[Path]:
    if not steam_root:
        return []
    libs = [steam_root]
    library_file = steam_root / "steamapps" / "libraryfolders.vdf"
    if library_file.exists():
        text = read_text(library_file)
        for match in re.finditer(r'"path"\s+"([^"]+)"', text, flags=re.IGNORECASE):
            raw = match.group(1).replace(r"\\", "\\")
            path = Path(raw)
            if (path / "steamapps").exists():
                libs.append(path.resolve())
    seen: set[str] = set()
    result: List[Path] = []
    for lib in libs:
        key = str(lib).lower()
        if key not in seen:
            seen.add(key)
            result.append(lib)
    return result


def find_skyrim_dir(override: Optional[str] = None) -> Optional[Path]:
    override_path = expand_path(override)
    if override_path and (override_path / "SkyrimSE.exe").exists():
        return override_path

    reg = registry_value(
        winreg.HKEY_LOCAL_MACHINE if winreg else None,
        r"Software\WOW6432Node\Bethesda Softworks\Skyrim Special Edition",
        "Installed Path",
    ) if winreg else None
    if reg:
        path = Path(reg)
        if (path / "SkyrimSE.exe").exists():
            return path.resolve()

    steam_root = find_steam_root()
    for lib in steam_libraries(steam_root):
        manifest = lib / "steamapps" / f"appmanifest_{SKYRIM_APP_ID}.acf"
        if not manifest.exists():
            continue
        install_dir = acf_value(read_text(manifest), "installdir") or "Skyrim Special Edition"
        game_dir = lib / "steamapps" / "common" / install_dir
        if (game_dir / "SkyrimSE.exe").exists():
            return game_dir.resolve()

    for candidate in [
        Path(r"C:\Program Files (x86)\Steam\steamapps\common\Skyrim Special Edition"),
        Path(r"C:\Program Files\Steam\steamapps\common\Skyrim Special Edition"),
    ]:
        if (candidate / "SkyrimSE.exe").exists():
            return candidate.resolve()
    return None


def default_vortex_appdata(override: Optional[str] = None) -> Optional[Path]:
    override_path = expand_path(override)
    if override_path:
        return override_path
    appdata = os.environ.get("APPDATA")
    if appdata:
        return (Path(appdata) / "Vortex").resolve()
    return None


def default_local_appdata() -> Optional[Path]:
    value = os.environ.get("LOCALAPPDATA")
    return Path(value).resolve() if value else None


def find_vortex_exe(override: Optional[str] = None) -> Optional[Path]:
    override_path = expand_path(override)
    if override_path:
        if override_path.is_file():
            return override_path
        if override_path.is_dir() and (override_path / "Vortex.exe").exists():
            return (override_path / "Vortex.exe").resolve()

    candidates: List[Path] = []
    local = default_local_appdata()
    if local:
        candidates.extend(
            [
                local / "Programs" / "Vortex" / "Vortex.exe",
                local / "Vortex" / "Vortex.exe",
            ]
        )
        programs = local / "Programs"
        if programs.exists():
            try:
                candidates.extend(programs.glob("**/Vortex.exe"))
            except OSError:
                pass

    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        env_path = os.environ.get(env_name)
        if env_path:
            candidates.append(Path(env_path) / "Vortex" / "Vortex.exe")

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists():
            return candidate.resolve()
    return None


def state_path_segment(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace(".", "\\.")


def state_path(*parts: object) -> str:
    return ".".join(state_path_segment(part) for part in parts)


def split_state_path(value: str) -> List[str]:
    parts: List[str] = []
    current: List[str] = []
    escaped = False
    for char in value:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ".":
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    parts.append("".join(current))
    return parts


def set_nested(root: Dict[str, Any], parts: List[str], value: Any) -> None:
    cursor: Dict[str, Any] = root
    for part in parts[:-1]:
        next_value = cursor.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            cursor[part] = next_value
        cursor = next_value
    if parts:
        cursor[parts[-1]] = value


def nested_get(root: Dict[str, Any], parts: List[str]) -> Any:
    cursor: Any = root
    for part in parts:
        if not isinstance(cursor, dict) or part not in cursor:
            return None
        cursor = cursor[part]
    return cursor


def parse_state_value(raw: str) -> Any:
    value = raw.strip()
    if value in {"undefined", ""}:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def parse_vortex_get_output(stdout: str) -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    unparsed_lines: List[str] = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if " = " in line:
            key, raw_value = line.split(" = ", 1)
        elif "=" in line:
            key, raw_value = line.split("=", 1)
        else:
            unparsed_lines.append(raw_line)
            continue
        values[key.strip()] = parse_state_value(raw_value)
    return {"values": values, "unparsedLines": unparsed_lines, "raw": stdout}


def values_to_state(values: Dict[str, Any]) -> Dict[str, Any]:
    state: Dict[str, Any] = {}
    for key, value in values.items():
        set_nested(state, split_state_path(key), value)
    return state


def run_vortex_cli(
    cli_args: List[str],
    vortex_exe_override: Optional[str] = None,
    timeout_seconds: int = 60,
) -> Dict[str, Any]:
    vortex_exe = find_vortex_exe(vortex_exe_override)
    if not vortex_exe:
        log_event("vortex-cli", "missing_executable", {"override": vortex_exe_override})
        raise ToolError(
            "Vortex.exe was not found. Pass vortex_exe, or install Vortex in the normal per-user location."
        )
    call_id = uuid.uuid4().hex[:10]
    start = time.perf_counter()
    log_event(
        "vortex-cli",
        "start",
        {
            "callId": call_id,
            "vortex_exe": str(vortex_exe),
            "argCount": len(cli_args),
            "args": cli_args,
            "timeoutSeconds": timeout_seconds,
        },
    )
    try:
        proc = subprocess.run(
            [str(vortex_exe), *cli_args],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        log_event(
            "vortex-cli",
            "timeout",
            {"callId": call_id, "durationMs": int((time.perf_counter() - start) * 1000), "timeoutSeconds": timeout_seconds},
        )
        raise ToolError(
            f"Vortex CLI timed out after {timeout_seconds}s. Close Vortex and try again; the state database may be busy."
        ) from exc
    except OSError as exc:
        log_event(
            "vortex-cli",
            "os_error",
            {"callId": call_id, "durationMs": int((time.perf_counter() - start) * 1000), "error": str(exc)},
        )
        raise ToolError(f"Could not run Vortex CLI at {vortex_exe}: {exc}") from exc

    result = {
        "vortex_exe": str(vortex_exe),
        "args": cli_args,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
    log_event(
        "vortex-cli",
        "finish",
        {
            "callId": call_id,
            "durationMs": int((time.perf_counter() - start) * 1000),
            "returncode": proc.returncode,
            "stdoutBytes": len(proc.stdout.encode("utf-8", errors="replace")),
            "stderrBytes": len(proc.stderr.encode("utf-8", errors="replace")),
            "stdoutPreview": proc.stdout[:2000],
            "stderrPreview": proc.stderr[:2000],
        },
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        stdout = proc.stdout.strip()
        detail = stderr or stdout or f"exit code {proc.returncode}"
        raise ToolError(f"Vortex CLI failed: {detail}. Close Vortex and try again if the database is locked.")
    return result


def make_set_arg(change: Dict[str, Any]) -> str:
    path = change.get("path")
    if not isinstance(path, str) or not path:
        raise ToolError("Every Vortex state change needs a non-empty path.")
    value = json.dumps(change.get("value"), separators=(",", ":"))
    return f"{path}={value}"


def cli_char_count(cli_args: List[str]) -> int:
    return sum(len(arg) + 3 for arg in cli_args)


def batched_state_changes(changes: List[Dict[str, Any]], max_chars: int = MAX_VORTEX_CLI_CHARS) -> List[List[Dict[str, Any]]]:
    batches: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    current_args: List[str] = []
    for change in changes:
        set_arg = make_set_arg(change)
        pair = ["--set", set_arg]
        if cli_char_count(pair) > max_chars:
            raise ToolError(
                f"One Vortex state value is too large for a safe CLI call: {change.get('path')}"
            )
        if current and cli_char_count(current_args + pair) > max_chars:
            batches.append(current)
            current = []
            current_args = []
        current.append(change)
        current_args.extend(pair)
    if current:
        batches.append(current)
    return batches


def is_vortex_process_running() -> bool:
    if os.name != "nt":
        return False
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Vortex.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    output = (proc.stdout or "").lower()
    return "vortex.exe" in output and "no tasks" not in output


def vortex_state_get(
    paths: List[str],
    vortex_exe_override: Optional[str] = None,
    timeout_seconds: int = 60,
) -> Dict[str, Any]:
    if not paths:
        raise ToolError("At least one Vortex state path is required.")
    cli_args: List[str] = []
    for path in paths:
        cli_args.extend(["--get", path])
    result = run_vortex_cli(cli_args, vortex_exe_override, timeout_seconds)
    parsed = parse_vortex_get_output(result["stdout"])
    return {**result, "parsed": parsed, "state": values_to_state(parsed["values"])}


def vortex_state_set(
    changes: List[Dict[str, Any]],
    vortex_exe_override: Optional[str] = None,
    timeout_seconds: int = 60,
    allow_running_vortex: bool = False,
) -> Dict[str, Any]:
    if not changes:
        raise ToolError("No Vortex state changes were requested.")
    if not allow_running_vortex and is_vortex_process_running():
        raise ToolError(
            "Vortex.exe is running. Close Vortex before profile writes, or pass allow_running_vortex=true if you accept the race risk."
        )
    calls = []
    vortex_exe = None
    for batch in batched_state_changes(changes):
        cli_args: List[str] = []
        for change in batch:
            cli_args.extend(["--set", make_set_arg(change)])
        result = run_vortex_cli(cli_args, vortex_exe_override, timeout_seconds)
        vortex_exe = result["vortex_exe"]
        calls.append(
            {
                "changeCount": len(batch),
                "returncode": result["returncode"],
                "stdout": result["stdout"],
                "stderr": result["stderr"],
            }
        )
    return {
        "vortex_exe": vortex_exe,
        "changeCount": len(changes),
        "batchCount": len(calls),
        "calls": calls,
    }


def now_ms() -> int:
    return int(_dt.datetime.now().timestamp() * 1000)


def epoch_to_iso(value: Any) -> Optional[str]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric <= 0:
        return None
    seconds = numeric / 1000 if numeric > 10_000_000_000 else numeric
    try:
        return _dt.datetime.fromtimestamp(seconds).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def default_documents() -> Optional[Path]:
    home = Path.home()
    candidates = [
        home / "Documents",
        home / "OneDrive" / "Documents",
    ]
    for path in candidates:
        if path.exists():
            return path.resolve()
    return candidates[0].resolve()


def default_my_games_dir(override: Optional[str] = None) -> Optional[Path]:
    override_path = expand_path(override)
    if override_path:
        return override_path
    docs = default_documents()
    return (docs / "My Games" / "Skyrim Special Edition").resolve() if docs else None


def local_support_cache_dir(env_var: str, folder: str, override: Optional[str] = None) -> Path:
    override_path = expand_path(override)
    if override_path:
        return override_path
    env_path = os.environ.get(env_var)
    if env_path:
        return expand_path(env_path) or Path(env_path)
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return (Path(base) / SERVER_NAME / folder).resolve()
    return (Path.home() / f".{SERVER_NAME}" / folder).resolve()


def nexus_default_cache_dir(override: Optional[str] = None) -> Path:
    return local_support_cache_dir(NEXUS_CACHE_ENV_VAR, "nexus-cache", override)


def scan_default_cache_dir(override: Optional[str] = None) -> Path:
    return local_support_cache_dir(SCAN_CACHE_ENV_VAR, "scan-cache", override)


def nexus_game_domain(args: Dict[str, Any]) -> str:
    raw = str(args.get("nexus_game_domain") or args.get("game_domain_name") or NEXUS_GAME_DOMAIN).strip().lower()
    return raw or NEXUS_GAME_DOMAIN


def nexus_api_key(args: Dict[str, Any]) -> Optional[str]:
    direct = str(args.get("nexus_api_key") or "").strip()
    if direct:
        return direct
    key_file = expand_path(args.get("nexus_api_key_file"))
    if key_file and key_file.exists() and key_file.is_file():
        try:
            return read_text(key_file, 20_000).strip() or None
        except OSError:
            return None
    env_value = os.environ.get(NEXUS_API_KEY_ENV_VAR)
    return env_value.strip() if env_value else None


def nexus_key_source(args: Dict[str, Any]) -> Optional[str]:
    if str(args.get("nexus_api_key") or "").strip():
        return "tool_argument"
    key_file = expand_path(args.get("nexus_api_key_file"))
    if key_file and key_file.exists() and key_file.is_file():
        return "file"
    if os.environ.get(NEXUS_API_KEY_ENV_VAR):
        return NEXUS_API_KEY_ENV_VAR
    return None


def nexus_config_status(args: Dict[str, Any]) -> Dict[str, Any]:
    configured = bool(nexus_api_key(args))
    return {
        "configured": configured,
        "keySource": nexus_key_source(args),
        "gameDomain": nexus_game_domain(args),
        "cacheDir": str(nexus_default_cache_dir(args.get("nexus_cache_dir"))),
        "apiBase": NEXUS_API_BASE,
        "notes": [
            "Use this MCP's own Nexus API key or NEXUS_MODS_API_KEY; do not borrow Vortex's application key.",
            "Nexus API metadata is optional. Local Skyrim/Vortex diagnostics still work without it.",
        ],
    }


def nexus_cache_path(args: Dict[str, Any]) -> Path:
    return nexus_default_cache_dir(args.get("nexus_cache_dir")) / "cache.json"


def nexus_cache_enabled(args: Dict[str, Any]) -> bool:
    return bool(args.get("nexus_use_cache", True))


def load_nexus_cache(args: Dict[str, Any]) -> Dict[str, Any]:
    path = nexus_cache_path(args)
    if not path.exists():
        return {}
    try:
        data = json.loads(read_text(path, 5_000_000))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_nexus_cache(args: Dict[str, Any], cache: Dict[str, Any]) -> None:
    path = nexus_cache_path(args)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text(path, json.dumps(cache, indent=2, ensure_ascii=False, default=str))


def nexus_cache_key(path: str, params: Optional[Dict[str, Any]] = None) -> str:
    raw = path
    if params:
        raw += "?" + urllib.parse.urlencode(sorted((str(k), str(v)) for k, v in params.items()))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def nexus_rate_limit_from_headers(headers: Any) -> Dict[str, Optional[int]]:
    def read_int(name: str) -> Optional[int]:
        value = headers.get(name) if headers else None
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    return {
        "dailyRemaining": read_int("x-rl-daily-remaining"),
        "dailyLimit": read_int("x-rl-daily-limit"),
        "hourlyRemaining": read_int("x-rl-hourly-remaining"),
        "hourlyLimit": read_int("x-rl-hourly-limit"),
    }


def nexus_url(path: str, params: Optional[Dict[str, Any]] = None) -> str:
    base = NEXUS_API_BASE.rstrip("/") + "/" + path.lstrip("/")
    if params:
        return base + "?" + urllib.parse.urlencode(params)
    return base


def parse_json_body(raw: str) -> Any:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"raw": raw[:2000]}


def nexus_http_get(
    args: Dict[str, Any],
    path: str,
    params: Optional[Dict[str, Any]] = None,
    cache_namespace: Optional[str] = None,
) -> Dict[str, Any]:
    key = nexus_api_key(args)
    ttl = int(args.get("nexus_cache_ttl_seconds", NEXUS_DEFAULT_CACHE_TTL_SECONDS))
    cache_id = f"{cache_namespace or 'rest'}:{nexus_cache_key(path, params)}"
    fetched_at = time.time()
    if nexus_cache_enabled(args) and cache_namespace:
        cache = load_nexus_cache(args)
        entry = cache.get(cache_id)
        if isinstance(entry, dict) and (fetched_at - float(entry.get("fetchedAtEpoch", 0))) <= ttl:
            return {
                "ok": True,
                "available": True,
                "cacheHit": True,
                "statusCode": entry.get("statusCode", 200),
                "data": entry.get("data"),
                "fetchedAt": entry.get("fetchedAt"),
                "rateLimit": entry.get("rateLimit", {}),
            }

    if not key:
        return {
            "ok": False,
            "available": False,
            "cacheHit": False,
            "statusCode": None,
            "error": "Nexus API key is not configured.",
            "keyConfigured": False,
            "keySource": None,
        }

    url = nexus_url(path, params)
    headers = {
        "Accept": "application/json",
        "APIKEY": key,
        "Application-Name": SERVER_NAME,
        "Application-Version": SERVER_VERSION,
        "User-Agent": f"{SERVER_NAME}/{SERVER_VERSION}",
    }
    timeout = max(1, int(args.get("nexus_timeout_seconds", args.get("timeout_seconds", 20))))
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            data = parse_json_body(raw)
            rate_limit = nexus_rate_limit_from_headers(response.headers)
            result = {
                "ok": True,
                "available": True,
                "cacheHit": False,
                "statusCode": response.status,
                "data": data,
                "fetchedAt": iso_now(),
                "rateLimit": rate_limit,
            }
            if nexus_cache_enabled(args) and cache_namespace:
                cache = load_nexus_cache(args)
                cache[cache_id] = {**result, "fetchedAtEpoch": fetched_at}
                write_nexus_cache(args, cache)
            return result
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        data = parse_json_body(raw)
        message = (data.get("message") or data.get("error")) if isinstance(data, dict) else str(exc)
        return {
            "ok": False,
            "available": False,
            "cacheHit": False,
            "statusCode": exc.code,
            "error": message or str(exc),
            "data": data,
            "rateLimit": nexus_rate_limit_from_headers(exc.headers),
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "ok": False,
            "available": False,
            "cacheHit": False,
            "statusCode": None,
            "error": str(exc),
        }


def nexus_int_arg(args: Dict[str, Any], key: str, label: str) -> int:
    raw = args.get(key)
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        raise ToolError(f"{label} must be a positive integer.") from None
    if value <= 0:
        raise ToolError(f"{label} must be a positive integer.")
    return value


def normalize_nexus_mod(data: Any, game_domain: str) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {"rawType": type(data).__name__}
    mod_id = data.get("mod_id") or data.get("modId") or data.get("id")
    return {
        "modId": mod_id,
        "gameDomain": data.get("domain_name") or data.get("domainName") or game_domain,
        "name": data.get("name"),
        "summary": data.get("summary"),
        "version": data.get("version"),
        "author": data.get("author"),
        "uploader": data.get("uploader"),
        "categoryId": data.get("category_id") or data.get("categoryId"),
        "category": data.get("category_name") or data.get("categoryName"),
        "createdAt": data.get("created_time") or data.get("createdAt"),
        "updatedAt": data.get("updated_time") or data.get("updatedAt"),
        "status": data.get("status"),
        "available": data.get("available"),
        "allowRating": data.get("allow_rating") or data.get("allowRating"),
        "containsAdultContent": data.get("contains_adult_content") or data.get("containsAdultContent"),
        "downloads": data.get("downloads") or data.get("downloads_count") or data.get("downloadsCount"),
        "endorsements": data.get("endorsements") or data.get("endorsement_count") or data.get("endorsementsCount"),
        "url": f"https://www.nexusmods.com/{game_domain}/mods/{mod_id}" if mod_id else None,
    }


def normalize_nexus_file(data: Any, game_domain: str, mod_id: Optional[int] = None) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {"rawType": type(data).__name__}
    file_id = data.get("file_id") or data.get("fileId") or data.get("id")
    actual_mod_id = mod_id or data.get("mod_id") or data.get("modId")
    return {
        "modId": actual_mod_id,
        "fileId": file_id,
        "uid": data.get("uid"),
        "gameDomain": game_domain,
        "name": data.get("name"),
        "fileName": data.get("file_name") or data.get("fileName"),
        "version": data.get("version"),
        "modVersion": data.get("mod_version") or data.get("modVersion"),
        "categoryId": data.get("category_id") or data.get("categoryId"),
        "category": data.get("category_name") or data.get("categoryName"),
        "isPrimary": data.get("is_primary") or data.get("isPrimary"),
        "sizeBytes": data.get("size") or data.get("sizeBytes"),
        "uploadedAt": data.get("uploaded_time") or data.get("uploadedAt"),
        "description": data.get("description"),
        "externalVirusScanUrl": data.get("external_virus_scan_url") or data.get("externalVirusScanUrl"),
        "contentPreviewUrl": data.get("content_preview_url") or data.get("contentPreviewUrl"),
        "url": f"https://www.nexusmods.com/{game_domain}/mods/{actual_mod_id}?tab=files&file_id={file_id}"
        if actual_mod_id and file_id
        else None,
    }


def nexus_validate_key(args: Dict[str, Any]) -> Dict[str, Any]:
    request = nexus_http_get(args, "/users/validate", cache_namespace=None)
    if not request.get("ok"):
        return {
            "available": False,
            "configured": bool(nexus_api_key(args)),
            "keySource": nexus_key_source(args),
            "error": request.get("error"),
            "statusCode": request.get("statusCode"),
            "notes": [
                "Use NEXUS_MODS_API_KEY or nexus_api_key_file for this MCP.",
                "Do not copy or reuse Vortex's application API key.",
            ],
        }
    data = request.get("data") if isinstance(request.get("data"), dict) else {}
    return {
        "available": True,
        "configured": True,
        "keySource": nexus_key_source(args),
        "user": {
            "userId": data.get("user_id") or data.get("userId"),
            "name": data.get("name"),
            "isPremium": data.get("is_premium") or data.get("isPremium"),
            "isSupporter": data.get("is_supporter") or data.get("isSupporter"),
            "profileUrl": data.get("profile_url") or data.get("profileUrl"),
        },
        "rateLimit": request.get("rateLimit"),
        "notes": ["The API key was validated without logging the key."],
    }


def nexus_mod_lookup(args: Dict[str, Any]) -> Dict[str, Any]:
    game_domain = nexus_game_domain(args)
    mod_id = nexus_int_arg(args, "mod_id", "mod_id")
    request = nexus_http_get(
        args,
        f"/games/{urllib.parse.quote(game_domain)}/mods/{mod_id}",
        cache_namespace=f"mod:{game_domain}:{mod_id}",
    )
    result = {
        "available": bool(request.get("ok")),
        "gameDomain": game_domain,
        "modId": mod_id,
        "cacheHit": request.get("cacheHit", False),
        "statusCode": request.get("statusCode"),
        "rateLimit": request.get("rateLimit", {}),
    }
    if not request.get("ok"):
        result["error"] = request.get("error")
        return result
    result["mod"] = normalize_nexus_mod(request.get("data"), game_domain)
    if bool(args.get("include_raw", False)):
        result["raw"] = request.get("data")
    return result


def nexus_mod_files(args: Dict[str, Any]) -> Dict[str, Any]:
    game_domain = nexus_game_domain(args)
    mod_id = nexus_int_arg(args, "mod_id", "mod_id")
    request = nexus_http_get(
        args,
        f"/games/{urllib.parse.quote(game_domain)}/mods/{mod_id}/files",
        cache_namespace=f"mod-files:{game_domain}:{mod_id}",
    )
    result = {
        "available": bool(request.get("ok")),
        "gameDomain": game_domain,
        "modId": mod_id,
        "cacheHit": request.get("cacheHit", False),
        "statusCode": request.get("statusCode"),
        "rateLimit": request.get("rateLimit", {}),
    }
    if not request.get("ok"):
        result["error"] = request.get("error")
        return result
    data = request.get("data")
    raw_files = data.get("files", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    files = [normalize_nexus_file(item, game_domain, mod_id) for item in raw_files if isinstance(item, dict)]
    result["fileCount"] = len(files)
    result["files"] = files
    if isinstance(data, dict) and data.get("file_updates") is not None:
        result["fileUpdates"] = data.get("file_updates")
    if bool(args.get("include_raw", False)):
        result["raw"] = data
    return result


def nexus_file_info(args: Dict[str, Any]) -> Dict[str, Any]:
    game_domain = nexus_game_domain(args)
    mod_id = nexus_int_arg(args, "mod_id", "mod_id")
    file_id = nexus_int_arg(args, "file_id", "file_id")
    request = nexus_http_get(
        args,
        f"/games/{urllib.parse.quote(game_domain)}/mods/{mod_id}/files/{file_id}",
        cache_namespace=f"file:{game_domain}:{mod_id}:{file_id}",
    )
    result = {
        "available": bool(request.get("ok")),
        "gameDomain": game_domain,
        "modId": mod_id,
        "fileId": file_id,
        "cacheHit": request.get("cacheHit", False),
        "statusCode": request.get("statusCode"),
        "rateLimit": request.get("rateLimit", {}),
    }
    if not request.get("ok"):
        result["error"] = request.get("error")
        return result
    result["file"] = normalize_nexus_file(request.get("data"), game_domain, mod_id)
    if bool(args.get("include_raw", False)):
        result["raw"] = request.get("data")
    return result


def nexus_file_by_md5(args: Dict[str, Any]) -> Dict[str, Any]:
    game_domain = nexus_game_domain(args)
    md5_hash = str(args.get("md5") or args.get("md5_hash") or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{32}", md5_hash):
        raise ToolError("md5 must be a 32-character hexadecimal MD5 hash.")
    request = nexus_http_get(
        args,
        f"/games/{urllib.parse.quote(game_domain)}/mods/md5_search/{md5_hash}",
        cache_namespace=f"md5:{game_domain}:{md5_hash}",
    )
    result = {
        "available": bool(request.get("ok")),
        "gameDomain": game_domain,
        "md5": md5_hash,
        "cacheHit": request.get("cacheHit", False),
        "statusCode": request.get("statusCode"),
        "rateLimit": request.get("rateLimit", {}),
    }
    if not request.get("ok"):
        result["error"] = request.get("error")
        return result
    data = request.get("data")
    raw_matches = data if isinstance(data, list) else data.get("matches", []) if isinstance(data, dict) else []
    matches = []
    for item in raw_matches:
        if isinstance(item, dict):
            match = {
                "mod": normalize_nexus_mod(item.get("mod") if isinstance(item.get("mod"), dict) else item, game_domain),
                "file": normalize_nexus_file(item.get("file") if isinstance(item.get("file"), dict) else item, game_domain),
            }
            matches.append(match)
    result["matchCount"] = len(matches)
    result["matches"] = matches
    if bool(args.get("include_raw", False)):
        result["raw"] = data
    return result


def nexus_parse_nxm_link(args: Dict[str, Any]) -> Dict[str, Any]:
    link = str(args.get("nxm_link") or args.get("url") or "").strip()
    if not link:
        raise ToolError("nxm_link is required.")
    parsed = urllib.parse.urlparse(link)
    if parsed.scheme.lower() != "nxm":
        raise ToolError("nxm_link must start with nxm://")
    parts = [part for part in parsed.path.split("/") if part]
    query = urllib.parse.parse_qs(parsed.query)
    mod_id = parts[1] if len(parts) >= 2 and parts[0].lower() == "mods" else None
    file_id = parts[3] if len(parts) >= 4 and parts[2].lower() == "files" else None
    expires = query.get("expires", [None])[0]
    key = query.get("key", [None])[0]
    return {
        "gameDomain": parsed.netloc.lower(),
        "modId": int(mod_id) if mod_id and mod_id.isdigit() else mod_id,
        "fileId": int(file_id) if file_id and file_id.isdigit() else file_id,
        "hasDownloadKey": bool(key),
        "expires": int(expires) if expires and expires.isdigit() else expires,
        "isExpired": bool(expires and expires.isdigit() and int(expires) < int(time.time())),
        "notes": [
            "For non-premium users, Nexus download links may require this website-generated key and expiry.",
            "This MCP should hand nxm links to Vortex for installation instead of bypassing Vortex metadata.",
        ],
    }


def metadata_first(metadata: Dict[str, Any], *keys: str) -> Optional[str]:
    lower_map = {str(key).lower(): value for key, value in metadata.items()}
    for key in keys:
        value = lower_map.get(key.lower())
        if value not in (None, ""):
            return str(value)
    return None


def local_nexus_ids(summary: Dict[str, Any], profile: Optional[Dict[str, Any]] = None) -> Dict[str, Optional[int]]:
    metadata = summary.get("metadata") if isinstance(summary.get("metadata"), dict) else {}
    profile = profile if isinstance(profile, dict) else {}

    def parse_int(value: Any) -> Optional[int]:
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return None

    mod_id = parse_int(profile.get("nexusModId") or metadata_first(metadata, "modId", "nexusModId", "nexus_id"))
    file_id = parse_int(profile.get("nexusFileId") or metadata_first(metadata, "fileId", "nexusFileId", "file_id"))
    return {"modId": mod_id, "fileId": file_id}


def local_mod_version(summary: Dict[str, Any], profile: Optional[Dict[str, Any]] = None) -> Optional[str]:
    metadata = summary.get("metadata") if isinstance(summary.get("metadata"), dict) else {}
    profile = profile if isinstance(profile, dict) else {}
    return (
        str(profile.get("version"))
        if profile.get("version") not in (None, "")
        else metadata_first(metadata, "version", "modVersion", "installedVersion")
    )


def nexus_update_report(args: Dict[str, Any]) -> Dict[str, Any]:
    _vortex_appdata, _skyrim_dir, staging_dir, _my_games = get_context_paths(args)
    if not staging_dir or not staging_dir.exists():
        raise ToolError("Vortex staging folder was not found. Pass staging_dir explicitly.")
    max_mods = int(args.get("max_mods", 500))
    max_lookup_mods = int(args.get("nexus_max_lookup_mods", args.get("max_nexus_lookup_mods", 80)))
    max_files_per_mod = int(args.get("max_files_per_mod", 3000))
    game_domain = nexus_game_domain(args)
    profile_lookup = profile_lookup_for_staging(args, staging_dir) if bool(args.get("include_profile_state", True)) else {"modsByPath": {}}
    profile_by_path = profile_lookup.get("modsByPath") if isinstance(profile_lookup.get("modsByPath"), dict) else {}

    if not nexus_api_key(args):
        return {
            "available": False,
            "configured": False,
            "gameDomain": game_domain,
            "checkedModCount": 0,
            "missingSourceMetadata": [],
            "notes": [
                "Nexus API key is not configured. Set NEXUS_MODS_API_KEY or pass nexus_api_key_file.",
                "Local Skyrim/Vortex diagnostics still work without Nexus metadata.",
            ],
        }

    checked = []
    missing_source = []
    skipped_lookup_limit = []
    stale = []
    unavailable = []
    errors = []
    mod_dirs = sorted([path for path in staging_dir.iterdir() if path.is_dir()], key=lambda path: path.name.lower())[:max_mods]
    scan_cache = load_scan_cache(args) if scan_cache_enabled(args) else {}
    for mod_dir in mod_dirs:
        summary = mod_summary_cached(mod_dir, include_files=False, max_files=max_files_per_mod, args=args, cache=scan_cache)
        try:
            profile_key = str(mod_dir.resolve()).lower()
        except OSError:
            profile_key = str(mod_dir).lower()
        profile = profile_by_path.get(profile_key)
        ids = local_nexus_ids(summary, profile if isinstance(profile, dict) else None)
        if not ids.get("modId"):
            missing_source.append({"mod": summary.get("name"), "reason": "No Nexus mod id found in local/Vortex metadata."})
            continue
        if len(checked) >= max_lookup_mods:
            skipped_lookup_limit.append({"mod": summary.get("name"), "modId": ids.get("modId"), "fileId": ids.get("fileId")})
            continue
        lookup = nexus_mod_lookup({**args, "mod_id": ids["modId"], "nexus_game_domain": game_domain})
        if not lookup.get("available"):
            errors.append({"mod": summary.get("name"), "modId": ids["modId"], "error": lookup.get("error")})
            continue
        remote = lookup.get("mod") if isinstance(lookup.get("mod"), dict) else {}
        local_version = local_mod_version(summary, profile if isinstance(profile, dict) else None)
        remote_version = str(remote.get("version")) if remote.get("version") not in (None, "") else None
        item = {
            "mod": summary.get("name"),
            "modId": ids.get("modId"),
            "fileId": ids.get("fileId"),
            "localVersion": local_version,
            "currentVersion": remote_version,
            "nexusName": remote.get("name"),
            "category": remote.get("category"),
            "updatedAt": remote.get("updatedAt"),
            "status": remote.get("status"),
            "available": remote.get("available"),
            "url": remote.get("url"),
            "cacheHit": lookup.get("cacheHit", False),
        }
        checked.append(item)
        if remote.get("available") is False or str(remote.get("status") or "").lower() not in {"", "published"}:
            unavailable.append(item)
        if local_version and remote_version and local_version != remote_version:
            stale.append(item)

    if scan_cache_enabled(args):
        write_scan_cache(args, scan_cache)

    return {
        "available": True,
        "configured": True,
        "gameDomain": game_domain,
        "checkedModCount": len(checked),
        "availableLocalModCount": len(mod_dirs),
        "lookupLimit": max_lookup_mods,
        "skippedLookupLimitCount": len(skipped_lookup_limit),
        "staleCount": len(stale),
        "unavailableCount": len(unavailable),
        "missingSourceMetadataCount": len(missing_source),
        "checkedMods": checked[:100],
        "staleMods": stale,
        "unavailableMods": unavailable,
        "missingSourceMetadata": missing_source[:100],
        "skippedLookupLimit": skipped_lookup_limit[:100],
        "errors": errors[:50],
        "profileStateAvailable": bool(profile_lookup.get("available")),
        "notes": [
            "This report is read-only and compares local/Vortex metadata to current Nexus metadata.",
            "A version mismatch is a review signal, not an automatic update instruction.",
            "Do not auto-update or uninstall mods from this report alone.",
        ],
    }


def scan_cache_path(args: Dict[str, Any]) -> Path:
    return scan_default_cache_dir(args.get("scan_cache_dir")) / "mod-summary-cache.json"


def scan_cache_enabled(args: Dict[str, Any]) -> bool:
    return bool(args.get("use_scan_cache", True))


def load_scan_cache(args: Dict[str, Any]) -> Dict[str, Any]:
    path = scan_cache_path(args)
    if not path.exists():
        return {}
    try:
        data = json.loads(read_text(path, 20_000_000))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_scan_cache(args: Dict[str, Any], cache: Dict[str, Any]) -> None:
    path = scan_cache_path(args)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text(path, json.dumps(cache, indent=2, ensure_ascii=False, default=str))
    except Exception as exc:
        log_event("scan-cache", "write_failed", {"path": str(path), "error": str(exc)})


def mod_dir_cache_signature(mod_dir: Path) -> Dict[str, Any]:
    def stat_part(path: Path) -> Optional[Dict[str, Any]]:
        try:
            stat = path.stat()
            return {
                "name": path.name,
                "isDir": path.is_dir(),
                "size": stat.st_size if path.is_file() else None,
                "mtimeNs": getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)),
            }
        except OSError:
            return None

    try:
        stat = mod_dir.stat()
        immediate: List[Dict[str, Any]] = []
        for child in sorted(mod_dir.iterdir(), key=lambda item: item.name.lower())[:200]:
            part = stat_part(child)
            if part:
                immediate.append(part)
        metadata_stats = [
            part
            for name in ("meta.ini", "info.json", "mod.json")
            for part in [stat_part(mod_dir / name)]
            if part
        ]
        return {
            "rootMtimeNs": getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)),
            "rootCtimeNs": getattr(stat, "st_ctime_ns", int(stat.st_ctime * 1_000_000_000)),
            "immediate": immediate,
            "metadata": metadata_stats,
        }
    except OSError:
        return {"rootMtimeNs": None, "rootCtimeNs": None}


def mod_summary_cache_key(mod_dir: Path, include_files: bool, max_files: int) -> str:
    try:
        root = str(mod_dir.resolve()).lower()
    except OSError:
        root = str(mod_dir).lower()
    raw = json.dumps(
        {
            "schema": "mod-summary-v2",
            "root": root,
            "includeFiles": bool(include_files),
            "maxFiles": int(max_files),
            "serverVersion": SERVER_VERSION,
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def mod_summary_cached(
    mod_dir: Path,
    include_files: bool = False,
    max_files: int = 5000,
    args: Optional[Dict[str, Any]] = None,
    cache: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    args = args or {}
    if not scan_cache_enabled(args):
        summary = mod_summary(mod_dir, include_files=include_files, max_files=max_files)
        summary["_cache"] = {"enabled": False, "hit": False}
        return summary

    own_cache = cache is None
    cache_data = cache if cache is not None else load_scan_cache(args)
    entries = cache_data.setdefault("entries", {}) if isinstance(cache_data, dict) else {}
    key = mod_summary_cache_key(mod_dir, include_files, max_files)
    signature = mod_dir_cache_signature(mod_dir)
    ttl = int(args.get("scan_cache_ttl_seconds", SCAN_DEFAULT_CACHE_TTL_SECONDS))
    now = time.time()
    entry = entries.get(key) if isinstance(entries, dict) else None
    if (
        isinstance(entry, dict)
        and entry.get("signature") == signature
        and (now - float(entry.get("fetchedAtEpoch", 0))) <= ttl
        and isinstance(entry.get("summary"), dict)
    ):
        summary = json.loads(json.dumps(entry["summary"], default=str))
        summary["_cache"] = {"enabled": True, "hit": True, "cacheKey": key}
        return summary

    summary = mod_summary(mod_dir, include_files=include_files, max_files=max_files)
    summary["_cache"] = {"enabled": True, "hit": False, "cacheKey": key}
    entries[key] = {
        "signature": signature,
        "summary": {k: v for k, v in summary.items() if k != "_cache"},
        "fetchedAt": iso_now(),
        "fetchedAtEpoch": now,
    }
    cache_data["schema"] = "vortex-skyrimse-mcp-scan-cache-v1"
    cache_data["updatedAt"] = iso_now()
    if own_cache:
        write_scan_cache(args, cache_data)
    return summary


def scan_cache_status(args: Dict[str, Any]) -> Dict[str, Any]:
    cache = load_scan_cache(args)
    entries = cache.get("entries") if isinstance(cache.get("entries"), dict) else {}
    path = scan_cache_path(args)
    return {
        "enabledByDefault": True,
        "enabledForThisCall": scan_cache_enabled(args),
        "path": str(path),
        "exists": path.exists(),
        "entryCount": len(entries),
        "ttlSeconds": int(args.get("scan_cache_ttl_seconds", SCAN_DEFAULT_CACHE_TTL_SECONDS)),
        "envVar": SCAN_CACHE_ENV_VAR,
        "notes": [
            "The scan cache stores derived local mod summaries only; it does not store Nexus API keys.",
            "It is a speed hint for large collections. Use no_scan_cache=true or --no-scan-cache for a fresh scan.",
        ],
    }


def staging_candidates(
    vortex_appdata: Optional[Path],
    override: Optional[str] = None,
) -> List[Path]:
    result: List[Path] = []
    override_path = expand_path(override)
    if override_path:
        result.append(override_path)
    if vortex_appdata:
        result.extend(
            [
                vortex_appdata / GAME_ID / "mods",
                vortex_appdata / "mods" / GAME_ID,
            ]
        )
    seen: set[str] = set()
    unique: List[Path] = []
    for path in result:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path.resolve())
    return unique


def choose_staging_dir(vortex_appdata: Optional[Path], override: Optional[str] = None) -> Optional[Path]:
    for candidate in staging_candidates(vortex_appdata, override):
        if candidate.exists():
            return candidate
    candidates = staging_candidates(vortex_appdata, override)
    return candidates[0] if candidates else None


def plugin_state_paths(local_appdata: Optional[Path] = None) -> Dict[str, Optional[str]]:
    base = local_appdata or default_local_appdata()
    if not base:
        return {"plugins_txt": None, "loadorder_txt": None}
    skyrim = base / "Skyrim Special Edition"
    return {
        "plugins_txt": str(skyrim / "plugins.txt") if (skyrim / "plugins.txt").exists() else None,
        "loadorder_txt": str(skyrim / "loadorder.txt") if (skyrim / "loadorder.txt").exists() else None,
    }


def detect_environment(args: Dict[str, Any]) -> Dict[str, Any]:
    vortex_appdata = default_vortex_appdata(args.get("vortex_appdata"))
    vortex_exe = find_vortex_exe(args.get("vortex_exe"))
    skyrim_dir = find_skyrim_dir(args.get("skyrim_dir"))
    staging_dir = choose_staging_dir(vortex_appdata, args.get("staging_dir"))
    local_appdata = expand_path(args.get("local_appdata")) or default_local_appdata()
    my_games = default_my_games_dir(args.get("my_games_dir"))
    steam_root = find_steam_root()
    issues: List[str] = []

    if not path_exists(skyrim_dir):
        issues.append("SkyrimSE.exe was not found. Run Skyrim SE once through Steam, or pass skyrim_dir.")
    elif not (skyrim_dir / "Data").exists():
        issues.append("Skyrim Data folder is missing under the detected game directory.")

    if not path_exists(vortex_appdata):
        issues.append("Vortex AppData folder was not found. Start Vortex once, or pass vortex_appdata.")
    if not path_exists(vortex_exe):
        issues.append("Vortex.exe was not found. Profile-aware tools need Vortex's own CLI; pass vortex_exe if needed.")
    if not path_exists(staging_dir):
        issues.append("Vortex Skyrim SE staging folder was not found. Pass staging_dir if Vortex uses a custom path.")

    skse_loader = skyrim_dir / "skse64_loader.exe" if skyrim_dir else None
    if skyrim_dir and not path_exists(skse_loader):
        issues.append("SKSE64 loader is not installed beside SkyrimSE.exe.")

    paths = plugin_state_paths(local_appdata)
    if not paths["plugins_txt"]:
        issues.append("plugins.txt was not found. Launch Skyrim once, then let Vortex deploy plugins.")
    xedit_found = xedit_candidates(args)

    return {
        "platform": sys.platform,
        "steam_root": str(steam_root) if steam_root else None,
        "steam_libraries": [str(p) for p in steam_libraries(steam_root)],
        "vortex_exe": str(vortex_exe) if vortex_exe else None,
        "vortex_appdata": str(vortex_appdata) if vortex_appdata else None,
        "staging_dir": str(staging_dir) if staging_dir else None,
        "staging_candidates": [str(p) for p in staging_candidates(vortex_appdata, args.get("staging_dir"))],
        "skyrim_dir": str(skyrim_dir) if skyrim_dir else None,
        "skyrim_data": str(skyrim_dir / "Data") if skyrim_dir else None,
        "skse_loader": str(skse_loader) if skse_loader else None,
        "skse_installed": bool(path_exists(skse_loader)),
        "local_appdata": str(local_appdata) if local_appdata else None,
        "my_games_dir": str(my_games) if my_games else None,
        "plugin_state": paths,
        "nexus_api": nexus_config_status(args),
        "scan_cache": scan_cache_status(args),
        "xedit": {
            "available": bool(xedit_found),
            "exe": str(xedit_found[0]) if xedit_found else None,
            "candidateNames": list(XEDIT_EXE_NAMES),
        },
        "issues": issues,
    }


def validate_setup(args: Dict[str, Any]) -> Dict[str, Any]:
    environment = detect_environment(args)
    tool_groups = {
        "alwaysAvailable": [
            "detect_environment",
            "validate_setup",
            "workflow_guide",
            "inventory_mods",
            "analyze_conflicts",
            "redundant_mod_report",
            "plugin_report",
            "ini_report",
            "mod_knowledge_report",
            "in_game_issue_report",
            "skyrim_runtime_log_report",
            "config_file_report",
            "safe_session_report",
            "bug_report_bundle",
            "skyrim_diagnostics_report",
            "scan_cache_status",
            "xedit_diagnostics_report",
            "xedit_inspection_script",
            "xedit_inspection_result_report",
            "skyrim_issue_case_packet",
            "skyrim_issue_case_status",
            "skyrim_issue_case_note",
            "skyrim_safe_experiment_plan",
            "skyrim_case_what_now",
            "skyrim_live_bridge_status",
            "skyrim_case_evidence_import",
            "skyrim_case_bundle",
        ],
        "nexusMetadataOptional": [
            "nexus_validate_key",
            "nexus_mod_lookup",
            "nexus_mod_files",
            "nexus_file_info",
            "nexus_file_by_md5",
            "nexus_parse_nxm_link",
            "nexus_update_report",
        ],
        "collectionDiagnostics": [
            "collection_local_match_report",
        ],
        "vortexCliRequired": [
            "vortex_profile_report",
            "vortex_profile_mods",
            "vortex_compare_profiles",
            "vortex_profile_deployment_report",
            "vortex_collection_report",
            "vortex_profile_backup",
            "vortex_profile_restore_plan",
            "vortex_clone_profile",
            "vortex_set_profile_mods",
        ],
        "writeCapableDryRunFirst": [
            "apply_ini_fixes",
            "apply_config_text_patch",
            "vortex_clone_profile",
            "vortex_set_profile_mods",
            "vortex_profile_restore_plan",
        ],
    }
    blockers = []
    if environment.get("vortex_exe") is None:
        blockers.append("Vortex CLI tools need Vortex.exe. Pass vortex_exe if detection missed it.")
    if environment.get("skyrim_dir") is None:
        blockers.append("Skyrim SE path was not detected. Pass skyrim_dir for plugin/deployment checks.")
    if environment.get("staging_dir") is None or not Path(str(environment.get("staging_dir"))).exists():
        blockers.append("Vortex staging folder was not detected. Pass staging_dir for mod inventory/conflict reports.")
    if not environment.get("skse_installed"):
        blockers.append("SKSE was not detected beside SkyrimSE.exe.")
    return {
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "environment": environment,
        "ready": len(blockers) == 0,
        "blockers": blockers,
        "toolGroups": tool_groups,
        "safetyDefaults": [
            "Profile writes are dry-run unless apply=true.",
            "Profile writes refuse to run while Vortex.exe is open unless allow_running_vortex=true.",
            "vortex_set_profile_mods and vortex_clone_profile write a profile backup before apply=true by default.",
            "Use vortex_profile_restore_plan with apply=false first to preview undo/restore actions.",
        ],
    }


def workflow_catalog() -> List[Dict[str, Any]]:
    return [
        {
            "key": "first_setup",
            "title": "First Setup Check",
            "matchTerms": ["setup", "install", "detect", "doctor", "configured", "path", "skse", "xedit"],
            "userPrompt": "Use validate_setup, then detect_environment. Tell me whether Vortex, Skyrim SE, staging, plugins.txt, SKSE, and xEdit are detected. Do not apply changes.",
            "tools": ["validate_setup", "detect_environment"],
            "whatToRead": ["ready", "blockers", "environment.issues", "toolGroups"],
            "humanSteps": ["Fix setup blockers before disabling mods or changing profiles."],
            "directCli": ["py -3 .\\server.py --tool validate_setup", "py -3 .\\server.py --tool detect_environment"],
            "menuAction": "1. Validate setup",
        },
        {
            "key": "mods_not_working",
            "title": "Mods Downloaded But Not Working In Game",
            "matchTerms": ["mods not working", "not working", "downloaded", "vanilla", "deploy", "deployment", "profile", "skyrim launches", "not active", "not showing", "audio"],
            "userPrompt": "Use skyrim_diagnostics_report with performance_mode=slow_model. Check whether my selected Vortex profile is deployed into Skyrim Data and enabled in plugins.txt. Do not apply changes.",
            "tools": ["skyrim_diagnostics_report", "vortex_profile_deployment_report", "plugin_report"],
            "whatToRead": ["findings", "sections.skyrimModdedPlay", "sections.setupValidation", "sections.logStatus"],
            "humanSteps": ["Select the intended Vortex profile.", "Click Deploy Mods in Vortex.", "Confirm plugins are enabled.", "Launch through SKSE when SKSE is part of the setup."],
            "directCli": ["py -3 .\\server.py --skyrim-diagnostics --performance-mode slow_model"],
            "menuAction": "12. Skyrim diagnostics report",
        },
        {
            "key": "weird_object",
            "title": "Weird Object Or Location Problem",
            "matchTerms": ["object", "bed", "door", "tavern", "whiterun", "cell", "formid", "placed", "outside", "room"],
            "userPrompt": "Use skyrim_issue_case_packet with my description, location, object, and any FormID/base object I provide. Then use skyrim_issue_case_status after I run the generated xEdit script. Do not edit plugins.",
            "tools": ["skyrim_issue_case_packet", "skyrim_issue_case_status", "skyrim_case_evidence_import", "skyrim_case_what_now", "skyrim_safe_experiment_plan", "skyrim_issue_case_note", "in_game_issue_report", "xedit_diagnostics_report", "xedit_inspection_script", "xedit_inspection_result_report", "vortex_profile_backup"],
            "whatToRead": ["candidateCount", "candidates", "formIdHint", "diagnosticQuality", "scriptPath", "reportPath"],
            "humanSteps": ["Use the console-clicked FormID if available.", "Generate a read-only xEdit inspection script for the top candidate.", "Back up or clone the profile before testing.", "Disable one candidate in a cloned profile, deploy, and test."],
            "directCli": ["py -3 .\\server.py --tool in_game_issue_report --description \"bed outside tavern room\" --location \"Whiterun Bannered Mare\" --object \"bed\""],
            "menuAction": "10. In-game issue triage",
        },
        {
            "key": "popup",
            "title": "Annoying Popup Or Notification",
            "matchTerms": ["popup", "pop-up", "notification", "warning", "alert", "prompt", "dialog", "mcm", "message", "not configured", "configured properly"],
            "userPrompt": "Use skyrim_runtime_log_report and in_game_issue_report with my plain popup description. If a config candidate appears, validate/read it first and propose apply_config_text_patch as a dry run.",
            "tools": ["skyrim_runtime_log_report", "in_game_issue_report", "config_file_report", "read_text_file", "apply_config_text_patch"],
            "whatToRead": ["skyrim_runtime_log_report.issueGroups", "skyrim_runtime_log_report.configCandidates", "in_game_issue_report.candidates", "nextBestInputs"],
            "humanSteps": ["Reproduce the popup once, then run the runtime log report.", "If a config file is identified, patch exact text only with backup.", "Test candidate disables in a cloned profile if no config fix is obvious."],
            "directCli": ["py -3 .\\server.py --runtime-logs --description \"annoying popup says file was not configured properly\"", "py -3 .\\server.py --tool in_game_issue_report --description \"annoying popup after loading a save\""],
            "menuAction": "10. In-game issue triage",
        },
        {
            "key": "runtime_logs",
            "title": "Skyrim Runtime Logs And Popups",
            "matchTerms": ["runtime log", "papyrus", "skse log", "crash log", "trainwreck", "crashlogger", "configured properly", "file was not configured", "log says"],
            "userPrompt": "Use skyrim_runtime_log_report with my description. Summarize critical/high/config findings, then use read_text_file on any configCandidates. Only propose apply_config_text_patch as dry_run=true unless I approve.",
            "tools": ["skyrim_runtime_log_report", "config_file_report", "read_text_file", "apply_config_text_patch", "safe_session_report"],
            "whatToRead": ["findingCount", "severityCounts", "issueGroups", "configCandidates", "freshLogStatus", "recommendedActions"],
            "humanSteps": ["Launch Skyrim once and reproduce the problem.", "Keep the generated backup if any config patch is applied.", "Deploy/test after changing a staged mod config."],
            "directCli": ["py -3 .\\server.py --runtime-logs --description \"popup says file was not configured properly\""],
            "menuAction": "18. Skyrim runtime logs",
        },
        {
            "key": "large_collection_review",
            "title": "Large Collection Review Or Removal Candidates",
            "matchTerms": ["collection", "remove", "redundant", "cleanup", "what can i remove", "mod list", "huge", "knowledge"],
            "userPrompt": "Use mod_knowledge_report to write a Markdown report explaining what each mod appears to do, how it fits into the collection, and which mods are safe candidates to review for disabling. Do not apply changes.",
            "tools": ["mod_knowledge_report", "scan_cache_status"],
            "whatToRead": ["Removal Review Shortlist", "Sensitive Conflict Examples", "Plugin Master Problems", "Mod Index"],
            "humanSteps": ["Review candidates in a cloned profile.", "Disable, deploy, test, then decide whether to uninstall later."],
            "directCli": ["py -3 .\\server.py --mod-knowledge"],
            "menuAction": "5. Mod knowledge Markdown report",
        },
        {
            "key": "collection_drift",
            "title": "Collection Drift Or Missing Collection Mods",
            "matchTerms": ["collection drift", "manifest", "missing collection", "nexus collection", "collection downloaded", "pinned", "file id"],
            "userPrompt": "Use vortex_collection_report and nexus_update_report to inspect collection-like state and local Nexus metadata. Do not install, update, or remove mods.",
            "tools": ["vortex_collection_report", "collection_local_match_report", "nexus_update_report"],
            "whatToRead": ["collectionStates", "missingModIds", "filePairMismatches", "staleMods"],
            "humanSteps": ["Use Vortex's collection UI for installs or updates.", "Do not auto-update pinned collection mods from metadata alone."],
            "directCli": ["py -3 .\\server.py --tool vortex_collection_report", "py -3 .\\server.py --tool collection_local_match_report --collection-manifest-path \"C:\\path\\collection.json\""],
            "menuAction": "15. Vortex collection state",
        },
        {
            "key": "safe_profile_undo",
            "title": "Safe Profile Experiment And Undo",
            "matchTerms": ["profile", "clone", "backup", "undo", "restore", "disable", "test profile", "safe test"],
            "userPrompt": "Use vortex_profile_backup with include_all_profiles=true. Then create a dry-run plan to clone my active profile as \"OpenClaw Safe Test\". Do not apply until I approve.",
            "tools": ["vortex_profile_backup", "vortex_clone_profile", "vortex_profile_restore_plan"],
            "whatToRead": ["backupPath", "plannedChangeCount", "plannedChanges"],
            "humanSteps": ["Close Vortex before profile writes.", "Reopen Vortex, pick the intended profile, deploy, and test.", "Keep the backup path."],
            "directCli": ["py -3 .\\server.py --tool vortex_profile_backup --include-all-profiles", "py -3 .\\server.py --tool vortex_clone_profile --args-json \"{\\\"new_name\\\":\\\"OpenClaw Safe Test\\\"}\""],
            "menuAction": "2. Create Vortex profile backup",
        },
        {
            "key": "bug_report",
            "title": "Bug Report Or Confusing Tool Failure",
            "matchTerms": ["bug", "error", "failed", "confused", "logs", "support", "bundle", "not working"],
            "userPrompt": "Use log_status and bug_report_bundle with zip_output=true and redact_user_paths=true. Summarize the highest-risk findings and tell me where the zip was written. Do not apply changes.",
            "tools": ["log_status", "bug_report_bundle"],
            "whatToRead": ["setupValidation", "recent tool_error or exception logs", "vortex-cli errors", "skyrimModdedPlay.findings"],
            "humanSteps": ["Review the zip before posting publicly.", "Include the exact OpenClaw prompt and whether Vortex was open."],
            "directCli": ["py -3 .\\server.py --tool bug_report_bundle --args-json \"{\\\"zip_output\\\":true,\\\"redact_user_paths\\\":true}\""],
            "menuAction": "7. Bug report zip",
        },
    ]


def workflow_score(workflow: Dict[str, Any], text: str) -> int:
    lowered = text.lower()
    score = 0
    for term in workflow.get("matchTerms", []):
        term_text = str(term).lower()
        if term_text and term_text in lowered:
            score += 3 if " " in term_text else 1
    return score


def workflow_guide(args: Dict[str, Any]) -> Dict[str, Any]:
    key = str(args.get("workflow_key") or "").strip().lower().replace("-", "_")
    problem = str(args.get("problem") or args.get("description") or "").strip()
    include_all = bool(args.get("include_all", False)) or key == "all"
    include_direct_cli = bool(args.get("include_direct_cli", True))
    max_workflows = max(1, min(20, int(args.get("max_workflows", 3))))
    catalog = workflow_catalog()

    if include_all:
        selected = catalog
        mode = "all"
    elif key and key != "auto":
        selected = [item for item in catalog if item["key"] == key]
        mode = "key"
        if not selected:
            raise ToolError(f"Unknown workflow_key: {key}. Use workflow_guide with workflow_key=all to list valid keys.")
    else:
        scored = [(workflow_score(item, problem), item) for item in catalog]
        scored.sort(key=lambda item: (-item[0], item[1]["key"]))
        selected = [item for score, item in scored if score > 0][:max_workflows]
        if not selected:
            selected = [item for item in catalog if item["key"] in {"mods_not_working", "first_setup", "bug_report"}][:max_workflows]
        mode = "inferred"

    workflows = []
    for item in selected[: max_workflows if not include_all else len(selected)]:
        cleaned = {k: v for k, v in item.items() if k != "matchTerms"}
        if not include_direct_cli:
            cleaned.pop("directCli", None)
        workflows.append(cleaned)

    return {
        "mode": mode,
        "problem": problem or None,
        "workflowCount": len(workflows),
        "validWorkflowKeys": [item["key"] for item in catalog],
        "workflows": workflows,
        "safetyRules": [
            "Reports first, backups second, cloned-profile tests third, real changes last.",
            "Do not deploy, install, update, disable, delete, sort, or edit plugins from a workflow guide alone.",
            "Use Vortex for final deployment/install/update decisions.",
        ],
        "notes": [
            "This is a routing helper for OpenClaw and humans. It does not inspect the local setup by itself.",
            "After choosing a workflow, run the listed tools and read the named fields before taking action.",
        ],
    }


def safe_walk(root: Path, max_files: int = MAX_DEFAULT_FILES) -> Iterable[Path]:
    count = 0
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__"}]
        for file_name in files:
            count += 1
            if count > max_files:
                return
            yield Path(base) / file_name


def parse_metadata_file(path: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    try:
        if path.suffix.lower() == ".json":
            data = json.loads(read_text(path))
            if isinstance(data, dict):
                for key in ("name", "modName", "modId", "fileId", "version", "author", "category"):
                    if key in data:
                        result[key] = data[key]
        elif path.suffix.lower() in {".ini", ".txt"}:
            for line in read_text(path, 80_000).splitlines():
                if "=" not in line or line.strip().startswith(("#", ";")):
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if key.lower() in {
                    "name",
                    "modname",
                    "modid",
                    "fileid",
                    "version",
                    "author",
                    "category",
                    "nexusmodid",
                    "nexusfileid",
                }:
                    result[key] = value
    except Exception as exc:
        result["_metadata_error"] = str(exc)
    return result


def find_readmes(mod_dir: Path, max_count: int = 8) -> List[str]:
    names = []
    patterns = ("readme", "description", "changelog", "manual", "instructions", "install")
    for file_path in safe_walk(mod_dir, 4000):
        name = file_path.name.lower()
        if file_path.suffix.lower() in {".txt", ".md", ".rtf"} and any(p in name for p in patterns):
            names.append(rel_to(file_path, mod_dir))
            if len(names) >= max_count:
                break
    return names


def classify_file(rel: str) -> str:
    lower = rel.lower().replace("\\", "/")
    suffix = Path(lower).suffix
    if suffix in {".esp", ".esm", ".esl"}:
        return "plugin"
    if suffix == ".bsa":
        return "archive"
    if lower.startswith("skse/plugins/") and suffix == ".dll":
        return "skse_plugin"
    if lower.startswith("scripts/") and suffix in {".pex", ".psc"}:
        return "script"
    if lower.startswith("meshes/") or suffix == ".nif":
        return "mesh"
    if lower.startswith("textures/") or suffix in {".dds", ".tga", ".png"}:
        return "texture"
    if lower.startswith("interface/") or suffix in {".swf", ".gfx"}:
        return "interface"
    if lower.startswith("fomod/"):
        return "fomod"
    if lower.startswith("nemesis") or "generatefnis" in lower or lower.startswith("tools/generatefnis"):
        return "animation_tool"
    if suffix in {".ini", ".toml", ".json", ".xml"}:
        return "config"
    return "other"


def parse_fomod(mod_dir: Path) -> Dict[str, Any]:
    import xml.etree.ElementTree as ET

    result: Dict[str, Any] = {}
    module_config = mod_dir / "fomod" / "ModuleConfig.xml"
    info_xml = mod_dir / "fomod" / "Info.xml"
    for xml_path in [module_config, info_xml]:
        if not xml_path.exists():
            continue
        try:
            root = ET.fromstring(read_text(xml_path, 300_000))
            if xml_path.name.lower() == "info.xml":
                for child in root:
                    tag = child.tag.split("}")[-1]
                    if child.text and tag.lower() in {"name", "author", "version", "website", "description"}:
                        result[tag.lower()] = child.text.strip()
            else:
                result["moduleName"] = root.attrib.get("moduleName") or root.findtext(".//moduleName")
                install_steps = root.findall(".//installStep")
                result["installStepCount"] = len(install_steps)
                result["hasConditionalInstall"] = root.find(".//conditionalFileInstalls") is not None
        except Exception as exc:
            result.setdefault("errors", []).append(f"{xml_path}: {exc}")
    return result


def plugin_masters(path: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {"path": str(path), "masters": [], "description": None, "author": None}
    try:
        data = path.read_bytes()
        if len(data) < 24 or data[:4] != b"TES4":
            result["error"] = "Not a TES4 plugin header."
            return result
        size = struct.unpack_from("<I", data, 4)[0]
        payload = data[24 : 24 + size]
        pos = 0
        extended_size: Optional[int] = None
        while pos + 6 <= len(payload):
            stype = payload[pos : pos + 4].decode("ascii", errors="replace")
            ssize = struct.unpack_from("<H", payload, pos + 4)[0]
            pos += 6
            if stype == "XXXX" and pos + ssize <= len(payload):
                if ssize >= 4:
                    extended_size = struct.unpack_from("<I", payload, pos)[0]
                pos += ssize
                continue
            if extended_size is not None:
                ssize = extended_size
                extended_size = None
            body = payload[pos : pos + ssize]
            pos += ssize
            text = body.split(b"\0", 1)[0].decode("utf-8", errors="replace").strip()
            if stype == "MAST" and text:
                result["masters"].append(text)
            elif stype == "CNAM" and text:
                result["author"] = text
            elif stype == "SNAM" and text:
                result["description"] = text
    except Exception as exc:
        result["error"] = str(exc)
    return result


def mod_summary(mod_dir: Path, include_files: bool = False, max_files: int = 5000) -> Dict[str, Any]:
    counters: Dict[str, int] = {}
    plugin_files: List[str] = []
    archives: List[str] = []
    skse_plugins: List[str] = []
    files: List[str] = []
    total_size = 0

    for file_path in safe_walk(mod_dir, max_files):
        rel = rel_to(file_path, mod_dir)
        kind = classify_file(rel)
        counters[kind] = counters.get(kind, 0) + 1
        try:
            total_size += file_path.stat().st_size
        except OSError:
            pass
        if kind == "plugin":
            plugin_files.append(rel)
        elif kind == "archive":
            archives.append(rel)
        elif kind == "skse_plugin":
            skse_plugins.append(rel)
        if include_files:
            files.append(rel)

    metadata: Dict[str, Any] = {}
    for meta_name in ("meta.ini", "info.json", "mod.json"):
        meta_path = mod_dir / meta_name
        if meta_path.exists():
            metadata.update(parse_metadata_file(meta_path))

    fomod = parse_fomod(mod_dir)
    if fomod:
        metadata["fomod"] = fomod

    return {
        "name": mod_dir.name,
        "path": str(mod_dir),
        "metadata": metadata,
        "fileCount": sum(counters.values()),
        "totalBytes": total_size,
        "kinds": counters,
        "plugins": plugin_files,
        "archives": archives,
        "sksePlugins": skse_plugins,
        "readmes": find_readmes(mod_dir),
        **({"files": files} if include_files else {}),
    }


def get_context_paths(args: Dict[str, Any]) -> Tuple[Optional[Path], Optional[Path], Optional[Path], Optional[Path]]:
    vortex_appdata = default_vortex_appdata(args.get("vortex_appdata"))
    skyrim_dir = find_skyrim_dir(args.get("skyrim_dir"))
    staging_dir = choose_staging_dir(vortex_appdata, args.get("staging_dir"))
    my_games = default_my_games_dir(args.get("my_games_dir"))
    return vortex_appdata, skyrim_dir, staging_dir, my_games


def inventory_mods(args: Dict[str, Any]) -> Dict[str, Any]:
    vortex_appdata, _skyrim_dir, staging_dir, _my_games = get_context_paths(args)
    if not staging_dir or not staging_dir.exists():
        raise ToolError("Vortex staging folder was not found. Pass staging_dir explicitly.")
    include_files = bool(args.get("include_files", False))
    max_mods = int(args.get("max_mods", 300))
    max_files_per_mod = int(args.get("max_files_per_mod", 5000))
    mods = []
    scan_cache = load_scan_cache(args) if scan_cache_enabled(args) else {}
    for mod_dir in sorted([p for p in staging_dir.iterdir() if p.is_dir()], key=lambda p: p.name.lower())[:max_mods]:
        mods.append(mod_summary_cached(mod_dir, include_files=include_files, max_files=max_files_per_mod, args=args, cache=scan_cache))
    if scan_cache_enabled(args):
        write_scan_cache(args, scan_cache)
    return {
        "vortex_appdata": str(vortex_appdata) if vortex_appdata else None,
        "staging_dir": str(staging_dir),
        "modCount": len(mods),
        "mods": mods,
        "scanCache": scan_cache_status(args) if bool(args.get("include_scan_cache_status", False)) else None,
    }


def sha256_file(path: Path, max_mb: int = 256) -> Optional[str]:
    try:
        if path.stat().st_size > max_mb * 1024 * 1024:
            return None
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def conflict_risk(kind: str, same_hash: Optional[bool]) -> Dict[str, str]:
    if same_hash is True:
        return {
            "severity": "low",
            "impact": "The files appear identical, so the conflict is usually harmless duplication.",
            "safeAction": "Leave it alone unless you are cleaning redundant mods in a cloned profile.",
        }
    if kind in {"skse_plugin", "script"}:
        return {
            "severity": "high",
            "impact": "Runtime code conflicts can change quests, gameplay, plugins, or SKSE behavior.",
            "safeAction": "Use Vortex's Conflicts view to confirm the intended winner; test in a cloned profile before changing rules.",
        }
    if kind in {"plugin", "archive"}:
        return {
            "severity": "high",
            "impact": "Plugin/archive conflicts can change records, assets, and load-order behavior.",
            "safeAction": "Inspect the related plugins and collection notes before changing load order or rules.",
        }
    if kind in {"interface", "config", "animation_tool"}:
        return {
            "severity": "medium",
            "impact": "UI, config, and generated-tool conflicts can break menus, MCM behavior, or generated outputs.",
            "safeAction": "Prefer the mod author's compatibility instructions and regenerate external outputs if required.",
        }
    if kind in {"mesh", "texture"}:
        return {
            "severity": "low-medium",
            "impact": "Visual conflicts usually change appearance, but skeleton/body/physics assets can affect gameplay stability.",
            "safeAction": "Pick the visual winner intentionally in Vortex; avoid changing body/skeleton/physics winners casually.",
        }
    return {
        "severity": "low",
        "impact": "The conflict is in a less-classified file type.",
        "safeAction": "Review only if the file path matches the problem you are diagnosing.",
    }


def explain_conflict_item(item: Dict[str, Any]) -> Dict[str, Any]:
    kind = str(item.get("kind") or "other")
    risk = conflict_risk(kind, item.get("sameHash"))
    providers = [str(provider.get("mod")) for provider in item.get("providers", []) if isinstance(provider, dict)]
    same_size = item.get("sameSize")
    same_hash = item.get("sameHash")
    if same_hash is True:
        difference = "same hash"
    elif same_hash is False:
        difference = "different hash"
    elif same_size is True:
        difference = "same size, content not hashed"
    else:
        difference = "different size or unknown size"
    return {
        "risk": risk["severity"],
        "difference": difference,
        "impact": risk["impact"],
        "safeAction": risk["safeAction"],
        "winnerKnown": False,
        "winnerNote": "This outside-Vortex report can see providers, but not Vortex's final rule winner. Check Vortex's Conflicts view for the actual winner.",
        "providerMods": providers,
    }


def analyze_conflicts(args: Dict[str, Any]) -> Dict[str, Any]:
    _vortex_appdata, skyrim_dir, staging_dir, _my_games = get_context_paths(args)
    if not staging_dir or not staging_dir.exists():
        raise ToolError("Vortex staging folder was not found. Pass staging_dir explicitly.")
    game_data = (skyrim_dir / "Data") if skyrim_dir else None
    hash_files = bool(args.get("hash_files", False))
    max_files = int(args.get("max_files", MAX_DEFAULT_FILES))
    max_conflicts = int(args.get("max_conflicts", 300))
    providers: Dict[str, List[Dict[str, Any]]] = {}

    mod_dirs = [p for p in staging_dir.iterdir() if p.is_dir()]
    scanned_files = 0
    for mod_dir in mod_dirs:
        for file_path in safe_walk(mod_dir, max_files):
            scanned_files += 1
            rel = rel_to(file_path, mod_dir).lower()
            try:
                size = file_path.stat().st_size
            except OSError:
                size = None
            providers.setdefault(rel, []).append(
                {"mod": mod_dir.name, "path": str(file_path), "size": size}
            )

    conflicts = []
    for rel, entries in providers.items():
        if len(entries) <= 1:
            continue
        sizes = sorted(set(e["size"] for e in entries))
        hashes = None
        if hash_files:
            hashes = sorted(set(sha256_file(Path(e["path"])) for e in entries))
        item = {
            "relativePath": rel,
            "kind": classify_file(rel),
            "providerCount": len(entries),
            "sameSize": len(sizes) == 1,
            "sameHash": (len([h for h in hashes or [] if h]) == 1) if hash_files else None,
            "providers": entries,
        }
        item["explanation"] = explain_conflict_item(item)
        conflicts.append(item)
    severity_order = {"high": 0, "medium": 1, "low-medium": 2, "low": 3}
    conflicts.sort(
        key=lambda c: (
            severity_order.get(str(c.get("explanation", {}).get("risk")), 9),
            c["kind"],
            -c["providerCount"],
            c["relativePath"],
        )
    )

    unmanaged_conflicts = []
    if game_data and game_data.exists():
        for rel, entries in list(providers.items())[:max_files]:
            data_file = game_data / rel
            if data_file.exists():
                unmanaged_conflicts.append(
                    {
                        "relativePath": rel,
                        "dataPath": str(data_file),
                        "modProviders": [e["mod"] for e in entries],
                    }
                )
                if len(unmanaged_conflicts) >= max_conflicts:
                    break

    return {
        "staging_dir": str(staging_dir),
        "skyrim_data": str(game_data) if game_data else None,
        "scannedModDirs": len(mod_dirs),
        "scannedFilesApprox": scanned_files,
        "conflictCount": len(conflicts),
        "conflicts": conflicts[:max_conflicts],
        "riskSummary": {
            risk: sum(1 for item in conflicts if item.get("explanation", {}).get("risk") == risk)
            for risk in ("high", "medium", "low-medium", "low")
        },
        "unmanagedDataOverlapCount": len(unmanaged_conflicts),
        "unmanagedDataOverlaps": unmanaged_conflicts,
        "notes": [
            "This reports file-level overlaps. Vortex conflict rules decide the actual winner.",
            "Same-hash conflicts are usually harmless duplication; different-hash conflicts need an intentional winner.",
        ],
    }


def redundant_mod_report(args: Dict[str, Any]) -> Dict[str, Any]:
    _vortex_appdata, _skyrim_dir, staging_dir, _my_games = get_context_paths(args)
    if not staging_dir or not staging_dir.exists():
        raise ToolError("Vortex staging folder was not found. Pass staging_dir explicitly.")
    hash_files = bool(args.get("hash_files", False))
    max_mods = int(args.get("max_mods", 200))
    mods = [p for p in sorted(staging_dir.iterdir(), key=lambda p: p.name.lower()) if p.is_dir()][:max_mods]
    scan_cache = load_scan_cache(args) if scan_cache_enabled(args) else {}
    summaries = [mod_summary_cached(p, include_files=False, max_files=8000, args=args, cache=scan_cache) for p in mods]
    if scan_cache_enabled(args):
        write_scan_cache(args, scan_cache)

    duplicate_plugins: Dict[str, List[str]] = {}
    duplicate_nexus: Dict[str, List[str]] = {}
    for summary in summaries:
        for plugin in summary["plugins"]:
            duplicate_plugins.setdefault(Path(plugin).name.lower(), []).append(summary["name"])
        meta = summary.get("metadata") or {}
        mod_id = str(meta.get("modId") or meta.get("nexusModId") or "").strip()
        if mod_id:
            duplicate_nexus.setdefault(mod_id, []).append(summary["name"])

    exact_or_subset: List[Dict[str, Any]] = []
    fingerprints: Dict[str, Dict[str, Any]] = {}
    for mod_dir in mods:
        fp: Dict[str, Any] = {}
        for file_path in safe_walk(mod_dir, 8000):
            rel = rel_to(file_path, mod_dir).lower()
            try:
                stat = file_path.stat()
            except OSError:
                continue
            fp[rel] = sha256_file(file_path) if hash_files else stat.st_size
        fingerprints[mod_dir.name] = fp

    names = list(fingerprints)
    for left_name in names:
        left = fingerprints[left_name]
        if not left:
            continue
        for right_name in names:
            if left_name == right_name:
                continue
            right = fingerprints[right_name]
            if len(left) > len(right):
                continue
            if all(k in right and right[k] == v for k, v in left.items()):
                exact_or_subset.append(
                    {
                        "possiblyRedundant": left_name,
                        "coveredBy": right_name,
                        "fileCount": len(left),
                        "basis": "hash subset" if hash_files else "same-size path subset",
                    }
                )
                break

    return {
        "staging_dir": str(staging_dir),
        "duplicatePlugins": {k: v for k, v in duplicate_plugins.items() if len(v) > 1},
        "duplicateNexusIds": {k: v for k, v in duplicate_nexus.items() if len(v) > 1},
        "coveredMods": exact_or_subset,
        "notes": [
            "Covered mods are candidates, not automatic delete decisions.",
            "Use hash_files=true for stronger evidence; it can be slower.",
        ],
    }


def parse_plugin_list(path: Optional[Path]) -> Dict[str, Any]:
    if not path or not path.exists():
        return {"path": str(path) if path else None, "exists": False, "entries": []}
    entries = []
    for raw in read_text(path, 1_000_000).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        enabled = line.startswith("*")
        name = line[1:] if enabled else line
        entries.append({"name": name, "enabled": enabled})
    return {"path": str(path), "exists": True, "entries": entries}


def plugin_report(args: Dict[str, Any]) -> Dict[str, Any]:
    _vortex_appdata, skyrim_dir, staging_dir, _my_games = get_context_paths(args)
    if not skyrim_dir or not skyrim_dir.exists():
        raise ToolError("Skyrim folder was not found. Pass skyrim_dir explicitly.")
    data_dir = skyrim_dir / "Data"
    local = expand_path(args.get("local_appdata")) or default_local_appdata()
    state = plugin_state_paths(local)
    plugins_txt = parse_plugin_list(Path(state["plugins_txt"]) if state["plugins_txt"] else None)
    loadorder_txt = parse_plugin_list(Path(state["loadorder_txt"]) if state["loadorder_txt"] else None)

    available: Dict[str, str] = {}
    plugin_details: Dict[str, Any] = {}
    for root in [data_dir, staging_dir]:
        if not root or not root.exists():
            continue
        for file_path in safe_walk(root, MAX_DEFAULT_FILES):
            if file_path.suffix.lower() in {".esp", ".esm", ".esl"}:
                available[file_path.name.lower()] = str(file_path)
                plugin_details[file_path.name] = plugin_masters(file_path)

    missing_enabled = []
    for entry in plugins_txt["entries"]:
        if entry["enabled"] and entry["name"].lower() not in available:
            missing_enabled.append(entry["name"])

    missing_masters = []
    for plugin_name, detail in plugin_details.items():
        for master in detail.get("masters", []):
            if master.lower() not in available:
                missing_masters.append({"plugin": plugin_name, "missingMaster": master})

    return {
        "skyrim_data": str(data_dir),
        "staging_dir": str(staging_dir) if staging_dir else None,
        "availablePluginCount": len(available),
        "pluginsTxt": plugins_txt,
        "loadorderTxt": loadorder_txt,
        "missingEnabledPlugins": missing_enabled,
        "missingMasters": missing_masters,
        "pluginHeaders": plugin_details,
    }


def find_on_path(names: Iterable[str]) -> List[Path]:
    result: List[Path] = []
    path_env = os.environ.get("PATH") or ""
    for folder in path_env.split(os.pathsep):
        if not folder:
            continue
        base = Path(folder)
        for name in names:
            candidate = base / name
            if candidate.exists() and candidate.is_file():
                result.append(candidate)
    return result


def xedit_candidates(args: Dict[str, Any]) -> List[Path]:
    explicit = expand_path(args.get("xedit_exe") or args.get("sseedit_exe"))
    candidates: List[Path] = [explicit] if explicit else []
    _vortex_appdata, skyrim_dir, _staging_dir, _my_games = get_context_paths(args)
    roots: List[Path] = []
    if skyrim_dir:
        roots.extend([skyrim_dir, skyrim_dir.parent, skyrim_dir.parent / "SSEEdit", skyrim_dir.parent / "xEdit"])
    docs = default_documents()
    if docs:
        roots.extend([docs / "SSEEdit", docs / "xEdit", docs / "Tools" / "SSEEdit"])
    for root in roots:
        for exe_name in XEDIT_EXE_NAMES:
            candidates.append(root / exe_name)
    candidates.extend(find_on_path(XEDIT_EXE_NAMES))

    seen: set[str] = set()
    found: List[Path] = []
    for candidate in candidates:
        if not candidate:
            continue
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if resolved.exists() and resolved.is_file():
            found.append(resolved)
    return found


def xedit_diagnostics_report(args: Dict[str, Any]) -> Dict[str, Any]:
    found = xedit_candidates(args)
    form_id = str(args.get("form_id") or "").strip()
    plugin_name = str(args.get("plugin_name") or "").strip()
    hint = form_id_load_order_hint(args, form_id)
    plugins: Dict[str, Any] = {}
    try:
        plugins = plugin_report(args)
    except Exception as exc:
        plugins = {"error": str(exc)}

    normalized_plugin = plugin_name.lower()
    if not normalized_plugin and isinstance(hint, dict) and hint.get("pluginName"):
        normalized_plugin = str(hint.get("pluginName")).lower()
    plugin_header = None
    if normalized_plugin and isinstance(plugins.get("pluginHeaders"), dict):
        for name, header in plugins["pluginHeaders"].items():
            if str(name).lower() == normalized_plugin:
                plugin_header = header
                break

    return {
        "available": bool(found),
        "xeditExe": str(found[0]) if found else None,
        "candidateExecutables": [str(path) for path in found[:10]],
        "formIdHint": hint,
        "pluginName": plugin_name or (hint.get("pluginName") if isinstance(hint, dict) else None),
        "pluginHeader": plugin_header,
        "pluginReportAvailable": "error" not in plugins,
        "pluginReportError": plugins.get("error") if isinstance(plugins, dict) else None,
        "readOnly": True,
        "suggestedWorkflow": [
            "Open xEdit/SSEEdit manually with the active Skyrim load order.",
            "If a FormID hint points to a plugin, inspect that plugin first.",
            "For stronger read-only evidence, generate xedit_inspection_script, run it in xEdit on selected candidate records/plugins, then parse the CSV with xedit_inspection_result_report.",
            "For placed objects, inspect the current cell and reference/base record before disabling mods.",
            "For popups, inspect message, quest, script, and MCM/config records related to the candidate mod.",
            "Do not clean, delete records, or save plugin changes from this diagnostic alone.",
        ],
        "nextLeapTools": ["xedit_inspection_script", "xedit_inspection_result_report"],
        "notes": [
            "This MCP does not automate xEdit writes. It only points OpenClaw at the safest read-only inspection target.",
            "ESL/light plugins and runtime-created references can make FormID prefix hints incomplete.",
        ],
    }


XEDIT_MUTATING_SCRIPT_TERMS = (
    "SetElementEditValues",
    "SetElementNativeValues",
    "SetEditValue",
    "SetNativeValue",
    "SetLoadOrderFormID",
    "SetIsESM",
    "SetIsDeleted",
    "SetIsInitiallyDisabled",
    "SetIsPersistent",
    "SetIsVisibleWhenDistant",
    "MarkModifiedRecursive",
    "Remove(",
    "ElementAssign",
    "InsertElement",
    "wbCopyElement",
    "SortMasters",
)


def pascal_string(value: Any) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def pascal_identifier(value: str, fallback: str = "OpenClawSkyrimInspector") -> str:
    raw = re.sub(r"[^A-Za-z0-9_]", "_", value or "")
    raw = re.sub(r"_+", "_", raw).strip("_")
    if not raw:
        raw = fallback
    if raw[0].isdigit():
        raw = "_" + raw
    return raw[:80]


def xedit_default_script_path(args: Dict[str, Any]) -> Path:
    output_path = expand_path(args.get("output_path"))
    if output_path:
        return output_path
    docs = default_documents() or Path.cwd()
    return docs / "vortex-skyrimse-mcp-reports" / "xedit-scripts" / f"OpenClawSkyrimInspector-{now_stamp()}.pas"


def xedit_terms(args: Dict[str, Any]) -> List[str]:
    raw_terms = tokenize_issue_terms(
        args.get("description"),
        args.get("location"),
        args.get("object"),
        args.get("cell"),
        args.get("base_object"),
        args.get("popup_text"),
        args.get("extra_terms"),
        args.get("plugin_name"),
        args.get("form_id"),
    )
    extra = args.get("terms")
    if isinstance(extra, list):
        raw_terms.extend(str(item) for item in extra if str(item).strip())
    elif isinstance(extra, str):
        raw_terms.extend(tokenize_issue_terms(extra))
    seen: set[str] = set()
    terms: List[str] = []
    for term in raw_terms:
        cleaned = str(term).strip()
        key = cleaned.lower()
        if len(cleaned) < 2 or key in seen:
            continue
        seen.add(key)
        terms.append(cleaned)
    return terms[: int(args.get("max_terms", 40))]


def xedit_command_preview(xedit_exe: Optional[Path], script_path: Path) -> Optional[str]:
    if not xedit_exe:
        return None
    return f'"{xedit_exe}" -SSE -script:"{script_path}" -nobuildrefs'


def xedit_inspection_script_text(args: Dict[str, Any], script_path: Path, report_path: Path) -> str:
    unit_name = pascal_identifier(script_path.stem)
    terms = xedit_terms(args)
    max_records = max(1, min(50_000, int(args.get("max_records", 2000))))
    term_lines = "\n".join(f"  Terms.Add({pascal_string(term)});" for term in terms)
    if not term_lines:
        term_lines = "  // No search terms supplied; every selected main record is exported."
    return f"""unit {unit_name};

interface
implementation
uses xEditAPI, Classes, SysUtils;

var
  Report: TStringList;
  Terms: TStringList;
  RowCount: integer;
  MaxRows: integer;

function Csv(s: string): string;
begin
  Result := '"' + StringReplace(s, '"', '""', [rfReplaceAll]) + '"';
end;

function SafeSignature(e: IInterface): string;
begin
  Result := '';
  try
    Result := Signature(e);
  except
    Result := '';
  end;
end;

function SafeEditorID(e: IInterface): string;
begin
  Result := '';
  try
    Result := EditorID(e);
  except
    Result := '';
  end;
end;

function SafeValue(e: IInterface; p: string): string;
begin
  Result := '';
  try
    Result := GetElementEditValues(e, p);
  except
    Result := '';
  end;
end;

function SafeName(e: IInterface): string;
begin
  Result := '';
  try
    Result := Name(e);
  except
    Result := '';
  end;
end;

function SafeFullPath(e: IInterface): string;
begin
  Result := '';
  try
    Result := FullPath(e);
  except
    Result := '';
  end;
end;

function SafeFileName(e: IInterface): string;
begin
  Result := '';
  try
    Result := GetFileName(GetFile(e));
  except
    Result := '';
  end;
end;

function SafeFormID(e: IInterface): string;
begin
  Result := '';
  try
    Result := IntToHex(GetLoadOrderFormID(e), 8);
  except
    Result := '';
  end;
end;

function MatchedTerm(text: string): string;
var
  i: integer;
  t: string;
  lower: string;
begin
  Result := '';
  lower := LowerCase(text);
  for i := 0 to Terms.Count - 1 do begin
    t := LowerCase(Terms[i]);
    if (t <> '') and (Pos(t, lower) > 0) then begin
      Result := Terms[i];
      exit;
    end;
  end;
end;

function Initialize: integer;
begin
  Result := 0;
  Report := TStringList.Create;
  Terms := TStringList.Create;
  RowCount := 0;
  MaxRows := {max_records};
{term_lines}
  Report.Add('sourcePlugin,signature,formId,editorId,name,full,cell,base,model,script,matchedTerm,fullPath');
  AddMessage('OpenClaw Skyrim inspector is read-only. It writes a CSV report and does not modify records.');
  AddMessage('Report path: ' + {pascal_string(report_path)});
end;

function Process(e: IInterface): integer;
var
  sig, fileName, formId, edid, recName, fullValue, cellValue, baseValue, modelValue, scriptValue, fullPath, searchText, hit: string;
begin
  Result := 0;
  if RowCount >= MaxRows then exit;
  sig := SafeSignature(e);
  if sig = '' then exit;
  fileName := SafeFileName(e);
  formId := SafeFormID(e);
  edid := SafeEditorID(e);
  recName := SafeName(e);
  fullValue := SafeValue(e, 'FULL');
  cellValue := SafeValue(e, 'Cell');
  baseValue := SafeValue(e, 'NAME - Base');
  if baseValue = '' then baseValue := SafeValue(e, 'NAME');
  modelValue := SafeValue(e, 'Model\\MODL');
  scriptValue := SafeValue(e, 'VMAD');
  fullPath := SafeFullPath(e);
  searchText := sig + ' ' + fileName + ' ' + formId + ' ' + edid + ' ' + recName + ' ' + fullValue + ' ' + cellValue + ' ' + baseValue + ' ' + modelValue + ' ' + scriptValue + ' ' + fullPath;
  if Terms.Count > 0 then begin
    hit := MatchedTerm(searchText);
    if hit = '' then exit;
  end else begin
    hit := '';
  end;
  Report.Add(Csv(fileName) + ',' + Csv(sig) + ',' + Csv(formId) + ',' + Csv(edid) + ',' + Csv(recName) + ',' + Csv(fullValue) + ',' + Csv(cellValue) + ',' + Csv(baseValue) + ',' + Csv(modelValue) + ',' + Csv(scriptValue) + ',' + Csv(hit) + ',' + Csv(fullPath));
  Inc(RowCount);
end;

function Finalize: integer;
begin
  Result := 0;
  Report.SaveToFile({pascal_string(report_path)});
  AddMessage('OpenClaw Skyrim inspector wrote ' + IntToStr(RowCount) + ' row(s) to: ' + {pascal_string(report_path)});
  Report.Free;
  Terms.Free;
end;

end.
"""


def xedit_script_safety_report(script_text: str) -> Dict[str, Any]:
    found = [term for term in XEDIT_MUTATING_SCRIPT_TERMS if term.lower() in script_text.lower()]
    return {
        "readOnlyIntended": not found,
        "mutatingTermsFound": found,
        "notes": [
            "This is a static string check. It does not prove the xEdit script is safe, but it catches obvious write/edit calls.",
            "Generated scripts should inspect selected records and write CSV output only.",
        ],
    }


def xedit_inspection_script(args: Dict[str, Any]) -> Dict[str, Any]:
    script_path = xedit_default_script_path(args)
    if script_path.suffix.lower() != ".pas":
        script_path = script_path.with_suffix(".pas")
    report_path = expand_path(args.get("report_path")) or script_path.with_suffix(".csv")
    if not report_path:
        raise ToolError("report_path resolved to an empty path.")
    include_script_text = bool(args.get("include_script_text", False))
    script_text = xedit_inspection_script_text(args, script_path, report_path)
    safety = xedit_script_safety_report(script_text)
    if safety["mutatingTermsFound"]:
        raise ToolError(f"Generated xEdit script failed static safety check: {safety['mutatingTermsFound']}")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    write_text(script_path, script_text)
    found = xedit_candidates(args)
    command = xedit_command_preview(found[0] if found else None, script_path)
    result = {
        "scriptPath": str(script_path),
        "reportPath": str(report_path),
        "xeditExe": str(found[0]) if found else None,
        "xeditCommandPreview": command,
        "terms": xedit_terms(args),
        "maxRecords": max(1, min(50_000, int(args.get("max_records", 2000)))),
        "readOnly": True,
        "safety": safety,
        "manualSteps": [
            "Open SSEEdit/xEdit with the same load order Vortex deploys.",
            "Load the candidate plugin(s), or load the full order if you are chasing overrides/conflicts.",
            "Right-click the plugin or selected records, choose Apply Script, and select the generated script.",
            "Do not save plugin changes when closing xEdit unless you intentionally made separate manual edits.",
            "Run xedit_inspection_result_report on the CSV report path after the script finishes.",
        ],
        "notes": [
            "This tool writes a read-only xEdit Pascal script. It does not launch xEdit or edit plugins.",
            "The script exports matching selected records to CSV using xEdit read APIs.",
        ],
        "sources": [
            "https://tes5edit.github.io/docs/13-Scripting-Functions.html",
            "https://github.com/TES5Edit/TES5Edit",
        ],
    }
    if include_script_text:
        result["scriptText"] = script_text
    return result


def summarize_xedit_rows(rows: List[Dict[str, str]], key: str, limit: int = 20) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "").strip() or "(blank)"
        counts[value] = counts.get(value, 0) + 1
    items = [{"value": value, "count": count} for value, count in counts.items()]
    items.sort(key=lambda item: (-int(item["count"]), str(item["value"]).lower()))
    return items[:limit]


XEDIT_SIGNATURE_GUIDANCE: Dict[str, Dict[str, Any]] = {
    "REFR": {
        "meaning": "placed reference/object",
        "issueKinds": ["placed_object"],
        "inspect": "Check which plugin wins the placed reference and whether it should exist in this cell/worldspace.",
    },
    "ACHR": {
        "meaning": "placed actor/NPC reference",
        "issueKinds": ["placed_object", "actor"],
        "inspect": "Check actor placement, packages, and overrides before disabling NPC or city overhaul mods.",
    },
    "CELL": {
        "meaning": "interior/exterior cell record",
        "issueKinds": ["placed_object", "location"],
        "inspect": "Compare cell overrides and persistent/temporary child records for misplaced objects.",
    },
    "WRLD": {
        "meaning": "worldspace record",
        "issueKinds": ["placed_object", "location"],
        "inspect": "Check worldspace/cell overrides and landscape or placed-reference children.",
    },
    "FURN": {
        "meaning": "furniture base object",
        "issueKinds": ["placed_object", "asset"],
        "inspect": "Inspect the base object if references point at a bed/chair/marker-like item.",
    },
    "STAT": {
        "meaning": "static mesh base object",
        "issueKinds": ["placed_object", "asset"],
        "inspect": "Inspect model path and references that place this static in the world.",
    },
    "MSTT": {
        "meaning": "movable static base object",
        "issueKinds": ["placed_object", "asset"],
        "inspect": "Inspect model path and placed references that instantiate it.",
    },
    "ACTI": {
        "meaning": "activator base object",
        "issueKinds": ["placed_object", "scripted_object"],
        "inspect": "Check scripts/VMAD and references; activators often create visible prompts or behavior.",
    },
    "MESG": {
        "meaning": "message/popup record",
        "issueKinds": ["popup", "ui_message"],
        "inspect": "Inspect message text and scripts/quests that show it.",
    },
    "QUST": {
        "meaning": "quest/script driver",
        "issueKinds": ["popup", "scripted_behavior"],
        "inspect": "Inspect quest stages, aliases, VMAD scripts, and startup conditions.",
    },
    "DIAL": {
        "meaning": "dialog topic",
        "issueKinds": ["dialog", "popup"],
        "inspect": "Inspect linked INFO records and conditions.",
    },
    "INFO": {
        "meaning": "dialog response/info",
        "issueKinds": ["dialog", "popup"],
        "inspect": "Inspect response text, conditions, and owning quest.",
    },
    "MGEF": {
        "meaning": "magic effect/script source",
        "issueKinds": ["popup", "scripted_behavior"],
        "inspect": "Inspect effect VMAD scripts and spell/enchantment users.",
    },
    "SPEL": {
        "meaning": "spell record",
        "issueKinds": ["popup", "scripted_behavior"],
        "inspect": "Inspect effects and scripts that may fire messages on load/equip/combat.",
    },
}


def xedit_record_interpretation(row: Dict[str, str]) -> Dict[str, Any]:
    sig = str(row.get("signature") or "").strip().upper()
    guidance = XEDIT_SIGNATURE_GUIDANCE.get(sig, {})
    issue_kinds = list(guidance.get("issueKinds", []))
    script_text = str(row.get("script") or "").strip()
    model = str(row.get("model") or "").strip()
    if script_text and "scripted_behavior" not in issue_kinds:
        issue_kinds.append("scripted_behavior")
    if model and "asset" not in issue_kinds:
        issue_kinds.append("asset")
    if not issue_kinds:
        issue_kinds.append("record_evidence")
    why = guidance.get("inspect") or "Inspect this record in xEdit and compare overrides before changing mods."
    if script_text:
        why += " VMAD/script data is present, so script-driven behavior is possible."
    if model:
        why += " A model path is present, so asset placement or mesh replacement may matter."
    return {
        "sourcePlugin": row.get("sourcePlugin") or "",
        "signature": sig or "(blank)",
        "meaning": guidance.get("meaning") or "record",
        "likelyIssueKinds": issue_kinds,
        "matchedTerm": row.get("matchedTerm") or "",
        "inspect": why,
    }


def summarize_xedit_interpretations(interpreted: List[Dict[str, Any]]) -> Dict[str, Any]:
    issue_counts: Dict[str, int] = {}
    signature_guidance: Dict[str, Dict[str, Any]] = {}
    for item in interpreted:
        for kind in item.get("likelyIssueKinds", []):
            issue_counts[str(kind)] = issue_counts.get(str(kind), 0) + 1
        sig = str(item.get("signature") or "(blank)")
        if sig not in signature_guidance:
            signature_guidance[sig] = {
                "signature": sig,
                "meaning": item.get("meaning"),
                "inspect": item.get("inspect"),
            }
    top_issue_kinds = [{"value": key, "count": value} for key, value in issue_counts.items()]
    top_issue_kinds.sort(key=lambda item: (-int(item["count"]), str(item["value"])))
    return {
        "topIssueKinds": top_issue_kinds,
        "recordTypeGuidance": list(signature_guidance.values())[:20],
    }


def xedit_inspection_result_report(args: Dict[str, Any]) -> Dict[str, Any]:
    path = expand_path(args.get("report_path") or args.get("path"))
    if not path or not path.exists() or not path.is_file():
        raise ToolError("report_path/path must point to an existing xEdit inspection CSV file.")
    path_allowed_for_text_tool(path, args, "read xEdit inspection reports")
    max_rows = max(1, min(50_000, int(args.get("max_rows", 2000))))
    rows: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append({str(key): str(value or "") for key, value in row.items() if key is not None})
            if len(rows) >= max_rows:
                break
    top_plugins = summarize_xedit_rows(rows, "sourcePlugin")
    top_signatures = summarize_xedit_rows(rows, "signature")
    top_terms = summarize_xedit_rows(rows, "matchedTerm")
    candidate_plugins = [item["value"] for item in top_plugins if item["value"] != "(blank)"][:10]
    interpreted_rows = [xedit_record_interpretation(row) for row in rows]
    interpretation_summary = summarize_xedit_interpretations(interpreted_rows)
    preview_limit = int(args.get("max_preview_rows", 50))
    preview_rows: List[Dict[str, Any]] = []
    for row, interpretation in zip(rows[:preview_limit], interpreted_rows[:preview_limit]):
        preview_rows.append({**row, "interpretation": interpretation})
    return {
        "path": str(path),
        "rowCount": len(rows),
        "truncated": len(rows) >= max_rows,
        "topPlugins": top_plugins,
        "topSignatures": top_signatures,
        "topMatchedTerms": top_terms,
        "topIssueKinds": interpretation_summary["topIssueKinds"],
        "recordTypeGuidance": interpretation_summary["recordTypeGuidance"],
        "candidatePlugins": candidate_plugins,
        "rows": preview_rows,
        "readOnly": True,
        "recommendedActions": [
            "Start with plugins/signatures that repeat most often in the report.",
            "Use recordTypeGuidance to decide whether evidence points at placed objects, popups/messages, scripts, or assets.",
            "For placed-object issues, inspect REFR/CELL/WRLD records and compare overrides before disabling mods.",
            "For popup/message issues, inspect MESG/QUST/MGEF/VMAD/script-related rows and mod config evidence.",
            "Do not save xEdit plugin edits from this report alone. Test changes in a cloned Vortex profile first.",
        ],
    }


def issue_case_default_dir(args: Dict[str, Any]) -> Path:
    explicit = expand_path(args.get("case_dir"))
    if explicit:
        return explicit
    output_path = expand_path(args.get("output_path"))
    if output_path:
        if output_path.suffix:
            return output_path.parent
        return output_path
    docs = default_documents() or Path.cwd()
    return docs / "vortex-skyrimse-mcp-reports" / "issue-cases" / f"issue-case-{now_stamp()}"


def issue_case_markdown(case: Dict[str, Any]) -> str:
    issue = case.get("issueInput", {}) if isinstance(case.get("issueInput"), dict) else {}
    in_game = case.get("inGameIssue", {}) if isinstance(case.get("inGameIssue"), dict) else {}
    xedit_diag = case.get("xeditDiagnostics", {}) if isinstance(case.get("xeditDiagnostics"), dict) else {}
    xedit_script = case.get("xeditScript", {}) if isinstance(case.get("xeditScript"), dict) else {}
    runtime = case.get("runtimeLogs", {}) if isinstance(case.get("runtimeLogs"), dict) else {}
    lines = [
        "# Skyrim Issue Case Packet",
        "",
        f"- Server: {SERVER_NAME} {SERVER_VERSION}",
        f"- Created: {case.get('createdAt')}",
        f"- Case folder: `{case.get('caseDir')}`",
        f"- Dry run only: `{str(case.get('dryRunOnly')).lower()}`",
        "",
        "## Issue",
        "",
        f"- Description: {issue.get('description') or '(blank)'}",
        f"- Location: {issue.get('location') or '(blank)'}",
        f"- Object/symptom: {issue.get('object') or '(blank)'}",
        f"- FormID: {issue.get('formId') or '(blank)'}",
        f"- Cell: {issue.get('cell') or '(blank)'}",
        f"- Base object: {issue.get('baseObject') or '(blank)'}",
        f"- Popup text: {'provided' if issue.get('popupTextProvided') else '(not provided)'}",
        "",
        "## Top Evidence",
        "",
    ]
    if in_game.get("candidates"):
        for index, candidate in enumerate(in_game.get("candidates", [])[:5], start=1):
            lines.append(
                f"{index}. `{candidate.get('mod')}` - {candidate.get('confidence')} confidence, score {candidate.get('score')}: {candidate.get('likelyReason')}"
            )
    elif case.get("inGameIssueError"):
        lines.append(f"- In-game issue scan error: {case.get('inGameIssueError')}")
    else:
        lines.append("- No in-game issue candidates were available in this packet.")
    if xedit_diag:
        lines.extend(
            [
                "",
                "## xEdit/SSEEdit",
                "",
                f"- Available: `{str(xedit_diag.get('available')).lower()}`",
                f"- Candidate executable: `{xedit_diag.get('exe') or '(not found)'}`",
                f"- Plugin hint: `{xedit_diag.get('pluginName') or '(none)'}`",
                f"- Confidence: `{xedit_diag.get('confidence') or '(unknown)'}`",
            ]
        )
    elif case.get("xeditDiagnosticsError"):
        lines.extend(["", "## xEdit/SSEEdit", "", f"- Diagnostics error: {case.get('xeditDiagnosticsError')}"])
    if xedit_script:
        lines.extend(
            [
                "",
                "## Generated Inspection Script",
                "",
                f"- Script path: `{xedit_script.get('scriptPath')}`",
                f"- CSV report path: `{xedit_script.get('reportPath')}`",
                f"- Search terms: `{', '.join(str(term) for term in xedit_script.get('terms', []))}`",
                "",
                "Run the script in SSEEdit/xEdit with Apply Script on the candidate plugin or selected records. Then run `xedit_inspection_result_report` on the CSV path.",
            ]
        )
    elif case.get("xeditScriptError"):
        lines.extend(["", "## Generated Inspection Script", "", f"- Script error: {case.get('xeditScriptError')}"])
    if runtime:
        lines.extend(
            [
                "",
                "## Runtime Logs",
                "",
                f"- Available: `{str(runtime.get('available')).lower()}`",
                f"- Findings: `{runtime.get('findingCount', 0)}`",
                f"- Issue groups: `{runtime.get('issueGroupCount', 0)}`",
            ]
        )
    elif case.get("runtimeLogsError"):
        lines.extend(["", "## Runtime Logs", "", f"- Runtime log error: {case.get('runtimeLogsError')}"])
    lines.extend(["", "## OpenClaw Next Steps", ""])
    for step in case.get("nextSteps", []):
        lines.append(f"- {step}")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- This packet is read-only diagnosis plus generated report files.",
            "- Do not save xEdit plugin edits from this packet alone.",
            "- Back up or clone the Vortex profile before disabling or removing anything.",
        ]
    )
    return "\n".join(lines) + "\n"


def skyrim_issue_case_packet(args: Dict[str, Any]) -> Dict[str, Any]:
    case_dir = issue_case_default_dir(args)
    markdown_path = expand_path(args.get("output_path")) if args.get("output_path") else case_dir / "issue-case.md"
    if not markdown_path:
        raise ToolError("output_path resolved to an empty path.")
    if not markdown_path.suffix:
        case_dir = markdown_path
        markdown_path = case_dir / "issue-case.md"
    case_dir.mkdir(parents=True, exist_ok=True)
    script_path = case_dir / "xedit-inspection.pas"
    csv_path = case_dir / "xedit-inspection.csv"
    json_path = markdown_path.with_suffix(".json")
    if json_path == markdown_path:
        json_path = markdown_path.with_name(f"{markdown_path.name}.json")

    issue_input = {
        "description": str(args.get("description") or "").strip(),
        "location": str(args.get("location") or "").strip(),
        "object": str(args.get("object") or "").strip(),
        "formId": normalize_form_id(str(args.get("form_id") or "").strip()),
        "cell": str(args.get("cell") or "").strip(),
        "baseObject": str(args.get("base_object") or "").strip(),
        "popupTextProvided": bool(str(args.get("popup_text") or "").strip()),
        "pluginName": str(args.get("plugin_name") or "").strip(),
    }
    has_issue_clues = any(issue_input.get(key) for key in ("description", "location", "object", "formId", "cell", "baseObject", "pluginName")) or issue_input["popupTextProvided"]
    if not has_issue_clues:
        raise ToolError("Pass at least one issue clue: description, location, object, form_id, cell, base_object, popup_text, or plugin_name.")

    packet: Dict[str, Any] = {
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "createdAt": iso_now(),
        "caseDir": str(case_dir),
        "markdownPath": str(markdown_path),
        "jsonPath": str(json_path),
        "dryRunOnly": True,
        "readOnly": True,
        "issueInput": issue_input,
    }
    try:
        packet["workflow"] = workflow_guide({**args, "problem": args.get("problem") or args.get("description") or args.get("popup_text") or args.get("object")})
    except Exception as exc:
        packet["workflowError"] = str(exc)
    try:
        packet["inGameIssue"] = in_game_issue_report(args)
    except Exception as exc:
        packet["inGameIssueError"] = str(exc)
    try:
        packet["xeditDiagnostics"] = xedit_diagnostics_report(args)
    except Exception as exc:
        packet["xeditDiagnosticsError"] = str(exc)
    if bool(args.get("include_xedit_script", True)):
        try:
            packet["xeditScript"] = xedit_inspection_script(
                {
                    **args,
                    "output_path": str(script_path),
                    "report_path": str(csv_path),
                    "include_script_text": False,
                }
            )
        except Exception as exc:
            packet["xeditScriptError"] = str(exc)
    if bool(args.get("include_runtime_logs", False)):
        try:
            packet["runtimeLogs"] = skyrim_runtime_log_report(args)
        except Exception as exc:
            packet["runtimeLogsError"] = str(exc)
    packet["nextSteps"] = [
        "Read the top in-game issue candidates before changing anything.",
        "If a FormID or plugin hint exists, inspect that plugin in SSEEdit/xEdit first.",
        "Run the generated xEdit script on selected candidate records/plugins, then parse the CSV with xedit_inspection_result_report.",
        "Create a Vortex profile backup or cloned test profile before disabling candidate mods.",
        "Test one candidate at a time and keep notes in this case folder.",
    ]
    packet_to_write = redact_paths_in_value(packet) if bool(args.get("redact_user_paths", False)) else packet
    write_text(json_path, json.dumps(packet_to_write, indent=2, ensure_ascii=False, default=str))
    write_text(markdown_path, issue_case_markdown(packet_to_write))
    log_event(
        "support",
        "skyrim_issue_case_packet_written",
        {"case_dir": str(case_dir), "markdown_path": str(markdown_path), "json_path": str(json_path)},
    )
    return {
        "caseDir": str(case_dir),
        "markdownPath": str(markdown_path),
        "jsonPath": str(json_path),
        "xeditScriptPath": packet.get("xeditScript", {}).get("scriptPath") if isinstance(packet.get("xeditScript"), dict) else None,
        "xeditCsvPath": packet.get("xeditScript", {}).get("reportPath") if isinstance(packet.get("xeditScript"), dict) else None,
        "candidateCount": packet.get("inGameIssue", {}).get("candidateCount") if isinstance(packet.get("inGameIssue"), dict) else None,
        "topCandidate": packet.get("inGameIssue", {}).get("candidates", [None])[0] if isinstance(packet.get("inGameIssue"), dict) and packet.get("inGameIssue", {}).get("candidates") else None,
        "xeditPluginHint": packet.get("xeditDiagnostics", {}).get("pluginName") if isinstance(packet.get("xeditDiagnostics"), dict) else None,
        "readOnly": True,
        "dryRunOnly": True,
        "errors": {key: value for key, value in packet.items() if key.endswith("Error")},
        "nextSteps": packet["nextSteps"],
    }


def issue_case_json_path(case_dir: Path) -> Path:
    preferred = case_dir / "issue-case.json"
    if preferred.exists():
        return preferred
    candidates = sorted(
        [
            path
            for path in case_dir.glob("*.json")
            if "status" not in path.stem.lower() and "plan" not in path.stem.lower() and "what-now" not in path.stem.lower()
        ],
        key=lambda path: (path.name != "issue-case.json", path.name.lower()),
    )
    return candidates[0] if candidates else preferred


def issue_case_load(case_dir: Path) -> Dict[str, Any]:
    path = issue_case_json_path(case_dir)
    if not path.exists() or not path.is_file():
        return {}
    data = json.loads(read_text(path, 20_000_000))
    return data if isinstance(data, dict) else {}


def issue_case_status_json_path(case_dir: Path) -> Path:
    preferred = case_dir / "issue-case-status.json"
    if preferred.exists():
        return preferred
    candidates = sorted(case_dir.glob("*status*.json"), key=lambda path: path.name.lower())
    return candidates[0] if candidates else preferred


def issue_case_load_status(case_dir: Path) -> Dict[str, Any]:
    path = issue_case_status_json_path(case_dir)
    if not path.exists() or not path.is_file():
        return {}
    data = json.loads(read_text(path, 20_000_000))
    return data if isinstance(data, dict) else {}


def issue_case_expected_csv(case_dir: Path, packet: Dict[str, Any], args: Dict[str, Any]) -> Path:
    explicit = expand_path(args.get("report_path") or args.get("path"))
    if explicit:
        return explicit
    xedit_script = packet.get("xeditScript") if isinstance(packet.get("xeditScript"), dict) else {}
    from_packet = expand_path(xedit_script.get("reportPath")) if isinstance(xedit_script, dict) else None
    return from_packet or (case_dir / "xedit-inspection.csv")


def issue_case_status_markdown(status: Dict[str, Any]) -> str:
    case_summary = status.get("caseSummary", {}) if isinstance(status.get("caseSummary"), dict) else {}
    xedit = status.get("xeditCsv", {}) if isinstance(status.get("xeditCsv"), dict) else {}
    result = status.get("xeditResult") if isinstance(status.get("xeditResult"), dict) else {}
    lines = [
        "# Skyrim Issue Case Status",
        "",
        f"- Server: {SERVER_NAME} {SERVER_VERSION}",
        f"- Updated: {status.get('updatedAt')}",
        f"- Case folder: `{status.get('caseDir')}`",
        f"- State: `{status.get('state')}`",
        f"- Read-only: `{str(status.get('readOnly')).lower()}`",
        "",
        "## Case Summary",
        "",
        f"- Description: {case_summary.get('description') or '(blank)'}",
        f"- Top triage candidate: `{case_summary.get('topCandidate') or '(none)'}`",
        f"- xEdit plugin hint: `{case_summary.get('xeditPluginHint') or '(none)'}`",
        "",
        "## xEdit CSV",
        "",
        f"- Expected CSV: `{xedit.get('path')}`",
        f"- Exists: `{str(xedit.get('exists')).lower()}`",
        f"- Parsed: `{str(xedit.get('parsed')).lower()}`",
    ]
    if xedit.get("error"):
        lines.append(f"- Error: {xedit.get('error')}")
    if result:
        lines.extend(
            [
                f"- Rows: `{result.get('rowCount', 0)}`",
                "",
                "## Top xEdit Evidence",
                "",
            ]
        )
        for item in result.get("topPlugins", [])[:8]:
            lines.append(f"- Plugin `{item.get('value')}`: {item.get('count')} row(s)")
        if result.get("topSignatures"):
            lines.append("")
            for item in result.get("topSignatures", [])[:8]:
                lines.append(f"- Signature `{item.get('value')}`: {item.get('count')} row(s)")
    lines.extend(["", "## Next Steps", ""])
    for step in status.get("nextSteps", []):
        lines.append(f"- {step}")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- This status report reads case files and xEdit CSV evidence only.",
            "- Do not save xEdit edits or remove mods from this status alone.",
            "- Use a cloned Vortex profile for any disable test.",
        ]
    )
    return "\n".join(lines) + "\n"


def skyrim_issue_case_status(args: Dict[str, Any]) -> Dict[str, Any]:
    case_dir = expand_path(args.get("case_dir") or args.get("path"))
    if not case_dir or not case_dir.exists() or not case_dir.is_dir():
        raise ToolError("case_dir/path must point to an existing issue case folder.")
    packet = issue_case_load(case_dir)
    csv_path = issue_case_expected_csv(case_dir, packet, args)
    status_path = expand_path(args.get("output_path")) if args.get("output_path") else case_dir / "issue-case-status.md"
    if not status_path:
        raise ToolError("output_path resolved to an empty path.")
    if not status_path.suffix:
        status_path = status_path / "issue-case-status.md"
    json_path = status_path.with_suffix(".json")
    if json_path == status_path:
        json_path = status_path.with_name(f"{status_path.name}.json")

    in_game = packet.get("inGameIssue") if isinstance(packet.get("inGameIssue"), dict) else {}
    candidates = in_game.get("candidates") if isinstance(in_game.get("candidates"), list) else []
    top_candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
    xedit_diag = packet.get("xeditDiagnostics") if isinstance(packet.get("xeditDiagnostics"), dict) else {}
    issue_input = packet.get("issueInput") if isinstance(packet.get("issueInput"), dict) else {}

    xedit_result: Optional[Dict[str, Any]] = None
    csv_error = None
    if csv_path.exists() and csv_path.is_file():
        try:
            csv_allowed_roots = [str(case_dir)]
            if args.get("report_path"):
                csv_allowed_roots.append(str(csv_path.parent))
            xedit_result = xedit_inspection_result_report(
                {
                    **args,
                    "report_path": str(csv_path),
                    "allowed_roots": csv_allowed_roots,
                    "allow_any_path": bool(args.get("allow_any_path", False)),
                    "max_preview_rows": int(args.get("max_preview_rows", 50)),
                    "max_rows": int(args.get("max_rows", 2000)),
                }
            )
        except Exception as exc:
            csv_error = str(exc)

    state = "needs_xedit_run"
    if not packet:
        state = "case_json_missing"
    if csv_error:
        state = "xedit_csv_error"
    elif xedit_result:
        row_count = int(xedit_result.get("rowCount", 0))
        state = "has_xedit_results" if row_count > 0 else "empty_xedit_results"

    next_steps = []
    if state == "needs_xedit_run":
        next_steps = [
            "Run the generated xEdit inspection script in SSEEdit/xEdit on the candidate plugin or selected records.",
            "Return to this case folder and run skyrim_issue_case_status again after the CSV appears.",
            "Use the top triage candidate only as a hint until xEdit or cloned-profile testing confirms it.",
        ]
    elif state == "has_xedit_results":
        next_steps = [
            "Start with the top xEdit source plugin/signature rows because they are stronger evidence than natural-language matching.",
            "Inspect REFR/CELL/WRLD rows for placed-object problems, or MESG/QUST/VMAD/script rows for popup problems.",
            "Back up or clone the Vortex profile before disabling exactly one candidate mod for a test.",
            "Do not save plugin edits from xEdit unless you intentionally created a separate patch and can undo it.",
        ]
    elif state == "empty_xedit_results":
        next_steps = [
            "The xEdit script ran but exported no rows. Apply it to a broader plugin scope or full load order, then rerun this status tool.",
            "If this is a popup, include exact popup text or run with runtime logs enabled.",
        ]
    elif state == "case_json_missing":
        next_steps = [
            "This folder is missing issue-case.json. Recreate the case packet or pass the correct case_dir.",
        ]
    else:
        next_steps = [
            "Fix the CSV path or rerun the xEdit script, then run this status tool again.",
        ]

    status = {
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "updatedAt": iso_now(),
        "caseDir": str(case_dir),
        "statusPath": str(status_path),
        "jsonPath": str(json_path),
        "state": state,
        "readOnly": True,
        "dryRunOnly": True,
        "caseSummary": {
            "description": issue_input.get("description"),
            "topCandidate": top_candidate.get("mod"),
            "topCandidateConfidence": top_candidate.get("confidence"),
            "xeditPluginHint": xedit_diag.get("pluginName"),
            "caseJsonPath": str(issue_case_json_path(case_dir)) if issue_case_json_path(case_dir).exists() else None,
        },
        "xeditCsv": {
            "path": str(csv_path),
            "exists": csv_path.exists() and csv_path.is_file(),
            "parsed": bool(xedit_result),
            "error": csv_error,
        },
        "xeditResult": xedit_result,
        "candidatePlugins": xedit_result.get("candidatePlugins", []) if xedit_result else [],
        "nextSteps": next_steps,
    }
    status_to_write = redact_paths_in_value(status) if bool(args.get("redact_user_paths", False)) else status
    write_text(json_path, json.dumps(status_to_write, indent=2, ensure_ascii=False, default=str))
    write_text(status_path, issue_case_status_markdown(status_to_write))
    log_event(
        "support",
        "skyrim_issue_case_status_written",
        {"case_dir": str(case_dir), "status_path": str(status_path), "json_path": str(json_path), "state": state},
    )
    return {
        "caseDir": str(case_dir),
        "statusPath": str(status_path),
        "jsonPath": str(json_path),
        "state": state,
        "xeditCsvPath": str(csv_path),
        "xeditCsvExists": csv_path.exists() and csv_path.is_file(),
        "rowCount": xedit_result.get("rowCount") if xedit_result else None,
        "candidatePlugins": status["candidatePlugins"],
        "topCandidate": status["caseSummary"]["topCandidate"],
        "readOnly": True,
        "dryRunOnly": True,
        "nextSteps": next_steps,
    }


def issue_case_notes_paths(case_dir: Path) -> Tuple[Path, Path]:
    return case_dir / "case-notes.md", case_dir / "case-notes.jsonl"


def skyrim_issue_case_note(args: Dict[str, Any]) -> Dict[str, Any]:
    case_dir = expand_path(args.get("case_dir") or args.get("path"))
    if not case_dir or not case_dir.exists() or not case_dir.is_dir():
        raise ToolError("case_dir/path must point to an existing issue case folder.")
    note = str(args.get("note") or args.get("text") or "").strip()
    if not note:
        raise ToolError("Pass note/text to append to the issue case.")
    kind = str(args.get("kind") or "observation").strip() or "observation"
    source = str(args.get("source") or "openclaw").strip() or "openclaw"
    result = str(args.get("result") or "").strip()
    next_action = str(args.get("next_action") or "").strip()
    timestamp = iso_now()
    md_path, jsonl_path = issue_case_notes_paths(case_dir)
    md_lines = [
        f"## {timestamp} - {kind}",
        "",
        f"- Source: {source}",
    ]
    if result:
        md_lines.append(f"- Result: {result}")
    if next_action:
        md_lines.append(f"- Next action: {next_action}")
    md_lines.extend(["", note, ""])
    write_header = not md_path.exists() or md_path.stat().st_size == 0
    with md_path.open("a", encoding="utf-8", newline="\n") as handle:
        if write_header:
            handle.write("# Skyrim Issue Case Notes\n\n")
        handle.write("\n".join(md_lines) + "\n")
    entry = {
        "timestamp": timestamp,
        "kind": kind,
        "source": source,
        "note": note,
        "result": result,
        "nextAction": next_action,
        "readOnly": True,
    }
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    log_event("support", "skyrim_issue_case_note_appended", {"case_dir": str(case_dir), "kind": kind})
    return {
        "caseDir": str(case_dir),
        "notesPath": str(md_path),
        "notesJsonlPath": str(jsonl_path),
        "entry": entry,
        "readOnly": False,
        "writesOnlyCaseNotes": True,
        "notes": ["This appends notes in the case folder only. It does not change Vortex, Skyrim, plugins, or mods."],
    }


def issue_case_evidence_paths(case_dir: Path) -> Tuple[Path, Path, Path]:
    return case_dir / "live-evidence.md", case_dir / "live-evidence.jsonl", case_dir / "live-evidence-latest.json"


def evidence_suggested_args(entry: Dict[str, Any]) -> Dict[str, Any]:
    issue_args: Dict[str, Any] = {}
    if entry.get("popupText"):
        issue_args["popup_text"] = entry["popupText"]
        issue_args["description"] = entry.get("summary") or "popup captured from live evidence"
        issue_args["issue_kind"] = "popup"
    if entry.get("cell"):
        issue_args["cell"] = entry["cell"]
    if entry.get("objectName"):
        issue_args["object"] = entry["objectName"]
    if entry.get("referenceFormId"):
        issue_args["form_id"] = entry["referenceFormId"]
    elif entry.get("baseFormId"):
        issue_args["form_id"] = entry["baseFormId"]
    if entry.get("baseFormId"):
        issue_args["base_object"] = entry["baseFormId"]
    if entry.get("ocrText") and "popup_text" not in issue_args:
        issue_args["description"] = entry["ocrText"][:500]
    suggestions: Dict[str, Any] = {}
    if issue_args:
        suggestions["in_game_issue_report"] = issue_args
        suggestions["skyrim_issue_case_packet"] = issue_args
    if issue_args.get("form_id"):
        suggestions["xedit_diagnostics_report"] = {"form_id": issue_args["form_id"]}
    return suggestions


def skyrim_case_evidence_import(args: Dict[str, Any]) -> Dict[str, Any]:
    case_dir = expand_path(args.get("case_dir") or args.get("path"))
    if not case_dir or not case_dir.exists() or not case_dir.is_dir():
        raise ToolError("case_dir/path must point to an existing issue case folder.")
    evidence_type = str(args.get("evidence_type") or args.get("kind") or "manual").strip() or "manual"
    text = str(args.get("text") or args.get("evidence_text") or "").strip()
    popup_text = str(args.get("popup_text") or "").strip()
    ocr_text = str(args.get("ocr_text") or "").strip()
    note = str(args.get("note") or "").strip()
    if not any([text, popup_text, ocr_text, note, args.get("form_id"), args.get("reference_form_id"), args.get("base_form_id"), args.get("cell")]):
        raise ToolError("Pass at least one evidence value: text, popup_text, ocr_text, note, form_id, reference_form_id, base_form_id, or cell.")
    reference_form_id = normalize_form_id(str(args.get("reference_form_id") or args.get("form_id") or "").strip())
    base_form_id = normalize_form_id(str(args.get("base_form_id") or "").strip())
    if evidence_type in {"popup", "popup_text"} and text and not popup_text:
        popup_text = text
    if evidence_type in {"popup_ocr", "ocr"} and text and not ocr_text:
        ocr_text = text
    summary = popup_text or ocr_text or text or note or reference_form_id or base_form_id or str(args.get("cell") or "")
    entry = {
        "timestamp": iso_now(),
        "type": evidence_type,
        "source": str(args.get("source") or "manual").strip() or "manual",
        "summary": summary[:500],
        "text": text,
        "popupText": popup_text,
        "ocrText": ocr_text,
        "referenceFormId": reference_form_id,
        "baseFormId": base_form_id,
        "cell": str(args.get("cell") or "").strip(),
        "objectName": str(args.get("object") or args.get("object_name") or "").strip(),
        "screenshotPath": str(args.get("screenshot_path") or "").strip(),
        "confidence": str(args.get("confidence") or "").strip(),
        "note": note,
        "suggestedToolArgs": {},
    }
    entry["suggestedToolArgs"] = evidence_suggested_args(entry)
    md_path, jsonl_path, latest_path = issue_case_evidence_paths(case_dir)
    md_lines = [
        f"## {entry['timestamp']} - {entry['type']}",
        "",
        f"- Source: {entry['source']}",
    ]
    if entry["confidence"]:
        md_lines.append(f"- Confidence: {entry['confidence']}")
    if entry["popupText"]:
        md_lines.append(f"- Popup text: {entry['popupText']}")
    if entry["ocrText"]:
        md_lines.append(f"- OCR text: {entry['ocrText']}")
    if entry["referenceFormId"]:
        md_lines.append(f"- Reference FormID: {entry['referenceFormId']}")
    if entry["baseFormId"]:
        md_lines.append(f"- Base FormID: {entry['baseFormId']}")
    if entry["cell"]:
        md_lines.append(f"- Cell: {entry['cell']}")
    if entry["objectName"]:
        md_lines.append(f"- Object: {entry['objectName']}")
    if entry["screenshotPath"]:
        md_lines.append(f"- Screenshot path: {entry['screenshotPath']}")
    if entry["note"]:
        md_lines.extend(["", entry["note"]])
    write_header = not md_path.exists() or md_path.stat().st_size == 0
    with md_path.open("a", encoding="utf-8", newline="\n") as handle:
        if write_header:
            handle.write("# Skyrim Live Evidence\n\n")
        handle.write("\n".join(md_lines) + "\n\n")
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    write_text(latest_path, json.dumps(entry, indent=2, ensure_ascii=False, default=str))
    log_event("support", "skyrim_case_evidence_imported", {"case_dir": str(case_dir), "type": evidence_type})
    return {
        "caseDir": str(case_dir),
        "evidencePath": str(md_path),
        "evidenceJsonlPath": str(jsonl_path),
        "latestJsonPath": str(latest_path),
        "entry": entry,
        "writesOnlyCaseEvidence": True,
        "readOnly": False,
        "nextSteps": [
            "Use suggestedToolArgs to rerun in_game_issue_report or xEdit diagnostics with stronger captured evidence.",
            "Run skyrim_case_what_now after importing important evidence.",
            "Keep live evidence append-only so OpenClaw can audit what changed between tests.",
        ],
    }


def skyrim_case_bundle(args: Dict[str, Any]) -> Dict[str, Any]:
    case_dir = expand_path(args.get("case_dir") or args.get("path"))
    if not case_dir or not case_dir.exists() or not case_dir.is_dir():
        raise ToolError("case_dir/path must point to an existing issue case folder.")
    output_path = expand_path(args.get("output_path"))
    if not output_path:
        output_path = case_dir.with_name(f"{case_dir.name}-bundle-{now_stamp()}.zip")
    if output_path.suffix.lower() != ".zip":
        output_path = output_path.with_suffix(".zip")
    max_files = max(1, int(args.get("max_files", 500)))
    max_file_bytes = max(1_000, int(args.get("max_file_bytes", 5_000_000)))
    entries: List[str] = []
    skipped: List[Dict[str, Any]] = []
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(case_dir.rglob("*"), key=lambda item: str(item).lower()):
            if len(entries) >= max_files:
                skipped.append({"path": str(path), "reason": "max_files reached"})
                continue
            if not path.is_file():
                continue
            if path.resolve() == output_path.resolve():
                continue
            try:
                size = path.stat().st_size
            except OSError as exc:
                skipped.append({"path": str(path), "reason": str(exc)})
                continue
            if size > max_file_bytes:
                skipped.append({"path": str(path), "size": size, "reason": "larger than max_file_bytes"})
                continue
            rel = rel_to(path, case_dir)
            bundle.write(path, rel)
            entries.append(rel)
    log_event("support", "skyrim_case_bundle_written", {"case_dir": str(case_dir), "output_path": str(output_path), "entries": len(entries)})
    return {
        "caseDir": str(case_dir),
        "zipPath": str(output_path),
        "entryCount": len(entries),
        "entries": entries,
        "skipped": skipped[:50],
        "privacyNote": "The bundle can include local paths, mod/plugin names, notes, and captured popup/OCR text. Review before posting publicly.",
        "readOnly": True,
    }


def issue_case_top_evidence(case_dir: Path, packet: Dict[str, Any], status: Dict[str, Any]) -> Dict[str, Any]:
    in_game = packet.get("inGameIssue") if isinstance(packet.get("inGameIssue"), dict) else {}
    candidates = in_game.get("candidates") if isinstance(in_game.get("candidates"), list) else []
    top_candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
    xedit_result = status.get("xeditResult") if isinstance(status.get("xeditResult"), dict) else {}
    candidate_plugins = xedit_result.get("candidatePlugins") if isinstance(xedit_result.get("candidatePlugins"), list) else []
    top_plugins = xedit_result.get("topPlugins") if isinstance(xedit_result.get("topPlugins"), list) else []
    top_signatures = xedit_result.get("topSignatures") if isinstance(xedit_result.get("topSignatures"), list) else []
    return {
        "topCandidate": top_candidate,
        "topCandidateName": top_candidate.get("mod"),
        "topCandidateModId": top_candidate.get("vortexModId"),
        "candidatePlugins": candidate_plugins,
        "topPlugin": top_plugins[0].get("value") if top_plugins and isinstance(top_plugins[0], dict) else None,
        "topSignature": top_signatures[0].get("value") if top_signatures and isinstance(top_signatures[0], dict) else None,
        "statusState": status.get("state"),
        "caseDir": str(case_dir),
    }


def safe_experiment_plan_markdown(plan: Dict[str, Any]) -> str:
    target = plan.get("target", {}) if isinstance(plan.get("target"), dict) else {}
    lines = [
        "# Skyrim Safe Experiment Plan",
        "",
        f"- Server: {SERVER_NAME} {SERVER_VERSION}",
        f"- Created: {plan.get('createdAt')}",
        f"- Case folder: `{plan.get('caseDir')}`",
        f"- Dry run only: `{str(plan.get('dryRunOnly')).lower()}`",
        "",
        "## Target",
        "",
        f"- Mod name: `{target.get('modName') or '(unknown)'}`",
        f"- Vortex mod id: `{target.get('vortexModId') or '(unknown)'}`",
        f"- Plugin evidence: `{target.get('plugin') or '(none)'}`",
        f"- Record evidence: `{target.get('signature') or '(none)'}`",
        "",
        "## Steps",
        "",
    ]
    for index, step in enumerate(plan.get("steps", []), start=1):
        lines.append(f"{index}. {step}")
    if plan.get("dryRunToolCalls"):
        lines.extend(["", "## Dry-Run Tool Calls", ""])
        for call in plan.get("dryRunToolCalls", []):
            lines.append(f"- `{call.get('tool')}` with args `{json.dumps(call.get('args', {}), ensure_ascii=False)}`")
    lines.extend(
        [
            "",
            "## Undo",
            "",
            "- Keep the profile backup path from step 1.",
            "- If the test gets worse, switch back to the original profile or use the backup/restore preview first.",
            "- Do not delete the mod during this experiment.",
        ]
    )
    return "\n".join(lines) + "\n"


def skyrim_safe_experiment_plan(args: Dict[str, Any]) -> Dict[str, Any]:
    case_dir = expand_path(args.get("case_dir") or args.get("path"))
    if not case_dir or not case_dir.exists() or not case_dir.is_dir():
        raise ToolError("case_dir/path must point to an existing issue case folder.")
    packet = issue_case_load(case_dir)
    status = issue_case_load_status(case_dir)
    evidence = issue_case_top_evidence(case_dir, packet, status)
    target_mod_name = str(args.get("target_mod") or args.get("target_mod_name") or evidence.get("topCandidateName") or "").strip()
    target_mod_id = str(args.get("target_mod_id") or evidence.get("topCandidateModId") or "").strip()
    target_plugin = str(args.get("plugin_name") or evidence.get("topPlugin") or "").strip()
    target_signature = str(args.get("signature") or evidence.get("topSignature") or "").strip()
    plan_path = expand_path(args.get("output_path")) if args.get("output_path") else case_dir / "safe-experiment-plan.md"
    if not plan_path:
        raise ToolError("output_path resolved to an empty path.")
    if not plan_path.suffix:
        plan_path = plan_path / "safe-experiment-plan.md"
    json_path = plan_path.with_suffix(".json")
    if json_path == plan_path:
        json_path = plan_path.with_name(f"{plan_path.name}.json")
    test_profile_name = str(args.get("test_profile_name") or "OpenClaw Safe Test").strip() or "OpenClaw Safe Test"
    steps = [
        "Write a Vortex profile backup with include_all_profiles=true and keep the backup path in the case notes.",
        f"Create or reuse a cloned profile named '{test_profile_name}'. Preview first; apply only after the user approves and Vortex is closed.",
        "Switch Vortex to the cloned profile and deploy mods.",
    ]
    if target_mod_id:
        steps.append(f"In the cloned profile only, preview disabling Vortex mod id '{target_mod_id}' ({target_mod_name or 'candidate mod'}).")
    else:
        steps.append("Find the exact Vortex mod id for the target mod before any disable preview. Do not guess mod ids from names.")
    steps.extend(
        [
            "Launch Skyrim through the normal SKSE route for this setup and reproduce the issue.",
            "Append the result to the case notes: fixed, unchanged, worse, or new issue.",
            "If fixed, keep the change in the cloned profile until the user decides whether to patch, replace, or remove the mod. If not fixed, restore/re-enable and test one different candidate.",
        ]
    )
    dry_run_calls = [
        {"tool": "vortex_profile_backup", "args": {"include_all_profiles": True}},
        {"tool": "vortex_clone_profile", "args": {"new_name": test_profile_name, "apply": False}},
    ]
    if target_mod_id:
        dry_run_calls.append({"tool": "vortex_set_profile_mods", "args": {"disable_mod_ids": [target_mod_id], "apply": False}})
    plan = {
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "createdAt": iso_now(),
        "caseDir": str(case_dir),
        "planPath": str(plan_path),
        "jsonPath": str(json_path),
        "dryRunOnly": True,
        "readOnly": True,
        "target": {
            "modName": target_mod_name,
            "vortexModId": target_mod_id or None,
            "plugin": target_plugin or None,
            "signature": target_signature or None,
            "evidenceState": evidence.get("statusState"),
        },
        "steps": steps,
        "dryRunToolCalls": dry_run_calls,
        "blockers": [] if target_mod_id else ["No exact Vortex mod id is known yet; use vortex_profile_mods/profile state before disabling anything."],
        "notes": [
            "This plan does not apply changes. It gives OpenClaw a safe order of operations.",
            "Never delete a collection mod during an experiment; disable in a cloned profile first.",
        ],
    }
    write_text(json_path, json.dumps(plan, indent=2, ensure_ascii=False, default=str))
    write_text(plan_path, safe_experiment_plan_markdown(plan))
    log_event("support", "skyrim_safe_experiment_plan_written", {"case_dir": str(case_dir), "plan_path": str(plan_path)})
    return {
        "caseDir": str(case_dir),
        "planPath": str(plan_path),
        "jsonPath": str(json_path),
        "target": plan["target"],
        "dryRunOnly": True,
        "readOnly": True,
        "blockers": plan["blockers"],
        "dryRunToolCalls": dry_run_calls,
        "nextSteps": steps[:4],
    }


def case_what_now_markdown(answer: Dict[str, Any]) -> str:
    lines = [
        "# Skyrim Case What Now",
        "",
        f"- Server: {SERVER_NAME} {SERVER_VERSION}",
        f"- Updated: {answer.get('updatedAt')}",
        f"- Case folder: `{answer.get('caseDir')}`",
        f"- Recommendation: {answer.get('recommendation')}",
        f"- Confidence: `{answer.get('confidence')}`",
        "",
        "## Why",
        "",
    ]
    for reason in answer.get("reasons", []):
        lines.append(f"- {reason}")
    lines.extend(["", "## Next Actions", ""])
    for action in answer.get("nextActions", []):
        lines.append(f"- {action}")
    lines.extend(["", "## Safety", "", "- This is advice from existing evidence only; it does not change mods or profiles."])
    return "\n".join(lines) + "\n"


def skyrim_case_what_now(args: Dict[str, Any]) -> Dict[str, Any]:
    case_dir = expand_path(args.get("case_dir") or args.get("path"))
    if not case_dir or not case_dir.exists() or not case_dir.is_dir():
        raise ToolError("case_dir/path must point to an existing issue case folder.")
    packet = issue_case_load(case_dir)
    status = issue_case_load_status(case_dir)
    evidence = issue_case_top_evidence(case_dir, packet, status)
    status_state = str(evidence.get("statusState") or "no_status")
    recommendation = "Run the generated xEdit inspection script, then update the case status."
    confidence = "medium"
    reasons = []
    next_actions = []
    if status_state == "has_xedit_results":
        recommendation = "Use the xEdit evidence to plan one cloned-profile disable test."
        confidence = "high" if evidence.get("topPlugin") else "medium"
        reasons.append(f"xEdit CSV evidence exists. Top plugin: {evidence.get('topPlugin') or 'unknown'}.")
        if evidence.get("topSignature"):
            reasons.append(f"Top record signature is {evidence.get('topSignature')}.")
        next_actions = [
            "Run skyrim_safe_experiment_plan for this case folder.",
            "Append a case note before and after the test.",
            "Disable only one exact Vortex mod id in a cloned profile after user approval.",
        ]
    elif status_state == "empty_xedit_results":
        recommendation = "Rerun the xEdit script on a broader selection or full load order."
        confidence = "medium"
        reasons.append("The case status found the CSV, but it had no rows.")
        next_actions = ["Apply the generated xEdit script to a broader plugin scope.", "Run skyrim_issue_case_status again."]
    elif status_state == "needs_xedit_run":
        reasons.append("The case exists, but the xEdit CSV has not been produced yet.")
        next_actions = ["Run the generated xEdit script in SSEEdit/xEdit.", "Run skyrim_issue_case_status after the CSV appears."]
    elif evidence.get("topCandidateName"):
        recommendation = "Generate or run xEdit evidence before testing the top candidate."
        confidence = "medium"
        reasons.append(f"Top local triage candidate is {evidence.get('topCandidateName')}, but xEdit status is not complete.")
        next_actions = ["Run the generated xEdit script or recreate the case packet.", "Then run skyrim_issue_case_status."]
    else:
        recommendation = "Recreate the issue case with more clues."
        confidence = "low"
        reasons.append("No useful case candidate or xEdit status was found.")
        next_actions = ["Add description/location/object/FormID/popup text, then run skyrim_issue_case_packet again."]
    out_path = expand_path(args.get("output_path")) if args.get("output_path") else case_dir / "what-now.md"
    if not out_path:
        raise ToolError("output_path resolved to an empty path.")
    if not out_path.suffix:
        out_path = out_path / "what-now.md"
    json_path = out_path.with_suffix(".json")
    answer = {
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "updatedAt": iso_now(),
        "caseDir": str(case_dir),
        "outputPath": str(out_path),
        "jsonPath": str(json_path),
        "recommendation": recommendation,
        "confidence": confidence,
        "reasons": reasons,
        "nextActions": next_actions,
        "readOnly": True,
        "dryRunOnly": True,
    }
    write_text(json_path, json.dumps(answer, indent=2, ensure_ascii=False, default=str))
    write_text(out_path, case_what_now_markdown(answer))
    log_event("support", "skyrim_case_what_now_written", {"case_dir": str(case_dir), "output_path": str(out_path)})
    return answer


def skyrim_live_bridge_status(args: Dict[str, Any]) -> Dict[str, Any]:
    case_dir = expand_path(args.get("case_dir") or args.get("path"))
    output_path = expand_path(args.get("output_path")) if args.get("output_path") else (case_dir / "live-bridge-design.md" if case_dir else None)
    capabilities = {
        "screenshotOcr": {
            "implemented": False,
            "neededFor": ["reading popup text without the user typing it", "capturing menu/dialog state"],
            "requirements": ["local screenshot capture", "OCR engine", "privacy-aware image storage in case folder"],
        },
        "consoleFormIdCapture": {
            "implemented": False,
            "neededFor": ["clicked reference/base FormID", "current cell"],
            "requirements": ["console log capture or user-assisted copy", "optional SKSE plugin for telemetry"],
        },
        "skseTelemetry": {
            "implemented": False,
            "neededFor": ["current cell", "active menus/messages", "selected reference"],
            "requirements": ["separate SKSE plugin", "read-only local IPC/log output", "strict no-save/no-plugin-edit boundary"],
        },
        "caseFolderIntegration": {
            "implemented": True,
            "neededFor": ["storing captured evidence", "letting OpenClaw continue from the same folder"],
            "requirements": ["skyrim_issue_case_packet", "skyrim_case_evidence_import", "skyrim_issue_case_note", "skyrim_issue_case_status"],
        },
    }
    design_lines = [
        "# Skyrim Live Bridge Status",
        "",
        "This MCP does not directly see the running game yet. It can consume evidence saved into a case folder.",
        "",
        "## Implemented Now",
        "",
        "- Case folders, live evidence import, notes, xEdit CSV parsing, and safe experiment plans.",
        "",
        "## Needed For True Live Diagnosis",
        "",
        "- Screenshot/OCR capture for popup text.",
        "- Console/FormID capture for clicked objects.",
        "- Optional SKSE telemetry for current cell and active messages.",
        "- Strict read-only IPC/log output so OpenClaw can observe without changing the game.",
        "",
    ]
    if output_path:
        write_text(output_path, "\n".join(design_lines))
    return {
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "caseDir": str(case_dir) if case_dir else None,
        "outputPath": str(output_path) if output_path else None,
        "canSeeRunningGameNow": False,
        "canUseCaseFolderEvidenceNow": True,
        "capabilities": capabilities,
        "recommendedNextBuild": [
            "Add a small separate screenshot/OCR helper that writes popup text to the case folder.",
            "Add a user-assisted console FormID capture file before considering SKSE telemetry.",
            "Keep all live bridge output read-only and append-only.",
        ],
        "readOnly": True,
    }


def collection_state_paths(game_id: str) -> List[str]:
    return [
        "persistent.collections",
        "persistent.collectionDownloads",
        "persistent.collectionInstallations",
        "settings.collections",
        state_path("persistent", "mods", game_id),
        "persistent.profiles",
    ]


def collectionish_keys(value: Dict[str, Any]) -> bool:
    keys = {str(key).lower() for key in value.keys()}
    return (
        any("collection" in key for key in keys)
        or {"slug", "revision", "revisionid"} & keys
        or ({"mods", "modids", "fileids"} & keys and {"name", "title", "id"} & keys)
    )


def summarize_collectionish(path: str, value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict) or not collectionish_keys(value):
        return None
    list_counts = {
        str(key): len(item)
        for key, item in value.items()
        if isinstance(item, (list, dict)) and any(term in str(key).lower() for term in ("mod", "file", "collection", "revision"))
    }
    return {
        "path": path,
        "id": value.get("id") or value.get("collectionId") or value.get("collection_id"),
        "name": value.get("name") or value.get("title"),
        "slug": value.get("slug") or value.get("collectionSlug"),
        "revision": value.get("revision") or value.get("revisionId") or value.get("revision_id"),
        "listCounts": list_counts,
        "keys": sorted(str(key) for key in value.keys())[:40],
    }


def find_collectionish_state(value: Any, path: str = "", max_items: int = 80) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []

    def walk(current: Any, current_path: str) -> None:
        if len(found) >= max_items:
            return
        if isinstance(current, dict):
            summary = summarize_collectionish(current_path, current)
            if summary:
                found.append(summary)
            for key, item in current.items():
                key_path = f"{current_path}.{key}" if current_path else str(key)
                if "collection" in key_path.lower() or isinstance(item, dict):
                    walk(item, key_path)
                elif isinstance(item, list) and "collection" in key_path.lower():
                    walk(item, key_path)
        elif isinstance(current, list):
            for index, item in enumerate(current[:max_items]):
                walk(item, f"{current_path}[{index}]")

    walk(value, path)
    return found


def mod_collection_markers(mods: Dict[str, Any], max_mods: int = 500) -> List[Dict[str, Any]]:
    rows = []
    for mod_id, entry in list(mods.items())[:max_mods]:
        if not isinstance(entry, dict):
            continue
        attributes = entry.get("attributes") if isinstance(entry.get("attributes"), dict) else {}
        marker_keys = [key for key in attributes.keys() if "collection" in str(key).lower()]
        if not marker_keys:
            continue
        rows.append(
            {
                "modId": str(mod_id),
                "name": summarize_vortex_mod(str(mod_id), mods).get("name"),
                "markers": {str(key): attributes.get(key) for key in marker_keys[:20]},
            }
        )
    return rows


def vortex_collection_report(args: Dict[str, Any]) -> Dict[str, Any]:
    game_id = str(args.get("game_id") or GAME_ID)
    max_items = int(args.get("max_collection_items", 80))
    paths = collection_state_paths(game_id)
    result = vortex_state_get(paths, args.get("vortex_exe"), int(args.get("timeout_seconds", 60)))
    state = result["state"]
    mods = nested_get(state, ["persistent", "mods", game_id])
    mods = mods if isinstance(mods, dict) else {}
    collection_states = find_collectionish_state(state, max_items=max_items)
    markers = mod_collection_markers(mods, int(args.get("max_mods", 500)))
    return {
        "gameId": game_id,
        "vortexExe": result.get("vortex_exe"),
        "rawPaths": paths,
        "collectionStateCount": len(collection_states),
        "collectionStates": collection_states[:max_items],
        "modCollectionMarkerCount": len(markers),
        "modCollectionMarkers": markers[:max_items],
        "available": bool(collection_states or markers),
        "notes": [
            "This is read-only and depends on whatever collection state Vortex exposes through its CLI.",
            "If no collection state appears, Vortex may store collection details in extension-private state this MCP cannot safely read yet.",
        ],
    }


def extract_manifest_mod_refs(value: Any, max_items: int = 5000) -> List[Dict[str, Optional[int]]]:
    refs: List[Dict[str, Optional[int]]] = []

    def parse_int(value: Any) -> Optional[int]:
        try:
            parsed = int(str(value))
            return parsed if parsed > 0 else None
        except (TypeError, ValueError):
            return None

    def lookup_id(current: Dict[str, Any], names: Iterable[str]) -> Optional[int]:
        normalized = {
            re.sub(r"[^a-z0-9]", "", str(key).lower()): item
            for key, item in current.items()
        }
        for name in names:
            value = normalized.get(re.sub(r"[^a-z0-9]", "", name.lower()))
            parsed = parse_int(value)
            if parsed:
                return parsed
        return None

    def walk(current: Any) -> None:
        if len(refs) >= max_items:
            return
        if isinstance(current, dict):
            mod_id = lookup_id(current, ("modId", "nexusModId", "nexus_mod_id", "mod_id", "nexusModsModId"))
            file_id = lookup_id(current, ("fileId", "nexusFileId", "nexus_file_id", "file_id", "nexusModsFileId"))
            if mod_id:
                refs.append({"modId": mod_id, "fileId": file_id})
            for item in current.values():
                if isinstance(item, (dict, list)):
                    walk(item)
        elif isinstance(current, list):
            for item in current:
                walk(item)

    walk(value)
    unique: Dict[Tuple[Optional[int], Optional[int]], Dict[str, Optional[int]]] = {}
    for ref in refs:
        unique[(ref.get("modId"), ref.get("fileId"))] = ref
    return list(unique.values())


def load_collection_manifest_arg(args: Dict[str, Any]) -> Any:
    try:
        if args.get("collection_manifest_json"):
            return json.loads(str(args.get("collection_manifest_json")))
        manifest_path = expand_path(args.get("collection_manifest_path"))
        if manifest_path and manifest_path.exists():
            return json.loads(read_text(manifest_path, 20_000_000))
        if manifest_path:
            raise ToolError(f"Collection manifest path was not found: {manifest_path}")
    except json.JSONDecodeError as exc:
        raise ToolError(f"Collection manifest JSON could not be parsed: {exc}") from exc
    raise ToolError("Pass collection_manifest_path or collection_manifest_json.")


def local_nexus_source_rows(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    _vortex_appdata, _skyrim_dir, staging_dir, _my_games = get_context_paths(args)
    if not staging_dir or not staging_dir.exists():
        raise ToolError("Vortex staging folder was not found. Pass staging_dir explicitly.")
    max_mods = int(args.get("max_mods", 500))
    max_files_per_mod = int(args.get("max_files_per_mod", 3000))
    profile_lookup = profile_lookup_for_staging(args, staging_dir) if bool(args.get("include_profile_state", True)) else {"modsByPath": {}}
    profile_by_path = profile_lookup.get("modsByPath") if isinstance(profile_lookup.get("modsByPath"), dict) else {}
    scan_cache = load_scan_cache(args) if scan_cache_enabled(args) else {}
    rows = []
    for mod_dir in sorted([path for path in staging_dir.iterdir() if path.is_dir()], key=lambda path: path.name.lower())[:max_mods]:
        summary = mod_summary_cached(mod_dir, include_files=False, max_files=max_files_per_mod, args=args, cache=scan_cache)
        try:
            profile_key = str(mod_dir.resolve()).lower()
        except OSError:
            profile_key = str(mod_dir).lower()
        profile = profile_by_path.get(profile_key)
        ids = local_nexus_ids(summary, profile if isinstance(profile, dict) else None)
        rows.append(
            {
                "mod": summary.get("name"),
                "path": str(mod_dir),
                "modId": ids.get("modId"),
                "fileId": ids.get("fileId"),
                "localVersion": local_mod_version(summary, profile if isinstance(profile, dict) else None),
                "enabled": profile.get("enabled") if isinstance(profile, dict) else None,
                "vortexModId": profile.get("id") if isinstance(profile, dict) else None,
            }
        )
    if scan_cache_enabled(args):
        write_scan_cache(args, scan_cache)
    return rows


def collection_local_match_report(args: Dict[str, Any]) -> Dict[str, Any]:
    manifest = load_collection_manifest_arg(args)
    refs = extract_manifest_mod_refs(manifest, int(args.get("max_collection_items", 5000)))
    local_rows = local_nexus_source_rows(args)
    expected_mod_ids = {ref["modId"] for ref in refs if ref.get("modId")}
    expected_pairs = {(ref.get("modId"), ref.get("fileId")) for ref in refs if ref.get("modId") and ref.get("fileId")}
    local_mod_ids = {row["modId"] for row in local_rows if row.get("modId")}
    local_pairs = {(row.get("modId"), row.get("fileId")) for row in local_rows if row.get("modId") and row.get("fileId")}
    missing_mod_ids = sorted(expected_mod_ids - local_mod_ids)
    extra_mod_ids = sorted(local_mod_ids - expected_mod_ids) if expected_mod_ids else []
    file_mismatches = sorted(expected_pairs - local_pairs)
    disabled_expected = [
        row for row in local_rows if row.get("modId") in expected_mod_ids and row.get("enabled") is False
    ]
    warnings = []
    if not refs:
        warnings.append(
            "No Nexus mod/file references were found in the supplied manifest. The JSON shape may not be a collection manifest this tool recognizes."
        )
    return {
        "manifestReferenceCount": len(refs),
        "expectedModCount": len(expected_mod_ids),
        "expectedFilePairCount": len(expected_pairs),
        "localNexusModCount": len(local_mod_ids),
        "missingModIds": missing_mod_ids[:200],
        "missingModIdCount": len(missing_mod_ids),
        "extraLocalNexusModIds": extra_mod_ids[:200],
        "extraLocalNexusModIdCount": len(extra_mod_ids),
        "filePairMismatchCount": len(file_mismatches),
        "filePairMismatches": [{"modId": mod_id, "fileId": file_id} for mod_id, file_id in file_mismatches[:200]],
        "disabledExpectedCount": len(disabled_expected),
        "disabledExpected": disabled_expected[:100],
        "warnings": warnings,
        "notes": [
            "This compares a supplied manifest-like JSON file to local Vortex/staging Nexus metadata. It does not install collection mods.",
            "File-pair mismatches can be normal when a collection pins older files or local metadata is incomplete.",
        ],
    }


def mod_evidence(args: Dict[str, Any]) -> Dict[str, Any]:
    mod_dir = expand_path(args.get("mod_dir"))
    if not mod_dir or not mod_dir.exists() or not mod_dir.is_dir():
        raise ToolError("mod_dir must point to an existing mod folder.")
    max_text_bytes = int(args.get("max_text_bytes", 80_000))
    summary = mod_summary(mod_dir, include_files=True, max_files=int(args.get("max_files", 4000)))
    texts = []
    for rel in summary.get("readmes", [])[:5]:
        path = mod_dir / rel
        if path.exists():
            texts.append({"relativePath": rel, "text": read_text(path, max_text_bytes)})
    plugin_headers = {}
    for rel in summary.get("plugins", []):
        path = mod_dir / rel
        if path.exists():
            plugin_headers[rel] = plugin_masters(path)
    return {
        "summary": summary,
        "pluginHeaders": plugin_headers,
        "readmeTexts": texts,
        "evidenceHints": infer_mod_purpose(summary),
    }


def infer_mod_purpose(summary: Dict[str, Any]) -> List[str]:
    hints = []
    kinds = summary.get("kinds", {})
    if kinds.get("skse_plugin"):
        hints.append("Contains SKSE DLL plugin files; check Address Library/runtime compatibility.")
    if kinds.get("script"):
        hints.append("Contains Papyrus scripts; conflicts can affect quests/gameplay.")
    if kinds.get("mesh") or kinds.get("texture"):
        hints.append("Contains visual assets such as meshes/textures.")
    if kinds.get("interface"):
        hints.append("Contains UI/interface files; check SkyUI/MCM compatibility.")
    if summary.get("plugins"):
        hints.append("Contains ESP/ESM/ESL plugins; load order and masters matter.")
    if summary.get("archives"):
        hints.append("Contains BSA archives; plugin/archive pairing may matter.")
    return hints


GAMEPLAY_FILE_KINDS = {
    "plugin",
    "archive",
    "skse_plugin",
    "script",
    "mesh",
    "texture",
    "interface",
    "animation_tool",
    "config",
}


def format_bytes(size: Any) -> str:
    try:
        value = float(size)
    except (TypeError, ValueError):
        return "unknown"
    units = ["B", "KB", "MB", "GB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"


def md_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\\", "\\\\").replace("\n", " ").replace("|", "\\|").strip()


def md_bullets(values: List[str], prefix: str = "- ") -> List[str]:
    return [f"{prefix}{value}" for value in values if value]


def first_readme_lines(mod_dir: Path, readmes: List[str], max_lines: int, max_bytes: int) -> List[Dict[str, Any]]:
    excerpts: List[Dict[str, Any]] = []
    for rel in readmes[:3]:
        path = mod_dir / rel
        if not path.exists():
            continue
        try:
            lines = []
            for raw in read_text(path, max_bytes).splitlines():
                line = raw.strip()
                if not line:
                    continue
                if len(line) > 220:
                    line = line[:217] + "..."
                lines.append(line)
                if len(lines) >= max_lines:
                    break
            if lines:
                excerpts.append({"relativePath": rel, "lines": lines})
        except Exception as exc:
            excerpts.append({"relativePath": rel, "error": str(exc)})
    return excerpts


def infer_mod_knowledge(summary: Dict[str, Any]) -> Dict[str, Any]:
    name = str(summary.get("name") or "")
    lower_name = name.lower()
    kinds = summary.get("kinds", {}) if isinstance(summary.get("kinds"), dict) else {}
    categories: List[str] = []
    risk_flags: List[str] = []

    if summary.get("plugins"):
        categories.append("load-order plugin")
    if kinds.get("archive"):
        categories.append("BSA/archive assets")
    if kinds.get("skse_plugin"):
        categories.append("SKSE native plugin")
        risk_flags.append("runtime/DLL compatibility")
    if kinds.get("script"):
        categories.append("Papyrus scripts")
        risk_flags.append("save-game/script state")
    if kinds.get("interface"):
        categories.append("UI/interface")
        risk_flags.append("UI/MCM overwrite order")
    if kinds.get("mesh") or kinds.get("texture"):
        categories.append("visual assets")
    if kinds.get("animation_tool") or any(token in lower_name for token in ("nemesis", "fnis", "animation", "behavior")):
        categories.append("animation/behavior")
        risk_flags.append("animation behavior generation")
    if any(token in lower_name for token in ("skeleton", "xpmsse", "bodyslide", "cbbe", "body", "physics")):
        categories.append("body/skeleton/physics")
        risk_flags.append("body/skeleton dependency")
    if kinds.get("config"):
        categories.append("configuration")
    if summary.get("metadata", {}).get("fomod"):
        categories.append("FOMOD installer")
    if any(token in lower_name for token in ("patch", "compat", "compatibility", "addon", "plugin")):
        categories.append("patch/add-on candidate")

    recognized = sum(int(kinds.get(kind, 0) or 0) for kind in GAMEPLAY_FILE_KINDS)
    docs_only = recognized == 0
    if docs_only:
        role = "documentation or installer leftovers"
        removal_risk = "low"
    elif kinds.get("skse_plugin"):
        role = "runtime extension"
        removal_risk = "high"
    elif kinds.get("script"):
        role = "scripted gameplay/system mod"
        removal_risk = "high"
    elif summary.get("plugins"):
        role = "load-order/content mod"
        removal_risk = "high"
    elif kinds.get("interface"):
        role = "UI/interface mod"
        removal_risk = "medium"
    elif kinds.get("animation_tool"):
        role = "animation tool/output"
        removal_risk = "medium"
    elif kinds.get("mesh") or kinds.get("texture"):
        role = "visual replacer/assets"
        removal_risk = "low-medium"
    else:
        role = "support/configuration files"
        removal_risk = "medium"

    return {
        "role": role,
        "categories": sorted(set(categories)) or ["unknown"],
        "riskFlags": sorted(set(risk_flags)),
        "recognizedGameFileCount": recognized,
        "docsOnly": docs_only,
        "removalRisk": removal_risk,
        "purposeHints": infer_mod_purpose(summary),
    }


def profile_lookup_for_staging(args: Dict[str, Any], staging_dir: Optional[Path]) -> Dict[str, Any]:
    if not bool(args.get("include_profile_state", True)):
        return {"available": False, "modsByPath": {}, "error": None}
    try:
        snapshot = load_vortex_profile_state(args, include_mods=True)
        profile_id, profile = require_profile(snapshot, args.get("profile_id"))
        mod_state = profile.get("modState") if isinstance(profile.get("modState"), dict) else {}
        by_path: Dict[str, Dict[str, Any]] = {}
        for mod_id, entry in mod_state.items():
            mod_id_str = str(mod_id)
            mod_meta = summarize_vortex_mod(mod_id_str, snapshot["mods"])
            mod_path = resolve_mod_staging_path(mod_id_str, snapshot["mods"].get(mod_id_str), staging_dir)
            if not mod_path:
                continue
            try:
                key = str(mod_path.resolve()).lower()
            except OSError:
                key = str(mod_path).lower()
            by_path[key] = {
                **mod_meta,
                "enabled": profile_enabled(entry),
                "enabledTime": profile_enabled_time(entry),
                "enabledTimeIso": epoch_to_iso(profile_enabled_time(entry)),
            }
        return {
            "available": True,
            "profile": summarize_profile(profile_id, profile, snapshot["activeProfileId"]),
            "modsByPath": by_path,
            "error": None,
        }
    except Exception as exc:
        return {"available": False, "modsByPath": {}, "error": str(exc)}


ISSUE_STOP_WORDS = {
    "about",
    "also",
    "and",
    "are",
    "because",
    "been",
    "being",
    "can",
    "causing",
    "does",
    "find",
    "from",
    "get",
    "has",
    "have",
    "how",
    "into",
    "its",
    "lot",
    "mod",
    "mods",
    "outside",
    "problem",
    "some",
    "that",
    "the",
    "there",
    "things",
    "this",
    "was",
    "what",
    "when",
    "which",
    "why",
    "with",
}


POPUP_INTENT_TERMS = {
    "alert",
    "alerts",
    "dialog",
    "dialogue",
    "message",
    "messages",
    "mcm",
    "menu",
    "modal",
    "notification",
    "notifications",
    "overlay",
    "pop",
    "popup",
    "popups",
    "popping",
    "prompt",
    "prompts",
    "toast",
    "warning",
    "warnings",
    "widget",
    "window",
}


POPUP_SUPPORT_TERMS = {
    "after",
    "alert",
    "box",
    "dialog",
    "interface",
    "loading",
    "mcm",
    "menu",
    "message",
    "notification",
    "prompt",
    "save",
    "settings",
    "skyui",
    "ui",
    "warning",
    "widget",
}


ISSUE_SCAN_MODES = {"quick", "balanced", "deep"}
PERFORMANCE_MODES = {"normal", "slow_model", "fast", "thorough"}
RESPONSE_MODES = {"standard", "compact", "brief", "slow_model"}
COMPACT_RESPONSE_MODES = {"compact", "brief", "slow_model"}
ISSUE_TEXT_SUFFIXES = {".txt", ".md", ".ini", ".json", ".xml", ".toml"}
PATH_SCAN_KINDS = {"interface", "script", "skse_plugin", "config", "fomod", "plugin", "animation_tool"}
WEAK_POPUP_PATH_TERMS = {"after", "loading", "save"}


def normalized_performance_mode(args: Dict[str, Any]) -> str:
    raw = str(args.get("performance_mode") or args.get("performanceMode") or "normal").strip().lower().replace("-", "_")
    return raw if raw in PERFORMANCE_MODES else "normal"


def normalized_response_mode(args: Dict[str, Any]) -> str:
    raw = str(args.get("response_mode") or args.get("responseMode") or "").strip().lower().replace("-", "_")
    if raw in COMPACT_RESPONSE_MODES:
        return "compact"
    if raw in RESPONSE_MODES:
        return raw
    return "compact" if normalized_performance_mode(args) in {"slow_model", "fast"} else "standard"


def compact_response_requested(args: Dict[str, Any]) -> bool:
    return normalized_response_mode(args) in COMPACT_RESPONSE_MODES


def apply_performance_defaults(args: Dict[str, Any]) -> Dict[str, Any]:
    mode = normalized_performance_mode(args)
    tuned = dict(args)
    if mode == "slow_model":
        if normalized_response_mode(tuned) == "standard":
            tuned["response_mode"] = "compact"
        else:
            tuned.setdefault("response_mode", "compact")
        tuned.setdefault("scan_mode", "balanced")
        tuned.setdefault("max_candidates", 5)
        tuned.setdefault("max_evidence_per_mod", 3)
        tuned.setdefault("balanced_text_files_per_mod", 4)
        tuned.setdefault("max_log_files", 6)
        tuned.setdefault("max_runtime_findings", 30)
        tuned.setdefault("max_runtime_index_files", 30_000)
        tuned.setdefault("timeout_seconds", 45)
        tuned.setdefault("include_conflicts", False)
        tuned.setdefault("include_profile_backup", False)
    elif mode == "fast":
        if normalized_response_mode(tuned) == "standard":
            tuned["response_mode"] = "compact"
        else:
            tuned.setdefault("response_mode", "compact")
        tuned.setdefault("scan_mode", "quick")
        tuned.setdefault("max_candidates", 3)
        tuned.setdefault("max_evidence_per_mod", 2)
        tuned.setdefault("max_mods", 250)
        tuned.setdefault("max_log_files", 4)
        tuned.setdefault("max_runtime_findings", 20)
        tuned.setdefault("max_runtime_index_files", 20_000)
        tuned.setdefault("timeout_seconds", 25)
        tuned.setdefault("include_conflicts", False)
        tuned.setdefault("include_profile_backup", False)
    elif mode == "thorough":
        tuned.setdefault("response_mode", "standard")
        tuned.setdefault("scan_mode", "balanced")
        tuned.setdefault("max_candidates", 20)
        tuned.setdefault("max_evidence_per_mod", 10)
        tuned.setdefault("balanced_text_files_per_mod", 12)
        tuned.setdefault("timeout_seconds", 90)
    return tuned


def tokenize_issue_terms(*values: Optional[str]) -> List[str]:
    terms: set[str] = set()
    joined = " ".join(str(value or "") for value in values).lower()
    for token in re.findall(r"[a-z0-9_'-]{3,}", joined):
        clean = token.strip("_'-")
        if clean and clean not in ISSUE_STOP_WORDS:
            terms.add(clean)
            compact = clean.replace("-", "")
            if compact and compact != clean and compact not in ISSUE_STOP_WORDS:
                terms.add(compact)
    if "whiterun" in terms and ({"tavern", "inn", "room"} & terms):
        terms.update({"bannered", "mare", "inn"})
    if "bannered" in terms or "mare" in terms:
        terms.update({"bannered", "mare", "whiterun", "tavern", "inn"})
    if "bed" in terms:
        terms.update({"bedroll", "furniture", "furn"})
    if POPUP_INTENT_TERMS & terms:
        terms.update(POPUP_SUPPORT_TERMS)
    return sorted(terms)


def matched_issue_terms(text: str, terms: Iterable[str]) -> List[str]:
    lower = text.lower()
    return sorted({term for term in terms if term and term in lower})


def issue_scan_mode(args: Dict[str, Any]) -> str:
    if bool(args.get("deep_scan_files", False)):
        return "deep"
    raw = str(args.get("scan_mode") or args.get("scanMode") or "balanced").strip().lower()
    return raw if raw in ISSUE_SCAN_MODES else "balanced"


def meaningful_issue_hits(hits: Iterable[str], issue_kind: str) -> bool:
    hit_set = set(hits)
    if not hit_set:
        return False
    if issue_kind == "popup" and hit_set <= WEAK_POPUP_PATH_TERMS:
        return False
    return True


def add_issue_evidence(
    evidence: List[Dict[str, Any]],
    matched: set[str],
    source: str,
    text: str,
    terms: Iterable[str],
    max_items: int,
) -> List[str]:
    hits = matched_issue_terms(text, terms)
    if not hits:
        return []
    matched.update(hits)
    if len(evidence) < max_items:
        preview = re.sub(r"\s+", " ", text).strip()
        if len(preview) > 180:
            preview = preview[:177] + "..."
        evidence.append({"source": source, "matchedTerms": hits, "preview": preview})
    return hits


def exact_text_excerpt(text: str, needle: str, radius: int = 90) -> str:
    lower = text.lower()
    index = lower.find(needle.lower())
    if index < 0:
        preview = re.sub(r"\s+", " ", text).strip()
        return preview[:180] + ("..." if len(preview) > 180 else "")
    start = max(0, index - radius)
    end = min(len(text), index + len(needle) + radius)
    excerpt = re.sub(r"\s+", " ", text[start:end]).strip()
    if start > 0:
        excerpt = "..." + excerpt
    if end < len(text):
        excerpt += "..."
    return excerpt


def read_file_head(path: Path, max_bytes: int) -> str:
    try:
        with path.open("rb") as handle:
            data = handle.read(max_bytes)
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def extract_plugin_strings(path: Path, max_bytes: int = 5_000_000, max_strings: int = 2500) -> List[str]:
    try:
        with path.open("rb") as handle:
            data = handle.read(max_bytes)
    except OSError:
        return []
    strings: List[str] = []
    seen: set[str] = set()
    for raw in re.findall(rb"[ -~]{4,}", data):
        text = raw.decode("utf-8", errors="replace").strip()
        key = text.lower()
        if key and key not in seen:
            seen.add(key)
            strings.append(text)
            if len(strings) >= max_strings:
                return strings
    for raw in re.findall(rb"(?:[ -~]\x00){4,}", data):
        text = raw.decode("utf-16le", errors="replace").strip()
        key = text.lower()
        if key and key not in seen:
            seen.add(key)
            strings.append(text)
            if len(strings) >= max_strings:
                return strings
    return strings


def normalize_form_id(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    value = re.sub(r"[^0-9A-Fa-f]", "", str(raw))
    if len(value) < 6:
        return None
    if len(value) > 8:
        value = value[-8:]
    return value.upper()


def form_id_load_order_hint(args: Dict[str, Any], form_id: Optional[str]) -> Optional[Dict[str, Any]]:
    normalized = normalize_form_id(form_id)
    if not normalized or len(normalized) < 8:
        return None
    prefix = normalized[:2]
    hint: Dict[str, Any] = {
        "formId": normalized,
        "loadOrderPrefix": prefix,
        "pluginName": None,
        "confidence": "low",
        "notes": [
            "This is a helper hint, not proof. ESL/light plugins and runtime-created references can make FormID prefixes harder to map.",
        ],
    }
    if prefix == "FE":
        hint["notes"].append("FE usually indicates an ESL/light plugin range; use xEdit or an in-game ref lookup for the exact plugin.")
        return hint
    local = expand_path(args.get("local_appdata")) or default_local_appdata()
    state = plugin_state_paths(local)
    plugins_txt = parse_plugin_list(Path(state["plugins_txt"]) if state["plugins_txt"] else None)
    enabled_entries = [entry for entry in plugins_txt.get("entries", []) if entry.get("enabled")]
    try:
        index = int(prefix, 16)
    except ValueError:
        return hint
    hint["loadOrderIndexDecimal"] = index
    if 0 <= index < len(enabled_entries):
        hint["pluginName"] = enabled_entries[index].get("name")
        hint["confidence"] = "medium"
    return hint


def infer_issue_kind(args: Dict[str, Any], terms: List[str]) -> str:
    explicit = str(args.get("issue_kind") or "").strip().lower()
    if explicit in {"placed_object", "popup", "ui_popup", "general"}:
        return "popup" if explicit == "ui_popup" else explicit
    if args.get("popup_text") or POPUP_INTENT_TERMS & set(terms):
        return "popup"
    if args.get("object") or {"bed", "bedroll", "furniture", "furn"} & set(terms):
        return "placed_object"
    return "general"


def natural_language_popup_mode(args: Dict[str, Any], terms: List[str]) -> bool:
    return infer_issue_kind(args, terms) == "popup" and not str(args.get("popup_text") or "").strip()


def popup_capability_evidence(summary: Dict[str, Any], max_evidence: int) -> Tuple[int, List[Dict[str, Any]]]:
    kinds = summary.get("kinds", {}) if isinstance(summary.get("kinds"), dict) else {}
    metadata = summary.get("metadata", {}) if isinstance(summary.get("metadata"), dict) else {}
    name = str(summary.get("name") or "")
    evidence: List[Dict[str, Any]] = []
    score = 0

    def add(points: int, source: str, matched: List[str], preview: str) -> None:
        nonlocal score
        score += points
        if len(evidence) < max_evidence:
            evidence.append({"source": source, "matchedTerms": matched, "preview": preview})

    if kinds.get("interface"):
        add(8, "mod file kinds", ["interface", "ui"], f"{kinds.get('interface')} UI/interface file(s) detected.")
    if kinds.get("script"):
        add(4, "mod file kinds", ["script"], f"{kinds.get('script')} Papyrus script file(s) detected.")
    if kinds.get("skse_plugin"):
        add(4, "mod file kinds", ["skse_plugin"], f"{kinds.get('skse_plugin')} SKSE plugin file(s) detected.")
    if kinds.get("config"):
        add(2, "mod file kinds", ["config"], f"{kinds.get('config')} config file(s) detected.")
    if metadata.get("fomod"):
        add(2, "FOMOD metadata", ["fomod", "menu"], "Installer metadata is present; check installed options if this mod is a candidate.")

    name_hits = matched_issue_terms(name, POPUP_SUPPORT_TERMS | POPUP_INTENT_TERMS)
    if name_hits:
        add(5, "mod name popup wording", name_hits, name)

    return score, evidence


def scan_mod_for_issue(
    mod_dir: Path,
    summary: Dict[str, Any],
    args: Dict[str, Any],
    terms: List[str],
    location_terms: List[str],
    object_terms: List[str],
    popup_terms: List[str],
    profile: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    max_files = int(args.get("max_files_per_mod", 3000))
    max_text_bytes = int(args.get("max_text_bytes", 12000))
    max_plugin_bytes = int(args.get("max_plugin_bytes", 5_000_000))
    max_plugin_strings = int(args.get("max_plugin_strings", 2500))
    max_evidence = int(args.get("max_evidence_per_mod", 10))
    scan_mode = issue_scan_mode(args)
    path_scan_enabled = scan_mode in {"balanced", "deep"}
    deep_scan_files = scan_mode == "deep"
    balanced_text_limit = max(0, int(args.get("balanced_text_files_per_mod", 8)))
    evidence: List[Dict[str, Any]] = []
    matched: set[str] = set()
    score = 0
    plugin_location_hit = False
    plugin_object_hit = False
    popup_text_hit = False
    file_path_score = 0
    balanced_text_count = 0
    popup_text = str(args.get("popup_text") or "").strip()
    issue_kind = infer_issue_kind(args, terms)
    natural_popup = natural_language_popup_mode(args, terms)
    popup_capability_score = 0

    def note_exact_popup(source: str, text: str) -> None:
        nonlocal popup_text_hit, score
        if not popup_text or popup_text.lower() not in text.lower():
            return
        popup_text_hit = True
        score += 25
        if len(evidence) < max_evidence:
            evidence.append(
                {
                    "source": source,
                    "matchedTerms": ["exact popup text"],
                    "preview": exact_text_excerpt(text, popup_text),
                }
            )

    def score_hits(source: str, text: str, search_terms: Iterable[str], weight: int) -> List[str]:
        nonlocal score
        note_exact_popup(source, text)
        hits = add_issue_evidence(evidence, matched, source, text, search_terms, max_evidence)
        if hits:
            score += weight * len(hits)
        return hits

    score_hits("mod name", str(summary.get("name") or mod_dir.name), terms, 2)
    for plugin in summary.get("plugins", []):
        score_hits(f"plugin filename: {plugin}", plugin, terms, 3)
    for readme in summary.get("readmes", []):
        path = mod_dir / readme
        if path.exists():
            score_hits(f"readme: {readme}", read_file_head(path, max_text_bytes), terms, 3)

    if natural_popup:
        capability_score, capability_evidence = popup_capability_evidence(summary, max_evidence - len(evidence))
        if capability_score:
            popup_capability_score = capability_score
            score += capability_score
            for item in capability_evidence:
                evidence.append(item)
                matched.update(item.get("matchedTerms", []))

    scanned_files = int(summary.get("fileCount", 0) or 0)
    scanned_plugins = 0
    for plugin in summary.get("plugins", []):
        plugin_path = mod_dir / plugin
        if not plugin_path.exists():
            continue
        scanned_plugins += 1
        strings = extract_plugin_strings(plugin_path, max_plugin_bytes, max_plugin_strings)
        for text in strings:
            hits = score_hits(f"plugin strings: {plugin}", text, terms, 4)
            if hits:
                loc_hits = matched_issue_terms(text, location_terms)
                obj_hits = matched_issue_terms(text, object_terms)
                pop_hits = matched_issue_terms(text, popup_terms)
                plugin_location_hit = plugin_location_hit or bool(loc_hits)
                plugin_object_hit = plugin_object_hit or bool(obj_hits)
                if loc_hits and obj_hits:
                    score += 18
                elif loc_hits:
                    score += 6
                elif obj_hits:
                    score += 4
                if pop_hits:
                    score += 8

    file_rels = list(summary.get("files", []) or [])
    if not file_rels and path_scan_enabled:
        file_rels = [rel_to(file_path, mod_dir) for file_path in safe_walk(mod_dir, max_files)]
    text_scan_rels: List[str] = []
    if path_scan_enabled:
        for rel in file_rels[:max_files]:
            kind = classify_file(rel)
            if kind in PATH_SCAN_KINDS or natural_popup:
                path_hits = score_hits(f"file path: {rel}", rel, terms, 1)
                if meaningful_issue_hits(path_hits, issue_kind):
                    bonus = 3 if kind in {"interface", "script", "skse_plugin"} else 1
                    score += bonus
                    file_path_score += len(path_hits) + bonus
                    if Path(rel).suffix.lower() in ISSUE_TEXT_SUFFIXES and kind != "plugin":
                        text_scan_rels.append(rel)
            if (
                scan_mode == "balanced"
                and len(text_scan_rels) < balanced_text_limit
                and Path(rel).suffix.lower() in ISSUE_TEXT_SUFFIXES
                and kind in {"config", "fomod"}
            ):
                text_scan_rels.append(rel)

        if deep_scan_files:
            text_scan_rels = [
                rel for rel in file_rels[:max_files] if Path(rel).suffix.lower() in ISSUE_TEXT_SUFFIXES and classify_file(rel) != "plugin"
            ]
        else:
            text_scan_rels = list(dict.fromkeys(text_scan_rels))[:balanced_text_limit]
        for rel in text_scan_rels:
            text = read_file_head(mod_dir / rel, max_text_bytes)
            if text:
                balanced_text_count += 1
                score_hits(f"text/config file: {rel}", text, terms, 2)

    if score <= 0:
        return None

    knowledge = infer_mod_knowledge(summary)
    confidence = "low"
    if plugin_location_hit and plugin_object_hit:
        confidence = "high"
    elif popup_text_hit:
        confidence = "high"
    elif score >= 18 and (summary.get("plugins") or summary.get("sksePlugins")):
        confidence = "medium"
    elif score >= 10:
        confidence = "medium"

    if issue_kind == "popup":
        if natural_popup:
            likely_reason = "This mod has UI/script/MCM-style evidence matching the natural-language popup request. Exact popup text is not required for this first pass; check MCM/settings first, then test in a cloned profile."
        else:
            likely_reason = "This mod has UI/script/plugin evidence matching the popup description. Check MCM/settings first, then test in a cloned profile."
    elif plugin_location_hit and plugin_object_hit:
        likely_reason = "This mod has plugin string evidence for both the location and object/problem terms. Inspect this plugin in xEdit first."
    elif plugin_location_hit:
        likely_reason = "This mod references the reported location. It is a candidate for xEdit cell inspection."
    elif plugin_object_hit:
        likely_reason = "This mod references the reported object/problem terms. It is a candidate, but the location match is weaker."
    else:
        likely_reason = "This mod matched the issue terms in filenames, readmes, or metadata. Treat it as a weak candidate until confirmed."

    return {
        "mod": summary.get("name") or mod_dir.name,
        "path": str(mod_dir),
        "score": score,
        "confidence": confidence,
        "matchedTerms": sorted(matched),
        "enabledInSelectedProfile": profile.get("enabled") if isinstance(profile, dict) else None,
        "vortexModId": profile.get("id") if isinstance(profile, dict) else None,
        "role": knowledge.get("role"),
        "categories": knowledge.get("categories"),
        "removalRisk": knowledge.get("removalRisk"),
        "plugins": summary.get("plugins", []),
        "sksePlugins": summary.get("sksePlugins", []),
        "evidence": evidence,
        "likelyReason": likely_reason,
        "scannedFilesApprox": scanned_files,
        "scannedPathCount": len(file_rels[:max_files]) if path_scan_enabled else 0,
        "scannedPluginCount": scanned_plugins,
        "balancedTextFileCount": balanced_text_count,
        "scanMode": scan_mode,
        "deepScanFiles": deep_scan_files,
        "popupEvidenceMode": "natural_language" if natural_popup else "exact_text" if popup_text else None,
        "popupCapabilityScore": popup_capability_score,
        "filePathScore": file_path_score,
    }


def issue_diagnostic_quality(issue_kind: str, candidates: List[Dict[str, Any]], popup_text: str, form_id: str, timed_out: bool) -> Dict[str, Any]:
    if timed_out:
        return {
            "level": "partial",
            "reason": "The scan hit its time budget before every mod was checked.",
            "missingEvidence": ["more scan time"],
        }
    if not candidates:
        missing = ["deep scan"]
        if issue_kind == "popup" and not popup_text:
            missing.append("screenshot/OCR or exact popup text")
        if issue_kind == "placed_object" and not form_id:
            missing.append("console-clicked FormID")
        return {"level": "weak", "reason": "No candidate mods matched the first scan.", "missingEvidence": missing}
    top = candidates[0]
    confidence = str(top.get("confidence") or "low")
    if confidence == "high":
        return {"level": "strong", "reason": "The top candidate has high-confidence local evidence.", "missingEvidence": []}
    if confidence == "medium":
        missing = []
        if issue_kind == "popup" and not popup_text:
            missing.append("screenshot/OCR or exact popup text")
        if issue_kind == "placed_object" and not form_id:
            missing.append("console-clicked FormID")
        return {"level": "medium", "reason": "The top candidate has useful but not definitive local evidence.", "missingEvidence": missing}
    return {
        "level": "weak",
        "reason": "Only weak filename/readme/path evidence was found.",
        "missingEvidence": ["deep scan", "stronger in-game evidence"],
    }


def issue_next_best_inputs(issue_kind: str, popup_text: str, form_id: str, candidates: List[Dict[str, Any]]) -> List[str]:
    inputs: List[str] = []
    if issue_kind == "popup" and not popup_text:
        inputs.append("A screenshot/OCR or exact popup text, if the first candidates are weak.")
        inputs.append("When the popup appears: main menu, load save, combat, sleep, fast travel, MCM, or startup.")
    if issue_kind == "placed_object" and not form_id:
        inputs.append("Open the console, click the object, and provide the reference/base FormID and object name.")
    if not candidates:
        inputs.append("Run again with scan_mode=deep or deep_scan_files=true for a slower text/config pass.")
    elif str(candidates[0].get("confidence")) != "high":
        inputs.append("Run a cloned-profile disable test for one candidate at a time after making a profile backup.")
    return inputs


def compact_preview(text: Any, limit: int = 140) -> str:
    preview = re.sub(r"\s+", " ", str(text or "")).strip()
    return preview[: limit - 3] + "..." if len(preview) > limit else preview


def compact_evidence_items(items: Any, max_items: int = 3) -> List[Dict[str, Any]]:
    compacted: List[Dict[str, Any]] = []
    if not isinstance(items, list):
        return compacted
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        compacted.append(
            {
                "source": item.get("source"),
                "matchedTerms": list(item.get("matchedTerms", []))[:8]
                if isinstance(item.get("matchedTerms"), list)
                else item.get("matchedTerms"),
                "preview": compact_preview(item.get("preview")),
            }
        )
    return compacted


def compact_candidate(candidate: Dict[str, Any], max_evidence: int = 3) -> Dict[str, Any]:
    return {
        "mod": candidate.get("mod"),
        "confidence": candidate.get("confidence"),
        "score": candidate.get("score"),
        "vortexModId": candidate.get("vortexModId"),
        "enabledInSelectedProfile": candidate.get("enabledInSelectedProfile"),
        "role": candidate.get("role"),
        "categories": list(candidate.get("categories", []))[:5] if isinstance(candidate.get("categories"), list) else candidate.get("categories"),
        "removalRisk": candidate.get("removalRisk"),
        "matchedTerms": list(candidate.get("matchedTerms", []))[:12]
        if isinstance(candidate.get("matchedTerms"), list)
        else candidate.get("matchedTerms"),
        "likelyReason": candidate.get("likelyReason"),
        "plugins": list(candidate.get("plugins", []))[:5] if isinstance(candidate.get("plugins"), list) else candidate.get("plugins"),
        "evidence": compact_evidence_items(candidate.get("evidence"), max_evidence),
        "evidenceCount": len(candidate.get("evidence", [])) if isinstance(candidate.get("evidence"), list) else 0,
        "scanMode": candidate.get("scanMode"),
        "popupEvidenceMode": candidate.get("popupEvidenceMode"),
        "scannedPathCount": candidate.get("scannedPathCount"),
        "balancedTextFileCount": candidate.get("balancedTextFileCount"),
    }


def compact_issue_report(report: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
    max_candidates = max(0, min(int(args.get("max_candidates", 5)), 8))
    max_evidence = max(0, min(int(args.get("max_evidence_per_mod", 3)), 4))
    candidates = report.get("candidates", []) if isinstance(report.get("candidates"), list) else []
    compacted = {
        "issue": report.get("issue"),
        "formIdHint": report.get("formIdHint"),
        "searchedTerms": report.get("searchedTerms"),
        "profileState": report.get("profileState"),
        "scannedModCount": report.get("scannedModCount"),
        "availableModCount": report.get("availableModCount"),
        "scan": report.get("scan"),
        "diagnosticQuality": report.get("diagnosticQuality"),
        "nextBestInputs": report.get("nextBestInputs"),
        "candidateCount": report.get("candidateCount"),
        "candidates": [compact_candidate(item, max_evidence) for item in candidates[:max_candidates] if isinstance(item, dict)],
        "truncated": bool(report.get("truncated")) or len(candidates) > max_candidates,
        "recommendedActions": list(report.get("recommendedActions", []))[:8]
        if isinstance(report.get("recommendedActions"), list)
        else report.get("recommendedActions"),
        "notes": list(report.get("notes", []))[:4] if isinstance(report.get("notes"), list) else report.get("notes"),
        "performanceMode": normalized_performance_mode(args),
        "responseMode": "compact",
    }
    return compacted


def compact_play_report(report: Dict[str, Any], max_findings: int = 8) -> Dict[str, Any]:
    findings = report.get("findings", []) if isinstance(report.get("findings"), list) else []
    return {
        "summary": report.get("summary"),
        "findings": findings[:max_findings],
        "recommendedActions": list(report.get("recommendedActions", []))[:max_findings]
        if isinstance(report.get("recommendedActions"), list)
        else report.get("recommendedActions"),
        "notes": report.get("notes"),
        "responseMode": "compact",
    }


def in_game_issue_report(args: Dict[str, Any]) -> Dict[str, Any]:
    args = apply_performance_defaults(args)
    _vortex_appdata, _skyrim_dir, staging_dir, _my_games = get_context_paths(args)
    if not staging_dir or not staging_dir.exists():
        raise ToolError("Vortex staging folder was not found. Pass staging_dir explicitly.")

    description = str(args.get("description") or "").strip()
    location = str(args.get("location") or "").strip()
    problem_object = str(args.get("object") or "").strip()
    popup_text = str(args.get("popup_text") or "").strip()
    form_id = str(args.get("form_id") or "").strip()
    cell = str(args.get("cell") or "").strip()
    base_object = str(args.get("base_object") or "").strip()
    terms = tokenize_issue_terms(description, location, problem_object, popup_text, cell, base_object, args.get("extra_terms"))
    if not terms and popup_text:
        terms = [popup_text.lower()]
    elif not terms and form_id:
        terms = [normalize_form_id(form_id) or form_id]
    elif not terms and infer_issue_kind(args, terms) == "popup":
        terms = sorted(POPUP_SUPPORT_TERMS | {"popup"})
    if not terms:
        raise ToolError("Pass description, location, object, popup_text, or extra_terms so the tool has something to search for.")
    location_terms = tokenize_issue_terms(location)
    object_terms = tokenize_issue_terms(problem_object, base_object)
    popup_terms = tokenize_issue_terms(popup_text, description if infer_issue_kind(args, terms) == "popup" else "")
    issue_kind = infer_issue_kind(args, terms)
    scan_mode = issue_scan_mode(args)
    timeout_seconds = max(1, int(args.get("timeout_seconds", 60)))
    deadline = time.perf_counter() + timeout_seconds

    max_mods = int(args.get("max_mods", 500))
    max_candidates = int(args.get("max_candidates", 20))
    profile_lookup = profile_lookup_for_staging(args, staging_dir)
    mods_by_path = profile_lookup.get("modsByPath", {}) if isinstance(profile_lookup.get("modsByPath"), dict) else {}
    profile_state_summary = {
        "available": bool(profile_lookup.get("available")),
        "profile": profile_lookup.get("profile"),
        "error": profile_lookup.get("error"),
        "mappedModCount": len(mods_by_path),
    }

    candidates: List[Dict[str, Any]] = []
    mod_dirs = [p for p in sorted(staging_dir.iterdir(), key=lambda p: p.name.lower()) if p.is_dir()][:max_mods]
    scan_cache = load_scan_cache(args) if scan_cache_enabled(args) else {}
    timed_out = False
    scanned_mod_count = 0
    for mod_dir in mod_dirs:
        if time.perf_counter() >= deadline:
            timed_out = True
            break
        scanned_mod_count += 1
        summary = mod_summary_cached(
            mod_dir,
            include_files=scan_mode in {"balanced", "deep"},
            max_files=int(args.get("max_files_per_mod", 3000)),
            args=args,
            cache=scan_cache,
        )
        try:
            key = str(mod_dir.resolve()).lower()
        except OSError:
            key = str(mod_dir).lower()
        profile = mods_by_path.get(key)
        candidate = scan_mod_for_issue(
            mod_dir,
            summary,
            args,
            terms,
            location_terms,
            object_terms,
            popup_terms,
            profile if isinstance(profile, dict) else None,
        )
        if candidate:
            candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            {"high": 0, "medium": 1, "low": 2}.get(str(item.get("confidence")), 3),
            -int(item.get("score", 0)),
            str(item.get("mod", "")).lower(),
        )
    )
    if scan_cache_enabled(args):
        write_scan_cache(args, scan_cache)

    recommended_actions = [
        "Do not delete the candidate mod. Create or use a cloned Vortex profile and test disabling one candidate at a time.",
        "If this is a placed object, open Skyrim's console, click the object, and give OpenClaw the shown reference/base FormID and object name.",
        "If the first two hex digits of a FormID identify a plugin in your load order, inspect that plugin first.",
        "Use xEdit/SSEEdit to inspect the reported cell or quest/message records before applying any fix.",
    ]
    if issue_kind == "popup":
        if popup_text:
            recommended_actions.insert(1, "Use the exact popup text result first; it is the strongest popup evidence this tool can read.")
        else:
            recommended_actions.insert(1, "The first scan is balanced: it checks names, plugins, readmes, useful file paths, and a small number of config/text files. No exact popup text is required.")
        recommended_actions.append("Check the candidate mod's MCM/settings before disabling it, because many popups are configurable notifications.")
    if timed_out:
        recommended_actions.insert(0, "The scan hit its time budget and returned partial results. Increase timeout_seconds or lower max_mods if needed.")
    if not candidates:
        recommended_actions.insert(0, "No candidates were found in the first scan. Rerun with scan_mode=deep or deep_scan_files=true for a slower pass.")
    diagnostic_quality = issue_diagnostic_quality(issue_kind, candidates, popup_text, form_id, timed_out)

    result = {
        "issue": {
            "kind": issue_kind,
            "description": description,
            "location": location,
            "object": problem_object,
            "cell": cell,
            "baseObject": base_object,
            "formId": normalize_form_id(form_id),
            "popupTextProvided": bool(popup_text),
            "popupTextRequired": False,
            "naturalLanguagePopup": issue_kind == "popup" and not bool(popup_text),
        },
        "formIdHint": form_id_load_order_hint(args, form_id),
        "staging_dir": str(staging_dir),
        "searchedTerms": terms,
        "profileState": profile_state_summary,
        "scannedModCount": scanned_mod_count,
        "availableModCount": len(mod_dirs),
        "scan": {
            "mode": scan_mode,
            "defaultMode": "balanced",
            "timedOut": timed_out,
            "timeoutSeconds": timeout_seconds,
            "firstScanIncludes": [
                "mod names",
                "plugin filenames",
                "readmes",
                "plugin strings",
                "important file paths",
                "limited config/text files",
                "Vortex profile state when available",
            ],
            "deepScanHint": "Use scan_mode=deep or deep_scan_files=true to read more text/config files if the first scan is weak.",
        },
        "diagnosticQuality": diagnostic_quality,
        "nextBestInputs": issue_next_best_inputs(issue_kind, popup_text, form_id, candidates),
        "candidateCount": len(candidates),
        "candidates": candidates[:max_candidates],
        "truncated": len(candidates) > max_candidates,
        "recommendedActions": recommended_actions,
        "skyrimLiveMcp": {
            "canSeeGameDirectly": False,
            "why": "This MCP reads local files and Vortex state. It cannot see the live 3D scene or popups unless another bridge provides screenshots, OCR text, console FormIDs, or SKSE telemetry.",
            "futureBridgeNeeds": [
                "Screenshot/OCR input for popup text and visible UI.",
                "SKSE plugin or console-log bridge for current cell, clicked reference FormID, base object, and active message/menu events.",
                "A safe xEdit/SSEEdit integration for read-only cell and record lookup before any fix is attempted.",
            ],
        },
        "notes": [
            "This is a heuristic read-only triage. High-confidence candidates still need confirmation in xEdit or a cloned-profile test.",
            "For misplaced objects, exact FormID evidence is much stronger than a natural-language description.",
            "For popups, saying 'popup', 'notification', 'warning', 'MCM message', or similar is enough for the first scan; exact text is optional evidence for a stronger second pass.",
        ],
    }
    if compact_response_requested(args):
        return compact_issue_report(result, args)
    return result


def knowledge_removal_candidates(
    rows: List[Dict[str, Any]],
    redundancy: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    by_name = {str(row["summary"]["name"]): row for row in rows}
    candidates: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()

    def add_candidate(mod_name: str, kind: str, confidence: str, reason: str, safer_action: str) -> None:
        key = (mod_name, kind)
        if key in seen:
            return
        seen.add(key)
        row = by_name.get(mod_name)
        profile = row.get("profile") if row else None
        candidates.append(
            {
                "mod": mod_name,
                "kind": kind,
                "confidence": confidence,
                "reason": reason,
                "saferAction": safer_action,
                "vortexModId": profile.get("id") if isinstance(profile, dict) else None,
            }
        )

    if redundancy:
        for item in redundancy.get("coveredMods", []):
            mod_name = str(item.get("possiblyRedundant") or "")
            if mod_name:
                basis = str(item.get("basis") or "file coverage")
                covered_by = str(item.get("coveredBy") or "another mod")
                confidence = "high" if "hash" in basis else "medium"
                add_candidate(
                    mod_name,
                    "covered duplicate",
                    confidence,
                    f"{basis}; files appear covered by {covered_by}.",
                    "Disable it in a cloned Vortex profile first. Delete/uninstall only after a successful test load.",
                )
        for plugin, mods in (redundancy.get("duplicatePlugins") or {}).items():
            for mod_name in mods:
                add_candidate(
                    str(mod_name),
                    "duplicate plugin name",
                    "medium",
                    f"Shares plugin filename {plugin} with: {', '.join(str(m) for m in mods if m != mod_name)}.",
                    "Keep only the intended variant after checking mod page instructions and load order.",
                )
        for nexus_id, mods in (redundancy.get("duplicateNexusIds") or {}).items():
            for mod_name in mods:
                add_candidate(
                    str(mod_name),
                    "same Nexus mod id",
                    "medium",
                    f"Shares Nexus mod id {nexus_id} with: {', '.join(str(m) for m in mods if m != mod_name)}.",
                    "Review whether these are main file/update/optional variants before disabling anything.",
                )

    for row in rows:
        name = str(row["summary"]["name"])
        knowledge = row["knowledge"]
        profile = row.get("profile")
        if knowledge.get("docsOnly"):
            add_candidate(
                name,
                "no recognized game files",
                "high",
                "No ESP/ESM/ESL, BSA, SKSE DLL, scripts, mesh, texture, interface, animation, or config files were detected.",
                "Likely safe to remove from the staging folder after confirming it is not an installer support folder.",
            )
        if isinstance(profile, dict) and profile.get("enabled") is False:
            add_candidate(
                name,
                "disabled in selected profile",
                "medium",
                "The selected Vortex profile records this mod as disabled.",
                "Leave it alone unless you need disk cleanup; disabled mods should not affect the current profile.",
            )

    candidates.sort(key=lambda item: ({"high": 0, "medium": 1, "low": 2}.get(str(item["confidence"]), 3), item["mod"].lower()))
    return candidates


def render_mod_knowledge_markdown(
    rows: List[Dict[str, Any]],
    args: Dict[str, Any],
    staging_dir: Path,
    output_path: Path,
    profile_lookup: Dict[str, Any],
    conflicts: Optional[Dict[str, Any]],
    redundancy: Optional[Dict[str, Any]],
    plugins: Optional[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
) -> str:
    max_detail_mods = int(args.get("max_detail_mods", 120))
    include_readmes = bool(args.get("include_readme_excerpts", True))
    category_counts: Dict[str, int] = {}
    high_risk = 0
    for row in rows:
        for category in row["knowledge"].get("categories", []):
            category_counts[category] = category_counts.get(category, 0) + 1
        if row["knowledge"].get("removalRisk") == "high":
            high_risk += 1

    lines = [
        "# Skyrim SE Mod Knowledge Report",
        "",
        f"- Generated: {iso_now()}",
        f"- Server: {SERVER_NAME} {SERVER_VERSION}",
        f"- Staging folder: `{staging_dir}`",
        f"- Output file: `{output_path}`",
        f"- Mods scanned: {len(rows)}",
        f"- Profile state: {'available' if profile_lookup.get('available') else 'not available'}",
    ]
    if profile_lookup.get("profile"):
        profile = profile_lookup["profile"]
        lines.append(f"- Selected profile: `{profile.get('name')}` (`{profile.get('id')}`)")
    if profile_lookup.get("error"):
        lines.append(f"- Profile note: {profile_lookup['error']}")
    lines.extend(
        [
            "",
            "## How This Report Knows Things",
            "",
            "This report is based on local evidence: staged files, plugin headers, FOMOD metadata, readme snippets, Vortex profile state when available, duplicate-file checks, conflict overlaps, and optional read-only Nexus metadata when configured.",
            "",
            "For a huge collection, use this as a map. OpenClaw should read the role, evidence, plugin masters, conflict notes, and removal review before suggesting changes.",
            "",
            "## Safe Removal Rule",
            "",
            "Do not delete mods just because they look unwanted. Clone the Vortex profile, disable candidate mods there, deploy, launch with SKSE, and test the save. Delete/uninstall only after the cloned-profile test works.",
            "",
            "## Collection Layers",
            "",
            "- Runtime layer: SKSE DLL plugins and SKSE scripts. Highest compatibility risk.",
            "- Load-order layer: ESP/ESM/ESL plugins and BSA archives. Masters and plugin order matter.",
            "- Script/gameplay layer: Papyrus scripts, quests, AI, perks, MCM systems. Removing mid-save can break saves.",
            "- Interface layer: SkyUI/MCM/SWF files. Conflicts can hide menus or controls.",
            "- Visual layer: meshes, textures, sounds, models. Usually easier to disable, but skeleton/body mods still matter.",
            "- Patch layer: compatibility patches/add-ons. Usually depend on other mods staying installed.",
            "",
            "## Summary",
            "",
            f"- High removal-risk mods: {high_risk}",
            f"- Conflict rows: {conflicts.get('conflictCount') if conflicts else 'not scanned'}",
            f"- Redundancy candidates: {len(candidates)}",
            "",
            "| Category | Mods |",
            "|---|---:|",
        ]
    )
    for category, count in sorted(category_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {md_cell(category)} | {count} |")

    lines.extend(["", "## Removal Review Shortlist", ""])
    if candidates:
        lines.extend(["| Mod | Evidence | Confidence | Safer action |", "|---|---|---|---|"])
        for item in candidates[: int(args.get("max_removal_candidates", 80))]:
            action = item["saferAction"]
            if item.get("vortexModId"):
                action += f" Vortex mod id: `{item['vortexModId']}`."
            lines.append(
                f"| {md_cell(item['mod'])} | {md_cell(item['kind'] + ': ' + item['reason'])} | {md_cell(item['confidence'])} | {md_cell(action)} |"
            )
    else:
        lines.append("No strong removal candidates were found from local evidence. Use the mod index to choose unwanted cosmetic/content mods manually.")

    lines.extend(["", "## Mod Index", ""])
    lines.extend(["| Mod | Role | Active | Plugins | Risk | Conflicts | Evidence |", "|---|---|---|---:|---|---:|---|"])
    for row in rows:
        summary = row["summary"]
        knowledge = row["knowledge"]
        profile = row.get("profile")
        active = "unknown"
        if isinstance(profile, dict):
            active = "yes" if profile.get("enabled") else "no"
        evidence = ", ".join(knowledge.get("categories", []))
        lines.append(
            "| "
            + " | ".join(
                [
                    md_cell(summary.get("name")),
                    md_cell(knowledge.get("role")),
                    md_cell(active),
                    md_cell(len(summary.get("plugins", []))),
                    md_cell(knowledge.get("removalRisk")),
                    md_cell(row.get("conflictCount", 0)),
                    md_cell(evidence),
                ]
            )
            + " |"
        )

    if conflicts:
        sensitive = [
            item
            for item in conflicts.get("conflicts", [])
            if item.get("kind") in {"script", "skse_plugin", "interface", "config", "plugin", "animation_tool"}
        ]
        lines.extend(["", "## Sensitive Conflict Examples", ""])
        if sensitive:
            for item in sensitive[:25]:
                providers = ", ".join(str(provider.get("mod")) for provider in item.get("providers", []))
                lines.append(f"- `{item.get('relativePath')}` ({item.get('kind')}): {providers}")
        else:
            lines.append("No sensitive conflict examples were found in the returned conflict window.")

    if plugins:
        missing_masters = plugins.get("missingMasters") or []
        lines.extend(["", "## Plugin Master Problems", ""])
        if missing_masters:
            for item in missing_masters[:50]:
                lines.append(f"- `{item.get('plugin')}` needs missing master `{item.get('missingMaster')}`.")
        else:
            lines.append("No missing masters were found in the scanned plugin headers.")

    lines.extend(["", "## Mod Details", ""])
    for index, row in enumerate(rows[:max_detail_mods], start=1):
        summary = row["summary"]
        knowledge = row["knowledge"]
        profile = row.get("profile")
        lines.extend(
            [
                f"### {index}. {summary.get('name')}",
                "",
                f"- Role: {knowledge.get('role')}",
                f"- Categories: {', '.join(knowledge.get('categories', []))}",
                f"- Removal risk: {knowledge.get('removalRisk')}",
                f"- Size/files: {format_bytes(summary.get('totalBytes'))}, {summary.get('fileCount')} files",
                f"- Staging path: `{summary.get('path')}`",
            ]
        )
        if isinstance(profile, dict):
            lines.append(f"- Vortex profile state: {'enabled' if profile.get('enabled') else 'disabled'}; id `{profile.get('id')}`")
            if profile.get("nexusModId"):
                lines.append(f"- Nexus ids: mod `{profile.get('nexusModId')}`, file `{profile.get('nexusFileId')}`")
        nexus = row.get("nexus") if isinstance(row.get("nexus"), dict) else {}
        if nexus.get("mod"):
            remote = nexus["mod"]
            lines.append(f"- Nexus metadata: `{remote.get('name')}` version `{remote.get('version')}`; {remote.get('url')}")
            if remote.get("summary"):
                lines.append(f"- Nexus summary: {remote.get('summary')}")
        elif nexus.get("error"):
            lines.append(f"- Nexus metadata: {nexus.get('error')}")
        if summary.get("plugins"):
            lines.append("- Plugins:")
            for rel, header in row.get("pluginHeaders", {}).items():
                masters = ", ".join(header.get("masters", [])) or "none"
                lines.append(f"  - `{Path(rel).name}` masters: {masters}")
        if summary.get("sksePlugins"):
            lines.append("- SKSE DLLs: " + ", ".join(f"`{Path(rel).name}`" for rel in summary.get("sksePlugins", [])[:8]))
        if row.get("conflictExamples"):
            lines.append("- Conflict examples:")
            for item in row["conflictExamples"][:5]:
                lines.append(f"  - `{item.get('relativePath')}` ({item.get('kind')}) with {', '.join(item.get('otherMods', []))}")
        if knowledge.get("purposeHints"):
            lines.extend(md_bullets(knowledge["purposeHints"]))
        if include_readmes and row.get("readmeExcerpts"):
            lines.append("- Readme evidence:")
            for excerpt in row["readmeExcerpts"]:
                lines.append(f"  - `{excerpt.get('relativePath')}`")
                for line in excerpt.get("lines", []):
                    lines.append(f"    - {line}")
        lines.append("")

    if len(rows) > max_detail_mods:
        lines.append(f"_Details truncated after {max_detail_mods} mods. Increase `max_detail_mods` if you need the full list._")

    return "\n".join(lines).rstrip() + "\n"


def mod_knowledge_report(args: Dict[str, Any]) -> Dict[str, Any]:
    _vortex_appdata, _skyrim_dir, staging_dir, _my_games = get_context_paths(args)
    if not staging_dir or not staging_dir.exists():
        raise ToolError("Vortex staging folder was not found. Pass staging_dir explicitly.")
    output_path = expand_path(args.get("output_path"))
    if not output_path:
        docs = default_documents() or Path.cwd()
        output_path = docs / f"vortex-skyrimse-mod-knowledge-{now_stamp()}.md"

    max_mods = int(args.get("max_mods", 500))
    max_files_per_mod = int(args.get("max_files_per_mod", 3000))
    include_readmes = bool(args.get("include_readme_excerpts", True))
    readme_lines = int(args.get("max_readme_lines", 4))
    readme_bytes = int(args.get("max_readme_bytes", 8000))
    redact_user_paths = bool(args.get("redact_user_paths", True))
    include_nexus_metadata = bool(args.get("include_nexus_metadata", False))
    nexus_lookup_limit = int(args.get("nexus_max_lookup_mods", args.get("max_nexus_lookup_mods", 40)))
    nexus_lookup_count = 0

    profile_lookup = profile_lookup_for_staging(args, staging_dir)
    profile_by_path = profile_lookup.get("modsByPath") if isinstance(profile_lookup.get("modsByPath"), dict) else {}

    conflicts = None
    mod_conflicts: Dict[str, Dict[str, Any]] = {}
    if bool(args.get("include_conflicts", True)):
        try:
            conflicts = analyze_conflicts(
                {
                    **args,
                    "max_files": int(args.get("conflict_max_files_per_mod", max_files_per_mod)),
                    "max_conflicts": int(args.get("max_conflicts", 500)),
                    "hash_files": bool(args.get("hash_files", False)),
                }
            )
            for item in conflicts.get("conflicts", []):
                providers = item.get("providers", [])
                provider_names = [str(provider.get("mod")) for provider in providers]
                for provider in providers:
                    mod_name = str(provider.get("mod"))
                    stats = mod_conflicts.setdefault(mod_name, {"count": 0, "examples": []})
                    stats["count"] += 1
                    if len(stats["examples"]) < 8:
                        stats["examples"].append(
                            {
                                "relativePath": item.get("relativePath"),
                                "kind": item.get("kind"),
                                "otherMods": [name for name in provider_names if name != mod_name],
                            }
                        )
        except Exception as exc:
            conflicts = {"error": str(exc), "conflicts": [], "conflictCount": "error"}

    redundancy = None
    if bool(args.get("include_redundancy", True)):
        try:
            redundancy = redundant_mod_report(
                {
                    **args,
                    "max_mods": max_mods,
                    "hash_files": bool(args.get("hash_files", False)),
                }
            )
        except Exception as exc:
            redundancy = {"error": str(exc), "coveredMods": [], "duplicatePlugins": {}, "duplicateNexusIds": {}}

    plugins = None
    if bool(args.get("include_plugin_report", True)):
        try:
            plugins = plugin_report(args)
        except Exception as exc:
            plugins = {"error": str(exc), "missingMasters": []}

    rows: List[Dict[str, Any]] = []
    mod_dirs = sorted([path for path in staging_dir.iterdir() if path.is_dir()], key=lambda path: path.name.lower())[:max_mods]
    scan_cache = load_scan_cache(args) if scan_cache_enabled(args) else {}
    for mod_dir in mod_dirs:
        summary = mod_summary_cached(mod_dir, include_files=False, max_files=max_files_per_mod, args=args, cache=scan_cache)
        plugin_headers = {}
        for rel in summary.get("plugins", []):
            plugin_path = mod_dir / rel
            if plugin_path.exists():
                plugin_headers[rel] = plugin_masters(plugin_path)
        try:
            profile_key = str(mod_dir.resolve()).lower()
        except OSError:
            profile_key = str(mod_dir).lower()
        knowledge = infer_mod_knowledge(summary)
        conflict_stats = mod_conflicts.get(summary["name"], {"count": 0, "examples": []})
        profile = profile_by_path.get(profile_key)
        row = {
            "summary": summary,
            "knowledge": knowledge,
            "pluginHeaders": plugin_headers,
            "profile": profile,
            "conflictCount": conflict_stats.get("count", 0),
            "conflictExamples": conflict_stats.get("examples", []),
            "readmeExcerpts": first_readme_lines(mod_dir, summary.get("readmes", []), readme_lines, readme_bytes)
            if include_readmes
            else [],
        }
        if include_nexus_metadata:
            ids = local_nexus_ids(summary, profile if isinstance(profile, dict) else None)
            if ids.get("modId") and nexus_lookup_count < nexus_lookup_limit:
                lookup = nexus_mod_lookup({**args, "mod_id": ids["modId"]})
                nexus_lookup_count += 1
                if lookup.get("available"):
                    row["nexus"] = {
                        "mod": lookup.get("mod"),
                        "modId": ids.get("modId"),
                        "fileId": ids.get("fileId"),
                        "cacheHit": lookup.get("cacheHit", False),
                    }
                else:
                    row["nexus"] = {"modId": ids.get("modId"), "fileId": ids.get("fileId"), "error": lookup.get("error")}
            elif ids.get("modId"):
                row["nexus"] = {"modId": ids.get("modId"), "fileId": ids.get("fileId"), "error": "Nexus lookup limit reached."}
            else:
                row["nexus"] = {"error": "No Nexus mod id found in local/Vortex metadata."}
        rows.append(row)

    if scan_cache_enabled(args):
        write_scan_cache(args, scan_cache)

    candidates = knowledge_removal_candidates(rows, redundancy)
    markdown = render_mod_knowledge_markdown(
        rows,
        args,
        staging_dir,
        output_path,
        profile_lookup,
        conflicts,
        redundancy,
        plugins,
        candidates,
    )
    if redact_user_paths:
        markdown = redact_text(markdown)
    write_text(output_path, markdown)
    return {
        "output_path": str(output_path),
        "staging_dir": str(staging_dir),
        "modCount": len(rows),
        "profileStateAvailable": bool(profile_lookup.get("available")),
        "profileStateError": profile_lookup.get("error"),
        "removalCandidateCount": len(candidates),
        "conflictCount": conflicts.get("conflictCount") if isinstance(conflicts, dict) else None,
        "nexusMetadataIncluded": include_nexus_metadata,
        "nexusLookupCount": nexus_lookup_count,
        "redactedUserPaths": redact_user_paths,
        "notes": [
            "The Markdown report is evidence-based and read-only.",
            "Disable candidate mods in a cloned profile before uninstalling or deleting anything.",
            "The tool infers purpose from local files and metadata; optional Nexus metadata is read-only and cached.",
        ],
    }


INI_RECOMMENDATIONS = [
    {
        "file": "SkyrimCustom.ini",
        "section": "Archive",
        "key": "bInvalidateOlderFiles",
        "value": "1",
        "reason": "Allows loose files deployed by mod managers to override archived game assets.",
    },
    {
        "file": "SkyrimCustom.ini",
        "section": "Archive",
        "key": "sResourceDataDirsFinal",
        "value": "",
        "reason": "Common Skyrim SE loose-file setting used with bInvalidateOlderFiles.",
    },
    {
        "file": "SkyrimPrefs.ini",
        "section": "Launcher",
        "key": "bEnableFileSelection",
        "value": "1",
        "reason": "Keeps plugin selection enabled for older launcher/plugin workflows.",
    },
]


def read_ini_value(path: Path, section: str, key: str) -> Optional[str]:
    if not path.exists():
        return None
    parser = configparser.ConfigParser(strict=False)
    parser.optionxform = str  # type: ignore
    try:
        parser.read_string(read_text(path, 2_000_000))
        for actual_section in parser.sections():
            if actual_section.lower() == section.lower():
                for actual_key, value in parser.items(actual_section):
                    if actual_key.lower() == key.lower():
                        return value
    except Exception:
        return None
    return None


def ini_report(args: Dict[str, Any]) -> Dict[str, Any]:
    my_games = default_my_games_dir(args.get("my_games_dir"))
    if not my_games:
        raise ToolError("My Games Skyrim folder was not found. Pass my_games_dir explicitly.")
    recommendations = []
    for rec in INI_RECOMMENDATIONS:
        path = my_games / rec["file"]
        current = read_ini_value(path, rec["section"], rec["key"])
        ok = current == rec["value"]
        recommendations.append({**rec, "path": str(path), "current": current, "ok": ok})
    return {"my_games_dir": str(my_games), "recommendations": recommendations}


def set_ini_value_text(text: str, section: str, key: str, value: str) -> str:
    lines = text.splitlines()
    section_re = re.compile(r"^\s*\[(.+?)\]\s*$")
    key_re = re.compile(rf"^\s*{re.escape(key)}\s*=", re.IGNORECASE)
    in_section = False
    found_section = False
    changed = False
    output: List[str] = []

    for line in lines:
        match = section_re.match(line)
        if match:
            if in_section and not changed:
                output.append(f"{key}={value}")
                changed = True
            in_section = match.group(1).lower() == section.lower()
            found_section = found_section or in_section
            output.append(line)
            continue
        if in_section and key_re.match(line):
            output.append(f"{key}={value}")
            changed = True
        else:
            output.append(line)

    if not found_section:
        if output and output[-1].strip():
            output.append("")
        output.extend([f"[{section}]", f"{key}={value}"])
    elif in_section and not changed:
        output.append(f"{key}={value}")
    return "\n".join(output) + "\n"


def apply_ini_fixes(args: Dict[str, Any]) -> Dict[str, Any]:
    dry_run = bool(args.get("dry_run", True))
    make_backup = bool(args.get("make_backup", True))
    my_games = default_my_games_dir(args.get("my_games_dir"))
    if not my_games:
        raise ToolError("My Games Skyrim folder was not found. Pass my_games_dir explicitly.")
    changes = []
    for rec in INI_RECOMMENDATIONS:
        path = my_games / rec["file"]
        before = read_text(path, 2_000_000) if path.exists() else ""
        after = set_ini_value_text(before, rec["section"], rec["key"], rec["value"])
        current = read_ini_value(path, rec["section"], rec["key"])
        needs_change = current != rec["value"]
        backup_path = None
        if needs_change and not dry_run:
            if make_backup and path.exists():
                backup_path = path.with_suffix(path.suffix + f".bak-{now_stamp()}")
                shutil.copy2(path, backup_path)
            write_text(path, after)
        changes.append(
            {
                **rec,
                "path": str(path),
                "current": current,
                "changed": bool(needs_change and not dry_run),
                "wouldChange": bool(needs_change),
                "backup": str(backup_path) if backup_path else None,
            }
        )
    return {"dryRun": dry_run, "my_games_dir": str(my_games), "changes": changes}


def allowed_roots(args: Dict[str, Any]) -> List[Path]:
    vortex_appdata, skyrim_dir, staging_dir, my_games = get_context_paths(args)
    roots = [p for p in [vortex_appdata, skyrim_dir, staging_dir, my_games, default_local_appdata()] if p]
    extra = args.get("allowed_roots") or []
    for value in extra:
        path = expand_path(value)
        if path:
            roots.append(path)
    return roots


def read_text_file(args: Dict[str, Any]) -> Dict[str, Any]:
    path = expand_path(args.get("path"))
    if not path or not path.exists() or not path.is_file():
        raise ToolError("path must point to an existing file.")
    allow_any = bool(args.get("allow_any_path", False))
    roots = allowed_roots(args)
    if not allow_any and not any(is_under(path, root) for root in roots):
        raise ToolError("Refusing to read outside detected Vortex/Skyrim roots unless allow_any_path=true.")
    max_bytes = int(args.get("max_bytes", MAX_DEFAULT_TEXT_BYTES))
    return {
        "path": str(path),
        "bytesReadMax": max_bytes,
        "text": read_text(path, max_bytes),
        "truncated": path.stat().st_size > max_bytes,
    }


def path_allowed_for_text_tool(path: Path, args: Dict[str, Any], verb: str) -> None:
    allow_any = bool(args.get("allow_any_path", False))
    roots = allowed_roots(args)
    if not allow_any and not any(is_under(path, root) for root in roots):
        raise ToolError(f"Refusing to {verb} outside detected Vortex/Skyrim roots unless allow_any_path=true.")


CONFIGURED_FALSE_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?P<prefix>[\"']?(?:is[_-]?configured|configured)[\"']?\s*[:=]\s*)"
    r"(?P<value>false|0|no)\b",
    re.IGNORECASE,
)


def configured_false_matches(text: str) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    replacements = {"false": "true", "0": "1", "no": "yes"}
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith(("#", ";", "//")):
            continue
        for match in CONFIGURED_FALSE_RE.finditer(line):
            value = match.group("value")
            replacement = replacements.get(value.lower(), "true")
            old_text = match.group(0)
            new_text = f"{match.group('prefix')}{replacement}"
            matches.append(
                {
                    "line": line_number,
                    "oldText": old_text,
                    "newText": new_text,
                    "value": value,
                    "preview": compact_preview(line, 180),
                    "occurrencesInFile": text.count(old_text),
                }
            )
    return matches


def loose_key_value_entries(text: str, max_items: int = 80) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    invalid_lines: List[Dict[str, Any]] = []
    for line_number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith(("#", ";", "//", "[")):
            continue
        match = re.match(r"^\s*([^:=\s][^:=]{0,160}?)\s*[:=]\s*(.*?)\s*$", raw)
        if match:
            key = match.group(1).strip().strip("\"'")
            value = match.group(2).strip()
            entries.append(
                {
                    "line": line_number,
                    "key": compact_preview(key, 100),
                    "valuePreview": compact_preview(value, 160),
                }
            )
        else:
            invalid_lines.append({"line": line_number, "preview": compact_preview(raw, 160)})
        if len(entries) >= max_items:
            break
    return {
        "entries": entries,
        "invalidLines": invalid_lines[:20],
        "truncated": len(entries) >= max_items,
    }


def config_patch_suggestions(text: str) -> List[Dict[str, Any]]:
    suggestions: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()
    for match in configured_false_matches(text):
        key = (match["oldText"], match["newText"])
        if key in seen:
            continue
        seen.add(key)
        suggestions.append(
            {
                "kind": "configured_flag",
                "confidence": "medium",
                "line": match["line"],
                "oldText": match["oldText"],
                "newText": match["newText"],
                "occurrencesInFile": match["occurrencesInFile"],
                "reason": "The file has a configured/configured-like flag set to a false value.",
                "safeTool": "apply_config_text_patch",
                "safeDefaults": {"dry_run": True, "make_backup": True},
            }
        )
    return suggestions[:12]


def config_health_findings(text: str, suffix: str, valid: Optional[bool], error: Optional[str]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    stripped = text.strip()
    if not stripped:
        findings.append(
            {
                "severity": "high",
                "code": "empty_config",
                "message": "The config file is empty.",
                "nextAction": "Restore the mod config from backup/reinstall, or fill required settings from the mod instructions.",
            }
        )
    if valid is False:
        findings.append(
            {
                "severity": "high",
                "code": "config_parse_failed",
                "message": error or "The config file could not be parsed.",
                "nextAction": "Fix syntax first. Do not change gameplay mods until the config parses.",
            }
        )
    if suffix in CONFIG_PATCH_SUFFIXES and configured_false_matches(text):
        findings.append(
            {
                "severity": "medium",
                "code": "configured_flag_false",
                "message": "A configured/configured-like flag is set to false.",
                "nextAction": "Read the surrounding config instructions. If this should be enabled, patch exact text with a dry run first.",
            }
        )
    placeholder_patterns = (
        r"(?i)\bTODO\b",
        r"(?i)\bFIXME\b",
        r"(?i)\bCHANGEME\b",
        r"(?i)\bREPLACE_ME\b",
        r"(?i)\byour_[a-z0-9_]+_here\b",
        r"(?i)<(?:path|folder|directory|mod|plugin)>",
    )
    if any(re.search(pattern, text) for pattern in placeholder_patterns):
        findings.append(
            {
                "severity": "medium",
                "code": "placeholder_value_seen",
                "message": "The config appears to contain placeholder text.",
                "nextAction": "Replace placeholders only after checking the mod instructions or readme.",
            }
        )
    if suffix in {".json", ".toml", ".xml", ".ini"} and "\x00" in text:
        findings.append(
            {
                "severity": "high",
                "code": "binary_looking_config",
                "message": "The config contains NUL bytes and may not be a normal text config.",
                "nextAction": "Do not patch this as text unless you know the file format.",
            }
        )
    return findings


def parse_config_text(path: Path, text: str) -> Dict[str, Any]:
    suffix = path.suffix.lower()
    result: Dict[str, Any] = {"format": suffix.lstrip(".") or "unknown", "valid": None, "summary": {}, "error": None}
    try:
        if suffix == ".json":
            data = json.loads(text)
            result["valid"] = True
            if isinstance(data, dict):
                result["summary"] = {
                    "rootType": "object",
                    "topLevelKeyCount": len(data),
                    "topLevelKeys": list(data.keys())[:40],
                }
            elif isinstance(data, list):
                result["summary"] = {"rootType": "array", "itemCount": len(data)}
            else:
                result["summary"] = {"rootType": type(data).__name__}
        elif suffix == ".xml":
            import xml.etree.ElementTree as ET

            root = ET.fromstring(text)
            result["valid"] = True
            result["summary"] = {
                "rootTag": root.tag.split("}")[-1],
                "childCount": len(list(root)),
                "attributes": dict(list(root.attrib.items())[:20]),
            }
        elif suffix in {".ini", ".cfg", ".conf", ".properties"}:
            if suffix == ".properties" or not re.search(r"(?m)^\s*\[[^\]]+\]\s*$", text):
                loose = loose_key_value_entries(text)
                result["format"] = "loose-key-value"
                result["valid"] = bool(loose["entries"])
                result["error"] = None if loose["entries"] else "No section headers or loose key/value settings were found."
                result["summary"] = {
                    "keyValueCount": len(loose["entries"]),
                    "keys": [item["key"] for item in loose["entries"][:40]],
                    "invalidLineCount": len(loose["invalidLines"]),
                    "invalidLines": loose["invalidLines"],
                    "truncated": loose["truncated"],
                }
            else:
                parser = configparser.ConfigParser()
                parser.optionxform = str  # type: ignore
                parser.read_string(text)
                sections = parser.sections()
                result["valid"] = True
                result["summary"] = {
                    "sectionCount": len(sections),
                    "sections": sections[:40],
                    "sectionKeyCounts": {section: len(parser.items(section)) for section in sections[:20]},
                }
        elif suffix == ".toml":
            try:
                import tomllib  # type: ignore
            except ImportError:  # pragma: no cover - Python < 3.11 fallback
                result["valid"] = None
                result["summary"] = {"note": "TOML syntax was not parsed because Python 3.11+ tomllib is unavailable."}
                return result
            data = tomllib.loads(text)
            result["valid"] = True
            result["summary"] = {
                "rootType": "object",
                "topLevelKeyCount": len(data),
                "topLevelKeys": list(data.keys())[:40],
            }
        elif suffix in {".yaml", ".yml"}:
            result["valid"] = None
            result["summary"] = {"note": "YAML syntax is not parsed because this dependency-free MCP does not bundle a YAML parser."}
        else:
            result["valid"] = None
            result["summary"] = {"note": "This file is treated as plain text."}
    except ToolError:
        raise
    except Exception as exc:
        result["valid"] = False
        result["error"] = str(exc)
    return result


def config_file_report(args: Dict[str, Any]) -> Dict[str, Any]:
    path = expand_path(args.get("path"))
    if not path or not path.exists() or not path.is_file():
        raise ToolError("path must point to an existing file.")
    path_allowed_for_text_tool(path, args, "read config files")
    max_bytes = int(args.get("max_bytes", 2_000_000))
    text, encoding, truncated = read_text_with_encoding(path, max_bytes)
    if truncated:
        raise ToolError(f"Refusing to parse because the file is larger than max_bytes={max_bytes}.")
    parsed = parse_config_text(path, text)
    health = config_health_findings(text, path.suffix.lower(), parsed.get("valid"), parsed.get("error"))
    suggestions = config_patch_suggestions(text) if path.suffix.lower() in CONFIG_PATCH_SUFFIXES else []
    lines = text.splitlines()
    preview_lines = []
    for line in lines:
        clean = line.strip()
        if clean and not clean.startswith(("#", ";", "//")):
            preview_lines.append(compact_preview(clean, 180))
        if len(preview_lines) >= int(args.get("max_preview_lines", 8)):
            break
    return {
        "path": str(path),
        "name": path.name,
        "suffix": path.suffix.lower(),
        "sizeBytes": path.stat().st_size,
        "encoding": encoding,
        "lineCount": len(lines),
        "format": parsed.get("format"),
        "valid": parsed.get("valid"),
        "parseError": parsed.get("error"),
        "summary": parsed.get("summary"),
        "healthFindings": health,
        "healthFindingCount": len(health),
        "suggestedTextPatches": suggestions,
        "suggestedTextPatchCount": len(suggestions),
        "nonCommentPreview": preview_lines,
        "notes": [
            "This is read-only and does not patch the file.",
            "Use apply_config_text_patch only for exact old/new text after reviewing the relevant setting.",
        ],
    }


def apply_config_text_patch(args: Dict[str, Any]) -> Dict[str, Any]:
    path = expand_path(args.get("path"))
    if not path or not path.exists() or not path.is_file():
        raise ToolError("path must point to an existing file.")
    suffix = path.suffix.lower()
    if suffix not in CONFIG_PATCH_SUFFIXES:
        raise ToolError(
            f"Refusing to patch {suffix or 'extensionless'} files. Allowed config/text suffixes: {', '.join(sorted(CONFIG_PATCH_SUFFIXES))}."
        )
    path_allowed_for_text_tool(path, args, "patch")

    old_text = args.get("old_text")
    new_text = args.get("new_text")
    if not isinstance(old_text, str) or old_text == "":
        raise ToolError("old_text must be a non-empty string copied exactly from the target file.")
    if not isinstance(new_text, str):
        raise ToolError("new_text must be a string.")
    max_bytes = int(args.get("max_bytes", 2_000_000))
    text, encoding, truncated = read_text_with_encoding(path, max_bytes)
    if truncated:
        raise ToolError(f"Refusing to patch because the file is larger than max_bytes={max_bytes}.")
    count = text.count(old_text)
    if count == 0:
        raise ToolError("old_text was not found in the file. Reread the file before proposing a patch.")
    allow_multiple = bool(args.get("allow_multiple", False))
    if count > 1 and not allow_multiple:
        raise ToolError("old_text appears more than once. Pass allow_multiple=true only after confirming every occurrence should change.")

    apply_requested = bool(args.get("apply", False))
    dry_run = bool(args.get("dry_run", not apply_requested))
    make_backup = bool(args.get("make_backup", True))
    after = text.replace(old_text, new_text)
    backup_path = None
    changed = False
    if not dry_run:
        if make_backup:
            backup_path = path.with_suffix(path.suffix + f".bak-{now_stamp()}")
            shutil.copy2(path, backup_path)
        path.write_bytes(after.encode(encoding))
        changed = True
        log_event(
            "support",
            "config_text_patch_applied",
            {"path": str(path), "backup": str(backup_path) if backup_path else None, "occurrences": count},
        )

    return {
        "path": str(path),
        "dryRun": dry_run,
        "changed": changed,
        "wouldChange": text != after,
        "occurrences": count,
        "encoding": encoding,
        "backup": str(backup_path) if backup_path else None,
        "backupWillBeCreated": bool(make_backup and dry_run),
        "preview": {"old": compact_preview(old_text, 500), "new": compact_preview(new_text, 500)},
        "notes": [
            "This replaces exact text only; it does not understand plugin records or arbitrary scripts.",
            "Use dry_run first, keep the backup, then deploy/test in Vortex if the patched file is staged by a mod.",
        ],
    }


def runtime_log_kind(path: Path, my_games: Optional[Path], skyrim_dir: Optional[Path]) -> str:
    lower = str(path).lower()
    name = path.name.lower()
    if "netscriptframework" in lower or "crash" in lower or "trainwreck" in lower:
        return "crash"
    if "papyrus" in name or "\\logs\\script" in lower.replace("/", "\\"):
        return "papyrus"
    if "\\skse\\" in lower.replace("/", "\\") or "\\skse\\plugins" in lower.replace("/", "\\"):
        return "skse"
    if my_games and is_under(path, my_games):
        return "my_games_runtime"
    if skyrim_dir and is_under(path, skyrim_dir):
        return "skyrim_runtime"
    return "runtime"


def collect_skyrim_runtime_log_files(args: Dict[str, Any]) -> Dict[str, Any]:
    _vortex_appdata, skyrim_dir, _staging_dir, my_games = get_context_paths(args)
    candidates: List[Path] = []

    def add_glob(root: Optional[Path], pattern: str) -> None:
        if not root or not root.exists():
            return
        try:
            candidates.extend(path for path in root.glob(pattern) if path.is_file() and path.suffix.lower() in RUNTIME_LOG_SUFFIXES)
        except OSError:
            return

    if my_games:
        add_glob(my_games / "Logs" / "Script", "Papyrus*.log")
        add_glob(my_games / "Logs" / "Script", "*.log")
        add_glob(my_games / "SKSE", "*.log")
        add_glob(my_games / "SKSE", "*.txt")
        add_glob(my_games / "Logs", "*.log")
        add_glob(my_games / "Logs", "*.txt")
    if skyrim_dir:
        add_glob(skyrim_dir, "*.log")
        add_glob(skyrim_dir, "*.txt")
        add_glob(skyrim_dir / "Data" / "SKSE" / "Plugins", "*.log")
        add_glob(skyrim_dir / "Data" / "SKSE" / "Plugins", "*.txt")
        add_glob(skyrim_dir / "Data" / "NetScriptFramework" / "Crash", "*.txt")
        add_glob(skyrim_dir / "Data" / "NetScriptFramework" / "Crash", "*.log")

    seen: set[str] = set()
    files: List[Path] = []
    for path in candidates:
        try:
            key = str(path.resolve()).lower()
        except OSError:
            key = str(path).lower()
        if key not in seen:
            seen.add(key)
            files.append(path)
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return {"files": files, "myGamesDir": my_games, "skyrimDir": skyrim_dir}


def clean_runtime_reference(raw: str) -> str:
    value = raw.strip().strip("'\"`[](){}<>,;:")
    value = re.sub(r"^(?:file|plugin|script|config|path|setting)\s+", "", value, flags=re.IGNORECASE).strip()
    return value.replace("\\\\", "\\")


def extract_runtime_references(text: str, max_refs: int = 12) -> List[str]:
    refs: List[str] = []
    seen: set[str] = set()
    for match in RUNTIME_REFERENCE_RE.finditer(text):
        ref = clean_runtime_reference(match.group(1))
        key = ref.lower().replace("\\", "/")
        if ref and key not in seen:
            seen.add(key)
            refs.append(ref)
            if len(refs) >= max_refs:
                break
    return refs


def runtime_reference_keys(ref: str) -> Tuple[str, str]:
    normalized = clean_runtime_reference(ref).lower().replace("\\", "/").strip("/")
    name = Path(normalized).name
    return normalized, name


def runtime_line_terms(line: str, problem_terms: Iterable[str]) -> List[str]:
    lower = line.lower()
    hits = [term for term in sorted(RUNTIME_LOG_ERROR_TERMS) if term in lower]
    hits.extend(term for term in problem_terms if term and term in lower and term not in hits)
    return hits


def runtime_line_severity(line: str, kind: str) -> str:
    lower = line.lower()
    if any(term in lower for term in ("access violation", "fatal", "unhandled exception", "stack overflow")):
        return "critical"
    if kind == "crash" and any(term in lower for term in ("crash", "exception", "error")):
        return "critical"
    if "address library" in lower or ("dll" in lower and any(term in lower for term in ("failed", "missing", "not found", "could not"))):
        return "high"
    if any(term in lower for term in ("error", "failed", "could not", "cannot", "missing", "not found", "not configured")):
        return "medium"
    if "warning" in lower:
        return "low"
    return "info"


def build_staged_file_index(staging_dir: Path, args: Dict[str, Any]) -> Dict[str, Any]:
    max_mods = int(args.get("max_mods", 500))
    max_files_per_mod = int(args.get("max_files_per_mod", 3000))
    max_index_files = int(args.get("max_runtime_index_files", 60_000))
    by_name: Dict[str, List[Dict[str, Any]]] = {}
    by_rel: Dict[str, List[Dict[str, Any]]] = {}
    configs_by_mod: Dict[str, List[Dict[str, Any]]] = {}
    total_files = 0
    truncated = False
    mod_dirs = [p for p in sorted(staging_dir.iterdir(), key=lambda item: item.name.lower()) if p.is_dir()][:max_mods]
    for mod_dir in mod_dirs:
        for file_path in safe_walk(mod_dir, max_files_per_mod):
            if total_files >= max_index_files:
                truncated = True
                break
            rel = rel_to(file_path, mod_dir)
            kind = classify_file(rel)
            suffix = Path(rel).suffix.lower()
            total_files += 1
            entry = {
                "mod": mod_dir.name,
                "path": str(file_path),
                "relativePath": rel,
                "kind": kind,
                "suffix": suffix,
            }
            rel_key = rel.lower().replace("\\", "/")
            by_rel.setdefault(rel_key, []).append(entry)
            by_name.setdefault(Path(rel_key).name, []).append(entry)
            if kind == "config" or suffix in CONFIG_PATCH_SUFFIXES:
                configs_by_mod.setdefault(mod_dir.name, []).append(entry)
        if truncated:
            break
    return {
        "available": True,
        "stagingDir": str(staging_dir),
        "indexedModCount": len(mod_dirs),
        "indexedFileCount": total_files,
        "truncated": truncated,
        "byName": by_name,
        "byRel": by_rel,
        "configsByMod": configs_by_mod,
    }


def match_runtime_references_to_staged_files(references: List[str], index: Optional[Dict[str, Any]], max_matches: int = 12) -> List[Dict[str, Any]]:
    if not index:
        return []
    by_name = index.get("byName") if isinstance(index.get("byName"), dict) else {}
    by_rel = index.get("byRel") if isinstance(index.get("byRel"), dict) else {}
    matches: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str, str]] = set()
    for ref in references:
        rel_key, name_key = runtime_reference_keys(ref)
        candidates = list(by_rel.get(rel_key, []))
        candidates.extend(item for key, items in by_rel.items() if key.endswith("/" + rel_key) for item in items)
        candidates.extend(by_name.get(name_key, []))
        for item in candidates:
            if not isinstance(item, dict):
                continue
            key = (str(item.get("mod")), str(item.get("relativePath")), ref)
            if key in seen:
                continue
            seen.add(key)
            matches.append({**item, "reference": ref})
            if len(matches) >= max_matches:
                return matches
    return matches


def runtime_config_candidates(
    findings: List[Dict[str, Any]],
    index: Optional[Dict[str, Any]],
    max_candidates: int = 20,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()
    configs_by_mod = index.get("configsByMod") if isinstance(index, dict) and isinstance(index.get("configsByMod"), dict) else {}
    for finding in findings:
        line = str(finding.get("line") or "")
        lower = line.lower()
        configish = any(term in lower for term in ("config", "configured", "ini", "json", "toml", "xml", "setting", "mcm"))
        matches = finding.get("stagedMatches", []) if isinstance(finding.get("stagedMatches"), list) else []
        for match in matches:
            if not isinstance(match, dict):
                continue
            suffix = str(match.get("suffix") or "").lower()
            mod = str(match.get("mod") or "")
            rel = str(match.get("relativePath") or "")
            if suffix in CONFIG_PATCH_SUFFIXES or str(match.get("kind")) == "config":
                key = (mod, rel)
                if key not in seen:
                    seen.add(key)
                    candidates.append(
                        {
                            "mod": mod,
                            "path": match.get("path"),
                            "relativePath": rel,
                            "reference": match.get("reference"),
                            "reason": "Runtime log referenced this config/text file.",
                            "repairTool": "apply_config_text_patch",
                        }
                    )
            elif configish and mod:
                for config in configs_by_mod.get(mod, [])[:4]:
                    if not isinstance(config, dict):
                        continue
                    key = (str(config.get("mod")), str(config.get("relativePath")))
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append(
                        {
                            "mod": config.get("mod"),
                            "path": config.get("path"),
                            "relativePath": config.get("relativePath"),
                            "reference": match.get("reference"),
                            "reason": "Runtime log referenced this mod during a config-like error.",
                            "repairTool": "apply_config_text_patch",
                        }
                    )
            if len(candidates) >= max_candidates:
                return candidates
    return candidates


def runtime_signature_for_finding(finding: Dict[str, Any]) -> Dict[str, Any]:
    line = str(finding.get("line") or "")
    lower = line.lower()
    references = finding.get("references") if isinstance(finding.get("references"), list) else []
    ref_names = [runtime_reference_keys(str(ref))[1] for ref in references]
    primary_ref = ref_names[0] if ref_names else ""
    if "address library" in lower:
        return {
            "code": "address_library_or_runtime_mismatch",
            "title": "Address Library or Skyrim runtime mismatch",
            "nextAction": "Check Skyrim runtime version, SKSE version, Address Library version, and SKSE DLL mod compatibility.",
        }
    if any(term in lower for term in ("access violation", "fatal", "unhandled exception", "stack overflow")):
        return {
            "code": "crash_exception",
            "title": "Crash or fatal exception",
            "nextAction": "Read the crash log first, then check SKSE DLLs and recent mod updates before changing gameplay mods.",
        }
    if "dll" in lower and any(term in lower for term in ("failed", "missing", "not found", "could not", "cannot")):
        return {
            "code": "skse_dll_load_failed",
            "title": "SKSE DLL/plugin load failure",
            "nextAction": "Check the referenced DLL mod, SKSE version, Address Library requirement, and whether the DLL is deployed.",
        }
    if any(term in lower for term in ("not configured", "not configured properly", "file was not configured")):
        return {
            "code": "config_not_configured",
            "title": "Config file not configured",
            "nextAction": "Validate/read config candidates, then patch exact text with backup only if the fix is obvious.",
        }
    if any(term in lower for term in ("json", "toml", "xml", "ini")) and any(term in lower for term in ("parse", "syntax", "invalid", "error")):
        return {
            "code": "config_parse_error",
            "title": "Config syntax or parse error",
            "nextAction": "Run config_file_report on the referenced candidate and fix syntax before testing mods.",
        }
    if any(term in lower for term in ("missing master", "requires master")):
        return {
            "code": "missing_master",
            "title": "Missing plugin master",
            "nextAction": "Install/enable the required master or disable the dependent plugin in a cloned profile first.",
        }
    if ".pex" in lower or ".psc" in lower or "script" in lower:
        return {
            "code": "papyrus_script_issue",
            "title": "Papyrus script issue",
            "nextAction": "Check whether the script's mod is installed/deployed and whether this is a repeated error after loading the save.",
        }
    if any(term in lower for term in ("missing", "not found", "could not find", "cannot find")):
        return {
            "code": "missing_file_or_asset",
            "title": "Missing file or asset",
            "nextAction": "Map the referenced file to a staged mod, then check deployment and conflicts before reinstalling anything.",
        }
    if "warning" in lower:
        return {
            "code": "runtime_warning",
            "title": "Runtime warning",
            "nextAction": "Treat one-off warnings as weak evidence; repeated warnings with the same reference are more useful.",
        }
    return {
        "code": "runtime_error",
        "title": "Runtime error",
        "nextAction": "Read the referenced file/mod evidence and prefer cloned-profile tests over deleting mods.",
        "primaryReference": primary_ref or None,
    }


def runtime_issue_groups(findings: List[Dict[str, Any]], max_examples: int = 3) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    for finding in findings:
        signature = runtime_signature_for_finding(finding)
        references = finding.get("references") if isinstance(finding.get("references"), list) else []
        ref_names = sorted({runtime_reference_keys(str(ref))[1] for ref in references if str(ref).strip()})
        ref_key = ",".join(ref_names[:4])
        if not ref_key:
            normalized = re.sub(r"\b0x[0-9a-f]+\b", "0x...", str(finding.get("line") or "").lower())
            normalized = re.sub(r"\d+", "#", normalized)
            ref_key = compact_preview(normalized, 100)
        key = (str(signature.get("code")), ref_key)
        group = groups.setdefault(
            key,
            {
                "code": signature.get("code"),
                "title": signature.get("title"),
                "highestSeverity": finding.get("severity"),
                "count": 0,
                "references": [],
                "mods": [],
                "examples": [],
                "nextAction": signature.get("nextAction"),
            },
        )
        group["count"] += 1
        if severity_rank.get(str(finding.get("severity")), 9) < severity_rank.get(str(group.get("highestSeverity")), 9):
            group["highestSeverity"] = finding.get("severity")
        seen_refs = set(group["references"])
        for ref in references:
            ref_text = str(ref)
            if ref_text and ref_text not in seen_refs:
                group["references"].append(ref_text)
                seen_refs.add(ref_text)
        seen_mods = set(group["mods"])
        for match in finding.get("stagedMatches", []) if isinstance(finding.get("stagedMatches"), list) else []:
            if isinstance(match, dict):
                mod = str(match.get("mod") or "")
                if mod and mod not in seen_mods:
                    group["mods"].append(mod)
                    seen_mods.add(mod)
        if len(group["examples"]) < max_examples:
            group["examples"].append(
                {
                    "logName": finding.get("logName"),
                    "line": finding.get("line"),
                    "stagedMatches": finding.get("stagedMatches", [])[:4]
                    if isinstance(finding.get("stagedMatches"), list)
                    else [],
                }
            )
    result = list(groups.values())
    result.sort(key=lambda item: (severity_rank.get(str(item.get("highestSeverity")), 9), -int(item.get("count", 0)), str(item.get("code"))))
    return result


def annotate_config_candidates(candidates: List[Dict[str, Any]], args: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not bool(args.get("validate_config_candidates", True)):
        return candidates
    annotated: List[Dict[str, Any]] = []
    for candidate in candidates:
        item = dict(candidate)
        path = item.get("path")
        if isinstance(path, str) and path:
            try:
                validation = config_file_report({**args, "path": path, "max_bytes": int(args.get("max_config_validation_bytes", 2_000_000))})
                item["validation"] = {
                    "valid": validation.get("valid"),
                    "format": validation.get("format"),
                    "parseError": validation.get("parseError"),
                    "summary": validation.get("summary"),
                    "healthFindings": validation.get("healthFindings"),
                    "healthFindingCount": validation.get("healthFindingCount"),
                    "suggestedTextPatches": validation.get("suggestedTextPatches"),
                    "suggestedTextPatchCount": validation.get("suggestedTextPatchCount"),
                }
            except Exception as exc:
                item["validationError"] = str(exc)
        annotated.append(item)
    return annotated


def skyrim_runtime_log_report(args: Dict[str, Any]) -> Dict[str, Any]:
    args = apply_performance_defaults(args)
    collected = collect_skyrim_runtime_log_files(args)
    files = collected["files"][: int(args.get("max_runtime_log_files", args.get("max_log_files", 12)))]
    max_bytes = int(args.get("max_log_bytes_per_file", args.get("max_log_bytes", LOG_TAIL_DEFAULT_BYTES)))
    max_findings = int(args.get("max_runtime_findings", 80))
    max_refs = int(args.get("max_runtime_references", 12))
    fresh_log_hours = float(args.get("fresh_log_hours", 24))
    problem_terms = tokenize_issue_terms(
        args.get("description"),
        args.get("popup_text"),
        args.get("extra_terms"),
        args.get("problem"),
    )
    _vortex_appdata, skyrim_dir, staging_dir, my_games = get_context_paths(args)
    include_staged_matches = bool(args.get("include_staged_file_matches", True))
    staged_index = None

    findings: List[Dict[str, Any]] = []
    log_summaries: List[Dict[str, Any]] = []
    for path in files:
        kind = runtime_log_kind(path, my_games, skyrim_dir)
        text = tail_file_text(path, max_bytes)
        file_findings = 0
        for tail_line, line in enumerate(text.splitlines(), start=1):
            hits = runtime_line_terms(line, problem_terms)
            refs = extract_runtime_references(line, max_refs)
            if not hits and not refs:
                continue
            if refs and not hits and kind != "crash":
                continue
            severity = runtime_line_severity(line, kind)
            findings.append(
                {
                    "severity": severity,
                    "kind": kind,
                    "log": str(path),
                    "logName": path.name,
                    "tailLine": tail_line,
                    "matchedTerms": hits,
                    "references": refs,
                    "stagedMatches": [],
                    "line": compact_preview(line, 600),
                }
            )
            file_findings += 1
            if len(findings) >= max_findings:
                break
        stat = path.stat()
        log_summaries.append(
            {
                "path": str(path),
                "name": path.name,
                "kind": kind,
                "sizeBytes": stat.st_size,
                "modifiedAt": epoch_to_iso(stat.st_mtime),
                "scannedTailBytes": min(stat.st_size, max_bytes),
                "findingCount": file_findings,
            }
        )
        if len(findings) >= max_findings:
            break

    if include_staged_matches and staging_dir and staging_dir.exists() and any(item.get("references") for item in findings):
        staged_index = build_staged_file_index(staging_dir, args)
        for finding in findings:
            refs = finding.get("references") if isinstance(finding.get("references"), list) else []
            finding["stagedMatches"] = match_runtime_references_to_staged_files(refs, staged_index, max_matches=max_refs)

    findings.sort(
        key=lambda item: (
            {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}.get(str(item.get("severity")), 5),
            str(item.get("logName", "")).lower(),
            int(item.get("tailLine", 0)),
        )
    )
    config_candidates = runtime_config_candidates(findings, staged_index, int(args.get("max_runtime_config_candidates", 20)))
    config_candidates = annotate_config_candidates(config_candidates, args)
    issue_groups = runtime_issue_groups(findings, int(args.get("max_issue_group_examples", 3)))
    severity_counts: Dict[str, int] = {}
    for finding in findings:
        severity = str(finding.get("severity") or "info")
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
    newest_mtime = max((path.stat().st_mtime for path in files), default=None)
    newest_age_hours = ((time.time() - newest_mtime) / 3600) if newest_mtime else None
    fresh_log_status = {
        "fresh": bool(newest_age_hours is not None and newest_age_hours <= fresh_log_hours),
        "freshLogHours": fresh_log_hours,
        "newestModifiedAt": epoch_to_iso(newest_mtime) if newest_mtime else None,
        "newestAgeHours": round(newest_age_hours, 2) if newest_age_hours is not None else None,
        "note": None,
    }
    if files and not fresh_log_status["fresh"]:
        fresh_log_status["note"] = "The newest runtime log is older than the freshness window. Reproduce the issue and rerun for stronger evidence."

    recommended_actions = [
        "Start with critical/high findings first; one SKSE DLL or Address Library mismatch can create many downstream symptoms.",
        "For config candidates, use config_file_report/read_text_file first, then apply_config_text_patch with dry_run=true and exact old/new text.",
        "Do not edit ESP/ESM/ESL records or delete mods from a log line alone. Confirm with xEdit or a cloned Vortex profile test.",
    ]
    if issue_groups:
        recommended_actions.insert(0, "Start from issueGroups; they deduplicate repeated log spam into the likely root-cause patterns.")
    if config_candidates:
        recommended_actions.insert(0, "A config-like runtime error points to staged config/text candidates that OpenClaw can inspect and patch with backups.")
    if files and not fresh_log_status["fresh"]:
        recommended_actions.insert(0, "Runtime logs look stale. Launch Skyrim, reproduce the popup/error, quit, then rerun this report.")
    if not files:
        recommended_actions.insert(0, "No Skyrim runtime logs were found. Enable Papyrus logging only for debugging, launch Skyrim once, reproduce the issue, then rerun.")

    return {
        "available": bool(files),
        "myGamesDir": str(my_games) if my_games else None,
        "skyrimDir": str(skyrim_dir) if skyrim_dir else None,
        "stagingDir": str(staging_dir) if staging_dir else None,
        "logCount": len(files),
        "findingCount": len(findings),
        "severityCounts": severity_counts,
        "freshLogStatus": fresh_log_status,
        "logs": log_summaries,
        "findings": findings,
        "issueGroupCount": len(issue_groups),
        "issueGroups": issue_groups,
        "configCandidates": config_candidates,
        "stagedFileIndex": {
            "available": bool(staged_index),
            "indexedModCount": staged_index.get("indexedModCount") if isinstance(staged_index, dict) else 0,
            "indexedFileCount": staged_index.get("indexedFileCount") if isinstance(staged_index, dict) else 0,
            "truncated": staged_index.get("truncated") if isinstance(staged_index, dict) else False,
        },
        "recommendedActions": recommended_actions,
        "notes": [
            "This scans recent tails of Papyrus, SKSE, crash, Trainwreck/CrashLogger, and NetScriptFramework logs when present.",
            "The report stores short matching lines, not whole log files.",
            "Papyrus warnings can be noisy; repeated fatal/SKSE/crash/config errors are usually more useful than one-off warnings.",
        ],
    }


def vortex_cli_get(args: Dict[str, Any]) -> Dict[str, Any]:
    paths = args.get("paths") or ["persistent.profiles", "settings.profiles"]
    if not isinstance(paths, list) or not all(isinstance(path, str) and path for path in paths):
        raise ToolError("paths must be a non-empty array of Vortex state paths.")
    timeout = int(args.get("timeout_seconds", 60))
    result = vortex_state_get(paths, args.get("vortex_exe"), timeout)
    parsed = result["parsed"]
    return {
        "vortex_exe": result["vortex_exe"],
        "paths": paths,
        "values": parsed["values"],
        "unparsedLines": parsed["unparsedLines"],
        "rawStdout": result["stdout"],
        "rawStderr": result["stderr"],
    }


def profile_enabled(entry: Any) -> bool:
    if isinstance(entry, dict):
        return bool(entry.get("enabled", False))
    return bool(entry)


def profile_enabled_time(entry: Any) -> Any:
    if isinstance(entry, dict):
        return entry.get("enabledTime")
    return None


def active_profile_from_settings(state: Dict[str, Any], values: Dict[str, Any]) -> Optional[str]:
    candidates = [
        nested_get(state, ["settings", "profiles", "activeProfileId"]),
        nested_get(state, ["settings", "profile", "activeProfileId"]),
        nested_get(state, ["settings", "profiles", "activeProfile"]),
    ]
    for key, value in values.items():
        if key.endswith("activeProfileId") or key.endswith("activeProfile"):
            candidates.append(value)
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def profile_last_activated(profile: Dict[str, Any]) -> float:
    try:
        return float(profile.get("lastActivated", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def summarize_profile(profile_id: str, profile: Dict[str, Any], active_id: Optional[str]) -> Dict[str, Any]:
    mod_state = profile.get("modState") if isinstance(profile.get("modState"), dict) else {}
    enabled_count = sum(1 for entry in mod_state.values() if profile_enabled(entry))
    last_activated = profile.get("lastActivated")
    features = profile.get("features") if isinstance(profile.get("features"), dict) else {}
    return {
        "id": profile_id,
        "name": profile.get("name") or profile_id,
        "gameId": profile.get("gameId"),
        "active": profile_id == active_id,
        "modStateCount": len(mod_state),
        "enabledModCount": enabled_count,
        "disabledModCount": max(0, len(mod_state) - enabled_count),
        "lastActivated": last_activated,
        "lastActivatedIso": epoch_to_iso(last_activated),
        "pendingRemove": bool(profile.get("pendingRemove", False)),
        "featureKeys": sorted(str(key) for key in features.keys()),
    }


def summarize_vortex_mod(mod_id: str, mods: Dict[str, Any]) -> Dict[str, Any]:
    entry = mods.get(mod_id)
    if not isinstance(entry, dict):
        return {"id": mod_id, "name": mod_id}
    attributes = entry.get("attributes") if isinstance(entry.get("attributes"), dict) else {}
    installation = entry.get("installationPath") or entry.get("path")
    name = (
        attributes.get("customFileName")
        or attributes.get("logicalFileName")
        or attributes.get("name")
        or entry.get("name")
        or mod_id
    )
    nexus_id = attributes.get("modId") or attributes.get("nexusModId")
    file_id = attributes.get("fileId") or attributes.get("nexusFileId")
    return {
        "id": mod_id,
        "name": name,
        "version": attributes.get("version") or entry.get("version"),
        "source": attributes.get("source") or attributes.get("sourceName"),
        "nexusModId": nexus_id,
        "nexusFileId": file_id,
        "installationPath": installation,
    }


def change_plan_preview(changes: List[Dict[str, Any]], max_preview: int = 50) -> Dict[str, Any]:
    limit = max(0, int(max_preview))
    return {
        "plannedChangeCount": len(changes),
        "plannedChanges": changes[:limit],
        "planTruncated": len(changes) > limit,
        "maxPlanPreview": limit,
    }


def clone_profile_changes(
    new_id: str,
    new_name: str,
    source: Dict[str, Any],
    make_active: bool,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    cloned = json.loads(json.dumps(source))
    cloned["id"] = new_id
    cloned["name"] = new_name
    cloned["lastActivated"] = now_ms() if make_active else 0
    cloned.pop("pendingRemove", None)

    changes: List[Dict[str, Any]] = []
    base_path = ("persistent", "profiles", new_id)
    for key, value in cloned.items():
        if key == "modState":
            continue
        changes.append({"path": state_path(*base_path, key), "value": value})

    mod_state = cloned.get("modState") if isinstance(cloned.get("modState"), dict) else {}
    for mod_id, entry in sorted(mod_state.items(), key=lambda item: str(item[0]).lower()):
        changes.append({"path": state_path(*base_path, "modState", mod_id), "value": entry})
    return cloned, changes


def load_vortex_profile_state(args: Dict[str, Any], include_mods: bool = False) -> Dict[str, Any]:
    game_id = str(args.get("game_id") or GAME_ID)
    paths = ["persistent.profiles", "settings.profiles", "settings.profile"]
    if include_mods:
        paths.append(state_path("persistent", "mods", game_id))
    result = vortex_state_get(paths, args.get("vortex_exe"), int(args.get("timeout_seconds", 60)))
    parsed = result["parsed"]
    state = result["state"]
    profiles = nested_get(state, ["persistent", "profiles"])
    if not isinstance(profiles, dict):
        profiles = {}
    mods = nested_get(state, ["persistent", "mods", game_id])
    if not isinstance(mods, dict):
        mods = {}

    include_all = bool(args.get("include_all_games", False))
    filtered_profiles = {
        str(profile_id): profile
        for profile_id, profile in profiles.items()
        if isinstance(profile, dict) and (include_all or profile.get("gameId") == game_id)
    }
    active_from_settings = active_profile_from_settings(state, parsed["values"])
    active_from_last = None
    if filtered_profiles:
        active_from_last = max(filtered_profiles.items(), key=lambda item: profile_last_activated(item[1]))[0]
    active_profile_id = active_from_settings if active_from_settings in filtered_profiles else active_from_last

    return {
        "gameId": game_id,
        "vortex_exe": result["vortex_exe"],
        "profiles": filtered_profiles,
        "allProfiles": profiles,
        "mods": mods,
        "activeProfileId": active_profile_id,
        "activeFromSettings": active_from_settings,
        "activeFromLastActivated": active_from_last,
        "rawPaths": paths,
    }


def require_profile(snapshot: Dict[str, Any], profile_id: Optional[str]) -> Tuple[str, Dict[str, Any]]:
    profiles = snapshot["profiles"]
    selected = profile_id or snapshot.get("activeProfileId")
    if not selected:
        raise ToolError("No active Vortex profile could be detected. Pass profile_id explicitly.")
    if selected not in profiles:
        raise ToolError(f"Vortex profile '{selected}' was not found for game {snapshot['gameId']}.")
    return selected, profiles[selected]


def default_backup_dir(args: Dict[str, Any]) -> Path:
    explicit = expand_path(args.get("backup_dir"))
    if explicit:
        return explicit
    docs = default_documents() or Path.cwd()
    return docs / "vortex-skyrimse-mcp-reports" / "profile-backups"


def selected_backup_profiles(snapshot: Dict[str, Any], profile_id: Optional[str], include_all_profiles: bool) -> Dict[str, Any]:
    if include_all_profiles:
        return {
            str(profile_id): profile
            for profile_id, profile in snapshot["profiles"].items()
            if isinstance(profile, dict)
        }
    selected_id, selected = require_profile(snapshot, profile_id)
    return {selected_id: selected}


def build_profile_backup(
    snapshot: Dict[str, Any],
    profiles: Dict[str, Any],
    include_mod_metadata: bool = True,
) -> Dict[str, Any]:
    return {
        "schema": "vortex-skyrimse-profile-backup-v1",
        "generatedAt": iso_now(),
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "gameId": snapshot["gameId"],
        "activeProfileId": snapshot.get("activeProfileId"),
        "profileCount": len(profiles),
        "profiles": json.loads(json.dumps(profiles, default=str)),
        "mods": json.loads(json.dumps(snapshot.get("mods", {}), default=str)) if include_mod_metadata else {},
        "notes": [
            "This file is for vortex_profile_restore_plan.",
            "Restore previews are dry-run by default; use apply=true only after reading the planned changes.",
            "Close Vortex before applying a restore plan.",
        ],
    }


def write_profile_backup_file(snapshot: Dict[str, Any], profiles: Dict[str, Any], args: Dict[str, Any]) -> Path:
    output_path = expand_path(args.get("output_path"))
    if not output_path:
        profile_part = "all-profiles" if len(profiles) != 1 else next(iter(profiles.keys()))
        safe_profile_part = re.sub(r"[^A-Za-z0-9_.-]+", "_", profile_part)[:80] or "profile"
        output_path = default_backup_dir(args) / f"vortex-profile-backup-{safe_profile_part}-{now_stamp()}.json"
    backup = build_profile_backup(snapshot, profiles, bool(args.get("include_mod_metadata", True)))
    write_text(output_path, json.dumps(backup, indent=2, ensure_ascii=False, default=str))
    log_event("support", "vortex_profile_backup_written", {"output_path": str(output_path), "profileIds": list(profiles.keys())})
    return output_path


def write_backup_before_apply(snapshot: Dict[str, Any], profiles: Dict[str, Any], args: Dict[str, Any], reason: str) -> Optional[str]:
    if not bool(args.get("backup_before_apply", True)):
        return None
    backup_args = {**args}
    backup_args.pop("output_path", None)
    if args.get("backup_path"):
        backup_args["output_path"] = args.get("backup_path")
    output_path = write_profile_backup_file(snapshot, profiles, backup_args)
    log_event(
        "support",
        "vortex_profile_backup_before_apply",
        {"output_path": str(output_path), "profileIds": list(profiles.keys()), "reason": reason},
    )
    return str(output_path)


def vortex_profile_backup(args: Dict[str, Any]) -> Dict[str, Any]:
    include_all_profiles = bool(args.get("include_all_profiles", False))
    snapshot = load_vortex_profile_state(args, include_mods=bool(args.get("include_mod_metadata", True)))
    profiles = selected_backup_profiles(snapshot, args.get("profile_id"), include_all_profiles)
    backup_args = {**args}
    if args.get("backup_path") and not args.get("output_path"):
        backup_args["output_path"] = args.get("backup_path")
    output_path = write_profile_backup_file(snapshot, profiles, backup_args)
    return {
        "output_path": str(output_path),
        "gameId": snapshot["gameId"],
        "activeProfileId": snapshot.get("activeProfileId"),
        "profileIds": list(profiles.keys()),
        "profileCount": len(profiles),
        "vortex_exe": snapshot["vortex_exe"],
        "nextSteps": [
            "Keep this file if you are about to test profile changes.",
            "Use vortex_profile_restore_plan with apply=false to preview undo actions.",
            "Use apply=true only after you confirm the plan and close Vortex.",
        ],
    }


def load_profile_backup(path_value: Optional[str]) -> Dict[str, Any]:
    path = expand_path(path_value)
    if not path or not path.exists() or not path.is_file():
        raise ToolError("backup_path must point to an existing profile backup JSON file.")
    data = json.loads(read_text(path, 10_000_000))
    if not isinstance(data, dict) or data.get("schema") != "vortex-skyrimse-profile-backup-v1":
        raise ToolError("backup_path is not a vortex-skyrimse profile backup file.")
    profiles = data.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ToolError("profile backup does not contain any profiles.")
    data["_backupPath"] = str(path)
    return data


def restore_profile_changes(
    profile_id: str,
    backup_profile: Dict[str, Any],
    current_profile: Dict[str, Any],
    disable_extra_mods: bool = False,
) -> List[Dict[str, Any]]:
    changes: List[Dict[str, Any]] = []
    for key, value in backup_profile.items():
        if key == "modState":
            continue
        if current_profile.get(key) != value:
            changes.append({"path": state_path("persistent", "profiles", profile_id, key), "value": value})

    backup_mod_state = backup_profile.get("modState") if isinstance(backup_profile.get("modState"), dict) else {}
    current_mod_state = current_profile.get("modState") if isinstance(current_profile.get("modState"), dict) else {}
    for mod_id, backup_entry in sorted(backup_mod_state.items(), key=lambda item: str(item[0]).lower()):
        current_entry = current_mod_state.get(mod_id)
        if current_entry != backup_entry:
            changes.append({"path": state_path("persistent", "profiles", profile_id, "modState", mod_id), "value": backup_entry})

    if disable_extra_mods:
        for mod_id, current_entry in sorted(current_mod_state.items(), key=lambda item: str(item[0]).lower()):
            if mod_id in backup_mod_state or not profile_enabled(current_entry):
                continue
            changes.append({"path": state_path("persistent", "profiles", profile_id, "modState", mod_id, "enabled"), "value": False})
    return changes


def vortex_profile_restore_plan(args: Dict[str, Any]) -> Dict[str, Any]:
    backup = load_profile_backup(args.get("backup_path"))
    backup_profiles = backup["profiles"]
    profile_id = str(args.get("profile_id") or backup.get("activeProfileId") or "")
    if not profile_id:
        if len(backup_profiles) == 1:
            profile_id = next(iter(backup_profiles.keys()))
        else:
            raise ToolError("backup contains multiple profiles; pass profile_id.")
    if profile_id not in backup_profiles:
        raise ToolError(f"profile_id '{profile_id}' is not present in this backup.")
    backup_profile = backup_profiles[profile_id]
    if not isinstance(backup_profile, dict):
        raise ToolError("backup profile payload is not an object.")

    restore_args = {**args, "game_id": args.get("game_id") or backup.get("gameId") or GAME_ID}
    snapshot = load_vortex_profile_state(restore_args, include_mods=False)
    if profile_id not in snapshot["profiles"]:
        raise ToolError(f"Current Vortex state does not contain profile '{profile_id}'.")
    current_profile = snapshot["profiles"][profile_id]
    extra_profiles = sorted(str(item) for item in snapshot["profiles"].keys() if str(item) not in backup_profiles)
    changes = restore_profile_changes(
        profile_id,
        backup_profile,
        current_profile,
        bool(args.get("disable_extra_mods", False)),
    )
    apply_changes = bool(args.get("apply", False))
    apply_result = None
    if apply_changes and changes:
        apply_result = vortex_state_set(
            changes,
            args.get("vortex_exe"),
            int(args.get("timeout_seconds", 60)),
            bool(args.get("allow_running_vortex", False)),
        )
    return {
        "dryRun": not apply_changes,
        "backup_path": backup["_backupPath"],
        "gameId": snapshot["gameId"],
        "profile": summarize_profile(profile_id, current_profile, snapshot["activeProfileId"]),
        "backupGeneratedAt": backup.get("generatedAt"),
        "disableExtraMods": bool(args.get("disable_extra_mods", False)),
        "extraProfilesNotInBackup": extra_profiles,
        **change_plan_preview(changes, int(args.get("max_plan_preview", 100))),
        "applied": bool(apply_result),
        "applyBatches": apply_result.get("batchCount") if apply_result else None,
        "vortex_exe": apply_result["vortex_exe"] if apply_result else snapshot["vortex_exe"],
        "notes": [
            "This restores backed-up profile fields and mod enabled-state records through Vortex's CLI.",
            "Dry-run is the default. Read plannedChanges before apply=true.",
            "Close Vortex before apply=true so Vortex does not overwrite or lock profile state.",
            "Extra profiles that are not in the backup are reported but not removed automatically.",
            "After applying a restore plan, open Vortex and deploy mods before launching Skyrim.",
        ],
    }


def vortex_profile_report(args: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = load_vortex_profile_state(args, include_mods=False)
    summaries = [
        summarize_profile(profile_id, profile, snapshot["activeProfileId"])
        for profile_id, profile in sorted(
            snapshot["profiles"].items(),
            key=lambda item: (item[1].get("gameId", ""), item[1].get("name", item[0]).lower()),
        )
    ]
    return {
        "gameId": snapshot["gameId"],
        "vortex_exe": snapshot["vortex_exe"],
        "activeProfileId": snapshot["activeProfileId"],
        "activeDetection": {
            "fromSettings": snapshot["activeFromSettings"],
            "fromLastActivated": snapshot["activeFromLastActivated"],
        },
        "profileCount": len(summaries),
        "profiles": summaries,
        "notes": [
            "Profile writes use Vortex.exe --set and default to dry-run in write-capable tools.",
            "Close Vortex before apply=true profile writes so Vortex does not overwrite or lock the state database.",
            "After changing profile mod enabled states, use Vortex to deploy mods before launching Skyrim.",
        ],
    }


def vortex_profile_mods(args: Dict[str, Any]) -> Dict[str, Any]:
    include_metadata = bool(args.get("include_mod_metadata", True))
    snapshot = load_vortex_profile_state(args, include_mods=include_metadata)
    profile_id, profile = require_profile(snapshot, args.get("profile_id"))
    mod_state = profile.get("modState") if isinstance(profile.get("modState"), dict) else {}
    include_disabled = bool(args.get("include_disabled", False))
    max_mods = int(args.get("max_mods", 500))
    rows = []
    for mod_id, entry in mod_state.items():
        enabled = profile_enabled(entry)
        if not include_disabled and not enabled:
            continue
        row = {
            "id": mod_id,
            "enabled": enabled,
            "enabledTime": profile_enabled_time(entry),
            "enabledTimeIso": epoch_to_iso(profile_enabled_time(entry)),
        }
        if include_metadata:
            row.update(summarize_vortex_mod(str(mod_id), snapshot["mods"]))
        rows.append(row)
    rows.sort(key=lambda item: (not item["enabled"], str(item.get("name") or item["id"]).lower()))
    return {
        "gameId": snapshot["gameId"],
        "profile": summarize_profile(profile_id, profile, snapshot["activeProfileId"]),
        "includeDisabled": include_disabled,
        "includeModMetadata": include_metadata,
        "returnedModCount": min(len(rows), max_mods),
        "totalMatchingModCount": len(rows),
        "mods": rows[:max_mods],
    }


def vortex_compare_profiles(args: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = load_vortex_profile_state(args, include_mods=False)
    left_id = args.get("left_profile_id")
    right_id = args.get("right_profile_id")
    if not left_id or not right_id:
        raise ToolError("left_profile_id and right_profile_id are required.")
    left_id, left = require_profile(snapshot, left_id)
    right_id, right = require_profile(snapshot, right_id)
    left_state = left.get("modState") if isinstance(left.get("modState"), dict) else {}
    right_state = right.get("modState") if isinstance(right.get("modState"), dict) else {}
    left_enabled = {str(mod_id) for mod_id, entry in left_state.items() if profile_enabled(entry)}
    right_enabled = {str(mod_id) for mod_id, entry in right_state.items() if profile_enabled(entry)}
    all_ids = set(str(mod_id) for mod_id in left_state.keys()) | set(str(mod_id) for mod_id in right_state.keys())
    different_state = [
        {
            "id": mod_id,
            "leftEnabled": mod_id in left_enabled,
            "rightEnabled": mod_id in right_enabled,
        }
        for mod_id in sorted(all_ids)
        if (mod_id in left_enabled) != (mod_id in right_enabled)
    ]
    return {
        "gameId": snapshot["gameId"],
        "left": summarize_profile(left_id, left, snapshot["activeProfileId"]),
        "right": summarize_profile(right_id, right, snapshot["activeProfileId"]),
        "enabledOnlyInLeft": sorted(left_enabled - right_enabled),
        "enabledOnlyInRight": sorted(right_enabled - left_enabled),
        "differentState": different_state,
        "differentStateCount": len(different_state),
    }


def resolve_mod_staging_path(mod_id: str, mod_entry: Any, staging_dir: Optional[Path]) -> Optional[Path]:
    candidates: List[Path] = []
    if isinstance(mod_entry, dict):
        raw_values = [
            mod_entry.get("installationPath"),
            mod_entry.get("path"),
            mod_entry.get("installPath"),
        ]
        attributes = mod_entry.get("attributes") if isinstance(mod_entry.get("attributes"), dict) else {}
        raw_values.extend([attributes.get("installationPath"), attributes.get("path")])
        for raw in raw_values:
            if not raw:
                continue
            path = Path(str(raw))
            candidates.append(path)
            if staging_dir and not path.is_absolute():
                candidates.append(staging_dir / str(raw))
    if staging_dir:
        candidates.append(staging_dir / mod_id)

    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if resolved.exists() and resolved.is_dir():
            return resolved
    return None


def root_plugin_paths(data_dir: Optional[Path]) -> Dict[str, str]:
    if not data_dir or not data_dir.exists():
        return {}
    result: Dict[str, str] = {}
    for child in data_dir.iterdir():
        if child.is_file() and child.suffix.lower() in {".esp", ".esm", ".esl"}:
            result[child.name.lower()] = str(child)
    return result


def skyrim_file_health(args: Dict[str, Any]) -> Dict[str, Any]:
    skyrim_dir = find_skyrim_dir(args.get("skyrim_dir"))
    data_dir = skyrim_dir / "Data" if skyrim_dir else None
    issues = []

    skse_loader = skyrim_dir / "skse64_loader.exe" if skyrim_dir else None
    skse_dlls = sorted(skyrim_dir.glob("skse64_*.dll")) if skyrim_dir and skyrim_dir.exists() else []
    skse_script_files = (
        sorted((data_dir / "Scripts").glob("skse*.pex"))
        if data_dir and (data_dir / "Scripts").exists()
        else []
    )
    if not skyrim_dir or not skyrim_dir.exists():
        issues.append("SkyrimSE.exe was not found.")
    if skyrim_dir and not path_exists(skse_loader):
        issues.append("skse64_loader.exe is missing beside SkyrimSE.exe.")
    if skyrim_dir and not skse_dlls:
        issues.append("SKSE runtime DLLs are missing beside SkyrimSE.exe.")
    if data_dir and data_dir.exists() and not skse_script_files:
        issues.append("SKSE script files were not found under Data\\Scripts.")

    voice_archives = sorted(data_dir.glob("Skyrim - Voices_*.bsa")) if data_dir and data_dir.exists() else []
    sound_archive = data_dir / "Skyrim - Sounds.bsa" if data_dir else None
    if data_dir and data_dir.exists() and not voice_archives:
        issues.append("No Skyrim voice archive was found in Data; missing voices can happen if the game files are incomplete.")
    if data_dir and data_dir.exists() and not path_exists(sound_archive):
        issues.append("Skyrim - Sounds.bsa was not found in Data; sound assets may be incomplete.")

    return {
        "skyrim_dir": str(skyrim_dir) if skyrim_dir else None,
        "data_dir": str(data_dir) if data_dir else None,
        "skse": {
            "loader": str(skse_loader) if skse_loader else None,
            "loaderExists": bool(path_exists(skse_loader)),
            "dlls": [str(path) for path in skse_dlls],
            "scriptFileCount": len(skse_script_files),
        },
        "audioArchives": {
            "voices": [str(path) for path in voice_archives],
            "sound": str(sound_archive) if sound_archive else None,
            "soundExists": bool(path_exists(sound_archive)),
        },
        "issues": issues,
    }


def vortex_profile_deployment_report(args: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = load_vortex_profile_state(args, include_mods=True)
    profile_id, profile = require_profile(snapshot, args.get("profile_id"))
    vortex_appdata, skyrim_dir, staging_dir, _my_games = get_context_paths(args)
    data_dir = skyrim_dir / "Data" if skyrim_dir else None
    data_plugins = root_plugin_paths(data_dir)
    local = expand_path(args.get("local_appdata")) or default_local_appdata()
    state = plugin_state_paths(local)
    plugins_txt = parse_plugin_list(Path(state["plugins_txt"]) if state["plugins_txt"] else None)
    plugins_enabled = {
        str(entry["name"]).lower()
        for entry in plugins_txt.get("entries", [])
        if entry.get("enabled")
    }

    mod_state = profile.get("modState") if isinstance(profile.get("modState"), dict) else {}
    enabled_mod_ids = [str(mod_id) for mod_id, entry in mod_state.items() if profile_enabled(entry)]
    max_mods = int(args.get("max_mods", 500))
    max_files_per_mod = int(args.get("max_files_per_mod", 3000))
    checked_mods = []
    unresolved_mods = []
    plugin_rows = []
    profile_plugin_names: set[str] = set()
    scan_cache = load_scan_cache(args) if scan_cache_enabled(args) else {}

    for mod_id in sorted(enabled_mod_ids, key=str.lower)[:max_mods]:
        mod_entry = snapshot["mods"].get(mod_id)
        mod_path = resolve_mod_staging_path(mod_id, mod_entry, staging_dir)
        if not mod_path:
            unresolved_mods.append({**summarize_vortex_mod(mod_id, snapshot["mods"]), "reason": "staging folder not found"})
            continue
        summary = mod_summary_cached(mod_path, include_files=False, max_files=max_files_per_mod, args=args, cache=scan_cache)
        checked_mods.append(
            {
                **summarize_vortex_mod(mod_id, snapshot["mods"]),
                "stagingPath": str(mod_path),
                "pluginCount": len(summary.get("plugins", [])),
                "archiveCount": len(summary.get("archives", [])),
                "sksePluginCount": len(summary.get("sksePlugins", [])),
            }
        )
        for rel in summary.get("plugins", []):
            plugin_name = Path(rel).name
            plugin_key = plugin_name.lower()
            profile_plugin_names.add(plugin_key)
            plugin_rows.append(
                {
                    "modId": mod_id,
                    "modName": summarize_vortex_mod(mod_id, snapshot["mods"]).get("name"),
                    "plugin": plugin_name,
                    "relativePath": rel,
                    "deployedInData": plugin_key in data_plugins,
                    "enabledInPluginsTxt": plugin_key in plugins_enabled,
                    "dataPath": data_plugins.get(plugin_key),
                }
            )

    if scan_cache_enabled(args):
        write_scan_cache(args, scan_cache)

    missing_from_data = [row for row in plugin_rows if not row["deployedInData"]]
    not_enabled = [row for row in plugin_rows if not row["enabledInPluginsTxt"]]
    enabled_plugins_not_seen_in_profile = sorted(plugins_enabled - profile_plugin_names)
    issues = []
    if not skyrim_dir or not skyrim_dir.exists():
        issues.append("SkyrimSE.exe/Data folder was not found; pass skyrim_dir.")
    if not staging_dir or not staging_dir.exists():
        issues.append("Vortex staging folder was not found; pass staging_dir.")
    if not plugins_txt.get("exists"):
        issues.append("plugins.txt was not found; launch Skyrim once and deploy plugins in Vortex.")
    if unresolved_mods:
        issues.append("Some enabled profile mods could not be matched to staging folders.")
    if missing_from_data:
        issues.append("Some plugins from enabled profile mods are not present in Skyrim Data; deploy mods in Vortex.")
    if not_enabled:
        issues.append("Some plugins from enabled profile mods are not enabled in plugins.txt.")
    if enabled_plugins_not_seen_in_profile and profile_plugin_names:
        issues.append("plugins.txt has enabled plugins not seen in the selected profile; this may indicate the wrong profile or stale deployment.")

    return {
        "gameId": snapshot["gameId"],
        "profile": summarize_profile(profile_id, profile, snapshot["activeProfileId"]),
        "vortex_appdata": str(vortex_appdata) if vortex_appdata else None,
        "staging_dir": str(staging_dir) if staging_dir else None,
        "skyrim_data": str(data_dir) if data_dir else None,
        "pluginsTxt": plugins_txt,
        "enabledProfileModCount": len(enabled_mod_ids),
        "checkedEnabledModCount": len(checked_mods),
        "uncheckedEnabledModCount": max(0, len(enabled_mod_ids) - max_mods),
        "unresolvedEnabledMods": unresolved_mods,
        "checkedMods": checked_mods,
        "profilePlugins": plugin_rows,
        "pluginsFromEnabledModsMissingFromData": missing_from_data,
        "pluginsFromEnabledModsNotEnabledInPluginsTxt": not_enabled,
        "enabledPluginsTxtNotSeenInProfile": enabled_plugins_not_seen_in_profile,
        "issues": issues,
        "notes": [
            "This is read-only. It compares the selected Vortex profile, staging folders, Skyrim Data, and plugins.txt.",
            "After switching profiles or changing enabled mods, use Vortex Deploy Mods before launching Skyrim.",
            "Texture/mesh/SKSE-only mods may have no ESP/ESM/ESL plugin and will not appear in profilePlugins.",
        ],
    }


def vortex_clone_profile(args: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = load_vortex_profile_state(args, include_mods=False)
    source_id, source = require_profile(snapshot, args.get("source_profile_id"))
    new_id = str(args.get("new_profile_id") or f"openclaw-{now_stamp()}-{uuid.uuid4().hex[:8]}")
    if new_id in snapshot["allProfiles"]:
        raise ToolError(f"A Vortex profile with id '{new_id}' already exists.")
    new_name = str(args.get("new_name") or f"OpenClaw Safe Test {now_stamp()}")
    make_active = bool(args.get("make_active", False))
    apply_changes = bool(args.get("apply", False))
    cloned, changes = clone_profile_changes(new_id, new_name, source, make_active)
    apply_result = None
    backup_path = None
    if apply_changes:
        backup_path = write_backup_before_apply(
            snapshot,
            selected_backup_profiles(snapshot, None, True),
            args,
            "vortex_clone_profile",
        )
        apply_result = vortex_state_set(
            changes,
            args.get("vortex_exe"),
            int(args.get("timeout_seconds", 60)),
            bool(args.get("allow_running_vortex", False)),
        )
    return {
        "dryRun": not apply_changes,
        "gameId": snapshot["gameId"],
        "sourceProfile": summarize_profile(source_id, source, snapshot["activeProfileId"]),
        "newProfile": summarize_profile(new_id, cloned, new_id if make_active else snapshot["activeProfileId"]),
        **change_plan_preview(changes, int(args.get("max_plan_preview", 50))),
        "backupBeforeApply": bool(args.get("backup_before_apply", True)),
        "backupPath": backup_path,
        "applied": bool(apply_result),
        "applyBatches": apply_result.get("batchCount") if apply_result else None,
        "vortex_exe": apply_result["vortex_exe"] if apply_result else snapshot["vortex_exe"],
        "notes": [
            "Use apply=true only with Vortex closed. By default this tool refuses writes while Vortex.exe is running.",
            "When apply=true, this writes a Vortex profile backup first unless backup_before_apply=false.",
            "The clone copies enabled/disabled mod state in chunked CLI writes so large collections avoid Windows command-length failures.",
            "Deploy mods in Vortex after activating or changing a profile.",
        ],
    }


def vortex_set_profile_mods(args: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = load_vortex_profile_state(args, include_mods=True)
    profile_id, profile = require_profile(snapshot, args.get("profile_id"))
    enable_ids = sorted({str(mod_id) for mod_id in args.get("enable_mod_ids", [])})
    disable_ids = sorted({str(mod_id) for mod_id in args.get("disable_mod_ids", [])})
    overlap = sorted(set(enable_ids) & set(disable_ids))
    if overlap:
        raise ToolError(f"These mod ids were requested for both enable and disable: {', '.join(overlap)}")
    if not enable_ids and not disable_ids:
        raise ToolError("Pass at least one mod id in enable_mod_ids or disable_mod_ids.")

    mod_state = profile.get("modState") if isinstance(profile.get("modState"), dict) else {}
    known_ids = set(str(mod_id) for mod_id in mod_state.keys()) | set(str(mod_id) for mod_id in snapshot["mods"].keys())
    requested_ids = set(enable_ids) | set(disable_ids)
    unknown_ids = sorted(requested_ids - known_ids)
    if unknown_ids and not bool(args.get("allow_unknown_mod_ids", False)):
        raise ToolError(
            "Unknown Vortex mod ids: "
            + ", ".join(unknown_ids)
            + ". Use vortex_profile_mods first, or set allow_unknown_mod_ids=true if you know the ids are valid."
        )

    timestamp = now_ms()
    changes: List[Dict[str, Any]] = []
    for mod_id in enable_ids:
        changes.append({"path": state_path("persistent", "profiles", profile_id, "modState", mod_id, "enabled"), "value": True})
        changes.append({"path": state_path("persistent", "profiles", profile_id, "modState", mod_id, "enabledTime"), "value": timestamp})
    for mod_id in disable_ids:
        changes.append({"path": state_path("persistent", "profiles", profile_id, "modState", mod_id, "enabled"), "value": False})

    apply_changes = bool(args.get("apply", False))
    apply_result = None
    backup_path = None
    if apply_changes:
        backup_path = write_backup_before_apply(
            snapshot,
            {profile_id: profile},
            args,
            "vortex_set_profile_mods",
        )
        apply_result = vortex_state_set(
            changes,
            args.get("vortex_exe"),
            int(args.get("timeout_seconds", 60)),
            bool(args.get("allow_running_vortex", False)),
        )
    return {
        "dryRun": not apply_changes,
        "gameId": snapshot["gameId"],
        "profile": summarize_profile(profile_id, profile, snapshot["activeProfileId"]),
        "enableModIds": enable_ids,
        "disableModIds": disable_ids,
        "unknownModIds": unknown_ids,
        **change_plan_preview(changes, int(args.get("max_plan_preview", 50))),
        "backupBeforeApply": bool(args.get("backup_before_apply", True)),
        "backupPath": backup_path,
        "applied": bool(apply_result),
        "applyBatches": apply_result.get("batchCount") if apply_result else None,
        "vortex_exe": apply_result["vortex_exe"] if apply_result else snapshot["vortex_exe"],
        "notes": [
            "This only changes Vortex profile state. It does not delete mods.",
            "Close Vortex before apply=true. By default this tool refuses writes while Vortex.exe is running.",
            "When apply=true, this writes a Vortex profile backup first unless backup_before_apply=false.",
            "Open Vortex afterward, switch to the profile if needed, and deploy mods before launching Skyrim.",
        ],
    }


FINDING_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def add_finding(
    findings: List[Dict[str, Any]],
    severity: str,
    code: str,
    message: str,
    next_action: str,
    evidence: Any = None,
) -> None:
    item = {
        "severity": severity,
        "code": code,
        "message": message,
        "nextAction": next_action,
    }
    if evidence is not None:
        item["evidence"] = evidence
    findings.append(item)


def sort_findings(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        findings,
        key=lambda item: (FINDING_SEVERITY_ORDER.get(str(item.get("severity")), 9), str(item.get("code"))),
    )


def report_status(section: Any) -> str:
    if isinstance(section, dict) and "error" in section:
        return "error"
    return "ok"


def skyrim_modded_play_report(args: Dict[str, Any]) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    sections: Dict[str, Any] = {}

    try:
        sections["environment"] = detect_environment(args)
    except Exception as exc:
        sections["environment"] = {"error": str(exc)}
        add_finding(findings, "critical", "environment_failed", str(exc), "Fix basic path detection first.")

    try:
        sections["fileHealth"] = skyrim_file_health(args)
    except Exception as exc:
        sections["fileHealth"] = {"error": str(exc)}
        add_finding(findings, "high", "file_health_failed", str(exc), "Pass skyrim_dir explicitly and rerun.")

    try:
        sections["profiles"] = vortex_profile_report(args)
    except Exception as exc:
        sections["profiles"] = {"error": str(exc)}
        add_finding(
            findings,
            "medium",
            "profile_report_failed",
            str(exc),
            "Pass vortex_exe, close Vortex if needed, and rerun profile detection.",
        )

    try:
        sections["deployment"] = vortex_profile_deployment_report(args)
    except Exception as exc:
        sections["deployment"] = {"error": str(exc)}
        add_finding(
            findings,
            "high",
            "deployment_report_failed",
            str(exc),
            "Make sure Vortex is installed, Skyrim SE is detected, and staging_dir/vortex_exe are correct.",
        )

    try:
        sections["plugins"] = plugin_report(args)
    except Exception as exc:
        sections["plugins"] = {"error": str(exc)}
        add_finding(findings, "high", "plugin_report_failed", str(exc), "Pass skyrim_dir and staging_dir explicitly.")

    try:
        sections["ini"] = ini_report(args)
    except Exception as exc:
        sections["ini"] = {"error": str(exc)}
        add_finding(
            findings,
            "low",
            "ini_report_failed",
            str(exc),
            "Launch Skyrim once so the INI folder exists, or pass my_games_dir.",
        )

    env = sections.get("environment") if isinstance(sections.get("environment"), dict) else {}
    for issue in env.get("issues", []) if isinstance(env, dict) else []:
        severity = "high" if "SkyrimSE.exe" in issue or "SKSE64" in issue else "medium"
        add_finding(findings, severity, "environment_issue", issue, "Fix the detected path/setup issue, then rerun.")

    file_health = sections.get("fileHealth") if isinstance(sections.get("fileHealth"), dict) else {}
    for issue in file_health.get("issues", []) if isinstance(file_health, dict) else []:
        if "voice archive" in issue or "Sounds.bsa" in issue:
            add_finding(
                findings,
                "high",
                "audio_archives_missing",
                issue,
                "Verify Skyrim SE files in Steam. On Proton/Wine, also install the XAudio/XACT workaround if voices are still silent after archives exist.",
            )
        elif "SKSE" in issue or "skse64" in issue:
            add_finding(
                findings,
                "high",
                "skse_incomplete",
                issue,
                "Install the SKSE build that matches your Skyrim runtime, with loader/DLLs beside SkyrimSE.exe and scripts under Data\\Scripts.",
            )
        else:
            add_finding(findings, "medium", "game_files_issue", issue, "Verify Skyrim SE files and rerun.")

    deployment = sections.get("deployment") if isinstance(sections.get("deployment"), dict) else {}
    if isinstance(deployment, dict) and "error" not in deployment:
        for issue in deployment.get("issues", []):
            severity = "high" if "not present in Skyrim Data" in issue or "not enabled in plugins.txt" in issue else "medium"
            next_action = "In Vortex, select the intended profile, enable the missing plugins, then click Deploy Mods."
            add_finding(findings, severity, "profile_deployment_issue", issue, next_action)
        missing_count = len(deployment.get("pluginsFromEnabledModsMissingFromData", []))
        disabled_count = len(deployment.get("pluginsFromEnabledModsNotEnabledInPluginsTxt", []))
        stale_count = len(deployment.get("enabledPluginsTxtNotSeenInProfile", []))
        if missing_count:
            add_finding(
                findings,
                "high",
                "enabled_profile_plugins_not_deployed",
                f"{missing_count} plugin(s) from enabled profile mods are not in Skyrim Data.",
                "Click Deploy Mods in Vortex and confirm the game path/staging path are correct.",
                deployment.get("pluginsFromEnabledModsMissingFromData", [])[:20],
            )
        if disabled_count:
            add_finding(
                findings,
                "high",
                "enabled_profile_plugins_disabled",
                f"{disabled_count} plugin(s) from enabled profile mods are not enabled in plugins.txt.",
                "Open Vortex Plugins, enable the plugins, sort if needed, then deploy.",
                deployment.get("pluginsFromEnabledModsNotEnabledInPluginsTxt", [])[:20],
            )
        if stale_count:
            add_finding(
                findings,
                "medium",
                "plugins_txt_may_be_stale",
                f"{stale_count} enabled plugins.txt entrie(s) were not seen in the selected Vortex profile.",
                "Confirm the active Vortex profile is the one you launch with, then deploy again.",
                deployment.get("enabledPluginsTxtNotSeenInProfile", [])[:40],
            )

    plugins = sections.get("plugins") if isinstance(sections.get("plugins"), dict) else {}
    if isinstance(plugins, dict) and "error" not in plugins:
        missing_enabled = plugins.get("missingEnabledPlugins", [])
        missing_masters = plugins.get("missingMasters", [])
        if missing_enabled:
            add_finding(
                findings,
                "high",
                "plugins_txt_points_to_missing_files",
                f"{len(missing_enabled)} enabled plugin(s) in plugins.txt are missing on disk.",
                "Deploy in Vortex, or disable/remove stale plugins from the active profile.",
                missing_enabled[:40],
            )
        if missing_masters:
            add_finding(
                findings,
                "critical",
                "missing_plugin_masters",
                f"{len(missing_masters)} plugin master requirement(s) are missing.",
                "Install/enable the required master mods or disable the dependent plugins before launching the save.",
                missing_masters[:40],
            )

    ini = sections.get("ini") if isinstance(sections.get("ini"), dict) else {}
    if isinstance(ini, dict) and "error" not in ini:
        failed_ini = [rec for rec in ini.get("recommendations", []) if not rec.get("ok")]
        if failed_ini:
            add_finding(
                findings,
                "low",
                "ini_recommendations_not_applied",
                f"{len(failed_ini)} Skyrim INI recommendation(s) are not applied.",
                "Run apply_ini_fixes as a dry-run first, then with dry_run=false only if you approve.",
                failed_ini,
            )

    if bool(args.get("include_nexus_metadata", False)):
        try:
            sections["nexusUpdates"] = nexus_update_report(args)
            nexus_updates = sections["nexusUpdates"]
            if not nexus_updates.get("available"):
                add_finding(
                    findings,
                    "low",
                    "nexus_metadata_unavailable",
                    nexus_updates.get("notes", ["Nexus metadata is unavailable."])[0],
                    "Set NEXUS_MODS_API_KEY if you want update/source metadata. Local diagnosis can continue without it.",
                )
            elif nexus_updates.get("staleCount"):
                add_finding(
                    findings,
                    "medium",
                    "nexus_updates_available",
                    f"{nexus_updates.get('staleCount')} locally identified Nexus mod(s) have a different current Nexus version.",
                    "Review changelogs in Vortex/Nexus before updating; do not auto-update a working collection blindly.",
                    nexus_updates.get("staleMods", [])[:20],
                )
            if nexus_updates.get("missingSourceMetadataCount"):
                add_finding(
                    findings,
                    "low",
                    "nexus_source_metadata_missing",
                    f"{nexus_updates.get('missingSourceMetadataCount')} staged mod(s) could not be mapped to a Nexus mod id.",
                    "This is common for local/manual imports; use MD5 lookup or Vortex metadata if exact source matters.",
                    nexus_updates.get("missingSourceMetadata", [])[:20],
                )
            if nexus_updates.get("skippedLookupLimitCount"):
                add_finding(
                    findings,
                    "low",
                    "nexus_lookup_limit_reached",
                    f"{nexus_updates.get('skippedLookupLimitCount')} Nexus-sourced mod(s) were skipped by the lookup limit.",
                    "Increase nexus_max_lookup_mods for a fuller, slower update/source metadata pass.",
                    nexus_updates.get("skippedLookupLimit", [])[:20],
                )
        except Exception as exc:
            sections["nexusUpdates"] = {"error": str(exc)}
            add_finding(
                findings,
                "low",
                "nexus_update_report_failed",
                str(exc),
                "Keep using local diagnostics; rerun Nexus metadata checks after configuring the API key/cache.",
            )

    if bool(args.get("include_conflicts", False)):
        try:
            sections["conflictPlan"] = suggest_conflict_fixes(args)
            sensitive = [
                action
                for action in sections["conflictPlan"].get("actions", [])
                if action.get("type") in {"missing_master", "sensitive_file_conflict"}
            ]
            if sensitive:
                add_finding(
                    findings,
                    "medium",
                    "sensitive_conflicts",
                    f"{len(sensitive)} missing-master or sensitive-conflict action(s) were found.",
                    "Review Vortex Conflicts and Plugins before launching a real save.",
                    sensitive[:40],
                )
        except Exception as exc:
            sections["conflictPlan"] = {"error": str(exc)}

    findings = sort_findings(findings)
    highest = findings[0].get("severity", "unknown") if findings else "none"
    ok_to_launch_modded = highest not in {"critical", "high"}
    recommended_actions = []
    seen_actions: set[str] = set()
    for finding in findings:
        action = finding.get("nextAction")
        if action and action not in seen_actions:
            recommended_actions.append(action)
            seen_actions.add(action)

    return {
        "summary": {
            "okToLaunchModded": ok_to_launch_modded,
            "highestSeverity": highest,
            "findingCount": len(findings),
            "sectionStatus": {key: report_status(value) for key, value in sections.items()},
        },
        "findings": findings,
        "recommendedActions": recommended_actions,
        "sections": sections,
        "notes": [
            "This tool is read-only. It does not change Vortex, Skyrim, plugins.txt, or INI files.",
            "For modded Skyrim SE, launch through SKSE after Vortex deploys the intended active profile.",
        ],
    }


def suggest_conflict_fixes(args: Dict[str, Any]) -> Dict[str, Any]:
    conflicts = analyze_conflicts({**args, "hash_files": args.get("hash_files", False)})
    plugins = plugin_report(args) if find_skyrim_dir(args.get("skyrim_dir")) else {}
    actions = []
    for missing in plugins.get("missingMasters", []):
        actions.append(
            {
                "priority": "high",
                "type": "missing_master",
                "message": f"{missing['plugin']} requires missing master {missing['missingMaster']}. Install/enable the required mod or disable the dependent plugin.",
            }
        )
    for item in conflicts.get("conflicts", [])[:80]:
        if item["sameHash"] is True:
            actions.append(
                {
                    "priority": "low",
                    "type": "duplicate_same_file",
                    "relativePath": item["relativePath"],
                    "message": "Multiple mods provide the exact same file. Usually safe, but redundant.",
                }
            )
        elif item["kind"] in {"script", "skse_plugin", "interface"}:
            explanation = item.get("explanation", {})
            actions.append(
                {
                    "priority": "high" if explanation.get("risk") == "high" else "medium",
                    "type": "sensitive_file_conflict",
                    "relativePath": item["relativePath"],
                    "providers": [p["mod"] for p in item["providers"]],
                    "message": explanation.get("impact")
                    or "Conflict touches scripts, SKSE DLLs, or UI files. Pick the intended winner in Vortex's Conflicts view.",
                    "safeAction": explanation.get("safeAction"),
                    "winnerNote": explanation.get("winnerNote"),
                }
            )
    return {
        "actions": actions,
        "notes": [
            "This MCP does not delete mods or rewrite Vortex conflict rules automatically.",
            "Use these actions as an assistant-readable repair plan, then confirm changes in Vortex.",
        ],
    }


def safe_session_default_path(args: Dict[str, Any]) -> Path:
    output_path = expand_path(args.get("output_path"))
    if output_path:
        return output_path
    docs = default_documents() or Path.cwd()
    return docs / "vortex-skyrimse-mcp-reports" / f"safe-session-{now_stamp()}.md"


def collect_section(sections: Dict[str, Any], key: str, func: Callable[[Dict[str, Any]], Dict[str, Any]], args: Dict[str, Any]) -> None:
    try:
        sections[key] = func(args)
    except Exception as exc:
        sections[f"{key}Error"] = str(exc)
        log_event("support", "safe_session_section_error", {"section": key, "error": str(exc)})


def safe_session_findings(sections: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    section_error_actions = {
        "setupValidationError": ("high", "Fix basic path detection first, then rerun the safe session."),
        "skyrimModdedPlayError": ("high", "Pass explicit skyrim_dir, staging_dir, vortex_exe, or local_appdata and rerun."),
        "inGameIssueError": ("medium", "Rerun with simpler issue text, screenshot/OCR popup text, or console FormID if available."),
        "skyrimRuntimeLogsError": ("medium", "Rerun after launching Skyrim once, reproducing the issue, or passing my_games_dir/skyrim_dir explicitly."),
        "nexusUpdateReportError": ("low", "Keep using local diagnostics; rerun Nexus metadata checks after configuring the API key/cache."),
        "logStatusError": ("low", "Pass log_dir explicitly or rerun after MCP Doctor creates logs."),
    }
    for key, (severity, action) in section_error_actions.items():
        if sections.get(key):
            add_finding(findings, severity, key[:-5].lower() + "_failed", str(sections[key]), action)
    setup = sections.get("setupValidation")
    if isinstance(setup, dict):
        for blocker in setup.get("blockers", []):
            add_finding(findings, "high", "setup_blocker", str(blocker), "Fix this setup blocker before applying changes.")
    if sections.get("profileBackupError"):
        add_finding(
            findings,
            "medium",
            "profile_backup_failed",
            str(sections["profileBackupError"]),
            "Profile backup failed; pass vortex_exe or create a backup from Vortex before profile experiments.",
        )
    play = sections.get("skyrimModdedPlay")
    if isinstance(play, dict):
        for item in play.get("findings", [])[:20]:
            if isinstance(item, dict):
                findings.append(item)
    issue = sections.get("inGameIssue")
    if isinstance(issue, dict):
        scan = issue.get("scan") if isinstance(issue.get("scan"), dict) else {}
        if scan.get("timedOut"):
            add_finding(
                findings,
                "medium",
                "in_game_issue_scan_partial",
                "The in-game issue scan hit its time budget and returned partial results.",
                "Increase timeout_seconds, lower max_mods, or provide stronger evidence before changing mods.",
            )
        quality = issue.get("diagnosticQuality") if isinstance(issue.get("diagnosticQuality"), dict) else {}
        if quality.get("level") == "weak":
            add_finding(
                findings,
                "low",
                "in_game_issue_evidence_weak",
                str(quality.get("reason") or "The in-game issue evidence is weak."),
                "Use nextBestInputs from the report, or rerun with scan_mode=deep before testing candidates.",
            )
        candidates = issue.get("candidates", [])
        if candidates:
            top = candidates[0]
            add_finding(
                findings,
                "medium",
                "in_game_issue_candidate",
                f"Top in-game issue candidate: {top.get('mod')} ({top.get('confidence')} confidence).",
                "Confirm in xEdit or a cloned Vortex profile before changing anything.",
                {
                    "mod": top.get("mod"),
                    "confidence": top.get("confidence"),
                    "matchedTerms": top.get("matchedTerms"),
                    "vortexModId": top.get("vortexModId"),
                },
            )
    xedit = sections.get("xeditDiagnostics")
    if isinstance(xedit, dict) and (xedit.get("formIdHint") or xedit.get("pluginName")):
        target = xedit.get("pluginName")
        if not target and isinstance(xedit.get("formIdHint"), dict):
            target = xedit["formIdHint"].get("pluginName")
        if target:
            add_finding(
                findings,
                "low",
                "xedit_read_only_target",
                f"xEdit/SSEEdit inspection target: {target}.",
                "Use xEdit/SSEEdit read-only first; do not save plugin edits from this diagnostic alone.",
                {"pluginName": target, "xeditExe": xedit.get("xeditExe")},
            )
    collection = sections.get("vortexCollection")
    if isinstance(collection, dict) and collection.get("available"):
        add_finding(
            findings,
            "low",
            "vortex_collection_state_seen",
            f"Vortex exposed {collection.get('collectionStateCount')} collection-like state item(s) and {collection.get('modCollectionMarkerCount')} mod marker(s).",
            "Use this for collection mismatch context only; do not auto-install or remove collection mods.",
        )
    runtime_logs = sections.get("skyrimRuntimeLogs")
    if isinstance(runtime_logs, dict):
        fresh = runtime_logs.get("freshLogStatus") if isinstance(runtime_logs.get("freshLogStatus"), dict) else {}
        if fresh and fresh.get("fresh") is False:
            add_finding(
                findings,
                "low",
                "runtime_logs_stale",
                str(fresh.get("note") or "The newest Skyrim runtime log may be stale."),
                "Reproduce the issue in Skyrim, quit, then rerun skyrim_runtime_log_report.",
                fresh,
            )
        groups = runtime_logs.get("issueGroups", []) if isinstance(runtime_logs.get("issueGroups"), list) else []
        for group in groups[:8]:
            if isinstance(group, dict) and group.get("highestSeverity") in {"critical", "high"}:
                add_finding(
                    findings,
                    str(group.get("highestSeverity")),
                    str(group.get("code") or "runtime_issue_group"),
                    f"{group.get('title')} ({group.get('count')} log hit(s)).",
                    str(group.get("nextAction") or "Read the runtime log group before changing mods."),
                    group,
                )
        for item in runtime_logs.get("findings", [])[:12]:
            if not isinstance(item, dict):
                continue
            severity = str(item.get("severity") or "info")
            if severity not in {"critical", "high", "medium"}:
                continue
            add_finding(
                findings,
                severity,
                "skyrim_runtime_log_finding",
                f"{item.get('logName') or 'runtime log'}: {item.get('line')}",
                "Inspect the referenced mod/config first; use exact-text config patches with backups only after reading the file.",
                {
                    "log": item.get("log"),
                    "references": item.get("references"),
                    "stagedMatches": item.get("stagedMatches"),
                },
            )
        for candidate in runtime_logs.get("configCandidates", [])[:8]:
            if isinstance(candidate, dict):
                validation = candidate.get("validation") if isinstance(candidate.get("validation"), dict) else {}
                health = validation.get("healthFindings") if isinstance(validation.get("healthFindings"), list) else []
                patch_suggestions = (
                    validation.get("suggestedTextPatches") if isinstance(validation.get("suggestedTextPatches"), list) else []
                )
                detail = {"candidate": candidate, "validation": validation}
                add_finding(
                    findings,
                    "medium",
                    "runtime_config_candidate",
                    f"Runtime logs point to config candidate {candidate.get('relativePath')} from {candidate.get('mod')}.",
                    "Use config_file_report/read_text_file, then apply_config_text_patch dry-run with exact old/new text.",
                    detail,
                )
                for health_item in health[:4]:
                    if isinstance(health_item, dict):
                        add_finding(
                            findings,
                            str(health_item.get("severity") or "medium"),
                            str(health_item.get("code") or "config_health_finding"),
                            f"{candidate.get('relativePath')}: {health_item.get('message')}",
                            str(health_item.get("nextAction") or "Read the config file before patching."),
                            detail,
                        )
                if patch_suggestions:
                    add_finding(
                        findings,
                        "medium",
                        "config_text_patch_suggestion",
                        f"{candidate.get('relativePath')}: {len(patch_suggestions)} exact-text patch suggestion(s) are available.",
                        "Preview apply_config_text_patch with dry_run=true and apply only after approval.",
                        {"candidate": candidate, "suggestedTextPatches": patch_suggestions[:4]},
                    )
    nexus_updates = sections.get("nexusUpdateReport") or sections.get("nexusUpdates")
    if isinstance(nexus_updates, dict):
        if not nexus_updates.get("available") and nexus_updates.get("notes"):
            add_finding(
                findings,
                "low",
                "nexus_metadata_unavailable",
                str(nexus_updates.get("notes", ["Nexus metadata is unavailable."])[0]),
                "Set NEXUS_MODS_API_KEY if you want Nexus metadata. Local diagnostics still work without it.",
            )
        if nexus_updates.get("staleCount"):
            add_finding(
                findings,
                "medium",
                "nexus_updates_available",
                f"{nexus_updates.get('staleCount')} locally identified Nexus mod(s) have a different current Nexus version.",
                "Review changelogs and collection compatibility before updating.",
                nexus_updates.get("staleMods", [])[:20],
            )
        if nexus_updates.get("skippedLookupLimitCount"):
            add_finding(
                findings,
                "low",
                "nexus_lookup_limit_reached",
                f"{nexus_updates.get('skippedLookupLimitCount')} Nexus-sourced mod(s) were skipped by the lookup limit.",
                "Increase nexus_max_lookup_mods only when you need a fuller metadata pass.",
                nexus_updates.get("skippedLookupLimit", [])[:20],
            )
    return sort_findings(findings)


def section_status_map(sections: Dict[str, Any]) -> Dict[str, str]:
    status: Dict[str, str] = {}
    for key, value in sections.items():
        if key.endswith("Error"):
            status[key[:-5]] = "error"
        elif key not in status:
            status[key] = report_status(value)
    return status


def safe_session_markdown(session: Dict[str, Any]) -> str:
    lines = [
        "# Vortex Skyrim SE Safe Session",
        "",
        f"- Generated: {session.get('generatedAt')}",
        f"- Server: {session.get('server')} {session.get('version')}",
        f"- Dry run only: {session.get('dryRunOnly')}",
        f"- Report JSON: {session.get('json_path') or 'not written'}",
        "",
        "## Summary",
        "",
    ]
    summary = session.get("summary", {}) if isinstance(session.get("summary"), dict) else {}
    for key in ("highestSeverity", "findingCount", "ready", "backupPath"):
        if key in summary:
            lines.append(f"- {key}: {summary.get(key)}")
    for key in ("performanceMode", "responseMode"):
        if key in summary:
            lines.append(f"- {key}: {summary.get(key)}")
    section_status = summary.get("sectionStatus")
    if isinstance(section_status, dict) and section_status:
        status_text = ", ".join(f"{key}={value}" for key, value in section_status.items())
        lines.append(f"- sectionStatus: {status_text}")

    findings = session.get("findings", []) if isinstance(session.get("findings"), list) else []
    lines.extend(["", "## Findings", ""])
    if findings:
        for item in findings[:30]:
            severity = item.get("severity", "info")
            code = item.get("code", "finding")
            message = item.get("message", "")
            action = item.get("nextAction", "")
            lines.append(f"- [{severity}] {code}: {message}")
            if action:
                lines.append(f"  Next: {action}")
    else:
        lines.append("- No high-signal findings were generated.")

    sections = session.get("sections", {}) if isinstance(session.get("sections"), dict) else {}
    setup = sections.get("setupValidation")
    if isinstance(setup, dict):
        lines.extend(["", "## Setup", ""])
        if setup.get("blockers"):
            for blocker in setup.get("blockers", []):
                lines.append(f"- Blocker: {blocker}")
        else:
            lines.append("- No setup blockers reported.")

    backup = sections.get("profileBackup")
    lines.extend(["", "## Backup", ""])
    if isinstance(backup, dict):
        lines.append(f"- Profile backup: {backup.get('output_path')}")
        lines.append(f"- Profiles backed up: {backup.get('profileCount')}")
    elif sections.get("profileBackupError"):
        lines.append(f"- Backup error: {sections.get('profileBackupError')}")
    else:
        lines.append("- Profile backup was not requested.")

    issue = sections.get("inGameIssue")
    if isinstance(issue, dict):
        lines.extend(["", "## In-Game Issue Candidates", ""])
        scan = issue.get("scan") if isinstance(issue.get("scan"), dict) else {}
        if scan:
            lines.append(f"- Scan mode: {scan.get('mode')} (timed out: {scan.get('timedOut')})")
        quality = issue.get("diagnosticQuality") if isinstance(issue.get("diagnosticQuality"), dict) else {}
        if quality:
            lines.append(f"- Diagnostic quality: {quality.get('level')} - {quality.get('reason')}")
        candidates = issue.get("candidates", [])
        if candidates:
            for candidate in candidates[:10]:
                lines.append(
                    f"- {candidate.get('mod')} ({candidate.get('confidence')} confidence, score {candidate.get('score')})"
                )
                reason = candidate.get("likelyReason")
                if reason:
                    lines.append(f"  Why: {reason}")
        else:
            lines.append("- No candidates found. Try screenshot/OCR popup text, console FormID, or deep_scan_files=true.")

    xedit = sections.get("xeditDiagnostics")
    if isinstance(xedit, dict):
        lines.extend(["", "## xEdit/SSEEdit", ""])
        lines.append(f"- Detected: {xedit.get('available')}")
        if xedit.get("xeditExe"):
            lines.append(f"- Executable: {xedit.get('xeditExe')}")
        if xedit.get("pluginName"):
            lines.append(f"- Suggested plugin: {xedit.get('pluginName')}")
        hint = xedit.get("formIdHint") if isinstance(xedit.get("formIdHint"), dict) else {}
        if hint:
            lines.append(f"- FormID hint: {hint.get('formId')} -> {hint.get('pluginName') or 'unknown'} ({hint.get('confidence')})")
        lines.append("- This section is read-only. Do not save plugin edits from this report alone.")

    collection = sections.get("vortexCollection")
    if isinstance(collection, dict):
        lines.extend(["", "## Vortex Collection State", ""])
        lines.append(f"- Collection-like state found: {collection.get('collectionStateCount')}")
        lines.append(f"- Mod collection markers found: {collection.get('modCollectionMarkerCount')}")
        for item in collection.get("collectionStates", [])[:8]:
            lines.append(f"- {item.get('name') or item.get('slug') or item.get('id') or item.get('path')}")

    runtime_logs = sections.get("skyrimRuntimeLogs")
    if isinstance(runtime_logs, dict):
        lines.extend(["", "## Skyrim Runtime Logs", ""])
        lines.append(f"- Logs scanned: {runtime_logs.get('logCount')}")
        lines.append(f"- Findings: {runtime_logs.get('findingCount')}")
        fresh = runtime_logs.get("freshLogStatus") if isinstance(runtime_logs.get("freshLogStatus"), dict) else {}
        if fresh:
            lines.append(f"- Fresh logs: {fresh.get('fresh')} (newest age hours: {fresh.get('newestAgeHours')})")
            if fresh.get("note"):
                lines.append(f"  Note: {fresh.get('note')}")
        severity_counts = runtime_logs.get("severityCounts")
        if isinstance(severity_counts, dict) and severity_counts:
            lines.append("- Severity counts: " + ", ".join(f"{key}={value}" for key, value in severity_counts.items()))
        groups = runtime_logs.get("issueGroups", []) if isinstance(runtime_logs.get("issueGroups"), list) else []
        if groups:
            lines.append("- Issue groups:")
            for group in groups[:8]:
                if isinstance(group, dict):
                    lines.append(f"  - [{group.get('highestSeverity')}] {group.get('title')} ({group.get('count')} hit(s))")
        for item in runtime_logs.get("findings", [])[:8]:
            if isinstance(item, dict):
                lines.append(f"- [{item.get('severity')}] {item.get('logName')}: {item.get('line')}")
                matches = item.get("stagedMatches")
                if isinstance(matches, list) and matches:
                    first = matches[0]
                    if isinstance(first, dict):
                        lines.append(f"  Match: {first.get('mod')} -> {first.get('relativePath')}")
        candidates = runtime_logs.get("configCandidates", [])
        if candidates:
            lines.append("- Config candidates:")
            for candidate in candidates[:8]:
                if isinstance(candidate, dict):
                    lines.append(f"  - {candidate.get('mod')}: {candidate.get('relativePath')}")
                    validation = candidate.get("validation") if isinstance(candidate.get("validation"), dict) else {}
                    if validation:
                        lines.append(
                            f"    validation: valid={validation.get('valid')}, healthFindings={validation.get('healthFindingCount')}, patchSuggestions={validation.get('suggestedTextPatchCount')}"
                        )
    elif sections.get("skyrimRuntimeLogsError"):
        lines.extend(["", "## Skyrim Runtime Logs", ""])
        lines.append(f"- Runtime log scan error: {sections.get('skyrimRuntimeLogsError')}")

    nexus_updates = sections.get("nexusUpdateReport") or sections.get("nexusUpdates")
    if isinstance(nexus_updates, dict):
        lines.extend(["", "## Nexus Metadata", ""])
        if not nexus_updates.get("available"):
            lines.append("- Nexus metadata was not available or not configured.")
            for note in nexus_updates.get("notes", [])[:3]:
                lines.append(f"  - {note}")
        else:
            lines.append(f"- Checked mods: {nexus_updates.get('checkedModCount')}")
            lines.append(f"- Version review candidates: {nexus_updates.get('staleCount')}")
            lines.append(f"- Missing source metadata: {nexus_updates.get('missingSourceMetadataCount')}")
            if nexus_updates.get("skippedLookupLimitCount"):
                lines.append(f"- Skipped by lookup limit: {nexus_updates.get('skippedLookupLimitCount')}")
            for item in nexus_updates.get("staleMods", [])[:10]:
                lines.append(
                    f"- {item.get('mod')}: local `{item.get('localVersion')}`, Nexus `{item.get('currentVersion')}`"
                )

    lines.extend(["", "## Next Actions", ""])
    next_actions = session.get("nextActions", []) if isinstance(session.get("nextActions"), list) else []
    if next_actions:
        for action in next_actions:
            lines.append(f"- {action}")
    else:
        lines.append("- Keep this report with any bug report or OpenClaw follow-up.")

    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- This report did not apply changes.",
            "- Do not delete mods from this report alone.",
            "- Use a cloned profile for tests, deploy in Vortex, then verify in game.",
            "",
        ]
    )
    return "\n".join(lines)


def safe_session_report(args: Dict[str, Any]) -> Dict[str, Any]:
    args = apply_performance_defaults(args)
    markdown_path = safe_session_default_path(args)
    json_path = expand_path(args.get("session_json_path"))
    if not json_path:
        json_path = markdown_path.with_suffix(".json")
    if json_path == markdown_path:
        json_path = markdown_path.with_name(f"{markdown_path.name}.json")
    include_profile_backup = bool(args.get("include_profile_backup", True))
    include_play_report = bool(args.get("include_play_report", True))
    include_logs = bool(args.get("include_logs", True))
    include_runtime_logs = bool(args.get("include_runtime_logs", True))
    include_xedit_report = bool(args.get("include_xedit_report", False))
    include_collection_report = bool(args.get("include_collection_report", False))
    redact_user_paths = bool(args.get("redact_user_paths", True))
    sections: Dict[str, Any] = {}

    collect_section(sections, "setupValidation", validate_setup, args)
    if include_profile_backup:
        backup_args = {**args, "include_all_profiles": bool(args.get("include_all_profiles", True))}
        backup_args.pop("output_path", None)
        if not backup_args.get("backup_dir") and not backup_args.get("backup_path"):
            backup_args["backup_dir"] = str(markdown_path.parent / "profile-backups")
        collect_section(sections, "profileBackup", vortex_profile_backup, backup_args)
    if include_play_report:
        play_args = {**args, "include_conflicts": bool(args.get("include_conflicts", False))}
        collect_section(sections, "skyrimModdedPlay", skyrim_modded_play_report, play_args)
        if compact_response_requested(args) and isinstance(sections.get("skyrimModdedPlay"), dict):
            sections["skyrimModdedPlay"] = compact_play_report(sections["skyrimModdedPlay"])
    if any(args.get(key) for key in ("description", "location", "object", "form_id", "cell", "base_object", "popup_text", "extra_terms", "issue_kind")):
        collect_section(sections, "inGameIssue", in_game_issue_report, args)
    if include_xedit_report or args.get("form_id") or args.get("plugin_name"):
        collect_section(sections, "xeditDiagnostics", xedit_diagnostics_report, args)
    if include_collection_report:
        collect_section(sections, "vortexCollection", vortex_collection_report, args)
    if bool(args.get("include_nexus_metadata", False)):
        collect_section(sections, "nexusUpdateReport", nexus_update_report, args)
    if include_runtime_logs:
        collect_section(sections, "skyrimRuntimeLogs", skyrim_runtime_log_report, args)
    if include_logs:
        collect_section(sections, "logStatus", log_status, {"log_dir": args.get("log_dir"), "max_files": args.get("max_log_files", 12)})

    findings = safe_session_findings(sections)
    highest = findings[0].get("severity", "unknown") if findings else "none"
    setup = sections.get("setupValidation") if isinstance(sections.get("setupValidation"), dict) else {}
    backup = sections.get("profileBackup") if isinstance(sections.get("profileBackup"), dict) else {}
    next_actions = []
    for item in findings:
        action = item.get("nextAction")
        if action and action not in next_actions:
            next_actions.append(action)
    if not next_actions:
        next_actions.append("Keep this report as a baseline before making changes.")
    issue_section = sections.get("inGameIssue") if isinstance(sections.get("inGameIssue"), dict) else {}
    if isinstance(issue_section, dict) and issue_section.get("candidates"):
        next_actions.append("If testing a mod candidate, use a cloned Vortex profile and deploy before launching Skyrim.")
    else:
        next_actions.append("Use a cloned Vortex profile for experiments, deploy in Vortex, then verify in game.")

    session: Dict[str, Any] = {
        "generatedAt": iso_now(),
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "dryRunOnly": True,
        "output_path": str(markdown_path),
        "json_path": str(json_path),
        "summary": {
            "ready": setup.get("ready") if isinstance(setup, dict) else None,
            "highestSeverity": highest,
            "findingCount": len(findings),
            "backupPath": backup.get("output_path") if isinstance(backup, dict) else None,
            "sectionStatus": section_status_map(sections),
            "performanceMode": normalized_performance_mode(args),
            "responseMode": normalized_response_mode(args),
        },
        "findings": findings,
        "nextActions": next_actions,
        "sections": sections,
        "notes": [
            "This is a no-change safe session report.",
            "Profile backup may fail if Vortex.exe is not detected; pass vortex_exe or back up in Vortex.",
            "Use performance_mode=slow_model for smaller outputs on weaker OpenClaw models.",
            "Use include_nexus_metadata=true with NEXUS_MODS_API_KEY for optional Nexus source/update metadata.",
            "Use include_xedit_report=true for read-only xEdit/SSEEdit target hints.",
            "Use include_collection_report=true to inspect collection-like state exposed by Vortex.",
            "Runtime log scanning checks recent Skyrim/Papyrus/SKSE/crash logs and points config-like errors at staged files when possible.",
            "Use deep_scan_files=true for a slower second pass on weak in-game issue results.",
        ],
    }
    session_to_write = redact_paths_in_value(session) if redact_user_paths else session
    write_text(json_path, json.dumps(session_to_write, indent=2, ensure_ascii=False, default=str))
    write_text(markdown_path, safe_session_markdown(session_to_write))
    log_event(
        "support",
        "safe_session_report_written",
        {"output_path": str(markdown_path), "json_path": str(json_path), "sections": list(sections.keys())},
    )
    return {
        "output_path": str(markdown_path),
        "json_path": str(json_path),
        "redactedUserPaths": redact_user_paths,
        "summary": session_to_write["summary"],
        "nextActions": session_to_write["nextActions"],
        "sections": list(sections.keys()),
    }


def skyrim_diagnostics_report(args: Dict[str, Any]) -> Dict[str, Any]:
    tuned = dict(args)
    tuned.setdefault("performance_mode", "slow_model")
    tuned.setdefault("include_nexus_metadata", bool(nexus_api_key(tuned)))
    tuned.setdefault("include_xedit_report", bool(tuned.get("form_id") or tuned.get("plugin_name")))
    if not tuned.get("output_path"):
        docs = default_documents() or Path.cwd()
        tuned["output_path"] = str(docs / "vortex-skyrimse-mcp-reports" / f"skyrim-diagnostics-{now_stamp()}.md")
    return safe_session_report(tuned)


def write_report(args: Dict[str, Any]) -> Dict[str, Any]:
    output_path = expand_path(args.get("output_path"))
    if not output_path:
        raise ToolError("output_path is required.")
    report = {
        "generatedAt": _dt.datetime.now().isoformat(),
        "environment": detect_environment(args),
    }
    try:
        report["ini"] = ini_report(args)
    except Exception as exc:
        report["iniError"] = str(exc)
    try:
        report["plugins"] = plugin_report(args)
    except Exception as exc:
        report["pluginsError"] = str(exc)
    try:
        report["redundancy"] = redundant_mod_report(args)
    except Exception as exc:
        report["redundancyError"] = str(exc)
    try:
        report["conflicts"] = analyze_conflicts(args)
    except Exception as exc:
        report["conflictsError"] = str(exc)
    if args.get("include_mod_inventory", False):
        try:
            report["inventory"] = inventory_mods(args)
        except Exception as exc:
            report["inventoryError"] = str(exc)
    if args.get("include_vortex_profiles", False):
        try:
            report["vortexProfiles"] = vortex_profile_report(args)
        except Exception as exc:
            report["vortexProfilesError"] = str(exc)
    if args.get("include_vortex_deployment", False):
        try:
            report["vortexProfileDeployment"] = vortex_profile_deployment_report(args)
        except Exception as exc:
            report["vortexProfileDeploymentError"] = str(exc)
    if args.get("include_play_report", False):
        try:
            report["skyrimModdedPlay"] = skyrim_modded_play_report(args)
        except Exception as exc:
            report["skyrimModdedPlayError"] = str(exc)
    write_text(output_path, json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return {"output_path": str(output_path), "sections": list(report.keys())}


def log_status(args: Dict[str, Any]) -> Dict[str, Any]:
    log_dir = default_log_dir(args.get("log_dir"))
    max_files = int(args.get("max_files", 20))
    files = recent_log_files(log_dir, max_files)
    channels: Dict[str, int] = {}
    for path in files:
        channel = log_channel_from_name(path.name)
        channels[channel] = channels.get(channel, 0) + 1
    return {
        "log_dir": str(log_dir),
        "exists": log_dir.exists(),
        "environmentVariable": LOG_ENV_VAR,
        "channels": channels,
        "files": [log_file_summary(path) for path in files],
        "notes": [
            "Logs are JSONL for server/tool/vortex-cli/support channels, plus plain .log transcripts from MCP Doctor.",
            "Set VORTEX_SKYRIMSE_MCP_LOG_DIR to move logs to another folder.",
        ],
    }


def bug_report_bundle(args: Dict[str, Any]) -> Dict[str, Any]:
    args = apply_performance_defaults(args)
    output_path = expand_path(args.get("output_path"))
    if not output_path:
        docs = default_documents() or Path.cwd()
        output_path = docs / f"vortex-skyrimse-mcp-bug-report-{now_stamp()}.json"
    max_log_files = int(args.get("max_log_files", 12))
    max_log_bytes = int(args.get("max_log_bytes", LOG_TAIL_DEFAULT_BYTES))
    include_logs = bool(args.get("include_logs", True))
    include_profiles = bool(args.get("include_vortex_profiles", True))
    include_deployment = bool(args.get("include_vortex_deployment", True))
    include_play_report = bool(args.get("include_play_report", True))
    include_conflicts = bool(args.get("include_conflicts", False))
    include_xedit_report = bool(args.get("include_xedit_report", False))
    include_collection_report = bool(args.get("include_collection_report", False))
    include_runtime_logs = bool(args.get("include_runtime_logs", True))
    redact_user_paths = bool(args.get("redact_user_paths", True))
    zip_output = bool(args.get("zip_output", False))
    zip_path = expand_path(args.get("zip_path"))
    include_log_tails_in_zip = bool(args.get("include_log_tails_in_zip", True))
    log_dir = default_log_dir(args.get("log_dir"))
    log_files: List[Path] = []

    bundle: Dict[str, Any] = {
        "generatedAt": iso_now(),
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "output_path": str(output_path),
        "log_dir": str(log_dir),
        "performanceMode": normalized_performance_mode(args),
        "responseMode": normalized_response_mode(args),
        "privacyNote": "This bundle may include local Windows paths, mod names, plugin names, and recent MCP logs. Review before posting publicly.",
        "redactedUserPaths": redact_user_paths,
        "redactionNote": "User profile, AppData, and LocalAppData paths are replaced when redact_user_paths=true.",
        "bugReportTemplate": {
            "summary": "What did you expect OpenClaw/Vortex/Skyrim to do, and what happened instead?",
            "reproductionSteps": [
                "What command, MCP tool, or OpenClaw prompt did you run?",
                "Was Vortex open or closed?",
                "Which Vortex profile was active?",
                "Did you click Deploy Mods before launching Skyrim?",
                "Did this happen after installing a collection, changing profiles, or updating SKSE?",
            ],
            "attach": [
                "This JSON bundle",
                "Screenshots of Vortex errors if any",
                "The exact OpenClaw prompt that failed",
            ],
        },
        "agentInstructions": [
            "Start with findings/issues/errors before suggesting changes.",
            "Do not apply INI or Vortex profile writes unless the user explicitly approves.",
            "If Vortex profile or deployment sections failed, ask for explicit vortex_exe, skyrim_dir, staging_dir, or vortex_appdata paths.",
            "If logs show a Vortex CLI database lock, tell the user to close Vortex and rerun the same tool.",
            "If Skyrim runtime logs include configCandidates, read the candidate file before proposing an exact-text patch.",
        ],
    }

    try:
        bundle["setupValidation"] = validate_setup(args)
    except Exception as exc:
        bundle["setupValidationError"] = str(exc)

    try:
        bundle["environment"] = detect_environment(args)
    except Exception as exc:
        bundle["environmentError"] = str(exc)

    if include_play_report:
        try:
            play_args = {**args, "include_conflicts": include_conflicts}
            bundle["skyrimModdedPlay"] = skyrim_modded_play_report(play_args)
            if compact_response_requested(args) and isinstance(bundle.get("skyrimModdedPlay"), dict):
                bundle["skyrimModdedPlay"] = compact_play_report(bundle["skyrimModdedPlay"])
        except Exception as exc:
            bundle["skyrimModdedPlayError"] = str(exc)

    if any(args.get(key) for key in ("description", "location", "object", "form_id", "cell", "base_object", "popup_text", "extra_terms", "issue_kind")):
        try:
            bundle["inGameIssue"] = in_game_issue_report(args)
        except Exception as exc:
            bundle["inGameIssueError"] = str(exc)

    if bool(args.get("include_nexus_metadata", False)):
        try:
            bundle["nexusUpdateReport"] = nexus_update_report(args)
        except Exception as exc:
            bundle["nexusUpdateReportError"] = str(exc)

    if include_xedit_report or args.get("form_id") or args.get("plugin_name"):
        try:
            bundle["xeditDiagnostics"] = xedit_diagnostics_report(args)
        except Exception as exc:
            bundle["xeditDiagnosticsError"] = str(exc)

    if include_collection_report:
        try:
            bundle["vortexCollection"] = vortex_collection_report(args)
        except Exception as exc:
            bundle["vortexCollectionError"] = str(exc)

    if include_runtime_logs:
        try:
            bundle["skyrimRuntimeLogs"] = skyrim_runtime_log_report(args)
        except Exception as exc:
            bundle["skyrimRuntimeLogsError"] = str(exc)

    if include_profiles:
        try:
            bundle["vortexProfiles"] = vortex_profile_report(args)
        except Exception as exc:
            bundle["vortexProfilesError"] = str(exc)

    if include_deployment:
        try:
            bundle["vortexProfileDeployment"] = vortex_profile_deployment_report(args)
        except Exception as exc:
            bundle["vortexProfileDeploymentError"] = str(exc)

    try:
        bundle["plugins"] = plugin_report(args)
    except Exception as exc:
        bundle["pluginsError"] = str(exc)

    try:
        bundle["ini"] = ini_report(args)
    except Exception as exc:
        bundle["iniError"] = str(exc)

    if include_logs:
        log_files = recent_log_files(log_dir, max_log_files)
        bundle["logs"] = {
            "status": log_status({"log_dir": str(log_dir), "max_files": max_log_files}),
            "recentFiles": [log_file_summary(path, include_tail=True, max_tail_bytes=max_log_bytes) for path in log_files],
        }

    bundle_to_write = redact_paths_in_value(bundle) if redact_user_paths else bundle
    write_text(output_path, json.dumps(bundle_to_write, indent=2, ensure_ascii=False, default=str))
    zip_info = None
    if zip_output:
        if not zip_path:
            zip_path = output_path.with_suffix(".zip")
        zip_info = write_bug_report_zip(
            zip_path,
            output_path,
            bundle_to_write,
            log_files if include_logs else [],
            max_log_bytes,
            include_log_tails=include_log_tails_in_zip,
            redact=redact_user_paths,
        )
    log_event(
        "support",
        "bug_report_bundle_written",
        {
            "output_path": str(output_path),
            "zip_path": str(zip_path) if zip_info else None,
            "sections": list(bundle.keys()),
            "include_logs": include_logs,
            "redact_user_paths": redact_user_paths,
        },
    )
    result = {
        "output_path": str(output_path),
        "log_dir": str(log_dir),
        "redactedUserPaths": redact_user_paths,
        "sections": list(bundle.keys()),
        "nextSteps": [
            "Send this JSON file to the maintainer or ask OpenClaw to read it.",
            "Include what you clicked or prompted right before the failure.",
            "Review the privacy note before posting publicly.",
        ],
    }
    if zip_info:
        result["zip_path"] = zip_info["zip_path"]
        result["zipEntries"] = zip_info["entries"]
    return result


TOOLS: Dict[str, Tuple[str, Dict[str, Any], Callable[[Dict[str, Any]], Dict[str, Any]]]] = {
    "detect_environment": (
        "Find Steam, Skyrim SE, Vortex AppData, staging guesses, plugins.txt, SKSE, and basic problems.",
        {
            "type": "object",
            "properties": {
                "vortex_appdata": {"type": "string"},
                "vortex_exe": {"type": "string"},
                "skyrim_dir": {"type": "string"},
                "staging_dir": {"type": "string"},
                "my_games_dir": {"type": "string"},
                "local_appdata": {"type": "string"},
            },
            "additionalProperties": False,
        },
        detect_environment,
    ),
    "validate_setup": (
        "One-shot setup check for OpenClaw: detected paths, blockers, available tool groups, and safe next steps.",
        {
            "type": "object",
            "properties": {
                "vortex_appdata": {"type": "string"},
                "vortex_exe": {"type": "string"},
                "skyrim_dir": {"type": "string"},
                "staging_dir": {"type": "string"},
                "my_games_dir": {"type": "string"},
                "local_appdata": {"type": "string"},
            },
            "additionalProperties": False,
        },
        validate_setup,
    ),
    "workflow_guide": (
        "Recommend the safest MCP workflow for a plain-language Skyrim/Vortex problem.",
        {
            "type": "object",
            "properties": {
                "problem": {"type": "string"},
                "description": {"type": "string"},
                "workflow_key": {
                    "type": "string",
                    "enum": [
                        "auto",
                        "all",
                        "first_setup",
                        "mods_not_working",
                        "weird_object",
                        "popup",
                        "runtime_logs",
                        "large_collection_review",
                        "collection_drift",
                        "safe_profile_undo",
                        "bug_report",
                    ],
                    "default": "auto",
                },
                "include_all": {"type": "boolean", "default": False},
                "include_direct_cli": {"type": "boolean", "default": True},
                "max_workflows": {"type": "integer", "default": 3},
            },
            "additionalProperties": False,
        },
        workflow_guide,
    ),
    "inventory_mods": (
        "Inventory staged Vortex Skyrim SE mods, file kinds, plugins, archives, SKSE DLLs, readmes, and metadata.",
        {
            "type": "object",
            "properties": {
                "vortex_appdata": {"type": "string"},
                "staging_dir": {"type": "string"},
                "include_files": {"type": "boolean", "default": False},
                "include_scan_cache_status": {"type": "boolean", "default": False},
                "max_mods": {"type": "integer", "default": 300},
                "max_files_per_mod": {"type": "integer", "default": 5000},
                "scan_cache_dir": {"type": "string"},
                "use_scan_cache": {"type": "boolean", "default": True},
                "scan_cache_ttl_seconds": {"type": "integer", "default": SCAN_DEFAULT_CACHE_TTL_SECONDS},
            },
            "additionalProperties": False,
        },
        inventory_mods,
    ),
    "analyze_conflicts": (
        "Find file-level conflicts across staged mods and unmanaged overlaps in Skyrim Data.",
        {
            "type": "object",
            "properties": {
                "vortex_appdata": {"type": "string"},
                "skyrim_dir": {"type": "string"},
                "staging_dir": {"type": "string"},
                "hash_files": {"type": "boolean", "default": False},
                "max_files": {"type": "integer", "default": MAX_DEFAULT_FILES},
                "max_conflicts": {"type": "integer", "default": 300},
            },
            "additionalProperties": False,
        },
        analyze_conflicts,
    ),
    "redundant_mod_report": (
        "Find likely redundant mods by duplicate plugins, duplicate Nexus ids, and covered file sets.",
        {
            "type": "object",
            "properties": {
                "vortex_appdata": {"type": "string"},
                "staging_dir": {"type": "string"},
                "hash_files": {"type": "boolean", "default": False},
                "max_mods": {"type": "integer", "default": 200},
                "scan_cache_dir": {"type": "string"},
                "use_scan_cache": {"type": "boolean", "default": True},
                "scan_cache_ttl_seconds": {"type": "integer", "default": SCAN_DEFAULT_CACHE_TTL_SECONDS},
            },
            "additionalProperties": False,
        },
        redundant_mod_report,
    ),
    "plugin_report": (
        "Read plugins.txt/loadorder.txt, list available plugins, parse plugin masters, and report missing masters.",
        {
            "type": "object",
            "properties": {
                "skyrim_dir": {"type": "string"},
                "staging_dir": {"type": "string"},
                "local_appdata": {"type": "string"},
            },
            "additionalProperties": False,
        },
        plugin_report,
    ),
    "scan_cache_status": (
        "Show the local mod-summary scan cache used to speed up repeated large-collection diagnostics.",
        {
            "type": "object",
            "properties": {
                "scan_cache_dir": {"type": "string"},
                "scan_cache_ttl_seconds": {"type": "integer", "default": SCAN_DEFAULT_CACHE_TTL_SECONDS},
            },
            "additionalProperties": False,
        },
        scan_cache_status,
    ),
    "xedit_diagnostics_report": (
        "Read-only xEdit/SSEEdit helper report for FormID/plugin inspection targets.",
        {
            "type": "object",
            "properties": {
                "xedit_exe": {"type": "string"},
                "sseedit_exe": {"type": "string"},
                "form_id": {"type": "string"},
                "plugin_name": {"type": "string"},
                "skyrim_dir": {"type": "string"},
                "staging_dir": {"type": "string"},
                "local_appdata": {"type": "string"},
            },
            "additionalProperties": False,
        },
        xedit_diagnostics_report,
    ),
    "xedit_inspection_script": (
        "Generate a read-only xEdit/SSEEdit Pascal script that exports matching selected records to CSV for OpenClaw analysis.",
        {
            "type": "object",
            "properties": {
                "xedit_exe": {"type": "string"},
                "sseedit_exe": {"type": "string"},
                "output_path": {"type": "string"},
                "report_path": {"type": "string"},
                "description": {"type": "string"},
                "location": {"type": "string"},
                "object": {"type": "string"},
                "cell": {"type": "string"},
                "base_object": {"type": "string"},
                "popup_text": {"type": "string"},
                "extra_terms": {"type": "string"},
                "terms": {"type": "array", "items": {"type": "string"}},
                "form_id": {"type": "string"},
                "plugin_name": {"type": "string"},
                "skyrim_dir": {"type": "string"},
                "staging_dir": {"type": "string"},
                "local_appdata": {"type": "string"},
                "max_records": {"type": "integer", "default": 2000},
                "max_terms": {"type": "integer", "default": 40},
                "include_script_text": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
        xedit_inspection_script,
    ),
    "xedit_inspection_result_report": (
        "Read the CSV produced by xedit_inspection_script and summarize candidate plugins, record signatures, and matching rows.",
        {
            "type": "object",
            "properties": {
                "report_path": {"type": "string"},
                "path": {"type": "string"},
                "max_rows": {"type": "integer", "default": 2000},
                "max_preview_rows": {"type": "integer", "default": 50},
                "allow_any_path": {"type": "boolean", "default": False},
                "allowed_roots": {"type": "array", "items": {"type": "string"}},
                "vortex_appdata": {"type": "string"},
                "skyrim_dir": {"type": "string"},
                "staging_dir": {"type": "string"},
                "my_games_dir": {"type": "string"},
            },
            "additionalProperties": False,
        },
        xedit_inspection_result_report,
    ),
    "skyrim_issue_case_packet": (
        "Create a no-change investigation folder for a visible Skyrim issue, including issue triage, xEdit hints, a generated read-only xEdit script, and OpenClaw next steps.",
        {
            "type": "object",
            "properties": {
                "case_dir": {"type": "string"},
                "output_path": {"type": "string"},
                "description": {"type": "string"},
                "location": {"type": "string"},
                "object": {"type": "string"},
                "cell": {"type": "string"},
                "base_object": {"type": "string"},
                "popup_text": {"type": "string"},
                "extra_terms": {"type": "string"},
                "form_id": {"type": "string"},
                "plugin_name": {"type": "string"},
                "issue_kind": {"type": "string", "enum": ["placed_object", "popup", "general"]},
                "scan_mode": {"type": "string", "enum": ["quick", "balanced", "deep"]},
                "performance_mode": {"type": "string", "enum": ["normal", "slow_model", "fast", "thorough"]},
                "response_mode": {"type": "string", "enum": ["standard", "compact"]},
                "staging_dir": {"type": "string"},
                "skyrim_dir": {"type": "string"},
                "vortex_appdata": {"type": "string"},
                "local_appdata": {"type": "string"},
                "my_games_dir": {"type": "string"},
                "profile_id": {"type": "string"},
                "xedit_exe": {"type": "string"},
                "sseedit_exe": {"type": "string"},
                "include_xedit_script": {"type": "boolean", "default": True},
                "include_runtime_logs": {"type": "boolean", "default": False},
                "include_profile_state": {"type": "boolean", "default": True},
                "use_scan_cache": {"type": "boolean", "default": True},
                "max_mods": {"type": "integer", "default": 500},
                "max_candidates": {"type": "integer", "default": 20},
                "max_records": {"type": "integer", "default": 2000},
                "timeout_seconds": {"type": "integer", "default": 60},
                "redact_user_paths": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
        skyrim_issue_case_packet,
    ),
    "skyrim_issue_case_status": (
        "Read an existing Skyrim issue case folder, parse its xEdit CSV if present, and write a no-change status report with next steps.",
        {
            "type": "object",
            "properties": {
                "case_dir": {"type": "string"},
                "path": {"type": "string"},
                "output_path": {"type": "string"},
                "report_path": {"type": "string"},
                "max_rows": {"type": "integer", "default": 2000},
                "max_preview_rows": {"type": "integer", "default": 50},
                "allow_any_path": {"type": "boolean", "default": False},
                "redact_user_paths": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
        skyrim_issue_case_status,
    ),
    "skyrim_issue_case_note": (
        "Append an observation, test result, or decision note to an existing issue case folder. Writes notes only.",
        {
            "type": "object",
            "properties": {
                "case_dir": {"type": "string"},
                "path": {"type": "string"},
                "note": {"type": "string"},
                "text": {"type": "string"},
                "kind": {"type": "string", "enum": ["observation", "test", "decision", "undo", "result", "question"]},
                "source": {"type": "string"},
                "result": {"type": "string"},
                "next_action": {"type": "string"},
            },
            "additionalProperties": False,
        },
        skyrim_issue_case_note,
    ),
    "skyrim_case_evidence_import": (
        "Append live-game evidence such as popup OCR text, console FormIDs, current cell, or screenshot notes to an issue case folder.",
        {
            "type": "object",
            "properties": {
                "case_dir": {"type": "string"},
                "path": {"type": "string"},
                "evidence_type": {"type": "string", "enum": ["manual", "popup_text", "popup_ocr", "console", "screenshot_note", "skse_telemetry"]},
                "kind": {"type": "string"},
                "text": {"type": "string"},
                "evidence_text": {"type": "string"},
                "popup_text": {"type": "string"},
                "ocr_text": {"type": "string"},
                "form_id": {"type": "string"},
                "reference_form_id": {"type": "string"},
                "base_form_id": {"type": "string"},
                "cell": {"type": "string"},
                "object": {"type": "string"},
                "object_name": {"type": "string"},
                "screenshot_path": {"type": "string"},
                "confidence": {"type": "string"},
                "source": {"type": "string"},
                "note": {"type": "string"},
            },
            "additionalProperties": False,
        },
        skyrim_case_evidence_import,
    ),
    "skyrim_case_bundle": (
        "Zip an issue case folder for OpenClaw review or bug reports. Does not modify mods, profiles, or plugins.",
        {
            "type": "object",
            "properties": {
                "case_dir": {"type": "string"},
                "path": {"type": "string"},
                "output_path": {"type": "string"},
                "max_files": {"type": "integer", "default": 500},
                "max_file_bytes": {"type": "integer", "default": 5000000},
            },
            "additionalProperties": False,
        },
        skyrim_case_bundle,
    ),
    "skyrim_safe_experiment_plan": (
        "Write a dry-run cloned-profile experiment plan from an issue case folder. It does not disable mods or change Vortex.",
        {
            "type": "object",
            "properties": {
                "case_dir": {"type": "string"},
                "path": {"type": "string"},
                "output_path": {"type": "string"},
                "target_mod": {"type": "string"},
                "target_mod_name": {"type": "string"},
                "target_mod_id": {"type": "string"},
                "plugin_name": {"type": "string"},
                "signature": {"type": "string"},
                "test_profile_name": {"type": "string"},
            },
            "additionalProperties": False,
        },
        skyrim_safe_experiment_plan,
    ),
    "skyrim_case_what_now": (
        "Read a case folder/status/notes and write one concise next-action recommendation. It does not change mods.",
        {
            "type": "object",
            "properties": {
                "case_dir": {"type": "string"},
                "path": {"type": "string"},
                "output_path": {"type": "string"},
            },
            "additionalProperties": False,
        },
        skyrim_case_what_now,
    ),
    "skyrim_live_bridge_status": (
        "Describe current live-Skyrim bridge capability and the safe requirements for screenshot/OCR, console FormID, or SKSE telemetry capture.",
        {
            "type": "object",
            "properties": {
                "case_dir": {"type": "string"},
                "path": {"type": "string"},
                "output_path": {"type": "string"},
            },
            "additionalProperties": False,
        },
        skyrim_live_bridge_status,
    ),
    "vortex_collection_report": (
        "Read-only inspection of collection-like state and mod collection markers exposed by Vortex CLI.",
        {
            "type": "object",
            "properties": {
                "vortex_exe": {"type": "string"},
                "game_id": {"type": "string", "default": GAME_ID},
                "max_mods": {"type": "integer", "default": 500},
                "max_collection_items": {"type": "integer", "default": 80},
                "timeout_seconds": {"type": "integer", "default": 60},
            },
            "additionalProperties": False,
        },
        vortex_collection_report,
    ),
    "collection_local_match_report": (
        "Compare a supplied collection manifest-like JSON file to local Vortex/staging Nexus metadata. Read-only.",
        {
            "type": "object",
            "properties": {
                "collection_manifest_path": {"type": "string"},
                "collection_manifest_json": {"type": "string"},
                "vortex_appdata": {"type": "string"},
                "vortex_exe": {"type": "string"},
                "staging_dir": {"type": "string"},
                "profile_id": {"type": "string"},
                "game_id": {"type": "string", "default": GAME_ID},
                "include_profile_state": {"type": "boolean", "default": True},
                "max_mods": {"type": "integer", "default": 500},
                "max_files_per_mod": {"type": "integer", "default": 3000},
                "max_collection_items": {"type": "integer", "default": 5000},
                "scan_cache_dir": {"type": "string"},
                "use_scan_cache": {"type": "boolean", "default": True},
                "scan_cache_ttl_seconds": {"type": "integer", "default": SCAN_DEFAULT_CACHE_TTL_SECONDS},
                "timeout_seconds": {"type": "integer", "default": 60},
            },
            "additionalProperties": False,
        },
        collection_local_match_report,
    ),
    "mod_evidence": (
        "Read one mod folder and return evidence of what it does: file kinds, plugins, masters, FOMOD, and readmes.",
        {
            "type": "object",
            "properties": {
                "mod_dir": {"type": "string"},
                "max_files": {"type": "integer", "default": 4000},
                "max_text_bytes": {"type": "integer", "default": 80000},
            },
            "required": ["mod_dir"],
            "additionalProperties": False,
        },
        mod_evidence,
    ),
    "nexus_validate_key": (
        "Validate this MCP's Nexus Mods API key without logging the key.",
        {
            "type": "object",
            "properties": {
                "nexus_api_key": {"type": "string"},
                "nexus_api_key_file": {"type": "string"},
                "nexus_game_domain": {"type": "string", "default": NEXUS_GAME_DOMAIN},
                "nexus_timeout_seconds": {"type": "integer", "default": 20},
            },
            "additionalProperties": False,
        },
        nexus_validate_key,
    ),
    "nexus_mod_lookup": (
        "Read-only Nexus Mods metadata lookup for one mod id.",
        {
            "type": "object",
            "properties": {
                "mod_id": {"type": "integer"},
                "nexus_api_key": {"type": "string"},
                "nexus_api_key_file": {"type": "string"},
                "nexus_game_domain": {"type": "string", "default": NEXUS_GAME_DOMAIN},
                "nexus_cache_dir": {"type": "string"},
                "nexus_use_cache": {"type": "boolean", "default": True},
                "nexus_cache_ttl_seconds": {"type": "integer", "default": NEXUS_DEFAULT_CACHE_TTL_SECONDS},
                "nexus_timeout_seconds": {"type": "integer", "default": 20},
                "include_raw": {"type": "boolean", "default": False},
            },
            "required": ["mod_id"],
            "additionalProperties": False,
        },
        nexus_mod_lookup,
    ),
    "nexus_mod_files": (
        "Read-only Nexus Mods file list for one mod id.",
        {
            "type": "object",
            "properties": {
                "mod_id": {"type": "integer"},
                "nexus_api_key": {"type": "string"},
                "nexus_api_key_file": {"type": "string"},
                "nexus_game_domain": {"type": "string", "default": NEXUS_GAME_DOMAIN},
                "nexus_cache_dir": {"type": "string"},
                "nexus_use_cache": {"type": "boolean", "default": True},
                "nexus_cache_ttl_seconds": {"type": "integer", "default": NEXUS_DEFAULT_CACHE_TTL_SECONDS},
                "nexus_timeout_seconds": {"type": "integer", "default": 20},
                "include_raw": {"type": "boolean", "default": False},
            },
            "required": ["mod_id"],
            "additionalProperties": False,
        },
        nexus_mod_files,
    ),
    "nexus_file_info": (
        "Read-only Nexus Mods metadata lookup for one mod file id.",
        {
            "type": "object",
            "properties": {
                "mod_id": {"type": "integer"},
                "file_id": {"type": "integer"},
                "nexus_api_key": {"type": "string"},
                "nexus_api_key_file": {"type": "string"},
                "nexus_game_domain": {"type": "string", "default": NEXUS_GAME_DOMAIN},
                "nexus_cache_dir": {"type": "string"},
                "nexus_use_cache": {"type": "boolean", "default": True},
                "nexus_cache_ttl_seconds": {"type": "integer", "default": NEXUS_DEFAULT_CACHE_TTL_SECONDS},
                "nexus_timeout_seconds": {"type": "integer", "default": 20},
                "include_raw": {"type": "boolean", "default": False},
            },
            "required": ["mod_id", "file_id"],
            "additionalProperties": False,
        },
        nexus_file_info,
    ),
    "nexus_file_by_md5": (
        "Read-only Nexus Mods source lookup for a downloaded archive MD5 hash.",
        {
            "type": "object",
            "properties": {
                "md5": {"type": "string"},
                "md5_hash": {"type": "string"},
                "nexus_api_key": {"type": "string"},
                "nexus_api_key_file": {"type": "string"},
                "nexus_game_domain": {"type": "string", "default": NEXUS_GAME_DOMAIN},
                "nexus_cache_dir": {"type": "string"},
                "nexus_use_cache": {"type": "boolean", "default": True},
                "nexus_cache_ttl_seconds": {"type": "integer", "default": NEXUS_DEFAULT_CACHE_TTL_SECONDS},
                "nexus_timeout_seconds": {"type": "integer", "default": 20},
                "include_raw": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
        nexus_file_by_md5,
    ),
    "nexus_parse_nxm_link": (
        "Parse an nxm:// link into game, mod, file, key, and expiry diagnostics without downloading.",
        {
            "type": "object",
            "properties": {
                "nxm_link": {"type": "string"},
                "url": {"type": "string"},
            },
            "additionalProperties": False,
        },
        nexus_parse_nxm_link,
    ),
    "nexus_update_report": (
        "Compare locally staged Vortex mods to current Nexus metadata when a Nexus API key is configured.",
        {
            "type": "object",
            "properties": {
                "vortex_appdata": {"type": "string"},
                "vortex_exe": {"type": "string"},
                "staging_dir": {"type": "string"},
                "profile_id": {"type": "string"},
                "game_id": {"type": "string", "default": GAME_ID},
                "include_profile_state": {"type": "boolean", "default": True},
                "max_mods": {"type": "integer", "default": 500},
                "max_files_per_mod": {"type": "integer", "default": 3000},
                "nexus_max_lookup_mods": {"type": "integer", "default": 80},
                "nexus_api_key": {"type": "string"},
                "nexus_api_key_file": {"type": "string"},
                "nexus_game_domain": {"type": "string", "default": NEXUS_GAME_DOMAIN},
                "nexus_cache_dir": {"type": "string"},
                "nexus_use_cache": {"type": "boolean", "default": True},
                "nexus_cache_ttl_seconds": {"type": "integer", "default": NEXUS_DEFAULT_CACHE_TTL_SECONDS},
                "nexus_timeout_seconds": {"type": "integer", "default": 20},
                "scan_cache_dir": {"type": "string"},
                "use_scan_cache": {"type": "boolean", "default": True},
                "scan_cache_ttl_seconds": {"type": "integer", "default": SCAN_DEFAULT_CACHE_TTL_SECONDS},
                "timeout_seconds": {"type": "integer", "default": 60},
            },
            "additionalProperties": False,
        },
        nexus_update_report,
    ),
    "mod_knowledge_report": (
        "Write a Markdown knowledge map for a large Skyrim SE mod collection: inferred roles, relationships, conflicts, and safe removal-review candidates.",
        {
            "type": "object",
            "properties": {
                "output_path": {"type": "string"},
                "vortex_appdata": {"type": "string"},
                "vortex_exe": {"type": "string"},
                "game_id": {"type": "string", "default": GAME_ID},
                "profile_id": {"type": "string"},
                "skyrim_dir": {"type": "string"},
                "staging_dir": {"type": "string"},
                "local_appdata": {"type": "string"},
                "include_profile_state": {"type": "boolean", "default": True},
                "include_conflicts": {"type": "boolean", "default": True},
                "include_redundancy": {"type": "boolean", "default": True},
                "include_plugin_report": {"type": "boolean", "default": True},
                "include_readme_excerpts": {"type": "boolean", "default": True},
                "include_nexus_metadata": {"type": "boolean", "default": False},
                "hash_files": {"type": "boolean", "default": False},
                "redact_user_paths": {"type": "boolean", "default": True},
                "max_mods": {"type": "integer", "default": 500},
                "max_files_per_mod": {"type": "integer", "default": 3000},
                "conflict_max_files_per_mod": {"type": "integer", "default": 3000},
                "max_conflicts": {"type": "integer", "default": 500},
                "max_detail_mods": {"type": "integer", "default": 120},
                "max_removal_candidates": {"type": "integer", "default": 80},
                "max_readme_lines": {"type": "integer", "default": 4},
                "max_readme_bytes": {"type": "integer", "default": 8000},
                "nexus_max_lookup_mods": {"type": "integer", "default": 40},
                "nexus_api_key": {"type": "string"},
                "nexus_api_key_file": {"type": "string"},
                "nexus_game_domain": {"type": "string", "default": NEXUS_GAME_DOMAIN},
                "nexus_cache_dir": {"type": "string"},
                "nexus_use_cache": {"type": "boolean", "default": True},
                "nexus_cache_ttl_seconds": {"type": "integer", "default": NEXUS_DEFAULT_CACHE_TTL_SECONDS},
                "scan_cache_dir": {"type": "string"},
                "use_scan_cache": {"type": "boolean", "default": True},
                "scan_cache_ttl_seconds": {"type": "integer", "default": SCAN_DEFAULT_CACHE_TTL_SECONDS},
                "timeout_seconds": {"type": "integer", "default": 60},
            },
            "additionalProperties": False,
        },
        mod_knowledge_report,
    ),
    "in_game_issue_report": (
        "Read-only triage for in-game weirdness such as misplaced objects or annoying popups; searches staged mods for likely causes.",
        {
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "location": {"type": "string"},
                "object": {"type": "string"},
                "form_id": {"type": "string"},
                "cell": {"type": "string"},
                "base_object": {"type": "string"},
                "popup_text": {"type": "string"},
                "extra_terms": {"type": "string"},
                "issue_kind": {"type": "string", "enum": ["placed_object", "popup", "general"]},
                "performance_mode": {"type": "string", "enum": ["normal", "slow_model", "fast", "thorough"], "default": "normal"},
                "response_mode": {"type": "string", "enum": ["standard", "compact"], "default": "standard"},
                "vortex_appdata": {"type": "string"},
                "vortex_exe": {"type": "string"},
                "game_id": {"type": "string", "default": GAME_ID},
                "profile_id": {"type": "string"},
                "staging_dir": {"type": "string"},
                "include_profile_state": {"type": "boolean", "default": True},
                "max_mods": {"type": "integer", "default": 500},
                "max_candidates": {"type": "integer", "default": 20},
                "max_files_per_mod": {"type": "integer", "default": 3000},
                "max_text_bytes": {"type": "integer", "default": 12000},
                "max_plugin_bytes": {"type": "integer", "default": 5000000},
                "max_plugin_strings": {"type": "integer", "default": 2500},
                "max_evidence_per_mod": {"type": "integer", "default": 10},
                "scan_mode": {"type": "string", "enum": ["quick", "balanced", "deep"], "default": "balanced"},
                "balanced_text_files_per_mod": {"type": "integer", "default": 8},
                "deep_scan_files": {"type": "boolean", "default": False},
                "scan_cache_dir": {"type": "string"},
                "use_scan_cache": {"type": "boolean", "default": True},
                "scan_cache_ttl_seconds": {"type": "integer", "default": SCAN_DEFAULT_CACHE_TTL_SECONDS},
                "timeout_seconds": {"type": "integer", "default": 60},
            },
            "additionalProperties": False,
        },
        in_game_issue_report,
    ),
    "safe_session_report": (
        "Write one no-change Markdown/JSON safe-session report with setup, optional profile backup, play health, optional in-game triage, and logs.",
        {
            "type": "object",
            "properties": {
                "output_path": {"type": "string"},
                "session_json_path": {"type": "string"},
                "vortex_appdata": {"type": "string"},
                "vortex_exe": {"type": "string"},
                "game_id": {"type": "string", "default": GAME_ID},
                "profile_id": {"type": "string"},
                "skyrim_dir": {"type": "string"},
                "staging_dir": {"type": "string"},
                "local_appdata": {"type": "string"},
                "my_games_dir": {"type": "string"},
                "backup_path": {"type": "string"},
                "backup_dir": {"type": "string"},
                "log_dir": {"type": "string"},
                "include_profile_backup": {"type": "boolean", "default": True},
                "include_all_profiles": {"type": "boolean", "default": True},
                "include_profile_state": {"type": "boolean", "default": True},
                "include_play_report": {"type": "boolean", "default": True},
                "include_logs": {"type": "boolean", "default": True},
                "include_runtime_logs": {"type": "boolean", "default": True},
                "include_conflicts": {"type": "boolean", "default": False},
                "include_nexus_metadata": {"type": "boolean", "default": False},
                "include_xedit_report": {"type": "boolean", "default": False},
                "include_collection_report": {"type": "boolean", "default": False},
                "redact_user_paths": {"type": "boolean", "default": True},
                "description": {"type": "string"},
                "location": {"type": "string"},
                "object": {"type": "string"},
                "form_id": {"type": "string"},
                "cell": {"type": "string"},
                "base_object": {"type": "string"},
                "popup_text": {"type": "string"},
                "extra_terms": {"type": "string"},
                "plugin_name": {"type": "string"},
                "xedit_exe": {"type": "string"},
                "issue_kind": {"type": "string", "enum": ["placed_object", "popup", "general"]},
                "performance_mode": {"type": "string", "enum": ["normal", "slow_model", "fast", "thorough"], "default": "normal"},
                "response_mode": {"type": "string", "enum": ["standard", "compact"], "default": "standard"},
                "scan_mode": {"type": "string", "enum": ["quick", "balanced", "deep"], "default": "balanced"},
                "balanced_text_files_per_mod": {"type": "integer", "default": 8},
                "deep_scan_files": {"type": "boolean", "default": False},
                "hash_files": {"type": "boolean", "default": False},
                "max_mods": {"type": "integer", "default": 500},
                "max_candidates": {"type": "integer", "default": 20},
                "max_files_per_mod": {"type": "integer", "default": 3000},
                "max_conflicts": {"type": "integer", "default": 300},
                "max_log_files": {"type": "integer", "default": 12},
                "max_runtime_log_files": {"type": "integer", "default": 12},
                "max_log_bytes_per_file": {"type": "integer", "default": LOG_TAIL_DEFAULT_BYTES},
                "max_runtime_findings": {"type": "integer", "default": 80},
                "max_runtime_index_files": {"type": "integer", "default": 60000},
                "fresh_log_hours": {"type": "number", "default": 24},
                "validate_config_candidates": {"type": "boolean", "default": True},
                "nexus_max_lookup_mods": {"type": "integer", "default": 80},
                "nexus_api_key": {"type": "string"},
                "nexus_api_key_file": {"type": "string"},
                "nexus_game_domain": {"type": "string", "default": NEXUS_GAME_DOMAIN},
                "nexus_cache_dir": {"type": "string"},
                "nexus_use_cache": {"type": "boolean", "default": True},
                "nexus_cache_ttl_seconds": {"type": "integer", "default": NEXUS_DEFAULT_CACHE_TTL_SECONDS},
                "nexus_timeout_seconds": {"type": "integer", "default": 20},
                "scan_cache_dir": {"type": "string"},
                "use_scan_cache": {"type": "boolean", "default": True},
                "scan_cache_ttl_seconds": {"type": "integer", "default": SCAN_DEFAULT_CACHE_TTL_SECONDS},
                "timeout_seconds": {"type": "integer", "default": 60},
            },
            "additionalProperties": False,
        },
        safe_session_report,
    ),
    "skyrim_diagnostics_report": (
        "One no-change Skyrim SE diagnostics report with setup, deployment, logs, optional issue triage, and optional Nexus metadata.",
        {
            "type": "object",
            "properties": {
                "output_path": {"type": "string"},
                "session_json_path": {"type": "string"},
                "vortex_appdata": {"type": "string"},
                "vortex_exe": {"type": "string"},
                "game_id": {"type": "string", "default": GAME_ID},
                "profile_id": {"type": "string"},
                "skyrim_dir": {"type": "string"},
                "staging_dir": {"type": "string"},
                "local_appdata": {"type": "string"},
                "my_games_dir": {"type": "string"},
                "log_dir": {"type": "string"},
                "include_profile_backup": {"type": "boolean", "default": True},
                "include_profile_state": {"type": "boolean", "default": True},
                "include_play_report": {"type": "boolean", "default": True},
                "include_logs": {"type": "boolean", "default": True},
                "include_runtime_logs": {"type": "boolean", "default": True},
                "include_conflicts": {"type": "boolean", "default": False},
                "include_nexus_metadata": {"type": "boolean", "default": False},
                "include_xedit_report": {"type": "boolean", "default": False},
                "include_collection_report": {"type": "boolean", "default": False},
                "redact_user_paths": {"type": "boolean", "default": True},
                "description": {"type": "string"},
                "location": {"type": "string"},
                "object": {"type": "string"},
                "form_id": {"type": "string"},
                "cell": {"type": "string"},
                "base_object": {"type": "string"},
                "popup_text": {"type": "string"},
                "extra_terms": {"type": "string"},
                "plugin_name": {"type": "string"},
                "xedit_exe": {"type": "string"},
                "issue_kind": {"type": "string", "enum": ["placed_object", "popup", "general"]},
                "performance_mode": {"type": "string", "enum": ["normal", "slow_model", "fast", "thorough"], "default": "slow_model"},
                "response_mode": {"type": "string", "enum": ["standard", "compact"], "default": "compact"},
                "scan_mode": {"type": "string", "enum": ["quick", "balanced", "deep"], "default": "balanced"},
                "max_mods": {"type": "integer", "default": 500},
                "max_candidates": {"type": "integer", "default": 20},
                "max_files_per_mod": {"type": "integer", "default": 3000},
                "max_conflicts": {"type": "integer", "default": 300},
                "max_log_files": {"type": "integer", "default": 12},
                "max_runtime_log_files": {"type": "integer", "default": 12},
                "max_log_bytes_per_file": {"type": "integer", "default": LOG_TAIL_DEFAULT_BYTES},
                "max_runtime_findings": {"type": "integer", "default": 80},
                "max_runtime_index_files": {"type": "integer", "default": 60000},
                "fresh_log_hours": {"type": "number", "default": 24},
                "validate_config_candidates": {"type": "boolean", "default": True},
                "nexus_max_lookup_mods": {"type": "integer", "default": 80},
                "nexus_api_key": {"type": "string"},
                "nexus_api_key_file": {"type": "string"},
                "nexus_game_domain": {"type": "string", "default": NEXUS_GAME_DOMAIN},
                "nexus_cache_dir": {"type": "string"},
                "nexus_use_cache": {"type": "boolean", "default": True},
                "nexus_cache_ttl_seconds": {"type": "integer", "default": NEXUS_DEFAULT_CACHE_TTL_SECONDS},
                "nexus_timeout_seconds": {"type": "integer", "default": 20},
                "scan_cache_dir": {"type": "string"},
                "use_scan_cache": {"type": "boolean", "default": True},
                "scan_cache_ttl_seconds": {"type": "integer", "default": SCAN_DEFAULT_CACHE_TTL_SECONDS},
                "timeout_seconds": {"type": "integer", "default": 60},
            },
            "additionalProperties": False,
        },
        skyrim_diagnostics_report,
    ),
    "ini_report": (
        "Inspect Skyrim SE INI files and report mod-manager-friendly settings.",
        {
            "type": "object",
            "properties": {"my_games_dir": {"type": "string"}},
            "additionalProperties": False,
        },
        ini_report,
    ),
    "apply_ini_fixes": (
        "Apply narrow Skyrim SE INI fixes. Dry-run by default and creates backups when writing.",
        {
            "type": "object",
            "properties": {
                "my_games_dir": {"type": "string"},
                "dry_run": {"type": "boolean", "default": True},
                "make_backup": {"type": "boolean", "default": True},
            },
            "additionalProperties": False,
        },
        apply_ini_fixes,
    ),
    "skyrim_runtime_log_report": (
        "Read recent Skyrim/Papyrus/SKSE/crash logs, detect high-signal errors/popups, and map referenced files back to staged mods.",
        {
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "popup_text": {"type": "string"},
                "extra_terms": {"type": "string"},
                "problem": {"type": "string"},
                "skyrim_dir": {"type": "string"},
                "staging_dir": {"type": "string"},
                "vortex_appdata": {"type": "string"},
                "my_games_dir": {"type": "string"},
                "performance_mode": {"type": "string", "enum": ["normal", "slow_model", "fast", "thorough"], "default": "normal"},
                "response_mode": {"type": "string", "enum": ["standard", "compact"], "default": "standard"},
                "include_staged_file_matches": {"type": "boolean", "default": True},
                "max_runtime_log_files": {"type": "integer", "default": 12},
                "max_log_files": {"type": "integer", "default": 12},
                "max_log_bytes_per_file": {"type": "integer", "default": LOG_TAIL_DEFAULT_BYTES},
                "max_log_bytes": {"type": "integer", "default": LOG_TAIL_DEFAULT_BYTES},
                "max_runtime_findings": {"type": "integer", "default": 80},
                "max_runtime_references": {"type": "integer", "default": 12},
                "max_runtime_config_candidates": {"type": "integer", "default": 20},
                "max_issue_group_examples": {"type": "integer", "default": 3},
                "fresh_log_hours": {"type": "number", "default": 24},
                "validate_config_candidates": {"type": "boolean", "default": True},
                "max_config_validation_bytes": {"type": "integer", "default": 2000000},
                "max_runtime_index_files": {"type": "integer", "default": 60000},
                "max_mods": {"type": "integer", "default": 500},
                "max_files_per_mod": {"type": "integer", "default": 3000},
            },
            "additionalProperties": False,
        },
        skyrim_runtime_log_report,
    ),
    "config_file_report": (
        "Read-only validation summary for JSON/XML/INI/TOML/YAML/plain config files under detected Vortex/Skyrim roots.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_bytes": {"type": "integer", "default": 2000000},
                "max_preview_lines": {"type": "integer", "default": 8},
                "allow_any_path": {"type": "boolean", "default": False},
                "allowed_roots": {"type": "array", "items": {"type": "string"}},
                "vortex_appdata": {"type": "string"},
                "skyrim_dir": {"type": "string"},
                "staging_dir": {"type": "string"},
                "my_games_dir": {"type": "string"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        config_file_report,
    ),
    "read_text_file": (
        "Read a text file under detected Vortex/Skyrim roots. Use for mod readmes, logs, INIs, and XML configs.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_bytes": {"type": "integer", "default": MAX_DEFAULT_TEXT_BYTES},
                "allow_any_path": {"type": "boolean", "default": False},
                "allowed_roots": {"type": "array", "items": {"type": "string"}},
                "vortex_appdata": {"type": "string"},
                "skyrim_dir": {"type": "string"},
                "staging_dir": {"type": "string"},
                "my_games_dir": {"type": "string"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        read_text_file,
    ),
    "apply_config_text_patch": (
        "Safely replace exact text in a staged Skyrim config/text file. Dry-run by default and creates backups when writing.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
                "dry_run": {"type": "boolean", "default": True},
                "apply": {"type": "boolean", "default": False},
                "make_backup": {"type": "boolean", "default": True},
                "allow_multiple": {"type": "boolean", "default": False},
                "max_bytes": {"type": "integer", "default": 2000000},
                "allow_any_path": {"type": "boolean", "default": False},
                "allowed_roots": {"type": "array", "items": {"type": "string"}},
                "vortex_appdata": {"type": "string"},
                "skyrim_dir": {"type": "string"},
                "staging_dir": {"type": "string"},
                "my_games_dir": {"type": "string"},
            },
            "required": ["path", "old_text", "new_text"],
            "additionalProperties": False,
        },
        apply_config_text_patch,
    ),
    "vortex_cli_get": (
        "Read raw Vortex state through Vortex.exe --get. Useful for diagnosing profile/state paths.",
        {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}},
                "vortex_exe": {"type": "string"},
                "timeout_seconds": {"type": "integer", "default": 60},
            },
            "additionalProperties": False,
        },
        vortex_cli_get,
    ),
    "vortex_profile_report": (
        "List Vortex profiles for Skyrim SE, including active-profile guess and enabled mod counts.",
        {
            "type": "object",
            "properties": {
                "game_id": {"type": "string", "default": GAME_ID},
                "include_all_games": {"type": "boolean", "default": False},
                "vortex_exe": {"type": "string"},
                "timeout_seconds": {"type": "integer", "default": 60},
            },
            "additionalProperties": False,
        },
        vortex_profile_report,
    ),
    "vortex_profile_mods": (
        "List enabled or disabled mods recorded in a Vortex profile, optionally with Vortex mod metadata.",
        {
            "type": "object",
            "properties": {
                "profile_id": {"type": "string"},
                "game_id": {"type": "string", "default": GAME_ID},
                "include_disabled": {"type": "boolean", "default": False},
                "include_mod_metadata": {"type": "boolean", "default": True},
                "max_mods": {"type": "integer", "default": 500},
                "vortex_exe": {"type": "string"},
                "timeout_seconds": {"type": "integer", "default": 60},
            },
            "additionalProperties": False,
        },
        vortex_profile_mods,
    ),
    "vortex_compare_profiles": (
        "Compare two Vortex profiles and show which mods are enabled only in one profile.",
        {
            "type": "object",
            "properties": {
                "left_profile_id": {"type": "string"},
                "right_profile_id": {"type": "string"},
                "game_id": {"type": "string", "default": GAME_ID},
                "vortex_exe": {"type": "string"},
                "timeout_seconds": {"type": "integer", "default": 60},
            },
            "required": ["left_profile_id", "right_profile_id"],
            "additionalProperties": False,
        },
        vortex_compare_profiles,
    ),
    "vortex_profile_deployment_report": (
        "Read-only check that enabled profile plugins are deployed into Skyrim Data and enabled in plugins.txt.",
        {
            "type": "object",
            "properties": {
                "profile_id": {"type": "string"},
                "game_id": {"type": "string", "default": GAME_ID},
                "vortex_exe": {"type": "string"},
                "vortex_appdata": {"type": "string"},
                "skyrim_dir": {"type": "string"},
                "staging_dir": {"type": "string"},
                "local_appdata": {"type": "string"},
                "max_mods": {"type": "integer", "default": 500},
                "max_files_per_mod": {"type": "integer", "default": 3000},
                "scan_cache_dir": {"type": "string"},
                "use_scan_cache": {"type": "boolean", "default": True},
                "scan_cache_ttl_seconds": {"type": "integer", "default": SCAN_DEFAULT_CACHE_TTL_SECONDS},
                "timeout_seconds": {"type": "integer", "default": 60},
            },
            "additionalProperties": False,
        },
        vortex_profile_deployment_report,
    ),
    "vortex_profile_backup": (
        "Write a JSON backup of the active or selected Vortex Skyrim SE profile for later restore previews.",
        {
            "type": "object",
            "properties": {
                "output_path": {"type": "string"},
                "backup_path": {"type": "string"},
                "backup_dir": {"type": "string"},
                "profile_id": {"type": "string"},
                "include_all_profiles": {"type": "boolean", "default": False},
                "include_mod_metadata": {"type": "boolean", "default": True},
                "game_id": {"type": "string", "default": GAME_ID},
                "vortex_exe": {"type": "string"},
                "timeout_seconds": {"type": "integer", "default": 60},
            },
            "additionalProperties": False,
        },
        vortex_profile_backup,
    ),
    "vortex_profile_restore_plan": (
        "Preview or apply a profile restore from a vortex_profile_backup JSON file. Dry-run by default.",
        {
            "type": "object",
            "properties": {
                "backup_path": {"type": "string"},
                "profile_id": {"type": "string"},
                "disable_extra_mods": {"type": "boolean", "default": False},
                "apply": {"type": "boolean", "default": False},
                "allow_running_vortex": {"type": "boolean", "default": False},
                "max_plan_preview": {"type": "integer", "default": 100},
                "game_id": {"type": "string", "default": GAME_ID},
                "vortex_exe": {"type": "string"},
                "timeout_seconds": {"type": "integer", "default": 60},
            },
            "required": ["backup_path"],
            "additionalProperties": False,
        },
        vortex_profile_restore_plan,
    ),
    "vortex_clone_profile": (
        "Clone a Vortex profile for safer experimentation. Dry-run by default; use apply=true with Vortex closed.",
        {
            "type": "object",
            "properties": {
                "source_profile_id": {"type": "string"},
                "new_profile_id": {"type": "string"},
                "new_name": {"type": "string"},
                "make_active": {"type": "boolean", "default": False},
                "apply": {"type": "boolean", "default": False},
                "allow_running_vortex": {"type": "boolean", "default": False},
                "backup_before_apply": {"type": "boolean", "default": True},
                "backup_path": {"type": "string"},
                "backup_dir": {"type": "string"},
                "max_plan_preview": {"type": "integer", "default": 50},
                "game_id": {"type": "string", "default": GAME_ID},
                "vortex_exe": {"type": "string"},
                "timeout_seconds": {"type": "integer", "default": 60},
            },
            "additionalProperties": False,
        },
        vortex_clone_profile,
    ),
    "vortex_set_profile_mods": (
        "Enable or disable exact Vortex mod ids in one profile. Dry-run by default and never deletes mods.",
        {
            "type": "object",
            "properties": {
                "profile_id": {"type": "string"},
                "enable_mod_ids": {"type": "array", "items": {"type": "string"}},
                "disable_mod_ids": {"type": "array", "items": {"type": "string"}},
                "allow_unknown_mod_ids": {"type": "boolean", "default": False},
                "apply": {"type": "boolean", "default": False},
                "allow_running_vortex": {"type": "boolean", "default": False},
                "backup_before_apply": {"type": "boolean", "default": True},
                "backup_path": {"type": "string"},
                "backup_dir": {"type": "string"},
                "max_plan_preview": {"type": "integer", "default": 50},
                "game_id": {"type": "string", "default": GAME_ID},
                "vortex_exe": {"type": "string"},
                "timeout_seconds": {"type": "integer", "default": 60},
            },
            "additionalProperties": False,
        },
        vortex_set_profile_mods,
    ),
    "skyrim_modded_play_report": (
        "One-shot read-only report for why modded Skyrim SE may not be launching with the expected Vortex profile.",
        {
            "type": "object",
            "properties": {
                "profile_id": {"type": "string"},
                "game_id": {"type": "string", "default": GAME_ID},
                "vortex_exe": {"type": "string"},
                "vortex_appdata": {"type": "string"},
                "skyrim_dir": {"type": "string"},
                "staging_dir": {"type": "string"},
                "my_games_dir": {"type": "string"},
                "local_appdata": {"type": "string"},
                "include_conflicts": {"type": "boolean", "default": False},
                "include_nexus_metadata": {"type": "boolean", "default": False},
                "max_mods": {"type": "integer", "default": 500},
                "max_files_per_mod": {"type": "integer", "default": 3000},
                "nexus_max_lookup_mods": {"type": "integer", "default": 80},
                "nexus_api_key": {"type": "string"},
                "nexus_api_key_file": {"type": "string"},
                "nexus_game_domain": {"type": "string", "default": NEXUS_GAME_DOMAIN},
                "nexus_cache_dir": {"type": "string"},
                "nexus_use_cache": {"type": "boolean", "default": True},
                "nexus_cache_ttl_seconds": {"type": "integer", "default": NEXUS_DEFAULT_CACHE_TTL_SECONDS},
                "nexus_timeout_seconds": {"type": "integer", "default": 20},
                "scan_cache_dir": {"type": "string"},
                "use_scan_cache": {"type": "boolean", "default": True},
                "scan_cache_ttl_seconds": {"type": "integer", "default": SCAN_DEFAULT_CACHE_TTL_SECONDS},
                "timeout_seconds": {"type": "integer", "default": 60},
            },
            "additionalProperties": False,
        },
        skyrim_modded_play_report,
    ),
    "suggest_conflict_fixes": (
        "Create an assistant-readable repair plan for missing masters, sensitive conflicts, and duplicate files.",
        {
            "type": "object",
            "properties": {
                "vortex_appdata": {"type": "string"},
                "skyrim_dir": {"type": "string"},
                "staging_dir": {"type": "string"},
                "hash_files": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
        suggest_conflict_fixes,
    ),
    "log_status": (
        "Show MCP log folder, recent log files, and logging channels for bug reports.",
        {
            "type": "object",
            "properties": {
                "log_dir": {"type": "string"},
                "max_files": {"type": "integer", "default": 20},
            },
            "additionalProperties": False,
        },
        log_status,
    ),
    "bug_report_bundle": (
        "Write a bug-report JSON bundle with setup validation, environment checks, play/deployment reports, and recent MCP logs.",
        {
            "type": "object",
            "properties": {
                "output_path": {"type": "string"},
                "log_dir": {"type": "string"},
                "vortex_appdata": {"type": "string"},
                "vortex_exe": {"type": "string"},
                "game_id": {"type": "string", "default": GAME_ID},
                "skyrim_dir": {"type": "string"},
                "staging_dir": {"type": "string"},
                "my_games_dir": {"type": "string"},
                "local_appdata": {"type": "string"},
                "profile_id": {"type": "string"},
                "description": {"type": "string"},
                "location": {"type": "string"},
                "object": {"type": "string"},
                "form_id": {"type": "string"},
                "cell": {"type": "string"},
                "base_object": {"type": "string"},
                "popup_text": {"type": "string"},
                "extra_terms": {"type": "string"},
                "issue_kind": {"type": "string", "enum": ["placed_object", "popup", "general"]},
                "performance_mode": {"type": "string", "enum": ["normal", "slow_model", "fast", "thorough"], "default": "normal"},
                "response_mode": {"type": "string", "enum": ["standard", "compact"], "default": "standard"},
                "max_text_bytes": {"type": "integer", "default": 12000},
                "max_plugin_bytes": {"type": "integer", "default": 5000000},
                "max_plugin_strings": {"type": "integer", "default": 2500},
                "max_evidence_per_mod": {"type": "integer", "default": 10},
                "scan_mode": {"type": "string", "enum": ["quick", "balanced", "deep"], "default": "balanced"},
                "balanced_text_files_per_mod": {"type": "integer", "default": 8},
                "deep_scan_files": {"type": "boolean", "default": False},
                "include_logs": {"type": "boolean", "default": True},
                "include_vortex_profiles": {"type": "boolean", "default": True},
                "include_vortex_deployment": {"type": "boolean", "default": True},
                "include_play_report": {"type": "boolean", "default": True},
                "include_conflicts": {"type": "boolean", "default": False},
                "include_nexus_metadata": {"type": "boolean", "default": False},
                "include_xedit_report": {"type": "boolean", "default": False},
                "include_collection_report": {"type": "boolean", "default": False},
                "include_runtime_logs": {"type": "boolean", "default": True},
                "redact_user_paths": {"type": "boolean", "default": True},
                "zip_output": {"type": "boolean", "default": False},
                "zip_path": {"type": "string"},
                "include_log_tails_in_zip": {"type": "boolean", "default": True},
                "max_log_files": {"type": "integer", "default": 12},
                "max_log_bytes": {"type": "integer", "default": LOG_TAIL_DEFAULT_BYTES},
                "max_runtime_log_files": {"type": "integer", "default": 12},
                "max_log_bytes_per_file": {"type": "integer", "default": LOG_TAIL_DEFAULT_BYTES},
                "max_runtime_findings": {"type": "integer", "default": 80},
                "max_runtime_index_files": {"type": "integer", "default": 60000},
                "fresh_log_hours": {"type": "number", "default": 24},
                "validate_config_candidates": {"type": "boolean", "default": True},
                "max_mods": {"type": "integer", "default": 500},
                "max_files_per_mod": {"type": "integer", "default": 3000},
                "nexus_max_lookup_mods": {"type": "integer", "default": 80},
                "nexus_api_key": {"type": "string"},
                "nexus_api_key_file": {"type": "string"},
                "nexus_game_domain": {"type": "string", "default": NEXUS_GAME_DOMAIN},
                "nexus_cache_dir": {"type": "string"},
                "nexus_use_cache": {"type": "boolean", "default": True},
                "nexus_cache_ttl_seconds": {"type": "integer", "default": NEXUS_DEFAULT_CACHE_TTL_SECONDS},
                "nexus_timeout_seconds": {"type": "integer", "default": 20},
                "plugin_name": {"type": "string"},
                "xedit_exe": {"type": "string"},
                "scan_cache_dir": {"type": "string"},
                "use_scan_cache": {"type": "boolean", "default": True},
                "scan_cache_ttl_seconds": {"type": "integer", "default": SCAN_DEFAULT_CACHE_TTL_SECONDS},
                "timeout_seconds": {"type": "integer", "default": 60},
            },
            "additionalProperties": False,
        },
        bug_report_bundle,
    ),
    "write_report": (
        "Write a JSON diagnosis report to disk for OpenClaw or another agent to analyze.",
        {
            "type": "object",
            "properties": {
                "output_path": {"type": "string"},
                "vortex_appdata": {"type": "string"},
                "vortex_exe": {"type": "string"},
                "game_id": {"type": "string", "default": GAME_ID},
                "skyrim_dir": {"type": "string"},
                "staging_dir": {"type": "string"},
                "my_games_dir": {"type": "string"},
                "include_mod_inventory": {"type": "boolean", "default": False},
                "include_vortex_profiles": {"type": "boolean", "default": False},
                "include_vortex_deployment": {"type": "boolean", "default": False},
                "include_play_report": {"type": "boolean", "default": False},
            },
            "required": ["output_path"],
            "additionalProperties": False,
        },
        write_report,
    ),
}


def tool_list() -> List[Dict[str, Any]]:
    tools = []
    for name, (description, schema, _func) in TOOLS.items():
        tools.append(
            {
                "name": name,
                "title": name.replace("_", " ").title(),
                "description": description,
                "inputSchema": schema,
            }
        )
    return tools


def handle_call(name: str, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if name not in TOOLS:
        log_event("tool", "unknown", {"tool": name, "args": arguments or {}})
        raise ToolError(f"Unknown tool: {name}")
    args = arguments or {}
    _description, _schema, func = TOOLS[name]
    call_id = uuid.uuid4().hex[:10]
    start = time.perf_counter()
    log_event("tool", "start", {"callId": call_id, "tool": name, "args": args})
    try:
        result = func(args)
        log_event(
            "tool",
            "success",
            {
                "callId": call_id,
                "tool": name,
                "durationMs": int((time.perf_counter() - start) * 1000),
                "result": summarize_result_for_log(result),
            },
        )
        return json_content(result)
    except ToolError as exc:
        log_event(
            "tool",
            "tool_error",
            {"callId": call_id, "tool": name, "durationMs": int((time.perf_counter() - start) * 1000), "error": str(exc)},
        )
        return json_content({"error": str(exc)}, is_error=True)
    except Exception as exc:
        log_event(
            "tool",
            "exception",
            {
                "callId": call_id,
                "tool": name,
                "durationMs": int((time.perf_counter() - start) * 1000),
                "error": str(exc),
                "traceback": traceback.format_exc(limit=8),
            },
        )
        return json_content(
            {
                "error": str(exc),
                "traceback": traceback.format_exc(limit=6),
            },
            is_error=True,
        )


def send(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n")
    sys.stdout.flush()


def response(msg_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def error_response(msg_id: Any, code: int, message: str, data: Any = None) -> Dict[str, Any]:
    error: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": msg_id, "error": error}


def handle_message(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    msg_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}

    # Notifications have no id and require no response.
    if msg_id is None and method:
        return None

    try:
        if method == "initialize":
            log_event("server", "initialize", {"clientInfo": params.get("clientInfo"), "protocolVersion": params.get("protocolVersion")})
            requested = params.get("protocolVersion") or PROTOCOL_VERSION
            return response(
                msg_id,
                {
                    "protocolVersion": requested,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            )
        if method == "ping":
            return response(msg_id, {})
        if method == "tools/list":
            log_event("server", "tools_list", {"count": len(TOOLS)})
            return response(msg_id, {"tools": tool_list()})
        if method == "tools/call":
            return response(msg_id, handle_call(params.get("name"), params.get("arguments")))
        log_event("server", "unknown_method", {"method": method})
        return error_response(msg_id, -32601, f"Method not found: {method}")
    except Exception as exc:
        log_event("server", "message_exception", {"method": method, "error": str(exc), "traceback": traceback.format_exc(limit=6)})
        return error_response(msg_id, -32603, str(exc))


def serve_stdio() -> None:
    log_event("server", "start", {"argv": sys.argv, "cwd": os.getcwd(), "transport": "stdio", "logDir": str(default_log_dir())})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
            messages = parsed if isinstance(parsed, list) else [parsed]
            replies = []
            for msg in messages:
                if not isinstance(msg, dict):
                    replies.append(error_response(None, -32600, "Invalid JSON-RPC message."))
                    continue
                reply = handle_message(msg)
                if reply is not None:
                    replies.append(reply)
            if isinstance(parsed, list):
                if replies:
                    send(replies)  # type: ignore[arg-type]
            elif replies:
                send(replies[0])
        except json.JSONDecodeError as exc:
            log_event("server", "parse_error", {"error": str(exc), "linePreview": line[:1000]})
            send(error_response(None, -32700, "Parse error.", str(exc)))


def self_test() -> int:
    log_event("server", "self_test", {"argv": sys.argv, "cwd": os.getcwd(), "logDir": str(default_log_dir())})
    env = detect_environment({})
    print(json.dumps({"server": SERVER_NAME, "version": SERVER_VERSION, "environment": env}, indent=2))
    return 0


def load_json_object_arg(raw: Optional[str], label: str) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolError(f"{label} must be valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ToolError(f"{label} must decode to a JSON object.")
    return value


def load_cli_tool_args(parsed: argparse.Namespace) -> Dict[str, Any]:
    tool_args: Dict[str, Any] = {}
    if parsed.args_file:
        path = expand_path(parsed.args_file)
        if not path or not path.exists():
            raise ToolError(f"args file was not found: {parsed.args_file}")
        tool_args.update(load_json_object_arg(read_text(path, 2_000_000), "--args-file"))
    tool_args.update(load_json_object_arg(parsed.args_json, "--args-json"))

    common = {
        "output_path": parsed.output_path,
        "case_dir": parsed.case_dir,
        "vortex_appdata": parsed.vortex_appdata,
        "vortex_exe": parsed.vortex_exe,
        "skyrim_dir": parsed.skyrim_dir,
        "staging_dir": parsed.staging_dir,
        "local_appdata": parsed.local_appdata,
        "my_games_dir": parsed.my_games_dir,
        "profile_id": parsed.profile_id,
        "backup_path": parsed.backup_path,
        "backup_dir": parsed.backup_dir,
        "session_json_path": parsed.session_json_path,
        "log_dir": parsed.log_dir,
        "description": parsed.description,
        "location": parsed.location,
        "object": parsed.object,
        "form_id": parsed.form_id,
        "cell": parsed.cell,
        "base_object": parsed.base_object,
        "popup_text": parsed.popup_text,
        "extra_terms": parsed.extra_terms,
        "issue_kind": parsed.issue_kind,
        "performance_mode": parsed.performance_mode,
        "response_mode": parsed.response_mode,
        "scan_mode": parsed.scan_mode,
        "nexus_api_key": parsed.nexus_api_key,
        "nexus_api_key_file": parsed.nexus_api_key_file,
        "nexus_game_domain": parsed.nexus_game_domain,
        "nexus_cache_dir": parsed.nexus_cache_dir,
        "scan_cache_dir": parsed.scan_cache_dir,
        "xedit_exe": parsed.xedit_exe,
        "plugin_name": parsed.plugin_name,
        "collection_manifest_path": parsed.collection_manifest_path,
        "collection_manifest_json": parsed.collection_manifest_json,
        "problem": parsed.problem,
        "workflow_key": parsed.workflow_key,
        "path": parsed.path,
        "report_path": parsed.report_path,
        "terms": parsed.terms,
        "note": parsed.note,
        "kind": parsed.note_kind,
        "source": parsed.note_source,
        "result": parsed.note_result,
        "next_action": parsed.next_action,
        "evidence_type": parsed.evidence_kind,
        "evidence_text": parsed.evidence_text,
        "ocr_text": parsed.ocr_text,
        "reference_form_id": parsed.reference_form_id,
        "base_form_id": parsed.base_form_id,
        "screenshot_path": parsed.screenshot_path,
        "confidence": parsed.confidence,
        "target_mod": parsed.target_mod,
        "target_mod_id": parsed.target_mod_id,
        "test_profile_name": parsed.test_profile_name,
        "signature": parsed.signature,
        "old_text": parsed.old_text,
        "new_text": parsed.new_text,
    }
    for key, value in common.items():
        if value:
            tool_args[key] = value
    if parsed.max_mods is not None:
        tool_args["max_mods"] = parsed.max_mods
    if parsed.max_log_files is not None:
        tool_args["max_log_files"] = parsed.max_log_files
    if parsed.max_file_bytes is not None:
        tool_args["max_file_bytes"] = parsed.max_file_bytes
    if parsed.max_runtime_log_files is not None:
        tool_args["max_runtime_log_files"] = parsed.max_runtime_log_files
    if parsed.max_log_bytes_per_file is not None:
        tool_args["max_log_bytes_per_file"] = parsed.max_log_bytes_per_file
    if parsed.max_runtime_findings is not None:
        tool_args["max_runtime_findings"] = parsed.max_runtime_findings
    if parsed.max_runtime_index_files is not None:
        tool_args["max_runtime_index_files"] = parsed.max_runtime_index_files
    if parsed.fresh_log_hours is not None:
        tool_args["fresh_log_hours"] = parsed.fresh_log_hours
    if parsed.balanced_text_files_per_mod is not None:
        tool_args["balanced_text_files_per_mod"] = parsed.balanced_text_files_per_mod
    if parsed.nexus_cache_ttl_seconds is not None:
        tool_args["nexus_cache_ttl_seconds"] = parsed.nexus_cache_ttl_seconds
    if parsed.nexus_timeout_seconds is not None:
        tool_args["nexus_timeout_seconds"] = parsed.nexus_timeout_seconds
    if parsed.nexus_max_lookup_mods is not None:
        tool_args["nexus_max_lookup_mods"] = parsed.nexus_max_lookup_mods
    if parsed.scan_cache_ttl_seconds is not None:
        tool_args["scan_cache_ttl_seconds"] = parsed.scan_cache_ttl_seconds
    if parsed.max_collection_items is not None:
        tool_args["max_collection_items"] = parsed.max_collection_items
    if parsed.max_workflows is not None:
        tool_args["max_workflows"] = parsed.max_workflows
    if parsed.max_records is not None:
        tool_args["max_records"] = parsed.max_records
    if parsed.max_preview_rows is not None:
        tool_args["max_preview_rows"] = parsed.max_preview_rows
    if parsed.hash_files:
        tool_args["hash_files"] = True
    if parsed.include_nexus_metadata:
        tool_args["include_nexus_metadata"] = True
    if parsed.include_xedit_report:
        tool_args["include_xedit_report"] = True
    if parsed.include_collection_report:
        tool_args["include_collection_report"] = True
    if parsed.include_runtime_logs:
        tool_args["include_runtime_logs"] = True
    if parsed.include_all_workflows:
        tool_args["include_all"] = True
    if parsed.no_direct_cli:
        tool_args["include_direct_cli"] = False
    if parsed.no_nexus_cache:
        tool_args["nexus_use_cache"] = False
    if parsed.no_scan_cache:
        tool_args["use_scan_cache"] = False
    if parsed.no_profile_state:
        tool_args["include_profile_state"] = False
    if parsed.no_conflicts:
        tool_args["include_conflicts"] = False
    if parsed.no_redundancy:
        tool_args["include_redundancy"] = False
    if parsed.no_readme_excerpts:
        tool_args["include_readme_excerpts"] = False
    if parsed.apply:
        tool_args["apply"] = True
    if parsed.allow_running_vortex:
        tool_args["allow_running_vortex"] = True
    if parsed.include_all_profiles:
        tool_args["include_all_profiles"] = True
    if parsed.disable_extra_mods:
        tool_args["disable_extra_mods"] = True
    if parsed.no_backup_before_apply:
        tool_args["backup_before_apply"] = False
    if parsed.no_mod_metadata:
        tool_args["include_mod_metadata"] = False
    if parsed.deep_scan_files:
        tool_args["deep_scan_files"] = True
    if parsed.no_profile_backup:
        tool_args["include_profile_backup"] = False
    if parsed.no_play_report:
        tool_args["include_play_report"] = False
    if parsed.no_logs:
        tool_args["include_logs"] = False
    if parsed.no_runtime_logs:
        tool_args["include_runtime_logs"] = False
    if parsed.no_xedit_script:
        tool_args["include_xedit_script"] = False
    if parsed.no_staged_file_matches:
        tool_args["include_staged_file_matches"] = False
    if parsed.no_config_validation:
        tool_args["validate_config_candidates"] = False
    if parsed.allow_any_path:
        tool_args["allow_any_path"] = True
    if parsed.allow_multiple:
        tool_args["allow_multiple"] = True
    if parsed.no_config_backup:
        tool_args["make_backup"] = False
    return tool_args


def call_tool_direct(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if name not in TOOLS:
        raise ToolError(f"Unknown tool: {name}")
    _description, _schema, func = TOOLS[name]
    call_id = uuid.uuid4().hex[:10]
    start = time.perf_counter()
    log_event("tool", "cli_start", {"callId": call_id, "tool": name, "args": args})
    try:
        result = func(args)
        log_event(
            "tool",
            "cli_success",
            {
                "callId": call_id,
                "tool": name,
                "durationMs": int((time.perf_counter() - start) * 1000),
                "result": summarize_result_for_log(result),
            },
        )
        return result
    except Exception as exc:
        log_event(
            "tool",
            "cli_error",
            {
                "callId": call_id,
                "tool": name,
                "durationMs": int((time.perf_counter() - start) * 1000),
                "error": str(exc),
                "traceback": traceback.format_exc(limit=6),
            },
        )
        raise


def print_json(data: Any, pretty: bool = True) -> None:
    if pretty:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print(json.dumps(data, separators=(",", ":"), ensure_ascii=False, default=str))


def cli_main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="server.py",
        description="Run the Vortex Skyrim SE MCP server or call its tools directly.",
    )
    parser.add_argument("--stdio", action="store_true", help="Run the MCP stdio server explicitly.")
    parser.add_argument("--self-test", action="store_true", help="Run environment self-test and exit.")
    parser.add_argument("--list-tools", action="store_true", help="Print available tool schemas as JSON and exit.")
    parser.add_argument("--tool", help="Call one MCP tool directly without an MCP client.")
    parser.add_argument("--mod-knowledge", action="store_true", help="Shortcut for --tool mod_knowledge_report.")
    parser.add_argument("--safe-session", action="store_true", help="Shortcut for --tool safe_session_report.")
    parser.add_argument("--skyrim-diagnostics", action="store_true", help="Shortcut for --tool skyrim_diagnostics_report.")
    parser.add_argument("--runtime-logs", action="store_true", help="Shortcut for --tool skyrim_runtime_log_report.")
    parser.add_argument("--workflow-guide", action="store_true", help="Shortcut for --tool workflow_guide.")
    parser.add_argument("--issue-case", action="store_true", help="Shortcut for --tool skyrim_issue_case_packet.")
    parser.add_argument("--issue-case-status", action="store_true", help="Shortcut for --tool skyrim_issue_case_status.")
    parser.add_argument("--case-note", action="store_true", help="Shortcut for --tool skyrim_issue_case_note.")
    parser.add_argument("--safe-experiment-plan", action="store_true", help="Shortcut for --tool skyrim_safe_experiment_plan.")
    parser.add_argument("--what-now", action="store_true", help="Shortcut for --tool skyrim_case_what_now.")
    parser.add_argument("--live-bridge-status", action="store_true", help="Shortcut for --tool skyrim_live_bridge_status.")
    parser.add_argument("--case-evidence", action="store_true", help="Shortcut for --tool skyrim_case_evidence_import.")
    parser.add_argument("--case-bundle", action="store_true", help="Shortcut for --tool skyrim_case_bundle.")
    parser.add_argument("--args-json", help="JSON object with tool arguments.")
    parser.add_argument("--args-file", help="Path to a JSON object file with tool arguments.")
    parser.add_argument("--output-json", help="Write the direct tool result JSON to this path.")
    parser.add_argument("--compact", action="store_true", help="Print compact JSON instead of indented JSON.")

    parser.add_argument("--output-path", help="Tool output path, for tools that write reports.")
    parser.add_argument("--case-dir", help="Folder for skyrim_issue_case_packet outputs.")
    parser.add_argument("--vortex-appdata", help="Override Vortex AppData path.")
    parser.add_argument("--vortex-exe", help="Override Vortex.exe path.")
    parser.add_argument("--skyrim-dir", help="Override Skyrim Special Edition folder.")
    parser.add_argument("--staging-dir", help="Override Vortex Skyrim SE staging folder.")
    parser.add_argument("--local-appdata", help="Override LocalAppData path.")
    parser.add_argument("--my-games-dir", help="Override Documents/My Games/Skyrim Special Edition path.")
    parser.add_argument("--profile-id", help="Override selected Vortex profile id.")
    parser.add_argument("--backup-path", help="Profile backup JSON path for restore tools, or explicit backup output path for write tools.")
    parser.add_argument("--backup-dir", help="Folder for automatic profile backups.")
    parser.add_argument("--session-json-path", help="JSON output path for --safe-session.")
    parser.add_argument("--log-dir", help="Override MCP log folder for log_status and support reports.")
    parser.add_argument("--path", help="Target path for read_text_file or apply_config_text_patch.")
    parser.add_argument("--report-path", help="CSV report path for xedit_inspection_script or xedit_inspection_result_report.")
    parser.add_argument("--old-text", help="Exact text to replace for apply_config_text_patch.")
    parser.add_argument("--new-text", help="Replacement text for apply_config_text_patch.")
    parser.add_argument("--description", help="In-game issue description for in_game_issue_report.")
    parser.add_argument("--problem", help="Plain-language problem for workflow_guide.")
    parser.add_argument("--workflow-key", help="Specific workflow key for workflow_guide, or all.")
    parser.add_argument("--location", help="In-game location for in_game_issue_report, such as 'Whiterun Bannered Mare'.")
    parser.add_argument("--object", help="Problem object for in_game_issue_report, such as 'bed' or 'door'.")
    parser.add_argument("--form-id", help="Console-clicked reference/base FormID for in_game_issue_report.")
    parser.add_argument("--cell", help="Current cell/location id or name for in_game_issue_report.")
    parser.add_argument("--base-object", help="Console-clicked base object name/id for in_game_issue_report.")
    parser.add_argument("--popup-text", help="Exact popup/notification text for in_game_issue_report.")
    parser.add_argument("--extra-terms", help="Extra search terms for in_game_issue_report.")
    parser.add_argument("--terms", nargs="*", help="Explicit search terms for xedit_inspection_script.")
    parser.add_argument("--note", help="Case note text for skyrim_issue_case_note.")
    parser.add_argument("--note-kind", choices=["observation", "test", "decision", "undo", "result", "question"], help="Case note kind.")
    parser.add_argument("--note-source", help="Case note source, such as user or openclaw.")
    parser.add_argument("--note-result", help="Short result label for a case note.")
    parser.add_argument("--next-action", help="Next action text for case notes.")
    parser.add_argument("--evidence-kind", choices=["manual", "popup_text", "popup_ocr", "console", "screenshot_note", "skse_telemetry"], help="Evidence kind for skyrim_case_evidence_import.")
    parser.add_argument("--evidence-text", help="Evidence text for skyrim_case_evidence_import.")
    parser.add_argument("--ocr-text", help="OCR text for skyrim_case_evidence_import.")
    parser.add_argument("--reference-form-id", help="Clicked reference FormID for skyrim_case_evidence_import.")
    parser.add_argument("--base-form-id", help="Clicked base FormID for skyrim_case_evidence_import.")
    parser.add_argument("--screenshot-path", help="Screenshot path for skyrim_case_evidence_import.")
    parser.add_argument("--confidence", help="Confidence label for imported evidence.")
    parser.add_argument("--target-mod", help="Target mod name for safe experiment planning.")
    parser.add_argument("--target-mod-id", help="Exact Vortex mod id for safe experiment planning.")
    parser.add_argument("--test-profile-name", help="Name for the cloned test profile in safe experiment planning.")
    parser.add_argument("--signature", help="xEdit record signature for safe experiment planning.")
    parser.add_argument("--issue-kind", choices=["placed_object", "popup", "general"], help="Issue type for in_game_issue_report.")
    parser.add_argument("--performance-mode", choices=["normal", "slow_model", "fast", "thorough"], help="Tune work and output size. Use slow_model for smaller OpenClaw-friendly reports.")
    parser.add_argument("--response-mode", choices=["standard", "compact"], help="Use compact to return fewer nested details for slower AI models.")
    parser.add_argument("--scan-mode", choices=["quick", "balanced", "deep"], help="Issue scan mode. balanced is the default first scan.")
    parser.add_argument("--nexus-api-key", help="Nexus Mods API key. Prefer NEXUS_MODS_API_KEY or --nexus-api-key-file to avoid shell history.")
    parser.add_argument("--nexus-api-key-file", help="Path to a local file containing a Nexus Mods API key.")
    parser.add_argument("--nexus-game-domain", help="Nexus game domain, default skyrimspecialedition.")
    parser.add_argument("--nexus-cache-dir", help="Override local Nexus metadata cache folder.")
    parser.add_argument("--nexus-cache-ttl-seconds", type=int, help="Nexus metadata cache TTL in seconds.")
    parser.add_argument("--nexus-timeout-seconds", type=int, help="Timeout for Nexus API calls.")
    parser.add_argument("--nexus-max-lookup-mods", type=int, help="Maximum local mods to enrich with Nexus metadata.")
    parser.add_argument("--scan-cache-dir", help="Override local mod-summary scan cache folder.")
    parser.add_argument("--scan-cache-ttl-seconds", type=int, help="Mod-summary scan cache TTL in seconds.")
    parser.add_argument("--xedit-exe", help="Path to SSEEdit.exe or xEdit.exe for xedit_diagnostics_report.")
    parser.add_argument("--plugin-name", help="Plugin filename for xedit_diagnostics_report.")
    parser.add_argument("--collection-manifest-path", help="JSON manifest-like file for collection_local_match_report.")
    parser.add_argument("--collection-manifest-json", help="Inline JSON object for collection_local_match_report.")
    parser.add_argument("--max-collection-items", type=int, help="Maximum collection-like entries or manifest refs to scan.")
    parser.add_argument("--max-workflows", type=int, help="Maximum workflows returned by workflow_guide.")
    parser.add_argument("--max-records", type=int, help="Maximum records exported by xedit_inspection_script.")
    parser.add_argument("--max-preview-rows", type=int, help="Maximum preview rows returned by xedit_inspection_result_report.")
    parser.add_argument("--max-mods", type=int, help="Maximum mods to scan for supported tools.")
    parser.add_argument("--max-log-files", type=int, help="Maximum recent log files for support reports.")
    parser.add_argument("--max-file-bytes", type=int, help="Maximum bytes per file for case bundle output.")
    parser.add_argument("--max-runtime-log-files", type=int, help="Maximum recent Skyrim runtime log files to scan.")
    parser.add_argument("--max-log-bytes-per-file", type=int, help="Maximum tail bytes read from each Skyrim runtime log.")
    parser.add_argument("--max-runtime-findings", type=int, help="Maximum runtime log findings to return.")
    parser.add_argument("--max-runtime-index-files", type=int, help="Maximum staged files to index for runtime log reference matching.")
    parser.add_argument("--fresh-log-hours", type=float, help="Runtime logs older than this many hours are marked stale.")
    parser.add_argument("--balanced-text-files-per-mod", type=int, help="For balanced issue scans, max config/text files to read per mod.")
    parser.add_argument("--hash-files", action="store_true", help="Hash files for stronger duplicate evidence. Slower.")
    parser.add_argument("--include-nexus-metadata", action="store_true", help="Include optional read-only Nexus metadata in supported reports.")
    parser.add_argument("--include-xedit-report", action="store_true", help="Include read-only xEdit/SSEEdit target hints in supported reports.")
    parser.add_argument("--include-collection-report", action="store_true", help="Include read-only Vortex collection-state hints in supported reports.")
    parser.add_argument("--include-runtime-logs", action="store_true", help="Include Skyrim runtime log scanning in supported reports that do not enable it by default.")
    parser.add_argument("--include-all-workflows", action="store_true", help="Return every workflow from workflow_guide.")
    parser.add_argument("--no-direct-cli", action="store_true", help="Hide direct CLI examples from workflow_guide output.")
    parser.add_argument("--no-nexus-cache", action="store_true", help="Disable the local Nexus metadata cache for this call.")
    parser.add_argument("--no-scan-cache", action="store_true", help="Disable the local mod-summary scan cache for this call.")
    parser.add_argument("--apply", action="store_true", help="Apply a write-capable tool. Most tools are dry-run without this.")
    parser.add_argument("--allow-running-vortex", action="store_true", help="Allow Vortex profile writes while Vortex.exe is running.")
    parser.add_argument("--include-all-profiles", action="store_true", help="For profile backup, include every detected Skyrim SE profile.")
    parser.add_argument("--disable-extra-mods", action="store_true", help="For profile restore, disable currently enabled mods that were not in the backup.")
    parser.add_argument("--no-profile-state", action="store_true", help="Do not call Vortex CLI for profile state.")
    parser.add_argument("--no-conflicts", action="store_true", help="Skip conflict scanning for supported tools.")
    parser.add_argument("--no-redundancy", action="store_true", help="Skip redundancy scanning for supported tools.")
    parser.add_argument("--no-readme-excerpts", action="store_true", help="Skip readme snippets for mod knowledge reports.")
    parser.add_argument("--no-backup-before-apply", action="store_true", help="Do not write an automatic profile backup before apply=true.")
    parser.add_argument("--no-mod-metadata", action="store_true", help="For profile backup, omit Vortex mod metadata.")
    parser.add_argument("--deep-scan-files", action="store_true", help="For in_game_issue_report, scan extra file paths and text/config files. Slower.")
    parser.add_argument("--no-profile-backup", action="store_true", help="For --safe-session, skip the profile backup section.")
    parser.add_argument("--no-play-report", action="store_true", help="For --safe-session, skip the modded play health section.")
    parser.add_argument("--no-logs", action="store_true", help="For --safe-session or bug reports, skip log status.")
    parser.add_argument("--no-runtime-logs", action="store_true", help="Skip Skyrim runtime log scanning in safe-session, diagnostics, and bug bundles.")
    parser.add_argument("--no-xedit-script", action="store_true", help="For skyrim_issue_case_packet, skip generating the xEdit inspection script.")
    parser.add_argument("--no-staged-file-matches", action="store_true", help="For skyrim_runtime_log_report, skip staged file indexing/matching.")
    parser.add_argument("--no-config-validation", action="store_true", help="For skyrim_runtime_log_report, skip validating config candidates.")
    parser.add_argument("--allow-any-path", action="store_true", help="Allow read/patch tools outside detected Vortex/Skyrim roots.")
    parser.add_argument("--allow-multiple", action="store_true", help="Allow apply_config_text_patch to replace multiple occurrences of old_text.")
    parser.add_argument("--no-config-backup", action="store_true", help="Do not create a backup when apply_config_text_patch writes.")

    parsed = parser.parse_args(argv)
    if parsed.self_test:
        return self_test()
    if parsed.stdio:
        serve_stdio()
        return 0
    if parsed.list_tools:
        print_json({"server": SERVER_NAME, "version": SERVER_VERSION, "tools": tool_list()}, pretty=not parsed.compact)
        return 0

    tool_name = (
        "skyrim_diagnostics_report"
        if parsed.skyrim_diagnostics
        else "safe_session_report"
        if parsed.safe_session
        else "skyrim_runtime_log_report"
        if parsed.runtime_logs
        else "mod_knowledge_report"
        if parsed.mod_knowledge
        else "workflow_guide"
        if parsed.workflow_guide
        else "skyrim_issue_case_packet"
        if parsed.issue_case
        else "skyrim_issue_case_status"
        if parsed.issue_case_status
        else "skyrim_issue_case_note"
        if parsed.case_note
        else "skyrim_safe_experiment_plan"
        if parsed.safe_experiment_plan
        else "skyrim_case_what_now"
        if parsed.what_now
        else "skyrim_live_bridge_status"
        if parsed.live_bridge_status
        else "skyrim_case_evidence_import"
        if parsed.case_evidence
        else "skyrim_case_bundle"
        if parsed.case_bundle
        else parsed.tool
    )
    if not tool_name:
        parser.error("pass --stdio, --self-test, --list-tools, --tool NAME, --mod-knowledge, --safe-session, --skyrim-diagnostics, --runtime-logs, --workflow-guide, --issue-case, --issue-case-status, --case-note, --safe-experiment-plan, --what-now, --live-bridge-status, --case-evidence, or --case-bundle")

    try:
        tool_args = load_cli_tool_args(parsed)
        result = call_tool_direct(tool_name, tool_args)
        if parsed.output_json:
            output_json = expand_path(parsed.output_json)
            if not output_json:
                raise ToolError("--output-json resolved to an empty path.")
            write_text(output_json, json.dumps(result, indent=2, ensure_ascii=False, default=str))
        print_json(result, pretty=not parsed.compact)
        return 0
    except Exception as exc:
        print_json({"error": str(exc), "tool": tool_name}, pretty=True)
        return 2


if __name__ == "__main__":
    if len(sys.argv) == 1:
        serve_stdio()
    else:
        raise SystemExit(cli_main(sys.argv[1:]))
