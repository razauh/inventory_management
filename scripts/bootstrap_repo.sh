#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONDA_ENV_DIR="$ROOT_DIR/.conda"
CONDA_BIN="${CONDA_BIN:-$(command -v conda || true)}"
PYTHON_BIN="$CONDA_ENV_DIR/bin/python"
SEED_SCRIPT="$ROOT_DIR/scripts/seed_wheelhouse.sh"
INSTALL_SCRIPT="$ROOT_DIR/scripts/install_requirements_secure.sh"
VERIFY_ENV_SCRIPT="$ROOT_DIR/scripts/verify_env.py"
SEED_ARGS=()

usage() {
  cat <<'EOF'
Usage:
  scripts/bootstrap_repo.sh --from-dir /path/to/trusted/wheels
  scripts/bootstrap_repo.sh --index-url https://your.trusted.index/simple

Optional:
  --extra-index-url URL
  CONDA_BIN=/path/to/conda
  WHEELHOUSE_DIR=/path/to/output-dir

This script creates or reuses ./.conda, seeds the app wheelhouse, runs the secure install, and verifies the env.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-dir|--index-url|--extra-index-url)
      SEED_ARGS+=("$1" "${2:-}")
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

if [[ ! -x "$PYTHON_BIN" ]]; then
  if [[ -z "$CONDA_BIN" || ! -x "$CONDA_BIN" ]]; then
    echo "Error: conda not found. Set CONDA_BIN or ensure conda is on PATH." >&2
    exit 1
  fi
  "$CONDA_BIN" create -y --prefix "$CONDA_ENV_DIR" python=3.12 --no-default-packages
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Error: expected conda env python at $PYTHON_BIN." >&2
  exit 1
fi

if [[ "${#SEED_ARGS[@]}" -gt 0 ]]; then
  "$SEED_SCRIPT" "${SEED_ARGS[@]}"
elif [[ ! -d "${WHEELHOUSE_DIR:-$ROOT_DIR/.wheelhouse-app}" ]] || ! find "${WHEELHOUSE_DIR:-$ROOT_DIR/.wheelhouse-app}" -maxdepth 1 -name '*.whl' -print -quit >/dev/null 2>&1; then
  echo "Error: app wheelhouse is missing or empty." >&2
  echo "Seed it first with --from-dir or --index-url." >&2
  exit 1
fi

"$INSTALL_SCRIPT"
"$PYTHON_BIN" "$VERIFY_ENV_SCRIPT" --requirements "$ROOT_DIR/requirements.in"
