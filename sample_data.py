"""
sample_data.py
Optional: creates a sample SQLite database (sample_business.db) with a few
different tables, purely so you can try out the auto-scan + chat features
without connecting your real data first.

Run: python sample_data.py
Then in the app, connect using: sample_business.db
"""
import sqlite3
from datetime import date

DB_PATH = "sample_business.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS stock (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price REAL
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name TEXT NOT NULL,
        quantity_sold INTEGER NOT NULL,
        total_amount REAL NOT NULL,
        sale_date TEXT NOT NULL
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        city TEXT,
        total_spent REAL DEFAULT 0
    )
    """)

    cur.execute("SELECT COUNT(*) FROM stock")
    if cur.fetchone()[0] == 0:
        stock_items = [
            ("Laptop", 25, 55000),
            ("Mouse", 150, 500),
            ("Keyboard", 80, 1200),
            ("Monitor", 40, 9000),
            ("USB Cable", 300, 150),
        ]
        cur.executemany(
            "INSERT INTO stock (item_name, quantity, unit_price) VALUES (?,?,?)",
            stock_items,
        )

        today = date.today().isoformat()
        cur.executemany(
            "INSERT INTO sales (item_name, quantity_sold, total_amount, sale_date) VALUES (?,?,?,?)",
            [
                ("Laptop", 3, 165000, today),
                ("Mouse", 12, 6000, today),
                ("Keyboard", 5, 6000, today),
                ("Monitor", 2, 18000, today),
            ],
        )

        cur.executemany(
            "INSERT INTO customers (name, city, total_spent) VALUES (?,?,?)",
            [
                ("Amit Sharma", "Gurugram", 87000),
                ("Priya Verma", "Delhi", 45000),
                ("Rohan Gupta", "Noida", 12000),
            ],
        )

    conn.commit()
    conn.close()
    print(f"Sample database created at {DB_PATH}")


if __name__ == "__main__":
    main()
