#!/bin/sh
set -e

# Render mounts the persistent disk as root; hand the upload folder to the app user, then run as that user.
mkdir -p "$STW_UPLOAD_DIR"
chown -R 10001 "$STW_UPLOAD_DIR"

# One worker: the in-process scheduler must run once. Duplicate generation is also blocked by database constraints.
exec setpriv --reuid=10001 --regid=10001 --clear-groups sh -c \
  'alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 --proxy-headers'
