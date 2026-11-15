# extensions.py
import sqlite3

from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
csrf = CSRFProtect()

login_manager = LoginManager()
login_manager.login_view = "auth.login"


@event.listens_for(Engine, "connect")
def _sqlite_set_wal(dbapi_connection, connection_record):
    # WAL is database-level and sticky, but PRAGMA-on-connect is the canonical
    # pattern — guarantees mode is set even on a fresh DB file created by alembic.
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()
