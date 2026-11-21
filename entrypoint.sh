#!/bin/sh
set -e

# Apply a staged database restore (Settings -> Backup & restore) BEFORE the migrations, so an
# older snapshot is migrated forward like any start. Stdlib-only and exits 0 even on failure
# (the `|| echo` is a second guard): a restore problem must never stop STD from starting.
echo "♻️  Checking for a staged database restore..."
python restore_swap.py || echo "[restore] restore step failed; continuing with the current database"

echo "📦 Running DB migrations..."
alembic upgrade head

echo "🚀 Starting Service Tracker Dashboard..."
if [ "${FLASK_DEBUG}" = "1" ]; then
    # Dev mode: Werkzeug server with reloader/debugger.
    exec python app.py
fi
# Production: gunicorn, exactly one worker (see gunicorn.conf.py).
exec gunicorn -c gunicorn.conf.py app:app
