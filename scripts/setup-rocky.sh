#!/usr/bin/env bash
# Rocky 9.x setup: install system deps, Python 3.11, venv, project deps, and self-check.
set -euo pipefail

if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'; C_BLUE=$'\033[34m'; C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'
else
  C_RESET=''; C_BLUE=''; C_GREEN=''; C_YELLOW=''; C_RED=''
fi

info() { printf '%s==>%s %s\n' "$C_BLUE" "$C_RESET" "$*"; }
ok()   { printf '%s==>%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%sWARNING:%s %s\n' "$C_YELLOW" "$C_RESET" "$*"; }
fail() { printf '%sERROR:%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

SKIP_SYSTEM_DEPS=0

print_usage() {
  cat <<'EOF'
Usage: scripts/setup-rocky.sh [OPTIONS]

Prepare a Rocky 9.x environment for building SCP Story EPUBs.

Options:
  --skip-system-deps   Skip the sudo dnf step. Use when Python 3.11 is already
                       available on PATH (e.g. via uv).
  -h, --help           Show this help and exit.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-system-deps) SKIP_SYSTEM_DEPS=1; shift ;;
    -h|--help) print_usage; exit 0 ;;
    *) fail "Unknown option: $1 (try --help)" ;;
  esac
done

if [[ -f /etc/os-release ]]; then
  # shellcheck source=/dev/null
  . /etc/os-release
  if [[ "${ID:-}" == *rocky* || "${ID:-}" == *rhel* ]] && [[ "${VERSION_ID:-}" == 9.* ]]; then
    ok "Detected ${PRETTY_NAME:-Rocky/RHEL 9.x}."
  else
    warn "Detected ${PRETTY_NAME:-unknown OS}, not Rocky/RHEL 9.x. Continuing anyway."
  fi
else
  warn "/etc/os-release not found; cannot detect OS. Continuing anyway."
fi

if [[ ":${PATH}:" == *":/mnt/c/"* ]]; then
  warn "WSL PATH contains /mnt/c entries. If commands resolve to Windows binaries, check WSL PATH interop."
fi

SYSTEM_PACKAGES=(python3.11 python3.11-pip gcc redhat-rpm-config)
if [[ "$SKIP_SYSTEM_DEPS" -eq 1 ]]; then
  info "Skipping system dependencies (--skip-system-deps)."
else
  info "Installing system packages: ${SYSTEM_PACKAGES[*]}"
  sudo dnf install -y "${SYSTEM_PACKAGES[@]}"
fi

PY=python3.11
if [[ -x /usr/bin/python3.11 ]]; then
  PY=/usr/bin/python3.11
elif ! command -v "$PY" >/dev/null 2>&1; then
  fail "python3.11 not found. Run without --skip-system-deps, or install Python 3.11 (e.g. via uv)."
fi
info "Using Python: $PY ($("$PY" --version))"

VENV_DIR="$REPO_ROOT/.venv"
if [[ ! -d "$VENV_DIR" ]]; then
  info "Creating venv at $VENV_DIR"
  "$PY" -m venv "$VENV_DIR"
else
  info "venv already exists at $VENV_DIR; reusing."
fi
# shellcheck source=/dev/null
. "$VENV_DIR/bin/activate"

info "Upgrading pip"
python -m pip install --upgrade pip

info "Installing project dependencies (editable, with dev extras)"
pip install -e ".[dev]"

info "Self-check"
python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || fail "Python in venv is not 3.11+."
python -c "import lxml, PIL, resvg_py, ebooklib, bs4, httpx, tinycss2, yaml" \
  || fail "Required Python modules not importable; run 'pip install -e .[dev]' first."
ok "All required modules importable."

if command -v ebook-convert >/dev/null 2>&1; then
  ok "Calibre ebook-convert found; Kindle builds (--kindle) are available."
else
  warn "Calibre ebook-convert not found. Kindle builds need it; see README's Calibre section."
fi

ok "Setup complete. Next steps:"
printf '  source .venv/bin/activate\n'
printf '  pytest -q\n'
printf '  python -m scp_epub --config config/series-1.yaml build --volume 001-099\n'
printf '  python -m scp_epub --config config/featured-scp.yaml build --volume featured\n'
