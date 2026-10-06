#!/usr/bin/env bash
# Wait for a running E4 process to end; if it did not finish, resume it from the cache.
# usage: experiments/watch_e4.sh <log> <model-pattern> <python args...>
log="$1"; pattern="$2"; shift 2
alive() {
  powershell -NoProfile -Command "if (Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -match 'e4_spec_extraction' -and \$_.CommandLine -match '$pattern' }) { exit 0 } else { exit 1 }"
}
while alive; do sleep 30; done
grep -q "rows written" "$log" || experiments/run_e4_resilient.sh "$log" "$@"
