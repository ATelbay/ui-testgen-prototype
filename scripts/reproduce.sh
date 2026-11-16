#!/usr/bin/env bash
# Re-run the checks and the practice 8 microbenchmark from a clean checkout.
# Usage: scripts/reproduce.sh [--capture]
#   --capture  also re-capture UI dumps from a booted emulator (needs adb);
#              this overwrites data/snapshots and results/macro.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"

"$PYTHON" --version
"$PYTHON" -m unittest discover -s tests -t . -v

if [[ "${1:-}" == "--capture" ]]; then
  "$PYTHON" benchmarks/capture_snapshots.py --repeats 10 --settle-seconds 5
fi

"$PYTHON" benchmarks/bench_validator.py --output results/micro
"$PYTHON" benchmarks/profile_validator.py --output results/profile
echo "Done. See results/micro/summary.csv and results/profile/."
