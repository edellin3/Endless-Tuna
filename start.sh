#!/bin/sh
# Run from any directory, without activating a virtual environment.
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
task_python="$task_root/endless-tuna/.venv/bin/python"
if [ ! -x "$task_python" ]; then
  echo 'Install first: see README.md (endless-tuna/.venv is missing).' >&2
  exit 1
fi
exec "$task_python" "$task_root/endless-tuna/scripts/start.py" "$@"
