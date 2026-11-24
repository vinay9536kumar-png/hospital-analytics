"""Natural-language questions -> safe, read-only SQL -> results.

Privacy design:
- Only the database SCHEMA and the user's question are sent to Gemini.
- Patient records and query results are never sent to Gemini.
- The generated SQL is validated and executed on a read-only connection.
- Queries that touch patient names or phone numbers are rejected.
"""
import os
import re
import sqlite3
import time
from datetime import date

import pandas as pd
from dotenv import load_dotenv

import db

load_dotenv()

MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
MAX_ROWS = 200

SCHEMA = """
Table patients(patient_id INTEGER, name TEXT, age INTEGER, gender TEXT,
               city TEXT, phone TEXT, blood_group TEXT)
Table visits(visit_id INTEGER, patient_id INTEGER, visit_type TEXT,
             disease TEXT, department TEXT, admit_date TEXT, discharge_date TEXT,
             status TEXT, doctor TEXT, notes TEXT)

Notes:
- Dates are stored as text in YYYY-MM-DD format.
- visit_type is one of: OPD, IPD, Emergency.
- status is one of: Admitted, Discharged, Referred.
- gender is one of: Male, Female, Other.
- One row in visits = one patient visit. "Patients per day" means visits grouped by admit_date.
- "Currently admitted" means visits.status = 'Admitted'.
- "Discharged on a day" means visits.discharge_date = that day and status IN ('Discharged', 'Referred').
"""

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|replace|"
    r"vacuum|reindex|trigger|truncate)\b",
    re.IGNORECASE,
)
PRIVATE_COLUMNS = re.compile(r"\b(name|phone|notes)\b", re.IGNORECASE)


class UnsafeQuery(Exception):
    pass


def clean_sql(text):
    text = text.strip()
    text = re.sub(r"^```(?:sql)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()
    return text.rstrip(";").strip()


def validate_sql(sql):
    if not sql:
        raise UnsafeQuery("Empty query.")
    if ";" in sql:
        raise UnsafeQuery("Only one statement is allowed.")
    if not re.match(r"^(select|with)\b", sql, re.IGNORECASE):
        raise UnsafeQuery("Only SELECT queries are allowed.")
    if FORBIDDEN.search(sql):
        raise UnsafeQuery("This query tries to change data, which is not allowed.")
    if PRIVATE_COLUMNS.search(sql):
        raise UnsafeQuery(
            "Patient names, phone numbers and notes are not available in chat. "
            "Use the Search tab for individual patients."
        )
    return sql


def call_gemini(prompt, retries=3):
    from google import genai
    from google.genai import errors

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    for attempt in range(retries):
        for model in MODELS:
            try:
                return client.models.generate_content(model=model, contents=prompt).text
            except errors.ServerError:
                continue
        time.sleep(2 ** attempt)
    raise RuntimeError("Gemini is busy right now, please try again in a minute.")


def generate_sql(question):
    prompt = f"""You are a SQLite expert for a hospital analytics tool.
Convert the question (it may be in Hindi, Hinglish or English) into ONE SQLite SELECT query.

Rules:
- Return ONLY the SQL, no explanation, no markdown.
- Use only the tables and columns in the schema below.
- Never select patient names, phone numbers or notes.
- Use readable column aliases in English.
- Today's date is {date.today().isoformat()}. Use date('now') or this date for "today",
  "yesterday", "this week", "this month", "last 7 days" and so on.
- For rankings add ORDER BY and LIMIT 10 unless the question asks otherwise.

SCHEMA:
{SCHEMA}

QUESTION: {question}
"""
    return clean_sql(call_gemini(prompt))


def run_readonly(sql):
    conn = sqlite3.connect(f"file:{db.DB_PATH}?mode=ro", uri=True)
    try:
        cur = conn.execute(sql)
        columns = [c[0] for c in cur.description]
        rows = cur.fetchmany(MAX_ROWS)
        return pd.DataFrame(rows, columns=columns)
    finally:
        conn.close()


def ask(question, sql_generator=generate_sql):
    """Returns (sql, dataframe). Raises UnsafeQuery or sqlite3.Error on problems."""
    sql = validate_sql(sql_generator(question))
    return sql, run_readonly(sql)