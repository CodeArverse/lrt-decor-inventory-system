"""LRT Decor Inventory System - online server.

Uses only the Python standard library (no pip install needed). Python 3.9+.

    python server.py

It holds the inventory database, the user accounts and the password-reset requests, and
it sends the emails via standard SMTP (Gmail).
The desktop app talks to it over HTTPS (put a reverse proxy such as Caddy in front of it,
or use a host that provides HTTPS).

Settings are environment variables, or lines KEY=value in a file called  server.env  that
sits next to this file:

    ADMIN_EMAIL        the admin's email. Receives "forgot password" requests, and is
                       created as the first admin account on a brand-new database  (required)
    SMTP_HOST          default smtp.gmail.com
    SMTP_PORT          default 465 (SSL) or 587 (TLS)
    SMTP_USER          your sending Gmail address
    SMTP_APP_PASSWORD  your 16-character Google App Password
    PORT               default 8000          HOST   default 0.0.0.0
    DATA_DIR           default ./data  (where inventory.db is kept - back this folder up!)
    SECRET_KEY         optional; generated into DATA_DIR/secret.key when missing
    TOKEN_HOURS        how long a login lasts, default 12
"""
import base64
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import smtplib
import sqlite3
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_env_file():
    path = os.path.join(BASE_DIR, "server.env")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()


def setting(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


DATA_DIR = setting("DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "inventory.db")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PBKDF2_ROUNDS = 200_000
MIN_PASSWORD_LENGTH = 8
MAX_BODY = 64 * 1024
SECRET = b""


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ======================= Database =======================
@contextmanager
def database():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    finally:
        db.close()


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ROUNDS).hex()


def generate_temp_password(length: int = 10) -> str:
    lower, upper, digits = "abcdefghijkmnpqrstuvwxyz", "ABCDEFGHJKLMNPQRSTUVWXYZ", "23456789"
    chars = [secrets.choice(lower), secrets.choice(upper), secrets.choice(digits)]
    chars += [secrets.choice(lower + upper + digits) for _ in range(length - 3)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def init_server():
    global SECRET
    os.makedirs(DATA_DIR, exist_ok=True)

    env_secret = setting("SECRET_KEY")
    if env_secret:
        SECRET = env_secret.encode()
    else:
        path = os.path.join(DATA_DIR, "secret.key")
        if not os.path.isfile(path):
            with open(path, "w", encoding="utf-8") as file:
                file.write(secrets.token_hex(32))
        with open(path, encoding="utf-8") as file:
            SECRET = file.read().strip().encode()

    sqlite3.connect(DB_PATH).execute("PRAGMA journal_mode=WAL").connection.close()

    with database() as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS items (
                   item_id       TEXT PRIMARY KEY,
                   name          TEXT NOT NULL,
                   category      TEXT NOT NULL,
                   subcategory   TEXT NOT NULL DEFAULT '',
                   unit          TEXT NOT NULL DEFAULT 'pcs',
                   quantity      INTEGER NOT NULL DEFAULT 0,
                   price         REAL NOT NULL DEFAULT 0,
                   updated_by    TEXT NOT NULL DEFAULT '',
                   updated_at    TEXT NOT NULL DEFAULT ''
               )"""
        )
        existing = {row[1] for row in db.execute("PRAGMA table_info(items)")}
        for column, definition in {
            "subcategory": "TEXT NOT NULL DEFAULT ''",
            "unit": "TEXT NOT NULL DEFAULT 'pcs'",
            "updated_by": "TEXT NOT NULL DEFAULT ''",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if column not in existing:
                db.execute(f"ALTER TABLE items ADD COLUMN {column} {definition}")

        db.execute(
            """CREATE TABLE IF NOT EXISTS users (
                   email          TEXT PRIMARY KEY,
                   salt           TEXT NOT NULL,
                   password_hash  TEXT NOT NULL,
                   role           TEXT NOT NULL DEFAULT 'user',
                   must_change    INTEGER NOT NULL DEFAULT 0,
                   created_at     TEXT NOT NULL DEFAULT ''
               )"""
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS reset_requests (
                   id            INTEGER PRIMARY KEY AUTOINCREMENT,
                   email         TEXT NOT NULL,
                   requested_at  TEXT NOT NULL,
                   status        TEXT NOT NULL DEFAULT 'pending',
                   handled_by    TEXT NOT NULL DEFAULT '',
                   handled_at    TEXT NOT NULL DEFAULT ''
               )"""
        )

        # Starting item list for a brand-new database (an existing inventory.db is left alone)
        if (db.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0
                and db.execute("PRAGMA user_version").fetchone()[0] < 1):
            from seed_data import ID_PREFIXES, SEED_ITEMS
            counters = {}
            for category, subcategory, default_unit, entries in SEED_ITEMS:
                prefix = ID_PREFIXES[category]
                for entry in entries:
                    name, unit = entry if isinstance(entry, tuple) else (entry, default_unit)
                    counters[prefix] = counters.get(prefix, 0) + 1
                    db.execute(
                        "INSERT OR IGNORE INTO items (item_id, name, category, subcategory, unit, quantity, price) "
                        "VALUES (?, ?, ?, ?, ?, 0, 0)",
                        (f"{prefix}-{counters[prefix]:03d}", name, category, subcategory, unit),
                    )
            db.execute("PRAGMA user_version = 1")

        # First start: create the admin account
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            admin_email = setting("ADMIN_EMAIL").lower()
            if not EMAIL_RE.match(admin_email):
                raise SystemExit("Set ADMIN_EMAIL (the admin's email) before the first start.")
            temp = generate_temp_password()
            salt = secrets.token_hex(16)
            db.execute(
                "INSERT INTO users (email, salt, password_hash, role, must_change, created_at) "
                "VALUES (?, ?, ?, 'admin', 1, ?)",
                (admin_email, salt, hash_password(temp, salt), now()),
            )
            print("=" * 60)
            print("FIRST ADMIN ACCOUNT CREATED")
            print(f"  email:              {admin_email}")
            print(f"  temporary password: {temp}")
            print("Log in with these; you'll be asked to choose a new password.")
            print("=" * 60, flush=True)


# ======================= Tokens & login limits =======================
def make_token(user) -> str:
    payload = {
        "e": user["email"],
        "v": user["salt"][:8],  # changes whenever the password changes -> old sessions die
        "x": int(time.time() + float(setting("TOKEN_HOURS", "12")) * 3600),
    }
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    signature = hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def read_token(token: str):
    try:
        body, signature = token.rsplit(".", 1)
        expected = hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body.encode()))
        if payload["x"] < time.time():
            return None
        return payload
    except Exception:
        return None


FAILS = {}
FAILS_LOCK = threading.Lock()
MAX_FAILS = 5
LOCK_SECONDS = 300


def locked_seconds(key: str) -> int:
    with FAILS_LOCK:
        count, until = FAILS.get(key, (0, 0))
        return max(0, int(until - time.time())) if count >= MAX_FAILS else 0


def register_failure(key: str):
    with FAILS_LOCK:
        if len(FAILS) > 10_000:
            FAILS.clear()
        count, until = FAILS.get(key, (0, 0))
        if count >= MAX_FAILS and until < time.time():
            count = 0  # the lock has run out: start counting again
        count += 1
        FAILS[key] = (count, time.time() + LOCK_SECONDS if count >= MAX_FAILS else 0)


def clear_failures(key: str):
    with FAILS_LOCK:
        FAILS.pop(key, None)


_DUMMY_SALT = "0" * 32


# ======================= Email (SMTP) =======================
def email_ready() -> bool:
    return bool(setting("SMTP_HOST") and setting("SMTP_USER") and setting("SMTP_APP_PASSWORD"))


def send_email(to, subject: str, body: str, reply_to: str = ""):
    if not email_ready():
        raise RuntimeError("SMTP settings are not fully configured in server.env.")

    host = setting("SMTP_HOST", "smtp.gmail.com")
    port = int(setting("SMTP_PORT", "465"))
    user = setting("SMTP_USER")
    password = setting("SMTP_APP_PASSWORD")

    recipients = [to] if isinstance(to, str) else list(to)

    msg = MIMEMultipart()
    msg["From"] = user
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.attach(MIMEText(body, "plain"))

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=20) as server:
                server.login(user, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as server:
                server.starttls()
                server.login(user, password)
                server.send_message(msg)
    except Exception as error:
        raise RuntimeError(f"SMTP error: {error}")


def describe_email_error(error: Exception) -> str:
    return str(error)


LAST_ALERT = {}


def alert_admin_async(user_email: str):
    def work():
        try:
            send_email(
                setting("ADMIN_EMAIL"),
                f"Password reset request from {user_email}",
                f"{user_email} can't log in to the LRT Decor Inventory System and asked for a "
                f"password reset.\n\nTo fix it: open the Inventory System > Password Requests, "
                f"select the request and press \"Reset & Email Password\". A temporary password "
                f"will be emailed to {user_email}.\n\nRequested: {now()}\n",
                reply_to=user_email,
            )
        except Exception as error:
            print(f"Could not email the admin about {user_email}: {describe_email_error(error)}", flush=True)

    threading.Thread(target=work, daemon=True).start()


# ======================= Helpers for handlers =======================
class Context:
    user = None
    body = None
    query = None
    params = None


def clean_email(value) -> str:
    email = str(value or "").strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise HttpError(400, "Please enter a valid email address.")
    return email


def check_new_password(new_password) -> str:
    if not isinstance(new_password, str) or len(new_password) < MIN_PASSWORD_LENGTH:
        raise HttpError(400, f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    return new_password


def count_admins(db) -> int:
    return db.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0]


# ======================= Public handlers =======================
def health(ctx):
    return {"ok": True}


def login(ctx):
    email = str(ctx.body.get("email", "")).strip().lower()[:254]
    password = str(ctx.body.get("password", ""))
    wait = locked_seconds(email)
    if wait:
        raise HttpError(429, f"Too many failed attempts. Try again in {math.ceil(wait / 60)} minute(s).")

    with database() as db:
        row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    candidate = hash_password(password, row["salt"] if row else _DUMMY_SALT)
    if not (row and hmac.compare_digest(candidate, row["password_hash"])):
        register_failure(email)
        raise HttpError(401, "Invalid credentials.")

    clear_failures(email)
    return {
        "token": make_token(row),
        "email": row["email"],
        "role": row["role"],
        "must_change": bool(row["must_change"]),
    }


def forgot_password(ctx):
    email = clean_email(ctx.body.get("email"))
    with database() as db:
        if not db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            status = "unknown"
        elif db.execute(
            "SELECT 1 FROM reset_requests WHERE email = ? AND status = 'pending'", (email,)
        ).fetchone():
            status = "pending"
        else:
            db.execute("INSERT INTO reset_requests (email, requested_at) VALUES (?, ?)", (email, now()))
            status = "created"

    if status == "created" or (status == "pending" and time.time() - LAST_ALERT.get(email, 0) > 600):
        LAST_ALERT[email] = time.time()
        alert_admin_async(email)
    return {"ok": True}


def change_password(ctx):
    user = ctx.user
    wait = locked_seconds(user["email"])
    if wait:
        raise HttpError(429, f"Too many failed attempts. Try again in {math.ceil(wait / 60)} minute(s).")
    current = str(ctx.body.get("current_password", ""))
    if not hmac.compare_digest(hash_password(current, user["salt"]), user["password_hash"]):
        register_failure(user["email"])
        raise HttpError(400, "The current password is wrong.")
    new_password = check_new_password(ctx.body.get("new_password"))
    if new_password == current:
        raise HttpError(400, "The new password must be different from the current one.")

    salt = secrets.token_hex(16)
    with database() as db:
        db.execute(
            "UPDATE users SET salt = ?, password_hash = ?, must_change = 0 WHERE email = ?",
            (salt, hash_password(new_password, salt), user["email"]),
        )
    clear_failures(user["email"])
    return {"token": make_token({"email": user["email"], "salt": salt})}


# ======================= Items =======================
ITEM_COLUMNS = "item_id, name, category, subcategory, unit, quantity, price, updated_by, updated_at"


def parse_item(body: dict, item_id: str) -> dict:
    def text(key, required, limit=200):
        value = str(body.get(key, "")).strip()
        if required and not value:
            raise HttpError(400, "Item ID, Item Name, Category and Unit are required.")
        if len(value) > limit:
            raise HttpError(400, f"{key} is too long.")
        return value

    quantity, price = body.get("quantity"), body.get("price", 0)
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
        raise HttpError(400, "Quantity must be a whole number (0 or more).")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or price < 0 or not math.isfinite(price):
        raise HttpError(400, "Unit Price must be a number (0 or more).")
    if not item_id.strip() or len(item_id) > 50:
        raise HttpError(400, "Item ID, Item Name, Category and Unit are required.")
    return {
        "item_id": item_id.strip(),
        "name": text("name", True),
        "category": text("category", True),
        "subcategory": text("subcategory", False),
        "unit": text("unit", True, 30),
        "quantity": quantity,
        "price": float(price),
    }


def list_items(ctx):
    with database() as db:
        return [dict(r) for r in db.execute(f"SELECT {ITEM_COLUMNS} FROM items ORDER BY rowid")]


def get_item(ctx):
    with database() as db:
        row = db.execute(f"SELECT {ITEM_COLUMNS} FROM items WHERE item_id = ?", (ctx.params[0],)).fetchone()
    if not row:
        raise HttpError(404, "That item no longer exists.")
    return dict(row)


def create_item(ctx):
    item = parse_item(ctx.body, str(ctx.body.get("item_id", "")))
    try:
        with database() as db:
            db.execute(
                "INSERT INTO items (item_id, name, category, subcategory, unit, quantity, price, updated_by, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (item["item_id"], item["name"], item["category"], item["subcategory"], item["unit"],
                 item["quantity"], item["price"], ctx.user["email"], datetime.now().strftime("%Y-%m-%d %H:%M")),
            )
    except sqlite3.IntegrityError:
        raise HttpError(409, f"Item ID '{item['item_id']}' already exists.")
    return {"ok": True}


def update_item(ctx):
    item = parse_item(ctx.body, ctx.params[0])
    with database() as db:
        cursor = db.execute(
            "UPDATE items SET name=?, category=?, subcategory=?, unit=?, quantity=?, price=?, "
            "updated_by=?, updated_at=? WHERE item_id=?",
            (item["name"], item["category"], item["subcategory"], item["unit"], item["quantity"],
             item["price"], ctx.user["email"], datetime.now().strftime("%Y-%m-%d %H:%M"), item["item_id"]),
        )
        if cursor.rowcount == 0:
            raise HttpError(404, "That item no longer exists.")
    return {"ok": True}


def delete_item(ctx):
    with database() as db:
        cursor = db.execute("DELETE FROM items WHERE item_id = ?", (ctx.params[0],))
        if cursor.rowcount == 0:
            raise HttpError(404, "That item no longer exists.")
    return {"ok": True}


# ======================= Admin: reset requests & users =======================
def admin_status(ctx):
    return {"email_ready": email_ready(), "admin_email": setting("ADMIN_EMAIL")}


def list_requests(ctx):
    with database() as db:
        rows = db.execute(
            "SELECT id, email, requested_at, status FROM reset_requests "
            "ORDER BY (status = 'pending') DESC, id DESC LIMIT 100"
        ).fetchall()
    return [dict(r) for r in rows]


def request_count(ctx):
    with database() as db:
        return {"pending": db.execute(
            "SELECT COUNT(*) FROM reset_requests WHERE status = 'pending'").fetchone()[0]}


def email_result(to: str, subject: str, body: str, temp: str) -> dict:
    try:
        send_email(to, subject, body)
        return {"emailed": True}
    except Exception as error:
        return {"emailed": False, "temp_password": temp, "error": describe_email_error(error)}


def reset_request(ctx):
    request_id = int(ctx.params[0])
    gone = False
    with database() as db:
        request = db.execute("SELECT * FROM reset_requests WHERE id = ?", (request_id,)).fetchone()
        if not request:
            raise HttpError(404, "That request no longer exists.")
        if request["status"] != "pending":
            raise HttpError(409, "That request was already handled.")
        email = request["email"]
        temp = generate_temp_password()
        salt = secrets.token_hex(16)
        updated = db.execute(
            "UPDATE users SET salt = ?, password_hash = ?, must_change = 1 WHERE email = ?",
            (salt, hash_password(temp, salt), email),
        ).rowcount
        gone = updated == 0
        db.execute(
            "UPDATE reset_requests SET status = ?, handled_by = ?, handled_at = ? WHERE id = ?",
            ("dismissed" if gone else "done", ctx.user["email"], now(), request_id),
        )
    if gone:
        raise HttpError(404, f"{email} no longer has an account, so the request was dismissed.")

    # Added the temporary password explicitly to the email body
    body = (
        "Hello,\n\nThe admin has reset your LRT Decor Inventory System password.\n\n"
        f"Your temporary password is: {temp}\n\n"
        "Log in with it. You'll be asked to choose a new password right away.\n"
        "If you didn't ask for this, please tell the admin.\n"
    )
    result = email_result(email, "Your new LRT Decor Inventory password", body, temp)
    result["email"] = email
    return result


def dismiss_request(ctx):
    with database() as db:
        cursor = db.execute(
            "UPDATE reset_requests SET status = 'dismissed', handled_by = ?, handled_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (ctx.user["email"], now(), int(ctx.params[0])),
        )
        if cursor.rowcount == 0:
            raise HttpError(404, "That request is no longer pending.")
    return {"ok": True}


def list_users(ctx):
    with database() as db:
        return [dict(r) for r in db.execute("SELECT email, role FROM users ORDER BY role, email")]


def add_user(ctx):
    email = clean_email(ctx.body.get("email"))
    role = str(ctx.body.get("role", "user"))
    if role not in ("user", "admin"):
        raise HttpError(400, "Role must be user or admin.")
    temp = generate_temp_password()
    salt = secrets.token_hex(16)
    try:
        with database() as db:
            db.execute(
                "INSERT INTO users (email, salt, password_hash, role, must_change, created_at) "
                "VALUES (?, ?, ?, ?, 1, ?)",
                (email, salt, hash_password(temp, salt), role, now()),
            )
    except sqlite3.IntegrityError:
        raise HttpError(409, "That email already has an account.")

    body = (
        "Hello,\n\nAn account was created for you in the LRT Decor Inventory System.\n\n"
        f"Email: {email}\nTemporary password: {temp}\n\n"
        "Log in with it. You'll be asked to choose your own password right away.\n"
    )
    result = email_result(email, "Your LRT Decor Inventory account", body, temp)
    result["email"] = email
    return result


def delete_user(ctx):
    email = clean_email(ctx.query.get("email"))
    if email == ctx.user["email"]:
        raise HttpError(400, "You can't remove the account you're logged in with.")
    with database() as db:
        row = db.execute("SELECT role FROM users WHERE email = ?", (email,)).fetchone()
        if not row:
            raise HttpError(404, "No such user.")
        if row["role"] == "admin" and count_admins(db) <= 1:
            raise HttpError(400, "You can't remove the last admin.")
        db.execute("DELETE FROM users WHERE email = ?", (email,))
        db.execute("DELETE FROM reset_requests WHERE email = ? AND status = 'pending'", (email,))
    return {"ok": True}


# ======================= Routing =======================
ROUTES = [(method, re.compile(pattern), func, access) for method, pattern, func, access in [
    ("GET", r"/health", health, "public"),
    ("POST", r"/login", login, "public"),
    ("POST", r"/forgot-password", forgot_password, "public"),
    ("POST", r"/change-password", change_password, "any"),
    ("GET", r"/items", list_items, "user"),
    ("POST", r"/items", create_item, "user"),
    ("GET", r"/items/([^/]+)", get_item, "user"),
    ("PUT", r"/items/([^/]+)", update_item, "user"),
    ("DELETE", r"/items/([^/]+)", delete_item, "user"),
    ("GET", r"/admin/status", admin_status, "admin"),
    ("GET", r"/admin/requests", list_requests, "admin"),
    ("GET", r"/admin/requests/count", request_count, "admin"),
    ("POST", r"/admin/requests/(\d+)/reset", reset_request, "admin"),
    ("POST", r"/admin/requests/(\d+)/dismiss", dismiss_request, "admin"),
    ("GET", r"/admin/users", list_users, "admin"),
    ("POST", r"/admin/users", add_user, "admin"),
    ("DELETE", r"/admin/users", delete_user, "admin"),
]]


def authorize(access: str, headers):
    if access == "public":
        return None
    header = headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HttpError(401, "Please log in.")
    payload = read_token(header[7:])
    if not payload:
        raise HttpError(401, "Your session expired. Please log in again.")
    with database() as db:
        user = db.execute("SELECT * FROM users WHERE email = ?", (payload["e"],)).fetchone()
    if not user or user["salt"][:8] != payload["v"]:
        raise HttpError(401, "Your session expired. Please log in again.")
    user = dict(user)
    if access != "any" and user["must_change"]:
        raise HttpError(403, "Choose a new password first.")
    if access == "admin" and user["role"] != "admin":
        raise HttpError(403, "Admins only.")
    return user


class Handler(BaseHTTPRequestHandler):
    server_version = "LRTInventory/1.0"
    timeout = 30

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PUT(self):
        self.dispatch("PUT")

    def do_DELETE(self):
        self.dispatch("DELETE")

    def send_json(self, status: int, data):
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise HttpError(413, "Request too large.")
        if length == 0:
            return {}
        try:
            data = json.loads(self.rfile.read(length))
        except ValueError:
            raise HttpError(400, "Invalid request.")
        if not isinstance(data, dict):
            raise HttpError(400, "Invalid request.")
        return data

    def dispatch(self, method: str):
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            route, path_exists = None, False
            for route_method, pattern, func, access in ROUTES:
                match = pattern.fullmatch(path)
                if match:
                    path_exists = True
                    if route_method == method:
                        route = (func, access, match)
                        break
            if route is None:
                raise HttpError(405 if path_exists else 404, "Not found.")

            func, access, match = route
            ctx = Context()
            ctx.user = authorize(access, self.headers)
            ctx.query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            ctx.params = [unquote(g) for g in match.groups()]
            ctx.body = self.read_json() if method in ("POST", "PUT") else {}
            self.send_json(200, func(ctx))
        except HttpError as error:
            self.send_json(error.status, {"detail": error.message})
        except Exception:
            traceback.print_exc()
            self.send_json(500, {"detail": "Server error."})


def main():
    init_server()
    host, port = setting("HOST", "0.0.0.0"), int(setting("PORT", "8000"))
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    print(f"LRT Inventory server running on http://{host}:{port}  (data: {DATA_DIR})", flush=True)
    if not email_ready():
        print("NOTE: SMTP settings not fully set - no emails will be sent.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("Stopping.")


if __name__ == "__main__":
    sys.exit(main())