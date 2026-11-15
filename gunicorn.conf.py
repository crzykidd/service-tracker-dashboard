"""gunicorn configuration for Service Tracker Dashboard.

Run with: gunicorn -c gunicorn.conf.py app:app
"""

bind = "0.0.0.0:8815"

# MUST stay 1. The register mutex, the APScheduler jobs and the health-check
# thread all live in-process; more than one worker would run every job N times
# and break the register upsert lock. Scale with threads, not workers.
workers = 1
threads = 4

# Long enough for slow register/icon fetches; the health loop is a thread.
timeout = 60

accesslog = "-"
errorlog = "-"

# Do NOT set preload_app: threads started in the master do not survive the
# fork, so startup work must run inside the worker (post_worker_init).


def post_worker_init(worker):
    from app import app, run_startup_tasks

    run_startup_tasks(app)
