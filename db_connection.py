"""
db_connection.py
Handles TWO separate connections:

1. Your business database -- whatever you connect to via connect().
   Uses SQLAlchemy, so it works with SQLite, PostgreSQL, MySQL, SQL Server,
   and more (as long as the right driver is installed).

2. app_data.db -- a small local SQLite file that stores the app's OWN
   settings (currently: your alert rules). This is kept separate from your
   business database on purpose -- the app never writes into your data,
   it only reads from it.
"""
import sqlite3
from sqlalchemy import create_engine

APP_DB_PATH = "app_data.db"

_engine = None
_connection_string = None


def connect(connection_string: str):
    """Connects to the user's database. Accepts either:
    - a plain file path for SQLite, e.g. 'business.db'
    - a full SQLAlchemy URL, e.g.:
        'sqlite:///path/to/file.db'
        'postgresql://user:password@host:5432/dbname'
        'mysql+pymysql://user:password@host/dbname'
    Raises an exception if the connection can't be established.
    """
    global _engine, _connection_string
    url = connection_string.strip()
    if "://" not in url:
        # Treat bare strings like "business.db" as a SQLite file path.
        url = f"sqlite:///{url}"

    engine = create_engine(url)
    with engine.connect():  # fail fast if the connection is bad
        pass

    _engine = engine
    _connection_string = url
    return engine


def get_engine():
    if _engine is None:
        raise RuntimeError("Not connected to a database yet. Call connect() first.")
    return _engine


def is_connected() -> bool:
    return _engine is not None


def get_app_connection() -> sqlite3.Connection:
    """Local, app-only SQLite connection (alert rules, settings)."""
    return sqlite3.connect(APP_DB_PATH, check_same_thread=False)
