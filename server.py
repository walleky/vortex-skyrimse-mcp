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
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

try:
    import winreg  # type: ignore
except Exception:  # pragma: no cover - non-Windows test hosts
    winreg = None


SERVER_NAME = "vortex-skyrimse-mcp"
SERVER_VERSION = "0.2.10"
PROTOCOL_VERSION = "2025-06-18"
SKYRIM_APP_ID = "489830"
GAME_ID = "skyrimse"
MAX_DEFAULT_TEXT_BYTES = 200_000
MAX_DEFAULT_FILES = 40_000
MAX_VORTEX_CLI_CHARS = 24_000
LOG_ENV_VAR = "VORTEX_SKYRIMSE_MCP_LOG_DIR"
LOG_TAIL_DEFAULT_BYTES = 80_000


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
            result[str(key)] = compact_for_log(item, max_string, max_items, depth + 1)
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
        eprint(f"{SERVER_NAME}: logging failed: {exc}")


def tail_file_text(path: Path, max_bytes: int = LOG_TAIL_DEFAULT_BYTES) -> str:
    data = path.read_bytes()
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    return data.decode("utf-8", errors="replace")


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
        "issues": issues,
    }


def validate_setup(args: Dict[str, Any]) -> Dict[str, Any]:
    environment = detect_environment(args)
    tool_groups = {
        "alwaysAvailable": [
            "detect_environment",
            "validate_setup",
            "inventory_mods",
            "analyze_conflicts",
            "redundant_mod_report",
            "plugin_report",
            "ini_report",
            "mod_knowledge_report",
            "in_game_issue_report",
            "safe_session_report",
            "bug_report_bundle",
        ],
        "vortexCliRequired": [
            "vortex_profile_report",
            "vortex_profile_mods",
            "vortex_compare_profiles",
            "vortex_profile_deployment_report",
            "vortex_profile_backup",
            "vortex_profile_restore_plan",
            "vortex_clone_profile",
            "vortex_set_profile_mods",
        ],
        "writeCapableDryRunFirst": [
            "apply_ini_fixes",
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
    for mod_dir in sorted([p for p in staging_dir.iterdir() if p.is_dir()], key=lambda p: p.name.lower())[:max_mods]:
        mods.append(mod_summary(mod_dir, include_files=include_files, max_files=max_files_per_mod))
    return {
        "vortex_appdata": str(vortex_appdata) if vortex_appdata else None,
        "staging_dir": str(staging_dir),
        "modCount": len(mods),
        "mods": mods,
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
        conflicts.append(
            {
                "relativePath": rel,
                "kind": classify_file(rel),
                "providerCount": len(entries),
                "sameSize": len(sizes) == 1,
                "sameHash": (len([h for h in hashes or [] if h]) == 1) if hash_files else None,
                "providers": entries,
            }
        )
    conflicts.sort(key=lambda c: (c["kind"], -c["providerCount"], c["relativePath"]))

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
    summaries = [mod_summary(p, include_files=False, max_files=8000) for p in mods]

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


def tokenize_issue_terms(*values: Optional[str]) -> List[str]:
    terms: set[str] = set()
    joined = " ".join(str(value or "") for value in values).lower()
    for token in re.findall(r"[a-z0-9_'-]{3,}", joined):
        clean = token.strip("_'-")
        if clean and clean not in ISSUE_STOP_WORDS:
            terms.add(clean)
    if "whiterun" in terms and ({"tavern", "inn", "room"} & terms):
        terms.update({"bannered", "mare", "inn"})
    if "bannered" in terms or "mare" in terms:
        terms.update({"bannered", "mare", "whiterun", "tavern", "inn"})
    if "bed" in terms:
        terms.update({"bedroll", "furniture", "furn"})
    if {"popup", "popups", "notification", "message"} & terms:
        terms.update({"message", "notification", "mcm", "menu", "interface", "dialog", "skyui"})
    return sorted(terms)


def matched_issue_terms(text: str, terms: Iterable[str]) -> List[str]:
    lower = text.lower()
    return sorted({term for term in terms if term and term in lower})


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
    if args.get("popup_text") or {"popup", "popups", "notification", "message", "mcm", "menu"} & set(terms):
        return "popup"
    if args.get("object") or {"bed", "bedroll", "furniture", "furn"} & set(terms):
        return "placed_object"
    return "general"


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
    deep_scan_files = bool(args.get("deep_scan_files", False))
    evidence: List[Dict[str, Any]] = []
    matched: set[str] = set()
    score = 0
    plugin_location_hit = False
    plugin_object_hit = False
    popup_text_hit = False
    popup_text = str(args.get("popup_text") or "").strip()

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

    text_suffixes = {".txt", ".md", ".ini", ".json", ".xml"}
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

    if deep_scan_files:
        for file_path in safe_walk(mod_dir, max_files):
            rel = rel_to(file_path, mod_dir)
            kind = classify_file(rel)
            path_hits = score_hits(f"file path: {rel}", rel, terms, 1)
            if kind != "plugin" and file_path.suffix.lower() in text_suffixes and len(evidence) < max_evidence:
                text = read_file_head(file_path, max_text_bytes)
                score_hits(f"text file: {rel}", text, terms, 2)
            if path_hits and kind in {"interface", "script", "skse_plugin"}:
                score += 2

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

    issue_kind = infer_issue_kind(args, terms)
    if issue_kind == "popup":
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
        "scannedPluginCount": scanned_plugins,
        "deepScanFiles": deep_scan_files,
    }


def in_game_issue_report(args: Dict[str, Any]) -> Dict[str, Any]:
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
    if not terms:
        raise ToolError("Pass description, location, object, popup_text, or extra_terms so the tool has something to search for.")
    location_terms = tokenize_issue_terms(location)
    object_terms = tokenize_issue_terms(problem_object, base_object)
    popup_terms = tokenize_issue_terms(popup_text, description if infer_issue_kind(args, terms) == "popup" else "")
    issue_kind = infer_issue_kind(args, terms)

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
    for mod_dir in mod_dirs:
        summary = mod_summary(mod_dir, include_files=False, max_files=int(args.get("max_files_per_mod", 3000)))
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

    recommended_actions = [
        "Do not delete the candidate mod. Create or use a cloned Vortex profile and test disabling one candidate at a time.",
        "If this is a placed object, open Skyrim's console, click the object, and give OpenClaw the shown reference/base FormID and object name.",
        "If the first two hex digits of a FormID identify a plugin in your load order, inspect that plugin first.",
        "Use xEdit/SSEEdit to inspect the reported cell or quest/message records before applying any fix.",
    ]
    if issue_kind == "popup":
        recommended_actions.insert(1, "Copy the exact popup text or attach a screenshot/OCR text; exact text makes the search much stronger.")
        recommended_actions.append("Check the candidate mod's MCM/settings before disabling it, because many popups are configurable notifications.")

    return {
        "issue": {
            "kind": issue_kind,
            "description": description,
            "location": location,
            "object": problem_object,
            "cell": cell,
            "baseObject": base_object,
            "formId": normalize_form_id(form_id),
            "popupTextProvided": bool(popup_text),
        },
        "formIdHint": form_id_load_order_hint(args, form_id),
        "staging_dir": str(staging_dir),
        "searchedTerms": terms,
        "profileState": profile_state_summary,
        "scannedModCount": len(mod_dirs),
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
            "For popups, exact text is much stronger than saying 'annoying popup'.",
        ],
    }


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
            "This report is based on local evidence: staged files, plugin headers, FOMOD metadata, readme snippets, Vortex profile state when available, duplicate-file checks, and conflict overlaps. It does not download mod-page descriptions by itself.",
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
    for mod_dir in mod_dirs:
        summary = mod_summary(mod_dir, include_files=False, max_files=max_files_per_mod)
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
        rows.append(
            {
                "summary": summary,
                "knowledge": knowledge,
                "pluginHeaders": plugin_headers,
                "profile": profile_by_path.get(profile_key),
                "conflictCount": conflict_stats.get("count", 0),
                "conflictExamples": conflict_stats.get("examples", []),
                "readmeExcerpts": first_readme_lines(mod_dir, summary.get("readmes", []), readme_lines, readme_bytes)
                if include_readmes
                else [],
            }
        )

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
        "redactedUserPaths": redact_user_paths,
        "notes": [
            "The Markdown report is evidence-based and read-only.",
            "Disable candidate mods in a cloned profile before uninstalling or deleting anything.",
            "The tool infers purpose from local files and metadata; it does not fetch Nexus page descriptions.",
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

    for mod_id in sorted(enabled_mod_ids, key=str.lower)[:max_mods]:
        mod_entry = snapshot["mods"].get(mod_id)
        mod_path = resolve_mod_staging_path(mod_id, mod_entry, staging_dir)
        if not mod_path:
            unresolved_mods.append({**summarize_vortex_mod(mod_id, snapshot["mods"]), "reason": "staging folder not found"})
            continue
        summary = mod_summary(mod_path, include_files=False, max_files=max_files_per_mod)
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
            actions.append(
                {
                    "priority": "medium",
                    "type": "sensitive_file_conflict",
                    "relativePath": item["relativePath"],
                    "providers": [p["mod"] for p in item["providers"]],
                    "message": "Conflict touches scripts, SKSE DLLs, or UI files. Pick the intended winner in Vortex's Conflicts view.",
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
        "inGameIssueError": ("medium", "Rerun with simpler issue text, exact popup text, or console FormID if available."),
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
            lines.append("- No candidates found. Try exact popup text, console FormID, or deep_scan_files=true.")

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
    markdown_path = safe_session_default_path(args)
    json_path = expand_path(args.get("session_json_path"))
    if not json_path:
        json_path = markdown_path.with_suffix(".json")
    if json_path == markdown_path:
        json_path = markdown_path.with_name(f"{markdown_path.name}.json")
    include_profile_backup = bool(args.get("include_profile_backup", True))
    include_play_report = bool(args.get("include_play_report", True))
    include_logs = bool(args.get("include_logs", True))
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
    if any(args.get(key) for key in ("description", "location", "object", "form_id", "cell", "base_object", "popup_text", "extra_terms")):
        collect_section(sections, "inGameIssue", in_game_issue_report, args)
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
        },
        "findings": findings,
        "nextActions": next_actions,
        "sections": sections,
        "notes": [
            "This is a no-change safe session report.",
            "Profile backup may fail if Vortex.exe is not detected; pass vortex_exe or back up in Vortex.",
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
        except Exception as exc:
            bundle["skyrimModdedPlayError"] = str(exc)

    if any(args.get(key) for key in ("description", "location", "object", "form_id", "cell", "base_object", "popup_text", "extra_terms")):
        try:
            bundle["inGameIssue"] = in_game_issue_report(args)
        except Exception as exc:
            bundle["inGameIssueError"] = str(exc)

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
    "inventory_mods": (
        "Inventory staged Vortex Skyrim SE mods, file kinds, plugins, archives, SKSE DLLs, readmes, and metadata.",
        {
            "type": "object",
            "properties": {
                "vortex_appdata": {"type": "string"},
                "staging_dir": {"type": "string"},
                "include_files": {"type": "boolean", "default": False},
                "max_mods": {"type": "integer", "default": 300},
                "max_files_per_mod": {"type": "integer", "default": 5000},
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
                "deep_scan_files": {"type": "boolean", "default": False},
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
                "include_conflicts": {"type": "boolean", "default": False},
                "redact_user_paths": {"type": "boolean", "default": True},
                "description": {"type": "string"},
                "location": {"type": "string"},
                "object": {"type": "string"},
                "form_id": {"type": "string"},
                "cell": {"type": "string"},
                "base_object": {"type": "string"},
                "popup_text": {"type": "string"},
                "extra_terms": {"type": "string"},
                "issue_kind": {"type": "string", "enum": ["placed_object", "popup", "general"]},
                "deep_scan_files": {"type": "boolean", "default": False},
                "hash_files": {"type": "boolean", "default": False},
                "max_mods": {"type": "integer", "default": 500},
                "max_candidates": {"type": "integer", "default": 20},
                "max_files_per_mod": {"type": "integer", "default": 3000},
                "max_conflicts": {"type": "integer", "default": 300},
                "max_log_files": {"type": "integer", "default": 12},
                "timeout_seconds": {"type": "integer", "default": 60},
            },
            "additionalProperties": False,
        },
        safe_session_report,
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
                "max_mods": {"type": "integer", "default": 500},
                "max_files_per_mod": {"type": "integer", "default": 3000},
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
                "max_text_bytes": {"type": "integer", "default": 12000},
                "max_plugin_bytes": {"type": "integer", "default": 5000000},
                "max_plugin_strings": {"type": "integer", "default": 2500},
                "max_evidence_per_mod": {"type": "integer", "default": 10},
                "deep_scan_files": {"type": "boolean", "default": False},
                "include_logs": {"type": "boolean", "default": True},
                "include_vortex_profiles": {"type": "boolean", "default": True},
                "include_vortex_deployment": {"type": "boolean", "default": True},
                "include_play_report": {"type": "boolean", "default": True},
                "include_conflicts": {"type": "boolean", "default": False},
                "redact_user_paths": {"type": "boolean", "default": True},
                "zip_output": {"type": "boolean", "default": False},
                "zip_path": {"type": "string"},
                "include_log_tails_in_zip": {"type": "boolean", "default": True},
                "max_log_files": {"type": "integer", "default": 12},
                "max_log_bytes": {"type": "integer", "default": LOG_TAIL_DEFAULT_BYTES},
                "max_mods": {"type": "integer", "default": 500},
                "max_files_per_mod": {"type": "integer", "default": 3000},
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
    }
    for key, value in common.items():
        if value:
            tool_args[key] = value
    if parsed.max_mods is not None:
        tool_args["max_mods"] = parsed.max_mods
    if parsed.max_log_files is not None:
        tool_args["max_log_files"] = parsed.max_log_files
    if parsed.hash_files:
        tool_args["hash_files"] = True
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
    parser.add_argument("--args-json", help="JSON object with tool arguments.")
    parser.add_argument("--args-file", help="Path to a JSON object file with tool arguments.")
    parser.add_argument("--output-json", help="Write the direct tool result JSON to this path.")
    parser.add_argument("--compact", action="store_true", help="Print compact JSON instead of indented JSON.")

    parser.add_argument("--output-path", help="Tool output path, for tools that write reports.")
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
    parser.add_argument("--description", help="In-game issue description for in_game_issue_report.")
    parser.add_argument("--location", help="In-game location for in_game_issue_report, such as 'Whiterun Bannered Mare'.")
    parser.add_argument("--object", help="Problem object for in_game_issue_report, such as 'bed' or 'door'.")
    parser.add_argument("--form-id", help="Console-clicked reference/base FormID for in_game_issue_report.")
    parser.add_argument("--cell", help="Current cell/location id or name for in_game_issue_report.")
    parser.add_argument("--base-object", help="Console-clicked base object name/id for in_game_issue_report.")
    parser.add_argument("--popup-text", help="Exact popup/notification text for in_game_issue_report.")
    parser.add_argument("--extra-terms", help="Extra search terms for in_game_issue_report.")
    parser.add_argument("--issue-kind", choices=["placed_object", "popup", "general"], help="Issue type for in_game_issue_report.")
    parser.add_argument("--max-mods", type=int, help="Maximum mods to scan for supported tools.")
    parser.add_argument("--max-log-files", type=int, help="Maximum recent log files for support reports.")
    parser.add_argument("--hash-files", action="store_true", help="Hash files for stronger duplicate evidence. Slower.")
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

    parsed = parser.parse_args(argv)
    if parsed.self_test:
        return self_test()
    if parsed.stdio:
        serve_stdio()
        return 0
    if parsed.list_tools:
        print_json({"server": SERVER_NAME, "version": SERVER_VERSION, "tools": tool_list()}, pretty=not parsed.compact)
        return 0

    tool_name = "safe_session_report" if parsed.safe_session else "mod_knowledge_report" if parsed.mod_knowledge else parsed.tool
    if not tool_name:
        parser.error("pass --stdio, --self-test, --list-tools, --tool NAME, --mod-knowledge, or --safe-session")

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
