import os
import re
import tkinter as tk
from tkinter import ttk, messagebox

# Fix for Python 3.13 tkinter Variable __del__ thread check issue during garbage collection
try:
    _old_variable_del = tk.Variable.__del__
    def _safe_variable_del(self):
        try:
            _old_variable_del(self)
        except (RuntimeError, Exception):
            pass
    tk.Variable.__del__ = _safe_variable_del
except Exception:
    pass

from api import ApiClient, ApiError
from windows import ChangePasswordDialog, ContactAdminWindow, center_window, run_in_background

# ======================= SETTINGS =======================
IMAGE_PATH = "../pexels-kathlene-1676830-35493874.png"

# "contain" = the whole picture is visible (empty space is filled with PANEL_COLOR)
# "fill"    = the picture covers the whole panel (the edges may be cropped)
FIT_MODE = "fill"

FORM_BG = "#d9b9a4"
PANEL_COLOR = "#2b3a55"    # left panel color (shown behind the picture / messages)
BUTTON_COLOR = "#1a73e8"   # Login button color
BUTTON_ACTIVE = "#1558b0"  # Login button color while pressed
# ========================================================

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

LEFT_WIDTH = 320
WINDOW_HEIGHT = 380


class LoginApp(tk.Tk):
    def __init__(self, api):
        super().__init__()
        self.api = api
        self.busy = False
        self.title("LRT Decor Inventory System")
        center_window(self, LEFT_WIDTH + 380, WINDOW_HEIGHT)
        self.resizable(False, False)

        self.show_password = tk.BooleanVar(value=False)
        self.attempts = 0
        self.max_attempts = 3
        self.photo = None
        self.user = None

        self.build_ui()

    def build_ui(self):
        # ---- Left division (picture) ----
        left = tk.Frame(self, width=LEFT_WIDTH, height=WINDOW_HEIGHT, bg=PANEL_COLOR)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        self.image_label = tk.Label(left, bg=PANEL_COLOR)
        self.image_label.pack(fill="both", expand=True)
        self.load_image()

        # ---- Right division (login form) ----
        frame = ttk.Frame(self, padding=28)
        frame.pack(side="left", fill="both", expand=True)

        ttk.Label(frame, text="Welcome", font=("Segoe UI", 16, "bold")).pack(pady=(10, 16))

        ttk.Label(frame, text="Enter your email").pack(anchor="w")
        self.email_entry = ttk.Entry(frame)
        self.email_entry.pack(fill="x", pady=(2, 10))

        ttk.Label(frame, text="Enter your password").pack(anchor="w")
        self.password_entry = ttk.Entry(frame, show="*")
        self.password_entry.pack(fill="x", pady=(2, 6))

        options_row = ttk.Frame(frame)
        options_row.pack(fill="x", pady=(0, 12))

        ttk.Checkbutton(
            options_row,
            text="Show password",
            variable=self.show_password,
            command=self.toggle_password,
        ).pack(side="left")

        help_link = tk.Label(
            options_row,
            text="Can't login? Contact the admin.",
            fg="#1a73e8",
            cursor="hand2",
            font=("Segoe UI", 9, "underline"),
        )
        help_link.pack(side="right")
        help_link.bind("<Button-1>", lambda e: self.open_contact_window())

        self.login_btn = tk.Button(
            frame,
            text="Login",
            command=self.login,
            bg=BUTTON_COLOR,
            fg="white",
            activebackground=BUTTON_ACTIVE,
            activeforeground="white",
            font=("Segoe UI", 11, "bold"),
            relief="raised",
            bd=0,
            pady=4,
            cursor="hand2",
        )
        self.login_btn.pack(fill="x")

        self.status = ttk.Label(frame, text="", foreground="red")
        self.status.pack(pady=(10, 0))

        self.email_entry.focus()
        self.bind("<Return>", lambda e: self.login())

    # ---------- Picture ----------
    def show_image_message(self, text):
        """Show a short message in the left panel when the picture can't be shown."""
        self.image_label.config(
            text=text,
            fg="white",
            font=("Segoe UI", 10),
            wraplength=LEFT_WIDTH - 40,
            justify="center",
        )

    def load_image(self):
        """Put the picture in the left panel, scaled to fit it."""
        path = IMAGE_PATH
        if not os.path.isabs(path):  # a plain file name means "next to this file"
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)

        if not os.path.isfile(path):
            self.show_image_message(f"Picture not found:\n{path}")
            return

        try:
            from PIL import Image, ImageOps, ImageTk
        except ImportError:
            self.load_image_without_pillow(path)
            return

        try:
            img = Image.open(path).convert("RGB")
            size = (LEFT_WIDTH, WINDOW_HEIGHT)
            if FIT_MODE == "fill":
                img = ImageOps.fit(img, size, Image.LANCZOS)
            else:
                img = ImageOps.contain(img, size, Image.LANCZOS)
            self.photo = ImageTk.PhotoImage(img)
            self.image_label.config(image=self.photo)
        except Exception as error:
            self.show_image_message(f"Could not load picture:\n{error}")

    def load_image_without_pillow(self, path):
        """Fallback when Pillow isn't installed: PNG/GIF only, shrunk by a whole number to fit."""
        if not path.lower().endswith((".png", ".gif")):
            self.show_image_message(
                "JPG pictures need Pillow.\nRun this, then restart:\n"
                "python -m pip install pillow"
            )
            return

        try:
            photo = tk.PhotoImage(file=path)
        except tk.TclError as error:
            self.show_image_message(f"Could not load picture:\n{error}")
            return

        width, height = photo.width(), photo.height()
        if FIT_MODE == "fill":
            factor = max(1, min(width // LEFT_WIDTH, height // WINDOW_HEIGHT))
        else:
            factor = max(1, -(-width // LEFT_WIDTH), -(-height // WINDOW_HEIGHT))

        if factor > 1:
            photo = photo.subsample(factor)
        self.photo = photo
        self.image_label.config(image=self.photo)

    # ---------- Contact admin ----------
    def open_contact_window(self):
        """Popup where the user asks the admin to reset their password."""
        ContactAdminWindow(self, self.api, self.email_entry.get().strip())

    # ---------- Login ----------
    def toggle_password(self):
        self.password_entry.config(show="" if self.show_password.get() else "*")

    def login(self):
        if self.busy:
            return
        email = self.email_entry.get().strip().lower()
        password = self.password_entry.get()

        if not email or not password:
            self.status.config(text="Please enter your email and password.")
            return

        if not EMAIL_PATTERN.match(email):
            self.status.config(text="Please enter a valid email address.")
            return

        self.busy = True
        self.login_btn.config(state="disabled")
        self.status.config(text="Signing in...", foreground="gray")
        run_in_background(
            self,
            lambda: self.api.login(email, password),
            lambda result, error: self.on_login_result(email, password, result, error),
        )

    def on_login_result(self, email, password, result, error):
        self.busy = False
        self.login_btn.config(state="normal")
        self.status.config(foreground="red")

        if error is not None:
            if isinstance(error, ApiError) and error.status == 401:
                self.attempts += 1
                remaining = self.max_attempts - self.attempts
                self.password_entry.delete(0, tk.END)
                if remaining <= 0:
                    messagebox.showerror("Locked", "Too many failed attempts.")
                    self.destroy()
                else:
                    self.status.config(text=f"Invalid credentials. {remaining} attempt(s) left.")
            else:
                self.status.config(text=str(error), wraplength=300, justify="center")
            return

        if result["must_change"]:
            dialog = ChangePasswordDialog(self, self.api, password)
            self.wait_window(dialog)
            if not dialog.changed:
                self.api.logout()
                self.password_entry.delete(0, tk.END)
                self.status.config(text="You must choose a new password to continue.")
                return

        self.user = email
        self.destroy()


def main():
    from dashboard import Dashboard

    api = ApiClient()
    if not api.is_secure:
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning(
            "Connection not encrypted",
            f"The server address ({api.base_url}) does not use https://.\n\n"
            "Passwords would travel over the internet unprotected. Ask your admin to set up HTTPS.",
            parent=root,
        )
        root.destroy()

    while True:
        api.logout()
        login = LoginApp(api)
        login.mainloop()
        if not login.user:
            break

        dashboard = Dashboard(login.user, api)
        dashboard.mainloop()
        if not dashboard.logged_out:
            break


if __name__ == "__main__":
    main()