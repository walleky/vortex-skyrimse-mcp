#!/usr/bin/env python3
"""
Vortex Skyrim SE MCP server for Windows.

This is a dependency-free MCP stdio server. It exposes safe tools for an MCP
client to inspect a Vortex-managed Skyrim Special Edition install, diagnose
deployment/plugin/INI issues, and build conflict/redundancy reports.

Write actions are intentionally narrow and dry-run by default.
"""

from __future__ import annotations

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
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

try:
    import winreg  # type: ignore
except Exception:  # pragma: no cover - non-Windows test hosts
    winreg = None


SERVER_NAME = "vortex-skyrimse-mcp"
SERVER_VERSION = "0.2.0"
PROTOCOL_VERSION = "2025-06-18"
SKYRIM_APP_ID = "489830"
GAME_ID = "skyrimse"
MAX_DEFAULT_TEXT_BYTES = 200_000
MAX_DEFAULT_FILES = 40_000
MAX_VORTEX_CLI_CHARS = 24_000


class ToolError(Exception):
    """Business error returned as a MCP tool error."""


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr, flush=True)


def now_stamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def expand_path(value: Optional[str]) -> Optional[Path]:
    if not value:
        return None
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


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
        raise ToolError(
            "Vortex.exe was not found. Pass vortex_exe, or install Vortex in the normal per-user location."
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
        raise ToolError(
            f"Vortex CLI timed out after {timeout_seconds}s. Close Vortex and try again; the state database may be busy."
        ) from exc
    except OSError as exc:
        raise ToolError(f"Could not run Vortex CLI at {vortex_exe}: {exc}") from exc

    result = {
        "vortex_exe": str(vortex_exe),
        "args": cli_args,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
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
    local_appdata = default_local_appdata()
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
    if apply_changes:
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
        "applied": bool(apply_result),
        "applyBatches": apply_result.get("batchCount") if apply_result else None,
        "vortex_exe": apply_result["vortex_exe"] if apply_result else snapshot["vortex_exe"],
        "notes": [
            "Use apply=true only with Vortex closed. By default this tool refuses writes while Vortex.exe is running.",
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
    if apply_changes:
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
        "applied": bool(apply_result),
        "applyBatches": apply_result.get("batchCount") if apply_result else None,
        "vortex_exe": apply_result["vortex_exe"] if apply_result else snapshot["vortex_exe"],
        "notes": [
            "This only changes Vortex profile state. It does not delete mods.",
            "Close Vortex before apply=true. By default this tool refuses writes while Vortex.exe is running.",
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
    highest = findings[0]["severity"] if findings else "none"
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
            },
            "additionalProperties": False,
        },
        detect_environment,
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
        raise ToolError(f"Unknown tool: {name}")
    args = arguments or {}
    _description, _schema, func = TOOLS[name]
    try:
        return json_content(func(args))
    except ToolError as exc:
        return json_content({"error": str(exc)}, is_error=True)
    except Exception as exc:
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
            return response(msg_id, {"tools": tool_list()})
        if method == "tools/call":
            return response(msg_id, handle_call(params.get("name"), params.get("arguments")))
        return error_response(msg_id, -32601, f"Method not found: {method}")
    except Exception as exc:
        return error_response(msg_id, -32603, str(exc))


def serve_stdio() -> None:
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
            send(error_response(None, -32700, "Parse error.", str(exc)))


def self_test() -> int:
    env = detect_environment({})
    print(json.dumps({"server": SERVER_NAME, "version": SERVER_VERSION, "environment": env}, indent=2))
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    serve_stdio()
