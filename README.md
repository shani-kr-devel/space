# Firm Data Assistant (Ollama + Any Database + Tkinter GUI)

Connect to **any database** — SQLite, PostgreSQL, MySQL, and more — and the
app automatically scans its schema (tables, columns, sample data), then
lets you ask plain-English questions about your firm's data and set
threshold alerts on any table/column it finds. No hardcoded schema, no
manual setup of "what a stock table looks like" — it adapts to whatever
you connect it to.

## How it works

- **`db_connection.py`**: owns two connections — the business database you
  connect to (via a connection string), and a small local `app_data.db`
  that stores the app's own settings (your alert rules). The app never
  writes into your business data, only reads from it.
- **`schema_scanner.py`**: the "auto scan" step. Uses SQLAlchemy to inspect
  whatever database you connected — every table, its columns/types, and a
  few sample rows — and builds a compact description for the LLM.
- **`rag_engine.py`**: text-to-SQL RAG. Gives Ollama the scanned schema,
  asks it to write a single read-only SQL query that answers your
  question, checks the query is safe (SELECT-only, no multiple
  statements, no data-modifying keywords), runs it, then asks Ollama to
  explain the results in plain language.
- **`alerts.py`**: generic threshold alerts — pick any table + numeric
  column, a condition (below/above/equal), and a value. A background
  thread checks all active alerts every 60 seconds.
- **`gui.py`**: minimal Tkinter GUI — a "Connect to your database" dialog
  first, then a chat window plus buttons to set/view alerts.

## Setup

1. **Install Ollama**: https://ollama.com/download, then pull a model:
   ```bash
   ollama pull llama3.1
   ```
   Make sure it's running: `ollama serve` (often starts automatically).

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
   If you're connecting to PostgreSQL or MySQL, also install the matching
   driver (see `requirements.txt` for which one).

3. **(Optional) Create a sample database to try it out first**:
   ```bash
   python sample_data.py
   ```
   This creates `sample_business.db` with `stock`, `sales`, and
   `customers` tables you can connect to right away.

4. **Run the app**:
   ```bash
   python gui.py      # minimal GUI (recommended)
   # or
   python main.py     # command-line version
   ```

## Connecting to your database

When the app starts, you'll be asked for a **connection string**:

| Database | Connection string example |
|---|---|
| SQLite file | `business.db` or `sqlite:///path/to/file.db` |
| PostgreSQL | `postgresql://user:password@host:5432/dbname` |
| MySQL / MariaDB | `mysql+pymysql://user:password@host/dbname` |
| SQL Server | `mssql+pyodbc://user:password@host/dbname?driver=ODBC+Driver+17+for+SQL+Server` |

The app connects, scans every table it can see, and shows you what it
found ("Connected! Found 3 table(s): stock, sales, customers.") before you
start asking questions.

## Using the GUI

- Type a question and hit Enter, e.g. *"how much stock do we have left of
  each item"* or *"who are our top 3 customers by spend"*. The app writes
  and runs a SQL query behind the scenes and shows you the plain-language
  answer (plus the SQL it used, so you can verify it).
- **Set Alert**: pick a table and numeric column from dropdowns (populated
  from your actual schema), a condition, and a threshold — e.g. "Laptop
  stock below 10."
- **View Alerts**: lists everything you've set.
- **Change Database**: switch to a different database at any time; the
  app rescans automatically.

## A note on safety and privacy

- The app only ever runs a single read-only `SELECT`/`WITH` query — it
  refuses anything containing `INSERT`, `UPDATE`, `DELETE`, `DROP`, etc.,
  or multiple statements chained together.
- Because Ollama runs entirely on your own machine, your data (including
  the sample rows used for schema scanning) never leaves your computer.
  Still, if your database contains especially sensitive fields, consider
  connecting with a read-only database user as an extra safeguard.

## Files

| File | Purpose |
|---|---|
| `db_connection.py` | Connects to your business database + a local settings DB |
| `schema_scanner.py` | Auto-scans the connected database's schema |
| `rag_engine.py` | Text-to-SQL RAG: generates, validates, runs, and explains queries |
| `alerts.py` | Stores and checks threshold alerts on any table/column |
| `gui.py` | Minimal Tkinter GUI entry point |
| `main.py` | Command-line entry point |
| `sample_data.py` | Optional: creates a sample database to try the app on |
