#!/usr/bin/env bash
# Shared Python command selection for repo scripts.
# Allows python3, python, or Windows py launcher (py -3).

PYTHON_CMD=()

if [[ -n "${PYTHON:-}" ]]; then
  # Allow overrides like: PYTHON="python" or PYTHON="py -3"
  read -r -a PYTHON_CMD <<<"${PYTHON}"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_CMD=(python3)
elif command -v python >/dev/null 2>&1; then
  PYTHON_CMD=(python)
elif command -v py >/dev/null 2>&1; then
  PYTHON_CMD=(py -3)
fi

# Verify that interpreter discovery selected a usable Python command.
python_check() {
  if [[ "${#PYTHON_CMD[@]}" -eq 0 ]]; then
    echo "❌ Missing Python interpreter (python3, python, or py -3)" >&2
    return 1
  fi
  return 0
}

# Execute the selected interpreter with the caller's arguments.
python_cmd() {
  python_check
  "${PYTHON_CMD[@]}" "$@"
}
