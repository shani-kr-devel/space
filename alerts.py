"""
alerts.py
Alert rules are generic now: you pick ANY table + numeric column found by
the schema scan, a condition, and a threshold. Rules are stored in the
app's own local app_data.db (never in your business database) and checked
against whatever database is currently connected.
"""
from datetime import datetime
from sqlalchemy import text as sql_text

from db_connection import get_app_connection, get_engine

_OPS = {"below": "<", "above": ">", "equal": "="}


def init_app_db():
    conn = get_app_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        description TEXT NOT NULL,
        table_name TEXT NOT NULL,
        column_name TEXT NOT NULL,
        identifier_column TEXT,
        identifier_value TEXT,
        condition TEXT NOT NULL,
        threshold REAL NOT NULL,
        active INTEGER DEFAULT 1,
        last_triggered TEXT
    )
    """)
    # Migration: older app_data.db files may not have identifier_value yet.
    existing_cols = [row[1] for row in conn.execute("PRAGMA table_info(alerts)")]
    if "identifier_value" not in existing_cols:
        conn.execute("ALTER TABLE alerts ADD COLUMN identifier_value TEXT")
    conn.commit()
    conn.close()


def add_alert(description, table_name, column_name, condition, threshold,
              identifier_column=None, identifier_value=None):
    conn = get_app_connection()
    conn.execute(
        "INSERT INTO alerts (description, table_name, column_name, identifier_column, "
        "identifier_value, condition, threshold, active) VALUES (?,?,?,?,?,?,?,1)",
        (description, table_name, column_name, identifier_column, identifier_value,
         condition, threshold),
    )
    conn.commit()
    conn.close()


def list_alerts():
    conn = get_app_connection()
    cur = conn.execute(
        "SELECT id, description, table_name, column_name, identifier_column, "
        "identifier_value, condition, threshold, active FROM alerts"
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def remove_alert(alert_id) -> bool:
    """Deletes an alert by id. Returns True if a row was actually deleted."""
    conn = get_app_connection()
    cur = conn.execute("DELETE FROM alerts WHERE id=?", (alert_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def check_alerts():
    """Runs each active alert as a SQL query against the connected business
    database. Returns a list of triggered alert message strings."""
    app_conn = get_app_connection()
    cur = app_conn.execute(
        "SELECT id, description, table_name, column_name, identifier_column, "
        "identifier_value, condition, threshold FROM alerts WHERE active=1"
    )
    rules = cur.fetchall()

    triggered = []
    try:
        engine = get_engine()
    except RuntimeError:
        app_conn.close()
        return triggered  # not connected to a database yet

    for alert_id, desc, table, column, id_col, id_value, condition, threshold in rules:
        op = _OPS.get(condition)
        if not op:
            continue
        select_cols = f"{id_col}, {column}" if id_col else column
        where_clause = f"{column} {op} :threshold"
        params = {"threshold": threshold}
        if id_col and id_value:
            where_clause += f" AND {id_col} = :id_value"
            params["id_value"] = id_value
        query = f"SELECT {select_cols} FROM {table} WHERE {where_clause}"
        try:
            with engine.connect() as conn:
                result = conn.execute(sql_text(query), params)
                rows = result.fetchall()
        except Exception as e:
            triggered.append(f"[ALERT ERROR] '{desc}' could not be checked: {e}")
            continue

        for row in rows:
            if id_col:
                triggered.append(
                    f"[ALERT] {desc} -> {table}.{id_col}={row[0]} has {column}={row[1]} "
                    f"({condition} {threshold})"
                )
            else:
                triggered.append(
                    f"[ALERT] {desc} -> a row in {table} has {column}={row[0]} "
                    f"({condition} {threshold})"
                )
        if rows:
            app_conn.execute(
                "UPDATE alerts SET last_triggered=? WHERE id=?",
                (datetime.now().isoformat(), alert_id),
            )

    app_conn.commit()
    app_conn.close()
    return triggered