"""Dialogs that talk to the server: forgot password, change password, and the admin screens."""
import re
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from api import ApiError

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8


def center_window(win, width: int, height: int):
    """Size a window and place it in the center of the screen."""
    win.update_idletasks()
    x = (win.winfo_screenwidth() - width) // 2
    y = (win.winfo_screenheight() - height) // 2
    win.geometry(f"{width}x{height}+{x}+{y}")


def run_in_background(widget, work, on_done):
    """Run work() in a thread so the window doesn't freeze while waiting for the
    server, then call on_done(value, error) back on the Tk thread."""
    outcome = {}

    def target():
        try:
            outcome["value"] = work()
        except Exception as error:
            outcome["error"] = error
        finally:
            outcome["finished"] = True

    threading.Thread(target=target, daemon=True).start()

    def poll():
        try:
            if not outcome.get("finished"):
                widget.after(100, poll)
                return
            on_done(outcome.get("value"), outcome.get("error"))
        except tk.TclError:
            pass  # the window was closed meanwhile

    widget.after(100, poll)


def error_text(error: Exception) -> str:
    return str(error) if isinstance(error, ApiError) else f"Unexpected error: {error}"


# ======================= Login screen =======================
class ContactAdminWindow(tk.Toplevel):
    """Login screen > 'Forgot password?': asks the server to notify the admin."""

    def __init__(self, parent, api, prefill: str = ""):
        super().__init__(parent)
        self.api = api
        self.title("Contact Admin")
        center_window(self, 340, 270)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        box = ttk.Frame(self, padding=20)
        box.pack(fill="both", expand=True)

        ttk.Label(box, text="Forgot your password?", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(
            box,
            text="Enter your email. The admin will reset your password and email you "
                 "a temporary one.",
            wraplength=295,
            justify="left",
        ).pack(anchor="w", pady=(4, 10))

        ttk.Label(box, text="Your email").pack(anchor="w")
        self.email_entry = ttk.Entry(box)
        self.email_entry.pack(fill="x", pady=(2, 8))
        self.email_entry.insert(0, prefill)
        self.email_entry.focus()

        self.msg = ttk.Label(box, text="", foreground="red", wraplength=295)
        self.msg.pack(anchor="w")

        self.send_btn = ttk.Button(box, text="Send request", command=self.submit)
        self.send_btn.pack(fill="x", pady=(8, 0))
        self.bind("<Return>", lambda e: self.submit())

    def submit(self):
        email = self.email_entry.get().strip().lower()
        if not EMAIL_PATTERN.match(email):
            self.msg.config(foreground="red", text="Please enter a valid email address.")
            return
        self.send_btn.state(["disabled"])
        self.msg.config(foreground="gray", text="Sending your request to the admin...")

        def done(_value, error):
            if error is not None:
                self.send_btn.state(["!disabled"])
                self.msg.config(foreground="red", text=error_text(error))
                return
            # Same answer whether or not the email has an account.
            messagebox.showinfo(
                "Request sent",
                "If this email belongs to an account, the admin has been notified.\n\n"
                "Once they reset your password, a temporary password will be sent to your email.",
                parent=self,
            )
            self.destroy()

        run_in_background(self, lambda: self.api.forgot_password(email), done)


class ChangePasswordDialog(tk.Toplevel):
    """Shown after logging in with a temporary password. `changed` tells the caller the result."""

    def __init__(self, parent, api, old_password: str):
        super().__init__(parent)
        self.api = api
        self.old_password = old_password
        self.changed = False

        self.title("Choose a new password")
        center_window(self, 340, 350)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        box = ttk.Frame(self, padding=20)
        box.pack(fill="both", expand=True)

        ttk.Label(box, text="Choose a new password", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(
            box,
            text=f"You signed in with a temporary password. Pick your own "
                 f"(at least {MIN_PASSWORD_LENGTH} characters).",
            wraplength=295,
            justify="left",
        ).pack(anchor="w", pady=(4, 10))

        ttk.Label(box, text="New password").pack(anchor="w")
        self.new_entry = ttk.Entry(box, show="*")
        self.new_entry.pack(fill="x", pady=(2, 8))

        ttk.Label(box, text="Confirm new password").pack(anchor="w")
        self.confirm_entry = ttk.Entry(box, show="*")
        self.confirm_entry.pack(fill="x", pady=(2, 8))

        self.msg = ttk.Label(box, text="", foreground="red", wraplength=295)
        self.msg.pack(anchor="w")

        self.save_btn = ttk.Button(box, text="Save password", command=self.save)
        self.save_btn.pack(fill="x", pady=(8, 0))
        self.new_entry.focus()
        self.bind("<Return>", lambda e: self.save())

    def save(self):
        new, confirm = self.new_entry.get(), self.confirm_entry.get()
        if len(new) < MIN_PASSWORD_LENGTH:
            self.msg.config(foreground="red", text=f"Use at least {MIN_PASSWORD_LENGTH} characters.")
            return
        if new != confirm:
            self.msg.config(foreground="red", text="The two passwords don't match.")
            return
        if new == self.old_password:
            self.msg.config(foreground="red", text="The new password must be different from the temporary one.")
            return

        self.save_btn.state(["disabled"])
        self.msg.config(foreground="gray", text="Saving...")

        def done(_value, error):
            if error is not None:
                self.save_btn.state(["!disabled"])
                self.msg.config(foreground="red", text=error_text(error))
                return
            self.changed = True
            self.destroy()

        run_in_background(self, lambda: self.api.change_password(self.old_password, new), done)


# ======================= Admin screens =======================
class PasswordRequestsWindow(tk.Toplevel):
    """Admin: see who asked for a reset, then reset it. The server emails the temporary password."""

    def __init__(self, parent, api, on_change=None):
        super().__init__(parent)
        self.api = api
        self.on_change = on_change
        self.title("Password Reset Requests")
        center_window(self, 660, 420)
        self.minsize(600, 340)
        self.transient(parent)
        self.build_ui()
        self.refresh()

    def build_ui(self):
        box = ttk.Frame(self, padding=16)
        box.pack(fill="both", expand=True)

        ttk.Label(
            box,
            text="Select a pending request and press Reset. A temporary password is emailed "
                 "to the user, who must choose a new one when they log in.",
            wraplength=620,
            justify="left",
        ).pack(anchor="w")
        self.email_status = ttk.Label(box, text="", wraplength=620, justify="left")
        self.email_status.pack(anchor="w", pady=(4, 8))

        table_frame = ttk.Frame(box)
        table_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            table_frame, columns=("email", "requested", "status"), show="headings", selectmode="browse"
        )
        for column, title, width in (
            ("email", "Email", 280), ("requested", "Requested", 160), ("status", "Status", 110)
        ):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, anchor="w")
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        buttons = ttk.Frame(box)
        buttons.pack(fill="x", pady=(10, 0))
        self.reset_btn = ttk.Button(buttons, text="Reset & Email Password", command=self.reset_selected)
        self.dismiss_btn = ttk.Button(buttons, text="Dismiss", command=self.dismiss_selected)
        self.refresh_btn = ttk.Button(buttons, text="Refresh", command=self.refresh)
        self.buttons = [self.reset_btn, self.dismiss_btn, self.refresh_btn]
        self.reset_btn.pack(side="left")
        self.dismiss_btn.pack(side="left", padx=6)
        self.refresh_btn.pack(side="left")

    def refresh(self):
        self.set_busy(True)

        def work():
            return self.api.admin_requests(), self.api.admin_status()

        def done(value, error):
            self.set_busy(False)
            if error is not None:
                messagebox.showerror("Could not load requests", error_text(error), parent=self)
                return
            rows, status = value
            self.tree.delete(*self.tree.get_children())
            for row in rows:
                self.tree.insert("", "end", iid=str(row["id"]),
                                 values=(row["email"], row["requested_at"], row["status"]))
            if status["email_ready"]:
                self.email_status.config(text="Email: ready (the server sends from its Gmail)", foreground="green")
            else:
                self.email_status.config(
                    text="Email: the server has no Gmail set up (SMTP_USER / SMTP_APP_PASSWORD), so "
                         "temporary passwords can't be emailed. They'll be shown here for you to pass on.",
                    foreground="#b45309",
                )
            if self.on_change:
                self.on_change()

        run_in_background(self, work, done)

    def set_busy(self, busy: bool):
        for button in self.buttons:
            button.state(["disabled" if busy else "!disabled"])
        self.config(cursor="watch" if busy else "")

    def selected_pending(self):
        """(request_id, email) of the selected pending request, or None."""
        selection = self.tree.selection()
        if not selection or self.tree.set(selection[0], "status") != "pending":
            messagebox.showinfo("Select a request", "Select a pending request first.", parent=self)
            return None
        return int(selection[0]), self.tree.set(selection[0], "email")

    def dismiss_selected(self):
        request = self.selected_pending()
        if not request or not messagebox.askyesno(
            "Dismiss request", f"Dismiss the request from {request[1]} without resetting?", parent=self
        ):
            return
        self.set_busy(True)

        def done(_value, error):
            self.set_busy(False)
            if error is not None:
                messagebox.showerror("Could not dismiss", error_text(error), parent=self)
            self.refresh()

        run_in_background(self, lambda: self.api.dismiss_request(request[0]), done)

    def reset_selected(self):
        request = self.selected_pending()
        if request is None:
            return
        request_id, email = request
        if not messagebox.askyesno(
            "Reset password",
            f"Reset the password for:\n{email}\n\nA temporary password will be emailed to them.",
            parent=self,
        ):
            return
        self.set_busy(True)

        def done(result, error):
            self.set_busy(False)
            if error is not None:
                messagebox.showerror("Reset failed", error_text(error), parent=self)
            elif result["emailed"]:
                messagebox.showinfo(
                    "Password sent",
                    f"A temporary password was emailed to {email}.\n"
                    "They'll be asked to choose a new one when they log in.",
                    parent=self,
                )
            else:
                self.clipboard_clear()
                self.clipboard_append(result["temp_password"])
                messagebox.showwarning(
                    "Password reset - email NOT sent",
                    f"{result.get('error', 'The email could not be sent.')}\n\n"
                    f"The password WAS reset. Give this temporary password to {email} yourself "
                    f"(it's also copied to your clipboard):\n\n{result['temp_password']}",
                    parent=self,
                )
            self.refresh()

        run_in_background(self, lambda: self.api.reset_request(request_id), done)


class UsersWindow(tk.Toplevel):
    """Admin: add users (with their real email) and remove users."""

    def __init__(self, parent, api):
        super().__init__(parent)
        self.api = api
        self.title("Manage Users")
        center_window(self, 560, 480)
        self.minsize(520, 440)
        self.transient(parent)

        box = ttk.Frame(self, padding=16)
        box.pack(fill="both", expand=True)

        table_frame = ttk.Frame(box)
        table_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table_frame, columns=("email", "role"), show="headings", selectmode="browse", height=8)
        self.tree.heading("email", text="Email")
        self.tree.heading("role", text="Role")
        self.tree.column("email", width=360, anchor="w")
        self.tree.column("role", width=100, anchor="w")
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.remove_btn = ttk.Button(box, text="Remove selected user", command=self.remove_selected)
        self.remove_btn.pack(anchor="e", pady=(8, 12))

        add = ttk.LabelFrame(box, text="Add a user", padding=12)
        add.pack(fill="x")
        ttk.Label(add, text="User's email (e.g. their Gmail)").pack(anchor="w")
        self.email_entry = ttk.Entry(add)
        self.email_entry.pack(fill="x", pady=(2, 6))
        ttk.Label(add, text="Role").pack(anchor="w")
        self.role_var = tk.StringVar(value="user")
        ttk.Combobox(add, textvariable=self.role_var, values=("user", "admin"), state="readonly").pack(fill="x", pady=(2, 6))
        self.msg = ttk.Label(add, text="", foreground="red", wraplength=480, justify="left")
        self.msg.pack(anchor="w")
        self.add_btn = ttk.Button(add, text="Add & Email Password", command=self.add)
        self.add_btn.pack(fill="x", pady=(6, 0))

        self.refresh()

    def refresh(self):
        def done(users, error):
            if error is not None:
                self.msg.config(foreground="red", text=error_text(error))
                return
            self.tree.delete(*self.tree.get_children())
            for user in users:
                self.tree.insert("", "end", iid=user["email"], values=(user["email"], user["role"]))

        run_in_background(self, self.api.admin_users, done)

    def remove_selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Select a user", "Select a user first.", parent=self)
            return
        email = selection[0]
        if not messagebox.askyesno("Remove user", f"Remove {email}? They will no longer be able to log in.", parent=self):
            return

        def done(_value, error):
            if error is not None:
                messagebox.showwarning("Not allowed", error_text(error), parent=self)
            self.refresh()

        run_in_background(self, lambda: self.api.delete_user(email), done)

    def add(self):
        email = self.email_entry.get().strip().lower()
        if not EMAIL_PATTERN.match(email):
            self.msg.config(foreground="red", text="Please enter a valid email address.")
            return
        self.msg.config(foreground="gray", text="Adding the user and sending the email...")
        self.add_btn.state(["disabled"])

        def done(result, error):
            self.add_btn.state(["!disabled"])
            if error is not None:
                self.msg.config(foreground="red", text=error_text(error))
                return
            self.msg.config(text="")
            self.email_entry.delete(0, tk.END)
            self.refresh()
            if result["emailed"]:
                messagebox.showinfo("User added", f"{email} was added. Their temporary password was emailed to them.", parent=self)
            else:
                self.clipboard_clear()
                self.clipboard_append(result["temp_password"])
                messagebox.showwarning(
                    "User added - email NOT sent",
                    f"{result.get('error', 'The email could not be sent.')}\n\nThe account WAS created. "
                    f"Give {email} this temporary password yourself (also copied to your clipboard):\n\n"
                    f"{result['temp_password']}",
                    parent=self,
                )

        run_in_background(self, lambda: self.api.add_user(email, self.role_var.get()), done)