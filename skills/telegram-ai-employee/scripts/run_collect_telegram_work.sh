#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SKILL_ROOT=$(dirname "$SCRIPT_DIR")
ENV_FILE=${TG_ENV_FILE:-"$SKILL_ROOT/secrets/telegram.env"}

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing env file: $ENV_FILE" >&2
  exit 1
fi

set -a
. "$ENV_FILE"
set +a

exec python3 "$SCRIPT_DIR/collect_telegram_work.py" "$@"
