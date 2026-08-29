#!/usr/bin/env sh
set -eu

BASE_URL="${VOLT_BASE_URL:-http://127.0.0.1:8000}"

printf 'Checking VOLT health...\n'
curl --fail --silent --show-error "$BASE_URL/health"
printf '\nStaging health check passed.\n'
