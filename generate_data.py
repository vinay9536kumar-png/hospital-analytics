import random
import sqlite3
from datetime import date, timedelta

random.seed(42)

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
CITIES = ["Delhi", "Lucknow", "Jaipur", "Kanpur", "Mumbai"]
NUM_PATIENTS = 1500
DAYS = 120

conn = sqlite3.connect("hospital.db")
cur = conn.cursor()
cur.executescript(
    """
    DROP TABLE IF EXISTS visits;
    DROP TABLE IF EXISTS patients;
    CREATE TABLE patients (
        patient_id INTEGER PRIMARY KEY,
        name TEXT,
        age INTEGER,
        gender TEXT,
        city TEXT
    );
    CREATE TABLE visits (
        visit_id INTEGER PRIMARY KEY,
        patient_id INTEGER,
        visit_type TEXT,
        disease TEXT,
        department TEXT,
        admit_date TEXT,
        discharge_date TEXT,
        status TEXT,
        FOREIGN KEY (patient_id) REFERENCES patients (patient_id)
    );
    """
)

patients = [
    (
        pid,
        f"Patient {pid}",
        random.randint(1, 90),
        random.choice(["Male", "Female"]),
        random.choice(CITIES),
    )
    for pid in range(1, NUM_PATIENTS + 1)
]
cur.executemany("INSERT INTO patients VALUES (?, ?, ?, ?, ?)", patients)

today = date.today()
visits = []
visit_id = 1
for offset in range(DAYS, -1, -1):
    day = today - timedelta(days=offset)
    count = random.randint(25, 45) if day.weekday() == 6 else random.randint(50, 90)
    for _ in range(count):
        disease = random.choice(list(DISEASES))
        visit_type = random.choices(["OPD", "IPD", "Emergency"], weights=[65, 25, 10])[0]

        if visit_type == "OPD":
            discharge = day
        else:
            discharge = day + timedelta(days=random.randint(1, 10))

        if discharge > today:
            status, discharge_str = "Admitted", None
        else:
            status = random.choices(["Discharged", "Referred"], weights=[95, 5])[0]
            discharge_str = discharge.isoformat()

        visits.append(
            (
                visit_id,
                random.randint(1, NUM_PATIENTS),
                visit_type,
                disease,
                DISEASES[disease],
                day.isoformat(),
                discharge_str,
                status,
            )
        )
        visit_id += 1

cur.executemany("INSERT INTO visits VALUES (?, ?, ?, ?, ?, ?, ?, ?)", visits)
conn.commit()

print("Patients:", cur.execute("SELECT COUNT(*) FROM patients").fetchone()[0])
print("Visits:", cur.execute("SELECT COUNT(*) FROM visits").fetchone()[0])
print(
    "Visits today:",
    cur.execute("SELECT COUNT(*) FROM visits WHERE admit_date = ?", (today.isoformat(),)).fetchone()[0],
)
conn.close()