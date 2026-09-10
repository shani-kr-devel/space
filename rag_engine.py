"""
rag_engine.py
Text-to-SQL RAG: uses the auto-scanned schema of whatever database you've
connected as context, asks Ollama to write a read-only SQL query that
answers the question, runs it safely, then asks Ollama to explain the
results in plain language for a business owner.
"""
import re
import ollama
from sqlalchemy import text as sql_text

from db_connection import get_engine
import schema_scanner

# Change this to whatever model you've pulled locally, e.g. "llama3.1",
# "mistral", "qwen2.5" -- run `ollama list` to see what you have.
MODEL = "llama3.1"

# Set to True if you want every answer to also show the SQL query that was
# generated and run -- useful for double-checking the model's work, or if
# an answer looks off and you want to see why. Off by default so normal
# chatting stays clean.
SHOW_SQL = False

FORBIDDEN_KEYWORDS = [
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "attach", "detach", "pragma", "exec", "grant", "revoke", "vacuum",
    "replace into",
]


def _clean_sql(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"^```(sql)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()
    return text.rstrip(";").strip()


def _is_safe_select(sql: str) -> bool:
    """Only allows a single, read-only SELECT/WITH query -- never anything
    that could modify data or run multiple statements."""
    lowered = sql.lower().strip()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        return False
    if ";" in sql:
        return False
    return not any(kw in lowered for kw in FORBIDDEN_KEYWORDS)


def _generate_sql(question: str, schema_text: str, model=MODEL) -> str:
    prompt = f"""Database schema (auto-detected):
{schema_text}

Question: {question}

Write ONE read-only SQL SELECT query to answer this question, using only
the tables/columns listed above. Return ONLY the raw SQL query -- no
explanation, no markdown formatting, no semicolons, no multiple statements.
"""
    response = ollama.chat(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You are a precise SQL analyst. You only ever "
                            "write a single read-only SELECT query.",
            },
            {"role": "user", "content": prompt},
        ],
    )
    return _clean_sql(response["message"]["content"])


def _run_sql(sql: str, row_limit: int = 100):
    engine = get_engine()
    query = sql if "limit" in sql.lower() else f"{sql} LIMIT {row_limit}"
    with engine.connect() as conn:
        result = conn.execute(sql_text(query))
        columns = list(result.keys())
        rows = result.fetchmany(row_limit)
    return columns, rows


def _explain_results(question: str, sql: str, columns, rows, model=MODEL) -> str:
    if rows:
        preview = "\n".join(
            ", ".join(f"{c}={v}" for c, v in zip(columns, r)) for r in rows[:50]
        )
    else:
        preview = "(no rows returned)"

    prompt = f"""Question: {question}

SQL query used: {sql}

Results ({len(rows)} row(s), showing up to 50):
{preview}

Using ONLY these results, give a clear, natural-language answer for a
business owner about their firm's data. Include concrete numbers. Do NOT
add a currency symbol (like $) or any currency name to numbers unless one
is explicitly present in the data itself -- just state the plain number.
If the results are empty, say so plainly instead of guessing.
"""
    response = ollama.chat(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You are a helpful business assistant that "
                            "explains query results in plain language.",
            },
            {"role": "user", "content": prompt},
        ],
    )
    return response["message"]["content"]


def answer_question(question: str, model=MODEL) -> str:
    schema_text, _ = schema_scanner.get_cached_schema()
    if not schema_text:
        return ("I haven't scanned a database yet -- connect to one first "
                 "(it needs at least one table).")

    sql = _generate_sql(question, schema_text, model)

    if not _is_safe_select(sql):
        return (f"I generated a query I'm not comfortable running for "
                 f"safety reasons:\n{sql}\n"
                 f"Try rephrasing your question more specifically.")

    try:
        columns, rows = _run_sql(sql)
    except Exception as e:
        return (f"I tried this query but it failed against your database:\n"
                 f"{sql}\n\nError: {e}\n"
                 f"Try rephrasing, or double-check the table/column names.")

    explanation = _explain_results(question, sql, columns, rows, model)
    if SHOW_SQL:
        return f"{explanation}\n\n(query used: {sql})"
    return explanation