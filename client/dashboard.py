import os
import subprocess
import sys
import tempfile
import textwrap
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

from api import ApiError
from windows import PasswordRequestsWindow, UsersWindow, run_in_background

WINDOW_WIDTH = 1150
WINDOW_HEIGHT = 640

HEADER_BG = "#2b3a55"
HEADER_BTN_BG = "#3d4f73"

# Category -> subcategories (used by the dropdowns). You can still type new ones.
CATEGORY_TREE = {
    "Structural & Track Systems": ["Panels", "Track Components", "Wall Guides & Angles"],
    "Mechanisms & Hardware": ["Mechanisms", "Handles & Operating Gear", "Rollers", "Locking & Sealing Components"],
    "Fasteners & Fixings": [
        "Bolts", "Screws (Metal & Wood)", "Rivets & Pins",
        "Washers & Nuts", "Anchors (Plastic)", "Knots / Nuts (G.I)",
    ],
    "Sealants, Insulation & Finishing": ["Insulation", "Seals & Gaskets", "Boards & Sheets"],
    "Tools & Consumables": ["General"],
}
ID_PREFIXES = {
    "Structural & Track Systems": "STR",
    "Mechanisms & Hardware": "MEC",
    "Fasteners & Fixings": "FAS",
    "Sealants, Insulation & Finishing": "SEA",
    "Tools & Consumables": "TOL",
}
UNITS = ["pcs", "ft", "m", "kg", "sheet", "roll", "box", "set"]

STATUS_FILTERS = ["All statuses", "In Stock", "Out of Stock"]
ALL_CATEGORIES = "All categories"

# Live clock format, e.g. "Monday, October 19, 2026   03:45:12 PM"
# For 24-hour time use "%A, %B %d, %Y   %H:%M:%S"
CLOCK_FORMAT = "%A, %B %d, %Y   %I:%M:%S %p"


def stock_status(quantity: int) -> str:
    return "Out of Stock" if quantity <= 0 else "In Stock"


def center_over(win, parent):
    """Place a popup in the middle of its parent window."""
    win.update_idletasks()
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    x = parent.winfo_x() + (parent.winfo_width() - w) // 2
    y = parent.winfo_y() + (parent.winfo_height() - h) // 2
    win.geometry(f"+{max(x, 0)}+{max(y, 0)}")


def send_to_printer(text: str):
    """Send plain text straight to the system's default printer (no browser involved)."""
    windows = sys.platform.startswith("win")
    fd, path = tempfile.mkstemp(suffix=".txt", prefix="inventory_report_")
    with os.fdopen(fd, "w", encoding="utf-8-sig" if windows else "utf-8") as f:
        f.write(text)

    if windows:
        os.startfile(path, "print")  # uses the printing action of the default .txt program
    else:
        subprocess.run(["lp", path], check=True)  # CUPS (macOS / Linux)


class ItemForm(tk.Toplevel):
    """Popup data entry form used for both Add and Edit."""

    def __init__(self, app, item_id=None):
        super().__init__(app)
        self.app = app
        self.editing_id = item_id

        self.title("Edit Item" if item_id else "Add Item")
        self.resizable(False, False)
        self.transient(app)

        self.id_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.category_var = tk.StringVar()
        self.sub_var = tk.StringVar()
        self.unit_var = tk.StringVar(value="pcs")
        self.qty_var = tk.StringVar(value="0")
        self.price_var = tk.StringVar()
        self.deduct_var = tk.StringVar(value="0")

        body = ttk.Frame(self, padding=20)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        ttk.Label(
            body, text="Edit Item" if item_id else "Add Item", font=("Segoe UI", 14, "bold")
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        self.id_entry = ttk.Entry(body, textvariable=self.id_var, width=34)
        self.name_entry = ttk.Entry(body, textvariable=self.name_var)
        self.category_box = ttk.Combobox(body, textvariable=self.category_var, values=app.category_names())
        self.sub_box = ttk.Combobox(body, textvariable=self.sub_var, values=[])
        unit_box = ttk.Combobox(body, textvariable=self.unit_var, values=UNITS)
        qty_box = ttk.Spinbox(body, from_=0, to=1000000, textvariable=self.qty_var)
        price_entry = ttk.Entry(body, textvariable=self.price_var)

        fields = [
            ("Item ID", self.id_entry),
            ("Item Name", self.name_entry),
            ("Category", self.category_box),
            ("Subcategory", self.sub_box),
            ("Unit", unit_box),
            ("Quantity on Hand", qty_box),
            ("Unit Price", price_entry),
        ]
        for row, (label, widget) in enumerate(fields, start=1):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 14))
            widget.grid(row=row, column=1, sticky="ew", pady=4)

        # Deduct stock (Edit only): type the amount sold/used and click Deduct
        if item_id:
            ttk.Label(body, text="Deduct (sold / used)").grid(
                row=8, column=0, sticky="w", pady=4, padx=(0, 14)
            )
            deduct_row = ttk.Frame(body)
            deduct_row.grid(row=8, column=1, sticky="ew", pady=4)
            deduct_row.columnconfigure(0, weight=1)
            ttk.Spinbox(
                deduct_row, from_=0, to=1000000, textvariable=self.deduct_var
            ).grid(row=0, column=0, sticky="ew")
            ttk.Button(deduct_row, text="Deduct", command=self.deduct_stock).grid(
                row=0, column=1, padx=(8, 0)
            )

        self.info_var = tk.StringVar()
        ttk.Label(body, textvariable=self.info_var, foreground="#5f6368").grid(
            row=9, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        buttons = ttk.Frame(body)
        buttons.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        buttons.columnconfigure((0, 1), weight=1)
        ttk.Button(buttons, text="Save", command=self.save).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(buttons, text="Cancel", command=self.destroy).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.category_box.bind("<<ComboboxSelected>>", self.on_category_selected)
        self.bind("<Return>", lambda e: self.save())
        self.bind("<Escape>", lambda e: self.destroy())

        if item_id:
            self.load_item(item_id)
            self.name_entry.focus()
        else:
            self.id_entry.focus()

        self.center_on_parent()
        self.grab_set()

    def center_on_parent(self):
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = self.app.winfo_x() + (self.app.winfo_width() - w) // 2
        y = self.app.winfo_y() + (self.app.winfo_height() - h) // 2
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def on_category_selected(self, event=None):
        category = self.category_var.get()
        self.sub_box.config(values=CATEGORY_TREE.get(category, []))
        self.sub_var.set("")
        if not self.editing_id and not self.id_var.get().strip():
            self.id_var.set(self.app.suggest_id(category))

    def load_item(self, item_id):
        try:
            row = self.app.api.get_item(item_id)
        except ApiError as error:
            self.app.show_api_error(error, parent=self)
            row = None
        if not row:
            self.destroy()
            return

        (item_id, name, category, sub, unit, qty, price, updated_by, updated_at) = row
        self.id_var.set(item_id)
        self.name_var.set(name)
        self.category_var.set(category)
        self.sub_box.config(values=CATEGORY_TREE.get(category, []))
        self.sub_var.set(sub)
        self.unit_var.set(unit)
        self.qty_var.set(str(qty))
        self.price_var.set(f"{price:.2f}" if price else "")
        self.info_var.set(
            f"Last updated by {updated_by} on {updated_at}" if updated_by else "Not updated yet"
        )
        self.id_entry.config(state="disabled")  # the ID is the key, so it can't be changed

    def deduct_stock(self):
        """Subtract the amount sold/used from Quantity on Hand (saved when you click Save)."""
        try:
            amount = int(self.deduct_var.get())
            if amount <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid amount", "Enter a whole number greater than 0 to deduct.", parent=self)
            return

        try:
            current = int(self.qty_var.get())
        except ValueError:
            messagebox.showerror("Invalid quantity", "Quantity on Hand must be a whole number.", parent=self)
            return

        if amount > current:
            messagebox.showerror(
                "Not enough stock",
                f"Only {current} on hand, so you can't deduct {amount}.",
                parent=self,
            )
            return

        self.qty_var.set(str(current - amount))
        self.deduct_var.set("0")

    def save(self):
        item_id = self.id_var.get().strip()
        name = self.name_var.get().strip()
        category = self.category_var.get().strip()
        subcategory = self.sub_var.get().strip()
        unit = self.unit_var.get().strip()

        if not item_id or not name or not category or not unit:
            messagebox.showwarning(
                "Missing information", "Item ID, Item Name, Category and Unit are required.", parent=self
            )
            return

        try:
            qty = int(self.qty_var.get())
            if qty < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid quantity", "Quantity must be a whole number (0 or more).", parent=self)
            return

        price_text = self.price_var.get().replace(",", "").strip()
        try:
            price = float(price_text) if price_text else 0.0
            if price < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid price", "Unit Price must be a number (0 or more).", parent=self)
            return

        try:
            if self.editing_id:
                self.app.api.update_item(self.editing_id, name, category, subcategory, unit, qty, price)
            else:
                self.app.api.create_item(item_id, name, category, subcategory, unit, qty, price)
        except ApiError as error:
            if error.status == 409:
                messagebox.showerror(
                    "Duplicate Item ID",
                    f"Item ID '{item_id}' already exists. Select it in the table and use Edit to change it.",
                    parent=self,
                )
            else:
                self.app.show_api_error(error, parent=self)
            return

        self.app.on_item_saved(item_id)
        self.destroy()


class SearchForm(tk.Toplevel):
    """Popup for searching and filtering the table."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Search Items")
        self.resizable(False, False)
        self.transient(app)

        self.search_var = tk.StringVar(value=app.search_var.get())
        self.cat_var = tk.StringVar(value=app.filter_cat_var.get())
        self.status_var = tk.StringVar(value=app.filter_status_var.get())

        body = ttk.Frame(self, padding=20)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text="Search Items", font=("Segoe UI", 14, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12)
        )

        self.search_entry = ttk.Entry(body, textvariable=self.search_var, width=34)
        category_box = ttk.Combobox(
            body, textvariable=self.cat_var, state="readonly",
            values=[ALL_CATEGORIES] + app.category_names(),
        )
        status_box = ttk.Combobox(
            body, textvariable=self.status_var, state="readonly", values=STATUS_FILTERS
        )

        for row, (label, widget) in enumerate(
            [("Search", self.search_entry), ("Category", category_box), ("Status", status_box)], start=1
        ):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 14))
            widget.grid(row=row, column=1, sticky="ew", pady=4)

        ttk.Label(
            body, text="Searches Item ID, name, category and subcategory.", foreground="#5f6368"
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        buttons.columnconfigure((0, 1), weight=1)
        ttk.Button(buttons, text="Search", command=self.search).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(buttons, text="Cancel", command=self.destroy).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.bind("<Return>", lambda e: self.search())
        self.bind("<Escape>", lambda e: self.destroy())

        self.search_entry.focus()
        self.search_entry.select_range(0, "end")
        self.center_on_parent()
        self.grab_set()

    def center_on_parent(self):
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = self.app.winfo_x() + (self.app.winfo_width() - w) // 2
        y = self.app.winfo_y() + (self.app.winfo_height() - h) // 2
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def search(self):
        self.app.search_var.set(self.search_var.get().strip())
        self.app.filter_cat_var.set(self.cat_var.get())
        self.app.filter_status_var.set(self.status_var.get())
        self.app.load_items()
        self.destroy()


class PrintForm(tk.Toplevel):
    """Popup: choose a report, preview it, and send it to the system printer."""

    REPORTS = [
        ("all", "Full inventory list"),
        ("out", "Out of stock items"),
        ("current", "Current table view (search and filters)"),
    ]

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.text = ""
        self.count = 0

        self.title("Print Report")
        self.resizable(False, False)
        self.transient(app)

        self.report_var = tk.StringVar(value="all")
        self.category_var = tk.StringVar(value=app.category_names()[0])

        body = ttk.Frame(self, padding=20)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Print Report", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 10))

        choices = ttk.LabelFrame(body, text="Select report", padding=12)
        choices.pack(fill="x")
        for key, label in self.REPORTS:
            ttk.Radiobutton(
                choices, text=label, value=key, variable=self.report_var, command=self.refresh
            ).pack(anchor="w", pady=2)

        category_row = ttk.Frame(choices)
        category_row.pack(anchor="w", fill="x", pady=2)
        ttk.Radiobutton(
            category_row, text="By category:", value="category",
            variable=self.report_var, command=self.refresh,
        ).pack(side="left")
        category_box = ttk.Combobox(
            category_row, textvariable=self.category_var, state="readonly",
            values=app.category_names(), width=34,
        )
        category_box.pack(side="left", padx=(8, 0))
        category_box.bind("<<ComboboxSelected>>", self.on_category_chosen)

        ttk.Label(body, text="Preview").pack(anchor="w", pady=(12, 2))
        preview_frame = ttk.Frame(body)
        preview_frame.pack(fill="both", expand=True)
        self.preview = tk.Text(
            preview_frame, width=78, height=14, font=("Consolas", 9), wrap="none",
            state="disabled", bg="#fafafa",
        )
        scroll = ttk.Scrollbar(preview_frame, orient="vertical", command=self.preview.yview)
        self.preview.configure(yscrollcommand=scroll.set)
        self.preview.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(14, 0))
        buttons.columnconfigure((0, 1), weight=1)
        ttk.Button(buttons, text="Print", command=self.print_report).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(buttons, text="Cancel", command=self.destroy).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.bind("<Escape>", lambda e: self.destroy())

        self.refresh()
        center_over(self, app)
        self.grab_set()

    def on_category_chosen(self, event=None):
        self.report_var.set("category")
        self.refresh()

    def refresh(self):
        self.text, self.count = self.app.make_report(self.report_var.get(), self.category_var.get())
        self.preview.config(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", self.text)
        self.preview.config(state="disabled")

    def print_report(self):
        if self.count == 0:
            messagebox.showinfo("Nothing to print", "This report has no items.", parent=self)
            return
        try:
            send_to_printer(self.text)
        except (OSError, subprocess.CalledProcessError) as error:
            messagebox.showerror(
                "Printing failed",
                f"The report could not be sent to the printer.\n\n{error}",
                parent=self,
            )
            return
        messagebox.showinfo("Print", "The report was sent to the default printer.", parent=self)
        self.destroy()


class Dashboard(tk.Tk):
    def __init__(self, user_email: str, api):
        super().__init__()
        self.user_email = user_email
        self.api = api            # connection to the server (already logged in)
        self.items = []           # copy of the item list from the server, refreshed regularly
        self.closing = False
        self.requests_btn = None  # admin-only "Password Requests" button
        self.tick = 0
        self.logged_out = False  # login.py checks this to decide whether to show the login again
        self.clock_job = None    # id of the pending clock update (so it can be cancelled)

        self.title("LRT Decor Inventory System")
        self.center(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.minsize(1000, 520)

        try:
            self.items = self.api.get_items()
        except ApiError as error:
            messagebox.showerror("Server", f"Could not load the inventory.\n\n{error}", parent=self)

        self.build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- Setup ----------
    def center(self, width: int, height: int):
        self.update_idletasks()
        x = (self.winfo_screenwidth() - width) // 2
        y = (self.winfo_screenheight() - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")

    def build_ui(self):
        # ---- Top bar: title on the left; clock, account email and Logout on the right ----
        header = tk.Frame(self, bg=HEADER_BG, height=56)
        header.pack(side="top", fill="x")
        header.pack_propagate(False)

        tk.Label(
            header,
            text="LRT Decor Inventory System",
            bg=HEADER_BG,
            fg="white",
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left", padx=20)

        # Logout is packed first so it sits at the far right, with the email just left of it
        tk.Button(
            header,
            text="Logout",
            command=self.logout,
            bg=HEADER_BTN_BG,
            fg="white",
            activebackground="#4b5f87",
            activeforeground="white",
            font=("Segoe UI", 9),
            relief="flat",
            bd=0,
            padx=14,
            pady=5,
            cursor="hand2",
        ).pack(side="right", padx=(10, 20))

        # Admin only: password-reset requests from the login screen, and user accounts
        if self.api.role == "admin":
            self.requests_btn = tk.Button(
                header,
                text="Password Requests",
                command=lambda: PasswordRequestsWindow(self, self.api, on_change=self.refresh_request_badge),
                bg=HEADER_BTN_BG,
                fg="white",
                activebackground="#4b5f87",
                activeforeground="white",
                font=("Segoe UI", 9),
                relief="flat",
                bd=0,
                padx=14,
                pady=5,
                cursor="hand2",
            )
            self.requests_btn.pack(side="right", padx=(10, 0))
            tk.Button(
                header,
                text="Users",
                command=lambda: UsersWindow(self, self.api),
                bg=HEADER_BTN_BG,
                fg="white",
                activebackground="#4b5f87",
                activeforeground="white",
                font=("Segoe UI", 9),
                relief="flat",
                bd=0,
                padx=14,
                pady=5,
                cursor="hand2",
            ).pack(side="right", padx=(10, 0))
            self.refresh_request_badge()

        tk.Label(
            header,
            text=self.user_email,
            bg=HEADER_BG,
            fg="#c9d3e6",
            font=("Segoe UI", 9),
        ).pack(side="right")

        # ---- Live date & time (left of the email) ----
        self.clock_var = tk.StringVar()
        tk.Label(
            header,
            textvariable=self.clock_var,
            bg=HEADER_BG,
            fg="white",
            font=("Segoe UI", 10, "bold"),
        ).pack(side="right", padx=(0, 24))
        self.update_clock()

        # ---- Main content area (full width) ----
        self.content = ttk.Frame(self, padding=20)
        self.content.pack(fill="both", expand=True)

        self.show_inventory()

    # ---------- Live clock ----------
    def update_clock(self):
        """Show the current date and time, and refresh every second."""
        self.clock_var.set(datetime.now().strftime(CLOCK_FORMAT))
        self.tick += 1
        if self.tick % 10 == 0:  # new password requests, every ~10 seconds (admin)
            self.refresh_request_badge()
        if self.tick % 30 == 0:  # pick up other users' changes, every ~30 seconds
            self.auto_refresh_items()
        self.clock_job = self.after(1000, self.update_clock)

    # ---------- Server data ----------
    def show_api_error(self, error, parent=None):
        if getattr(error, "status", 0) == 401:
            self.session_expired()
            return
        messagebox.showerror("Server", str(error), parent=parent or self)

    def session_expired(self):
        if self.closing:
            return
        self.closing = True
        messagebox.showwarning("Session expired", "Your session expired. Please log in again.", parent=self)
        self.logged_out = True
        self.stop_clock()
        self.destroy()

    def reload_items(self):
        """Fetch the latest items from the server and redraw the table."""
        try:
            self.items = self.api.get_items()
        except ApiError as error:
            self.show_api_error(error)
            return False
        self.load_items()
        return True

    def auto_refresh_items(self):
        if self.closing:
            return

        def done(items, error):
            if error is not None:
                if getattr(error, "status", 0) == 401:
                    self.session_expired()
                return  # offline etc.: ignore, the next refresh tries again
            if items != self.items:
                self.items = items
                self.load_items()

        run_in_background(self, self.api.get_items, done)

    def refresh_request_badge(self):
        if self.requests_btn is None or self.closing:
            return

        def done(count, error):
            if error is not None:
                if getattr(error, "status", 0) == 401:
                    self.session_expired()
                return
            if count:
                self.requests_btn.config(
                    text=f"Password Requests ({count})", bg="#c0392b", activebackground="#a93226"
                )
            else:
                self.requests_btn.config(
                    text="Password Requests", bg=HEADER_BTN_BG, activebackground="#4b5f87"
                )

        run_in_background(self, self.api.pending_count, done)

    def stop_clock(self):
        if self.clock_job is not None:
            self.after_cancel(self.clock_job)
            self.clock_job = None

    # ---------- Inventory page (table only) ----------
    def clear_content(self):
        for widget in self.content.winfo_children():
            widget.destroy()

    def category_names(self):
        names = list(CATEGORY_TREE)
        for category in sorted({item[2] for item in self.items}):
            if category not in names:
                names.append(category)
        return names

    def show_inventory(self):
        self.clear_content()

        # ---- Title ----
        ttk.Label(self.content, text="Materials Inventory List", font=("Segoe UI", 16, "bold")).pack(
            anchor="w", pady=(0, 10)
        )
        self.summary_var = tk.StringVar()

        # ---- Action buttons ----
        buttons = ttk.Frame(self.content)
        buttons.pack(fill="x", pady=(0, 10))
        for text, command in [
            ("Add", self.add_item),
            ("Edit", self.edit_item),
            ("Delete", self.delete_item),
            ("Search", self.open_search),
            ("Print", self.print_items),
            ("Refresh", self.refresh_items),
        ]:
            ttk.Button(buttons, text=text, width=10, command=command).pack(side="left", padx=(0, 8))

        # Totals, on the right side of the same row as the buttons
        self.summary_label = ttk.Label(buttons, textvariable=self.summary_var, foreground="#5f6368")
        self.summary_label.pack(side="right")

        # Current search/filter settings (changed through the Search popup)
        self.search_var = tk.StringVar()
        self.filter_cat_var = tk.StringVar(value=ALL_CATEGORIES)
        self.filter_status_var = tk.StringVar(value=STATUS_FILTERS[0])

        # ---- Table of materials ----
        table_frame = ttk.Frame(self.content)
        table_frame.pack(fill="both", expand=True)

        columns = ("id", "name", "category", "subcategory", "unit", "quantity", "status", "price")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")

        headings = {
            "id": ("Item ID", 70, 60, "center"),
            "name": ("Item Name", 210, 120, "w"),
            "category": ("Category", 170, 90, "w"),
            "subcategory": ("Subcategory", 130, 80, "w"),
            "unit": ("Unit", 45, 35, "center"),
            "quantity": ("Qty", 55, 40, "center"),
            "status": ("Status", 85, 70, "center"),
            "price": ("Unit Price", 75, 60, "e"),
        }
        for col, (text, width, minwidth, anchor) in headings.items():
            self.table.heading(col, text=text)
            self.table.column(col, width=width, minwidth=minwidth, anchor=anchor)

        self.table.tag_configure("out", foreground="#c5221f")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Line the totals up with the table's last column (the scrollbar sits to its right)
        self.update_idletasks()
        self.summary_label.pack_configure(padx=(0, scrollbar.winfo_reqwidth()))

        # Double-click a row to edit it
        self.table.bind(
            "<Double-1>",
            lambda e: self.edit_item() if self.table.identify_region(e.x, e.y) == "cell" else None,
        )

        self.load_items()

    # ---------- Data helpers ----------
    def fetch_items(self):
        """Rows matching the current search/filters (filtered here, from the local copy)."""
        term = self.search_var.get().strip().lower()
        category = self.filter_cat_var.get()
        status = self.filter_status_var.get()

        rows = []
        for item in self.items:
            item_id, name, item_category, sub, unit, qty, price = item[:7]
            if term and not any(term in str(v).lower() for v in (item_id, name, item_category, sub)):
                continue
            if category != ALL_CATEGORIES and item_category != category:
                continue
            if status == "Out of Stock" and qty > 0:
                continue
            if status == "In Stock" and qty <= 0:
                continue
            rows.append(item[:7])
        return rows

    def load_items(self):
        selected = self.table.selection()
        self.table.delete(*self.table.get_children())
        for item_id, name, category, sub, unit, qty, price in self.fetch_items():
            status = stock_status(qty)
            tag = "out" if status == "Out of Stock" else ""
            # iid = item_id so we can always look the row up again
            self.table.insert(
                "", "end", iid=item_id, tags=(tag,),
                values=(item_id, name, category, sub, unit, qty, status, f"{price:,.2f}"),
            )
        keep = [iid for iid in selected if self.table.exists(iid)]
        if keep:
            self.table.selection_set(keep)
        self.update_summary()

    def update_summary(self):
        total = len(self.items)
        out = sum(1 for item in self.items if item[5] <= 0)
        text = f"Total items: {total}    Out of stock: {out}"
        filtered = (
            self.search_var.get().strip()
            or self.filter_cat_var.get() != ALL_CATEGORIES
            or self.filter_status_var.get() != STATUS_FILTERS[0]
        )
        if filtered:
            text = f"Showing {len(self.table.get_children())} of {total}    " + text
        self.summary_var.set(text)

    def suggest_id(self, category):
        prefix = ID_PREFIXES.get(category, "ITM")
        numbers = []
        for item_id in (item[0] for item in self.items if item[0].startswith(f"{prefix}-")):
            tail = item_id.split("-", 1)[1]
            if tail.isdigit():
                numbers.append(int(tail))
        return f"{prefix}-{max(numbers, default=0) + 1:03d}"

    def on_item_saved(self, item_id):
        """Called by the popup after a successful save."""
        self.reload_items()
        if self.table.exists(item_id):
            self.table.selection_set(item_id)
            self.table.see(item_id)

    # ---------- Button actions ----------
    def add_item(self):
        ItemForm(self)

    def open_search(self):
        SearchForm(self)

    def edit_item(self):
        selected = self.table.selection()
        if not selected:
            messagebox.showwarning("No selection", "Select an item in the table first.", parent=self)
            return
        ItemForm(self, item_id=selected[0])

    def delete_item(self):
        selected = self.table.selection()
        if not selected:
            messagebox.showwarning("No selection", "Select an item in the table first.", parent=self)
            return

        item_id = selected[0]
        if not messagebox.askyesno("Delete item", f"Delete item '{item_id}'?", parent=self):
            return

        try:
            self.api.delete_item(item_id)
        except ApiError as error:
            self.show_api_error(error)
        self.reload_items()

    def print_items(self):
        PrintForm(self)

    # ---------- Reports ----------
    REPORT_TITLES = {
        "all": "Full Inventory List",
        "out": "Out of Stock Report",
        "current": "Current Table View",
        "category": "Inventory by Category",
    }

    def describe_filters(self):
        parts = []
        if self.search_var.get().strip():
            parts.append(f'Search: "{self.search_var.get().strip()}"')
        if self.filter_cat_var.get() != ALL_CATEGORIES:
            parts.append(f"Category: {self.filter_cat_var.get()}")
        if self.filter_status_var.get() != STATUS_FILTERS[0]:
            parts.append(f"Status: {self.filter_status_var.get()}")
        return "   ".join(parts) or "No search or filters applied"

    def report_rows(self, kind, category=""):
        if kind == "current":
            return self.fetch_items()

        rows = [item[:7] for item in self.items]
        if kind == "out":
            return [r for r in rows if stock_status(r[5]) == "Out of Stock"]
        if kind == "category":
            return [r for r in rows if r[2] == category]
        return rows

    def make_report(self, kind, category=""):
        """Return (report text, number of items) for the chosen report."""
        rows = self.report_rows(kind, category)
        note = ""
        if kind == "category":
            note = f"Category: {category}"
        elif kind == "current":
            note = self.describe_filters()
        return self.build_report_text(self.REPORT_TITLES[kind], rows, note), len(rows)

    def build_report_text(self, title, rows, note=""):
        width = 71
        name_width = 36
        lines = ["LRT DECOR INVENTORY".center(width), title.center(width)]
        if note:
            lines.append(note.center(width))
        lines.append(f"Printed {datetime.now():%Y-%m-%d %H:%M} by {self.user_email}".center(width))
        lines.append("=" * width)
        lines.append(f"{'Item ID':<8} {'Item Name':<{name_width}} {'Unit':<5} {'Qty':>6} {'Status':<12}")
        lines.append("-" * width)

        if not rows:
            lines += ["", "No items to report."]

        # Group by category, then subcategory (in the order they appear in the list)
        groups = {}
        for row in rows:
            groups.setdefault(row[2], {}).setdefault(row[3], []).append(row)

        for category, subcategories in groups.items():
            lines += ["", category.upper()]
            for subcategory, items in subcategories.items():
                if subcategory:
                    lines.append(f"  {subcategory}")
                for item_id, name, _cat, _sub, unit, qty, _price in items:
                    wrapped = textwrap.wrap(name, name_width) or [""]
                    lines.append(
                        f"{item_id:<8} {wrapped[0]:<{name_width}} {unit:<5} {qty:>6} "
                        f"{stock_status(qty):<12}"
                    )
                    for extra in wrapped[1:]:
                        lines.append(f"{'':<8} {extra:<{name_width}}")

        out = sum(1 for r in rows if stock_status(r[5]) == "Out of Stock")
        lines += ["", "-" * width, f"Items: {len(rows)}    Out of stock: {out}"]
        return "\n".join(lines) + "\n"

    def refresh_items(self):
        """Clear the search/filters and reload the table from the database."""
        self.search_var.set("")
        self.filter_cat_var.set(ALL_CATEGORIES)
        self.filter_status_var.set(STATUS_FILTERS[0])
        self.table.selection_remove(*self.table.selection())
        self.reload_items()

    # ---------- Window actions ----------
    def logout(self):
        if messagebox.askyesno("Logout", "Are you sure you want to log out?", parent=self):
            self.logged_out = True
            self.closing = True
            self.stop_clock()
            self.destroy()

    def on_close(self):
        # Closing with the X (or Exit) leaves logged_out as False, so the app exits.
        self.closing = True
        self.stop_clock()
        self.destroy()


if __name__ == "__main__":
    print("Start the program with main.py (it needs the login and the server).")