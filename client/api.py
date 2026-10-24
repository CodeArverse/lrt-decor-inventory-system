"""Talks to the LRT Inventory server. Uses only the standard library."""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

# >>> Put your server's address here, e.g. "https://inventory.yourdomain.com"
# (or write it in a text file named server_url.txt next to the .exe - no rebuild needed).
SERVER_URL = "http://127.0.0.1:8000"


def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def load_server_url() -> str:
    env = os.environ.get("LRT_SERVER_URL", "").strip()
    if env:
        return env.rstrip("/")
    try:
        with open(os.path.join(app_dir(), "server_url.txt"), encoding="utf-8") as file:
            text = file.read().strip()
            if text:
                return text.rstrip("/")
    except OSError:
        pass
    return SERVER_URL.rstrip("/")


class ApiError(Exception):
    """status 0 = could not reach the server; otherwise the HTTP status."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


ITEM_FIELDS = ("item_id", "name", "category", "subcategory", "unit",
               "quantity", "price", "updated_by", "updated_at")


def item_tuple(item: dict) -> tuple:
    return tuple(item[field] for field in ITEM_FIELDS)


class ApiClient:
    def __init__(self, base_url: str = None):
        self.base_url = (base_url or load_server_url()).rstrip("/")
        self.token = None
        self.email = ""
        self.role = ""

    @property
    def is_secure(self) -> bool:
        host = urllib.parse.urlparse(self.base_url).hostname or ""
        return self.base_url.startswith("https://") or host in ("127.0.0.1", "localhost")

    def request(self, method: str, path: str, body=None, params=None, timeout: int = 20):
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            message = "Something went wrong."
            try:
                detail = json.loads(error.read()).get("detail")
                if isinstance(detail, str):
                    message = detail
            except Exception:
                pass
            raise ApiError(message, error.code)
        except (urllib.error.URLError, OSError, ValueError):
            raise ApiError("Can't reach the server. Check your internet connection and try again.", 0)
        return json.loads(raw) if raw else None

    # ---------- Accounts ----------
    def login(self, email: str, password: str) -> dict:
        result = self.request("POST", "/login", {"email": email, "password": password})
        self.token, self.email, self.role = result["token"], result["email"], result["role"]
        return result

    def logout(self):
        self.token, self.email, self.role = None, "", ""

    def forgot_password(self, email: str):
        self.request("POST", "/forgot-password", {"email": email})

    def change_password(self, current_password: str, new_password: str):
        result = self.request(
            "POST", "/change-password",
            {"current_password": current_password, "new_password": new_password},
        )
        self.token = result["token"]

    # ---------- Items ----------
    def get_items(self) -> list:
        return [item_tuple(item) for item in self.request("GET", "/items")]

    def get_item(self, item_id: str):
        try:
            return item_tuple(self.request("GET", "/items/" + urllib.parse.quote(item_id, safe="")))
        except ApiError as error:
            if error.status == 404:
                return None
            raise

    @staticmethod
    def _item_body(item_id, name, category, subcategory, unit, quantity, price) -> dict:
        return {"item_id": item_id, "name": name, "category": category, "subcategory": subcategory,
                "unit": unit, "quantity": quantity, "price": price}

    def create_item(self, item_id, name, category, subcategory, unit, quantity, price):
        self.request("POST", "/items", self._item_body(item_id, name, category, subcategory, unit, quantity, price))

    def update_item(self, item_id, name, category, subcategory, unit, quantity, price):
        self.request("PUT", "/items/" + urllib.parse.quote(item_id, safe=""),
                     self._item_body(item_id, name, category, subcategory, unit, quantity, price))

    def delete_item(self, item_id: str):
        self.request("DELETE", "/items/" + urllib.parse.quote(item_id, safe=""))

    # ---------- Admin ----------
    def admin_status(self) -> dict:
        return self.request("GET", "/admin/status")

    def admin_requests(self) -> list:
        return self.request("GET", "/admin/requests")

    def pending_count(self) -> int:
        return self.request("GET", "/admin/requests/count")["pending"]

    def reset_request(self, request_id: int) -> dict:
        return self.request("POST", f"/admin/requests/{int(request_id)}/reset", {}, timeout=40)

    def dismiss_request(self, request_id: int):
        self.request("POST", f"/admin/requests/{int(request_id)}/dismiss", {})

    def admin_users(self) -> list:
        return self.request("GET", "/admin/users")

    def add_user(self, email: str, role: str) -> dict:
        return self.request("POST", "/admin/users", {"email": email, "role": role}, timeout=40)

    def delete_user(self, email: str):
        self.request("DELETE", "/admin/users", params={"email": email})
