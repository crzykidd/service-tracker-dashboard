#!/bin/sh
set -e

echo "📦 Running DB migrations..."
alembic upgrade head

echo "🚀 Starting Service Tracker Dashboard..."
if [ "${FLASK_DEBUG}" = "1" ]; then
    # Dev mode: Werkzeug server with reloader/debugger.
    exec python app.py
fi
# Production: gunicorn, exactly one worker (see gunicorn.conf.py).
exec gunicorn -c gunicorn.conf.py app:app
