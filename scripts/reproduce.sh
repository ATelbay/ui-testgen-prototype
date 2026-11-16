#!/usr/bin/env bash
# Re-run the checks and the practice 8 microbenchmark from a clean checkout.
# Usage:
#   scripts/reproduce.sh            tests, microbenchmark and profiling
#   scripts/reproduce.sh --capture  only re-capture UI dumps and dump latency
#                                   from a booted emulator (needs adb); this
#                                   overwrites data/snapshots and results/macro.
# In practice 8 the emulator was stopped before the microbenchmark, so run
# --capture first, stop the emulator (adb emu kill), then run without flags.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"
"$PYTHON" --version

if [[ "${1:-}" == "--capture" ]]; then
  "$PYTHON" benchmarks/capture_snapshots.py --repeats 10 --settle-seconds 5
  echo "Captured. Stop the emulator (adb emu kill), then run scripts/reproduce.sh."
  exit 0
fi

"$PYTHON" -m unittest discover -s tests -t . -v
"$PYTHON" benchmarks/bench_validator.py --output results/micro
"$PYTHON" benchmarks/profile_validator.py --output results/profile
echo "Done. See results/micro/summary.csv and results/profile/."
