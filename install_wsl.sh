#!/usr/bin/env bash
set -euo pipefail

CLIENT_NAME="openclaw"
CONFIG_OUT=""
PYTHON_COMMAND="${PYTHON_COMMAND:-python3}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --client-name)
      CLIENT_NAME="${2:-openclaw}"
      shift 2
      ;;
    --config-out)
      CONFIG_OUT="${2:-}"
      shift 2
      ;;
    --python-command)
      PYTHON_COMMAND="${2:-python3}"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

if ! command -v "$PYTHON_COMMAND" >/dev/null 2>&1; then
  echo "Python 3 was not found in WSL. Install python3, then rerun this script." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER="$SCRIPT_DIR/server.py"
if [[ ! -f "$SERVER" ]]; then
  echo "server.py was not found beside this installer." >&2
  exit 1
fi

"$PYTHON_COMMAND" "$SERVER" --list-tools --compact >/dev/null

WINDOWS_PROFILE="${VORTEX_SKYRIMSE_MCP_WINDOWS_USERPROFILE:-}"
if [[ -z "$WINDOWS_PROFILE" && -n "${USER:-}" && -d "/mnt/c/Users/${USER}/AppData/Roaming" ]]; then
  WINDOWS_PROFILE="/mnt/c/Users/${USER}"
fi
if [[ -z "$WINDOWS_PROFILE" && -d "/mnt/c/Users" ]]; then
  while IFS= read -r candidate; do
    name="$(basename "$candidate")"
    case "${name,,}" in
      "all users"|"default"|"default user"|"public")
        continue
        ;;
    esac
    if [[ -d "$candidate/AppData/Roaming" || -d "$candidate/Documents" ]]; then
      WINDOWS_PROFILE="$candidate"
      break
    fi
  done < <(find /mnt/c/Users -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)
fi

CONFIG_JSON="$("$PYTHON_COMMAND" - "$SERVER" "$WINDOWS_PROFILE" <<'PY'
import json
import sys

server = sys.argv[1]
windows_profile = sys.argv[2] if len(sys.argv) > 2 else ""
env = {
    "VORTEX_SKYRIMSE_MCP_WSL_MOUNT_ROOT": "/mnt",
}
if windows_profile:
    env["VORTEX_SKYRIMSE_MCP_WINDOWS_USERPROFILE"] = windows_profile
snippet = {
    "mcpServers": {
        "vortex-skyrimse": {
            "command": "python3",
            "args": [server],
            "env": env,
        }
    }
}
print(json.dumps(snippet, indent=2))
PY
)"

echo
echo "Vortex Skyrim SE MCP server is ready for WSL/OpenClaw."
echo
echo "Add this MCP server config to ${CLIENT_NAME}:"
echo
printf '%s\n' "$CONFIG_JSON"
echo

if [[ -n "$CONFIG_OUT" ]]; then
  mkdir -p "$(dirname "$CONFIG_OUT")"
  printf '%s\n' "$CONFIG_JSON" > "$CONFIG_OUT"
  echo "Wrote config snippet to: $CONFIG_OUT"
fi

echo "Quick WSL bridge test:"
echo "  $PYTHON_COMMAND \"$SERVER\" --wsl-bridge"
echo
echo "If Windows paths do not resolve, rerun OpenClaw with:"
echo "  export VORTEX_SKYRIMSE_MCP_WINDOWS_USERPROFILE=/mnt/c/Users/<you>"
