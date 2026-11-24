import sqlite3
from contextlib import contextmanager

import pandas as pd

DB_PATH = "hospital.db"

DISEASES = {
    "Viral Fever": "General Medicine",
    "Diabetes": "General Medicine",
    "Dengue": "General Medicine",
    "Typhoid": "General Medicine",
    "Hypertension": "Cardiology",
    "Heart Disease": "Cardiology",
    "Asthma": "Pulmonology",
    "Pneumonia": "Pulmonology",
    "Fracture": "Orthopedics",
    "Arthritis": "Orthopedics",
    "Kidney Stone": "Urology",
    "Skin Allergy": "Dermatology",
    "Pregnancy Care": "Gynecology",
    "Migraine": "Neurology",
}
DEPARTMENTS = [
    "Auto",
    "General Medicine",
    "Cardiology",
    "Pulmonology",
    "Orthopedics",
    "Urology",
    "Dermatology",
    "Gynecology",
    "Neurology",
    "Pediatrics",
    "ENT",
    "Other",
]
BLOOD_GROUPS = ["Unknown", "A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]


@contextmanager
def get_conn():
    """Open the database for one operation (safe for many users at once).

    WAL mode lets staff on different computers read while someone writes, and the
    busy timeout makes a writer wait briefly instead of failing with "database is locked".
    """
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_columns():
    """Add the extra columns used by the data entry form (safe to run many times)."""
    extra = {
        "patients": ["phone", "blood_group"],
        "visits": ["doctor", "notes"],
    }
    with get_conn() as conn:
        for table, columns in extra.items():
            existing = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            for column in columns:
                if column not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS bill_items (
                item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                visit_id INTEGER NOT NULL,
                category TEXT,
                description TEXT,
                quantity REAL,
                unit_price REAL
            );
            CREATE TABLE IF NOT EXISTS bills (
                visit_id INTEGER PRIMARY KEY,
                discount REAL DEFAULT 0,
                paid_amount REAL DEFAULT 0,
                payment_mode TEXT
            );
            """
        )


def query_df(sql, params=()):
    with get_conn() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def scalar(sql, params=()):
    with get_conn() as conn:
        return conn.execute(sql, params).fetchone()[0]


def add_patient(name, age, gender, city, phone="", blood_group="Unknown"):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO patients (name, age, gender, city, phone, blood_group) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, age, gender, city, phone, blood_group),
        )
        return cur.lastrowid


def add_visit(patient_id, visit_type, disease, department, admit_date, doctor="", notes=""):
    if visit_type == "OPD":
        status, discharge_date = "Discharged", admit_date
    else:
        status, discharge_date = "Admitted", None
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO visits (patient_id, visit_type, disease, department, "
            "admit_date, discharge_date, status, doctor, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (patient_id, visit_type, disease, department, admit_date,
             discharge_date, status, doctor, notes),
        )
        return cur.lastrowid


def search_patients(term):
    like = f"%{term}%"
    return query_df(
        "SELECT patient_id, name, age, gender, phone, city FROM patients "
        "WHERE name LIKE ? OR phone LIKE ? ORDER BY patient_id DESC LIMIT 20",
        (like, like),
    )


def get_admitted():
    return query_df(
        "SELECT v.visit_id, p.name, v.disease, v.department, v.visit_type, v.admit_date "
        "FROM visits v JOIN patients p ON p.patient_id = v.patient_id "
        "WHERE v.status = 'Admitted' ORDER BY v.admit_date"
    )


def discharge_visit(visit_id, outcome, discharge_date):
    with get_conn() as conn:
        conn.execute(
            "UPDATE visits SET status = ?, discharge_date = ? WHERE visit_id = ?",
            (outcome, discharge_date, visit_id),
        )


def distinct_values(column):
    allowed = {"disease", "department", "status", "visit_type"}
    if column not in allowed:
        raise ValueError("Invalid column")
    df = query_df(f"SELECT DISTINCT {column} AS value FROM visits ORDER BY {column}")
    return df["value"].dropna().tolist()


def search_visits(term="", disease="All", department="All", status="All",
                  visit_type="All", start=None, end=None, limit=500,
                  include_billing=False):
    extra_columns, extra_joins = "", ""
    if include_billing:
        extra_columns = (
            ", COALESCE(bi.subtotal, 0) AS bill_subtotal, "
            "COALESCE(b.discount, 0) AS bill_discount, "
            "COALESCE(b.paid_amount, 0) AS bill_paid"
        )
        extra_joins = (
            " LEFT JOIN (SELECT visit_id, SUM(quantity * unit_price) AS subtotal "
            "FROM bill_items GROUP BY visit_id) bi ON bi.visit_id = v.visit_id "
            "LEFT JOIN bills b ON b.visit_id = v.visit_id"
        )
    sql = (
        "SELECT v.visit_id, p.patient_id, p.name, p.age, p.gender, p.phone, p.city, "
        "v.visit_type, v.disease, v.department, v.doctor, v.admit_date, "
        f"v.discharge_date, v.status{extra_columns} "
        f"FROM visits v JOIN patients p ON p.patient_id = v.patient_id{extra_joins} "
        "WHERE 1=1"
    )
    params = []
    if term:
        sql += " AND (p.name LIKE ? OR p.phone LIKE ? OR CAST(p.patient_id AS TEXT) = ?)"
        params += [f"%{term}%", f"%{term}%", term.strip()]
    for column, value in (("v.disease", disease), ("v.department", department),
                          ("v.status", status), ("v.visit_type", visit_type)):
        if value != "All":
            sql += f" AND {column} = ?"
            params.append(value)
    if start:
        sql += " AND v.admit_date >= ?"
        params.append(start)
    if end:
        sql += " AND v.admit_date <= ?"
        params.append(end)
    sql += " ORDER BY v.admit_date DESC, v.visit_id DESC LIMIT ?"
    params.append(limit)
    df = query_df(sql, params)
    if include_billing:
        subtotal = df.pop("bill_subtotal")
        discount = df.pop("bill_discount").clip(upper=subtotal)
        paid = df.pop("bill_paid")
        total = subtotal - discount
        df["bill_total"] = total
        df["bill_paid"] = paid
        df["bill_balance"] = (total - paid).clip(lower=0)
        df["payment_status"] = "Unpaid"
        df.loc[(paid > 0) & (paid < total), "payment_status"] = "Partially paid"
        df.loc[(subtotal > 0) & (paid >= total), "payment_status"] = "Paid"
        df.loc[subtotal <= 0, "payment_status"] = "No charges"
    return df


def patient_history(patient_id):
    return query_df(
        "SELECT visit_id, visit_type, disease, department, doctor, admit_date, "
        "discharge_date, status, notes FROM visits WHERE patient_id = ? "
        "ORDER BY admit_date DESC",
        (patient_id,),
    )


# ------------------------------------------------------------------ Billing
BILL_CATEGORIES = [
    "Consultation", "Room / Bed", "Medicine", "Lab Test",
    "Radiology / Scan", "Procedure / Surgery", "Other",
]
PAYMENT_MODES = ["Cash", "UPI", "Card", "Insurance", "Other"]


def get_visit_header(visit_id):
    df = query_df(
        "SELECT v.visit_id, v.visit_type, v.disease, v.department, v.doctor, "
        "v.admit_date, v.discharge_date, v.status, p.patient_id, p.name, p.age, "
        "p.gender, p.phone, p.city FROM visits v "
        "JOIN patients p ON p.patient_id = v.patient_id WHERE v.visit_id = ?",
        (visit_id,),
    )
    return df.iloc[0].to_dict() if not df.empty else None


def add_bill_item(visit_id, category, description, quantity, unit_price):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO bill_items (visit_id, category, description, quantity, unit_price) "
            "VALUES (?, ?, ?, ?, ?)",
            (visit_id, category, description, quantity, unit_price),
        )


def get_bill_items(visit_id):
    df = query_df(
        "SELECT item_id, category, description, quantity, unit_price "
        "FROM bill_items WHERE visit_id = ? ORDER BY item_id",
        (visit_id,),
    )
    df["amount"] = df["quantity"] * df["unit_price"]
    return df


def delete_bill_item(item_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM bill_items WHERE item_id = ?", (item_id,))


def get_bill_meta(visit_id):
    df = query_df(
        "SELECT discount, paid_amount, payment_mode FROM bills WHERE visit_id = ?",
        (visit_id,),
    )
    if df.empty:
        return {"discount": 0.0, "paid_amount": 0.0, "payment_mode": "Cash"}
    row = df.iloc[0]
    return {
        "discount": float(row["discount"] or 0),
        "paid_amount": float(row["paid_amount"] or 0),
        "payment_mode": row["payment_mode"] or "Cash",
    }


def save_bill_meta(visit_id, discount, paid_amount, payment_mode):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO bills (visit_id, discount, paid_amount, payment_mode) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(visit_id) DO UPDATE SET "
            "discount = excluded.discount, paid_amount = excluded.paid_amount, "
            "payment_mode = excluded.payment_mode",
            (visit_id, discount, paid_amount, payment_mode),
        )


def bill_summary(visit_id):
    items = get_bill_items(visit_id)
    meta = get_bill_meta(visit_id)
    subtotal = float(items["amount"].sum()) if not items.empty else 0.0
    discount = min(meta["discount"], subtotal)
    total = subtotal - discount
    paid = meta["paid_amount"]
    balance = max(total - paid, 0.0)
    if subtotal <= 0:
        status = "No charges"
    elif paid >= total:
        status = "Paid"
    elif paid > 0:
        status = "Partially paid"
    else:
        status = "Unpaid"
    return {
        "subtotal": subtotal, "discount": discount, "total": total,
        "paid": paid, "balance": balance, "status": status,
        "payment_mode": meta["payment_mode"],
    }