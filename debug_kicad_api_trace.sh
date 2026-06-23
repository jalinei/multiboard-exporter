#!/usr/bin/env sh
set -eu

LOG_FILE="${1:-/tmp/kicad_api_trace.log}"

KICAD_ENABLE_WXTRACE=1 \
WXTRACE=KICAD_API \
kicad 2>&1 | tee "$LOG_FILE"
