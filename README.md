# Hospital Analytics

A hospital management and analytics web app built with Streamlit and SQLite. Staff sign in with a Staff ID and password, register patients, search records, generate PDF bills, and ask questions about hospital data in plain Hindi or English.

> The repository ships with a script that generates **synthetic demo data**. No real patient data is included.

## Features

- **Staff login** with Staff ID and password, role-based access, account lockout and session timeout
- **Dashboard**: patients per day, currently admitted, discharged today, top diseases, department-wise load
- **Add Patient**: register a new patient or add a visit for an existing one (OPD / IPD / Emergency)
- **Search**: find patients by name, phone or ID; filter by disease, department, status, visit type and date; export results to CSV; view a patient's full visit history
- **Ask AI**: ask questions such as "How many patients came today?" or "Top 5 diseases this month" in Hindi, Hinglish or English
- **Billing**: add charges per visit (consultation, room, medicine, lab tests and more), apply a discount, record payment, and **download the bill as a PDF**
- **Discharge**: discharge or refer admitted patients
- **User management** (admin): create staff logins, reset passwords, enable or disable accounts
- **Audit log**: records logins, failed attempts, new visits, discharges, bill downloads and AI questions

## Screenshots

### Dashboard
![Dashboard](docs/screenshots/dashboard.png)

### Search
![Search](docs/screenshots/search.png)

### PDF bills
All bills below use synthetic demo data.

| Admitted patient, part paid | OPD, fully paid | Emergency, unpaid with discount |
|---|---|---|
| ![Bill 1](docs/screenshots/bill-1.png) | ![Bill 2](docs/screenshots/bill-2.png) | ![Bill 3](docs/screenshots/bill-3.png) |

## Roles

| Role | Access |
|---|---|
| admin | Everything, including Users and the audit log |
| doctor | Dashboard, Search, Ask AI |
| reception | Add Patient, Search, Discharge |
| billing | Search, Billing |

## Tech Stack

- Python 3.12
- Streamlit
- SQLite
- Pandas and Plotly
- Google Gemini API (`google-genai`)
- ReportLab (PDF bills)

## Project Structure

```
Hospital Analytics/
├── app.py            # Streamlit app: tabs and role-based access
├── auth.py           # Login, roles, password hashing, lockout, audit log
├── db.py             # Database helpers: patients, visits, search, billing
├── billing.py        # PDF bill generation
├── ai_chat.py        # Natural language question -> safe read-only SQL
├── generate_data.py  # Creates the database with synthetic demo data
├── backup.py         # Safe database backup
├── start_server.bat  # One-click server start (Windows)
├── backup.bat        # One-click backup (Windows)
├── .streamlit/config.toml
├── docs/screenshots/ # Images used in this README
├── requirements.txt
└── README.md
```

## Setup

1. Create and activate a virtual environment:

```
python -m venv venv
venv\Scripts\activate
```

2. Install dependencies:

```
pip install -r requirements.txt
```

3. Create a `.env` file in the project folder with your Gemini API key (needed only for the Ask AI tab). Get a key from [Google AI Studio](https://aistudio.google.com/):

```
GEMINI_API_KEY=your_api_key_here
```

4. Create the demo database (run this once only, it resets the data):

```
python generate_data.py
```

5. Start the app:

```
streamlit run app.py
```

## First Run

1. On the first launch the app asks you to create the **admin account** (Staff ID, name, password).
2. Sign in, open the **Users** tab and create logins for other staff with a role and a temporary password.
3. Passwords need at least 8 characters with letters and numbers.

## How Ask AI Works

1. You type a question in Hindi or English.
2. Only the question and the table structure are sent to Gemini, which returns one SQL `SELECT` query.
3. The query is validated: a single `SELECT` only, no data-changing statements, and no access to patient names, phone numbers or notes.
4. It runs on a **read-only** database connection and the result is shown in the app.

Patient records and query results are never sent to the AI service.

## Running on a Hospital Network (many computers, one server)

Run the app on **one** server computer. Every other computer opens it in a browser, so all staff share one database.

1. Pick a computer that stays on and give it a fixed IP address (ask your network admin or reserve the IP in the router).
2. Copy the project folder to it and complete the Setup steps above.
3. Create the folder `.streamlit` inside the project folder and put `config.toml` in it.
4. Allow the port in Windows Firewall (PowerShell as Administrator):

```
New-NetFirewallRule -DisplayName "Hospital App" -Direction Inbound -Protocol TCP -LocalPort 8501 -Action Allow -Profile Private
```

5. Start the server by double-clicking `start_server.bat`.
6. On any other computer in the hospital, open `http://SERVER-IP:8501` (for example `http://192.168.1.20:8501`) and sign in with your Staff ID.

**Start automatically after a reboot:** open Task Scheduler, create a task that runs `start_server.bat` "At startup" with highest privileges.

**Daily backup:** create a second task that runs `backup.bat` every day. Backups go to the `backups` folder (the newest 30 are kept). Copy that folder to an external drive regularly.

The database uses WAL mode, so several staff can work at the same time. This setup is for a trusted local network. For access from other buildings or the internet, put the app behind an HTTPS reverse proxy first.

## Security Notes

- Passwords are stored only as salted PBKDF2-HMAC-SHA256 hashes.
- 5 wrong passwords lock the account for 15 minutes.
- Sessions expire after 30 minutes of inactivity.
- The SQLite file is not encrypted. Protect the computer with a Windows login and back up `hospital.db` regularly.
- Run the app on the hospital's own computer or local network. Do not expose it to the internet without HTTPS and a proper security review.
- Do not publish `hospital.db` or `.env`. Add both to `.gitignore`.
- This is a basic login system and is not a substitute for a full security audit or healthcare compliance review.

## Future Improvements

- GST and tax support on bills
- Import of existing hospital data from Excel or CSV
- Appointment scheduling
- Automatic database backups
- Printable discharge summary

## Author

Vinay Kumar - [GitHub](https://github.com/vinay9536kumar-png)