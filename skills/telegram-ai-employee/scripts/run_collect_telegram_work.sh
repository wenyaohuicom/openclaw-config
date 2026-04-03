#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SKILL_ROOT=$(dirname "$SCRIPT_DIR")
SECRETS_DIR="$SKILL_ROOT/secrets"
OUTPUT_DIR="$SKILL_ROOT/output"
PROFILE=${TG_PROFILE:-default}

# Read --profile early so each account can use its own env and session file.
prev=
for arg in "$@"; do
  if [ "$prev" = "--profile" ]; then
    PROFILE=$arg
    prev=
    continue
  fi
  case "$arg" in
    --profile=*) PROFILE=${arg#--profile=} ;;
    --profile) prev=--profile ;;
  esac
done

BASE_ENV="$SECRETS_DIR/telegram.env"
PROFILE_ENV="$SECRETS_DIR/telegram.$PROFILE.env"

if [ -n "${TG_ENV_FILE:-}" ]; then
  if [ ! -f "$TG_ENV_FILE" ]; then
    echo "Missing env file: $TG_ENV_FILE" >&2
    exit 1
  fi
  set -a
  . "$TG_ENV_FILE"
  set +a
else
  loaded_any=0
  if [ -f "$BASE_ENV" ]; then
    set -a
    . "$BASE_ENV"
    set +a
    loaded_any=1
  fi
  if [ "$PROFILE" != "default" ] && [ -f "$PROFILE_ENV" ]; then
    set -a
    . "$PROFILE_ENV"
    set +a
    loaded_any=1
  fi
  if [ "$loaded_any" -eq 0 ]; then
    echo "Missing env file. Expected $BASE_ENV or $PROFILE_ENV" >&2
    exit 1
  fi
fi

export TG_PROFILE="$PROFILE"
: "${TG_SESSION_PATH:=$SECRETS_DIR/telegram-user${PROFILE:+.$PROFILE}.session}"
: "${TG_OUTPUT_DIR:=$OUTPUT_DIR/$PROFILE}"

if [ "$PROFILE" = "default" ]; then
  TG_SESSION_PATH="$SECRETS_DIR/telegram-user.session"
  TG_OUTPUT_DIR="$OUTPUT_DIR"
fi

export TG_SESSION_PATH TG_OUTPUT_DIR
exec python3 "$SCRIPT_DIR/collect_telegram_work.py" "$@"
