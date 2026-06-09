#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT_DIR/requirements.in"
WHEELHOUSE="${WHEELHOUSE_DIR:-$ROOT_DIR/.wheelhouse-app}"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.conda/bin/python}"
SOURCE_DIR=""
INDEX_URL=""
EXTRA_INDEX_URL=""

usage() {
  cat <<'EOF'
Usage:
  scripts/seed_wheelhouse.sh --from-dir /path/to/wheels
  scripts/seed_wheelhouse.sh --index-url https://your.trusted.index/simple

Optional:
  --extra-index-url URL
  WHEELHOUSE_DIR=/path/to/output-dir
  PYTHON_BIN=/path/to/python

The index mode is explicit on purpose: do not point it at an index you have not vetted.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-dir)
      SOURCE_DIR="${2:-}"
      shift 2
      ;;
    --index-url)
      INDEX_URL="${2:-}"
      shift 2
      ;;
    --extra-index-url)
      EXTRA_INDEX_URL="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ ! -f "$MANIFEST" ]]; then
  echo "Error: missing manifest at $MANIFEST." >&2
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi

if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "Error: python runtime not found." >&2
  exit 1
fi

mkdir -p "$WHEELHOUSE"

if [[ -n "$SOURCE_DIR" && -n "$INDEX_URL" ]]; then
  echo "Error: choose either --from-dir or --index-url, not both." >&2
  exit 1
fi

if [[ -n "$SOURCE_DIR" ]]; then
  if [[ ! -d "$SOURCE_DIR" ]]; then
    echo "Error: source directory not found: $SOURCE_DIR" >&2
    exit 1
  fi
  find "$SOURCE_DIR" -maxdepth 1 -type f -name '*.whl' -exec cp -f '{}' "$WHEELHOUSE/" \;
  if ! find "$WHEELHOUSE" -maxdepth 1 -name '*.whl' -print -quit >/dev/null 2>&1; then
    echo "Error: no wheel files were copied into .wheelhouse." >&2
    exit 1
  fi
  echo "Seeded $WHEELHOUSE from $SOURCE_DIR"
  exit 0
fi

if [[ -n "$INDEX_URL" ]]; then
  cmd=(
    "$PYTHON_BIN" -m pip download
    --only-binary=:all:
    --dest "$WHEELHOUSE"
    -r "$MANIFEST"
    --index-url "$INDEX_URL"
  )
  if [[ -n "$EXTRA_INDEX_URL" ]]; then
    cmd+=(--extra-index-url "$EXTRA_INDEX_URL")
  fi
  "${cmd[@]}"
  echo "Seeded $WHEELHOUSE from the explicit index URL."
  exit 0
fi

echo "Error: no source selected." >&2
usage >&2
exit 1
