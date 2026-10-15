#!/usr/bin/env bash
# Re-run an E4 command until it finishes. Completed LLM calls are cached, so every restart resumes.
# usage: experiments/run_e4_resilient.sh <log> <python args...>
log="$1"; shift
for attempt in $(seq 1 12); do
  .venv/Scripts/python.exe experiments/e4_spec_extraction.py "$@" >> "$log" 2>&1
  grep -q "rows written" "$log" && exit 0
  echo "[restart $attempt] previous run stopped early, resuming from cache" >> "$log"
done
exit 1
