#!/usr/bin/env bash

set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/.logs"
PYTHONPATH_VALUE="/media/pc/64B0D1DBB0D1B3B0"

TEST_FILES=(
  "tests/inventory/test_add_adjustment_transaction_scope.py"
  "tests/repositories/test_basic_repo_transaction_scope.py"
  "tests/product/test_product_transaction_scope.py"
  "tests/login/test_login_transaction_scope.py"
)

mkdir -p "$LOG_DIR"

overall_status=0

for test_file in "${TEST_FILES[@]}"; do
  log_name="$(basename "${test_file%.py}").log"
  log_path="$LOG_DIR/$log_name"

  echo "Running $test_file"
  echo "Log: $log_path"

  if PYTHONPATH="$PYTHONPATH_VALUE" pytest "$ROOT_DIR/$test_file" >"$log_path" 2>&1; then
    echo "PASS $test_file"
  else
    echo "FAIL $test_file"
    overall_status=1
  fi
done

exit "$overall_status"
