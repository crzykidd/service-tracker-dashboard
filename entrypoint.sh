#!/bin/sh
set -e

echo "📦 Running DB migrations..."
alembic upgrade head

echo "🚀 Starting Service Tracker Dashboard..."
exec python app.py
