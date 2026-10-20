import os
import json
import random
import secrets
import hashlib
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, date, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
REAL_DB = os.path.join(BASE, "temple.db")
DEMO_DB = os.path.join(BASE, "temple_demo.db")
STATE = {"db": REAL_DB, "role": None, "demo": False, "temple": "T1",
         "auth": None, "home_temple": None}

TEMPLES = {
    "T1": {"name": "Shri Parshwa Sushil Dham", "place": "Balagaranahalli, Bengaluru",
           "kind": "Jain temple", "food": True,
           "sections": ["Food Coupons", "Room Bookings", "Income", "Expenses", "Expense Summary",
                        "Salary", "Staff", "Programs", "Monthly Summary"]},
    "T2": {"name": "Shri Suswani Mataji Dham", "place": "Guddahatti Gate, Bengaluru",
           "kind": "Hindu temple", "food": False,
           "sections": ["Room Bookings", "Income", "Expenses", "Expense Summary",
                        "Salary", "Staff", "Programs", "Monthly Summary"]},
}

# Coupon prices (Rs.). Saved records keep the total they were saved with.
BREAKFAST_RATE = 120
LUNCH_RATE = 150
DINNER_RATE = 150

DATA_TABLES = ["Staff", "MonthlySalary", "FoodCoupons", "Rooms", "Bookings",
               "Income", "Expenses", "Programs"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS Staff (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, role TEXT,
    date_of_joining TEXT, base_salary REAL,
    created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS MonthlySalary (
    id INTEGER PRIMARY KEY, month INTEGER NOT NULL, year INTEGER NOT NULL,
    paid_leave INTEGER, LOP INTEGER, working_days INTEGER,
    total_amount REAL NOT NULL, hold_salary REAL, total_deductions REAL,
    addition REAL, net_payable REAL NOT NULL, remarks TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS FoodCoupons (
    id INTEGER PRIMARY KEY, date TEXT NOT NULL, day TEXT,
    breakfast INTEGER, lunch INTEGER, dinner INTEGER, total_price REAL,
    remarks TEXT, created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS Rooms (
    id INTEGER PRIMARY KEY, room_no TEXT NOT NULL, room_type TEXT,
    rate_per_day REAL, created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS Bookings (
    id INTEGER PRIMARY KEY, guest_name TEXT NOT NULL, phone TEXT,
    no_of_people INTEGER, room_no TEXT NOT NULL, check_in TEXT NOT NULL,
    check_out TEXT NOT NULL, total_amount REAL, payment_mode TEXT, remarks TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS Income (
    id INTEGER PRIMARY KEY, date TEXT NOT NULL, source TEXT NOT NULL,
    amount REAL NOT NULL, payment_mode TEXT, receipt_no TEXT, donor TEXT,
    occasion TEXT, remarks TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS ExpenseCategories (
    name TEXT PRIMARY KEY, temples TEXT DEFAULT 'BOTH', summary_group TEXT);
CREATE TABLE IF NOT EXISTS Context (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS Expenses (
    id INTEGER PRIMARY KEY, date TEXT NOT NULL, category TEXT NOT NULL,
    item TEXT NOT NULL, quantity REAL, unit TEXT, rate REAL,
    amount REAL NOT NULL, vendor TEXT, bill_no TEXT, occasion TEXT, remarks TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS Programs (
    id INTEGER PRIMARY KEY, program_name TEXT NOT NULL, organizer TEXT,
    date TEXT NOT NULL, place TEXT, expenses REAL, donations_received REAL,
    created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS VoidLog (
    id INTEGER PRIMARY KEY, table_name TEXT NOT NULL, record_id INTEGER NOT NULL,
    reason TEXT NOT NULL, voided_at TEXT NOT NULL, voided_by TEXT, snapshot TEXT);
CREATE TABLE IF NOT EXISTS Auth (
    role TEXT PRIMARY KEY, salt TEXT NOT NULL, hash TEXT NOT NULL);
"""

# (name, which temples use it, heading used in the combined Expense Summary)
DEFAULT_CATEGORIES = [
    ("Fuel & Generator", "BOTH", "Fuel & Generator"),
    ("Flowers & Decoration", "BOTH", "Flowers & Decoration"),
    ("Sanitation", "BOTH", "Sanitation"),
    ("Plumbing", "BOTH", "Plumbing"),
    ("Electrical", "BOTH", "Electrical"),
    ("Service & Repairs", "BOTH", "Service & Repairs"),
    ("Other", "BOTH", "Other"),
    ("Kitchen & Groceries", "T1", "Kitchen & Groceries"),
    ("Pooja Items", "T1", "Pooja Ingredients"),
    ("Abhishek Milk", "T2", "Pooja Ingredients"),
    ("Homa Samagri", "T2", "Pooja Ingredients"),
    ("Pooja Shop Stock", "T2", "Pooja Shop Stock"),
]


# ---------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------
def query(sql, params=()):
    conn = sqlite3.connect(STATE["db"])
    try:
        cur = conn.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall() if cur.description else []
        conn.commit()
        return cols, rows
    finally:
        conn.close()


def add_column(conn, table, col, decl):
    existing = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    if col not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def init_db(path):
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        # every record belongs to a temple (older files are treated as temple 1)
        for t in DATA_TABLES + ["VoidLog"]:
            add_column(conn, t, "temple", "TEXT NOT NULL DEFAULT 'T1'")
        add_column(conn, "ExpenseCategories", "temples", "TEXT DEFAULT 'BOTH'")
        add_column(conn, "ExpenseCategories", "summary_group", "TEXT")
        for t in DATA_TABLES:
            hidden = f"id NOT IN (SELECT record_id FROM VoidLog WHERE table_name='{t}')"
            conn.execute(f"DROP VIEW IF EXISTS live_{t}")
            conn.execute(f"DROP VIEW IF EXISTS all_{t}")
            # live_X = records of the temple chosen on screen, voided ones hidden
            conn.execute(f"CREATE VIEW live_{t} AS SELECT * FROM {t} WHERE "
                         f"temple = (SELECT value FROM Context WHERE key='temple') AND {hidden}")
            # all_X = both temples together (used by the combined Expense Summary)
            conn.execute(f"CREATE VIEW all_{t} AS SELECT * FROM {t} WHERE {hidden}")
        conn.executemany("INSERT OR REPLACE INTO ExpenseCategories (name, temples, summary_group) "
                         "VALUES (?,?,?)", DEFAULT_CATEGORIES)
        conn.execute("INSERT OR IGNORE INTO Context VALUES ('temple', 'T1')")
        if not conn.execute("SELECT 1 FROM Rooms WHERE temple='T2'").fetchone():
            t2_rooms = [("201", "2BHK"), ("301", "2BHK")] + [
                (f"{f}0{n}", "4-bed with toilet") for f in (2, 3, 4) for n in range(2, 6)]
            conn.executemany("INSERT INTO Rooms (room_no, room_type, temple) VALUES (?,?,'T2')", t2_rooms)
        conn.commit()
    finally:
        conn.close()


def set_temple(code):
    STATE["temple"] = code
    query("INSERT OR REPLACE INTO Context VALUES ('temple', ?)", (code,))


def today():
    return datetime.now().strftime("%Y-%m-%d")


def fmtnum(x):
    return f"{x:.2f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------
# Passwords (stored scrambled, never as plain text)
# ---------------------------------------------------------------
def hash_pw(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()


def set_password(role, pw):
    salt = secrets.token_hex(16)
    query("INSERT OR REPLACE INTO Auth VALUES (?,?,?)", (role, salt, hash_pw(pw, salt)))


def auth_ready():
    have = {r[0] for r in query("SELECT role FROM Auth")[1]}
    return {"entry_T1", "entry_T2", "viewer"} <= have


def check_password(pw):
    for role, salt, h in query("SELECT role, salt, hash FROM Auth")[1]:
        if secrets.compare_digest(hash_pw(pw, salt), h):
            return role
    return None


# ---------------------------------------------------------------
# Void (instead of delete): record stays forever in VoidLog
# ---------------------------------------------------------------
def void_record(table, rid, reason):
    conn = sqlite3.connect(STATE["db"])
    try:
        cur = conn.execute(f"SELECT * FROM {table} WHERE id=?", (rid,))
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        if row is None:
            raise ValueError("Record not found.")
        snap = dict(zip(cols, row))
        conn.execute(
            "INSERT INTO VoidLog (table_name, record_id, reason, voided_at, voided_by, snapshot, temple) "
            "VALUES (?,?,?,?,?,?,?)",
            (table, rid, reason, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             STATE.get("auth") or STATE["role"], json.dumps(snap, default=str),
             snap.get("temple", "T1")))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------
# Rules for rooms
# ---------------------------------------------------------------
def parse_rooms(text):
    return [r.strip().upper() for r in text.replace(";", ",").split(",") if r.strip()]


def eff_end(check_in, check_out):
    """A same-day visit (check-in = check-out) occupies the room for that one day."""
    if check_out > check_in:
        return check_out
    return (date.fromisoformat(check_in) + timedelta(days=1)).isoformat()


def validate_booking(v):
    if v["check_out"] < v["check_in"]:
        return ("Check-out cannot be before check-in.\n"
                "For a same-day visit, use the same date for both.")
    rooms = parse_rooms(v["room_no"])
    if not rooms:
        return "Enter at least one room number."
    known = {r[0].upper() for r in query("SELECT room_no FROM live_Rooms")[1]}
    bad = [r for r in rooms if r not in known] if known else []
    if bad:
        return (f"Unknown room(s): {', '.join(bad)}.\n"
                "Please check the room number.")
    rows = query("SELECT guest_name, room_no, check_in, check_out FROM live_Bookings "
                 "WHERE check_in <= ? AND check_out >= ?", (v["check_out"], v["check_in"]))[1]
    new_end = eff_end(v["check_in"], v["check_out"])
    for guest, rn, ci, co in rows:
        if not (v["check_in"] < eff_end(ci, co) and ci < new_end):
            continue
        clash = set(rooms) & set(parse_rooms(rn))
        if clash:
            return (f"Room {', '.join(sorted(clash))} is already occupied by "
                    f"{guest} ({ci} to {co}).")
    v["room_no"] = ", ".join(rooms)
    return None


def validate_income(v):
    if v["amount"] <= 0:
        return "Amount must be more than zero."
    return None


def validate_salary(v):
    if not 1 <= v["month"] <= 12:
        return "Month must be between 1 and 12."
    return None


def rooms_today():
    t = today()
    rooms = query("SELECT room_no, room_type FROM live_Rooms")[1]
    occupied = {}
    rows = query("SELECT guest_name, room_no, check_out FROM live_Bookings "
                 "WHERE check_in <= ? AND (check_out > ? OR (check_in = ? AND check_out = ?))",
                 (t, t, t, t))[1]
    for guest, rn, co in rows:
        for r in parse_rooms(rn):
            occupied[r] = (guest, co)
    busy = [f"{r}: {g}, till {co}" for r, (g, co) in sorted(occupied.items())]
    text = ""
    if rooms:
        free = [f"{r} ({typ})" if typ else r for r, typ in sorted(rooms) if r.upper() not in occupied]
        text = f"AVAILABLE TODAY ({len(free)})\n" + (", ".join(free) or "none") + "\n\n"
    return text + f"OCCUPIED ({len(busy)})\n" + ("\n".join(busy) or "none")


# ---------------------------------------------------------------
# What each section stores
# field = (column, label, kind, required [, choices])
# ---------------------------------------------------------------
def food_auto(v):
    now = datetime.now()
    b, l, d = (v.get(k) or 0 for k in ("breakfast", "lunch", "dinner"))
    return {"date": now.strftime("%Y-%m-%d"), "day": now.strftime("%A"),
            "total_price": b * BREAKFAST_RATE + l * LUNCH_RATE + d * DINNER_RATE}


def salary_calc(num, has):
    if not has("total_amount"):
        return {}
    return {"net_payable": num("total_amount") + num("addition")
            - num("total_deductions") - num("hold_salary")}


def expense_calc(num, has):
    if num("quantity") and num("rate"):
        return {"amount": num("quantity") * num("rate")}
    return {}


def lines_func(sql, fmt):
    def f():
        rows = query(sql)[1]
        return "\n".join(fmt(r) for r in rows) if rows else "No data yet."
    return f


UNITS = ["litres", "kg", "pieces", "bunch", "packet", "box", "hours", "job"]
INCOME_SOURCES = {
    "T1": ["Hundi", "Donation (cash)", "Donation (UPI/online)", "Pooja / Seva tickets",
           "Boli / Chadhava", "Swami Vatsalya donation", "Jeevdaya donation", "Other"],
    "T2": ["Hundi", "Donation (cash)", "Donation (UPI/online)", "Pooja shop sales",
           "Abhishek / Homa seva", "Other"],
}
RITUALS = {"T1": [], "T2": ["Daily abhishek", "Homa"]}


def income_choices():
    return INCOME_SOURCES[STATE["temple"]]


def category_choices():
    return [r[0] for r in query("SELECT name FROM ExpenseCategories "
                                "WHERE temples IN ('BOTH', ?) ORDER BY name", (STATE["temple"],))[1]]


def occasion_choices():
    names = [r[0] for r in query("SELECT program_name FROM live_Programs ORDER BY id DESC")[1]]
    return RITUALS[STATE["temple"]] + names


def new_category(v):
    query("INSERT OR IGNORE INTO ExpenseCategories (name, temples, summary_group) VALUES (?,?,?)",
          (v["category"].strip(), STATE["temple"], v["category"].strip()))

SECTIONS = {
    "Food Coupons": {
        "table": "FoodCoupons", "order": "date DESC, id DESC",
        "zero_blank": True, "auto": food_auto, "unique": ["date"],
        "header": lambda: f"Today: {today()}  ({datetime.now().strftime('%A')})",
        "total_label": lambda num: "Total: Rs. {:,.0f}".format(
            num("breakfast") * BREAKFAST_RATE + num("lunch") * LUNCH_RATE
            + num("dinner") * DINNER_RATE),
        "fields": [("breakfast", "Breakfast coupons", "int", False),
                   ("lunch", "Lunch coupons", "int", False),
                   ("dinner", "Dinner coupons", "int", False),
                   ("remarks", "Remarks", "text", False)],
        "extras": [
            ("Busiest days (top 5)", lines_func(
                "SELECT date, day, breakfast+lunch+dinner AS t FROM live_FoodCoupons "
                "ORDER BY t DESC LIMIT 5",
                lambda r: f"{r[0]}  ({r[1]}) : {r[2]} coupons")),
            ("Average by weekday", lines_func(
                "SELECT day, ROUND(AVG(breakfast+lunch+dinner),1) AS a FROM live_FoodCoupons "
                "GROUP BY day ORDER BY a DESC",
                lambda r: f"{r[0]} : {r[1]} coupons per day")),
        ],
    },
    "Room Bookings": {
        "table": "Bookings", "order": "id DESC",
        "validate": validate_booking,
        "fields": [("guest_name", "Guest name", "text", True),
                   ("phone", "Phone", "text", False),
                   ("no_of_people", "Number of people", "int", False),
                   ("room_no", "Room no(s) - e.g. 101, 102", "text", True),
                   ("check_in", "Check-in (YYYY-MM-DD)", "date", True),
                   ("check_out", "Check-out (YYYY-MM-DD) - same date if leaving the same day", "date", True),
                   ("total_amount", "Total amount", "float", False),
                   ("payment_mode", "Payment mode", "choice", False,
                    ["Cash", "UPI", "Card", "Bank transfer"]),
                   ("remarks", "Remarks", "text", False)],
        "extras": [("Rooms available today", rooms_today)],
    },
    "Income": {
        "table": "Income", "order": "date DESC, id DESC", "validate": validate_income,
        "fields": [("date", "Date (YYYY-MM-DD)", "date", True),
                   ("source", "Source (pick or type)", "choice", True, income_choices),
                   ("amount", "Amount", "float", True),
                   ("payment_mode", "Payment mode", "choice", False,
                    ["Cash", "UPI", "Card", "Bank transfer", "Cheque"]),
                   ("receipt_no", "Receipt no.", "text", False),
                   ("donor", "Donor name (optional)", "text", False),
                   ("occasion", "Occasion / program (optional)", "choice", False,
                    occasion_choices),
                   ("remarks", "Remarks (e.g. weekly hundi counting)", "text", False)],
        "extras": [("Income by source (all time)", lines_func(
            "SELECT source, SUM(amount) FROM live_Income GROUP BY source ORDER BY 2 DESC",
            lambda r: f"{r[0]} : Rs. {r[1]:,.0f}"))],
    },
    "Expenses": {
        "table": "Expenses", "order": "date DESC, id DESC",
        "calc": expense_calc,
        "after_save": new_category,
        "fields": [("date", "Date (YYYY-MM-DD)", "date", True),
                   ("category", "Category (pick or type a new one)", "choice", True,
                    category_choices),
                   ("item", "Item (e.g. Diesel, Phenyl, Roses)", "text", True),
                   ("quantity", "Quantity", "float", False),
                   ("unit", "Unit", "choice", False, UNITS),
                   ("rate", "Rate per unit", "float", False),
                   ("amount", "Amount (auto if quantity x rate)", "float", True),
                   ("vendor", "Vendor / shop", "text", False),
                   ("bill_no", "Bill no.", "text", False),
                   ("occasion", "Occasion / program (optional)", "choice", False,
                    occasion_choices),
                   ("remarks", "Remarks", "text", False)],
        "extras": [("Diesel by month", lines_func(
            "SELECT strftime('%Y-%m', date), SUM(quantity), SUM(amount), "
            "ROUND(SUM(amount)/SUM(quantity),2) FROM live_Expenses "
            "WHERE item LIKE '%diesel%' AND quantity > 0 GROUP BY 1 ORDER BY 1",
            lambda r: f"{r[0]} : {r[1]:g} litres, Rs. {r[2]:,.0f}  (avg Rs. {r[3]} per litre)")),
            ("Milk by month", lines_func(
                "SELECT strftime('%Y-%m', date), SUM(quantity), SUM(amount), "
                "ROUND(SUM(amount)/SUM(quantity),2) FROM live_Expenses "
                "WHERE item LIKE '%milk%' AND quantity > 0 GROUP BY 1 ORDER BY 1",
                lambda r: f"{r[0]} : {r[1]:g} litres, Rs. {r[2]:,.0f}  (avg Rs. {r[3]} per litre)"))],
    },
    "Salary": {
        "table": "MonthlySalary", "order": "year DESC, month DESC",
        "unique": ["month", "year"], "validate": validate_salary, "calc": salary_calc,
        "note": "Net payable is filled in as: total + addition - deductions - hold.\n"
                "You can change it if needed.",
        "fields": [("month", "Month (1-12)", "month", True),
                   ("year", "Year", "year", True),
                   ("paid_leave", "Paid leave (days)", "int", False),
                   ("LOP", "LOP (days)", "int", False),
                   ("working_days", "Working days", "int", False),
                   ("total_amount", "Total salary amount", "float", True),
                   ("hold_salary", "Hold salary", "float", False),
                   ("total_deductions", "Total deductions", "float", False),
                   ("addition", "Addition", "float", False),
                   ("net_payable", "Net payable", "float", True),
                   ("remarks", "Remarks", "text", False)],
    },
    "Staff": {
        "table": "Staff", "order": "id DESC",
        "fields": [("name", "Name", "text", True),
                   ("role", "Role", "text", False),
                   ("date_of_joining", "Date of joining (YYYY-MM-DD)", "date", False),
                   ("base_salary", "Base salary", "float", False)],
    },
    "Programs": {
        "table": "Programs", "order": "date DESC, id DESC",
        "fields": [("program_name", "Program name", "text", True),
                   ("organizer", "Organizer", "text", False),
                   ("date", "Date (YYYY-MM-DD)", "date", True),
                   ("place", "Place", "text", False),
                   ("expenses", "Expenses", "float", False),
                   ("donations_received", "Donations received", "float", False)],
    },
    "Voided Records": {
        "table": "VoidLog", "source": "VoidLog", "order": "id DESC", "readonly": True,
        "back_home": True,
        "fields": [],
    },
}


def convert(kind, text, label, required):
    text = text.strip()
    if text == "":
        if required:
            raise ValueError(f"{label} is required.")
        return None
    try:
        if kind in ("int", "month", "year"):
            return int(text)
        if kind == "float":
            return float(text)
        if kind == "date":
            datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        hint = " Use YYYY-MM-DD." if kind == "date" else ""
        raise ValueError(f"{label} is not valid.{hint}")
    return text


# ---------------------------------------------------------------
# Add-new form
# ---------------------------------------------------------------
class Form(tk.Toplevel):
    def __init__(self, app, name, cfg, on_saved):
        super().__init__(app.root)
        self.title(f"Add new - {name}")
        self.cfg, self.on_saved = cfg, on_saved
        self.vars = {}
        self._busy = False
        self.transient(app.root)
        self.grab_set()
        now = datetime.now()
        r = 0

        if cfg.get("header"):
            ttk.Label(self, text=cfg["header"](), font=("Arial", 12, "bold")).grid(
                row=r, column=0, columnspan=2, pady=8)
            r += 1

        for col, label, kind, req, *extra in cfg["fields"]:
            ttk.Label(self, text=label + (" *" if req else "")).grid(
                row=r, column=0, padx=10, pady=4, sticky="e")
            var = tk.StringVar()
            if kind == "month":
                var.set(str(now.month))
                ttk.Combobox(self, textvariable=var, values=list(range(1, 13)),
                             width=8, state="readonly").grid(row=r, column=1, sticky="w")
            elif kind == "choice":
                choices = extra[0] if extra else []
                if callable(choices):
                    choices = choices()
                if isinstance(choices, str):
                    choices = [x[0] for x in query(choices)[1] if x[0]]
                ttk.Combobox(self, textvariable=var, values=choices, width=34).grid(
                    row=r, column=1, sticky="w", padx=4)
            else:
                if kind == "year":
                    var.set(str(now.year))
                elif kind == "date" and req:
                    var.set(today())
                ttk.Entry(self, textvariable=var, width=36).grid(
                    row=r, column=1, sticky="w", padx=4)
            self.vars[col] = var
            r += 1

        self.total_var = tk.StringVar()
        if cfg.get("total_label"):
            ttk.Label(self, textvariable=self.total_var, font=("Arial", 12, "bold")).grid(
                row=r, column=0, columnspan=2, pady=8)
            r += 1
        if cfg.get("note"):
            ttk.Label(self, text=cfg["note"], foreground="gray").grid(
                row=r, column=0, columnspan=2, pady=4)
            r += 1

        ttk.Button(self, text="Save", command=self.save).grid(
            row=r, column=0, columnspan=2, pady=12)
        ttk.Label(self, text="Saved records cannot be edited or deleted - they can only be voided "
                             "with a reason.", foreground="gray").grid(
            row=r + 1, column=0, columnspan=2, pady=(0, 10))

        for v in self.vars.values():
            v.trace_add("write", lambda *a: self.recalc())
        self.recalc()

    def num(self, col):
        try:
            return float(self.vars[col].get().strip() or 0)
        except ValueError:
            return 0.0

    def has(self, col):
        return bool(self.vars[col].get().strip())

    def recalc(self):
        if self._busy:
            return
        self._busy = True
        try:
            if self.cfg.get("total_label"):
                self.total_var.set(self.cfg["total_label"](self.num))
            if self.cfg.get("calc"):
                for col, val in self.cfg["calc"](self.num, self.has).items():
                    self.vars[col].set(fmtnum(val))
        finally:
            self._busy = False

    def save(self):
        cfg = self.cfg
        vals = {}
        try:
            for col, label, kind, req, *extra in cfg["fields"]:
                v = convert(kind, self.vars[col].get(), label, req)
                if v is None and cfg.get("zero_blank") and kind in ("int", "float"):
                    v = 0
                vals[col] = v
        except ValueError as e:
            messagebox.showerror("Please check", str(e), parent=self)
            return

        if cfg.get("validate"):
            err = cfg["validate"](vals)
            if err:
                messagebox.showerror("Cannot save", err, parent=self)
                return
        if cfg.get("auto"):
            vals.update(cfg["auto"](vals))

        if cfg.get("unique"):
            cols = cfg["unique"]
            cond = " AND ".join(f"{c}=?" for c in cols)
            if query(f"SELECT 1 FROM live_{cfg['table']} WHERE {cond}",
                     tuple(vals[c] for c in cols))[1]:
                messagebox.showwarning(
                    "Already exists",
                    "This entry already exists (" +
                    ", ".join(f"{c} = {vals[c]}" for c in cols) + ").\n"
                    "The old record was NOT changed.\n"
                    "If it was wrong, void it first (with a reason) and then add the correct one.",
                    parent=self)
                return

        vals["temple"] = STATE["temple"]
        cols = list(vals)
        query(f"INSERT INTO {cfg['table']} ({','.join(cols)}) "
              f"VALUES ({','.join('?' * len(cols))})", tuple(vals[c] for c in cols))
        if cfg.get("after_save"):
            cfg["after_save"](vals)
        messagebox.showinfo("Saved", "Record saved.", parent=self)
        self.destroy()
        self.on_saved()


# ---------------------------------------------------------------
# Void dialog: reason + password, then the record is hidden but kept forever
# ---------------------------------------------------------------
class VoidDialog(tk.Toplevel):
    def __init__(self, app, table, rid, summary, on_done):
        super().__init__(app.root)
        self.title("Void record")
        self.table, self.rid, self.on_done = table, rid, on_done
        self.transient(app.root)
        self.grab_set()
        ttk.Label(self, text="Voiding hides this record from all lists and reports.\n"
                             "It is permanently recorded for the main office, with your reason.",
                  foreground="#b00020").pack(padx=15, pady=(12, 6))
        ttk.Label(self, text=summary, justify="left").pack(padx=15, pady=6, anchor="w")
        ttk.Label(self, text="Reason for voiding * (at least 5 characters)").pack(padx=15, anchor="w")
        self.reason = tk.StringVar()
        ttk.Entry(self, textvariable=self.reason, width=55).pack(padx=15, pady=4)
        ttk.Label(self, text="Your password *").pack(padx=15, anchor="w")
        self.pw = tk.StringVar()
        ttk.Entry(self, textvariable=self.pw, show="*", width=30).pack(padx=15, pady=4, anchor="w")
        row = ttk.Frame(self)
        row.pack(pady=12)
        ttk.Button(row, text="Void this record", command=self.confirm).pack(side="left", padx=6)
        ttk.Button(row, text="Cancel", command=self.destroy).pack(side="left", padx=6)

    def confirm(self):
        reason = self.reason.get().strip()
        if len(reason) < 5:
            messagebox.showerror("Reason needed", "Please give a clear reason (at least 5 characters).",
                                 parent=self)
            return
        if check_password(self.pw.get()) != STATE["auth"]:
            messagebox.showerror("Wrong password", "The password is not correct.", parent=self)
            return
        void_record(self.table, self.rid, reason)
        messagebox.showinfo("Voided", "Record voided. It has been recorded for the main office.",
                            parent=self)
        self.destroy()
        self.on_done()


# ---------------------------------------------------------------
# One page per section
# ---------------------------------------------------------------
class Page(ttk.Frame):
    def __init__(self, app, name, cfg):
        super().__init__(app.container)
        self.app, self.name, self.cfg = app, name, cfg
        can_edit = STATE["role"] == "entry" and not cfg.get("readonly")

        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=10)
        back = app.go_home if cfg.get("back_home") else app.go_menu
        ttk.Button(top, text="< Back", command=back).pack(side="left")
        self.title_label = ttk.Label(top, text=name, font=("Arial", 16, "bold"))
        self.title_label.pack(side="left", padx=15)
        if can_edit:
            ttk.Button(top, text="+ Add new", command=self.add).pack(side="right")
            ttk.Button(top, text="Void selected", command=self.void).pack(side="right", padx=8)

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10)
        ttk.Label(bar, text="Search:").pack(side="left")
        self.search = tk.StringVar()
        ttk.Entry(bar, textvariable=self.search, width=30).pack(side="left", padx=6)
        self.search.trace_add("write", lambda *a: self.refresh())
        for label, func in cfg.get("extras", []):
            ttk.Button(bar, text=label,
                       command=lambda l=label, f=func: messagebox.showinfo(l, f())).pack(
                side="left", padx=6)
        self.count = ttk.Label(bar, text="")
        self.count.pack(side="right")

        holder = ttk.Frame(self)
        holder.pack(fill="both", expand=True, padx=10, pady=10)
        self.tree = ttk.Treeview(holder, show="headings")
        ys = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(holder, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        ys.pack(side="right", fill="y")
        xs.pack(side="bottom", fill="x")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self.details)
        ttk.Label(self, text="Double-click a row to see all its details.",
                  foreground="gray").pack(pady=(0, 6))

    def set_title(self):
        if self.cfg.get("back_home"):
            self.title_label.config(text=f"{self.name} (all temples)")
        else:
            self.title_label.config(text=f"{self.name}  -  {TEMPLES[STATE['temple']]['name']}")

    def source(self):
        return self.cfg.get("source") or f"live_{self.cfg['table']}"

    def add(self):
        Form(self.app, self.name, self.cfg, self.refresh)

    def void(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Select a record", "Click a record in the table first.")
            return
        cols = self.tree["columns"]
        vals = self.tree.item(sel[0], "values")
        summary = "\n".join(f"{c}: {v}" for c, v in list(zip(cols, vals))[:8])
        VoidDialog(self.app, self.cfg["table"], int(vals[0]), summary, self.refresh)

    def refresh(self):
        src = self.source()
        cols, _ = query(f"SELECT * FROM {src} LIMIT 0")
        if not self.cfg.get("readonly"):
            cols = [c for c in cols if c != "temple"]
        sql, params = f"SELECT {', '.join(cols)} FROM {src}", ()
        text = self.search.get().strip()
        if text:
            sql += " WHERE " + " OR ".join(f"CAST({c} AS TEXT) LIKE ?" for c in cols)
            params = tuple(f"%{text}%" for _ in cols)
        sql += f" ORDER BY {self.cfg['order']}"
        _, rows = query(sql, params)

        self.tree["columns"] = cols
        for c in cols:
            self.tree.heading(c, text=c.replace("_", " ").title())
            wide = c in ("remarks", "reason", "snapshot", "item", "guest_name")
            self.tree.column(c, width=220 if wide else 105, anchor="center")
        self.tree.column(cols[0], width=50)
        self.tree.delete(*self.tree.get_children())
        for row in rows:
            self.tree.insert("", "end", values=["" if v is None else v for v in row])
        self.count.config(text=f"{len(rows)} record(s)")

    def details(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        pairs = []
        for c, v in zip(self.tree["columns"], self.tree.item(item, "values")):
            if c == "snapshot":
                try:
                    for k, val in json.loads(v).items():
                        pairs.append((f"Original {k}", "" if val is None else val))
                    continue
                except ValueError:
                    pass
            pairs.append((c, v))
        win = tk.Toplevel(self.app.root)
        win.title(f"{self.name} - details")
        for i, (c, v) in enumerate(pairs):
            ttk.Label(win, text=c.replace("_", " ").title() + ":",
                      font=("Arial", 10, "bold")).grid(row=i, column=0, padx=10, pady=3, sticky="e")
            ttk.Label(win, text=str(v), wraplength=450, justify="left").grid(
                row=i, column=1, padx=10, pady=3, sticky="w")


# ---------------------------------------------------------------
# Monthly summary
# ---------------------------------------------------------------
def money(x):
    return f"Rs. {x:,.0f}"


def build_report(year, month):
    ym = f"{year}-{month:02d}"
    py, pm = (year - 1, 12) if month == 1 else (year, month - 1)
    pym = f"{py}-{pm:02d}"
    info = TEMPLES[STATE["temple"]]
    L = [f"{info['name']}, {info['place']}",
         f"MONTHLY SUMMARY - {datetime(year, month, 1).strftime('%B %Y')}", ""]

    sales = 0
    if info["food"]:
        n, b, l, d, sales = query(
            "SELECT COUNT(*), COALESCE(SUM(breakfast),0), COALESCE(SUM(lunch),0), "
            "COALESCE(SUM(dinner),0), COALESCE(SUM(total_price),0) FROM live_FoodCoupons "
            "WHERE strftime('%Y-%m', date)=?", (ym,))[1][0]
        L += ["FOOD COUPONS", f"  Days recorded : {n}",
              f"  Breakfast / Lunch / Dinner : {b:,} / {l:,} / {d:,}",
              f"  Coupon sales : {money(sales)}"]
        top = query("SELECT date, day, breakfast+lunch+dinner AS t FROM live_FoodCoupons "
                    "WHERE strftime('%Y-%m', date)=? ORDER BY t DESC LIMIT 1", (ym,))[1]
        if top:
            L.append(f"  Busiest day : {top[0][0]} ({top[0][1]}) - {top[0][2]:,} coupons")
        L.append("")

    bn, room_income = query("SELECT COUNT(*), COALESCE(SUM(total_amount),0) FROM live_Bookings "
                            "WHERE strftime('%Y-%m', check_in)=?", (ym,))[1][0]
    L += ["ROOM BOOKINGS", f"  Bookings : {bn}", f"  Room income : {money(room_income)}"]

    inc_rows = query("SELECT source, SUM(amount) FROM live_Income "
                     "WHERE strftime('%Y-%m', date)=? GROUP BY source ORDER BY 2 DESC", (ym,))[1]
    inc_total = sum(a for _, a in inc_rows)
    L += ["", "DONATIONS & OTHER INCOME", f"  Total : {money(inc_total)}"]
    L += [f"  {c:<26}{money(a):>14}" for c, a in inc_rows] or ["  No income recorded"]

    exp_total = query("SELECT COALESCE(SUM(amount),0) FROM live_Expenses "
                      "WHERE strftime('%Y-%m', date)=?", (ym,))[1][0][0]
    prev_total = query("SELECT COALESCE(SUM(amount),0) FROM live_Expenses "
                       "WHERE strftime('%Y-%m', date)=?", (pym,))[1][0][0]
    cats = query("SELECT category, SUM(amount) FROM live_Expenses "
                 "WHERE strftime('%Y-%m', date)=? GROUP BY category ORDER BY 2 DESC", (ym,))[1]
    change = ""
    if prev_total > 0:
        in_progress = (year, month) == (datetime.now().year, datetime.now().month)
        change = (f"   ({(exp_total - prev_total) / prev_total * 100:+.0f}% vs previous month"
                  f"{', month still in progress' if in_progress else ''})")
    L += ["", "EXPENSES", f"  Total : {money(exp_total)}{change}"]
    L += [f"  {c:<26}{money(a):>14}" for c, a in cats] or ["  No expenses recorded"]

    sal = query("SELECT total_amount, addition, total_deductions, hold_salary, net_payable "
                "FROM live_MonthlySalary WHERE month=? AND year=?", (month, year))[1]
    L += ["", "SALARY"]
    if sal:
        t, a, dd, h, net = sal[0]
        L += [f"  Total {money(t or 0)}   Addition {money(a or 0)}   Deductions {money(dd or 0)}",
              f"  Hold {money(h or 0)}   Net payable {money(net or 0)}"]
        salary_net = net or 0
    else:
        L.append("  Not recorded for this month")
        salary_net = 0

    progs = query("SELECT p.program_name, p.date, "
                  "(SELECT COALESCE(SUM(e.amount),0) FROM live_Expenses e "
                  " WHERE e.occasion = p.program_name), "
                  "(SELECT COALESCE(SUM(i.amount),0) FROM live_Income i "
                  " WHERE i.occasion = p.program_name) "
                  "FROM live_Programs p WHERE strftime('%Y-%m', p.date)=? ORDER BY p.date", (ym,))[1]
    L += ["", "PROGRAMS"]
    if progs:
        for nme, dt, ex, dn in progs:
            L.append(f"  {dt}  {nme}  (expenses {money(ex)}, donations {money(dn)}, "
                     f"net {money(dn - ex)})")
    else:
        L.append("  No program this month")

    income = sales + room_income + inc_total
    outgo = exp_total + salary_net
    L += ["", "POSITION (from recorded data)",
          f"  Income ({'coupons + ' if info['food'] else ''}rooms + donations/sales)".ljust(47) + f": {money(income)}",
          f"  Outgo (expenses + net salary)                : {money(outgo)}",
          f"  Balance                                      : {money(income - outgo)}",
          "", "Note: all figures come from the Income and Expenses sections;",
          "program lines add up entries linked to that program (Occasion field)."]
    return "\n".join(L), cats


class Summary(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.container)
        now = datetime.now()
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=10)
        ttk.Button(top, text="< Back", command=app.go_menu).pack(side="left")
        ttk.Label(top, text="Monthly Summary", font=("Arial", 16, "bold")).pack(side="left", padx=15)
        self.month = tk.StringVar(value=str(now.month))
        self.year = tk.StringVar(value=str(now.year))
        ttk.Combobox(top, textvariable=self.month, values=list(range(1, 13)),
                     width=4, state="readonly").pack(side="left", padx=(20, 4))
        ttk.Entry(top, textvariable=self.year, width=6).pack(side="left", padx=4)
        ttk.Button(top, text="Show", command=self.show).pack(side="left", padx=8)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=5)
        self.text = tk.Text(body, width=78, font=("Consolas", 10), state="disabled")
        self.text.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(body, width=380, bg="white", highlightthickness=1)
        self.canvas.pack(side="left", fill="y", padx=(10, 0))

    def refresh(self):
        self.show()

    def show(self):
        try:
            y, m = int(self.year.get()), int(self.month.get())
            text, cats = build_report(y, m)
        except ValueError:
            messagebox.showerror("Please check", "Enter a valid month and year.")
            return
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.text.config(state="disabled")

        c = self.canvas
        c.delete("all")
        c.create_text(10, 14, anchor="w", font=("Arial", 11, "bold"), text="Expenses by category")
        if cats:
            biggest = max(a for _, a in cats)
            for i, (cat, amt) in enumerate(cats):
                y0 = 40 + i * 34
                c.create_text(10, y0, anchor="w", font=("Arial", 9), text=cat)
                w = max(4, int(240 * amt / biggest))
                c.create_rectangle(10, y0 + 10, 10 + w, y0 + 24, fill="#d9822b", outline="")
                c.create_text(16 + w, y0 + 17, anchor="w", font=("Arial", 9), text=f"{amt:,.0f}")


# ---------------------------------------------------------------
# Expense summary: both temples combined under common headings
# (for example "Pooja Ingredients" = Jain pooja items + milk for abhishek + homa samagri)
# ---------------------------------------------------------------
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
BOTH_LABEL = "Both temples (combined)"
GROUP = "COALESCE(c.summary_group, e.category)"
FROM = "FROM all_Expenses e LEFT JOIN ExpenseCategories c ON c.name = e.category"


def scope_options():
    return [BOTH_LABEL] + [t["name"] for t in TEMPLES.values()]


def scope_code(label):
    for code, t in TEMPLES.items():
        if t["name"] == label:
            return code
    return None


def expense_grid(year, code=None):
    sql = f"SELECT {GROUP}, strftime('%m', e.date), SUM(e.amount) {FROM} " \
          "WHERE strftime('%Y', e.date)=?"
    params = [str(year)]
    if code:
        sql += " AND e.temple=?"
        params.append(code)
    data = {}
    for grp, mm, amt in query(sql + " GROUP BY 1, 2", tuple(params))[1]:
        data.setdefault(grp, [0.0] * 12)[int(mm) - 1] = amt
    return data


def expense_by_temple(year):
    data = {}
    for code, mm, amt in query("SELECT temple, strftime('%m', date), SUM(amount) FROM all_Expenses "
                               "WHERE strftime('%Y', date)=? GROUP BY 1, 2", (str(year),))[1]:
        data.setdefault(code, [0.0] * 12)[int(mm) - 1] = amt
    return data


def expense_compare(a, b, code=None):
    sql = (f"SELECT {GROUP}, "
           "SUM(CASE WHEN strftime('%Y-%m', e.date)=? THEN e.amount ELSE 0 END), "
           "SUM(CASE WHEN strftime('%Y-%m', e.date)=? THEN e.amount ELSE 0 END) "
           f"{FROM} WHERE strftime('%Y-%m', e.date) IN (?, ?)")
    params = [a, b, a, b]
    if code:
        sql += " AND e.temple=?"
        params.append(code)
    return query(sql + " GROUP BY 1 ORDER BY 3 DESC", tuple(params))[1]


class ExpenseSummary(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.container)
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=10)
        back = app.go_menu if STATE["home_temple"] else app.go_home
        ttk.Button(top, text="< Back", command=back).pack(side="left")
        ttk.Label(top, text="Expense Summary", font=("Arial", 16, "bold")).pack(side="left", padx=15)
        ttk.Label(top, text="Year:").pack(side="left", padx=(20, 4))
        self.year = tk.StringVar(value=str(datetime.now().year))
        ttk.Entry(top, textvariable=self.year, width=6).pack(side="left")
        ttk.Label(top, text="Show:").pack(side="left", padx=(16, 4))
        options = scope_options() if STATE["role"] == "viewer" else [TEMPLES[STATE["home_temple"]]["name"]]
        self.scope = tk.StringVar(value=options[0])
        ttk.Combobox(top, textvariable=self.scope, values=options, width=28,
                     state="readonly").pack(side="left")
        ttk.Button(top, text="Show", command=self.refresh).pack(side="left", padx=8)

        ttk.Label(self, text="Expenses by heading and month (Rs.). Both temples are grouped under common "
                             "headings, e.g. Pooja Ingredients.",
                  font=("Arial", 10, "bold")).pack(anchor="w", padx=12)
        cols = ["category"] + [m.lower() for m in MONTH_ABBR] + ["total"]
        self.grid_tree = ttk.Treeview(self, columns=cols, show="headings", height=10)
        self.grid_tree.heading("category", text="Heading")
        self.grid_tree.column("category", width=190, anchor="w")
        for m in MONTH_ABBR:
            self.grid_tree.heading(m.lower(), text=m)
            self.grid_tree.column(m.lower(), width=68, anchor="e")
        self.grid_tree.heading("total", text="Total")
        self.grid_tree.column("total", width=90, anchor="e")
        self.grid_tree.tag_configure("sum", font=("Arial", 10, "bold"), background="#eeeeee")
        self.grid_tree.tag_configure("sub", foreground="#555555")
        self.grid_tree.pack(fill="x", padx=10, pady=(2, 10))

        cmp_bar = ttk.Frame(self)
        cmp_bar.pack(fill="x", padx=10)
        ttk.Label(cmp_bar, text="Compare month", font=("Arial", 11, "bold")).pack(side="left")
        self.a = tk.StringVar()
        self.b = tk.StringVar()
        self.box_a = ttk.Combobox(cmp_bar, textvariable=self.a, width=10, state="readonly")
        self.box_b = ttk.Combobox(cmp_bar, textvariable=self.b, width=10, state="readonly")
        self.box_a.pack(side="left", padx=6)
        ttk.Label(cmp_bar, text="with").pack(side="left")
        self.box_b.pack(side="left", padx=6)
        ttk.Button(cmp_bar, text="Compare", command=self.show_compare).pack(side="left", padx=8)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=8)
        ccols = ("category", "a", "b", "diff", "pct")
        self.cmp_tree = ttk.Treeview(body, columns=ccols, show="headings", height=10)
        for c, w, anc in zip(ccols, (190, 90, 90, 90, 70), ("w", "e", "e", "e", "e")):
            self.cmp_tree.column(c, width=w, anchor=anc)
        self.cmp_tree.tag_configure("up", foreground="#b00020")
        self.cmp_tree.tag_configure("down", foreground="#1b7f3b")
        self.cmp_tree.tag_configure("sum", font=("Arial", 10, "bold"), background="#eeeeee")
        self.cmp_tree.pack(side="left", fill="y")
        self.canvas = tk.Canvas(body, bg="white", highlightthickness=1)
        self.canvas.pack(side="left", fill="both", expand=True, padx=(10, 0))
        ttk.Label(self, text="Red = spent more than the first month, green = spent less.",
                  foreground="gray").pack(pady=(0, 6))

    def refresh(self):
        code = scope_code(self.scope.get())
        months = [r[0] for r in query("SELECT DISTINCT strftime('%Y-%m', date) FROM all_Expenses "
                                      "WHERE (? IS NULL OR temple = ?) ORDER BY 1 DESC",
                                      (code, code))[1]]
        if self.a.get() not in months or self.b.get() not in months:
            self.a.set("")
            self.b.set("")
        self.box_a["values"] = months
        self.box_b["values"] = months
        if len(months) >= 2 and not (self.a.get() and self.b.get()):
            self.a.set(months[1])
            self.b.set(months[0])
        elif months and not self.a.get():
            self.a.set(months[0])
            self.b.set(months[0])
        self.show_grid()
        self.show_compare()

    def show_grid(self):
        try:
            year = int(self.year.get())
        except ValueError:
            messagebox.showerror("Please check", "Enter a valid year.")
            return
        code = scope_code(self.scope.get())
        data = expense_grid(year, code)
        self.grid_tree.delete(*self.grid_tree.get_children())
        col_tot = [0.0] * 12
        for cat, vals in sorted(data.items(), key=lambda kv: -sum(kv[1])):
            self.grid_tree.insert("", "end", values=[cat] + [f"{v:,.0f}" if v else "-" for v in vals]
                                  + [f"{sum(vals):,.0f}"])
            col_tot = [t + v for t, v in zip(col_tot, vals)]
        self.grid_tree.insert("", "end", tags=("sum",),
                              values=["TOTAL"] + [f"{v:,.0f}" if v else "-" for v in col_tot]
                              + [f"{sum(col_tot):,.0f}"])
        if code is None:
            by_temple = expense_by_temple(year)
            for tcode, info in TEMPLES.items():
                vals = by_temple.get(tcode, [0.0] * 12)
                self.grid_tree.insert("", "end", tags=("sub",),
                                      values=["   of which " + info["name"]]
                                      + [f"{v:,.0f}" if v else "-" for v in vals]
                                      + [f"{sum(vals):,.0f}"])

    def show_compare(self):
        a, b = self.a.get(), self.b.get()
        self.cmp_tree.delete(*self.cmp_tree.get_children())
        self.canvas.delete("all")
        if not a or not b:
            return
        for c, name in zip(("category", "a", "b", "diff", "pct"),
                           ("Heading", a, b, "Difference", "Change")):
            self.cmp_tree.heading(c, text=name)
        rows = expense_compare(a, b, scope_code(self.scope.get()))
        ta = tb = 0
        for cat, x, y in rows:
            ta, tb = ta + x, tb + y
            self.cmp_tree.insert("", "end", tags=("up" if y > x else "down" if y < x else "",),
                                 values=self.cmp_values(cat, x, y))
        self.cmp_tree.insert("", "end", tags=("sum",), values=self.cmp_values("TOTAL", ta, tb))

        c = self.canvas
        c.create_text(10, 14, anchor="w", font=("Arial", 11, "bold"), text=f"{a}  vs  {b}")
        c.create_rectangle(260, 8, 272, 20, fill="#4a7fc1", outline="")
        c.create_text(276, 14, anchor="w", font=("Arial", 9), text=a)
        c.create_rectangle(330, 8, 342, 20, fill="#d9822b", outline="")
        c.create_text(346, 14, anchor="w", font=("Arial", 9), text=b)
        if rows:
            biggest = max(max(x, y) for _, x, y in rows) or 1
            for i, (cat, x, y) in enumerate(rows):
                y0 = 40 + i * 36
                c.create_text(10, y0, anchor="w", font=("Arial", 9), text=cat)
                wa, wb = max(2, int(300 * x / biggest)), max(2, int(300 * y / biggest))
                c.create_rectangle(10, y0 + 8, 10 + wa, y0 + 17, fill="#4a7fc1", outline="")
                c.create_text(16 + wa, y0 + 12, anchor="w", font=("Arial", 8), text=f"{x:,.0f}")
                c.create_rectangle(10, y0 + 18, 10 + wb, y0 + 27, fill="#d9822b", outline="")
                c.create_text(16 + wb, y0 + 22, anchor="w", font=("Arial", 8), text=f"{y:,.0f}")

    @staticmethod
    def cmp_values(cat, x, y):
        diff = y - x
        pct = f"{diff / x * 100:+.0f}%" if x else ("new" if y else "-")
        return [cat, f"{x:,.0f}", f"{y:,.0f}", f"{diff:+,.0f}", pct]


# ---------------------------------------------------------------
# Login, home, app
# ---------------------------------------------------------------
class SetupDialog(tk.Toplevel):
    def __init__(self, root):
        super().__init__(root)
        self.title("First-time setup - create passwords")
        self.done = False
        self.transient(root)
        self.grab_set()
        ttk.Label(self, text="Create three passwords: one for each temple's data-entry person\n"
                             "and one for the main office (view only).\n"
                             "Keep them safe - they cannot be recovered.",
                  justify="center").grid(row=0, column=0, columnspan=2, padx=15, pady=12)
        self.fields = [("entry_T1", f"Data entry - {TEMPLES['T1']['name']}"),
                       ("entry_T2", f"Data entry - {TEMPLES['T2']['name']}"),
                       ("viewer", "Main office (view only)")]
        self.v = {}
        r = 1
        for role, label in self.fields:
            for suffix, text in (("1", label + " (min. 6 characters)"), ("2", "Confirm")):
                var = self.v[role + suffix] = tk.StringVar()
                ttk.Label(self, text=text).grid(row=r, column=0, padx=10, pady=3, sticky="e")
                ttk.Entry(self, textvariable=var, show="*", width=26).grid(row=r, column=1, padx=10)
                r += 1
        ttk.Button(self, text="Save passwords", command=self.save).grid(
            row=r, column=0, columnspan=2, pady=14)

    def save(self):
        roles = [f[0] for f in self.fields]
        pw = {r: self.v[r + "1"].get() for r in roles}
        if any(len(p) < 6 for p in pw.values()):
            messagebox.showerror("Too short", "Passwords need at least 6 characters.", parent=self)
        elif any(pw[r] != self.v[r + "2"].get() for r in roles):
            messagebox.showerror("Mismatch", "A password and its confirmation do not match.", parent=self)
        elif len(set(pw.values())) < 3:
            messagebox.showerror("Same password", "The three passwords must be different.", parent=self)
        else:
            for r in roles:
                set_password(r, pw[r])
            query("DELETE FROM Auth WHERE role='entry'")
            self.done = True
            self.destroy()


class Login(ttk.Frame):
    def __init__(self, root, on_success):
        super().__init__(root)
        self.root, self.on_success, self.tries = root, on_success, 0
        box = ttk.Frame(self)
        box.place(relx=0.5, rely=0.4, anchor="center")
        ttk.Label(box, text="Temple Management", font=("Arial", 26, "bold")).pack(pady=(0, 6))
        for t in TEMPLES.values():
            ttk.Label(box, text=f"{t['name']}, {t['place']}", font=("Arial", 11)).pack()
        ttk.Label(box, text="Please log in to continue", font=("Arial", 11)).pack(pady=(14, 18))
        self.pw = tk.StringVar()
        entry = ttk.Entry(box, textvariable=self.pw, show="*", width=30, font=("Arial", 13))
        entry.pack(pady=6)
        entry.focus_set()
        entry.bind("<Return>", lambda e: self.attempt())
        tk.Button(box, text="Log in", width=20, command=self.attempt).pack(pady=10)
        self.demo = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="Demo mode (sample data for presentation)",
                        variable=self.demo, command=self.hint).pack(pady=6)
        self.hint_label = ttk.Label(box, text="", foreground="#b36b00")
        self.hint_label.pack()

    def hint(self):
        self.hint_label.config(
            text=(f"Demo passwords:  {TEMPLES['T1']['name']} = demo123   |   "
                  f"{TEMPLES['T2']['name']} = demo456   |   Main office (view only) = view123")
            if self.demo.get() else "", wraplength=520, justify="center")

    def attempt(self):
        STATE["demo"] = self.demo.get()
        STATE["db"] = DEMO_DB if STATE["demo"] else REAL_DB
        if STATE["demo"]:
            if not os.path.exists(DEMO_DB):
                make_demo(DEMO_DB)
            else:
                init_db(DEMO_DB)
                if not auth_ready():
                    make_demo(DEMO_DB)      # older sample file: rebuild it
        else:
            init_db(STATE["db"])
            if not auth_ready():
                dlg = SetupDialog(self.root)
                self.root.wait_window(dlg)
                return
        role = check_password(self.pw.get())
        if role:
            STATE["auth"] = role
            if role == "viewer":
                STATE["role"], STATE["home_temple"] = "viewer", None
            else:
                STATE["role"], STATE["home_temple"] = "entry", role.split("_", 1)[1]
            self.on_success()
            return
        self.tries += 1
        if self.tries >= 5:
            messagebox.showerror("Locked", "Too many wrong attempts. The program will close.")
            self.root.destroy()
        else:
            messagebox.showerror("Wrong password", f"Incorrect password. Attempts left: {5 - self.tries}")
            self.pw.set("")


def backup_now():
    folder = os.path.join(BASE, "backups")
    os.makedirs(folder, exist_ok=True)
    stem = "temple_demo" if STATE["demo"] else "temple"
    path = os.path.join(folder, f"{stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    src, dst = sqlite3.connect(STATE["db"]), sqlite3.connect(path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return path


class App:
    def __init__(self, root, on_logout):
        self.root = root
        self.on_logout = on_logout
        self.container = ttk.Frame(root)
        self.container.pack(fill="both", expand=True)
        self.menu_frame = None
        self.current = None

        home = self.home_frame = ttk.Frame(self.container)
        self.top_bar(home, on_menu=False)
        ttk.Label(home, text="Temple Management", font=("Arial", 26, "bold")).pack(pady=(30, 4))
        ttk.Label(home, text=datetime.now().strftime("%A, %d %B %Y"),
                  font=("Arial", 12)).pack(pady=(0, 30))
        row = ttk.Frame(home)
        row.pack()
        for code, t in TEMPLES.items():
            tk.Button(row, text=f"{t['name']}\n{t['place']}\n({t['kind']})", font=("Arial", 14),
                      width=26, height=6, command=lambda c=code: self.open_temple(c)).pack(
                side="left", padx=15)
        tk.Button(row, text="Expense Summary\n(both temples combined)", font=("Arial", 14),
                  width=26, height=6, command=lambda: self.open("Expense Summary")).pack(
            side="left", padx=15)

        # Voided Records exists only for the main-office login
        self.pages = {n: Page(self, n, c) for n, c in SECTIONS.items()
                      if n != "Voided Records" or STATE["role"] == "viewer"}
        self.pages["Monthly Summary"] = Summary(self)
        self.pages["Expense Summary"] = ExpenseSummary(self)
        if STATE["home_temple"]:
            self.open_temple(STATE["home_temple"])      # data-entry staff see only their temple
        else:
            self.go_home()

    def top_bar(self, parent, on_menu):
        bar = ttk.Frame(parent)
        bar.pack(fill="x", padx=15, pady=10)
        if on_menu and STATE["role"] == "viewer":
            ttk.Button(bar, text="< Home", command=self.go_home).pack(side="left", padx=(0, 12))
        if STATE["role"] == "viewer":
            who = "Main office (view only)"
        else:
            who = f"Data entry - {TEMPLES[STATE['home_temple']]['name']}"
        ttk.Label(bar, text=f"Logged in: {who}").pack(side="left")
        if STATE["demo"]:
            tk.Label(bar, text="  DEMO MODE - sample data  ", bg="#f4b942",
                     font=("Arial", 10, "bold")).pack(side="left", padx=15)
        ttk.Button(bar, text="Log out", command=self.on_logout).pack(side="right")
        ttk.Button(bar, text="Backup now", command=self.backup).pack(side="right", padx=8)
        if STATE["role"] == "viewer" and not on_menu:
            ttk.Button(bar, text="Voided Records",
                       command=lambda: self.open("Voided Records")).pack(side="right")

    def backup(self):
        path = backup_now()
        messagebox.showinfo("Backup done", f"A copy of the data was saved to:\n{path}")

    def show(self, frame):
        if self.current:
            self.current.pack_forget()
        self.current = frame
        frame.pack(fill="both", expand=True)

    def go_home(self):
        self.show(self.home_frame)

    def go_menu(self):
        self.show(self.menu_frame)

    def open_temple(self, code):
        set_temple(code)
        info = TEMPLES[code]
        if self.menu_frame is not None:
            self.menu_frame.destroy()
        m = self.menu_frame = ttk.Frame(self.container)
        self.top_bar(m, on_menu=True)
        ttk.Label(m, text=info["name"], font=("Arial", 26, "bold")).pack(pady=(10, 0))
        ttk.Label(m, text=f"{info['place']}   |   {info['kind']}", font=("Arial", 13)).pack()
        ttk.Label(m, text=datetime.now().strftime("%A, %d %B %Y"), font=("Arial", 11)).pack(pady=(4, 20))
        grid = ttk.Frame(m)
        grid.pack()
        for i, name in enumerate(info["sections"]):
            tk.Button(grid, text=name, font=("Arial", 14), width=20, height=2,
                      command=lambda n=name: self.open(n)).grid(
                row=i // 3, column=i % 3, padx=12, pady=12)
        self.show(m)

    def open(self, name):
        page = self.pages[name]
        if isinstance(page, Page):
            page.search.set("")
            page.set_title()
        page.refresh()
        self.show(page)


# ---------------------------------------------------------------
# Sample data for the trustee presentation (separate file: temple_demo.db)
# ---------------------------------------------------------------
def make_demo_t2(path, rnd, start, end):
    """Sample data for Shri Suswani Mataji Dham (Hindu temple, no food service)."""
    conn = sqlite3.connect(path)
    rooms = [("201", "2BHK", 2500), ("301", "2BHK", 2500)]
    rooms += [(f"{f}0{n}", "4-bed with toilet", 1200) for f in (2, 3, 4) for n in range(2, 6)]
    conn.executemany("UPDATE Rooms SET rate_per_day=? WHERE room_no=? AND temple='T2'",
                     [(r[2], r[0]) for r in rooms])
    rate = {r[0]: r[2] for r in rooms}
    room_nos = [r[0] for r in rooms]

    staff = [("Pandit Ramakant", "Head Pujari", "2014-05-12", 30000),
             ("Mahesh", "Pujari", "2018-08-01", 20000),
             ("Geeta", "Pooja shop attendant", "2019-11-10", 14000),
             ("Lokesh", "Cleaner", "2020-02-17", 12000),
             ("Basavaraj", "Security", "2017-06-21", 14000),
             ("Rekha", "Clerk", "2016-09-05", 18000)]
    conn.executemany("INSERT INTO Staff (name, role, date_of_joining, base_salary, temple) "
                     "VALUES (?,?,?,?,'T2')", staff)
    conn.executemany(
        "INSERT INTO MonthlySalary (month, year, paid_leave, LOP, working_days, total_amount, "
        "hold_salary, total_deductions, addition, net_payable, remarks, temple) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,'T2')",
        [(8, 2026, 2, 0, 31, 108000, 0, 1500, 0, 106500, ""),
         (9, 2026, 1, 0, 30, 108000, 0, 0, 3000, 111000, "Festival bonus added")])

    names = ["Mahesh Agarwal", "Sunita Devi", "Prakash Rao", "Anita Sharma", "Gopal Reddy",
             "Meena Iyer", "Harish Patel", "Kavitha Nair", "Suresh Gupta", "Latha Menon",
             "Vijay Singh", "Padma Rao"]
    modes = ["Cash", "UPI", "UPI", "Card"]
    booked = [(["201", "202"], "2026-10-16", "2026-10-19")]
    bookings = [("Mahesh Agarwal", "9845098450", 8, "201, 202", "2026-10-16", "2026-10-19",
                 (2500 + 1200) * 3, "UPI", "Family group")]
    for _ in range(150):
        if len(bookings) >= 30:
            break
        s0 = start + timedelta(days=rnd.randint(0, 76))
        nights = rnd.choice([0, 1, 1, 2, 3, 4])
        ci, co = s0.isoformat(), (s0 + timedelta(days=nights)).isoformat()
        rs = sorted(rnd.sample(room_nos, rnd.choice([1, 1, 2, 2, 3])))
        if any(set(rs) & set(b[0]) and ci < eff_end(b[1], b[2]) and b[1] < eff_end(ci, co)
               for b in booked):
            continue
        booked.append((rs, ci, co))
        bookings.append((rnd.choice(names), f"98{rnd.randint(10000000, 99999999)}",
                         len(rs) * rnd.randint(2, 4), ", ".join(rs), ci, co,
                         sum(rate[r] for r in rs) * max(nights, 1), rnd.choice(modes),
                         "Same-day visit" if nights == 0 else ""))
    conn.executemany(
        "INSERT INTO Bookings (guest_name, phone, no_of_people, room_no, check_in, check_out, "
        "total_amount, payment_mode, remarks, temple) VALUES (?,?,?,?,?,?,?,?,?,'T2')", bookings)

    conn.executemany(
        "INSERT INTO Programs (program_name, organizer, date, place, expenses, donations_received, temple) "
        "VALUES (?,?,?,?,?,?,'T2')",
        [("Maha Shivratri Jagran", "Temple Committee", "2026-02-15", "Mahadev temple", 90000, 210000),
         ("Navratri Bhajan (9 nights)", "Mahila Bhajan Mandali", "2026-10-11", "Temple premises",
          75000, 180000)])

    # homa: every Sunday, amavasya, poornima and the 9 days of Navratri (sample dates)
    special = {"2026-08-12": "Amavasya homa", "2026-09-11": "Amavasya homa",
               "2026-10-10": "Amavasya homa", "2026-08-28": "Poornima homa",
               "2026-09-26": "Poornima homa"}
    homa_days, d = {}, start
    while d <= end:
        iso = d.isoformat()
        if d.weekday() == 6:
            homa_days[iso] = "Sunday homa"
        if iso in special:
            homa_days[iso] = special[iso]
        if date(2026, 10, 11) <= d <= date(2026, 10, 19):
            homa_days[iso] = "Navratri homa"
        d += timedelta(days=1)

    milk_rate = {8: 60, 9: 61, 10: 63}
    exp, income, d = [], [], start
    while d <= end:
        iso = d.isoformat()
        litres = rnd.choice([5, 6, 8, 10])
        exp.append((iso, "Abhishek Milk", "Milk (daily abhishek)", litres, "litres", milk_rate[d.month],
                    litres * milk_rate[d.month], "Nandini Dairy", "", "Daily abhishek", ""))
        if iso in homa_days:
            exp.append((iso, "Homa Samagri", "Homa samagri (ghee, havan material, wood)", None, "", None,
                        rnd.randint(2500, 5000), "Pooja Stores", f"H-{rnd.randint(1000, 9999)}",
                        "Homa", homa_days[iso]))
            if rnd.random() < 0.5:
                income.append((iso, "Abhishek / Homa seva", rnd.choice([1100, 2100, 5100]), "UPI",
                               "", "", "Homa", ""))
        if d.weekday() == 0:
            exp.append((iso, "Flowers & Decoration", "Flowers for the Mataji shrines (weekly)", None, "",
                        None, rnd.randint(1200, 2500), "Market flower stall", "", "", ""))
        if d.weekday() == 1:
            exp.append((iso, "Pooja Shop Stock", "Coconut, camphor, kumkum, agarbatti, cloth for the shop",
                        None, "", None, rnd.randint(15000, 30000), "Pooja Wholesale Traders",
                        f"P-{rnd.randint(1000, 9999)}", "", ""))
        if d.day % 10 == 5:
            item, unit, r, lo, hi = rnd.choice(
                [("Phenyl", "litres", 95, 10, 20), ("Handwash", "litres", 150, 5, 10),
                 ("Broom sticks", "pieces", 40, 10, 20), ("Garbage bags", "packet", 120, 5, 10)])
            q = rnd.randint(lo, hi)
            exp.append((iso, "Sanitation", item, q, unit, r, q * r, "City Hygiene Store",
                        f"S-{rnd.randint(1000, 9999)}", "", ""))
        if d.weekday() == 6:
            income.append((iso, "Hundi", rnd.randint(30000, 60000), "Cash",
                           f"H-{rnd.randint(1000, 9999)}", "", "", "Weekly hundi counting"))
        income.append((iso, "Donation (UPI/online)", rnd.randint(500, 3000), "UPI", "", "", "", ""))
        shop = rnd.randint(4000, 12000) * (1.5 if d.weekday() >= 5 else 1)
        income.append((iso, "Pooja shop sales", round(shop), "Cash", "", "", "", "Daily shop sales"))
        d += timedelta(days=1)

    for dt, cat, item, amount, vendor, occasion in [
            ("2026-02-14", "Flowers & Decoration", "Flowers and decoration for the function", 30000,
             "Local supplier", "Maha Shivratri Jagran"),
            ("2026-10-09", "Service & Repairs", "Sound system and lighting for the bhajan", 18000,
             "Sai Sound Services", "Navratri Bhajan (9 nights)"),
            ("2026-10-10", "Flowers & Decoration", "Flowers and decoration for Navratri", 26000,
             "Local supplier", "Navratri Bhajan (9 nights)"),
            ("2026-08-14", "Electrical", "Lighting repair, Mataji shrines", 4200, "Bright Electricals", ""),
            ("2026-09-22", "Electrical", "Inverter battery service", 6800, "Bright Electricals", ""),
            ("2026-08-30", "Plumbing", "Bathroom fittings, third floor rooms", 5400, "Shree Plumbing", ""),
            ("2026-10-05", "Plumbing", "Water pump repair", 7200, "Shree Plumbing", ""),
            ("2026-09-12", "Service & Repairs", "Annual service, water purifier", 3500, "AquaCare", ""),
            ("2026-10-08", "Service & Repairs", "Painting, shrine compound wall", 24000, "Colour Works", "")]:
        exp.append((dt, cat, item, None, "", None, amount, vendor, f"B-{rnd.randint(1000, 9999)}",
                    occasion, ""))
    for dt, amt, occasion in [("2026-02-15", 210000, "Maha Shivratri Jagran"),
                              ("2026-10-11", 180000, "Navratri Bhajan (9 nights)")]:
        income.append((dt, "Donation (cash)", amt, "Cash", f"D-{rnd.randint(1000, 9999)}", "", occasion,
                       "Collected during the function"))

    conn.executemany(
        "INSERT INTO Expenses (date, category, item, quantity, unit, rate, amount, vendor, bill_no, "
        "occasion, remarks, temple) VALUES (?,?,?,?,?,?,?,?,?,?,?,'T2')", exp)
    conn.executemany(
        "INSERT INTO Income (date, source, amount, payment_mode, receipt_no, donor, occasion, remarks, "
        "temple) VALUES (?,?,?,?,?,?,?,?,'T2')", income)
    conn.commit()
    conn.close()


def make_demo(path):
    prev = STATE["db"]
    STATE["db"] = path
    try:
        if os.path.exists(path):
            os.remove(path)
        init_db(path)
        set_password("entry_T1", "demo123")
        set_password("entry_T2", "demo456")
        set_password("viewer", "view123")
        rnd = random.Random(7)
        conn = sqlite3.connect(path)

        rooms = [(str(n), "Non-AC" if n <= 104 else "AC" if n <= 108 else "Dormitory",
                  600 if n <= 104 else 1200 if n <= 108 else 250) for n in range(101, 111)]
        conn.executemany("INSERT INTO Rooms (room_no, room_type, rate_per_day) VALUES (?,?,?)", rooms)
        rate = {r[0]: r[2] for r in rooms}

        staff = [("Suresh Babu", "Head Pujari", "2012-04-10", 32000),
                 ("Narayana Sharma", "Pujari", "2015-06-01", 24000),
                 ("Lakshmi", "Cook", "2018-01-15", 16000),
                 ("Mohan", "Cook", "2019-03-20", 15000),
                 ("Raju", "Cleaner", "2020-07-01", 12000),
                 ("Shanta", "Cleaner", "2021-02-11", 12000),
                 ("Venkatesh", "Security", "2017-09-05", 14000),
                 ("Anand Kumar", "Clerk", "2016-11-23", 20000)]
        conn.executemany("INSERT INTO Staff (name, role, date_of_joining, base_salary) VALUES (?,?,?,?)", staff)

        conn.executemany(
            "INSERT INTO MonthlySalary (month, year, paid_leave, LOP, working_days, total_amount, "
            "hold_salary, total_deductions, addition, net_payable, remarks) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(8, 2026, 3, 1, 31, 145000, 0, 2500, 0, 142500, ""),
             (9, 2026, 2, 0, 30, 145000, 5000, 1800, 8000, 146200,
              "Festival bonus added; 5000 held for one worker")])

        # daily coupons: busier on weekends, a few festival spikes
        start, end = date(2026, 8, 1), date(2026, 10, 16)
        food, d = [], start
        while d <= end:
            mult = 1.5 if d.weekday() >= 5 else 1.0
            note = ""
            if rnd.random() < 0.06:
                mult *= 2
                note = "Parva day"
            b, l, di = (int(rnd.randint(lo, hi) * mult)
                        for lo, hi in ((30, 60), (60, 120), (40, 80)))
            food.append((d.isoformat(), d.strftime("%A"), b, l, di,
                         b * BREAKFAST_RATE + l * LUNCH_RATE + di * DINNER_RATE, note))
            d += timedelta(days=1)
        conn.executemany("INSERT INTO FoodCoupons (date, day, breakfast, lunch, dinner, total_price, remarks) "
                         "VALUES (?,?,?,?,?,?,?)", food)

        # bookings (a group is occupying rooms 102 and 103 right now)
        names = ["Ramesh Jain", "Sunita Shah", "Prakash Mehta", "Anita Doshi", "Gopal Kothari",
                 "Meena Gandhi", "Harish Sanghvi", "Kavita Bhandari", "Suresh Oswal", "Lata Chopra",
                 "Vijay Jain", "Padma Shah", "Ravi Jain", "Sarita Mehta", "Kiran Shah"]
        modes = ["Cash", "UPI", "UPI", "Card"]
        booked = [(["102", "103"], "2026-10-16", "2026-10-19")]
        bookings = [("Ramesh Jain", "9848012345", 8, "102, 103", "2026-10-16", "2026-10-19",
                     2 * 600 * 3, "UPI", "Group from Hyderabad")]
        for _ in range(120):
            if len(bookings) >= 36:
                break
            s = start + timedelta(days=rnd.randint(0, 76))
            nights = rnd.choice([0, 1, 1, 2, 3, 4])
            ci, co = s.isoformat(), (s + timedelta(days=nights)).isoformat()
            rs = sorted(str(n) for n in rnd.sample(range(101, 111), rnd.choice([1, 1, 1, 2, 2, 3, 4])))
            if any(set(rs) & set(b[0]) and ci < eff_end(b[1], b[2]) and b[1] < eff_end(ci, co)
                   for b in booked):
                continue
            booked.append((rs, ci, co))
            bookings.append((rnd.choice(names), f"98{rnd.randint(10000000, 99999999)}",
                             len(rs) * rnd.randint(2, 4), ", ".join(rs), ci, co,
                             sum(rate[r] for r in rs) * max(nights, 1), rnd.choice(modes),
                             "Same-day visit" if nights == 0 else ""))
        conn.executemany(
            "INSERT INTO Bookings (guest_name, phone, no_of_people, room_no, check_in, check_out, "
            "total_amount, payment_mode, remarks) VALUES (?,?,?,?,?,?,?,?,?)", bookings)

        programs = [("Mahavir Jayanti", "Jain Sangh Trust", "2026-03-31", "Temple premises", 110000, 260000),
                    ("Siddhachakra Mahapujan", "Jain Sangh Trust", "2026-08-23", "Main hall", 42000, 65000),
                    ("Paryushan Parva Begins", "Jain Sangh Trust", "2026-09-08", "Temple premises", 95000, 180000),
                    ("Samvatsari Pratikraman", "Jain Sangh Trust", "2026-09-15", "Main hall", 68000, 120000),
                    ("Swami Vatsalya (community meal)", "Mahila Mandal", "2026-09-20", "Dining hall", 52000, 90000),
                    ("Dwajarohan (temple flag change)", "Jain Sangh Trust", "2026-10-04", "Temple premises", 60000, 140000),
                    ("Shanti Snatra Pujan", "Yuvak Mandal", "2026-10-11", "Temple premises", 85000, 150000)]
        conn.executemany("INSERT INTO Programs (program_name, organizer, date, place, expenses, "
                         "donations_received) VALUES (?,?,?,?,?,?)", programs)

        # income: weekly hundi counting, online donations, seva tickets, function donations
        income, d = [], start
        while d <= end:
            if d.weekday() == 6:
                income.append((d.isoformat(), "Hundi", rnd.randint(40000, 80000), "Cash",
                               f"H-{rnd.randint(1000, 9999)}", "", "", "Weekly hundi counting"))
            income.append((d.isoformat(), "Donation (UPI/online)", rnd.randint(1000, 4000),
                           "UPI", "", "", "", ""))
            tickets = rnd.randint(2000, 6000) * (1.5 if d.weekday() >= 5 else 1)
            income.append((d.isoformat(), "Pooja / Seva tickets", round(tickets), "Cash",
                           "", "", "", ""))
            d += timedelta(days=1)
        for p in programs:
            income.append((p[2], "Donation (cash)", p[5], "Cash", f"D-{rnd.randint(1000, 9999)}",
                           "", p[0], "Collected during the function"))
        for dt, amt in [("2026-09-10", 85000), ("2026-09-15", 125000)]:
            income.append((dt, "Boli / Chadhava", amt, "Cash", f"B-{rnd.randint(1000, 9999)}",
                           "", "", "Paryushan boli"))
        conn.executemany("INSERT INTO Income (date, source, amount, payment_mode, receipt_no, donor, "
                         "occasion, remarks) VALUES (?,?,?,?,?,?,?,?)", income)

        # expenses
        exp = []
        diesel_rate = {8: 90.5, 9: 92.0, 10: 94.5}
        d = start
        while d <= end:
            if rnd.random() < 0.12:
                litres = rnd.choice([20, 30, 40, 50, 60])
                exp.append((d.isoformat(), "Fuel & Generator", "Diesel", litres, "litres",
                            diesel_rate[d.month], round(litres * diesel_rate[d.month]),
                            "Sri Fuels", f"F-{rnd.randint(1000, 9999)}", "",
                            f"Power cut about {rnd.randint(2, 7)} hours"))
            if d.weekday() in (0, 3):
                exp.append((d.isoformat(), "Kitchen & Groceries", "Jain groceries (no onion/garlic)", None, "", None,
                            rnd.randint(35000, 60000), "Balaji Traders", f"K-{rnd.randint(1000, 9999)}", "", ""))
            if d.weekday() == 0:
                exp.append((d.isoformat(), "Flowers & Decoration", "Daily flowers (weekly)", None, "", None,
                            rnd.randint(1500, 3200), "Market flower stall", "", "", ""))
            if d.day % 10 == 5:
                item, unit, r, lo, hi = rnd.choice(
                    [("Phenyl", "litres", 95, 10, 20), ("Handwash", "litres", 150, 5, 10),
                     ("Broom sticks", "pieces", 40, 10, 20), ("Toilet cleaner", "litres", 180, 5, 10),
                     ("Garbage bags", "packet", 120, 5, 10)])
                q = rnd.randint(lo, hi)
                exp.append((d.isoformat(), "Sanitation", item, q, unit, r, q * r,
                            "City Hygiene Store", f"S-{rnd.randint(1000, 9999)}", "", ""))
            d += timedelta(days=1)
        for name, dt, cat, item, amount in [
                ("Mahavir Jayanti", "2026-03-30", "Flowers & Decoration",
                 "Flowers and decoration for the function", 32000),
                ("Dwajarohan (temple flag change)", "2026-10-03", "Pooja Items",
                 "New flag cloth, pole fittings and pooja material", 15000),
                ("Siddhachakra Mahapujan", "2026-08-22", "Flowers & Decoration",
                 "Flowers and decoration for the function", 9000),
                ("Paryushan Parva Begins", "2026-09-07", "Flowers & Decoration",
                 "Flowers and decoration for the function", 24000),
                ("Samvatsari Pratikraman", "2026-09-14", "Flowers & Decoration",
                 "Flowers and decoration for the function", 18500),
                ("Swami Vatsalya (community meal)", "2026-09-19", "Kitchen & Groceries",
                 "Special groceries for the community meal", 38000),
                ("Shanti Snatra Pujan", "2026-10-10", "Flowers & Decoration",
                 "Flowers and decoration for the function", 21000)]:
            exp.append((dt, cat, item, None, "", None, amount, "Local supplier",
                        f"V-{rnd.randint(1000, 9999)}", name, "Large order for the function"))
        for dt, cat, item, amount, vendor in [
                ("2026-08-12", "Plumbing", "Tap and pipe fittings", 3400, "Shree Plumbing"),
                ("2026-09-08", "Plumbing", "Drain cleaning", 2600, "Shree Plumbing"),
                ("2026-10-02", "Plumbing", "Water tank valve repair", 5200, "Shree Plumbing"),
                ("2026-08-19", "Electrical", "LED bulbs (20)", 5000, "Bright Electricals"),
                ("2026-09-18", "Electrical", "Wiring repair, main hall", 7800, "Bright Electricals"),
                ("2026-10-06", "Electrical", "Fan repair and capacitors", 3100, "Bright Electricals"),
                ("2026-09-25", "Service & Repairs", "Wall painting, entrance", 28000, "Colour Works"),
                ("2026-08-28", "Pooja Items", "Kesar, chandan, vasakshep, dhoop", 6500, "Pooja Stores")]:
            exp.append((dt, cat, item, None, "", None, amount, vendor,
                        f"B-{rnd.randint(1000, 9999)}", "", ""))
        conn.executemany(
            "INSERT INTO Expenses (date, category, item, quantity, unit, rate, amount, vendor, "
            "bill_no, occasion, remarks) VALUES (?,?,?,?,?,?,?,?,?,?,?)", exp)
        conn.commit()
        conn.close()

        make_demo_t2(path, rnd, start, end)

        # voided entries in both temples, so the trail is visible in the demo
        STATE["role"] = "entry"
        for temple, cat, item, amount, vendor, reason, remark in [
                ("T1", "Fuel & Generator", "Diesel", 36800, "Sri Fuels",
                 "Amount typed wrongly (extra zero); correct entry added again", "Typo"),
                ("T1", "Sanitation", "Phenyl", 1900, "City Hygiene Store",
                 "Duplicate entry - same bill entered twice", ""),
                ("T2", "Abhishek Milk", "Milk (daily abhishek)", 6200, "Nandini Dairy",
                 "Wrong amount entered; correct entry added again", "Typo")]:
            STATE["auth"] = f"entry_{temple}"
            query("INSERT INTO Expenses (date, category, item, amount, vendor, remarks, temple) "
                  "VALUES (?,?,?,?,?,?,?)", ("2026-10-09", cat, item, amount, vendor, remark, temple))
            rid = query("SELECT MAX(id) FROM Expenses")[1][0][0]
            void_record("Expenses", rid, reason)
        STATE["role"] = STATE["auth"] = None
        set_temple("T1")
    finally:
        STATE["db"] = prev


def main():
    root = tk.Tk()
    root.title("Temple Management")
    root.geometry("1150x720")

    def clear():
        for w in root.winfo_children():
            w.destroy()

    def show_login():
        clear()
        STATE["role"] = STATE["auth"] = STATE["home_temple"] = None
        Login(root, start).pack(fill="both", expand=True)

    def start():
        clear()
        App(root, show_login)

    show_login()
    root.mainloop()


if __name__ == "__main__":
    main()
