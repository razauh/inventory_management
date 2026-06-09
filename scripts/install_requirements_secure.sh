#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT_DIR/requirements.in"
LOCK_FILE="$ROOT_DIR/requirements.lock.txt"
LOCK_SCRIPT="$ROOT_DIR/scripts/lock_requirements.py"
VERIFY_SCRIPT="$ROOT_DIR/scripts/verify_wheelhouse.py"
APP_WHEELHOUSE="${WHEELHOUSE_DIR:-$ROOT_DIR/.wheelhouse-app}"
LOCAL_PYTHON="$ROOT_DIR/.conda/bin/python"
PYTHON_BIN="${PYTHON_BIN:-}"

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$LOCAL_PYTHON" ]]; then
    PYTHON_BIN="$LOCAL_PYTHON"
  else
    PYTHON_BIN="$(command -v python3 || true)"
  fi
fi

if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "Error: python runtime not found." >&2
  exit 1
fi

if [[ ! -f "$MANIFEST" ]]; then
  echo "Error: missing requirements manifest at $MANIFEST." >&2
  exit 1
fi

if [[ ! -f "$LOCK_SCRIPT" ]]; then
  echo "Error: missing lock generator at $LOCK_SCRIPT." >&2
  exit 1
fi

if [[ ! -f "$VERIFY_SCRIPT" ]]; then
  echo "Error: missing wheelhouse verifier at $VERIFY_SCRIPT." >&2
  exit 1
fi

if [[ ! -d "$APP_WHEELHOUSE" ]] || ! find "$APP_WHEELHOUSE" -maxdepth 1 -name '*.whl' -print -quit >/dev/null 2>&1; then
  echo "Error: app wheelhouse is missing or empty: $APP_WHEELHOUSE" >&2
  echo "Seed it from a vetted source first, then rerun this script." >&2
  exit 1
fi

"$PYTHON_BIN" "$LOCK_SCRIPT" --manifest "$MANIFEST" --wheelhouse "$APP_WHEELHOUSE" --output "$LOCK_FILE"
"$PYTHON_BIN" "$VERIFY_SCRIPT" --lock-file "$LOCK_FILE" --wheelhouse "$APP_WHEELHOUSE"
"$PYTHON_BIN" -m pip install -r "$ROOT_DIR/requirements.txt"
