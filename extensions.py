# extensions.py
import sqlite3

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()


@event.listens_for(Engine, "connect")
def _sqlite_set_wal(dbapi_connection, connection_record):
    # WAL is database-level and sticky, but PRAGMA-on-connect is the canonical
    # pattern — guarantees mode is set even on a fresh DB file created by alembic.
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()
