import os
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

# Always use the temple.db that sits next to this file
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temple.db")

# Coupon prices (Rs.). Old records keep the total saved at the time.
BREAKFAST_RATE = 120
LUNCH_RATE = 150
DINNER_RATE = 150


def query(sql, params=()):
    conn = sqlite3.connect(DB)
    try:
        cur = conn.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall() if cur.description else []
        conn.commit()
        return cols, rows
    finally:
        conn.close()


def today():
    return datetime.now().strftime("%Y-%m-%d")


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
# What each section stores and shows
# field = (column, label, kind, required)
# ---------------------------------------------------------------
def food_auto(v):
    now = datetime.now()
    b, l, d = (v.get(k) or 0 for k in ("breakfast", "lunch", "dinner"))
    return {"date": now.strftime("%Y-%m-%d"), "day": now.strftime("%A"),
            "total_price": b * BREAKFAST_RATE + l * LUNCH_RATE + d * DINNER_RATE}


SECTIONS = {
    "Staff": {
        "table": "Staff", "order": "staff_id DESC",
        "fields": [("name", "Name", "text", True),
                   ("role", "Role", "text", False),
                   ("date_of_joining", "Date of joining (YYYY-MM-DD)", "date", False),
                   ("base_salary", "Base salary", "float", False)],
        "defaults": {"active": 1},
    },
    "Salary": {
        "table": "MonthlySalary", "order": "year DESC, month DESC",
        "salary": True,
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
    "Food Coupons": {
        "table": "FoodCoupons", "order": "date DESC",
        "food": True, "zero_blank": True, "auto": food_auto,
        "header": lambda: f"Today: {today()}  ({datetime.now().strftime('%A')})",
        "fields": [("breakfast", "Breakfast coupons", "int", False),
                   ("lunch", "Lunch coupons", "int", False),
                   ("dinner", "Dinner coupons", "int", False),
                   ("remarks", "Remarks", "text", False)],
        "extras": [
            ("Busiest days (top 5)",
             "SELECT date, day, breakfast+lunch+dinner AS t FROM FoodCoupons ORDER BY t DESC LIMIT 5",
             lambda r: f"{r[0]}  ({r[1]}) : {r[2]} coupons"),
            ("Average by weekday",
             "SELECT day, ROUND(AVG(breakfast+lunch+dinner),1) AS a FROM FoodCoupons GROUP BY day ORDER BY a DESC",
             lambda r: f"{r[0]} : {r[1]} coupons per day"),
        ],
    },
    "Room Bookings": {
        "table": "Bookings", "order": "booking_id DESC",
        "fields": [("guest_name", "Guest name", "text", True),
                   ("phone", "Phone", "text", False),
                   ("no_of_people", "Number of people", "int", False),
                   ("room_no", "Room no(s) - e.g. 101, 102", "text", True),
                   ("check_in", "Check-in (YYYY-MM-DD)", "date", True),
                   ("check_out", "Check-out (YYYY-MM-DD)", "date", False),
                   ("total_amount", "Total amount", "float", False),
                   ("remarks", "Remarks", "text", False)],
    },
    "Programs": {
        "table": "Programs", "order": "program_id DESC",
        "fields": [("program_name", "Program name", "text", True),
                   ("organizer", "Organizer", "text", False),
                   ("date", "Date (YYYY-MM-DD)", "date", True),
                   ("place", "Place", "text", False),
                   ("expenses", "Expenses", "float", False),
                   ("donations_received", "Donations received", "float", False)],
    },
}


# ---------------------------------------------------------------
# Add-new form
# ---------------------------------------------------------------
class Form(tk.Toplevel):
    def __init__(self, app, name, cfg, on_saved):
        super().__init__(app.root)
        self.title(f"Add new - {name}")
        self.cfg, self.on_saved = cfg, on_saved
        self.vars = {}
        self.transient(app.root)
        self.grab_set()
        now = datetime.now()
        r = 0

        if cfg.get("header"):
            ttk.Label(self, text=cfg["header"](), font=("Arial", 12, "bold")).grid(
                row=r, column=0, columnspan=2, pady=8)
            r += 1

        for col, label, kind, req in cfg["fields"]:
            ttk.Label(self, text=label + (" *" if req else "")).grid(
                row=r, column=0, padx=10, pady=4, sticky="e")
            var = tk.StringVar()
            if kind == "month":
                var.set(str(now.month))
                ttk.Combobox(self, textvariable=var, values=list(range(1, 13)),
                             width=8, state="readonly").grid(row=r, column=1, sticky="w")
            else:
                if kind == "year":
                    var.set(str(now.year))
                elif kind == "date" and req:
                    var.set(today())
                ttk.Entry(self, textvariable=var, width=32).grid(row=r, column=1, sticky="w", padx=4)
            self.vars[col] = var
            r += 1

        self.total_var = tk.StringVar()
        if cfg.get("food"):
            ttk.Label(self, textvariable=self.total_var, font=("Arial", 12, "bold")).grid(
                row=r, column=0, columnspan=2, pady=8)
            r += 1
        if cfg.get("salary"):
            ttk.Label(self, text="Net payable is filled in as: total + addition - deductions - hold.\n"
                                 "You can change it if needed.",
                      foreground="gray").grid(row=r, column=0, columnspan=2, pady=4)
            r += 1

        ttk.Button(self, text="Save", command=self.save).grid(row=r, column=0, columnspan=2, pady=12)

        for v in self.vars.values():
            v.trace_add("write", lambda *a: self.recalc())
        self.recalc()

    def num(self, col):
        try:
            return float(self.vars[col].get().strip() or 0)
        except ValueError:
            return 0.0

    def recalc(self):
        if self.cfg.get("food"):
            total = (self.num("breakfast") * BREAKFAST_RATE + self.num("lunch") * LUNCH_RATE
                     + self.num("dinner") * DINNER_RATE)
            self.total_var.set(f"Total: Rs. {total:,.0f}")
        if self.cfg.get("salary") and self.vars["total_amount"].get().strip():
            net = (self.num("total_amount") + self.num("addition")
                   - self.num("total_deductions") - self.num("hold_salary"))
            self.vars["net_payable"].set(f"{net:g}")

    def save(self):
        vals = {}
        try:
            for col, label, kind, req in self.cfg["fields"]:
                v = convert(kind, self.vars[col].get(), label, req)
                if v is None and self.cfg.get("zero_blank") and kind in ("int", "float"):
                    v = 0
                vals[col] = v
            if self.cfg.get("salary") and not 1 <= vals["month"] <= 12:
                raise ValueError("Month must be between 1 and 12.")
        except ValueError as e:
            messagebox.showerror("Please check", str(e), parent=self)
            return

        vals.update(self.cfg.get("defaults", {}))
        if self.cfg.get("auto"):
            vals.update(self.cfg["auto"](vals))

        cols = list(vals)
        sql = (f"INSERT INTO {self.cfg['table']} ({','.join(cols)}) "
               f"VALUES ({','.join('?' * len(cols))})")
        try:
            query(sql, tuple(vals[c] for c in cols))
        except sqlite3.IntegrityError:
            messagebox.showwarning("Already exists",
                                   "A record for this date / month already exists.\n"
                                   "The old record was NOT changed.", parent=self)
            return
        messagebox.showinfo("Saved", "Record saved.", parent=self)
        self.destroy()
        self.on_saved()


# ---------------------------------------------------------------
# One page per section: search + table of stored records
# ---------------------------------------------------------------
class Page(ttk.Frame):
    def __init__(self, app, name, cfg):
        super().__init__(app.container)
        self.app, self.name, self.cfg = app, name, cfg

        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=10)
        ttk.Button(top, text="< Home", command=app.go_home).pack(side="left")
        ttk.Label(top, text=name, font=("Arial", 16, "bold")).pack(side="left", padx=15)
        ttk.Button(top, text="+ Add new", command=self.add).pack(side="right")

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10)
        ttk.Label(bar, text="Search:").pack(side="left")
        self.search = tk.StringVar()
        ttk.Entry(bar, textvariable=self.search, width=30).pack(side="left", padx=6)
        self.search.trace_add("write", lambda *a: self.refresh())
        for label, sql, fmt in cfg.get("extras", []):
            ttk.Button(bar, text=label,
                       command=lambda l=label, s=sql, f=fmt: self.extra(l, s, f)).pack(side="left", padx=6)
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

    def add(self):
        Form(self.app, self.name, self.cfg, self.refresh)

    def refresh(self):
        cols, _ = query(f"SELECT * FROM {self.cfg['table']} LIMIT 0")
        sql = f"SELECT * FROM {self.cfg['table']}"
        params = ()
        text = self.search.get().strip()
        if text:
            sql += " WHERE " + " OR ".join(f"CAST({c} AS TEXT) LIKE ?" for c in cols)
            params = tuple(f"%{text}%" for _ in cols)
        sql += f" ORDER BY {self.cfg['order']}"
        _, rows = query(sql, params)

        self.tree["columns"] = cols
        for c in cols:
            self.tree.heading(c, text=c.replace("_", " ").title())
            self.tree.column(c, width=110, anchor="center")
        self.tree.delete(*self.tree.get_children())
        for row in rows:
            self.tree.insert("", "end", values=["" if v is None else v for v in row])
        self.count.config(text=f"{len(rows)} record(s)")

    def details(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        cols = self.tree["columns"]
        vals = self.tree.item(item, "values")
        win = tk.Toplevel(self.app.root)
        win.title(f"{self.name} - details")
        for i, (c, v) in enumerate(zip(cols, vals)):
            ttk.Label(win, text=c.replace("_", " ").title() + ":",
                      font=("Arial", 10, "bold")).grid(row=i, column=0, padx=10, pady=3, sticky="e")
            ttk.Label(win, text=v).grid(row=i, column=1, padx=10, pady=3, sticky="w")

    def extra(self, label, sql, fmt):
        _, rows = query(sql)
        if not rows:
            messagebox.showinfo(label, "No data yet.")
        else:
            messagebox.showinfo(label, "\n".join(fmt(r) for r in rows))


# ---------------------------------------------------------------
# Home page
# ---------------------------------------------------------------
class App:
    def __init__(self, root):
        self.root = root
        root.title("Temple Management")
        root.geometry("1000x640")
        self.container = ttk.Frame(root)
        self.container.pack(fill="both", expand=True)

        self.home_frame = ttk.Frame(self.container)
        ttk.Label(self.home_frame, text="Temple Management",
                  font=("Arial", 26, "bold")).pack(pady=(50, 5))
        ttk.Label(self.home_frame, text=datetime.now().strftime("%A, %d %B %Y"),
                  font=("Arial", 12)).pack(pady=(0, 30))
        grid = ttk.Frame(self.home_frame)
        grid.pack()
        for i, name in enumerate(SECTIONS):
            tk.Button(grid, text=name, font=("Arial", 15), width=20, height=3,
                      command=lambda n=name: self.open(n)).grid(
                row=i // 2, column=i % 2, padx=15, pady=15)

        self.pages = {n: Page(self, n, c) for n, c in SECTIONS.items()}
        self.current = None
        self.go_home()

    def show(self, frame):
        if self.current:
            self.current.pack_forget()
        self.current = frame
        frame.pack(fill="both", expand=True)

    def go_home(self):
        self.show(self.home_frame)

    def open(self, name):
        page = self.pages[name]
        page.search.set("")
        page.refresh()
        self.show(page)


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
