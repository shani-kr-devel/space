"""
main.py
Command-line version (use gui.py instead for the GUI).
Run: python main.py
"""
import threading
import time
import sys

import db_connection
import schema_scanner
from rag_engine import answer_question
from alerts import init_app_db, add_alert, list_alerts, remove_alert, check_alerts

ALERT_CHECK_INTERVAL_SECONDS = 60


def alert_watcher():
    while True:
        if db_connection.is_connected():
            try:
                triggered = check_alerts()
                for msg in triggered:
                    print("\n" + msg + "\n> ", end="", flush=True)
            except Exception as e:
                print(f"\n[alert watcher error] {e}\n> ", end="", flush=True)
        time.sleep(ALERT_CHECK_INTERVAL_SECONDS)


def connect_flow():
    print("Connect to your database.")
    print("Examples: business.db | sqlite:///path/to/file.db | "
          "postgresql://user:pass@host:5432/dbname\n")
    while True:
        conn_str = input("Connection string: ").strip()
        if not conn_str:
            continue
        try:
            engine = db_connection.connect(conn_str)
            schema_text, tables = schema_scanner.scan_schema(engine)
            if not tables:
                print("Connected, but no tables were found. Try a different database.\n")
                continue
            print(f"Connected! Found {len(tables)} table(s): {', '.join(tables.keys())}\n")
            return
        except Exception as e:
            print(f"Failed to connect: {e}\n")


def handle_set_alert():
    schema_text, tables = schema_scanner.get_cached_schema()
    if not tables:
        print("Connect to a database first.\n")
        return
    print(f"Available tables: {', '.join(tables.keys())}")
    table = input("Table: ").strip()
    if table not in tables:
        print("Unknown table. Alert not saved.\n")
        return
    print(f"Columns in {table}: {', '.join(tables[table]['columns'])}")
    column = input("Numeric column to watch: ").strip()
    id_col = input("Identifier column (optional, blank for none): ").strip() or None
    id_value = None
    if id_col:
        specific = input(
            f"Apply only to a specific {id_col} value? (leave blank to apply to ALL rows): "
        ).strip()
        id_value = specific or None
    desc = input("Short description: ").strip()
    condition = input("Condition - 'below', 'above', or 'equal': ").strip().lower()
    try:
        threshold = float(input("Threshold number: ").strip())
    except ValueError:
        print("Threshold must be a number. Alert not saved.\n")
        return
    add_alert(desc, table, column, condition, threshold, id_col, id_value)
    print("Alert saved. It will be checked automatically in the background.\n")


def handle_remove_alert():
    rows = list_alerts()
    if not rows:
        print("No alerts set yet.\n")
        return
    for r in rows:
        print(
            f"#{r[0]} | {r[1]} | {r[2]}.{r[3]} (id_col={r[4]}, value={r[5]}) "
            f"{r[6]} {r[7]} | active={bool(r[8])}"
        )
    raw_id = input("Enter the # of the alert to remove (blank to cancel): ").strip()
    if not raw_id:
        return
    try:
        alert_id = int(raw_id)
    except ValueError:
        print("That's not a valid alert number.\n")
        return
    if remove_alert(alert_id):
        print("Alert removed.\n")
    else:
        print("No alert found with that number.\n")


def main():
    init_app_db()
    connect_flow()

    watcher = threading.Thread(target=alert_watcher, daemon=True)
    watcher.start()

    print("=== Firm Data Assistant (Ollama) ===")
    print("Ask a question, or type 'setalert', 'removealert', 'alerts', 'reconnect', or 'quit'.\n")

    while True:
        try:
            q = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            sys.exit(0)

        if not q:
            continue
        if q.lower() in ("quit", "exit"):
            print("Goodbye.")
            break
        elif q.lower() == "reconnect":
            connect_flow()
        elif q.lower() == "setalert":
            handle_set_alert()
        elif q.lower() == "removealert":
            handle_remove_alert()
        elif q.lower() == "alerts":
            rows = list_alerts()
            if not rows:
                print("No alerts set yet.")
            for r in rows:
                print(
                    f"#{r[0]} | {r[1]} | {r[2]}.{r[3]} (id_col={r[4]}, value={r[5]}) "
                    f"{r[6]} {r[7]} | active={bool(r[8])}"
                )
        else:
            try:
                print(answer_question(q))
            except Exception as e:
                print(
                    f"Error talking to Ollama: {e}\n"
                    "Make sure Ollama is running (`ollama serve`) and the "
                    "model in rag_engine.py has been pulled (`ollama pull llama3.1`)."
                )


if __name__ == "__main__":
    main()