"""Login, roles, password hashing, lockout and audit log for the hospital app.

- Passwords are never stored: only a salted PBKDF2-HMAC-SHA256 hash.
- 5 wrong passwords lock the account for 15 minutes.
- Sessions expire after 30 minutes of inactivity.
- Every login and important action is written to an audit log.
"""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

import db

ITERATIONS = 200_000
MAX_FAILED = 5
LOCK_MINUTES = 15
SESSION_MINUTES = 30

ROLES = ["admin", "doctor", "reception", "billing"]
ROLE_TABS = {
    "admin": ["Dashboard", "Add Patient", "Search", "Ask AI", "Billing", "Discharge", "Users"],
    "doctor": ["Dashboard", "Search", "Ask AI"],
    "reception": ["Add Patient", "Search", "Discharge"],
    "billing": ["Search", "Billing"],
}
# Roles that can see bill amounts outside the Billing tab (for example in Search)
BILL_VIEW_ROLES = {"admin", "billing"}
USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,30}$")


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def ensure_tables():
    with db.get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                full_name TEXT,
                role TEXT NOT NULL,
                salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                active INTEGER DEFAULT 1,
                failed_attempts INTEGER DEFAULT 0,
                locked_until TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                username TEXT,
                action TEXT,
                details TEXT
            );
            """
        )


# ---------------------------------------------------------------- passwords
def hash_password(password, salt_hex):
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), ITERATIONS
    ).hex()


def password_problem(password):
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Password must contain both letters and numbers."
    return None


# -------------------------------------------------------------------- users
def has_users():
    return db.scalar("SELECT COUNT(*) FROM users") > 0


def get_user(username):
    df = db.query_df("SELECT * FROM users WHERE username = ?", (username,))
    return df.iloc[0].to_dict() if not df.empty else None


def create_user(username, password, role, full_name=""):
    username = username.strip().lower()
    if not USERNAME_RE.match(username):
        raise ValueError("Staff ID must be 3-30 characters: letters, numbers, . _ -")
    if role not in ROLES:
        raise ValueError("Invalid role.")
    problem = password_problem(password)
    if problem:
        raise ValueError(problem)
    if get_user(username):
        raise ValueError("This Staff ID already exists.")
    salt = secrets.token_hex(16)
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO users (username, full_name, role, salt, password_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (username, full_name.strip(), role, salt, hash_password(password, salt), now_iso()),
        )


def list_users():
    return db.query_df(
        "SELECT username, full_name, role, active, failed_attempts, locked_until, created_at "
        "FROM users ORDER BY username"
    )


def active_admin_count():
    return db.scalar("SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1")


def set_active(username, active):
    user = get_user(username)
    if user and user["role"] == "admin" and not active and active_admin_count() <= 1:
        raise ValueError("You cannot deactivate the last active admin.")
    with db.get_conn() as conn:
        conn.execute("UPDATE users SET active = ? WHERE username = ?", (1 if active else 0, username))


def reset_password(username, new_password):
    problem = password_problem(new_password)
    if problem:
        raise ValueError(problem)
    salt = secrets.token_hex(16)
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE users SET salt = ?, password_hash = ?, failed_attempts = 0, "
            "locked_until = NULL WHERE username = ?",
            (salt, hash_password(new_password, salt), username),
        )


def change_password(username, old_password, new_password):
    user, _ = authenticate(username, old_password, log=False)
    if user is None:
        raise ValueError("Current password is incorrect.")
    reset_password(username, new_password)


# ----------------------------------------------------------- authentication
def authenticate(username, password, log=True):
    """Returns (user_dict or None, message)."""
    username = username.strip().lower()
    user = get_user(username)
    generic = "Invalid Staff ID or password."

    if user is None:
        hash_password(password, "00" * 16)  # keep timing similar
        if log:
            log_action(username or "-", "login_failed", "unknown user")
        return None, generic

    if not user["active"]:
        if log:
            log_action(username, "login_blocked", "inactive account")
        return None, "This account is disabled. Please contact the admin."

    locked_until = user["locked_until"]
    if locked_until and datetime.fromisoformat(locked_until) > datetime.now():
        return None, f"Account locked until {locked_until}. Try again later."

    expected = user["password_hash"]
    if hmac.compare_digest(hash_password(password, user["salt"]), expected):
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE username = ?",
                (username,),
            )
        if log:
            log_action(username, "login")
        return {"username": username, "full_name": user["full_name"] or username,
                "role": user["role"]}, "OK"

    failed = int(user["failed_attempts"] or 0) + 1
    lock = None
    if failed >= MAX_FAILED:
        lock = (datetime.now() + timedelta(minutes=LOCK_MINUTES)).isoformat(timespec="seconds")
        failed = 0
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE username = ?",
            (failed, lock, username),
        )
    if log:
        log_action(username, "login_failed", "wrong password" + (" - account locked" if lock else ""))
    if lock:
        return None, f"Too many wrong attempts. Account locked for {LOCK_MINUTES} minutes."
    return None, generic


# ---------------------------------------------------------------- audit log
def log_action(username, action, details=""):
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO audit_log (timestamp, username, action, details) VALUES (?, ?, ?, ?)",
            (now_iso(), username, action, details),
        )


def recent_audit(limit=200):
    return db.query_df(
        "SELECT timestamp, username, action, details FROM audit_log "
        "ORDER BY log_id DESC LIMIT ?",
        (limit,),
    )


# ------------------------------------------------------------ Streamlit UI
def require_login():
    """Shows the login (or first-time setup) screen until the user signs in."""
    import streamlit as st

    ensure_tables()
    user = st.session_state.get("auth_user")
    if user:
        last = st.session_state.get("last_active", datetime.now())
        if datetime.now() - last > timedelta(minutes=SESSION_MINUTES):
            log_action(user["username"], "session_timeout")
            st.session_state.pop("auth_user", None)
            st.session_state["login_notice"] = "Your session expired. Please sign in again."
        else:
            st.session_state["last_active"] = datetime.now()
            return user

    st.title("🏥 Hospital Analytics")
    notice = st.session_state.pop("login_notice", None)
    if notice:
        st.info(notice)

    if not has_users():
        st.subheader("First-time setup: create the admin account")
        with st.form("first_admin"):
            full_name = st.text_input("Full name")
            username = st.text_input("Staff ID")
            password = st.text_input("Password", type="password")
            confirm = st.text_input("Confirm password", type="password")
            if st.form_submit_button("Create admin"):
                if password != confirm:
                    st.error("Passwords do not match.")
                else:
                    try:
                        create_user(username, password, "admin", full_name)
                        log_action(username.strip().lower(), "admin_created")
                        st.success("Admin created. You can now sign in.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        st.stop()

    st.subheader("Sign in")
    with st.form("login_form"):
        username = st.text_input("Staff ID")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in"):
            user, message = authenticate(username, password)
            if user:
                st.session_state["auth_user"] = user
                st.session_state["last_active"] = datetime.now()
                st.rerun()
            else:
                st.error(message)
    st.stop()


def render_sidebar(user):
    import streamlit as st

    st.sidebar.markdown(f"**{user['full_name']}**  \nRole: {user['role']}")
    with st.sidebar.expander("Change password"):
        with st.form("change_pw"):
            old = st.text_input("Current password", type="password")
            new = st.text_input("New password", type="password")
            confirm = st.text_input("Confirm new password", type="password")
            if st.form_submit_button("Update"):
                if new != confirm:
                    st.error("New passwords do not match.")
                else:
                    try:
                        change_password(user["username"], old, new)
                        log_action(user["username"], "password_changed")
                        st.success("Password updated.")
                    except ValueError as exc:
                        st.error(str(exc))
    if st.sidebar.button("Log out"):
        log_action(user["username"], "logout")
        st.session_state.pop("auth_user", None)
        st.rerun()


def render_user_admin(current_user):
    import streamlit as st

    st.subheader("Users")
    st.dataframe(list_users(), width="stretch", hide_index=True)

    st.markdown("**Add a staff member**")
    with st.form("add_user", clear_on_submit=True):
        a, b, c, d = st.columns(4)
        username = a.text_input("Username")
        full_name = b.text_input("Full name")
        role = c.selectbox("Role", ROLES, index=ROLES.index("reception"))
        password = d.text_input("Temporary password", type="password")
        if st.form_submit_button("Create staff login"):
            try:
                create_user(username, password, role, full_name)
                log_action(current_user["username"], "user_created",
                           f"{username.strip().lower()} ({role})")
                st.success("User created.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    users = list_users()["username"].tolist()
    st.markdown("**Manage a user**")
    target = st.selectbox("Select Staff ID", users, key="manage_user")
    c1, c2 = st.columns(2)
    with c1.form("reset_pw", clear_on_submit=True):
        new_pw = st.text_input("New password", type="password")
        if st.form_submit_button("Reset password"):
            try:
                reset_password(target, new_pw)
                log_action(current_user["username"], "password_reset", target)
                st.success("Password reset.")
            except ValueError as exc:
                st.error(str(exc))
    with c2:
        info = get_user(target)
        is_active = bool(info["active"])
        label = "Disable account" if is_active else "Enable account"
        if st.button(label):
            try:
                if target == current_user["username"] and is_active:
                    raise ValueError("You cannot disable your own account.")
                set_active(target, not is_active)
                log_action(current_user["username"],
                           "user_disabled" if is_active else "user_enabled", target)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    with st.expander("Audit log (latest 200 events)"):
        st.dataframe(recent_audit(), width="stretch", hide_index=True)
        