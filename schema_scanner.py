"""
schema_scanner.py
Automatically inspects whatever database is currently connected: what
tables exist, their columns/types, and a few sample rows -- and builds a
compact text description the LLM can use as context. This is what lets the
app work on ANY database without you telling it the schema up front.
"""
from sqlalchemy import inspect, text as sql_text

_cache = {"schema_text": "", "tables": {}}


def scan_schema(engine, sample_rows: int = 3):
    """Scans the connected database and caches the result.
    Returns (schema_text, tables_dict).
    tables_dict looks like: {"stock": {"columns": [...], "column_types": {...}}, ...}
    """
    inspector = inspect(engine)
    tables = {}
    lines = []

    for table_name in inspector.get_table_names():
        columns = inspector.get_columns(table_name)
        col_names = [c["name"] for c in columns]
        col_types = {c["name"]: str(c["type"]) for c in columns}
        tables[table_name] = {"columns": col_names, "column_types": col_types}

        col_desc = ", ".join(f"{c['name']} ({c['type']})" for c in columns)
        lines.append(f"TABLE {table_name}({col_desc})")

        try:
            with engine.connect() as conn:
                result = conn.execute(sql_text(f"SELECT * FROM {table_name} LIMIT {sample_rows}"))
                cols = list(result.keys())
                rows = result.fetchall()
            if rows:
                sample = "; ".join(
                    ", ".join(f"{c}={v}" for c, v in zip(cols, r)) for r in rows
                )
                lines.append(f"  sample rows: {sample}")
        except Exception:
            pass  # sampling is a nice-to-have, never block the scan on it

    schema_text = "\n".join(lines)
    _cache["schema_text"] = schema_text
    _cache["tables"] = tables
    return schema_text, tables


def get_cached_schema():
    """Returns the last scan's (schema_text, tables_dict) without re-scanning."""
    return _cache["schema_text"], _cache["tables"]
