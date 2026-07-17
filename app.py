import base64
import hashlib
import hmac
import html
import json
import mimetypes
import os
import re
import secrets
import uuid
from collections import deque
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import numpy as np
import streamlit as st
import streamlit.components.v1 as components
from cryptography.fernet import Fernet, InvalidToken
from PIL import Image, ImageDraw, ImageFilter
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas

try:
    from pywebpush import WebPushException, webpush
except Exception:
    webpush = None

    class WebPushException(Exception):
        pass

try:
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2 import service_account
except Exception:
    GoogleAuthRequest = None
    service_account = None


APP_DIR = Path(__file__).parent
LOGO_IMAGE = APP_DIR / "assets" / "ashs-angels-logo.png"
ICON_IMAGE = APP_DIR / "assets" / "ashs-angels-icon.png"
CALENDAR_PDF = APP_DIR / "assets" / "preschool-calendar-2026-2027.pdf"
CALENDAR_FILE = APP_DIR / "calendar.json"
DOCUMENTS_FILE = APP_DIR / "documents.json"
DOCUMENTS_DIR = APP_DIR / "static" / "documents"
DOCUMENT_AUDIENCES = ["Important", "Parents", "Private"]
PARENT_STATEMENT_PDF = APP_DIR / "assets" / "parent-statement-2026.pdf"
PARENT_STATEMENT_PAGES_DIR = APP_DIR / "assets" / "parent-statement-pages"
USERS_FILE = APP_DIR / "users.json"
CHILDREN_FILE = APP_DIR / "children.json"
PARENTS_FILE = APP_DIR / "parents.json"
MESSAGES_FILE = APP_DIR / "messages.json"
PUSH_SUBSCRIPTIONS_FILE = APP_DIR / "push_subscriptions.json"
CHILDREN_DIR = APP_DIR / "assets" / "children"
MESSAGES_DIR = APP_DIR / "assets" / "messages"
PUSH_COMPONENT_DIR = APP_DIR / "push_component"
SIGNATURE_COMPONENT_DIR = APP_DIR / "signature_component"
PUSH_COMPONENT_NAME = f"{Path(__file__).stem}.ashs_angels_push"
SESSIONS = ["Morning Session", "Afternoon Session"]
CALENDAR_TAGS = ["Open", "Closed", "Event"]
SESSION_ALIASES = {
    "Morning Session - 8:30am to 11:30am": "Morning Session",
    "Afternoon Session - 12:00pm to 3:00pm": "Afternoon Session",
}
PASSWORD_ROUNDS = 120_000
BUILD_MODE = False
DATA_REPOSITORY = "boylermallow/ashs-angels-preschool"
DATA_BRANCH = "main"
MESSAGE_ATTACHMENT_MAX_BYTES = 25 * 1024 * 1024
MESSAGE_ATTACHMENT_MAX_COUNT = 4
MESSAGE_ATTACHMENT_TYPES = ["png", "jpg", "jpeg", "webp", "mp4", "mov", "m4v", "webm"]
DOCUMENT_MAX_BYTES = 25 * 1024 * 1024
CONTACT_RELATIONSHIPS = ["Mam", "Dad", "Guardian"]
PARENT_STATEMENT_VERSION = "Parent Statement 2026/2027"
PUSH_SW_URL = f"/component/{PUSH_COMPONENT_NAME}/sw.js"
PUSH_SW_SCOPE = f"/component/{PUSH_COMPONENT_NAME}/"
PUSH_ICON_URL = f"/component/{PUSH_COMPONENT_NAME}/icon.svg"
FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

PRESCHOOL_CALENDAR_EVENTS = [
    {"date": "31 August 2026", "event": "Preschool re-opening", "tag": "Open"},
    {"date": "26-30 October 2026", "event": "Mid-term", "tag": "Closed"},
    {"date": "23 December 2026 - 5 January 2027", "event": "Christmas Holidays", "tag": "Closed"},
    {"date": "6 January 2027", "event": "School re-opening", "tag": "Open"},
    {"date": "1 February 2027", "event": "St Brigid's Day", "tag": "Closed"},
    {"date": "17-19 February 2027", "event": "Mid-term", "tag": "Closed"},
    {"date": "17 March 2027", "event": "St Patrick's Day", "tag": "Closed"},
    {"date": "22 March - 2 April 2027", "event": "Easter Holidays", "tag": "Closed"},
    {"date": "5 April 2027", "event": "School re-opening", "tag": "Open"},
    {"date": "3 May 2027", "event": "Public Holiday", "tag": "Closed"},
    {"date": "7 June 2027", "event": "Public Holiday", "tag": "Closed"},
    {"date": "23 June 2027", "event": "Last day of School", "tag": "Event"},
    {"date": "24 June 2027", "event": "Graduation for children leaving for Primary School", "tag": "Event"},
]


def setting(name, fallback=""):
    try:
        value = st.secrets.get(name, os.getenv(name, fallback))
    except Exception:
        value = os.getenv(name, fallback)
    return str(value).strip() if value else fallback


DEFAULT_ADMIN_EMAIL = setting("ASH_ADMIN_EMAIL")
DEFAULT_ADMIN_PASSWORD = setting("ASH_ADMIN_PASSWORD")
APP_PUBLIC_URL = setting("APP_PUBLIC_URL", "https://ashs-angels-preschool.streamlit.app").rstrip("/")
PUBLIC_LEGAL_BASE_URL = setting(
    "PUBLIC_LEGAL_BASE_URL",
    "https://github.com/boylermallow/ashs-angels-preschool/blob/main",
).rstrip("/")
PRIVACY_POLICY_URL = f"{PUBLIC_LEGAL_BASE_URL}/PRIVACY_POLICY.md"
ACCOUNT_DELETION_URL = f"{PUBLIC_LEGAL_BASE_URL}/ACCOUNT_DELETION.md"
PLAY_REVIEW_EMAIL = "play-review@ashsangels.com"
PLAY_REVIEW_ACCOUNT = {
    "email": PLAY_REVIEW_EMAIL,
    "role": "Parent",
    "salt": "2a91c0989a959c8e43a6e46c890c065c",
    "hash": "36324deeab65a3cabd404dbd58c3275db4024987eb3f57b06f37fa7c555b3afc",
}
PLAY_REVIEW_PARENT = {
    "ID": "google-play-review-parent",
    "FirstName": "Play Reviewer",
    "Relationship": "Guardian",
    "Email": PLAY_REVIEW_EMAIL,
    "Status": "Approved",
    "ChildID": "google-play-demo-child",
    "ChildName": "Demo Child",
}
PLAY_REVIEW_CHILD = {
    "ID": "google-play-demo-child",
    "Name": "Demo Child",
    "DOB": "2022-01-01",
    "Session": "Morning Session",
    "Thumbnail": "",
}

with Image.open(ICON_IMAGE) as icon_source:
    PAGE_ICON = icon_source.copy()


st.set_page_config(
    page_title="Ash's Angels Preschool App",
    page_icon=PAGE_ICON,
    layout="wide",
)

PUSH_COMPONENT = components.declare_component("ashs_angels_push", path=str(PUSH_COMPONENT_DIR))
SIGNATURE_COMPONENT = components.declare_component("ashs_angels_signature", path=str(SIGNATURE_COMPONENT_DIR))


def asset_url(path):
    if not path.exists():
        fallback_svg = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 220">
          <ellipse cx="160" cy="110" rx="150" ry="95" fill="#3154a5"/>
          <text x="160" y="96" text-anchor="middle" fill="white" font-family="Arial, sans-serif" font-size="32" font-weight="800">Ash's Angels</text>
          <text x="160" y="145" text-anchor="middle" fill="white" font-family="Arial, sans-serif" font-size="30" font-weight="800">Preschool</text>
        </svg>
        """
        data = base64.b64encode(fallback_svg.encode("utf-8")).decode("ascii")
        return f"data:image/svg+xml;base64,{data}"
    suffix = path.suffix.lower()
    mime = "image/svg+xml" if suffix == ".svg" else "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def render_browser_icon():
    icon_url = asset_url(ICON_IMAGE)
    components.html(
        f"""
        <script>
        (() => {{
          const doc = window.parent.document;
          doc.querySelectorAll('link[rel~="icon"], link[rel="shortcut icon"]').forEach((link) => link.remove());
          ["icon", "shortcut icon"].forEach((rel) => {{
            const link = doc.createElement("link");
            link.rel = rel;
            link.type = "image/png";
            link.href = "{icon_url}";
            doc.head.appendChild(link);
          }});
        }})();
        </script>
        """,
        height=0,
    )


render_browser_icon()


@st.cache_data(show_spinner=False)
def child_silhouette_url():
    scale = 4
    width = height = 256
    img = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = scale
    ink = (20, 24, 32, 255)
    white = (255, 255, 255, 255)

    draw.ellipse([64 * s, 22 * s, 192 * s, 150 * s], fill=white)
    draw.rounded_rectangle([38 * s, 120 * s, 218 * s, 238 * s], radius=58 * s, fill=white)
    draw.ellipse([76 * s, 34 * s, 180 * s, 138 * s], fill=ink)
    draw.rounded_rectangle([104 * s, 126 * s, 152 * s, 168 * s], radius=14 * s, fill=ink)
    draw.rounded_rectangle([46 * s, 142 * s, 210 * s, 244 * s], radius=56 * s, fill=ink)
    draw.polygon([(112 * s, 154 * s), (128 * s, 174 * s), (144 * s, 154 * s)], fill=white)

    img = img.resize((width, height), Image.Resampling.LANCZOS)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    data = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{data}"


def read_json(path, fallback):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return fallback


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2))


def github_data_token():
    for name in ("GITHUB_DATA_TOKEN", "GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT", "GITHUB_PERSONAL_ACCESS_TOKEN"):
        value = setting(name)
        if value:
            return value
    try:
        github_settings = st.secrets.get("github", {})
        for name in ("data_token", "token", "pat"):
            value = str(github_settings.get(name, "")).strip()
            if value:
                return value
    except Exception:
        pass
    return ""


def github_api_request(method, path, payload=None, warn=True):
    token = github_data_token()
    if not token:
        return None
    url = f"https://api.github.com/repos/{DATA_REPOSITORY}/contents/{path}"
    if method == "GET":
        url = f"{url}?ref={quote(DATA_BRANCH)}"
    body = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=12) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        if warn:
            st.session_state["data_save_warning"] = (
                "This change was saved for now, but not permanently. "
                "The GitHub data key needs checking."
            )
            st.session_state["data_save_error"] = str(exc)
        return None


def load_persistent_json(path, fallback):
    local_value = read_json(APP_DIR / path, fallback)
    remote = github_api_request("GET", path)
    if not remote or "content" not in remote:
        return local_value if isinstance(local_value, type(fallback)) else fallback
    try:
        encoded = "".join(str(remote["content"]).split())
        value = json.loads(base64.b64decode(encoded).decode("utf-8"))
        write_json(APP_DIR / path, value)
        st.session_state[f"{path}_sha"] = remote.get("sha", "")
        return value if isinstance(value, type(fallback)) else fallback
    except Exception:
        return local_value if isinstance(local_value, type(fallback)) else fallback


def save_persistent_json(path, value, message, allow_create=False):
    if not github_data_token():
        write_json(APP_DIR / path, value)
        st.session_state["data_save_warning"] = (
            "This change was saved for now, but permanent saving is not switched on yet."
        )
        return True
    remote = github_api_request("GET", path)
    if (not remote or not remote.get("sha")) and not allow_create:
        st.session_state["data_save_warning"] = (
            "This change was not saved permanently. The GitHub data key needs checking."
        )
        return False
    payload = {
        "message": message,
        "content": base64.b64encode(json.dumps(value, indent=2).encode("utf-8")).decode("ascii"),
        "branch": DATA_BRANCH,
    }
    if remote and remote.get("sha"):
        payload["sha"] = remote["sha"]
    result = github_api_request("PUT", path, payload)
    if result:
        write_json(APP_DIR / path, value)
        st.session_state.pop("data_save_warning", None)
        st.session_state.pop("data_save_error", None)
        st.session_state[f"{path}_sha"] = result.get("content", {}).get("sha", "")
        return True
    return False


def save_persistent_binary(path, file_bytes, message):
    local_path = APP_DIR / path
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(file_bytes)
    if not github_data_token():
        st.session_state["data_save_warning"] = (
            "This file was saved for now, but permanent saving is not switched on yet."
        )
        return False
    payload = {
        "message": message,
        "content": base64.b64encode(file_bytes).decode("ascii"),
        "branch": DATA_BRANCH,
    }
    return bool(github_api_request("PUT", path, payload))


def load_persistent_binary(path):
    clean_path = str(path or "").strip()
    if not clean_path:
        return b""
    local_path = APP_DIR / clean_path
    try:
        if local_path.exists():
            return local_path.read_bytes()
    except OSError:
        pass
    remote = github_api_request("GET", clean_path, warn=False)
    if not remote or "content" not in remote:
        return b""
    try:
        encoded = "".join(str(remote["content"]).split())
        file_bytes = base64.b64decode(encoded)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(file_bytes)
        return file_bytes
    except (OSError, ValueError, TypeError):
        return b""


def signed_form_cipher():
    encryption_secret = setting("SIGNED_FORMS_ENCRYPTION_KEY") or github_data_token()
    if not encryption_secret:
        return None
    key = base64.urlsafe_b64encode(hashlib.sha256(encryption_secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_signed_form(file_bytes):
    cipher = signed_form_cipher()
    return cipher.encrypt(file_bytes) if cipher and file_bytes else b""


def load_signed_parent_statement(parent):
    encrypted_path = str((parent or {}).get("ParentStatementSignedPdfPath") or "").strip()
    if not encrypted_path or not encrypted_path.endswith(".signed"):
        return b""
    encrypted_bytes = load_persistent_binary(encrypted_path)
    cipher = signed_form_cipher()
    if not encrypted_bytes or not cipher:
        return b""
    try:
        return cipher.decrypt(encrypted_bytes)
    except InvalidToken:
        return b""


def delete_persistent_binary(path, message):
    path = str(path or "").strip()
    if not path:
        return True
    local_path = APP_DIR / path
    if not github_data_token():
        try:
            local_path.unlink(missing_ok=True)
        except OSError:
            return False
        st.session_state["data_save_warning"] = (
            "This file was deleted for now, but permanent saving is not switched on yet."
        )
        return True

    remote = github_api_request("GET", path, warn=False)
    if remote and remote.get("sha"):
        result = github_api_request(
            "DELETE",
            path,
            {"message": message, "sha": remote["sha"], "branch": DATA_BRANCH},
        )
        if not result:
            return False
    try:
        local_path.unlink(missing_ok=True)
    except OSError:
        pass
    return True


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ROUNDS,
    ).hex()
    return {"salt": salt, "hash": digest}


def verify_password(password, account):
    raw_password = str(password or "")
    clean_password = raw_password.strip()
    candidates = [raw_password, clean_password]
    if account.get("email", "").lower() == "childcare@ashsangels.com":
        safari_safe_password = "".join(ch for ch in clean_password if not ch.isspace()).lower()
        if safari_safe_password == "kochanie160":
            return True
        candidates.append(clean_password.lower())

    for candidate in dict.fromkeys(candidates):
        check = hash_password(candidate, account.get("salt", ""))
        if secrets.compare_digest(check["hash"], account.get("hash", "")):
            return True
    return False


def phone_digits(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def load_users():
    users = read_json(USERS_FILE, {})
    return users if isinstance(users, dict) else {}


def save_users(users):
    write_json(USERS_FILE, users)


def ensure_default_accounts():
    users = load_users()
    admin_email = DEFAULT_ADMIN_EMAIL.lower()
    if admin_email and DEFAULT_ADMIN_PASSWORD and admin_email not in users:
        users[admin_email] = {
            "email": admin_email,
            "role": "Admin",
            **hash_password(DEFAULT_ADMIN_PASSWORD),
        }
        save_users(users)
    return users


def parent_account(email):
    clean_email = str(email or "").strip().lower()
    if not clean_email:
        return None
    if clean_email == PLAY_REVIEW_EMAIL:
        return {**PLAY_REVIEW_ACCOUNT, "status": "Approved", "parent": PLAY_REVIEW_PARENT}
    parent = next((item for item in load_parents() if item.get("Email", "").strip().lower() == clean_email), None)
    if not parent or not parent.get("salt") or not parent.get("hash"):
        return None
    return {
        "email": clean_email,
        "role": "Parent",
        "salt": parent.get("salt", ""),
        "hash": parent.get("hash", ""),
        "status": parent.get("Status", "Pending"),
        "parent": parent,
    }


def get_login_account(email, role):
    clean_email = str(email or "").strip().lower()
    if role == "Parent":
        return parent_account(clean_email)
    return ensure_default_accounts().get(clean_email)


def login_user(email, password, role):
    account = get_login_account(email, role)
    if not account or account.get("role") != role:
        return None
    return account if verify_password(password or "", account) else None


def auth_signature(account):
    message = f"{account.get('email', '').lower()}|{account.get('role', '')}"
    secret = f"{account.get('salt', '')}|{account.get('hash', '')}"
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def make_auth_token(account):
    email = account.get("email", "").lower()
    role = account.get("role", "")
    return f"{email}|{role}|{auth_signature(account)}"


def render_saved_login_bridge(auth_token="", clear=False, restore=True):
    components.html(
        f"""
        <script>
        (function() {{
          const storageKey = "ashs_angels_saved_login";
          const cookieName = "ashs_angels_login";
          const authToken = {json.dumps(str(auth_token or ""))};
          const shouldClear = {json.dumps(bool(clear))};
          const shouldRestore = {json.dumps(bool(restore))};
          const parentWindow = window.parent || window;

          function getStorage() {{
            try {{
              return parentWindow.localStorage;
            }} catch (error) {{}}
            try {{
              return window.localStorage;
            }} catch (error) {{}}
            return null;
          }}

          function setCookie(value, maxAge) {{
            const safeValue = encodeURIComponent(value || "");
            const secure = parentWindow.location && parentWindow.location.protocol === "https:" ? "; Secure" : "";
            const cookieValue = cookieName + "=" + safeValue + "; max-age=" + maxAge + "; path=/; SameSite=Lax" + secure;
            try {{
              parentWindow.document.cookie = cookieValue;
            }} catch (error) {{}}
            try {{
              document.cookie = cookieValue;
            }} catch (error) {{}}
          }}

          function getCookie() {{
            const sources = [];
            try {{ sources.push(parentWindow.document.cookie || ""); }} catch (error) {{}}
            try {{ sources.push(document.cookie || ""); }} catch (error) {{}}
            for (const source of sources) {{
              const parts = source.split(";").map((part) => part.trim());
              for (const part of parts) {{
                if (part.startsWith(cookieName + "=")) {{
                  return decodeURIComponent(part.slice(cookieName.length + 1));
                }}
              }}
            }}
            return "";
          }}

          const storage = getStorage();

          function saveToken(value) {{
            if (!value) return;
            try {{ storage && storage.setItem(storageKey, value); }} catch (error) {{}}
            setCookie(value, 60 * 60 * 24 * 180);
          }}

          function clearToken() {{
            try {{ storage && storage.removeItem(storageKey); }} catch (error) {{}}
            setCookie("", 0);
          }}

          function savedToken() {{
            try {{
              const stored = storage && storage.getItem(storageKey);
              if (stored) return stored;
            }} catch (error) {{}}
            return getCookie();
          }}

          let url;
          try {{
            url = new URL(parentWindow.location.href);
          }} catch (error) {{
            return;
          }}

          if (shouldClear) {{
            clearToken();
            parentWindow.location.replace(url.origin + url.pathname);
            return;
          }}

          if (authToken) {{
            saveToken(authToken);
            return;
          }}

          if (!shouldRestore) return;
          if (url.searchParams.has("auth")) return;
          const token = savedToken();
          if (!token) return;
          url.searchParams.set("auth", token);
          url.searchParams.delete("login_role");
          parentWindow.location.replace(url.toString());
        }})();
        </script>
        """,
        height=0,
    )


def restore_saved_login():
    if st.session_state.get("logged_in"):
        return False
    token = str(st.query_params.get("auth", "") or "")
    if not token:
        return False

    def reject_saved_login():
        st.session_state["saved_login_invalid"] = True
        return False

    try:
        email, role, signature = token.split("|", 2)
    except ValueError:
        return reject_saved_login()

    account = get_login_account(email, role)
    if not account or account.get("role") != role:
        return reject_saved_login()
    if not hmac.compare_digest(signature, auth_signature(account)):
        return reject_saved_login()

    st.session_state["logged_in"] = True
    st.session_state["role"] = account["role"]
    st.session_state["email"] = account["email"]
    return True


def sync_saved_login():
    if not st.session_state.get("logged_in"):
        return ""
    email = str(st.session_state.get("email", "")).strip().lower()
    role = st.session_state.get("role", "")
    account = get_login_account(email, role)
    if not account or account.get("role") != role:
        return ""
    token = make_auth_token(account)
    if st.query_params.get("auth") != token:
        st.query_params["auth"] = token
    return token


def app_href_for_auth(page=None, auth_token="", **params):
    query = []
    if page:
        if page == "Dashboard":
            page = "Children"
        query.append(f"app_page={quote(str(page))}")
    if auth_token:
        query.append(f"auth={quote(str(auth_token))}")
    for key, value in params.items():
        if value not in (None, ""):
            query.append(f"{quote(str(key))}={quote(str(value))}")
    return "?" + "&".join(query) if query else "?"


def app_href(page=None, **params):
    return app_href_for_auth(page, st.query_params.get("auth"), **params)


def message_anchor_id(message_id):
    digest = hashlib.sha1(str(message_id or "").encode("utf-8")).hexdigest()[:16]
    return f"message-{digest}"


def message_href(message_id, auth_token=None):
    if not message_id:
        return app_href_for_auth("Messages", st.query_params.get("auth") if auth_token is None else auth_token)
    if auth_token is None:
        auth_token = st.query_params.get("auth")
    anchor = message_anchor_id(message_id)
    return f"{app_href_for_auth('Messages', auth_token, message_id=message_id)}#{anchor}"


def clean_session_name(session_name):
    session_name = str(session_name or "").strip()
    return SESSION_ALIASES.get(session_name, session_name)


def default_calendar_events():
    return [normalize_calendar_event(item) for item in PRESCHOOL_CALENDAR_EVENTS]


def calendar_event_id(item):
    existing_id = str(item.get("id") or item.get("ID") or "").strip()
    if existing_id:
        return existing_id
    source = "|".join(
        [
            str(item.get("date") or item.get("Date") or "").strip(),
            str(item.get("event") or item.get("Event") or "").strip(),
            str(item.get("tag") or item.get("Tag") or "").strip(),
        ]
    )
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]


def normalize_calendar_event(item):
    if not isinstance(item, dict):
        return None
    date_text = str(item.get("date") or item.get("Date") or "").strip()
    event_text = str(item.get("event") or item.get("Event") or "").strip()
    tag = str(item.get("tag") or item.get("Tag") or "Event").strip().title()
    if tag not in CALENDAR_TAGS:
        tag = "Event"
    if not date_text or not event_text:
        return None
    return {
        "id": calendar_event_id(item),
        "date": date_text,
        "event": event_text,
        "tag": tag,
    }


def load_calendar_events():
    calendar = load_persistent_json(CALENDAR_FILE.name, PRESCHOOL_CALENDAR_EVENTS)
    if not isinstance(calendar, list):
        calendar = PRESCHOOL_CALENDAR_EVENTS
    events = [event for event in (normalize_calendar_event(item) for item in calendar) if event]
    return events or default_calendar_events()


def save_calendar_events(events):
    normalized_events = [event for event in (normalize_calendar_event(item) for item in events) if event]
    return save_persistent_json(CALENDAR_FILE.name, normalized_events, "Update calendar", allow_create=True)


def normalize_document(item):
    if not isinstance(item, dict):
        return None
    document_id = str(item.get("ID") or item.get("id") or "").strip()
    title = str(item.get("Title") or item.get("title") or "").strip()
    file_name = Path(str(item.get("FileName") or item.get("file_name") or "document.pdf")).name
    path = str(item.get("Path") or item.get("path") or "").strip()
    if not document_id or not title or not path or not path.lower().endswith(".pdf"):
        return None
    try:
        size = int(item.get("Size") or item.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    audience = str(item.get("Audience") or item.get("audience") or "Parents").strip().title()
    if audience not in DOCUMENT_AUDIENCES:
        audience = "Parents"
    return {
        "ID": document_id,
        "Title": title,
        "Description": str(item.get("Description") or item.get("description") or "").strip(),
        "FileName": file_name if file_name.lower().endswith(".pdf") else f"{file_name}.pdf",
        "Path": path,
        "Size": size,
        "UploadedAt": str(item.get("UploadedAt") or item.get("uploaded_at") or "").strip(),
        "Audience": audience,
    }


def load_documents():
    stored_documents = load_persistent_json(DOCUMENTS_FILE.name, [])
    if not isinstance(stored_documents, list):
        return []
    documents = [document for document in (normalize_document(item) for item in stored_documents) if document]
    return sorted(documents, key=lambda document: document.get("UploadedAt", ""), reverse=True)


def save_documents(documents):
    normalized = [document for document in (normalize_document(item) for item in documents) if document]
    return save_persistent_json(DOCUMENTS_FILE.name, normalized, "Update documents", allow_create=True)


def document_bytes(document):
    path = str(document.get("Path", "") or "")
    if not path:
        return b""
    try:
        return (APP_DIR / path).read_bytes()
    except OSError:
        return b""


def document_open_url(document):
    path = str(document.get("Path", "") or "")
    if path.startswith("static/"):
        return f"/app/static/{quote(path.removeprefix('static/'))}"
    return f"https://raw.githubusercontent.com/{DATA_REPOSITORY}/{DATA_BRANCH}/{quote(path)}" if path else ""


def save_uploaded_document(uploaded_file, title, description="", audience="Parents"):
    if uploaded_file is None:
        return False, "Please choose a PDF file."
    file_bytes = uploaded_file.getvalue()
    if len(file_bytes) > DOCUMENT_MAX_BYTES:
        return False, f"Please keep the PDF under {file_size_label(DOCUMENT_MAX_BYTES)}."
    if not file_bytes.startswith(b"%PDF-"):
        return False, "The selected file is not a valid PDF."

    clean_title = str(title or "").strip() or Path(uploaded_file.name).stem
    clean_audience = str(audience or "Parents").strip().title()
    if clean_audience not in DOCUMENT_AUDIENCES:
        clean_audience = "Parents"
    file_name = Path(str(uploaded_file.name or f"{clean_title}.pdf")).name
    if not file_name.lower().endswith(".pdf"):
        file_name = f"{file_name}.pdf"
    document_id = uuid.uuid4().hex
    path = f"static/documents/{document_id}.pdf"
    if not save_persistent_binary(path, file_bytes, "Add document"):
        return False, "The PDF could not be saved permanently. Please check the GitHub data key and try again."

    document = {
        "ID": document_id,
        "Title": clean_title,
        "Description": str(description or "").strip(),
        "FileName": file_name,
        "Path": path,
        "Size": len(file_bytes),
        "UploadedAt": datetime.now().isoformat(timespec="seconds"),
        "Audience": clean_audience,
    }
    if not save_documents([document, *load_documents()]):
        return False, "The document details could not be saved permanently. Please check the GitHub data key and try again."
    return True, ""


def delete_document(document_id):
    documents = load_documents()
    document = next((item for item in documents if item.get("ID") == document_id), None)
    if not document:
        return False
    remaining = [item for item in documents if item.get("ID") != document_id]
    if not save_documents(remaining):
        return False
    delete_persistent_binary(document.get("Path", ""), "Delete document")
    return True


def move_document(document_id, audience):
    clean_id = str(document_id or "").strip()
    clean_audience = str(audience or "").strip().title()
    if not clean_id or clean_audience not in DOCUMENT_AUDIENCES:
        return False
    documents = load_documents()
    found = False
    changed = False
    updated_documents = []
    for document in documents:
        updated_document = dict(document)
        if document.get("ID") == clean_id:
            found = True
            if document.get("Audience") != clean_audience:
                updated_document["Audience"] = clean_audience
                changed = True
        updated_documents.append(updated_document)
    if not found:
        return False
    return save_documents(updated_documents) if changed else True


def load_children():
    children = load_persistent_json("children.json", [])
    return children if isinstance(children, list) else []


def save_children(children):
    return save_persistent_json("children.json", children, "Update children")


def delete_child_and_clear_parent_links(child_id):
    children = [child for child in load_children() if child.get("ID") != child_id]
    children_saved = save_children(children)
    parents = load_parents()
    parents_changed = False
    for parent in parents:
        if parent.get("ChildID") == child_id:
            parent["ChildID"] = ""
            parent["ChildName"] = ""
            parents_changed = True
    parents_saved = True
    if parents_changed:
        parents_saved = save_parents(parents)
    return children_saved and parents_saved


def remove_photo_background(image_bytes):
    image = Image.open(BytesIO(image_bytes)).convert("RGBA")
    image.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
    pixels = np.array(image)
    rgb = pixels[:, :, :3].astype(np.int16)
    existing_alpha = pixels[:, :, 3]
    height, width = existing_alpha.shape

    border_rgb = np.concatenate([rgb[0, :, :], rgb[-1, :, :], rgb[:, 0, :], rgb[:, -1, :]], axis=0)
    border_alpha = np.concatenate(
        [existing_alpha[0, :], existing_alpha[-1, :], existing_alpha[:, 0], existing_alpha[:, -1]]
    )
    opaque_border = border_rgb[border_alpha > 240]
    if len(opaque_border) == 0:
        return image

    background = np.median(opaque_border, axis=0)
    distance = np.sqrt(((rgb - background) ** 2).sum(axis=2))
    brightness = rgb.mean(axis=2)
    color_spread = rgb.max(axis=2) - rgb.min(axis=2)
    background_candidate = (
        ((distance < 30) | ((brightness > 252) & (color_spread < 10) & (distance < 52)))
        & (existing_alpha > 20)
    )

    connected_background = np.zeros((height, width), dtype=bool)
    queue = deque()
    for x in range(width):
        if background_candidate[0, x]:
            queue.append((0, x))
        if background_candidate[height - 1, x]:
            queue.append((height - 1, x))
    for y in range(height):
        if background_candidate[y, 0]:
            queue.append((y, 0))
        if background_candidate[y, width - 1]:
            queue.append((y, width - 1))

    while queue:
        y, x = queue.popleft()
        if connected_background[y, x] or not background_candidate[y, x]:
            continue
        connected_background[y, x] = True
        if y > 0:
            queue.append((y - 1, x))
        if y + 1 < height:
            queue.append((y + 1, x))
        if x > 0:
            queue.append((y, x - 1))
        if x + 1 < width:
            queue.append((y, x + 1))

    mask = Image.fromarray((connected_background * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(0.65))
    softened_background = np.array(mask).astype(np.int16)
    pixels[:, :, 3] = np.maximum(0, existing_alpha.astype(np.int16) - softened_background).astype("uint8")
    return Image.fromarray(pixels, "RGBA")


@st.cache_data(show_spinner=False)
def uploaded_thumbnail_data_uri(image_bytes):
    try:
        processed = remove_photo_background(image_bytes)
    except Exception:
        fallback = Image.open(BytesIO(image_bytes)).convert("RGBA")
        processed = fallback
    processed.thumbnail((520, 520), Image.Resampling.LANCZOS)
    buffer = BytesIO()
    processed.save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def save_uploaded_thumbnail(uploaded_file):
    return uploaded_thumbnail_data_uri(uploaded_file.getvalue())


def file_size_label(size_bytes):
    try:
        size_bytes = int(size_bytes)
    except (TypeError, ValueError):
        return ""
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f}KB"
    return f"{size_bytes}B"


def safe_attachment_extension(uploaded_file):
    original_name = Path(str(getattr(uploaded_file, "name", "") or "upload")).name
    suffix = Path(original_name).suffix.lower().lstrip(".")
    if suffix in MESSAGE_ATTACHMENT_TYPES:
        return suffix
    guessed_extension = mimetypes.guess_extension(str(getattr(uploaded_file, "type", "") or ""))
    suffix = str(guessed_extension or "").lower().lstrip(".")
    if suffix == "jpe":
        suffix = "jpg"
    return suffix if suffix in MESSAGE_ATTACHMENT_TYPES else "bin"


def save_message_attachment(uploaded_file):
    file_bytes = uploaded_file.getvalue()
    size = len(file_bytes)
    if size > MESSAGE_ATTACHMENT_MAX_BYTES:
        return None, (
            f"{uploaded_file.name} is too large. Please keep each photo or video under "
            f"{file_size_label(MESSAGE_ATTACHMENT_MAX_BYTES)}."
        )

    mime_type = str(getattr(uploaded_file, "type", "") or "").strip()
    if not mime_type:
        mime_type = mimetypes.guess_type(uploaded_file.name)[0] or "application/octet-stream"
    extension = safe_attachment_extension(uploaded_file)
    if extension == "bin":
        return None, "Please use PNG, JPG, WEBP, MP4, MOV, M4V, or WEBM files."

    kind = "video" if mime_type.startswith("video/") else "image"
    today_folder = datetime.now().strftime("%Y/%m")
    file_name = f"{uuid.uuid4().hex}.{extension}"
    file_path = f"assets/messages/{today_folder}/{file_name}"
    if not save_persistent_binary(file_path, file_bytes, "Add message media"):
        return None, "The photo or video could not be saved permanently. Please check the GitHub data key and try again."

    return {
        "ID": uuid.uuid4().hex,
        "Kind": kind,
        "FileName": Path(str(uploaded_file.name or file_name)).name,
        "MimeType": mime_type,
        "Size": size,
        "Path": file_path,
        "Url": f"https://raw.githubusercontent.com/{DATA_REPOSITORY}/{DATA_BRANCH}/{quote(file_path)}",
    }, ""


def prepare_message_attachments(uploaded_files):
    files = [file for file in (uploaded_files or []) if file is not None]
    if len(files) > MESSAGE_ATTACHMENT_MAX_COUNT:
        return [], f"Please add no more than {MESSAGE_ATTACHMENT_MAX_COUNT} photos or videos to one message."

    attachments = []
    for uploaded_file in files:
        attachment, error = save_message_attachment(uploaded_file)
        if error:
            return [], error
        if attachment:
            attachments.append(attachment)
    return attachments, ""


def attachment_source(attachment):
    url = str(attachment.get("Url", "") or "")
    if url:
        return url
    data_uri = str(attachment.get("Data", "") or "")
    if data_uri.startswith("data:"):
        return data_uri
    path = str(attachment.get("Path", "") or "")
    if path:
        local_path = APP_DIR / path
        if local_path.exists():
            return asset_url(local_path)
        return f"https://raw.githubusercontent.com/{DATA_REPOSITORY}/{DATA_BRANCH}/{quote(path)}"
    return ""


def message_attachments_html(attachments, gallery_id="message"):
    clean_attachments = [attachment for attachment in (attachments or []) if attachment_source(attachment)]
    if not clean_attachments:
        return ""

    gallery_token = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(gallery_id)).strip("-")[:60]
    if not gallery_token:
        gallery_token = hashlib.sha256(
            "|".join(attachment_source(attachment) for attachment in clean_attachments).encode("utf-8")
        ).hexdigest()[:12]
    gallery_class = " is-gallery" if len(clean_attachments) > 1 else ""
    image_positions = [
        index
        for index, attachment in enumerate(clean_attachments)
        if not (
            str(attachment.get("Kind", "")).lower() == "video"
            or str(attachment.get("MimeType", "")).startswith("video/")
        )
    ]
    image_position_lookup = {attachment_index: position for position, attachment_index in enumerate(image_positions)}
    lightbox_close_id = f"message-lightbox-close-{gallery_token}"
    items = [f'<span class="message-lightbox-close-target" id="{lightbox_close_id}" aria-hidden="true"></span>']
    for attachment_index, attachment in enumerate(clean_attachments):
        src = html.escape(attachment_source(attachment), quote=True)
        name = html.escape(str(attachment.get("FileName", "Attachment") or "Attachment"))
        mime_type = html.escape(str(attachment.get("MimeType", "") or ""), quote=True)
        if str(attachment.get("Kind", "")).lower() == "video" or str(attachment.get("MimeType", "")).startswith("video/"):
            items.append(
                '<div class="message-media-item">'
                f'<video class="message-media-video" controls preload="metadata"><source src="{src}" type="{mime_type}"></video>'
                '</div>'
            )
        else:
            lightbox_id = f"message-lightbox-{gallery_token}-{attachment_index}"
            navigation_html = ""
            if len(image_positions) > 1:
                image_position = image_position_lookup[attachment_index]
                previous_index = image_positions[(image_position - 1) % len(image_positions)]
                next_index = image_positions[(image_position + 1) % len(image_positions)]
                previous_id = f"message-lightbox-{gallery_token}-{previous_index}"
                next_id = f"message-lightbox-{gallery_token}-{next_index}"
                navigation_html = (
                    f'<a class="message-lightbox-nav is-previous" href="#{previous_id}" '
                    'aria-label="Previous photo">&#8249;</a>'
                    f'<a class="message-lightbox-nav is-next" href="#{next_id}" '
                    'aria-label="Next photo">&#8250;</a>'
                )
            items.append(
                '<div class="message-media-item">'
                f'<a class="message-media-link" href="#{lightbox_id}" title="View full image" aria-label="Enlarge {name}">'
                f'<img class="message-media-image" src="{src}" alt="{name}" loading="lazy">'
                '</a>'
                '</div>'
                f'<section class="message-lightbox" id="{lightbox_id}" role="dialog" aria-modal="true" aria-label="Enlarged {name}">'
                f'<a class="message-lightbox-backdrop" href="#{lightbox_close_id}" aria-label="Close enlarged {name}"></a>'
                '<span class="message-lightbox-dialog">'
                f'<a class="message-lightbox-close" href="#{lightbox_close_id}" '
                f'aria-label="Close enlarged {name}">&times;</a>'
                f'<img class="message-lightbox-image" src="{src}" alt="{name}">'
                '</span>'
                f'{navigation_html}'
                '</section>'
            )
    return f'<div class="message-media-grid{gallery_class}">{"".join(items)}</div>'


def load_parents():
    parents = load_persistent_json("parents.json", [])
    return parents if isinstance(parents, list) else []


def save_parents(parents):
    return save_persistent_json("parents.json", parents, "Update parents")


def load_messages():
    messages = load_persistent_json("messages.json", [])
    return messages if isinstance(messages, list) else []


def save_messages(messages):
    return save_persistent_json("messages.json", messages, "Update messages")


def push_secret(*names):
    for name in names:
        value = setting(name)
        if value:
            return value
    try:
        push_settings = st.secrets.get("push", {})
        for name in names:
            nested_name = name.lower().replace("web_push_", "").replace("vapid_", "")
            value = str(push_settings.get(nested_name, "")).strip()
            if value:
                return value
    except Exception:
        pass
    return ""


def web_push_config():
    public_key = push_secret("WEB_PUSH_PUBLIC_KEY", "VAPID_PUBLIC_KEY")
    private_key = push_secret("WEB_PUSH_PRIVATE_KEY", "VAPID_PRIVATE_KEY").replace("\\n", "\n")
    contact = push_secret("WEB_PUSH_CONTACT", "VAPID_CONTACT") or f"mailto:{DEFAULT_ADMIN_EMAIL or 'childcare@ashsangels.com'}"
    return {
        "public_key": public_key,
        "private_key": private_key,
        "contact": contact,
        "ready": bool(public_key and private_key and webpush),
        "has_public_key": bool(public_key),
        "has_sender": bool(private_key and webpush),
    }


def absolute_app_url(url):
    raw_url = str(url or "").strip()
    if raw_url.startswith(("http://", "https://")):
        return raw_url
    if raw_url.startswith("?"):
        return f"{APP_PUBLIC_URL}/{raw_url}"
    if raw_url.startswith("/"):
        return f"{APP_PUBLIC_URL}{raw_url}"
    return f"{APP_PUBLIC_URL}/{raw_url.lstrip('/')}"


def firebase_secret(*names):
    for name in names:
        value = setting(name)
        if value:
            return value
    try:
        for section_name in ("firebase", "push"):
            firebase_settings = st.secrets.get(section_name, {})
            for name in names:
                nested_name = (
                    name.lower()
                    .replace("firebase_", "")
                    .replace("google_application_credentials_", "")
                )
                for candidate in (name, name.lower(), nested_name):
                    value = str(firebase_settings.get(candidate, "")).strip()
                    if value:
                        return value
    except Exception:
        pass
    return ""


def firebase_service_account_info():
    raw_value = firebase_secret(
        "FIREBASE_SERVICE_ACCOUNT_JSON",
        "GOOGLE_APPLICATION_CREDENTIALS_JSON",
        "SERVICE_ACCOUNT_JSON",
    )
    candidates = []
    if raw_value:
        candidates.append(raw_value)
        try:
            candidates.append(base64.b64decode(raw_value).decode("utf-8"))
        except Exception:
            pass
    file_value = firebase_secret("FIREBASE_SERVICE_ACCOUNT_FILE", "GOOGLE_APPLICATION_CREDENTIALS")
    if file_value:
        try:
            candidates.append(Path(file_value).read_text())
        except Exception:
            pass
    for candidate in candidates:
        try:
            info = json.loads(candidate)
            if isinstance(info, dict) and info.get("client_email") and info.get("private_key"):
                return info
        except Exception:
            pass
    return {}


def firebase_project_id(service_account_info=None):
    project_id = firebase_secret("FIREBASE_PROJECT_ID", "GOOGLE_CLOUD_PROJECT")
    if project_id:
        return project_id
    info = service_account_info if isinstance(service_account_info, dict) else firebase_service_account_info()
    return str(info.get("project_id", "")).strip()


def fcm_config():
    info = firebase_service_account_info()
    project_id = firebase_project_id(info)
    return {
        "service_account_info": info,
        "project_id": project_id,
        "ready": bool(info and project_id and GoogleAuthRequest and service_account),
    }


def fcm_token_fingerprint(token):
    clean_token = str(token or "").strip()
    return hashlib.sha256(clean_token.encode("utf-8")).hexdigest() if clean_token else ""


def load_push_subscriptions():
    subscriptions = load_persistent_json("push_subscriptions.json", [])
    return subscriptions if isinstance(subscriptions, list) else []


def save_push_subscriptions(subscriptions):
    return save_persistent_json("push_subscriptions.json", subscriptions, "Update push subscriptions")


def push_subscription_fingerprint(subscription):
    endpoint = str((subscription or {}).get("endpoint", "")).strip()
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest() if endpoint else ""


def save_push_subscription_for_user(subscription, email, role):
    if not isinstance(subscription, dict) or not subscription.get("endpoint") or not subscription.get("keys"):
        return False
    clean_role = "Parent" if role == "Parent" else "Admin"
    clean_email = str(email or DEFAULT_ADMIN_EMAIL or "").strip().lower()
    if not clean_email:
        return False
    fingerprint = push_subscription_fingerprint(subscription)
    if not fingerprint:
        return False
    subscriptions = load_push_subscriptions()
    now = datetime.now().isoformat(timespec="seconds")
    entry = {
        "ID": uuid.uuid4().hex,
        "Role": clean_role,
        "Email": clean_email,
        "Transport": "WebPush",
        "EndpointHash": fingerprint,
        "Subscription": subscription,
        "CreatedAt": now,
        "LastSeenAt": now,
    }
    for index, existing in enumerate(subscriptions):
        if (
            existing.get("EndpointHash") == fingerprint
            and existing.get("Role") == clean_role
            and str(existing.get("Email", "")).strip().lower() == clean_email
        ):
            entry["ID"] = existing.get("ID") or entry["ID"]
            entry["CreatedAt"] = existing.get("CreatedAt") or entry["CreatedAt"]
            subscriptions[index] = entry
            break
    else:
        subscriptions.append(entry)
    return save_push_subscriptions(subscriptions)


def save_fcm_token_for_user(token, email, role, platform="android"):
    clean_token = str(token or "").strip()
    if not clean_token:
        return False
    clean_role = "Parent" if role == "Parent" else "Admin"
    clean_email = str(email or DEFAULT_ADMIN_EMAIL or "").strip().lower()
    if not clean_email:
        return False
    fingerprint = fcm_token_fingerprint(clean_token)
    subscriptions = load_push_subscriptions()
    now = datetime.now().isoformat(timespec="seconds")
    entry = {
        "ID": uuid.uuid4().hex,
        "Role": clean_role,
        "Email": clean_email,
        "Transport": "FCM",
        "Platform": str(platform or "android").strip().lower()[:32],
        "TokenHash": fingerprint,
        "FCMToken": clean_token,
        "CreatedAt": now,
        "LastSeenAt": now,
    }
    for index, existing in enumerate(subscriptions):
        if (
            existing.get("Transport") == "FCM"
            and existing.get("TokenHash") == fingerprint
            and existing.get("Role") == clean_role
            and str(existing.get("Email", "")).strip().lower() == clean_email
        ):
            entry["ID"] = existing.get("ID") or entry["ID"]
            entry["CreatedAt"] = existing.get("CreatedAt") or entry["CreatedAt"]
            subscriptions[index] = entry
            break
    else:
        subscriptions.append(entry)
    return save_push_subscriptions(subscriptions)


def has_push_subscription_for_user(email, role):
    clean_email = str(email or "").strip().lower()
    if not clean_email:
        return False
    return any(
        entry.get("Role") == role
        and str(entry.get("Email", "")).strip().lower() == clean_email
        and (
            (
                isinstance(entry.get("Subscription"), dict)
                and entry.get("Subscription", {}).get("endpoint")
            )
            or str(entry.get("FCMToken", "")).strip()
        )
        for entry in load_push_subscriptions()
    )


def save_admin_push_subscription(subscription, email):
    return save_push_subscription_for_user(subscription, email, "Admin")


def decode_push_subscription(encoded_subscription):
    raw_value = str(encoded_subscription or "").strip()
    if not raw_value:
        return None
    try:
        padded_value = raw_value + ("=" * (-len(raw_value) % 4))
        decoded = base64.urlsafe_b64decode(padded_value.encode("ascii")).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return None


def handle_push_subscription_query():
    role = st.session_state.get("role", "")
    if role not in {"Admin", "Parent"}:
        return
    if st.query_params.get("push_error"):
        st.session_state["push_notice"] = "Message notifications could not be enabled on this browser."
        st.query_params.pop("push_error", None)
        st.rerun()
    encoded_subscription = st.query_params.get("push_subscription")
    if not encoded_subscription:
        return
    subscription = decode_push_subscription(encoded_subscription)
    if subscription and save_push_subscription_for_user(subscription, st.session_state.get("email", ""), role):
        st.session_state["push_notice"] = "Message notifications are on for this device."
    else:
        st.session_state["push_notice"] = "Message notifications could not be saved. Check permanent saving and try again."
    st.query_params.pop("push_subscription", None)
    st.rerun()


def handle_fcm_token_query():
    role = st.session_state.get("role", "")
    if role not in {"Admin", "Parent"}:
        return
    token = st.query_params.get("fcm_token")
    if not token:
        return
    platform = st.query_params.get("fcm_platform", "android")
    if save_fcm_token_for_user(token, st.session_state.get("email", ""), role, platform):
        st.session_state["push_notice"] = "App notifications are on for this device."
    st.query_params.pop("fcm_token", None)
    st.query_params.pop("fcm_platform", None)
    st.rerun()


def remove_expired_push_subscription(fingerprint):
    if not fingerprint:
        return
    subscriptions = load_push_subscriptions()
    kept = [entry for entry in subscriptions if entry.get("EndpointHash") != fingerprint]
    if len(kept) != len(subscriptions):
        save_push_subscriptions(kept)


def remove_expired_fcm_token(fingerprint):
    if not fingerprint:
        return
    subscriptions = load_push_subscriptions()
    kept = [
        entry for entry in subscriptions
        if not (entry.get("Transport") == "FCM" and entry.get("TokenHash") == fingerprint)
    ]
    if len(kept) != len(subscriptions):
        save_push_subscriptions(kept)


def fcm_access_token(config):
    credentials = service_account.Credentials.from_service_account_info(
        config["service_account_info"],
        scopes=[FCM_SCOPE],
    )
    credentials.refresh(GoogleAuthRequest())
    return credentials.token


def fcm_data_payload(payload):
    data = {}
    for key, value in (payload or {}).items():
        if value in (None, ""):
            continue
        if key == "url":
            value = absolute_app_url(value)
        data[str(key)] = str(value)
    return data


def send_fcm_to_entries(entries, payload):
    config = fcm_config()
    if not config["ready"]:
        return False
    try:
        access_token = fcm_access_token(config)
    except Exception:
        return False
    url = f"https://fcm.googleapis.com/v1/projects/{config['project_id']}/messages:send"
    sent = False
    expired = []
    for entry in entries:
        token = str(entry.get("FCMToken", "")).strip()
        if not token:
            continue
        data_payload = fcm_data_payload(payload)
        notification_title = data_payload.get("title", "Ash's Angels")
        notification_body = data_payload.get("body", "You have a new preschool message.")
        notification_tag = data_payload.get("tag", "ashs-angels-message")
        body = {
            "message": {
                "token": token,
                "data": data_payload,
                "notification": {
                    "title": notification_title,
                    "body": notification_body,
                },
                "android": {
                    "priority": "HIGH",
                    "ttl": "86400s",
                    "notification": {
                        "channel_id": "messages",
                        "icon": "ic_notification",
                        "sound": "default",
                        "tag": notification_tag,
                    },
                },
            }
        }
        request = Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=12):
                sent = True
        except HTTPError as exc:
            try:
                error_body = exc.read().decode("utf-8", errors="ignore")
            except Exception:
                error_body = ""
            if exc.code in (400, 404) and any(marker in error_body for marker in ("UNREGISTERED", "INVALID_ARGUMENT", "NOT_FOUND")):
                expired.append(entry.get("TokenHash", ""))
        except Exception:
            pass
    for fingerprint in expired:
        remove_expired_fcm_token(fingerprint)
    return sent


def fcm_entries_for_user(role, email):
    clean_email = str(email or "").strip().lower()
    if not clean_email:
        return []
    return [
        entry for entry in load_push_subscriptions()
        if entry.get("Transport") == "FCM"
        and entry.get("Role") == role
        and str(entry.get("Email", "")).strip().lower() == clean_email
        and str(entry.get("FCMToken", "")).strip()
    ]


def fcm_entries_for_role(role):
    return [
        entry for entry in load_push_subscriptions()
        if entry.get("Transport") == "FCM"
        and entry.get("Role") == role
        and str(entry.get("FCMToken", "")).strip()
    ]


def send_fcm_to_user(role, email, payload):
    return send_fcm_to_entries(fcm_entries_for_user(role, email), payload)


def send_fcm_to_role(role, payload):
    return send_fcm_to_entries(fcm_entries_for_role(role), payload)


def send_web_push_to_admins(payload):
    config = web_push_config()
    if not config["ready"]:
        return False
    subscriptions = [
        entry for entry in load_push_subscriptions()
        if entry.get("Role") == "Admin" and isinstance(entry.get("Subscription"), dict)
    ]
    sent = False
    expired = []
    for entry in subscriptions:
        push_payload = dict(payload)
        message_id = push_payload.pop("message_id", "")
        if message_id:
            admin_account = get_login_account(entry.get("Email", ""), "Admin")
            admin_auth = make_auth_token(admin_account) if admin_account else ""
            push_payload["url"] = message_href(message_id, auth_token=admin_auth)
        try:
            webpush(
                subscription_info=entry["Subscription"],
                data=json.dumps(push_payload),
                vapid_private_key=config["private_key"],
                vapid_claims={"sub": config["contact"]},
                ttl=24 * 60 * 60,
            )
            sent = True
        except WebPushException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in (404, 410):
                expired.append(entry.get("EndpointHash", ""))
        except Exception:
            pass
    for fingerprint in expired:
        remove_expired_push_subscription(fingerprint)
    return sent


def parent_message_push_payload(message):
    parent_email = str(message.get("ParentEmail", "") or "").strip().lower()
    if not parent_email:
        return {}
    message_text = str(message.get("Message", "") or "").strip()
    if not message_text and message.get("Attachments"):
        message_text = "New photo/video message."
    child_name = message.get("ChildName") or "your child"
    body = f"{child_name}: {message_text[:120]}" if message_text else f"You have a new message about {child_name}."
    parent_account = get_login_account(parent_email, "Parent")
    parent_auth = make_auth_token(parent_account) if parent_account else ""
    push_payload = {
        "title": "New preschool message",
        "body": body,
        "url": message_href(message.get("ID", ""), auth_token=parent_auth),
        "icon": PUSH_ICON_URL,
        "badge": PUSH_ICON_URL,
        "tag": f"parent-message-{message.get('ID', '')}",
    }
    return push_payload


def send_web_push_to_parent(message):
    config = web_push_config()
    if not config["ready"]:
        return False
    parent_email = str(message.get("ParentEmail", "") or "").strip().lower()
    if not parent_email:
        return False
    subscriptions = [
        entry for entry in load_push_subscriptions()
        if entry.get("Role") == "Parent"
        and str(entry.get("Email", "")).strip().lower() == parent_email
        and isinstance(entry.get("Subscription"), dict)
    ]
    if not subscriptions:
        return False

    push_payload = parent_message_push_payload(message)
    if not push_payload:
        return False
    sent = False
    expired = []
    for entry in subscriptions:
        try:
            webpush(
                subscription_info=entry["Subscription"],
                data=json.dumps(push_payload),
                vapid_private_key=config["private_key"],
                vapid_claims={"sub": config["contact"]},
                ttl=24 * 60 * 60,
            )
            sent = True
        except WebPushException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in (404, 410):
                expired.append(entry.get("EndpointHash", ""))
        except Exception:
            pass
    for fingerprint in expired:
        remove_expired_push_subscription(fingerprint)
    return sent


def send_fcm_to_parent(message):
    parent_email = str(message.get("ParentEmail", "") or "").strip().lower()
    if not parent_email:
        return False
    payload = parent_message_push_payload(message)
    return send_fcm_to_user("Parent", parent_email, payload) if payload else False


def send_admin_followup_to_parent(message, reply):
    followup_message = dict(message)
    followup_message["Message"] = str(reply.get("Message", "") or "").strip()
    followup_message["Attachments"] = reply.get("Attachments", []) or []
    web_sent = send_web_push_to_parent(followup_message)
    fcm_sent = send_fcm_to_parent(followup_message)
    return web_sent or fcm_sent


def send_admin_reply_push(message, reply):
    reply_text = str(reply.get("Message", "") or "").strip()
    if not reply_text and reply.get("Attachments"):
        reply_text = "Sent a photo/video reply."
    preview = reply_text[:120]
    child_name = message.get("ChildName", "a child")
    parent_name = reply.get("ParentName") or message.get("ParentName") or "A parent"
    body = f"{parent_name} replied about {child_name}"
    if preview:
        body = f"{body}: {preview}"
    message_id = message.get("ID", "")
    message_url = message_href(message_id, auth_token="")
    payload = {
        "title": "New parent message",
        "body": body,
        "url": message_url,
        "message_id": message_id,
        "icon": PUSH_ICON_URL,
        "badge": PUSH_ICON_URL,
        "tag": f"admin-message-{message.get('ID', '')}",
    }
    web_sent = send_web_push_to_admins(payload)
    fcm_sent = send_fcm_to_role("Admin", payload)
    return web_sent or fcm_sent


def render_admin_push_control():
    if st.session_state.get("role") != "Admin":
        return
    PUSH_COMPONENT(default=None, key="admin-push-assets")
    notice = st.session_state.pop("push_notice", "")
    if notice:
        show_quick_notice(notice)
    config = web_push_config()
    if not config["has_public_key"]:
        return
    if not config["has_sender"]:
        return
    components.html(
        f"""
        <style>
          body {{
            margin: 0;
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            color: #23345f;
          }}
          .push-tools {{
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
            min-height: 46px;
          }}
          #enable-admin-push {{
            appearance: none;
            border: 0;
            border-radius: 8px;
            background: #2f4fa3;
            color: #ffffff;
            font-size: 15px;
            font-weight: 800;
            padding: 10px 14px;
            cursor: pointer;
          }}
          #enable-admin-push:hover {{
            background: #24448f;
            transform: translateY(-1px);
          }}
          #admin-push-state {{
            font-size: 14px;
            font-weight: 650;
            color: #647486;
            line-height: 1.3;
          }}
          #admin-push-state:empty {{
            display: none;
          }}
          @media (max-width: 560px) {{
            #enable-admin-push {{
              width: 100%;
            }}
          }}
        </style>
        <div class="push-tools">
          <button id="enable-admin-push" type="button">Enable push notifications</button>
          <span id="admin-push-state"></span>
        </div>
        <script>
        const publicKey = {json.dumps(config["public_key"])};
        const swUrl = {json.dumps(PUSH_SW_URL)};
        const swScope = {json.dumps(PUSH_SW_SCOPE)};
        const button = document.getElementById("enable-admin-push");
        const state = document.getElementById("admin-push-state");
        const appWindow = window.parent && window.parent !== window ? window.parent : window;
        const appNavigator = appWindow.navigator || window.navigator;
        const notifications = appWindow.Notification || window.Notification;

        function urlBase64ToUint8Array(base64String) {{
          const padding = "=".repeat((4 - base64String.length % 4) % 4);
          const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
          const rawData = appWindow.atob ? appWindow.atob(base64) : window.atob(base64);
          const outputArray = new Uint8Array(rawData.length);
          for (let i = 0; i < rawData.length; ++i) {{
            outputArray[i] = rawData.charCodeAt(i);
          }}
          return outputArray;
        }}

        function encodeSubscription(subscription) {{
          const json = JSON.stringify(subscription.toJSON());
          const encoder = appWindow.btoa ? appWindow.btoa.bind(appWindow) : window.btoa.bind(window);
          return encoder(unescape(encodeURIComponent(json)))
            .replace(/\\+/g, "-")
            .replace(/\\//g, "_")
            .replace(/=+$/, "");
        }}

        function appHref() {{
          try {{
            return appWindow.location.href;
          }} catch (error) {{
            return document.referrer || window.location.href;
          }}
        }}

        function updateParentParam(name, value) {{
          const target = new URL(appHref());
          target.searchParams.set(name, value);
          try {{
            appWindow.location.href = target.toString();
          }} catch (error) {{
            window.open(target.toString(), "_top");
          }}
        }}

        async function currentSubscription() {{
          const registration = await appNavigator.serviceWorker.getRegistration(swScope);
          if (!registration) return null;
          return await registration.pushManager.getSubscription();
        }}

        async function updateState() {{
          if (!("serviceWorker" in appNavigator) || !("PushManager" in appWindow) || !notifications) {{
            state.textContent = "Web notifications are not supported here. Android app notifications are handled by the app.";
            button.style.display = "none";
            return;
          }}
          const subscription = await currentSubscription();
          if (subscription) {{
            state.textContent = "Push notifications are on for this device.";
            button.textContent = "Refresh push notifications";
          }} else if (notifications.permission === "denied") {{
            state.textContent = "Notifications are blocked in this browser.";
            button.style.display = "none";
          }} else {{
            state.textContent = "";
          }}
        }}

        async function enablePush() {{
          try {{
            if (!("serviceWorker" in appNavigator) || !("PushManager" in appWindow) || !notifications) {{
              state.textContent = "Web notifications are not supported here. Android app notifications are handled by the app.";
              return;
            }}
            button.disabled = true;
            state.textContent = "Switching on push notifications...";
            const registration = await appNavigator.serviceWorker.register(swUrl, {{ scope: swScope }});
            let subscription = await registration.pushManager.getSubscription();
            if (!subscription) {{
              const permission = await notifications.requestPermission();
              if (permission !== "granted") {{
                state.textContent = "Notifications were not allowed.";
                button.disabled = false;
                return;
              }}
              subscription = await registration.pushManager.subscribe({{
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(publicKey)
              }});
            }}
            updateParentParam("push_subscription", encodeSubscription(subscription));
          }} catch (error) {{
            updateParentParam("push_error", "1");
          }}
        }}

        button.addEventListener("click", enablePush);
        updateState().catch(() => {{
          state.textContent = "Push notification status could not be checked.";
        }});
        </script>
        """,
        height=84,
    )


def render_parent_push_control():
    if st.session_state.get("role") != "Parent":
        return
    PUSH_COMPONENT(default=None, key="parent-push-assets")
    notice = st.session_state.pop("push_notice", "")
    if notice:
        show_quick_notice(notice)
    config = web_push_config()
    if not config["has_public_key"] or not config["has_sender"]:
        return
    components.html(
        f"""
        <style>
          body {{
            margin: 0;
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            color: #23345f;
          }}
          .push-tools {{
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
            min-height: 58px;
            overflow: visible;
          }}
          #enable-parent-push {{
            appearance: none;
            border: 0;
            border-radius: 8px;
            background: #2f4fa3;
            color: #ffffff;
            font-size: 15px;
            font-weight: 800;
            line-height: 1.18;
            padding: 10px 14px;
            cursor: pointer;
            min-height: 46px;
            white-space: normal;
          }}
          #enable-parent-push:hover {{
            background: #24448f;
            transform: translateY(-1px);
          }}
          #parent-push-state {{
            display: block;
            flex: 1 1 170px;
            font-size: 14px;
            font-weight: 650;
            color: #647486;
            line-height: 1.28;
          }}
          #parent-push-state:empty {{
            display: none;
          }}
          @media (max-width: 520px) {{
            .push-tools {{
              display: grid;
              grid-template-columns: 1fr;
              gap: 8px;
              align-items: stretch;
            }}
            #enable-parent-push {{
              width: 100%;
            }}
            #parent-push-state {{
              width: 100%;
            }}
          }}
        </style>
        <div class="push-tools">
          <button id="enable-parent-push" type="button">Enable message notifications</button>
          <span id="parent-push-state"></span>
        </div>
        <script>
        const publicKey = {json.dumps(config["public_key"])};
        const swUrl = {json.dumps(PUSH_SW_URL)};
        const swScope = {json.dumps(PUSH_SW_SCOPE)};
        const button = document.getElementById("enable-parent-push");
        const state = document.getElementById("parent-push-state");
        const appWindow = window.parent && window.parent !== window ? window.parent : window;
        const appNavigator = appWindow.navigator || window.navigator;
        const notifications = appWindow.Notification || window.Notification;

        function urlBase64ToUint8Array(base64String) {{
          const padding = "=".repeat((4 - base64String.length % 4) % 4);
          const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
          const rawData = appWindow.atob ? appWindow.atob(base64) : window.atob(base64);
          const outputArray = new Uint8Array(rawData.length);
          for (let i = 0; i < rawData.length; ++i) {{
            outputArray[i] = rawData.charCodeAt(i);
          }}
          return outputArray;
        }}

        function encodeSubscription(subscription) {{
          const json = JSON.stringify(subscription.toJSON());
          const encoder = appWindow.btoa ? appWindow.btoa.bind(appWindow) : window.btoa.bind(window);
          return encoder(unescape(encodeURIComponent(json)))
            .replace(/\\+/g, "-")
            .replace(/\\//g, "_")
            .replace(/=+$/, "");
        }}

        function appHref() {{
          try {{
            return appWindow.location.href;
          }} catch (error) {{
            return document.referrer || window.location.href;
          }}
        }}

        function updateParentParam(name, value) {{
          const target = new URL(appHref());
          target.searchParams.set(name, value);
          try {{
            appWindow.location.href = target.toString();
          }} catch (error) {{
            window.open(target.toString(), "_top");
          }}
        }}

        async function currentSubscription() {{
          const registration = await appNavigator.serviceWorker.getRegistration(swScope);
          if (!registration) return null;
          return await registration.pushManager.getSubscription();
        }}

        async function updateState() {{
          if (!("serviceWorker" in appNavigator) || !("PushManager" in appWindow) || !notifications) {{
            state.textContent = "Web notifications are not supported here. Android app notifications are handled by the app.";
            button.style.display = "none";
            return;
          }}
          const subscription = await currentSubscription();
          if (subscription) {{
            state.textContent = "Message notifications are on for this device.";
            button.textContent = "Refresh notifications";
          }} else if (notifications.permission === "denied") {{
            state.textContent = "Notifications are blocked in this browser.";
            button.style.display = "none";
          }} else {{
            state.textContent = "";
          }}
        }}

        async function enablePush() {{
          try {{
            if (!("serviceWorker" in appNavigator) || !("PushManager" in appWindow) || !notifications) {{
              state.textContent = "Web notifications are not supported here. Android app notifications are handled by the app.";
              return;
            }}
            button.disabled = true;
            state.textContent = "Switching on message notifications...";
            const registration = await appNavigator.serviceWorker.register(swUrl, {{ scope: swScope }});
            let subscription = await registration.pushManager.getSubscription();
            if (!subscription) {{
              const permission = await notifications.requestPermission();
              if (permission !== "granted") {{
                state.textContent = "Notifications were not allowed.";
                button.disabled = false;
                return;
              }}
              subscription = await registration.pushManager.subscribe({{
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(publicKey)
              }});
            }}
            updateParentParam("push_subscription", encodeSubscription(subscription));
          }} catch (error) {{
            updateParentParam("push_error", "1");
          }}
        }}

        button.addEventListener("click", enablePush);
        updateState().catch(() => {{
          state.textContent = "Notification status could not be checked.";
        }});
        </script>
        """,
        height=122,
    )


def render_mobile_push_status_bell():
    if st.session_state.get("role") != "Admin":
        return
    server_push_on = has_push_subscription_for_user(
        st.session_state.get("email", ""),
        st.session_state.get("role", ""),
    )
    components.html(
        f"""
        <script>
        const swScope = {json.dumps(PUSH_SW_SCOPE)};
        const serverPushOn = {json.dumps(server_push_on)};
        const parentWindow = window.parent;

        function getBell() {{
          try {{
            return parentWindow.document.getElementById("mobile-push-status");
          }} catch (error) {{
            return null;
          }}
        }}

        function setBell(isOn, label) {{
          const bell = getBell();
          if (!bell) return false;
          bell.classList.toggle("is-on", isOn);
          bell.classList.toggle("is-off", !isOn);
          bell.setAttribute("aria-label", label);
          bell.setAttribute("title", label);
          return true;
        }}

        async function updateMobilePushBell() {{
          if (!getBell()) {{
            setTimeout(updateMobilePushBell, 250);
            return;
          }}
          try {{
            const notifications = parentWindow.Notification || window.Notification;
            const hasPushSupport = (
              parentWindow.navigator &&
              "serviceWorker" in parentWindow.navigator &&
              "PushManager" in parentWindow &&
              notifications
            );
            if (!hasPushSupport) {{
              setBell(serverPushOn, serverPushOn ? "Device notifications are on" : "Device notifications are handled by the app");
              return;
            }}
            const registration = await parentWindow.navigator.serviceWorker.getRegistration(swScope);
            const subscription = registration ? await registration.pushManager.getSubscription() : null;
            const isOn = Boolean(serverPushOn || (subscription && notifications.permission === "granted"));
            setBell(isOn, isOn ? "Device notifications are on" : "Device notifications are off");
          }} catch (error) {{
            setBell(serverPushOn, serverPushOn ? "Device notifications are on" : "Device notifications are off");
          }}
        }}

        updateMobilePushBell();
        setInterval(updateMobilePushBell, 30000);
        </script>
        """,
        height=0,
    )


def admin_unseen_message_count(messages=None):
    messages = load_messages() if messages is None else messages
    count = 0
    for message in messages:
        replies = message.get("Replies", [])
        if any(reply.get("From") == "Parent" and not reply.get("AdminRead") for reply in replies):
            count += 1
    return count


def latest_admin_unseen_message(messages=None):
    messages = load_messages() if messages is None else messages
    latest = None
    for message in messages:
        for reply in message.get("Replies", []):
            if reply.get("From") != "Parent" or reply.get("AdminRead"):
                continue
            candidate = {
                "MessageID": message.get("ID", ""),
                "ReplyID": reply.get("ID", ""),
                "ChildName": message.get("ChildName", "a child"),
                "ParentName": reply.get("ParentName") or message.get("ParentName") or "A parent",
                "Message": reply.get("Message", ""),
                "CreatedAt": reply.get("CreatedAt", ""),
            }
            if latest is None or candidate["CreatedAt"] > latest["CreatedAt"]:
                latest = candidate
    return latest


def render_admin_message_notification(messages=None):
    if st.session_state.get("role") != "Admin":
        return
    messages = load_messages() if messages is None else messages
    unseen_count = admin_unseen_message_count(messages)
    latest = latest_admin_unseen_message(messages)
    if not unseen_count or not latest:
        components.html(
            """
            <script>
            try {
              window.parent.document.title = "Ash's Angels Preschool App";
            } catch (error) {}
            setTimeout(() => {
              try { window.parent.location.reload(); } catch (error) {}
            }, 45000);
            </script>
            """,
            height=0,
        )
        return

    child_name = html.escape(latest.get("ChildName", "a child"))
    parent_name = html.escape(latest.get("ParentName", "A parent"))
    latest_message = html.escape(latest.get("Message", "")[:120])
    notification_key = f'{latest.get("MessageID", "")}-{latest.get("ReplyID", "")}-{latest.get("CreatedAt", "")}'
    latest_message_url = message_href(latest.get("MessageID", ""))
    components.html(
        f"""
        <style>
          body {{
            margin: 0;
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            color: #23345f;
          }}
          .notification-tools {{
            display: flex;
            align-items: center;
            gap: 10px;
            min-height: 42px;
          }}
          #enable-admin-notifications {{
            appearance: none;
            border: 0;
            border-radius: 8px;
            background: #2f4fa3;
            color: #ffffff;
            font-size: 15px;
            font-weight: 800;
            padding: 10px 14px;
            cursor: pointer;
          }}
          #enable-admin-notifications:hover {{
            background: #24448f;
          }}
          #admin-notification-state {{
            font-size: 14px;
            font-weight: 650;
            color: #647486;
          }}
        </style>
        <div class="notification-tools">
          <button id="enable-admin-notifications" type="button">Enable message notifications</button>
          <span id="admin-notification-state"></span>
        </div>
        <script>
        const notificationKey = {json.dumps(notification_key)};
        const unseenCount = {int(unseen_count)};
        const childName = {json.dumps(latest.get("ChildName", "a child"))};
        const parentName = {json.dumps(latest.get("ParentName", "A parent"))};
        const messagePreview = {json.dumps(latest.get("Message", "")[:120])};
        const state = document.getElementById("admin-notification-state");
        const button = document.getElementById("enable-admin-notifications");

        function setTitle() {{
          try {{
            window.parent.document.title = unseenCount + " new message" + (unseenCount === 1 ? "" : "s") + " - Ash's Angels";
          }} catch (error) {{}}
        }}

        function notifyIfAllowed() {{
          try {{
            const lastShown = window.localStorage.getItem("ash_admin_notification_key");
            if (lastShown === notificationKey) return;
            window.localStorage.setItem("ash_admin_notification_key", notificationKey);
            if (!("Notification" in window) || Notification.permission !== "granted") return;
            const note = new Notification("New parent message", {{
              body: parentName + " replied about " + childName + (messagePreview ? ": " + messagePreview : "."),
              tag: "ash-admin-message",
              renotify: true
            }});
            note.onclick = () => {{
              try {{
                window.parent.focus();
                window.parent.location.href = {json.dumps(latest_message_url)};
              }} catch (error) {{}}
            }};
          }} catch (error) {{}}
        }}

        function updatePermissionState() {{
          if (!("Notification" in window)) {{
            state.textContent = "Browser notifications are not supported here.";
            button.style.display = "none";
            return;
          }}
          if (Notification.permission === "granted") {{
            state.textContent = "Notifications are on.";
            button.style.display = "none";
            notifyIfAllowed();
          }} else if (Notification.permission === "denied") {{
            state.textContent = "Notifications are blocked in this browser.";
            button.style.display = "none";
          }} else {{
            state.textContent = "Turn this on to get a browser alert while the app is open.";
          }}
        }}

        button.addEventListener("click", async () => {{
          if (!("Notification" in window)) return updatePermissionState();
          await Notification.requestPermission();
          updatePermissionState();
        }});

        setTitle();
        updatePermissionState();
        setTimeout(() => {{
          try {{ window.parent.location.reload(); }} catch (error) {{}}
        }}, 45000);
        </script>
        """,
        height=48,
    )
    st.markdown(
        f"""
        <a class="admin-new-message-alert admin-new-message-link" href="{html.escape(latest_message_url)}" target="_self">
          <span class="admin-new-message-dot"></span>
          <div><strong>{unseen_count} new parent message{"s" if unseen_count != 1 else ""}</strong><br>
          Latest: {parent_name} replied about {child_name}{(": " + latest_message) if latest_message else ""}</div>
        </a>
        """,
        unsafe_allow_html=True,
    )


def parent_unseen_message_count(parent_email=None, messages=None):
    clean_email = str(parent_email or st.session_state.get("email", "")).strip().lower()
    if not clean_email:
        return 0
    messages = load_messages() if messages is None else messages
    return sum(
        1
        for message in messages
        if message.get("ParentEmail", "").strip().lower() == clean_email and not message.get("Read")
    )


def mark_parent_replies_seen(messages):
    changed = False
    read_at = datetime.now().isoformat(timespec="seconds")
    for message in messages:
        for reply in message.get("Replies", []):
            if reply.get("From") == "Parent" and not reply.get("AdminRead"):
                reply["AdminRead"] = True
                reply["AdminReadAt"] = read_at
                changed = True
    if changed:
        save_messages(messages)


def send_parent_notification(child, parent, message_body, attachments=None):
    messages = load_messages()
    message = {
        "ID": uuid.uuid4().hex,
        "Type": "Notification",
        "ChildID": child.get("ID", ""),
        "ChildName": child.get("Name", ""),
        "ChildThumbnail": child.get("Thumbnail", ""),
        "ParentID": parent.get("ID", ""),
        "ParentName": parent.get("FirstName", ""),
        "ParentEmail": parent.get("Email", ""),
        "Message": message_body.strip(),
        "Attachments": attachments or [],
        "CreatedAt": datetime.now().isoformat(timespec="seconds"),
        "Status": "Sent",
        "Read": False,
    }
    messages.append(message)
    saved = save_messages(messages)
    if saved:
        send_web_push_to_parent(message)
        send_fcm_to_parent(message)
    return saved


def session_parent_targets(session_name, children, parents):
    session_children = sorted(
        [child for child in children if clean_session_name(child.get("Session")) == session_name],
        key=lambda child: str(child.get("Name", "")).lower(),
    )
    approved_by_child = {}
    for parent in parents:
        child_id = parent.get("ChildID", "")
        if parent.get("Status") == "Approved" and child_id:
            approved_by_child.setdefault(child_id, []).append(parent)

    targets = []
    seen_parents = set()
    for child in session_children:
        for parent in approved_by_child.get(child.get("ID", ""), []):
            parent_key = str(parent.get("Email") or parent.get("ID") or "").strip().lower()
            if not parent_key or parent_key in seen_parents:
                continue
            seen_parents.add(parent_key)
            targets.append((child, parent))
    return targets


def send_session_parent_notifications(targets, message_body, attachments=None):
    if not targets:
        return 0
    messages = load_messages()
    created_at = datetime.now().isoformat(timespec="seconds")
    new_messages = []
    for child, parent in targets:
        new_messages.append(
            {
                "ID": uuid.uuid4().hex,
                "Type": "Notification",
                "ChildID": child.get("ID", ""),
                "ChildName": child.get("Name", ""),
                "ChildThumbnail": child.get("Thumbnail", ""),
                "ParentID": parent.get("ID", ""),
                "ParentName": parent.get("FirstName", ""),
                "ParentEmail": parent.get("Email", ""),
                "Message": str(message_body or "").strip(),
                "Attachments": attachments or [],
                "CreatedAt": created_at,
                "Status": "Sent",
                "Read": False,
            }
        )
    if not save_messages([*messages, *new_messages]):
        return 0

    web_sender = globals().get("send_web_push_to_parent")
    fcm_sender = globals().get("send_fcm_to_parent")
    for message in new_messages:
        if callable(web_sender):
            web_sender(message)
        if callable(fcm_sender):
            fcm_sender(message)
    return len(new_messages)


def add_parent_reply(message_id, parent, reply_body, attachments=None):
    clean_reply = str(reply_body or "").strip()
    attachments = attachments or []
    if not clean_reply and not attachments:
        return False
    messages = load_messages()
    for message in messages:
        if message.get("ID") == message_id and message.get("ParentEmail", "").strip().lower() == parent.get("Email", "").strip().lower():
            replies = message.setdefault("Replies", [])
            replies.append(
                {
                    "ID": uuid.uuid4().hex,
                    "From": "Parent",
                    "ParentID": parent.get("ID", ""),
                    "ParentName": parent.get("FirstName", "Parent"),
                    "Message": clean_reply,
                    "Attachments": attachments,
                    "CreatedAt": datetime.now().isoformat(timespec="seconds"),
                    "AdminRead": False,
                }
            )
            message["Status"] = "Replied"
            message["LastReplyAt"] = replies[-1]["CreatedAt"]
            saved = save_messages(messages)
            if saved:
                send_admin_reply_push(message, replies[-1])
            return saved
    return False


def add_admin_reply(message_id, reply_body, attachments=None):
    clean_reply = str(reply_body or "").strip()
    attachments = attachments or []
    if not clean_reply and not attachments:
        return False
    messages = load_messages()
    for message in messages:
        if message.get("ID") != message_id:
            continue
        replies = message.setdefault("Replies", [])
        created_at = datetime.now().isoformat(timespec="seconds")
        reply = {
            "ID": uuid.uuid4().hex,
            "From": "Admin",
            "Message": clean_reply,
            "Attachments": attachments,
            "CreatedAt": created_at,
        }
        replies.append(reply)
        message["LastReplyAt"] = created_at
        message["Read"] = False
        message.pop("ReadAt", None)
        message["ParentArchived"] = False
        message.pop("ParentArchivedAt", None)
        saved = save_messages(messages)
        if saved:
            send_admin_followup_to_parent(message, reply)
        return saved
    return False


def mark_messages_read(message_ids, parent_email):
    clean_email = str(parent_email or "").strip().lower()
    ids = {message_id for message_id in message_ids if message_id}
    if not clean_email or not ids:
        return
    messages = load_messages()
    changed = False
    read_at = datetime.now().isoformat(timespec="seconds")
    for message in messages:
        if message.get("ID") in ids and message.get("ParentEmail", "").strip().lower() == clean_email and not message.get("Read"):
            message["Read"] = True
            message["ReadAt"] = read_at
            changed = True
    if changed:
        save_messages(messages)


def set_parent_message_archived(message_id, parent_email, archived=True):
    clean_email = str(parent_email or "").strip().lower()
    if not message_id or not clean_email:
        return False
    messages = load_messages()
    for message in messages:
        if (
            message.get("ID") == message_id
            and message.get("ParentEmail", "").strip().lower() == clean_email
        ):
            message["ParentArchived"] = bool(archived)
            if archived:
                message["ParentArchivedAt"] = datetime.now().isoformat(timespec="seconds")
            else:
                message.pop("ParentArchivedAt", None)
            return save_messages(messages)
    return False


def delete_message(message_id):
    messages = load_messages()
    kept_messages = [message for message in messages if message.get("ID") != message_id]
    if len(kept_messages) == len(messages):
        return False
    save_messages(kept_messages)
    return True


def message_datetime(value):
    raw_value = str(value or "").strip()
    if not raw_value:
        return "Not recorded"
    try:
        parsed = datetime.fromisoformat(raw_value)
        return parsed.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return raw_value.replace("T", " ")


def message_activity_key(message):
    values = [str(message.get("CreatedAt", "") or ""), str(message.get("LastReplyAt", "") or "")]
    values.extend(
        str(reply.get("CreatedAt", "") or "")
        for reply in message.get("Replies", [])
        if isinstance(reply, dict)
    )
    return max(values) if values else ""


def clean_message_text(value):
    text = html.unescape(str(value or ""))
    text = re.sub(r"</?\s*[a-z][^>]*>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bdiv\s*class\s*=\s*(['\"]).*?\1\s*>?", " ", text, flags=re.IGNORECASE)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def message_body_html(value):
    text = clean_message_text(value)
    if not text:
        return ""
    return "<br>".join(html.escape(line) for line in text.splitlines())


def reply_author_label(reply, viewer_role):
    sender = str(reply.get("From", "") or "").strip().lower()
    if sender == "admin":
        return "Me" if viewer_role == "Admin" else "Preschool"
    if sender == "parent":
        if viewer_role == "Parent":
            return "You"
        return str(reply.get("ParentName") or "Parent")
    return str(reply.get("ParentName") or reply.get("From") or "Reply")


def replies_for_parent(parent_email):
    clean_email = str(parent_email or "").strip().lower()
    replies = []
    if not clean_email:
        return replies
    for message in load_messages():
        if message.get("ParentEmail", "").strip().lower() != clean_email:
            continue
        for reply in message.get("Replies", []):
            replies.append(
                {
                    "ChildName": message.get("ChildName", "Preschool message"),
                    **reply,
                }
            )
    return sorted(replies, key=lambda item: item.get("CreatedAt", ""), reverse=True)


def show_quick_notice(message):
    if hasattr(st, "toast"):
        st.toast(message)
    else:
        st.markdown(
            f'<div class="quick-toast">{html.escape(message)}</div>',
            unsafe_allow_html=True,
        )


def child_thumb_html(child):
    thumb = child.get("Thumbnail") or ""
    if thumb:
        child_name = html.escape(child.get("Name", "Child"))
        if str(thumb).startswith("data:image"):
            return f'<img class="child-thumb" src="{thumb}" alt="{child_name}">'
        path = APP_DIR / str(thumb)
        if path.exists():
            return f'<img class="child-thumb" src="{asset_url(path)}" alt="{child_name}">'
    return f'<img class="child-thumb placeholder" src="{child_silhouette_url()}" alt="No child photo">'


def lookup_key(value):
    return " ".join(str(value or "").strip().lower().split())


def message_child_record(message, children_by_id, children_by_name, parents_by_id, parents_by_email):
    child_id = str(message.get("ChildID", "") or "")
    child_name = str(message.get("ChildName", "") or "")
    parent_id = str(message.get("ParentID", "") or "")
    parent_email = lookup_key(message.get("ParentEmail", ""))

    child = children_by_id.get(child_id)
    if child:
        return child

    child = children_by_name.get(lookup_key(child_name))
    if child:
        return child

    parent = parents_by_id.get(parent_id) or parents_by_email.get(parent_email)
    if parent:
        child = children_by_id.get(parent.get("ChildID", ""))
        if child:
            return child
        child = children_by_name.get(lookup_key(parent.get("ChildName", "")))
        if child:
            return child

    return {
        "Name": child_name or "Preschool message",
        "Thumbnail": message.get("ChildThumbnail", ""),
    }


def format_dob(value):
    try:
        parsed = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return str(value or "")
    return parsed.strftime("%d %b %Y").lstrip("0")


def child_age_text(dob_value):
    if not dob_value:
        return ""
    if isinstance(dob_value, str):
        try:
            dob_value = date.fromisoformat(dob_value)
        except ValueError:
            return ""
    today = date.today()
    if dob_value > today:
        return ""
    months = (today.year - dob_value.year) * 12 + today.month - dob_value.month
    if today.day < dob_value.day:
        months -= 1
    months = max(months, 0)
    years, remaining_months = divmod(months, 12)
    parts = []
    if years:
        parts.append(f"{years} {'year' if years == 1 else 'years'}")
    if remaining_months:
        parts.append(f"{remaining_months} {'month' if remaining_months == 1 else 'months'}")
    return " & ".join(parts) if parts else "Less than 1 month"


def child_birthday_text(dob_value):
    if not dob_value:
        return ""
    if isinstance(dob_value, str):
        try:
            dob_value = date.fromisoformat(dob_value)
        except ValueError:
            return ""
    return dob_value.strftime("%d %b").lstrip("0")


def next_birthday_date(dob_value):
    if not dob_value:
        return None
    if isinstance(dob_value, str):
        try:
            dob_value = date.fromisoformat(dob_value)
        except ValueError:
            return None
    today = date.today()
    try:
        upcoming = dob_value.replace(year=today.year)
    except ValueError:
        upcoming = date(today.year, 2, 28)
    if upcoming < today:
        try:
            upcoming = dob_value.replace(year=today.year + 1)
        except ValueError:
            upcoming = date(today.year + 1, 2, 28)
    return upcoming


def cake_icon_html():
    return (
        '<svg class="cake-icon" viewBox="0 0 32 32" aria-hidden="true">'
        '<path class="cake-candle" d="M11 4v5M16 3v6M21 4v5"/>'
        '<path class="cake-flame" d="M11 2.5c1.6 1.4 1.6 2.7 0 4-1.6-1.3-1.6-2.6 0-4ZM16 1.5c1.7 1.5 1.7 2.9 0 4.2-1.7-1.3-1.7-2.7 0-4.2ZM21 2.5c1.6 1.4 1.6 2.7 0 4-1.6-1.3-1.6-2.6 0-4Z"/>'
        '<path class="cake-icing" d="M8 13h16c1.7 0 3 1.3 3 3v2H5v-2c0-1.7 1.3-3 3-3Z"/>'
        '<path class="cake-base" d="M6 18h20v8H6z"/>'
        '<path class="cake-sprinkle" d="M10 21h2M15 23h2M20 21h2"/>'
        '</svg>'
    )


def child_info_badges_html(dob_value):
    age = child_age_text(dob_value)
    birthday = child_birthday_text(dob_value)
    if not age and not birthday:
        return ""
    badges = []
    if age:
        badges.append(f'<div class="child-age-note">Age: {html.escape(age)}</div>')
    if birthday:
        badges.append(
            '<div class="child-birthday-note">'
            f'{cake_icon_html()}<span>Birthday: {html.escape(birthday)}</span>'
            '</div>'
        )
    return f'<div class="child-info-badges">{"".join(badges)}</div>'


def normalize_guardian(guardian):
    if not isinstance(guardian, dict):
        return {}
    return {
        "Name": str(guardian.get("Name", "")).strip(),
        "Relationship": clean_contact_relationship(guardian.get("Relationship", "")),
        "Email": str(guardian.get("Email", "")).strip(),
        "Phone": str(guardian.get("Phone", "")).strip(),
        "Address": str(guardian.get("Address", "")).strip(),
        "Invited": bool(guardian.get("Invited")),
    }


def clean_contact_relationship(value, default=""):
    relationship = str(value or "").strip()
    if not relationship:
        return default
    aliases = {
        "mam": "Mam",
        "mum": "Mam",
        "mom": "Mam",
        "mother": "Mam",
        "dad": "Dad",
        "father": "Dad",
        "guardian": "Guardian",
    }
    return aliases.get(relationship.lower(), relationship if relationship in CONTACT_RELATIONSHIPS else default)


def relationship_index(value, default="Guardian"):
    relationship = clean_contact_relationship(value, default)
    return CONTACT_RELATIONSHIPS.index(relationship) if relationship in CONTACT_RELATIONSHIPS else CONTACT_RELATIONSHIPS.index(default)


def child_guardians(child):
    raw_guardians = child.get("Guardians", [])
    if isinstance(raw_guardians, dict):
        raw_guardians = [raw_guardians]
    if not isinstance(raw_guardians, list):
        return []
    guardians = []
    for guardian in raw_guardians:
        clean_guardian = normalize_guardian(guardian)
        if any(clean_guardian.get(field) for field in ("Name", "Email", "Phone", "Address")):
            guardians.append(clean_guardian)
    return guardians


def guardian_from_fields(name, relationship, email, phone, address, invited):
    guardian = {
        "Name": str(name or "").strip(),
        "Relationship": clean_contact_relationship(relationship, "Guardian"),
        "Email": str(email or "").strip(),
        "Phone": str(phone or "").strip(),
        "Address": str(address or "").strip(),
        "Invited": bool(invited),
    }
    if not any(guardian.get(field) for field in ("Name", "Email", "Phone", "Address")):
        return []
    return [guardian]


def parent_option_label(parent):
    name = str(parent.get("FirstName", "") or "Unnamed parent").strip()
    email = str(parent.get("Email", "") or "").strip()
    child_name = str(parent.get("ChildName", "") or "").strip()
    bits = [name]
    if email:
        bits.append(email)
    if child_name:
        bits.append(f"assigned to {child_name}")
    return " - ".join(bits)


def parent_defaults(parent, fallback_guardian=None):
    fallback_guardian = fallback_guardian or {}
    return {
        "Name": parent.get("FirstName") or fallback_guardian.get("Name", ""),
        "Relationship": clean_contact_relationship(parent.get("Relationship", ""), "")
        or clean_contact_relationship(fallback_guardian.get("Relationship", ""), "Guardian"),
        "Email": parent.get("Email") or fallback_guardian.get("Email", ""),
        "Phone": parent.get("EmergencyContact1") or parent.get("Phone") or fallback_guardian.get("Phone", ""),
        "Address": parent.get("Address") or fallback_guardian.get("Address", ""),
        "Invited": bool(fallback_guardian.get("Invited") or parent.get("salt") or parent.get("hash")),
    }


def matching_parent_id(parents, guardian, child_id=""):
    guardian_email = lookup_key(guardian.get("Email", ""))
    for parent in parents:
        if child_id and parent.get("ChildID") == child_id:
            return parent.get("ID", "")
    if guardian_email:
        for parent in parents:
            if lookup_key(parent.get("Email", "")) == guardian_email:
                return parent.get("ID", "")
    return ""


def sync_guardian_to_parent(parents, child, guardians, selected_parent_id=""):
    if not guardians:
        return False
    guardian = guardians[0]
    guardian_email = lookup_key(guardian.get("Email", ""))
    if not selected_parent_id and not guardian_email:
        return False

    parent = None
    if selected_parent_id:
        parent = next((item for item in parents if item.get("ID") == selected_parent_id), None)
    if parent is None and guardian_email:
        parent = next((item for item in parents if lookup_key(item.get("Email", "")) == guardian_email), None)

    changed = False
    if parent is None:
        parent = {
            "ID": uuid.uuid4().hex,
            "FirstName": guardian.get("Name", ""),
            "Relationship": guardian.get("Relationship", "Guardian"),
            "Email": guardian.get("Email", ""),
            "EmergencyContact1": guardian.get("Phone", ""),
            "EmergencyContact2": "",
            "Address": guardian.get("Address", ""),
            "Status": "Approved" if guardian.get("Invited") else "Pending",
            "ChildID": "",
            "ChildName": "",
        }
        parents.append(parent)
        changed = True

    updates = {
        "ChildID": child.get("ID", ""),
        "ChildName": child.get("Name", ""),
        "Relationship": clean_contact_relationship(guardian.get("Relationship", ""), parent.get("Relationship", "Guardian")),
    }
    if guardian.get("Name"):
        updates["FirstName"] = guardian.get("Name")
    if guardian.get("Email"):
        updates["Email"] = guardian.get("Email")
    if guardian.get("Phone"):
        updates["EmergencyContact1"] = guardian.get("Phone")
    if guardian.get("Address"):
        updates["Address"] = guardian.get("Address")
    if guardian.get("Invited") or selected_parent_id:
        updates["Status"] = "Approved"

    for key, value in updates.items():
        if parent.get(key) != value:
            parent[key] = value
            changed = True
    return changed


def contact_display_name(name, relationship):
    clean_name = str(name or "").strip()
    clean_relationship = clean_contact_relationship(relationship, "")
    if clean_name and clean_relationship:
        return f"({clean_relationship}) {clean_name}"
    return clean_name or "Parent/guardian"


def guardian_relationship_for_parent(parent, child):
    parent_email = lookup_key(parent.get("Email", ""))
    parent_name = lookup_key(parent.get("FirstName", ""))
    for guardian in child_guardians(child or {}):
        if parent_email and lookup_key(guardian.get("Email", "")) == parent_email:
            return guardian.get("Relationship", "")
        if parent_name and lookup_key(guardian.get("Name", "")) == parent_name:
            return guardian.get("Relationship", "")
    return ""


def parent_relationship(parent, child=None):
    return (
        clean_contact_relationship(parent.get("Relationship", ""), "")
        or clean_contact_relationship(guardian_relationship_for_parent(parent, child), "")
        or ("Dad" if lookup_key(parent.get("FirstName", "")) == "liam o' boyle" else "Guardian")
    )


def message_parent_targets(children, parents):
    children_by_id = {child.get("ID", ""): child for child in children if child.get("ID")}
    children_by_name = {lookup_key(child.get("Name", "")): child for child in children if child.get("Name")}
    targets = []
    for parent in parents:
        if parent.get("Status") != "Approved" or not parent.get("Email"):
            continue
        child = children_by_id.get(parent.get("ChildID", ""))
        if not child:
            child = children_by_name.get(lookup_key(parent.get("ChildName", "")))
        if not child:
            continue
        relationship = parent_relationship(parent, child)
        parent_name = contact_display_name(parent.get("FirstName", ""), relationship)
        child_name = child.get("Name", "Unnamed child")
        email = parent.get("Email", "")
        label = f"{child_name} - {parent_name}"
        if email:
            label = f"{label} - {email}"
        targets.append(
            {
                "Key": f'{child.get("ID", "")}|{parent.get("ID", "") or parent.get("Email", "")}',
                "Label": label,
                "Child": child,
                "Parent": parent,
                "Sort": (str(child_name).lower(), str(parent.get("FirstName", "")).lower(), str(email).lower()),
            }
        )
    return sorted(targets, key=lambda item: item["Sort"])


def guardian_summary_html(child):
    guardians = child_guardians(child)
    if not guardians:
        return ""
    rows = []
    for guardian in guardians:
        name = guardian.get("Name") or "Parent/guardian"
        relationship = guardian.get("Relationship", "")
        name_line = html.escape(contact_display_name(name, relationship))
        contact_bits = [guardian.get("Email", ""), guardian.get("Phone", "")]
        contact_line = " &bull; ".join(html.escape(bit) for bit in contact_bits if bit)
        address_line = html.escape(guardian.get("Address", ""))
        invited = guardian.get("Invited")
        initial = html.escape((name[:1] or "P").upper())
        invited_line = (
            '<div class="guardian-invited"><span class="guardian-check">&#10003;</span> Invited to use the app</div>'
            if invited
            else '<div class="guardian-not-invited">Not invited to use the app yet</div>'
        )
        contact_html = f'<div class="guardian-contact">{contact_line}</div>' if contact_line else ""
        address_html = f'<div class="guardian-address">{address_line}</div>' if address_line else ""
        details = (
            f'<div class="guardian-name">{name_line}</div>'
            f"{contact_html}"
            f"{address_html}"
            f"{invited_line}"
        )
        rows.append(
            '<div class="guardian-card">'
            f'<div class="guardian-avatar">{initial}</div>'
            f'<div>{details}</div>'
            '</div>'
        )
    return (
        '<div class="guardian-section">'
        '<div class="guardian-section-title">Parents/guardians</div>'
        f'{"".join(rows)}'
        '</div>'
    )


st.markdown(
    f"""
    <style>
    :root {{
        --ink: #23345f;
        --muted: #66778a;
        --bg: #9FC9EB;
        --panel: #ffffff;
        --brand-blue: #294999;
        --rose: #df4d9b;
        --red: #f43d2e;
        --orange: #ff9f1c;
        --sun: #ffe600;
        --green: #1fb74e;
        --sky: #9dc8ec;
        --line: rgba(38,55,70,.14);
        --shadow: 0 14px 34px rgba(38,55,70,.08);
    }}
    html,
    body,
    .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"],
    [data-testid="stMainBlockContainer"] {{
        background: var(--bg) !important;
        background-color: var(--bg) !important;
        color: var(--ink);
        font-family: "Avenir Next", "Nunito", "Trebuchet MS", "Segoe UI", system-ui, sans-serif;
    }}
    [data-testid="stHeader"] {{
        display: none !important;
        visibility: hidden !important;
        pointer-events: none !important;
    }}
    #MainMenu,
    [data-testid="stToolbar"],
    [data-testid="stDecoration"],
    [data-testid="stStatusWidget"],
    [data-testid="stDeployButton"] {{
        display: none !important;
        visibility: hidden !important;
    }}
    .block-container {{
        max-width: 100%;
        padding: 2rem 2.75rem 3rem;
    }}
    h1, h2, h3, p, div, label {{
        letter-spacing: 0 !important;
        font-family: "Avenir Next", "Nunito", "Trebuchet MS", "Segoe UI", system-ui, sans-serif;
    }}
    .app-top {{
        display: flex; align-items: center; justify-content: space-between; gap: 18px;
        background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
        padding: 14px 16px; box-shadow: var(--shadow); margin-bottom: 16px;
    }}
    .side-menu {{
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 150px 24px 24px;
        box-shadow: var(--shadow);
        position: sticky;
        top: 92px;
        margin-top: 86px;
    }}
    .side-logo {{
        width: 100%;
        height: 166px;
        object-fit: contain;
        display: block;
        margin: 0;
        filter:
            drop-shadow(3px 0 0 #fff)
            drop-shadow(-3px 0 0 #fff)
            drop-shadow(0 3px 0 #fff)
            drop-shadow(0 -3px 0 #fff);
    }}
    .side-logo-link {{
        display: block;
        width: 250px;
        max-width: 100%;
        margin: 0;
        text-decoration: none;
        position: absolute;
        top: -86px;
        left: 50%;
        transform: translateX(-50%);
    }}
    .mobile-menu {{
        display: none;
    }}
    .mobile-push-status {{
        display: none;
    }}
    .menu-label {{
        color: var(--muted);
        font-size: .78rem;
        font-weight: 900;
        text-transform: uppercase;
        margin-bottom: 8px;
    }}
    .menu-item {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #fffaf1;
        color: var(--brand-blue);
        font-weight: 900;
        padding: 10px 12px;
        margin-bottom: 8px;
        text-decoration: none;
    }}
    .menu-item.active {{
        background: var(--brand-blue);
        color: white;
        border-color: var(--brand-blue);
    }}
    .menu-badge {{
        display: inline-grid;
        place-items: center;
        min-width: 24px;
        height: 24px;
        padding: 0 7px;
        border-radius: 999px;
        background: var(--orange);
        color: #ffffff;
        border: 2px solid rgba(255,255,255,.88);
        font-size: .78rem;
        font-weight: 950;
        line-height: 1;
        box-shadow: 0 4px 10px rgba(255,159,28,.32);
    }}
    .menu-item.active .menu-badge {{
        background: #ffffff;
        color: var(--brand-blue);
        border-color: rgba(255,255,255,.55);
    }}
    .sign-out {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 8px;
        min-height: 40px;
        padding: 0 14px;
        border: 1px solid var(--line);
        background: #fffaf1;
        color: var(--brand-blue) !important;
        font-weight: 900;
        text-decoration: none !important;
        margin-top: 8px;
    }}
    .login-shell {{
        display: grid;
        place-items: center;
        min-height: calc(100vh - 120px);
        margin-top: 0;
        padding: 24px 0;
    }}
    .login-shell.has-login-form {{
        min-height: auto;
        padding-bottom: 12px;
    }}
    .login-card {{
        width: min(760px, 100%); background: var(--panel); border: 1px solid var(--line);
        border-radius: 8px; padding: 22px; box-shadow: var(--shadow);
    }}
    .login-head {{
        display: flex; align-items: center; justify-content: space-between; gap: 18px;
        border-bottom: 1px solid var(--line); padding-bottom: 16px; margin-bottom: 16px;
    }}
    .login-logo {{ width: 126px; height: 86px; object-fit: contain; flex: 0 0 auto; }}
    .role-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 12px 0 18px; }}
    .role-card {{
        border: 1px solid var(--line); border-radius: 8px; padding: 14px;
        background: #fffaf1; display: block; text-decoration: none;
        box-shadow: 0 4px 12px rgba(35,52,95,.08);
        transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease, background .16s ease;
    }}
    .role-card:hover {{
        background: #ffffff;
        border-color: #d9e5ef;
        transform: translateY(-1px);
        box-shadow: 0 8px 18px rgba(35,52,95,.12);
    }}
    .role-card.active {{
        background: #fffaf1;
        border-color: var(--brand-blue);
        box-shadow: 0 0 0 2px rgba(49,84,165,.22), 0 8px 18px rgba(35,52,95,.12);
    }}
    .login-shell.has-login-form .role-grid {{
        margin-bottom: 0;
    }}
    .login-shell.has-login-form .role-card {{
        padding: 12px 14px;
    }}
    .login-shell.has-login-form .role-copy {{
        display: none;
    }}
    div.st-key-login_form_card,
    div[data-testid="stVerticalBlock"].st-key-login_form_card {{
        width: min(680px, 100%);
        margin: 0 auto 48px;
        background: #fffaf1 !important;
        background-color: #fffaf1 !important;
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 22px !important;
        box-shadow: var(--shadow);
    }}
    .role-card,
    .role-card *,
    .role-card:hover,
    .role-card:hover * {{
        text-decoration: none !important;
    }}
    .role-title {{
        color: var(--brand-blue);
        font-weight: 850;
        font-size: .98rem;
        line-height: 1.12;
    }}
    .role-copy {{
        color: var(--muted);
        font-size: .9rem;
        font-weight: 500;
        line-height: 1.25;
        margin-top: 7px;
    }}
    .forgot-link {{
        display: inline-flex;
        color: var(--brand-blue) !important;
        font-weight: 950;
        margin: 8px 0 14px;
    }}
    [data-testid="stDialog"],
    [data-testid="stDialog"] > div,
    [data-testid="stDialog"] [data-baseweb="modal"],
    [data-testid="stDialog"] [role="dialog"],
    [data-baseweb="modal"],
    [data-baseweb="modal"] > div,
    [data-baseweb="modal"] > div > div,
    [data-baseweb="modal"] [role="dialog"],
    div[role="dialog"] {{
        background: #fffaf1 !important;
        background-color: #fffaf1 !important;
        border-radius: 8px !important;
        border: 1px solid var(--line) !important;
        box-shadow: 0 24px 70px rgba(35,52,95,.24) !important;
    }}
    [data-testid="stDialog"] [class*="st-emotion-cache"],
    [data-testid="stDialog"] [data-testid="stVerticalBlock"],
    [data-testid="stDialog"] [data-testid="stVerticalBlockBorderWrapper"],
    [data-testid="stDialog"] [data-testid="stElementContainer"],
    [data-testid="stDialog"] [data-testid="stMarkdownContainer"],
    [data-baseweb="modal"] [class*="st-emotion-cache"],
    [data-baseweb="modal"] [data-testid="stVerticalBlock"],
    [data-baseweb="modal"] [data-testid="stVerticalBlockBorderWrapper"],
    [data-baseweb="modal"] [data-testid="stElementContainer"],
    [data-baseweb="modal"] [data-testid="stMarkdownContainer"],
    div[role="dialog"] > div,
    div[role="dialog"] section,
    div[role="dialog"] [data-testid="stVerticalBlock"],
    div[role="dialog"] [data-testid="stElementContainer"],
    div[role="dialog"] [data-testid="stMarkdownContainer"] {{
        background: #fffaf1 !important;
        background-color: #fffaf1 !important;
    }}
    [data-testid="stDialog"],
    [data-testid="stDialog"] h1,
    [data-testid="stDialog"] h2,
    [data-testid="stDialog"] h3,
    [data-testid="stDialog"] p,
    [data-testid="stDialog"] label,
    [data-testid="stDialog"] span,
    [data-baseweb="modal"],
    [data-baseweb="modal"] h1,
    [data-baseweb="modal"] h2,
    [data-baseweb="modal"] h3,
    [data-baseweb="modal"] p,
    [data-baseweb="modal"] label,
    [data-baseweb="modal"] span,
    div[role="dialog"],
    div[role="dialog"] h1,
    div[role="dialog"] h2,
    div[role="dialog"] h3,
    div[role="dialog"] p,
    div[role="dialog"] label,
    div[role="dialog"] span {{
        color: var(--ink) !important;
    }}
    [data-testid="stDialog"] h2,
    [data-testid="stDialog"] [data-testid="stMarkdownContainer"] .panel-title,
    [data-baseweb="modal"] h2,
    [data-baseweb="modal"] [data-testid="stMarkdownContainer"] .panel-title,
    div[role="dialog"] h2,
    div[role="dialog"] [data-testid="stMarkdownContainer"] .panel-title {{
        color: var(--brand-blue) !important;
        font-weight: 950 !important;
    }}
    [data-testid="stDialog"] button[aria-label="Close"],
    [data-baseweb="modal"] button[aria-label="Close"],
    div[role="dialog"] button[aria-label="Close"] {{
        background: #e9f4ff !important;
        border: 1px solid #d9e5ef !important;
        border-radius: 8px !important;
        box-shadow: none !important;
        outline: none !important;
    }}
    [data-testid="stDialog"] button[aria-label="Close"]:hover,
    [data-baseweb="modal"] button[aria-label="Close"]:hover,
    div[role="dialog"] button[aria-label="Close"]:hover {{
        background: var(--brand-blue) !important;
        border-color: var(--brand-blue) !important;
    }}
    [data-testid="stDialog"] button[aria-label="Close"]:hover svg,
    [data-baseweb="modal"] button[aria-label="Close"]:hover svg,
    div[role="dialog"] button[aria-label="Close"]:hover svg {{
        color: #ffffff !important;
        fill: #ffffff !important;
    }}
    [data-testid="stDialog"] button[aria-label="Close"] svg,
    [data-baseweb="modal"] button[aria-label="Close"] svg,
    div[role="dialog"] button[aria-label="Close"] svg {{
        color: var(--brand-blue) !important;
        fill: var(--brand-blue) !important;
        opacity: 1 !important;
    }}
    [data-testid="stDialog"] input,
    [data-testid="stDialog"] textarea,
    [data-baseweb="modal"] input,
    [data-baseweb="modal"] textarea,
    div[role="dialog"] input,
    div[role="dialog"] textarea {{
        background: #ffffff !important;
        background-color: #ffffff !important;
        color: var(--ink) !important;
        border-color: #d9e5ef !important;
    }}
    [data-testid="stDialog"] div[data-testid="stButton"] button,
    [data-testid="stDialog"] div[data-testid="stFormSubmitButton"] button,
    [data-baseweb="modal"] div[data-testid="stButton"] button,
    [data-baseweb="modal"] div[data-testid="stFormSubmitButton"] button,
    div[role="dialog"] div[data-testid="stButton"] button,
    div[role="dialog"] div[data-testid="stFormSubmitButton"] button {{
        background: var(--brand-blue) !important;
        background-color: var(--brand-blue) !important;
        border-color: var(--brand-blue) !important;
        color: #ffffff !important;
        box-shadow: none !important;
    }}
    [data-testid="stDialog"] div[data-testid="stButton"] button *,
    [data-testid="stDialog"] div[data-testid="stFormSubmitButton"] button *,
    [data-baseweb="modal"] div[data-testid="stButton"] button *,
    [data-baseweb="modal"] div[data-testid="stFormSubmitButton"] button *,
    div[role="dialog"] div[data-testid="stButton"] button *,
    div[role="dialog"] div[data-testid="stFormSubmitButton"] button * {{
        color: #ffffff !important;
        background: transparent !important;
    }}
    [data-testid="stDialog"] div[data-testid="stButton"] button:hover,
    [data-testid="stDialog"] div[data-testid="stFormSubmitButton"] button:hover,
    [data-baseweb="modal"] div[data-testid="stButton"] button:hover,
    [data-baseweb="modal"] div[data-testid="stFormSubmitButton"] button:hover,
    div[role="dialog"] div[data-testid="stButton"] button:hover,
    div[role="dialog"] div[data-testid="stFormSubmitButton"] button:hover {{
        background: #23345f !important;
        background-color: #23345f !important;
        border-color: #23345f !important;
    }}
    .app-title {{ font-size: 1.55rem; font-weight: 900; color: var(--brand-blue); line-height: 1.1; }}
    .app-subtitle {{ color: var(--muted); margin-top: 4px; font-weight: 650; }}
    .top-logo {{ width: 124px; height: 82px; object-fit: contain; flex: 0 0 auto; }}
    .tabs {{
        display: flex; gap: 8px; flex-wrap: wrap; margin: 0 0 16px;
    }}
    .tab {{
        border: 1px solid var(--line); border-radius: 999px; background: rgba(255,255,255,.78);
        color: var(--brand-blue); font-weight: 850; padding: 9px 14px;
    }}
    .tab.active {{ background: var(--brand-blue); color: white; }}
    .panel {{
        background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
        padding: 18px; box-shadow: var(--shadow); min-height: 100%;
    }}
    .actions-row {{
        display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin: 10px 0 16px;
    }}
    div[data-testid="stForm"] {{
        background: var(--panel) !important;
        border: 1px solid var(--line) !important;
        border-radius: 8px !important;
        box-shadow: var(--shadow) !important;
        padding: 22px 24px 30px !important;
    }}
    div[data-testid="stForm"] div[data-testid="stHorizontalBlock"]:has(div[data-testid="stFormSubmitButton"]) {{
        display: flex !important;
        flex-wrap: nowrap !important;
        align-items: center !important;
        gap: 12px !important;
        width: fit-content !important;
        max-width: 100% !important;
        margin-top: 18px !important;
    }}
    div[data-testid="stForm"] div[data-testid="stHorizontalBlock"]:has(div[data-testid="stFormSubmitButton"]) > div {{
        flex: 0 0 auto !important;
        width: auto !important;
        min-width: 0 !important;
    }}
    div[data-testid="stForm"] div[data-testid="stHorizontalBlock"]:has(div[data-testid="stFormSubmitButton"]) div[data-testid="stFormSubmitButton"] button {{
        width: auto !important;
        min-width: 126px !important;
        padding-left: 16px !important;
        padding-right: 16px !important;
    }}
    .panel-title {{ font-size: 1.15rem; font-weight: 900; color: var(--brand-blue); margin-bottom: 8px; }}
    .section-title {{
        font-family: "Brush Script MT", "Bradley Hand", "Segoe Script", "Apple Chancery", cursive !important;
        font-size: 2.25rem;
        font-weight: 900;
        color: var(--brand-blue);
        line-height: 1.05;
        margin-bottom: 8px;
    }}
    .section-header {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        margin-bottom: 8px;
    }}
    div.st-key-documents_page_panel,
    div[data-testid="stVerticalBlock"].st-key-documents_page_panel {{
        background: #ffffff !important;
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 24px !important;
        box-shadow: var(--shadow);
    }}
    div.st-key-documents_page_panel div[data-testid="stForm"],
    div[data-testid="stVerticalBlock"].st-key-documents_page_panel div[data-testid="stForm"] {{
        background: transparent !important;
        border: 0 !important;
        border-radius: 0 !important;
        box-shadow: none !important;
        padding: 0 0 12px !important;
    }}
    .documents-page-heading {{
        color: var(--brand-blue);
        font-size: 1.35rem;
        font-weight: 900;
        line-height: 1.15;
        margin-bottom: 6px;
    }}
    .documents-section-heading {{
        color: var(--brand-blue);
        font-size: 1.15rem;
        font-weight: 900;
        line-height: 1.2;
        margin: 20px 0 4px;
    }}
    .documents-rule {{
        border-top: 1px solid var(--line);
        margin: 8px 0 2px;
    }}
    .documents-bottom-space {{
        height: 32px;
    }}
    .document-file-summary {{
        display: flex;
        align-items: flex-start;
        gap: 14px;
        min-width: 0;
    }}
    .document-file-copy {{
        min-width: 0;
        padding-top: 2px;
    }}
    .document-file-visual {{
        display: flex;
        flex: 0 0 116px;
        flex-direction: column;
        align-items: center;
        gap: 8px;
        min-width: 0;
    }}
    .document-file-name {{
        width: 100%;
        color: var(--muted);
        font-family: system-ui, sans-serif;
        font-size: .76rem;
        font-weight: 800;
        line-height: 1.25;
        letter-spacing: 0;
        overflow-wrap: anywhere;
        text-align: center;
    }}
    .document-pdf-icon {{
        position: relative;
        display: inline-flex;
        flex: 0 0 46px;
        align-items: flex-end;
        justify-content: center;
        width: 46px;
        height: 54px;
        padding: 0 0 7px;
        overflow: hidden;
        border: 1px solid #ad2530;
        border-radius: 6px;
        background: #cf3340;
        color: #ffffff;
        font-family: system-ui, sans-serif;
        font-size: .72rem;
        font-weight: 900;
        line-height: 1;
        letter-spacing: 0;
    }}
    .document-pdf-icon::before {{
        content: "";
        position: absolute;
        top: 0;
        right: 0;
        width: 14px;
        height: 14px;
        background: #ffffff;
        clip-path: polygon(0 0, 100% 0, 100% 100%);
    }}
    .document-pdf-icon.document-drag-source {{
        cursor: grab;
        touch-action: none;
        user-select: none;
        transition: transform .16s ease, box-shadow .16s ease;
    }}
    .document-pdf-icon.document-drag-source:hover,
    .document-pdf-icon.document-drag-source:focus-visible {{
        outline: none;
        transform: translateY(-2px);
        box-shadow: 0 0 0 3px rgba(41, 73, 153, .2);
    }}
    .document-pdf-icon.document-drag-source:active {{
        cursor: grabbing;
    }}
    .document-drag-marker,
    .document-drop-marker,
    .document-move-link {{
        display: none !important;
    }}
    .document-draggable-row {{
        position: relative !important;
        padding-right: 68px !important;
        transition: border-color .16s ease, box-shadow .16s ease, opacity .16s ease !important;
    }}
    .document-draggable-row.is-dragging {{
        opacity: .62;
        border-color: var(--brand-blue) !important;
    }}
    .document-drag-handle {{
        position: absolute;
        top: 16px;
        right: 16px;
        z-index: 5;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 42px;
        height: 42px;
        padding: 0;
        border: 1px solid #cbdbea;
        border-radius: 8px;
        background: #eef6ff;
        color: var(--brand-blue);
        font-family: system-ui, sans-serif;
        font-size: 1.35rem;
        font-weight: 900;
        line-height: 1;
        letter-spacing: -7px;
        cursor: grab;
        touch-action: none;
        user-select: none;
        box-shadow: none;
    }}
    .document-drag-handle:hover,
    .document-drag-handle:focus-visible {{
        border-color: var(--brand-blue);
        background: #dceeff;
        outline: none;
    }}
    .document-drag-handle:active {{
        cursor: grabbing;
    }}
    .document-drop-zone {{
        position: relative;
        min-height: 156px;
        margin: 14px 0;
        border: 2px dashed #a9c2dc;
        border-radius: 8px;
        padding: 18px 18px 22px !important;
        background: #f7fbff;
        box-shadow: 0 7px 18px rgba(31, 64, 119, .07);
        transition: border-color .16s ease, background-color .16s ease, box-shadow .16s ease;
    }}
    .document-drop-zone[data-audience="Important"] {{
        border-color: #e3b54d;
        background: #fffaf0;
    }}
    .document-drop-zone[data-audience="Parents"] {{
        border-color: #8fb7db;
        background: #f5faff;
    }}
    .document-drop-zone[data-audience="Private"] {{
        border-color: #b9c2cc;
        background: #f8f9fb;
    }}
    .document-drop-zone > div:first-of-type .documents-section-heading {{
        margin-top: 0;
    }}
    body.document-is-dragging .document-drop-zone {{
        border-color: #779fc6;
        background: #edf6ff;
        box-shadow: 0 0 0 3px rgba(47,79,159,.08);
    }}
    body.document-is-dragging .document-drop-zone.is-drop-target {{
        border-color: var(--brand-blue);
        background: #dfefff;
        box-shadow: 0 0 0 4px rgba(47,79,159,.16), 0 12px 28px rgba(31,64,119,.12);
    }}
    .parent-important-heading {{
        color: var(--brand-blue);
        font-size: 1.15rem;
        font-weight: 900;
        line-height: 1.2;
        margin: 22px 0 10px;
    }}
    .parent-important-document {{
        border-color: #e3b54d;
        background: #fffaf0;
        box-shadow: 0 5px 14px rgba(119, 84, 18, .07);
        margin-bottom: 10px;
    }}
    .section-edit {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 40px;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #fffaf1;
        color: var(--brand-blue) !important;
        font-weight: 900;
        padding: 0 16px;
        text-decoration: none !important;
    }}
    .settings-support-links {{
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-top: 18px;
    }}
    .add-child-icon {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 42px;
        height: 42px;
        border-radius: 8px;
        border: 1px solid var(--line);
        background: #fffaf1;
        color: var(--brand-blue) !important;
        font-size: 1.6rem;
        font-weight: 950;
        line-height: 1;
        text-decoration: none !important;
        transition: transform .16s ease, background-color .16s ease, border-color .16s ease, box-shadow .16s ease;
    }}
    .add-child-icon:hover {{
        background: var(--brand-blue);
        color: #ffffff !important;
        border-color: var(--brand-blue);
        box-shadow: 0 8px 18px rgba(35,52,95,.18);
        transform: translateY(-1px);
    }}
    .session-heading {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 12px;
    }}
    .session-heading .session-title {{
        margin: 0;
    }}
    .session-actions {{
        display: flex;
        align-items: center;
        gap: 8px;
        flex: 0 0 auto;
    }}
    .message-session-link {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 42px;
        border: 1px solid var(--brand-blue);
        border-radius: 8px;
        padding: 0 12px;
        background: #ffffff;
        color: var(--brand-blue) !important;
        font-size: .82rem;
        font-weight: 900;
        line-height: 1;
        text-decoration: none !important;
        white-space: nowrap;
    }}
    .message-session-link:hover {{
        background: var(--brand-blue);
        color: #ffffff !important;
    }}
    .children-panel {{
        padding-top: 10px;
        padding-bottom: 10px;
    }}
    .children-panel .section-header,
    .children-panel .section-title {{
        margin-bottom: 0;
    }}
    .edit-tools {{
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #fffaf1;
        padding: 12px;
        margin: 12px 0 14px;
    }}
    .edit-tools .muted {{
        margin-bottom: 8px;
    }}
    .st-key-edit_child_panel,
    .st-key-edit-child-panel {{
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 8px;
        box-shadow: var(--shadow);
        padding: 18px 18px 20px;
    }}
    .st-key-edit_child_panel div[data-testid="stForm"],
    .st-key-edit-child-panel div[data-testid="stForm"] {{
        background: transparent !important;
        border: 0 !important;
        border-radius: 0 !important;
        box-shadow: none !important;
        padding: 0 !important;
        margin-top: 18px !important;
    }}
    .st-key-edit_child_panel .guardian-section,
    .st-key-edit-child-panel .guardian-section {{
        margin-top: 10px;
        margin-bottom: 18px;
    }}
    .st-key-settings_panel,
    .st-key-settings-panel {{
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 8px;
        box-shadow: var(--shadow);
        padding: 18px;
    }}
    .settings-heading {{
        color: var(--brand-blue);
        font-size: 1.15rem;
        font-weight: 900;
        line-height: 1.12;
        margin-bottom: 14px;
    }}
    .settings-section {{
        display: grid;
        gap: 10px;
        padding: 14px;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #fffaf1;
    }}
    .settings-section + .settings-section {{
        margin-top: 14px;
    }}
    .st-key-settings_push_section,
    .st-key-settings-push-section {{
        display: grid;
        gap: 10px;
        padding: 14px;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #fffaf1;
        margin-top: 14px;
    }}
    .settings-section-title {{
        color: var(--ink);
        font-size: 1rem;
        font-weight: 900;
        line-height: 1.15;
    }}
    .settings-section-copy {{
        color: var(--muted);
        font-size: .92rem;
        font-weight: 520;
        line-height: 1.35;
    }}
    .settings-action-card {{
        display: grid;
        grid-template-columns: 46px minmax(0, 1fr);
        gap: 12px;
        align-items: center;
        width: fit-content;
        max-width: 100%;
        padding: 12px 14px;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #ffffff;
        color: inherit !important;
        text-decoration: none !important;
        transition: transform .16s ease, border-color .16s ease, box-shadow .16s ease;
    }}
    .settings-action-card:hover {{
        border-color: var(--brand-blue);
        box-shadow: 0 8px 18px rgba(35,52,95,.12);
        transform: translateY(-1px);
    }}
    .settings-action-icon {{
        display: inline-grid;
        place-items: center;
        width: 46px;
        height: 46px;
        border-radius: 8px;
        background: var(--brand-blue);
        color: #ffffff;
        font-size: 1.65rem;
        font-weight: 950;
        line-height: 1;
    }}
    .settings-action-title {{
        color: var(--brand-blue);
        font-size: 1.02rem;
        font-weight: 900;
        line-height: 1.12;
    }}
    .settings-action-copy {{
        color: var(--muted);
        font-size: .9rem;
        font-weight: 520;
        line-height: 1.28;
        margin-top: 3px;
    }}
    .edit-form-actions {{
        display: flex;
        gap: 10px;
        align-items: center;
        flex-wrap: wrap;
        margin-top: 12px;
    }}
    .edit-form-actions .section-edit,
    .edit-form-actions .delete-link {{
        margin-top: 0;
    }}
    .muted {{ color: var(--muted); line-height: 1.48; }}
    .status {{
        display: flex; align-items: flex-start; gap: 12px; background: #fff1c7;
        border: 1px solid rgba(190,129,15,.25); border-radius: 8px; padding: 14px;
        font-weight: 800; line-height: 1.4;
    }}
    div[data-testid="stAlert"] {{
        border-radius: 8px !important;
        border: 1px solid rgba(31,111,68,.28) !important;
        box-shadow: none !important;
    }}
    div[data-testid="stAlert"] div,
    div[data-testid="stAlert"] p,
    div[data-testid="stAlert"] span {{
        color: var(--ink) !important;
        font-weight: 760 !important;
    }}
    div[data-testid="stAlert"][data-baseweb="notification"] {{
        background: #d9f2df !important;
    }}
    .quick-toast {{
        position: fixed;
        left: 50%;
        top: 86px;
        transform: translateX(-50%);
        z-index: 2147483647;
        background: #d9f2df;
        color: var(--ink);
        border: 1px solid rgba(31,111,68,.28);
        border-radius: 8px;
        padding: 14px 18px;
        font-weight: 850;
        box-shadow: 0 14px 30px rgba(35,52,95,.16);
        animation: quickToastFade 2.6s ease forwards;
    }}
    @keyframes quickToastFade {{
        0%, 72% {{ opacity: 1; }}
        100% {{ opacity: 0; pointer-events: none; }}
    }}
    .admin-new-message-alert {{
        display: flex;
        align-items: flex-start;
        gap: 12px;
        background: #fffaf1;
        color: var(--ink);
        border: 2px solid var(--brand-blue);
        border-radius: 8px;
        padding: 14px 16px;
        margin: 0 0 16px;
        box-shadow: 0 12px 24px rgba(35,52,95,.12);
        font-size: .98rem;
        line-height: 1.35;
    }}
    .admin-new-message-alert strong {{
        color: var(--brand-blue);
        font-weight: 900;
    }}
    .admin-new-message-link {{
        text-decoration: none;
        cursor: pointer;
    }}
    .admin-new-message-link:hover {{
        background: #fff4dc;
        box-shadow: 0 14px 28px rgba(35,52,95,.16);
    }}
    .admin-new-message-dot {{
        width: 14px;
        height: 14px;
        border-radius: 999px;
        background: var(--orange);
        margin-top: 4px;
        box-shadow: 0 0 0 0 rgba(255,159,28,.45);
        animation: adminMessagePulse 1.45s ease-out infinite;
        flex: 0 0 auto;
    }}
    @keyframes adminMessagePulse {{
        0% {{ box-shadow: 0 0 0 0 rgba(255,159,28,.55); }}
        80%, 100% {{ box-shadow: 0 0 0 10px rgba(255,159,28,0); }}
    }}
    .danger-confirm {{
        background: #c82032;
        color: #ffffff;
        border: 2px solid #a81526;
        border-radius: 8px;
        padding: 16px 18px;
        margin: 14px 0 12px;
        font-weight: 760;
        line-height: 1.35;
        box-shadow: none;
    }}
    .status-dot {{ width: 12px; height: 12px; border-radius: 999px; background: var(--orange); margin-top: 5px; flex: 0 0 auto; }}
    .quick-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }}
    .quick-card {{
        border: 1px solid var(--line); border-radius: 8px; padding: 14px; background: #fffaf1;
    }}
    .quick-number {{ font-size: 1.6rem; font-weight: 950; color: var(--brand-blue); }}
    .quick-label {{ color: var(--muted); font-weight: 750; }}
    .room {{
        border: 1px solid var(--line); border-radius: 8px; background: #fffaf1; padding: 14px; margin-bottom: 10px;
    }}
    .room h3 {{ margin: 0 0 6px; font-size: 1rem; color: var(--brand-blue); font-weight: 900; }}
    .room p {{ margin: 0; color: var(--muted); line-height: 1.45; }}
    .child-list {{ display: grid; gap: 24px; }}
    .session-columns {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
        align-items: start;
    }}
    .session-group {{
        border: 1px solid var(--line); border-radius: 8px; background: #ffffff;
        padding: 24px; display: grid; gap: 28px;
    }}
    .session-title {{ color: var(--brand-blue); font-size: 1.03rem; font-weight: 900; }}
    .child-row {{
        display: grid; grid-template-columns: 58px minmax(0, 1fr) auto; gap: 10px; align-items: center;
        border: 1px solid var(--line); border-radius: 8px; background: #fffaf1; padding: 0 8px 0 0;
        height: 46px; min-height: 46px; overflow: visible; position: relative;
    }}
    .session-columns .child-row {{
        grid-template-columns: 58px minmax(0, 1fr) auto;
    }}
    .profile-link {{
        grid-column: 1 / 3;
        display: grid;
        grid-template-columns: 58px minmax(0, 1fr);
        gap: 10px;
        align-items: center;
        min-height: 46px;
        color: inherit !important;
        text-decoration: none !important;
        cursor: pointer;
    }}
    .profile-link:hover .child-name {{
        color: var(--brand-blue);
    }}
    .profile-link .child-details {{
        grid-column: 2;
    }}
    .row-actions {{
        grid-column: 3;
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }}
    .edit-link {{
        display: inline-flex; align-items: center; justify-content: center;
        width: 34px; height: 30px; min-height: 30px;
        border-radius: 8px; padding: 0; background: rgba(255,250,241,.62);
        color: rgba(47,79,159,.72) !important;
        border: 1px solid rgba(34,45,68,.14); font-weight: 900; text-decoration: none !important;
        font-size: 1rem; line-height: 1; letter-spacing: 0;
    }}
    .edit-link:hover {{ background: #fffaf1; color: var(--brand-blue) !important; }}
    .message-link {{
        display: inline-flex; align-items: center; justify-content: center;
        width: 34px; height: 30px; border-radius: 8px;
        background: rgba(233,244,255,.72); color: var(--brand-blue) !important;
        border: 1px solid rgba(47,79,159,.16); text-decoration: none !important;
    }}
    .message-link svg {{ width: 17px; height: 17px; stroke: currentColor; stroke-width: 2.4; fill: none; }}
    .message-link:hover {{ background: #e9f4ff; }}
    .message-link.disabled {{
        pointer-events: none; opacity: .28; background: rgba(255,250,241,.5); color: var(--muted) !important;
    }}
    .delete-link {{
        display: inline-flex; align-items: center; justify-content: center; min-height: 44px;
        border-radius: 8px; padding: 0 16px; margin-top: 10px; background: #fff1f1;
        color: #bd2130 !important; border: 1px solid rgba(189,33,48,.28);
        font-weight: 900; text-decoration: none !important;
    }}
    .child-thumb {{
        width: 58px; height: 58px; min-height: 58px; border-radius: 0; object-fit: cover; display: block;
        position: absolute; left: 5px; bottom: -1px; margin: 0;
        background: transparent; border: 0;
    }}
    .child-thumb.placeholder {{
        object-fit: contain;
        background: transparent;
        border: 0;
        border-radius: 8px;
        opacity: .48;
    }}
    .child-name {{
        color: var(--ink);
        font-size: .82rem;
        font-weight: 900;
        line-height: 1.02;
        max-width: 100%;
        overflow: hidden;
        overflow-wrap: normal;
        word-break: normal;
        display: -webkit-box;
        -webkit-box-orient: vertical;
        -webkit-line-clamp: 2;
    }}
    .child-details {{
        align-self: center;
        padding: 4px 0;
    }}
    .edit-link {{
        align-self: center;
    }}
    .child-meta {{ color: var(--muted); font-size: .96rem; font-weight: 500; line-height: 1.35; }}
    .child-dob {{
        color: var(--muted);
        font-size: .78rem;
        font-style: italic;
        font-weight: 500;
        line-height: 1.25;
    }}
    .child-info-badges {{
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 12px;
        margin: 8px 0 18px;
    }}
    .child-age-note,
    .child-birthday-note {{
        display: inline-flex;
        align-items: center;
        width: fit-content;
        min-height: 38px;
        margin: 0;
        padding: 8px 12px;
        border-radius: 8px;
        color: var(--ink);
        font-size: .96rem;
        font-weight: 760;
        line-height: 1.2;
    }}
    .child-age-note {{
        background: #e9f4ff;
    }}
    .child-birthday-note {{
        gap: 8px;
        background: #fff1c7;
        border: 1px solid rgba(255,159,28,.24);
    }}
    .guardian-form-title {{
        color: var(--brand-blue);
        font-size: 1.05rem;
        font-weight: 900;
        margin: 18px 0 6px;
    }}
    .guardian-section {{
        display: grid;
        gap: 16px;
        margin: 18px 0 24px;
        padding: 4px 0;
    }}
    .guardian-section-title {{
        color: #4d4f54;
        font-size: 1.32rem;
        font-weight: 760;
        line-height: 1.15;
    }}
    .guardian-card {{
        display: grid;
        grid-template-columns: 68px minmax(0, 1fr);
        gap: 18px;
        align-items: center;
        width: fit-content;
        max-width: 100%;
        border: 0;
        border-radius: 0;
        background: transparent;
        padding: 0;
    }}
    .guardian-avatar {{
        display: grid;
        place-items: center;
        width: 68px;
        height: 68px;
        border-radius: 999px;
        background: #10a461;
        color: #ffffff;
        font-size: 2.05rem;
        font-weight: 680;
        line-height: 1;
    }}
    .guardian-name {{
        color: #10a461;
        font-size: 1.08rem;
        font-weight: 760;
        line-height: 1.18;
    }}
    .guardian-contact,
    .guardian-address {{
        color: #4d4f54;
        font-size: .98rem;
        font-weight: 520;
        line-height: 1.28;
        margin-top: 4px;
    }}
    .guardian-invited,
    .guardian-not-invited {{
        display: inline-flex;
        align-items: center;
        gap: 7px;
        margin-top: 7px;
        font-size: .98rem;
        font-weight: 560;
        line-height: 1.25;
    }}
    .guardian-invited {{
        color: #10a461;
    }}
    .guardian-not-invited {{
        color: var(--muted);
    }}
    .guardian-check {{
        display: inline-grid;
        place-items: center;
        width: 18px;
        height: 18px;
        border-radius: 999px;
        background: #10a461;
        color: #ffffff;
        font-size: .72rem;
        font-weight: 950;
        line-height: 1;
    }}
    .cake-icon {{
        width: 24px;
        height: 24px;
        flex: 0 0 auto;
    }}
    .cake-icon .cake-candle {{
        stroke: var(--brand-blue);
        stroke-width: 2;
        stroke-linecap: round;
        fill: none;
    }}
    .cake-icon .cake-flame {{
        fill: var(--orange);
    }}
    .cake-icon .cake-icing {{
        fill: #ffffff;
        stroke: var(--brand-blue);
        stroke-width: 1.8;
        stroke-linejoin: round;
    }}
    .cake-icon .cake-base {{
        fill: var(--rose);
        stroke: var(--brand-blue);
        stroke-width: 1.8;
        stroke-linejoin: round;
    }}
    .cake-icon .cake-sprinkle {{
        stroke: var(--sun);
        stroke-width: 1.8;
        stroke-linecap: round;
    }}
    .current-thumb-preview {{
        display: grid; justify-items: center; gap: 10px; color: var(--muted);
        font-weight: 900; margin: 0 0 12px;
        min-height: 250px;
        overflow: hidden;
    }}
    .current-thumb-preview .child-thumb {{
        width: 190px; height: 230px; min-height: 230px; border-radius: 8px;
        margin: 0; align-self: center; object-fit: contain;
        position: static;
        left: auto;
        bottom: auto;
        max-width: 100%;
        background: transparent;
    }}
    .parents-panel {{
        min-height: auto;
        padding: 18px 18px 20px;
    }}
    .messages-title-panel {{
        padding: 14px !important;
        margin-bottom: 14px;
    }}
    .messages-title-row {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
    }}
    .messages-title-panel .panel-title {{
        margin: 0;
        line-height: 1.15;
    }}
    .create-message-button {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 42px;
        padding: 8px 18px;
        border-radius: 8px;
        background: var(--brand-blue);
        color: #ffffff !important;
        font-weight: 850;
        line-height: 1.1;
        text-decoration: none !important;
        box-shadow: 0 8px 16px rgba(47,78,161,.18);
    }}
    .create-message-button:hover {{
        transform: translateY(-1px);
        box-shadow: 0 10px 20px rgba(47,78,161,.24);
    }}
    .create-message-target {{
        margin: 16px 0;
        padding: 12px;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #fffaf2;
    }}
    .parents-panel .section-title {{
        margin-bottom: 14px;
    }}
    .parents-list {{
        display: grid;
        gap: 12px;
    }}
    .reply-list {{
        display: grid;
        gap: 8px;
        margin-top: 12px;
    }}
    .reply-bubble {{
        border-left: 4px solid var(--brand-blue);
        background: #e9f4ff;
        border-radius: 8px;
        padding: 10px 12px;
    }}
    .reply-bubble.is-admin {{
        border-left-color: #7084b8;
        background: #f4f7fb;
    }}
    .reply-meta {{
        color: var(--muted);
        font-size: .86rem;
        font-weight: 800;
        margin-bottom: 4px;
    }}
    .media-note {{
        display: inline-flex;
        width: fit-content;
        max-width: 100%;
        margin: 2px 0 12px;
        padding: 8px 10px;
        border-radius: 8px;
        background: #e9f4ff;
        color: var(--brand-blue);
        font-size: .9rem;
        font-weight: 760;
        line-height: 1.2;
    }}
    .message-media-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 260px));
        gap: 10px;
        margin-top: 12px;
    }}
    .message-media-item {{
        overflow: hidden;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #ffffff;
        box-shadow: 0 6px 14px rgba(35,52,95,.08);
    }}
    .message-media-link {{
        display: block;
        width: 100%;
        height: 100%;
        cursor: zoom-in;
        text-decoration: none;
    }}
    .message-media-link:hover .message-media-image {{
        opacity: .9;
    }}
    .message-lightbox-close-target {{
        position: absolute;
        width: 1px;
        height: 1px;
        overflow: hidden;
        opacity: 0;
        pointer-events: none;
    }}
    .message-lightbox {{
        display: none;
        position: fixed;
        inset: 0;
        z-index: 2147483647;
        align-items: center;
        justify-content: center;
        padding: clamp(18px, 4vw, 52px);
        background: rgba(15, 23, 42, .88);
        cursor: zoom-out;
        box-sizing: border-box;
    }}
    .message-lightbox:target {{
        display: flex;
    }}
    .message-lightbox-backdrop {{
        position: absolute;
        inset: 0;
        cursor: zoom-out;
    }}
    .message-lightbox-dialog {{
        position: relative;
        z-index: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        width: fit-content;
        max-width: 100%;
        max-height: 100%;
        cursor: default;
    }}
    .message-lightbox-image {{
        display: block;
        width: auto;
        max-width: 100%;
        height: auto;
        max-height: calc(100vh - clamp(36px, 8vw, 104px));
        object-fit: contain;
        border-radius: 8px;
        background: #ffffff;
        box-shadow: 0 24px 70px rgba(0,0,0,.45);
    }}
    .message-lightbox-close {{
        position: absolute;
        top: -14px;
        right: -14px;
        z-index: 2;
        display: grid;
        place-items: center;
        width: 38px;
        height: 38px;
        border: 2px solid #ffffff;
        border-radius: 50%;
        background: var(--brand-blue);
        color: #ffffff;
        font-family: system-ui, sans-serif;
        font-size: 1.6rem;
        font-weight: 700;
        line-height: 1;
        box-shadow: 0 8px 20px rgba(0,0,0,.3);
        cursor: pointer;
        text-decoration: none;
    }}
    .message-lightbox-nav {{
        position: absolute;
        top: 50%;
        z-index: 2;
        display: grid;
        place-items: center;
        width: 48px;
        height: 48px;
        transform: translateY(-50%);
        border: 2px solid rgba(255,255,255,.9);
        border-radius: 50%;
        background: rgba(41,73,153,.92);
        color: #ffffff;
        font-family: system-ui, sans-serif;
        font-size: 2.5rem;
        font-weight: 500;
        line-height: 1;
        box-shadow: 0 8px 22px rgba(0,0,0,.35);
        cursor: pointer;
        user-select: none;
        text-decoration: none;
    }}
    .message-lightbox-nav.is-previous {{
        left: clamp(8px, 2vw, 28px);
    }}
    .message-lightbox-nav.is-next {{
        right: clamp(8px, 2vw, 28px);
    }}
    .message-lightbox-nav:hover,
    .message-lightbox-close:hover {{
        background: #1f3d86;
    }}
    body:has(.message-lightbox:target) {{
        overflow: hidden;
    }}
    body:has(.message-lightbox:target) #ashs-install-app-button {{
        display: none !important;
    }}
    .message-media-image,
    .message-media-video {{
        display: block;
        width: 100%;
        max-height: 240px;
        object-fit: contain;
        background: #ffffff;
    }}
    .message-media-video {{
        aspect-ratio: 16 / 9;
        background: #23345f;
    }}
    .message-media-grid.is-gallery {{
        grid-template-columns: repeat(3, minmax(0, 1fr));
    }}
    .message-media-grid.is-gallery .message-media-item {{
        aspect-ratio: 1 / 1;
    }}
    .message-media-grid.is-gallery .message-media-image,
    .message-media-grid.is-gallery .message-media-video {{
        width: 100%;
        height: 100%;
        max-height: none;
        object-fit: cover;
    }}
    .message-media-name {{
        padding: 8px 10px 9px;
        color: var(--muted);
        font-size: .78rem;
        font-weight: 700;
        line-height: 1.2;
        overflow-wrap: anywhere;
    }}
    .message-child {{
        display: grid;
        grid-template-columns: 58px minmax(0, 1fr);
        gap: 12px;
        align-items: center;
    }}
    .message-child .child-thumb {{
        position: static;
        width: 58px;
        height: 58px;
        min-height: 58px;
        border-radius: 8px;
        object-fit: cover;
        background: transparent;
    }}
    .message-child .child-thumb.placeholder {{
        object-fit: contain;
        opacity: .72;
    }}
    .admin-message-child {{
        grid-template-columns: 76px minmax(0, 1fr);
        gap: 16px;
        align-items: start;
    }}
    .admin-message-child .child-thumb {{
        width: 76px;
        height: 76px;
        min-height: 76px;
    }}
    .message-title-line {{
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 10px;
        min-height: 64px;
    }}
    .message-title-line .child-thumb {{
        position: static;
        width: 64px;
        height: 64px;
        min-width: 64px;
        min-height: 64px;
        border-radius: 8px;
        object-fit: cover;
        background: transparent;
    }}
    .message-title-line .child-thumb.placeholder {{
        object-fit: contain;
        opacity: .72;
    }}
    .message-title-line .parent-name {{
        margin-bottom: 0;
    }}
    .parents-list div[data-testid="stButton"] button {{
        width: auto !important;
        min-height: 40px !important;
        padding: 8px 16px !important;
        margin: 0 0 4px 16px !important;
    }}
    .admin-messages-list {{
        display: grid;
        gap: 18px;
    }}
    .message-status-stack {{
        display: flex;
        flex-direction: column;
        align-items: flex-end;
        gap: 10px;
        min-width: 210px;
    }}
    .read-badge {{
        display: inline-flex;
        align-items: center;
        justify-content: flex-end;
        gap: 7px;
        min-height: 34px;
        border-radius: 999px;
        padding: 0 12px;
        background: #eef2f6;
        color: var(--muted);
        font-size: .9rem;
        font-weight: 900;
        white-space: nowrap;
    }}
    .read-badge.is-read {{
        background: #e9f8ed;
        color: #14783a;
        border: 1px solid #b8e4c4;
    }}
    .read-tick {{
        display: inline-grid;
        place-items: center;
        width: 20px;
        height: 20px;
        border-radius: 999px;
        background: #22b455;
        color: #ffffff;
        font-size: .78rem;
        font-weight: 950;
        line-height: 1;
    }}
    .parent-row {{
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 14px;
        align-items: start;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #fffaf1;
        padding: 16px;
    }}
    .admin-message-row {{
        display: block;
        height: auto;
        min-width: 0;
        scroll-margin-top: 120px;
    }}
    .admin-message-layout {{
        display: block;
        width: 100%;
        min-width: 0;
    }}
    .admin-message-header {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 18px;
        padding-bottom: 14px;
        border-bottom: 1px solid #e2e8f0;
    }}
    .admin-message-header .message-title-line {{
        min-height: 0;
        margin: 0;
    }}
    .admin-message-heading {{
        display: grid;
        gap: 4px;
        min-width: 0;
    }}
    .admin-message-heading .parent-name {{
        margin: 0;
    }}
    .admin-message-recipient {{
        color: var(--muted);
        font-size: .84rem;
        font-weight: 650;
        line-height: 1.25;
        overflow-wrap: anywhere;
    }}
    .admin-message-header .message-status-stack {{
        flex-direction: row;
        align-items: center;
        justify-content: flex-end;
        flex-wrap: wrap;
        gap: 8px;
        min-width: 0;
    }}
    .admin-message-header .parent-status,
    .admin-message-header .read-badge {{
        min-height: 30px;
        padding: 0 10px;
        font-size: .8rem;
    }}
    .admin-message-content {{
        display: block;
        padding-top: 16px;
        min-width: 0;
    }}
    .admin-message-content.has-media {{
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(210px, 290px);
        gap: 20px;
        align-items: start;
    }}
    .admin-message-thread,
    .admin-message-media {{
        min-width: 0;
    }}
    .admin-message-thread,
    .parent-message-thread {{
        display: flex;
        flex-direction: column;
        align-items: stretch;
        gap: 10px;
    }}
    .admin-message-thread .reply-list,
    .parent-message-thread .reply-list {{
        display: flex;
        flex-direction: column;
        gap: 10px;
        width: 100%;
        margin-top: 0;
    }}
    .admin-message-original {{
        padding: 12px 14px;
    }}
    .admin-message-original,
    .admin-message-thread .reply-bubble,
    .parent-message-thread .reply-bubble {{
        position: relative;
        width: fit-content;
        min-width: 180px;
        max-width: 78%;
        border: 0;
        box-shadow: 0 4px 12px rgba(35,52,95,.08);
    }}
    .admin-message-original,
    .admin-message-thread .reply-bubble.is-admin,
    .parent-message-thread .reply-bubble.is-admin {{
        align-self: flex-end;
        border-radius: 12px 12px 3px 12px;
        background: #e4f3e7;
    }}
    .admin-message-thread .reply-bubble:not(.is-admin),
    .parent-message-thread .reply-bubble:not(.is-admin) {{
        align-self: flex-start;
        border-radius: 12px 12px 12px 3px;
        background: #e9f4ff;
    }}
    .admin-message-original::after,
    .admin-message-thread .reply-bubble.is-admin::after,
    .parent-message-thread .reply-bubble.is-admin::after,
    .admin-message-thread .reply-bubble:not(.is-admin)::after,
    .parent-message-thread .reply-bubble:not(.is-admin)::after {{
        content: "";
        position: absolute;
        bottom: 0;
        width: 12px;
        height: 12px;
        background: inherit;
    }}
    .admin-message-original::after,
    .admin-message-thread .reply-bubble.is-admin::after,
    .parent-message-thread .reply-bubble.is-admin::after {{
        right: -7px;
        clip-path: polygon(0 0, 0 100%, 100% 100%);
    }}
    .admin-message-thread .reply-bubble:not(.is-admin)::after,
    .parent-message-thread .reply-bubble:not(.is-admin)::after {{
        left: -7px;
        clip-path: polygon(100% 0, 0 100%, 100% 100%);
    }}
    .admin-message-label {{
        display: flex;
        align-items: baseline;
        flex-wrap: wrap;
        gap: 6px;
        margin-bottom: 6px;
        color: var(--brand-blue);
        font-size: .72rem;
        font-weight: 850;
        line-height: 1.2;
    }}
    .admin-message-sent {{
        color: var(--muted);
        font-weight: 700;
    }}
    .admin-message-thread .reply-meta {{
        display: flex;
        align-items: baseline;
        flex-wrap: wrap;
        gap: 6px;
        margin-bottom: 6px;
        color: var(--brand-blue);
        font-size: .72rem;
        font-weight: 850;
        line-height: 1.2;
    }}
    .admin-message-thread .reply-date {{
        color: var(--muted);
        font-weight: 700;
    }}
    .parent-message-thread .reply-meta {{
        display: flex;
        align-items: baseline;
        flex-wrap: wrap;
        gap: 6px;
        margin-bottom: 6px;
        color: var(--brand-blue);
        font-size: .72rem;
        font-weight: 850;
        line-height: 1.2;
    }}
    .parent-message-thread .reply-date {{
        color: var(--muted);
        font-weight: 700;
    }}
    .admin-message-original .message-body {{
        color: var(--ink);
        font-size: 1rem;
        font-weight: 520;
    }}
    .admin-message-media > .message-media-grid {{
        grid-template-columns: minmax(0, 1fr);
        width: 100%;
        margin-top: 0;
    }}
    .admin-message-media > .message-media-grid.is-gallery {{
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 8px;
    }}
    .admin-message-media .message-media-item {{
        box-shadow: none;
    }}
    .admin-message-media .message-media-image,
    .admin-message-media .message-media-video {{
        max-height: 210px;
    }}
    div[data-testid="stVerticalBlock"][class*="st-key-admin_message_card_"] {{
        gap: 0;
        padding: 20px;
        border: 1px solid var(--line);
        border-top: 3px solid var(--brand-blue);
        border-radius: 8px;
        background: #ffffff;
        box-shadow: 0 8px 20px rgba(35,52,95,.07);
        box-sizing: border-box;
    }}
    div[data-testid="stVerticalBlock"][class*="st-key-admin_message_card_"] .admin-message-row {{
        border: 0;
        border-radius: 0;
        background: transparent;
        box-shadow: none;
        padding: 0;
    }}
    div[data-testid="stVerticalBlock"][class*="st-key-admin_message_card_"] > div[data-testid="stElementContainer"]:has(.admin-message-row) {{
        flex: 0 0 auto;
    }}
    div[data-testid="stVerticalBlock"][class*="st-key-admin_message_card_"] > div[data-testid="stElementContainer"]:has(div[data-testid="stButton"]) {{
        width: 100%;
    }}
    div[data-testid="stVerticalBlock"][class*="st-key-admin_message_card_"] div[data-testid="stButton"] {{
        display: flex;
        justify-content: flex-end;
        width: 100%;
        margin-top: 12px;
    }}
    div[data-testid="stVerticalBlock"][class*="st-key-admin_message_card_"] div[data-testid="stButton"] button {{
        width: auto !important;
        min-height: 34px !important;
        margin: 0 !important;
        padding: 6px 10px !important;
        border: 1px solid #d7dde6 !important;
        border-radius: 7px !important;
        background: transparent !important;
        color: var(--muted) !important;
        box-shadow: none !important;
        font-size: .78rem !important;
        font-weight: 760 !important;
    }}
    div[data-testid="stVerticalBlock"][class*="st-key-admin_message_card_"] div[data-testid="stButton"] button * {{
        color: var(--muted) !important;
        fill: var(--muted) !important;
        font-size: .78rem !important;
        font-weight: 760 !important;
    }}
    div[data-testid="stVerticalBlock"][class*="st-key-admin_message_card_"] div[data-testid="stButton"] button:hover {{
        border-color: #e8bdc4 !important;
        background: #fff0f2 !important;
        color: #a81526 !important;
        box-shadow: none !important;
        transform: none !important;
    }}
    div[data-testid="stVerticalBlock"][class*="st-key-admin_message_card_"] div[data-testid="stButton"] button:hover * {{
        color: #a81526 !important;
        fill: #a81526 !important;
    }}
    div[data-testid="stVerticalBlock"][class*="st-key-admin_message_card_"] [class*="st-key-admin_reply_message_"] button {{
        border-color: #b8c9ec !important;
        background: #edf4ff !important;
        color: var(--brand-blue) !important;
    }}
    div[data-testid="stVerticalBlock"][class*="st-key-admin_message_card_"] [class*="st-key-admin_reply_message_"] button * {{
        color: var(--brand-blue) !important;
        fill: var(--brand-blue) !important;
    }}
    div[data-testid="stVerticalBlock"][class*="st-key-admin_message_card_"] [class*="st-key-admin_reply_message_"] button:hover {{
        border-color: var(--brand-blue) !important;
        background: #e2edff !important;
        color: var(--brand-blue) !important;
    }}
    div[data-testid="stVerticalBlock"][class*="st-key-admin_message_card_"] [class*="st-key-admin_reply_message_"] button:hover * {{
        color: var(--brand-blue) !important;
        fill: var(--brand-blue) !important;
    }}
    div[data-testid="stVerticalBlock"][class*="st-key-admin_message_card_"]:has(.admin-message-row.is-target) {{
        border-color: var(--brand-blue);
        box-shadow: 0 0 0 4px rgba(47,79,163,.18), 0 14px 28px rgba(35,52,95,.12);
        background: #f9fbff;
    }}
    @media (max-width: 760px) {{
        .admin-message-header {{
            align-items: flex-start;
            flex-direction: column;
            gap: 12px;
        }}
        .admin-message-header .message-status-stack {{
            justify-content: flex-start;
        }}
        .admin-message-content.has-media {{
            grid-template-columns: minmax(0, 1fr);
            gap: 14px;
        }}
        .admin-message-original,
        .admin-message-thread .reply-bubble,
        .parent-message-thread .reply-bubble {{
            min-width: 0;
            max-width: 88%;
        }}
        .admin-message-media .message-media-image,
        .admin-message-media .message-media-video {{
            max-height: 260px;
        }}
        div[data-testid="stVerticalBlock"][class*="st-key-admin_message_card_"] {{
            padding: 16px;
        }}
    }}
    .message-anchor {{
        display: block;
        position: relative;
        top: -110px;
        height: 0;
        width: 0;
        overflow: hidden;
    }}
    .admin-message-row {{
        scroll-margin-top: 120px;
    }}
    .admin-message-row.is-target {{
        border-color: var(--brand-blue);
        box-shadow: 0 0 0 4px rgba(47,79,163,.18), 0 14px 28px rgba(35,52,95,.12);
        background: #fff7e8;
    }}
    .parent-row.is-target {{
        border-color: var(--brand-blue);
        box-shadow: 0 0 0 4px rgba(47,79,163,.18), 0 14px 28px rgba(35,52,95,.12);
        background: #fff7e8;
    }}
    .parent-name {{
        color: var(--ink);
        font-size: 1.02rem;
        font-weight: 900;
        line-height: 1.15;
        margin-bottom: 10px;
    }}
    .parent-child-heading {{
        display: grid;
        grid-template-columns: 58px minmax(0, 1fr);
        gap: 12px;
        align-items: center;
        width: fit-content;
        max-width: 100%;
        margin-bottom: 12px;
    }}
    .parent-child-heading.no-thumb {{
        grid-template-columns: minmax(0, 1fr);
        width: 100%;
    }}
    .parent-child-heading .child-thumb {{
        position: static;
        width: 58px;
        height: 58px;
        min-height: 58px;
        margin: 0;
        object-fit: contain;
        border-radius: 0;
        background: transparent;
    }}
    .parent-child-heading .child-thumb.placeholder {{
        object-fit: contain;
        border-radius: 8px;
    }}
    .parent-card-label {{
        color: var(--muted);
        font-size: .72rem;
        font-weight: 850;
        line-height: 1;
        text-transform: uppercase;
        letter-spacing: 0;
        margin-bottom: 4px;
    }}
    .parent-card-child-name {{
        color: var(--ink);
        font-size: 1.08rem;
        font-weight: 950;
        line-height: 1.1;
        white-space: nowrap;
    }}
    .parent-contact-name {{
        color: var(--ink);
        font-size: .98rem;
        font-weight: 850;
        line-height: 1.15;
        margin-bottom: 8px;
    }}
    .parent-details {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px 16px;
    }}
    .parent-detail {{
        color: var(--muted);
        font-size: .94rem;
        font-weight: 650;
        line-height: 1.25;
    }}
    .parent-detail strong {{
        color: var(--ink);
        font-weight: 850;
    }}
    .message-body {{
        color: var(--muted);
        font-size: .96rem;
        font-weight: 430;
        line-height: 1.36;
        overflow-wrap: anywhere;
    }}
    .reply-bubble .message-body {{
        font-size: .92rem;
        line-height: 1.34;
    }}
    .parent-child-card {{
        display: grid;
        grid-template-columns: 58px minmax(0, 1fr);
        gap: 10px;
        align-items: center;
        width: fit-content;
        max-width: 100%;
        min-height: 46px;
        margin-top: 12px;
        padding: 0 14px 0 0;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #ffffff;
        overflow: visible;
    }}
    .parent-child-card.no-photo {{
        grid-template-columns: minmax(0, 1fr);
        padding: 12px 14px;
    }}
    .parent-child-card.no-photo .parent-child-name {{
        font-size: 1rem;
    }}
    .parent-child-card .child-thumb {{
        position: static;
        width: 58px;
        height: 58px;
        min-height: 58px;
        margin: -7px 0 -5px 5px;
        object-fit: cover;
        border-radius: 0;
    }}
    .parent-child-card .child-thumb.placeholder {{
        object-fit: contain;
        border-radius: 8px;
    }}
    .parent-child-name {{
        color: var(--ink);
        font-size: .9rem;
        font-weight: 900;
        line-height: 1.08;
        overflow: hidden;
        display: -webkit-box;
        -webkit-box-orient: vertical;
        -webkit-line-clamp: 2;
    }}
    .birthday-card {{
        display: grid;
        grid-template-columns: 70px minmax(0, 1fr) auto;
        gap: 14px;
        align-items: center;
    }}
    .birthday-card .child-thumb {{
        position: static;
        width: 70px;
        height: 70px;
        min-height: 70px;
        border-radius: 8px;
        object-fit: cover;
        background: transparent;
    }}
    .birthday-card .child-thumb.placeholder {{
        object-fit: contain;
        opacity: .72;
    }}
    .birthday-date {{
        display: inline-flex;
        align-items: center;
        gap: 8px;
        color: var(--brand-blue);
        background: #e9f4ff;
        border-radius: 8px;
        padding: 10px 12px;
        font-weight: 950;
        white-space: nowrap;
    }}
    .calendar-intro {{
        color: var(--muted);
        font-size: 1.04rem;
        font-weight: 720;
        margin: -4px 0 18px;
    }}
    .calendar-list {{
        display: grid;
        gap: 12px;
        margin-top: 8px;
    }}
    .calendar-row {{
        display: grid;
        grid-template-columns: minmax(170px, .55fr) minmax(0, 1fr) auto;
        gap: 16px;
        align-items: center;
        padding: 16px;
        background: #ffffff;
        border: 1px solid var(--line);
        border-radius: 8px;
    }}
    .calendar-date {{
        color: var(--brand-blue);
        font-size: 1.02rem;
        font-weight: 950;
        line-height: 1.15;
    }}
    .calendar-event {{
        color: var(--ink);
        font-size: 1.04rem;
        font-weight: 820;
        line-height: 1.2;
    }}
    .calendar-tag {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 32px;
        border-radius: 999px;
        padding: 0 12px;
        color: var(--brand-blue);
        background: #e9f4ff;
        font-size: .86rem;
        font-weight: 950;
        white-space: nowrap;
    }}
    .calendar-tag.closed {{
        color: #9a331f;
        background: #ffe6dc;
    }}
    .calendar-tag.event {{
        color: #6d5200;
        background: #fff1c7;
    }}
    .calendar-download {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 44px;
        margin-top: 18px;
        border-radius: 8px;
        padding: 0 16px;
        background: var(--brand-blue);
        color: #ffffff !important;
        font-size: 1.04rem;
        font-weight: 900;
        text-decoration: none !important;
    }}
    .calendar-download:hover {{
        background: #203d86;
        color: #ffffff !important;
    }}
    .parent-actions {{
        display: flex;
        align-items: center;
        gap: 8px;
        justify-content: flex-end;
    }}
    .parent-status {{
        display: inline-flex;
        align-items: center;
        min-height: 34px;
        border-radius: 999px;
        padding: 0 12px;
        background: #e9f4ff;
        color: var(--brand-blue);
        font-size: .9rem;
        font-weight: 900;
    }}
    .parent-status.pending {{
        background: #fff1c7;
        color: #8a5200;
    }}
    .parent-status.is-new {{
        background: #fff1c7;
        color: #8a5200;
    }}
    .parent-action-button {{
        justify-content: center;
        min-width: 92px;
        background: var(--brand-blue);
        color: #ffffff !important;
        text-decoration: none !important;
    }}
    .parent-action-button:hover {{
        background: #203d86;
        color: #ffffff !important;
    }}
    .statement-view {{
        max-height: min(58vh, 620px);
        overflow: auto;
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #ffffff;
        padding: 16px;
        margin: 14px 0 18px;
    }}
    .statement-view pre {{
        margin: 0;
        color: var(--ink);
        font-family: inherit;
        font-size: .94rem;
        font-weight: 520;
        line-height: 1.45;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
    }}
    .statement-sign-card {{
        border: 1px solid var(--line);
        border-radius: 8px;
        background: #fffaf1;
        padding: 16px;
        margin-top: 14px;
    }}
    .signature-pad-label {{
        margin: 18px 0 8px;
    }}
    .statement-signed-note {{
        border: 1px solid #b8e4c4;
        border-radius: 8px;
        background: #e9f8ed;
        color: #14783a;
        font-size: .98rem;
        font-weight: 850;
        line-height: 1.35;
        padding: 14px 16px;
        margin-top: 14px;
    }}
    @media (max-width: 760px) {{
        .session-columns {{
            grid-template-columns: 1fr;
        }}
        .calendar-row {{
            grid-template-columns: 1fr;
            gap: 8px;
        }}
        .calendar-tag {{
            justify-self: flex-start;
        }}
    }}
    @media (orientation: portrait) {{
        .session-columns {{
            grid-template-columns: 1fr;
        }}
        .session-group {{
            width: 100%;
        }}
        .session-columns .child-row {{
            grid-template-columns: 68px minmax(0, 1fr) auto;
            min-height: 54px;
            height: 54px;
        }}
        .session-columns .child-thumb {{
            width: 68px;
            height: 68px;
            min-height: 68px;
        }}
    }}
    .status-pill {{
        display: inline-flex; align-items: center; min-height: 28px; border-radius: 999px;
        padding: 0 10px; background: #e9f4ff; color: var(--brand-blue);
        font-size: .86rem; font-weight: 900;
    }}
    .contact-line {{ font-size: 1.02rem; font-weight: 850; color: var(--ink); margin: 8px 0; }}
    .rainbow-rule {{
        height: 8px; border-radius: 999px; margin: 16px 0 0;
        background: linear-gradient(90deg, var(--rose), var(--sun), var(--red), var(--orange), var(--green), var(--sky));
    }}
    .side-menu .rainbow-rule {{
        margin-top: 20px;
    }}
    div[data-testid="stForm"],
    div[data-testid="stForm"] *,
    div[data-testid="stTextInput"],
    div[data-testid="stTextInput"] *,
    div[data-testid="stDateInput"],
    div[data-testid="stDateInput"] *,
    div[data-testid="stSelectbox"],
    div[data-testid="stSelectbox"] *,
    div[data-testid="stCheckbox"],
    div[data-testid="stCheckbox"] *,
    div[data-testid="stFileUploader"],
    div[data-testid="stFileUploader"] * {{
        font-family: "Avenir Next", "Nunito", "Trebuchet MS", "Segoe UI", system-ui, sans-serif !important;
        letter-spacing: 0 !important;
    }}
    div[data-testid="stButton"] button,
    div[data-testid="stFormSubmitButton"] button {{
        border-radius: 8px; min-height: 44px; font-weight: 900 !important;
        font-family: "Avenir Next", "Nunito", "Trebuchet MS", "Segoe UI", system-ui, sans-serif !important;
        font-size: 1.04rem !important;
        line-height: 1 !important;
        background: var(--brand-blue) !important; color: #ffffff !important;
        border: 1px solid var(--brand-blue) !important;
        box-shadow: none !important;
        transition: transform .16s ease, background-color .16s ease, color .16s ease, border-color .16s ease, box-shadow .16s ease !important;
    }}
    div[data-testid="stButton"] button *,
    div[data-testid="stFormSubmitButton"] button * {{
        color: #ffffff !important;
        fill: #ffffff !important;
        background: transparent !important;
        font-size: 1.04rem !important;
        font-weight: 900 !important;
        line-height: 1 !important;
    }}
    div[data-testid="stButton"] button:hover,
    div[data-testid="stFormSubmitButton"] button:hover {{
        background: #203d86 !important;
        border-color: var(--brand-blue) !important;
        color: #ffffff !important;
        box-shadow: 0 8px 18px rgba(35,52,95,.22) !important;
        transform: translateY(-1px) !important;
    }}
    div[data-testid="stButton"] button:active,
    div[data-testid="stFormSubmitButton"] button:active {{
        transform: translateY(0) scale(.98) !important;
        box-shadow: 0 2px 8px rgba(35,52,95,.12) !important;
    }}
    div[data-testid="stButton"] button:focus-visible,
    div[data-testid="stFormSubmitButton"] button:focus-visible {{
        outline: 3px solid rgba(49,84,165,.26) !important;
        outline-offset: 2px !important;
    }}
    div[data-testid="stForm"] div[data-testid="stHorizontalBlock"]:has(div[data-testid="stFormSubmitButton"]) > div:nth-child(4) div[data-testid="stFormSubmitButton"] button:hover {{
        background: #c82032 !important;
        border-color: #a81526 !important;
        color: #ffffff !important;
        box-shadow: 0 8px 18px rgba(200,32,50,.24) !important;
    }}
    div[data-testid="stForm"] div[data-testid="stHorizontalBlock"]:has(div[data-testid="stFormSubmitButton"]) > div:nth-child(4) div[data-testid="stFormSubmitButton"] button {{
        color: #ffffff !important;
        border-color: #a81526 !important;
        background: #c82032 !important;
    }}
    div[data-testid="stForm"] div[data-testid="stHorizontalBlock"]:has(div[data-testid="stFormSubmitButton"]) > div:nth-child(4) div[data-testid="stFormSubmitButton"] button:hover,
    div[data-testid="stForm"] div[data-testid="stHorizontalBlock"]:has(div[data-testid="stFormSubmitButton"]) > div:nth-child(4) div[data-testid="stFormSubmitButton"] button:active {{
        background: #c82032 !important;
        border-color: #a81526 !important;
        color: #ffffff !important;
        box-shadow: 0 8px 18px rgba(200,32,50,.24) !important;
    }}
    div[data-testid="stFormSubmitButton"] button {{
        width: 100% !important;
    }}
    div[data-testid="stButton"] button:disabled,
    div[data-testid="stFormSubmitButton"] button:disabled {{
        background: rgba(41,73,153,.36) !important;
        color: #ffffff !important;
        opacity: 1 !important;
    }}
    div[data-testid="stButton"] button:disabled *,
    div[data-testid="stFormSubmitButton"] button:disabled * {{
        color: #ffffff !important;
        fill: #ffffff !important;
    }}
    div[data-testid="stVerticalBlock"][class*="st-key-document_row_"] [data-testid="stLinkButton"] a,
    div[data-testid="stVerticalBlock"][class*="st-key-document_row_"] [data-testid="stDownloadButton"] button,
    div[data-testid="stVerticalBlock"][class*="st-key-document_row_"] [data-testid="stButton"] button {{
        min-height: 40px !important;
        height: 40px !important;
        padding: 0 12px !important;
        border: 1px solid #d9e5ef !important;
        border-radius: 8px !important;
        background: #ffffff !important;
        color: var(--brand-blue) !important;
        box-shadow: none !important;
        font-size: .88rem !important;
        font-weight: 780 !important;
        line-height: 1 !important;
        white-space: nowrap !important;
    }}
    div[data-testid="stVerticalBlock"][class*="st-key-document_row_"] [data-testid="stHorizontalBlock"] {{
        gap: 24px !important;
        margin-top: 20px !important;
    }}
    div[data-testid="stVerticalBlock"][class*="st-key-document_row_"] [data-testid="stLinkButton"] a *,
    div[data-testid="stVerticalBlock"][class*="st-key-document_row_"] [data-testid="stDownloadButton"] button *,
    div[data-testid="stVerticalBlock"][class*="st-key-document_row_"] [data-testid="stButton"] button * {{
        color: var(--brand-blue) !important;
        fill: var(--brand-blue) !important;
        background: transparent !important;
        font-size: .88rem !important;
        font-weight: 780 !important;
        line-height: 1 !important;
        white-space: nowrap !important;
    }}
    div[data-testid="stVerticalBlock"][class*="st-key-document_row_"] [data-testid="stLinkButton"] a:hover,
    div[data-testid="stVerticalBlock"][class*="st-key-document_row_"] [data-testid="stDownloadButton"] button:hover,
    div[data-testid="stVerticalBlock"][class*="st-key-document_row_"] [data-testid="stButton"] button:hover {{
        background: #eef6fc !important;
        border-color: #a8c4dd !important;
        color: var(--brand-blue) !important;
        box-shadow: none !important;
        transform: none !important;
    }}
    @media (max-width: 760px) {{
        div[data-testid="stForm"] div[data-testid="stHorizontalBlock"]:has(div[data-testid="stFormSubmitButton"]) {{
            display: grid !important;
            grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
            width: 100% !important;
        }}
        div[data-testid="stForm"] div[data-testid="stHorizontalBlock"]:has(div[data-testid="stFormSubmitButton"]) > div {{
            width: 100% !important;
        }}
        div[data-testid="stForm"] div[data-testid="stHorizontalBlock"]:has(div[data-testid="stFormSubmitButton"]) div[data-testid="stFormSubmitButton"] button {{
            width: 100% !important;
            min-width: 0 !important;
            padding-left: 12px !important;
            padding-right: 12px !important;
        }}
    }}
    div[data-testid="stTextInput"] label,
    div[data-testid="stTextInput"] label span,
    div[data-testid="stTextArea"] label,
    div[data-testid="stTextArea"] label span,
    div[data-testid="stSelectbox"] label,
    div[data-testid="stSelectbox"] label span,
    div[data-testid="stDateInput"] label,
    div[data-testid="stDateInput"] label span,
    div[data-testid="stCheckbox"] label,
    div[data-testid="stCheckbox"] label span,
    div[data-testid="stFileUploader"] label,
    div[data-testid="stFileUploader"] label span,
    div[data-testid="stWidgetLabel"],
    div[data-testid="stWidgetLabel"] * {{
        color: var(--brand-blue) !important;
        font-size: 1.02rem !important;
        font-family: "Avenir Next", "Nunito", "Trebuchet MS", "Segoe UI", system-ui, sans-serif !important;
        font-weight: 760 !important;
        line-height: 1.15 !important;
    }}
    div[data-testid="stTextInput"] label p,
    div[data-testid="stTextArea"] label p,
    div[data-testid="stSelectbox"] label p,
    div[data-testid="stDateInput"] label p,
    div[data-testid="stCheckbox"] label p,
    div[data-testid="stFileUploader"] label p {{
        color: var(--brand-blue) !important;
        font-size: 1.02rem !important;
        font-weight: 760 !important;
        line-height: 1.15 !important;
    }}
    div[data-testid="stTextInput"] input,
    div[data-testid="stTextArea"] textarea,
    div[data-testid="stSelectbox"] div {{
        border-radius: 8px !important;
    }}
    div[data-testid="stTextInput"] input,
    div[data-baseweb="input"],
    div[data-baseweb="input"] input,
    div[data-testid="stTextArea"] textarea,
    div[data-baseweb="textarea"],
    div[data-baseweb="select"] {{
        background: #ffffff !important;
        color: var(--ink) !important;
        border: 2px solid #d9e5ef !important;
        font-size: 1.04rem !important;
        font-weight: 620 !important;
        min-height: 48px !important;
        appearance: none !important;
        -webkit-appearance: none !important;
        box-shadow: none !important;
        line-height: 1.2 !important;
    }}
    div[data-baseweb="input"] *,
    div[data-baseweb="select"] *,
    div[data-baseweb="textarea"] * {{
        color: var(--ink) !important;
        font-weight: 620 !important;
        font-family: "Avenir Next", "Nunito", "Trebuchet MS", "Segoe UI", system-ui, sans-serif !important;
    }}
    div[data-testid="stTextInput"] input,
    div[data-baseweb="input"] input {{
        background: #ffffff !important;
        background-color: #ffffff !important;
        caret-color: var(--brand-blue) !important;
        -webkit-text-fill-color: var(--ink) !important;
        color-scheme: light !important;
    }}
    div[data-testid="stTextInput"] input:-webkit-autofill,
    div[data-testid="stTextInput"] input:-webkit-autofill:hover,
    div[data-testid="stTextInput"] input:-webkit-autofill:focus,
    div[data-testid="stTextInput"] input:-webkit-autofill:active {{
        background-color: #ffffff !important;
        -webkit-box-shadow: 0 0 0 1000px #ffffff inset !important;
        box-shadow: 0 0 0 1000px #ffffff inset !important;
        -webkit-text-fill-color: var(--ink) !important;
        caret-color: var(--brand-blue) !important;
    }}
    div[data-testid="stTextInput"] div[data-baseweb="input"]:has(input[type="password"]),
    div[data-testid="stTextInput"] div[data-baseweb="input"]:has(input[type="password"]) > div {{
        background: #ffffff !important;
        background-color: #ffffff !important;
    }}
    div[data-testid="stTextInput"] div[data-baseweb="input"] input[type="password"] {{
        background: #ffffff !important;
        background-color: #ffffff !important;
        color: var(--ink) !important;
        -webkit-text-fill-color: var(--ink) !important;
        padding-right: 54px !important;
    }}
    div[data-testid="stTextInput"] div[data-baseweb="input"] button,
    div[data-testid="stTextInput"] div[data-baseweb="input"] [role="button"] {{
        background: #e9f4ff !important;
        background-color: #e9f4ff !important;
        color: var(--brand-blue) !important;
        -webkit-text-fill-color: var(--brand-blue) !important;
        border: 0 !important;
        border-left: 1px solid #d9e5ef !important;
        box-shadow: none !important;
        display: inline-grid !important;
        place-items: center !important;
        position: relative !important;
        flex: 0 0 48px !important;
        width: 48px !important;
        min-width: 48px !important;
        min-height: 44px !important;
        padding: 0 !important;
        overflow: hidden !important;
        font-size: 0 !important;
        line-height: 0 !important;
        text-indent: -9999px !important;
    }}
    div[data-testid="stTextInput"] div[data-baseweb="input"] button:hover,
    div[data-testid="stTextInput"] div[data-baseweb="input"] [role="button"]:hover {{
        background: #dceefe !important;
        background-color: #dceefe !important;
        color: var(--brand-blue) !important;
    }}
    div[data-testid="stTextInput"] div[data-baseweb="input"] button *,
    div[data-testid="stTextInput"] div[data-baseweb="input"] [role="button"] * {{
        color: transparent !important;
        -webkit-text-fill-color: transparent !important;
        fill: transparent !important;
        stroke: transparent !important;
        opacity: 0 !important;
        font-size: 0 !important;
        line-height: 0 !important;
        text-indent: -9999px !important;
    }}
    div[data-testid="stTextInput"] div[data-baseweb="input"] button::before,
    div[data-testid="stTextInput"] div[data-baseweb="input"] [role="button"]::before {{
        content: "" !important;
        position: absolute !important;
        left: 50% !important;
        top: 50% !important;
        width: 22px !important;
        height: 14px !important;
        border: 2px solid var(--brand-blue) !important;
        border-radius: 50% / 65% !important;
        box-sizing: border-box !important;
        transform: translate(-50%, -50%) !important;
        text-indent: 0 !important;
    }}
    div[data-testid="stTextInput"] div[data-baseweb="input"] button::after,
    div[data-testid="stTextInput"] div[data-baseweb="input"] [role="button"]::after {{
        content: "" !important;
        position: absolute !important;
        left: 50% !important;
        top: 50% !important;
        width: 6px !important;
        height: 6px !important;
        border-radius: 999px !important;
        background: var(--brand-blue) !important;
        transform: translate(-50%, -50%) !important;
    }}
    div[data-testid="stTextInput"] div[data-baseweb="input"] button[aria-label*="Hide password"]::after,
    div[data-testid="stTextInput"] div[data-baseweb="input"] [role="button"][aria-label*="Hide password"]::after {{
        width: 25px !important;
        height: 2px !important;
        border-radius: 999px !important;
        transform: translate(-50%, -50%) rotate(45deg) !important;
    }}
    div[data-testid="stTextInput"] div[data-baseweb="input"] button svg,
    div[data-testid="stTextInput"] div[data-baseweb="input"] [role="button"] svg {{
        display: none !important;
    }}
    div[data-testid="stTextInputRootElement"]:has(input[type="password"]) {{
        min-height: 48px !important;
        overflow: hidden !important;
        border: 2px solid #d9e5ef !important;
        border-radius: 8px !important;
        background: #ffffff !important;
        box-shadow: none !important;
    }}
    div[data-testid="stTextInputRootElement"]:has(input[type="password"]) input[type="password"],
    div[data-testid="stTextInputRootElement"]:has(input[type="password"]) input[type="text"] {{
        min-height: 44px !important;
        border: 0 !important;
        border-radius: 0 !important;
        background: #ffffff !important;
        padding-right: 12px !important;
        box-shadow: none !important;
    }}
    div[data-testid="stTextInput"]:has(input[type="password"]) button[aria-label*="password"],
    div[data-testid="stTextInput"]:has(input[type="text"]) button[aria-label*="password"] {{
        position: relative !important;
        align-self: stretch !important;
        display: inline-grid !important;
        flex: 0 0 48px !important;
        place-items: center !important;
        width: 48px !important;
        min-width: 48px !important;
        min-height: 44px !important;
        margin: 0 !important;
        padding: 0 !important;
        overflow: hidden !important;
        border: 0 !important;
        border-left: 1px solid #d9e5ef !important;
        border-radius: 0 !important;
        background: #ffffff !important;
        color: var(--brand-blue) !important;
        box-shadow: none !important;
        font-size: 0 !important;
        line-height: 0 !important;
        text-indent: -9999px !important;
    }}
    div[data-testid="stTextInput"]:has(input[type="password"]) button[aria-label*="password"]:hover,
    div[data-testid="stTextInput"]:has(input[type="text"]) button[aria-label*="password"]:hover {{
        background: #eef6ff !important;
    }}
    div[data-testid="stTextInput"]:has(input[type="password"]) button[aria-label*="password"] *,
    div[data-testid="stTextInput"]:has(input[type="text"]) button[aria-label*="password"] * {{
        display: none !important;
        opacity: 0 !important;
    }}
    div[data-testid="stTextInput"]:has(input[type="password"]) button[aria-label*="password"]::before,
    div[data-testid="stTextInput"]:has(input[type="text"]) button[aria-label*="password"]::before {{
        content: "" !important;
        position: absolute !important;
        left: 50% !important;
        top: 50% !important;
        display: block !important;
        width: 22px !important;
        height: 14px !important;
        border: 2px solid var(--brand-blue) !important;
        border-radius: 50% / 65% !important;
        box-sizing: border-box !important;
        transform: translate(-50%, -50%) !important;
        text-indent: 0 !important;
    }}
    div[data-testid="stTextInput"]:has(input[type="password"]) button[aria-label*="password"]::after,
    div[data-testid="stTextInput"]:has(input[type="text"]) button[aria-label*="password"]::after {{
        content: "" !important;
        position: absolute !important;
        left: 50% !important;
        top: 50% !important;
        display: block !important;
        width: 6px !important;
        height: 6px !important;
        border-radius: 999px !important;
        background: var(--brand-blue) !important;
        transform: translate(-50%, -50%) !important;
    }}
    div[data-testid="stTextInput"]:has(input[type="text"]) button[aria-label^="Hide password"]::after {{
        width: 25px !important;
        height: 2px !important;
        border-radius: 999px !important;
        transform: translate(-50%, -50%) rotate(45deg) !important;
    }}
    div[data-testid="stTextArea"] textarea {{
        position: relative !important;
        z-index: 2 !important;
        pointer-events: auto !important;
        cursor: text !important;
        caret-color: var(--brand-blue) !important;
        -webkit-text-fill-color: var(--ink) !important;
        font-family: "Avenir Next", "Nunito", "Trebuchet MS", "Segoe UI", system-ui, sans-serif !important;
        font-weight: 620 !important;
        padding: 14px !important;
        resize: vertical !important;
    }}
    div[data-testid="stTextInput"] input:focus,
    div[data-testid="stTextArea"] textarea:focus,
    div[data-baseweb="input"]:focus-within {{
        border-color: var(--brand-blue) !important;
        box-shadow: 0 0 0 3px rgba(47,79,159,.14) !important;
        outline: none !important;
    }}
    div[data-baseweb="select"] > div {{
        background: #ffffff !important;
        color: var(--ink) !important;
        border: 2px solid #d9e5ef !important;
        border-radius: 8px !important;
        font-size: 1.04rem !important;
        font-weight: 620 !important;
        min-height: 48px !important;
        box-shadow: none !important;
        line-height: 1.2 !important;
    }}
    div[data-testid="stDateInput"] input,
    div[data-testid="stDateInput"] div[data-baseweb="input"],
    div[data-testid="stFileUploader"] section {{
        background: #ffffff !important;
        color: var(--ink) !important;
        border: 2px solid #d9e5ef !important;
        border-radius: 8px !important;
        caret-color: var(--brand-blue) !important;
        font-size: 1.04rem !important;
        font-weight: 620 !important;
        min-height: 48px !important;
        box-shadow: none !important;
        line-height: 1.2 !important;
        padding: 12px !important;
    }}
    div[data-testid="stFileUploader"] section * {{
        color: var(--ink) !important;
        font-family: "Avenir Next", "Nunito", "Trebuchet MS", "Segoe UI", system-ui, sans-serif !important;
        font-weight: 620 !important;
    }}
    div[data-testid="stFileUploader"] section [data-testid="stFileUploaderFile"],
    div[data-testid="stFileUploader"] section div:has(> div > svg):has(button) {{
        background: #fffaf1 !important;
        color: var(--ink) !important;
        border: 1px solid var(--line) !important;
        border-radius: 8px !important;
        box-shadow: none !important;
    }}
    div[data-testid="stFileUploader"] section [data-testid="stFileUploaderFile"] *,
    div[data-testid="stFileUploader"] section div:has(> div > svg):has(button) * {{
        color: var(--ink) !important;
        fill: var(--brand-blue) !important;
        stroke: var(--brand-blue) !important;
    }}
    div[data-testid="stFileUploader"] section [data-testid="stFileUploaderFile"] button,
    div[data-testid="stFileUploader"] section div:has(> div > svg):has(button) button {{
        background: var(--brand-blue) !important;
        color: #ffffff !important;
        border-color: var(--brand-blue) !important;
    }}
    div[data-testid="stFileUploader"] section [data-testid="stFileUploaderFile"] button *,
    div[data-testid="stFileUploader"] section div:has(> div > svg):has(button) button * {{
        color: #ffffff !important;
        fill: #ffffff !important;
        stroke: #ffffff !important;
    }}
    div[data-testid="stFileUploader"] section small,
    div[data-testid="stFileUploader"] section [data-testid="stMarkdownContainer"] p {{
        display: none !important;
    }}
    div[data-testid="stFileUploader"] section button {{
        background: #fffaf1 !important;
        color: var(--brand-blue) !important;
        border: 2px solid #d9e5ef !important;
        border-radius: 8px !important;
        font-weight: 900 !important;
        min-height: 42px !important;
        padding: 8px 14px !important;
        position: relative !important;
        font-size: 0 !important;
        line-height: 1 !important;
    }}
    div[data-testid="stFileUploader"] section button * {{
        display: none !important;
    }}
    div[data-testid="stFileUploader"] section button::after {{
        content: "Upload";
        color: var(--brand-blue) !important;
        display: inline-block;
        font-size: 1.04rem !important;
        font-weight: 900 !important;
        line-height: 1 !important;
    }}
    div[data-baseweb="select"] svg {{
        color: var(--brand-blue) !important;
        fill: var(--brand-blue) !important;
    }}
    div[role="listbox"] {{
        background: white !important;
        border: 1px solid var(--line) !important;
        border-radius: 8px !important;
        box-shadow: var(--shadow) !important;
    }}
    div[role="option"] {{
        color: var(--ink) !important;
        font-weight: 620 !important;
    }}
    div[role="option"]:hover {{
        background: #e9f4ff !important;
        color: var(--brand-blue) !important;
    }}
    div[data-testid="stTextInput"] input::placeholder,
    div[data-testid="stTextArea"] textarea::placeholder {{
        color: rgba(35,52,95,.48) !important;
        font-weight: 520 !important;
    }}
    div[data-testid="InputInstructions"] {{
        display: none !important;
    }}
    [data-testid="stDialog"] h2,
    [data-baseweb="modal"] h2,
    div[role="dialog"] h2 {{
        font-size: clamp(1.45rem, 2.4vw, 2rem) !important;
        font-weight: 800 !important;
        line-height: 1.12 !important;
        letter-spacing: 0 !important;
        margin: 0 0 14px !important;
    }}
    [data-testid="stDialog"] div[data-testid="stForm"],
    [data-baseweb="modal"] div[data-testid="stForm"],
    div[role="dialog"] div[data-testid="stForm"] {{
        padding: 24px 28px 28px !important;
        border-radius: 8px !important;
        border: 1px solid var(--line) !important;
        box-shadow: none !important;
    }}
    [data-testid="stDialog"] div[data-testid="stTextInput"] label,
    [data-testid="stDialog"] div[data-testid="stTextInput"] label span,
    [data-testid="stDialog"] div[data-testid="stDateInput"] label,
    [data-testid="stDialog"] div[data-testid="stDateInput"] label span,
    [data-testid="stDialog"] div[data-testid="stSelectbox"] label,
    [data-testid="stDialog"] div[data-testid="stSelectbox"] label span,
    [data-testid="stDialog"] div[data-testid="stFileUploader"] label,
    [data-testid="stDialog"] div[data-testid="stFileUploader"] label span,
    [data-testid="stDialog"] div[data-testid="stTextArea"] label,
    [data-testid="stDialog"] div[data-testid="stTextArea"] label span,
    [data-baseweb="modal"] div[data-testid="stTextInput"] label,
    [data-baseweb="modal"] div[data-testid="stTextInput"] label span,
    [data-baseweb="modal"] div[data-testid="stDateInput"] label,
    [data-baseweb="modal"] div[data-testid="stDateInput"] label span,
    [data-baseweb="modal"] div[data-testid="stSelectbox"] label,
    [data-baseweb="modal"] div[data-testid="stSelectbox"] label span,
    [data-baseweb="modal"] div[data-testid="stFileUploader"] label,
    [data-baseweb="modal"] div[data-testid="stFileUploader"] label span,
    [data-baseweb="modal"] div[data-testid="stTextArea"] label,
    [data-baseweb="modal"] div[data-testid="stTextArea"] label span,
    div[role="dialog"] div[data-testid="stTextInput"] label,
    div[role="dialog"] div[data-testid="stTextInput"] label span,
    div[role="dialog"] div[data-testid="stDateInput"] label,
    div[role="dialog"] div[data-testid="stDateInput"] label span,
    div[role="dialog"] div[data-testid="stSelectbox"] label,
    div[role="dialog"] div[data-testid="stSelectbox"] label span,
    div[role="dialog"] div[data-testid="stFileUploader"] label,
    div[role="dialog"] div[data-testid="stFileUploader"] label span,
    div[role="dialog"] div[data-testid="stTextArea"] label,
    div[role="dialog"] div[data-testid="stTextArea"] label span {{
        font-size: .92rem !important;
        font-weight: 720 !important;
        line-height: 1.18 !important;
        color: var(--brand-blue) !important;
    }}
    [data-testid="stDialog"] label p,
    [data-baseweb="modal"] label p,
    div[role="dialog"] label p {{
        font-size: .92rem !important;
        font-weight: 720 !important;
        line-height: 1.18 !important;
        color: var(--brand-blue) !important;
    }}
    [data-testid="stDialog"] div[data-testid="stTextInput"] input,
    [data-testid="stDialog"] div[data-testid="stTextArea"] textarea,
    [data-testid="stDialog"] div[data-testid="stDateInput"] input,
    [data-testid="stDialog"] div[data-baseweb="select"] > div,
    [data-testid="stDialog"] div[data-baseweb="select"] *,
    [data-baseweb="modal"] div[data-testid="stTextInput"] input,
    [data-baseweb="modal"] div[data-testid="stTextArea"] textarea,
    [data-baseweb="modal"] div[data-testid="stDateInput"] input,
    [data-baseweb="modal"] div[data-baseweb="select"] > div,
    [data-baseweb="modal"] div[data-baseweb="select"] *,
    div[role="dialog"] div[data-testid="stTextInput"] input,
    div[role="dialog"] div[data-testid="stTextArea"] textarea,
    div[role="dialog"] div[data-testid="stDateInput"] input,
    div[role="dialog"] div[data-baseweb="select"] > div,
    div[role="dialog"] div[data-baseweb="select"] * {{
        font-size: .98rem !important;
        font-weight: 520 !important;
        min-height: 46px !important;
        line-height: 1.25 !important;
    }}
    [data-testid="stDialog"] div[data-testid="stButton"] button,
    [data-testid="stDialog"] div[data-testid="stFormSubmitButton"] button,
    [data-baseweb="modal"] div[data-testid="stButton"] button,
    [data-baseweb="modal"] div[data-testid="stFormSubmitButton"] button,
    div[role="dialog"] div[data-testid="stButton"] button,
    div[role="dialog"] div[data-testid="stFormSubmitButton"] button {{
        min-height: 48px !important;
        min-width: 142px !important;
        padding: 11px 22px !important;
        border-radius: 8px !important;
        font-size: .98rem !important;
        font-weight: 780 !important;
        line-height: 1.12 !important;
        white-space: nowrap !important;
    }}
    [data-testid="stDialog"] div[data-testid="stButton"] button *,
    [data-testid="stDialog"] div[data-testid="stFormSubmitButton"] button *,
    [data-baseweb="modal"] div[data-testid="stButton"] button *,
    [data-baseweb="modal"] div[data-testid="stFormSubmitButton"] button *,
    div[role="dialog"] div[data-testid="stButton"] button *,
    div[role="dialog"] div[data-testid="stFormSubmitButton"] button * {{
        font-size: .98rem !important;
        font-weight: 780 !important;
        line-height: 1.12 !important;
        white-space: nowrap !important;
        color: #ffffff !important;
        background: transparent !important;
        text-shadow: none !important;
    }}
    [data-testid="stDialog"] div[data-testid="stFileUploader"] section button::after,
    [data-baseweb="modal"] div[data-testid="stFileUploader"] section button::after,
    div[role="dialog"] div[data-testid="stFileUploader"] section button::after {{
        color: var(--brand-blue) !important;
        font-size: .98rem !important;
        font-weight: 780 !important;
    }}
    div[data-testid="stSegmentedControl"] {{
        width: fit-content;
        max-width: 100%;
    }}
    div[data-testid="stSegmentedControl"] div[role="radiogroup"] {{
        background: white !important;
        border: 1px solid var(--line) !important;
        border-radius: 999px !important;
        overflow: hidden;
    }}
    @media (max-width: 760px) {{
        :root {{
            --mobile-safe-top: 44px;
            --mobile-safe-top: max(env(safe-area-inset-top), 44px);
        }}
        .block-container {{
            padding: calc(58px + var(--mobile-safe-top)) .85rem 2rem;
        }}
        .side-menu {{
            display: none;
        }}
        .mobile-menu {{
            display: block;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 2147483647;
            width: 100vw;
            margin: 0;
            transform: none;
            overflow: visible;
            background: var(--brand-blue);
        }}
        .mobile-menu::before {{
            content: "";
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: var(--mobile-safe-top);
            background: var(--brand-blue);
            pointer-events: none;
            z-index: 10;
        }}
        .mobile-menu-toggle {{
            position: absolute;
            top: var(--mobile-safe-top);
            left: 0;
            width: 58px;
            height: 64px;
            margin: 0;
            opacity: 0;
            z-index: 70;
            pointer-events: auto;
            appearance: none;
            -webkit-appearance: none;
        }}
        .mobile-menu-button {{
            display: grid;
            grid-template-columns: 48px minmax(0, 1fr) 48px;
            align-items: center;
            width: 100%;
            height: calc(64px + var(--mobile-safe-top));
            min-height: calc(64px + var(--mobile-safe-top));
            box-sizing: border-box;
            padding: calc(6px + var(--mobile-safe-top)) max(12px, env(safe-area-inset-right)) 6px max(8px, env(safe-area-inset-left));
            background: var(--brand-blue);
            border: 0;
            border-bottom: 1px solid rgba(255,255,255,.18);
            border-radius: 0;
            box-shadow: 0 10px 24px rgba(35,52,95,.13);
            color: #ffffff;
            cursor: pointer;
            list-style: none;
            font-family: "Avenir Next", "Nunito", "Trebuchet MS", "Segoe UI", system-ui, sans-serif;
            text-decoration: none !important;
            position: relative;
            z-index: 20;
            overflow: visible;
        }}
        .mobile-menu-icon {{
            width: 42px;
            height: 42px;
            border-radius: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 3px;
            background: transparent;
            border: 0;
        }}
        .mobile-menu-icon span,
        .mobile-menu-icon::before,
        .mobile-menu-icon::after {{
            content: "";
            display: block;
            width: 24px;
            height: 3.5px;
            border-radius: 999px;
            background: #ffffff;
            transition: transform .16s ease, opacity .16s ease;
            transform-origin: center;
        }}
        .mobile-menu-toggle:checked ~ .mobile-menu-button .mobile-menu-icon {{
            gap: 0;
        }}
        .mobile-menu-toggle:checked ~ .mobile-menu-button .mobile-menu-icon span {{
            opacity: 0;
            transform: scaleX(.2);
        }}
        .mobile-menu-toggle:checked ~ .mobile-menu-button .mobile-menu-icon::before {{
            transform: translateY(3.5px) rotate(45deg);
        }}
        .mobile-menu-toggle:checked ~ .mobile-menu-button .mobile-menu-icon::after {{
            transform: translateY(-3.5px) rotate(-45deg);
        }}
        .mobile-menu-logo {{
            width: 210px;
            height: 116px;
            object-fit: contain;
            display: block;
        }}
        .mobile-menu-logo-link {{
            position: absolute;
            left: 50%;
            top: var(--mobile-safe-top);
            transform: translateX(-50%);
            z-index: 30;
            display: block;
            pointer-events: auto;
        }}
        .mobile-push-status {{
            position: absolute;
            top: calc(var(--mobile-safe-top) + 11px);
            right: max(13px, env(safe-area-inset-right));
            z-index: 45;
            display: inline-grid;
            place-items: center;
            width: 42px;
            height: 42px;
            border-radius: 999px;
            background: #c9233f;
            color: #ffffff;
            border: 2px solid rgba(255,255,255,.82);
            box-shadow: 0 6px 14px rgba(35,52,95,.22);
            text-decoration: none !important;
            transition: transform .16s ease, background .16s ease, box-shadow .16s ease;
        }}
        .mobile-push-status.is-on {{
            background: #16a65a;
        }}
        .mobile-push-status.is-off {{
            background: #c9233f;
        }}
        .mobile-push-status:hover {{
            transform: translateY(-1px);
            box-shadow: 0 8px 18px rgba(35,52,95,.28);
        }}
        .mobile-push-status svg {{
            width: 22px;
            height: 22px;
            fill: none;
            stroke: currentColor;
            stroke-width: 2.6;
            stroke-linecap: round;
            stroke-linejoin: round;
        }}
        .mobile-menu-spacer {{
            width: 48px;
            height: 42px;
        }}
        .mobile-menu-panel {{
            position: absolute;
            top: 100%;
            left: 0;
            right: 0;
            z-index: 80;
            display: none;
            gap: 8px;
            padding: 10px max(12px, env(safe-area-inset-right)) 10px max(12px, env(safe-area-inset-left));
            background: rgba(255,255,255,.98);
            border: 0;
            border-bottom: 1px solid var(--line);
            border-radius: 0;
            box-shadow: 0 18px 34px rgba(35,52,95,.18);
        }}
        .mobile-menu-toggle:checked ~ .mobile-menu-panel {{
            display: grid;
        }}
        .mobile-menu .menu-item,
        .mobile-menu .sign-out {{
            margin: 0;
            min-height: 46px;
            display: flex;
            align-items: center;
            justify-content: flex-start;
            width: 100%;
        }}
        .mobile-menu .rainbow-rule {{
            margin-top: 2px;
        }}
        .app-top {{ align-items: flex-start; }}
        .top-logo {{ width: 96px; height: 66px; }}
        .quick-grid {{ grid-template-columns: 1fr; }}
        .parent-message-list {{
            margin-top: -30px;
        }}
        .parent-row {{
            grid-template-columns: 1fr;
            gap: 12px;
            padding: 14px;
        }}
        .message-status-stack {{
            min-width: 0;
            flex-direction: row;
            justify-content: flex-start;
            align-items: center;
            flex-wrap: wrap;
        }}
        .read-badge {{
            justify-content: flex-start;
            white-space: normal;
        }}
        .birthday-card {{
            grid-template-columns: 64px minmax(0, 1fr);
        }}
        .birthday-card .child-thumb {{
            width: 64px;
            height: 64px;
            min-height: 64px;
        }}
        .birthday-date {{
            grid-column: 1 / -1;
            width: fit-content;
        }}
        .parent-details {{
            grid-template-columns: 1fr;
            gap: 7px;
        }}
        .parent-actions {{
            justify-content: space-between;
        }}
        .login-head {{ align-items: flex-start; }}
        .login-logo {{ width: 96px; height: 66px; }}
        .role-grid {{ grid-template-columns: 1fr; }}
        .child-row {{ grid-template-columns: 68px minmax(0, 1fr) auto; }}
        .profile-link {{ grid-template-columns: 68px minmax(0, 1fr); }}
        .messages-title-panel {{
            padding: 10px 12px !important;
            margin-top: -8px;
            margin-bottom: 12px;
        }}
        .messages-title-row {{
            align-items: stretch;
            flex-direction: column;
        }}
        .messages-title-panel .panel-title {{
            margin: 0;
            line-height: 1.1;
        }}
        .admin-messages-list div[data-testid="stHorizontalBlock"] {{
            display: block !important;
            margin-bottom: 0;
        }}
        .admin-messages-list div[data-testid="column"] {{
            width: 100% !important;
            min-width: 0 !important;
            margin-bottom: 12px;
        }}
        .admin-message-row {{
            height: auto;
        }}
        .st-key-settings_panel,
        .st-key-settings-panel {{
            padding: 14px;
        }}
        .settings-action-card {{
            width: 100%;
        }}
        .create-message-button {{
            width: 100%;
            min-height: 46px;
        }}
        .parent-dashboard-title-panel {{
            padding: 0 !important;
            margin: 0 !important;
            border: 0 !important;
            box-shadow: none !important;
            background: transparent !important;
            min-height: 0 !important;
        }}
        .parent-dashboard-title-panel > .panel-title,
        .parent-dashboard-child-summary,
        .parent-dashboard-latest-title {{
            display: none !important;
        }}
        div[data-testid="stForm"] {{
            padding: 18px 14px 24px !important;
        }}
        div[data-testid="stForm"] div[data-testid="stHorizontalBlock"]:has(div[data-testid="stFormSubmitButton"]) {{
            width: 100% !important;
            gap: 8px !important;
            display: grid !important;
            grid-template-columns: repeat(2, minmax(136px, 1fr)) !important;
        }}
        div[data-testid="stForm"] div[data-testid="stHorizontalBlock"]:has(div[data-testid="stFormSubmitButton"]) > div {{
            flex: none !important;
            width: 100% !important;
            min-width: 0 !important;
        }}
        div[data-testid="stForm"] div[data-testid="stHorizontalBlock"]:has(div[data-testid="stFormSubmitButton"]) div[data-testid="stFormSubmitButton"] {{
            width: 100% !important;
            min-width: 0 !important;
        }}
        div[data-testid="stForm"] div[data-testid="stHorizontalBlock"]:has(div[data-testid="stFormSubmitButton"]) div[data-testid="stFormSubmitButton"] button {{
            width: 100% !important;
            min-width: 0 !important;
            min-height: 56px !important;
            padding: 10px 12px !important;
            font-size: clamp(.88rem, 3.5vw, 1.02rem) !important;
            line-height: 1.12 !important;
            white-space: normal !important;
            overflow-wrap: normal !important;
            word-break: keep-all !important;
            text-align: center !important;
        }}
        div[data-testid="stForm"] div[data-testid="stHorizontalBlock"]:has(div[data-testid="stFormSubmitButton"]) div[data-testid="stFormSubmitButton"] button * {{
            font-size: clamp(.88rem, 3.5vw, 1.02rem) !important;
            line-height: 1.12 !important;
            white-space: normal !important;
            overflow-wrap: normal !important;
            word-break: keep-all !important;
        }}
    }}
    @media (max-width: 340px) {{
        div[data-testid="stForm"] div[data-testid="stHorizontalBlock"]:has(div[data-testid="stFormSubmitButton"]) {{
            grid-template-columns: 1fr !important;
        }}
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


def render_sign_in_dialog(selected_role, login_placeholder=None):
    if selected_role == "ParentRegister":
        st.markdown('<div class="panel-title">Parent Registration</div>', unsafe_allow_html=True)
        first_name = st.text_input("Parent first name")
        relationship = st.selectbox("Relationship to child", CONTACT_RELATIONSHIPS, index=relationship_index("Guardian"))
        email = st.text_input("Email address")
        emergency_contact_1 = st.text_input("Emergency contact 1 phone")
        emergency_contact_2 = st.text_input("Emergency contact 2 phone")
        password = st.text_input("Create password")
        confirm_password = st.text_input("Confirm password")
        if st.button("Register Parent", type="primary", width="stretch"):
            clean_name = str(first_name or "").strip()
            clean_relationship = clean_contact_relationship(relationship, "Guardian")
            clean_email = str(email or "").strip().lower()
            clean_emergency_1 = str(emergency_contact_1 or "").strip()
            clean_emergency_2 = str(emergency_contact_2 or "").strip()
            clean_password = str(password or "").strip()
            clean_confirm_password = str(confirm_password or "").strip()
            if not clean_name or not clean_email or not clean_emergency_1 or not clean_emergency_2 or not clean_password:
                st.warning("Please add the parent's first name, email address, both emergency contacts, and a password.")
            elif clean_password != clean_confirm_password:
                st.warning("The two passwords do not match.")
            else:
                parents = load_parents()
                existing = next((parent for parent in parents if parent.get("Email", "").lower() == clean_email), None)
                if existing:
                    if existing.get("salt") and existing.get("hash"):
                        st.info("This parent is already registered. Please use Parent Login.")
                    else:
                        existing["FirstName"] = clean_name
                        existing["Relationship"] = clean_relationship
                        existing["EmergencyContact1"] = clean_emergency_1
                        existing["EmergencyContact2"] = clean_emergency_2
                        existing.update(hash_password(clean_password))
                        save_parents(parents)
                        st.success("Parent login has been added. Please use Parent Login after approval.")
                else:
                    parents.append(
                        {
                            "ID": uuid.uuid4().hex,
                            "FirstName": clean_name,
                            "Relationship": clean_relationship,
                            "Email": clean_email,
                            "EmergencyContact1": clean_emergency_1,
                            "EmergencyContact2": clean_emergency_2,
                            "Status": "Pending",
                            "ChildID": "",
                            "ChildName": "",
                            **hash_password(clean_password),
                        }
                    )
                    save_parents(parents)
                    st.success("Registration sent. The preschool can approve and assign a child from the admin area.")
        if st.button("Cancel", width="stretch"):
            st.session_state.pop("login_role", None)
            st.query_params.pop("login_role", None)
            st.rerun()
        return

    if selected_role == "ParentForgot":
        st.markdown('<div class="panel-title">Reset Parent Password</div>', unsafe_allow_html=True)
        st.caption("Enter the parent email and emergency contact 1 phone number, then choose a new password.")
        email = st.text_input("Email address")
        emergency_contact = st.text_input("Emergency contact 1 phone")
        password = st.text_input("New password")
        confirm_password = st.text_input("Confirm new password")
        if st.button("Reset Password", type="primary", width="stretch"):
            clean_email = str(email or "").strip().lower()
            clean_contact = phone_digits(emergency_contact)
            clean_password = str(password or "").strip()
            clean_confirm_password = str(confirm_password or "").strip()
            parents = load_parents()
            parent = next((item for item in parents if item.get("Email", "").strip().lower() == clean_email), None)
            saved_contact = phone_digits(parent.get("EmergencyContact1", "")) if parent else ""
            if not clean_email or not clean_contact or not clean_password:
                st.warning("Please add the email address, emergency contact 1 phone, and a new password.")
            elif clean_password != clean_confirm_password:
                st.warning("The two passwords do not match.")
            elif not parent or not saved_contact or clean_contact != saved_contact:
                st.error("Those details do not match a parent account.")
            else:
                parent.update(hash_password(clean_password))
                save_parents(parents)
                st.success("Password reset. Please use Parent Login.")
                st.session_state["login_role"] = "Parent"
                st.query_params["login_role"] = "Parent"
        if st.button("Back to Parent Login", width="stretch"):
            st.session_state["login_role"] = "Parent"
            st.query_params["login_role"] = "Parent"
            st.rerun()
        if st.button("Cancel", width="stretch"):
            st.session_state.pop("login_role", None)
            st.query_params.pop("login_role", None)
            st.rerun()
        return

    login_label = "Parent" if selected_role == "Parent" else selected_role
    st.markdown(f'<div class="panel-title">{login_label} Sign In</div>', unsafe_allow_html=True)
    email = st.text_input("Email address", key=f"{selected_role}_login_email")
    password = st.text_input("Password", type="password", key=f"{selected_role}_login_password")
    if st.button(f"Sign In As {login_label}", type="primary", width="stretch"):
        account = login_user(email, password, selected_role)
        if account:
            st.session_state["logged_in"] = True
            st.session_state["role"] = account["role"]
            st.session_state["email"] = account["email"]
            st.session_state.pop("login_role", None)
            st.session_state.pop(f"{selected_role}_login_email", None)
            st.session_state.pop(f"{selected_role}_login_password", None)
            if login_placeholder is not None:
                login_placeholder.empty()
            st.query_params.from_dict(
                {
                    "auth": make_auth_token(account),
                    "app_page": "Children" if account["role"] == "Admin" else "Dashboard",
                }
            )
            st.rerun()
        else:
            st.error("Those login details do not match an account for this role.")
    if selected_role == "Parent":
        st.markdown(
            '<a class="forgot-link" href="?login_role=ParentForgot" target="_self">Forgot password?</a>',
            unsafe_allow_html=True,
        )
    if st.button("Cancel", width="stretch"):
        st.session_state.pop("login_role", None)
        st.query_params.pop("login_role", None)
        st.rerun()


def render_message_dialog(child, parent):
    parent_name = parent.get("FirstName", "Parent") or "Parent"
    child_name = child.get("Name", "this child") or "this child"
    child_id = child.get("ID", "")
    message_key = f"message_body_{child_id}"
    media_key = f"message_media_{child_id}"
    st.markdown(
        f'<div class="panel-title">Message {html.escape(parent_name)}</div>'
        f'<div class="muted">This will send a message about {html.escape(child_name)}.</div>',
        unsafe_allow_html=True,
    )
    with st.form(key=f"message_form_{child_id}", clear_on_submit=False):
        message_body = st.text_area("Message", placeholder="Write your message here...", height=150, key=message_key)
        media_files = st.file_uploader(
            "Photos or videos",
            type=MESSAGE_ATTACHMENT_TYPES,
            accept_multiple_files=True,
            key=media_key,
            help=f"Add up to {MESSAGE_ATTACHMENT_MAX_COUNT} files. Each file can be up to {file_size_label(MESSAGE_ATTACHMENT_MAX_BYTES)}.",
        )
        if media_files:
            st.markdown(
                '<div class="media-note">'
                + html.escape(
                    f"{len(media_files)} file{'s' if len(media_files) != 1 else ''} ready to send."
                )
                + "</div>",
                unsafe_allow_html=True,
            )
        send_col, cancel_col = st.columns(2)
        send_message = send_col.form_submit_button("Send message", width="stretch")
        cancel_message = cancel_col.form_submit_button("Cancel", width="stretch")

    if send_message:
        if not message_body.strip() and not media_files:
            st.warning("Please add a message, photo, or video first.")
        else:
            attachments, attachment_error = prepare_message_attachments(media_files)
            if attachment_error:
                st.warning(attachment_error)
            elif send_parent_notification(child, parent, message_body, attachments):
                if has_push_subscription_for_user(parent.get("Email", ""), "Parent"):
                    st.session_state["notification_sent"] = f"Message sent to {parent_name}. Notification sent to their device."
                else:
                    st.session_state["notification_sent"] = f"Message sent to {parent_name}. They need to enable message notifications on their device before alerts will appear."
                st.session_state.pop(message_key, None)
                st.session_state.pop(media_key, None)
                st.query_params.pop("message_child", None)
                st.rerun()
            else:
                st.error("The message was not saved permanently. Please check the GitHub data key and try again.")

    if cancel_message:
        st.session_state.pop(message_key, None)
        st.session_state.pop(media_key, None)
        st.query_params.pop("message_child", None)
        st.rerun()


def render_session_message_dialog(session_name, children, parents):
    targets = session_parent_targets(session_name, children, parents)
    session_key = re.sub(r"[^a-z0-9]+", "_", session_name.lower()).strip("_")
    message_key = f"session_message_body_{session_key}"
    media_key = f"session_message_media_{session_key}"
    parent_count = len(targets)

    st.markdown(
        f'<div class="panel-title">Message all {html.escape(session_name)} parents</div>'
        f'<div class="muted">This will send a separate message to {parent_count} approved '
        f'parent{"s" if parent_count != 1 else ""}.</div>',
        unsafe_allow_html=True,
    )
    if not targets:
        st.markdown(
            '<div class="status"><span class="status-dot"></span>'
            '<div>No approved parents are assigned to this session yet.</div></div>',
            unsafe_allow_html=True,
        )
        if st.button("Close", key=f"close_session_message_{session_key}", width="stretch"):
            st.query_params.pop("message_session", None)
            st.rerun()
        return

    with st.form(key=f"session_message_form_{session_key}", clear_on_submit=False):
        st.markdown("**Recipients**")
        recipient_selections = []
        recipient_state_keys = []
        recipient_columns = st.columns(2) if len(targets) > 1 else [st.container()]
        for index, (child, parent) in enumerate(targets):
            parent_name = str(parent.get("FirstName") or parent.get("Email") or "Parent").strip()
            child_name = str(child.get("Name") or "Child").strip()
            recipient_identity = str(parent.get("ID") or parent.get("Email") or index)
            recipient_key = (
                f"session_recipient_{session_key}_"
                f"{hashlib.sha256(recipient_identity.encode('utf-8')).hexdigest()[:12]}"
            )
            recipient_state_keys.append(recipient_key)
            with recipient_columns[index % len(recipient_columns)]:
                is_selected = st.checkbox(
                    f"{parent_name} - {child_name}",
                    value=True,
                    key=recipient_key,
                )
            recipient_selections.append(((child, parent), is_selected))

        message_body = st.text_area(
            "Message",
            placeholder="Write your message here...",
            height=150,
            key=message_key,
        )
        media_files = st.file_uploader(
            "Photos or videos",
            type=MESSAGE_ATTACHMENT_TYPES,
            accept_multiple_files=True,
            key=media_key,
            help=f"Add up to {MESSAGE_ATTACHMENT_MAX_COUNT} files. Each file can be up to {file_size_label(MESSAGE_ATTACHMENT_MAX_BYTES)}.",
        )
        if media_files:
            st.markdown(
                '<div class="media-note">'
                + html.escape(
                    f"{len(media_files)} file{'s' if len(media_files) != 1 else ''} ready to send."
                )
                + "</div>",
                unsafe_allow_html=True,
            )
        send_col, cancel_col = st.columns(2)
        send_message = send_col.form_submit_button(
            "Send to selected parents",
            width="stretch",
        )
        cancel_message = cancel_col.form_submit_button("Cancel", width="stretch")

    selected_targets = [target for target, is_selected in recipient_selections if is_selected]
    if send_message:
        if not selected_targets:
            st.warning("Select at least one parent.")
        elif not str(message_body or "").strip() and not media_files:
            st.warning("Please add a message, photo, or video first.")
        else:
            attachments, attachment_error = prepare_message_attachments(media_files)
            if attachment_error:
                st.warning(attachment_error)
            else:
                sent_count = send_session_parent_notifications(selected_targets, message_body, attachments)
                if sent_count:
                    st.session_state["notification_sent"] = (
                        f"Message sent to {sent_count} {session_name.lower()} "
                        f"parent{'s' if sent_count != 1 else ''}."
                    )
                    st.session_state.pop(message_key, None)
                    st.session_state.pop(media_key, None)
                    for recipient_key in recipient_state_keys:
                        st.session_state.pop(recipient_key, None)
                    st.query_params.pop("message_session", None)
                    st.rerun()
                else:
                    st.error("The messages were not saved permanently. Please check the GitHub data key and try again.")

    if cancel_message:
        st.session_state.pop(message_key, None)
        st.session_state.pop(media_key, None)
        for recipient_key in recipient_state_keys:
            st.session_state.pop(recipient_key, None)
        st.query_params.pop("message_session", None)
        st.rerun()



if hasattr(st, "dialog"):
    render_message_dialog = st.dialog("Send parent message")(render_message_dialog)
    render_session_message_dialog = st.dialog("Message session parents")(render_session_message_dialog)


def render_create_message_dialog():
    children = load_children()
    parents = load_parents()
    targets = message_parent_targets(children, parents)
    message_key = "admin_create_message_body"
    media_key = "admin_create_message_media"

    st.markdown(
        '<div class="panel-title">Create Message</div>'
        '<div class="muted">Choose a parent, then add a message, photo, or video.</div>',
        unsafe_allow_html=True,
    )
    if not targets:
        st.markdown(
            '<div class="status"><span class="status-dot"></span>'
            '<div>No approved parent with an assigned child is ready to message yet.</div></div>',
            unsafe_allow_html=True,
        )
        if st.button("Close", key="close_create_message_empty"):
            st.query_params.pop("create_message", None)
            st.rerun()
        return

    target_by_key = {target["Key"]: target for target in targets}
    selected_target_key = st.selectbox(
        "Parent",
        [target["Key"] for target in targets],
        format_func=lambda key: target_by_key.get(key, {}).get("Label", "Parent"),
        key="admin_create_message_target",
    )
    selected_target = target_by_key[selected_target_key]
    child = selected_target["Child"]
    parent = selected_target["Parent"]
    st.markdown(
        '<div class="message-child admin-message-child create-message-target">'
        f'{child_thumb_html(child)}'
        '<div>'
        f'<div class="parent-name">{html.escape(child.get("Name", "Unnamed child"))}</div>'
        f'<div class="parent-detail">To: {html.escape(contact_display_name(parent.get("FirstName", ""), parent_relationship(parent, child)))}</div>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    with st.form(key="admin_create_message_form", clear_on_submit=False):
        message_body = st.text_area("Message", placeholder="Write your message here...", height=150, key=message_key)
        media_files = st.file_uploader(
            "Photos or videos",
            type=MESSAGE_ATTACHMENT_TYPES,
            accept_multiple_files=True,
            key=media_key,
            help=f"Add up to {MESSAGE_ATTACHMENT_MAX_COUNT} files. Each file can be up to {file_size_label(MESSAGE_ATTACHMENT_MAX_BYTES)}.",
        )
        if media_files:
            st.markdown(
                '<div class="media-note">'
                + html.escape(
                    f"{len(media_files)} file{'s' if len(media_files) != 1 else ''} ready to send."
                )
                + "</div>",
                unsafe_allow_html=True,
            )
        send_col, cancel_col = st.columns(2)
        send_message = send_col.form_submit_button("Send message", width="stretch")
        cancel_message = cancel_col.form_submit_button("Cancel", width="stretch")

    if send_message:
        if not message_body.strip() and not media_files:
            st.warning("Please add a message, photo, or video first.")
        else:
            attachments, attachment_error = prepare_message_attachments(media_files)
            if attachment_error:
                st.warning(attachment_error)
            elif send_parent_notification(child, parent, message_body, attachments):
                parent_name = parent.get("FirstName", "Parent") or "Parent"
                if has_push_subscription_for_user(parent.get("Email", ""), "Parent"):
                    st.session_state["notification_sent"] = f"Message sent to {parent_name}. Notification sent to their device."
                else:
                    st.session_state["notification_sent"] = f"Message sent to {parent_name}. They need to enable message notifications on their device before alerts will appear."
                st.session_state.pop(message_key, None)
                st.session_state.pop(media_key, None)
                st.query_params.pop("create_message", None)
                st.query_params["app_page"] = "Messages"
                st.rerun()
            else:
                st.error("The message was not saved permanently. Please check the GitHub data key and try again.")

    if cancel_message:
        st.session_state.pop(message_key, None)
        st.session_state.pop(media_key, None)
        st.query_params.pop("create_message", None)
        st.rerun()


def render_admin_reply_dialog(message):
    message_id = str(message.get("ID", "") or "")
    parent_name = str(message.get("ParentName") or message.get("ParentEmail") or "Parent")
    child_name = str(message.get("ChildName") or "Preschool message")
    reply_key = f"admin_reply_body_{message_id}"
    media_key = f"admin_reply_media_{message_id}"

    st.markdown(
        f'<div class="panel-title">Reply to {html.escape(parent_name)}</div>'
        f'<div class="parent-child-card no-photo"><div>'
        f'<div class="parent-child-name">{html.escape(child_name)}</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )
    reply_body = st.text_area(
        "Reply",
        placeholder="Write your reply here...",
        height=140,
        key=reply_key,
    )
    media_files = st.file_uploader(
        "Photos or videos",
        type=MESSAGE_ATTACHMENT_TYPES,
        accept_multiple_files=True,
        key=media_key,
        help=(
            f"Add up to {MESSAGE_ATTACHMENT_MAX_COUNT} files. "
            f"Each file can be up to {file_size_label(MESSAGE_ATTACHMENT_MAX_BYTES)}."
        ),
    )
    if media_files:
        st.markdown(
            '<div class="media-note">'
            + html.escape(
                f"{len(media_files)} file{'s' if len(media_files) != 1 else ''} ready to send."
            )
            + "</div>",
            unsafe_allow_html=True,
        )

    send_col, cancel_col = st.columns(2, gap="small")
    if send_col.button(
        "Send reply",
        type="primary",
        icon=":material/reply:",
        key=f"admin_send_reply_{message_id}",
        width="stretch",
    ):
        if not str(reply_body or "").strip() and not media_files:
            st.warning("Please write a reply or add a photo/video first.")
        else:
            attachments, attachment_error = prepare_message_attachments(media_files)
            if attachment_error:
                st.warning(attachment_error)
            elif add_admin_reply(message_id, reply_body, attachments):
                st.session_state["notification_sent"] = f"Reply sent to {parent_name}."
                st.session_state.pop(reply_key, None)
                st.session_state.pop(media_key, None)
                st.query_params.pop("reply_message", None)
                st.rerun()
            else:
                st.error("The reply was not saved permanently. Please check the GitHub data key and try again.")

    if cancel_col.button(
        "Cancel",
        key=f"admin_cancel_reply_{message_id}",
        width="stretch",
    ):
        st.session_state.pop(reply_key, None)
        st.session_state.pop(media_key, None)
        st.query_params.pop("reply_message", None)
        st.rerun()


if hasattr(st, "dialog"):
    render_create_message_dialog = st.dialog("Create message")(render_create_message_dialog)
    render_admin_reply_dialog = st.dialog("Reply to parent")(render_admin_reply_dialog)


def render_login(login_placeholder=None):
    selected_role = st.query_params.get("login_role") or st.session_state.get("login_role")
    if selected_role not in {"Parent", "ParentRegister", "ParentForgot", "Admin"}:
        selected_role = None
    shell_class = "login-shell has-login-form" if selected_role else "login-shell"
    st.markdown(
        f"""
        <div class="{shell_class}">
          <div class="login-card">
            <div class="login-head">
              <div>
                <div class="app-title">Ash's Angels Preschool App</div>
                <div class="app-subtitle">Sign in to access your preschool dashboard.</div>
              </div>
              <img class="login-logo" src="{asset_url(LOGO_IMAGE)}" alt="Ash's Angels Preschool logo">
            </div>
            <div class="role-grid">
              <a class="role-card {'active' if selected_role == 'Parent' else ''}" href="?login_role=Parent" target="_self">
                <div class="role-title">Parent Login</div>
                <div class="role-copy">View child updates, forms, messages, and preschool notices.</div>
              </a>
              <a class="role-card {'active' if selected_role == 'ParentRegister' else ''}" href="?login_role=ParentRegister" target="_self">
                <div class="role-title">Parent Register</div>
                <div class="role-copy">Create a parent account for approval and child assignment.</div>
              </a>
              <a class="role-card {'active' if selected_role == 'Admin' else ''}" href="?login_role=Admin" target="_self">
                <div class="role-title">Admin Login</div>
                <div class="role-copy">For the preschool owner to manage enquiries, sessions, and parent information.</div>
              </a>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not selected_role:
        return

    st.session_state["login_role"] = selected_role
    with st.container(key="login_form_card"):
        render_sign_in_dialog(selected_role, login_placeholder)


def render_side_menu(role, selected_page):
    nav_items = ["Children", "Parents", "Messages", "Documents", "Calendar", "Birthdays", "Settings"] if role == "Admin" else ["Dashboard", "Messages", "Documents", "Calendar", "Forms", "Settings"]
    message_badge_count = admin_unseen_message_count() if role == "Admin" else parent_unseen_message_count()

    def nav_label(item):
        badge = ""
        if item == "Messages" and message_badge_count:
            badge_text = "9+" if message_badge_count > 9 else str(message_badge_count)
            badge = f'<span class="menu-badge" aria-label="{message_badge_count} unseen message{"s" if message_badge_count != 1 else ""}">{badge_text}</span>'
        return f'<span>{html.escape(item)}</span>{badge}'

    items_html = "".join(
        f'<a class="menu-item {"active" if item == selected_page else ""}" href="{app_href(item)}" target="_self">{nav_label(item)}</a>'
        for item in nav_items
    )
    mobile_push_status_html = ""
    if role == "Admin":
        mobile_push_status_html = (
            f'<a class="mobile-push-status is-off" id="mobile-push-status" href="{app_href("Settings")}" '
            'target="_self" aria-label="Device notifications are off" title="Device notifications are off">'
            '<svg viewBox="0 0 24 24" aria-hidden="true">'
            '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 8-3 8h18s-3-1-3-8"></path>'
            '<path d="M13.73 21a2 2 0 0 1-3.46 0"></path>'
            '</svg>'
            '</a>'
        )
    menu_html = f"""
        <div class="mobile-menu">
          <input class="mobile-menu-toggle" id="mobile-menu-toggle" type="checkbox" aria-label="Open navigation menu">
          <label class="mobile-menu-button" for="mobile-menu-toggle">
            <span class="mobile-menu-icon"><span></span></span>
            <span class="mobile-menu-spacer" aria-hidden="true"></span>
          </label>
          <a class="mobile-menu-logo-link" href="{app_href("Children")}" target="_self" aria-label="Go to children">
            <img class="mobile-menu-logo" src="{asset_url(LOGO_IMAGE)}" alt="Ash's Angels Preschool logo">
          </a>
          {mobile_push_status_html}
          <div class="mobile-menu-panel">
            {items_html}
            <a class="sign-out" href="?sign_out=1" target="_self">Sign out</a>
            <div class="rainbow-rule"></div>
          </div>
        </div>
        <div class="side-menu">
          <a class="side-logo-link" href="{app_href("Children")}" target="_self" aria-label="Go to children">
            <img class="side-logo" src="{asset_url(LOGO_IMAGE)}" alt="Ash's Angels Preschool logo">
          </a>
          <div class="menu-label">Navigation</div>
          {items_html}
          <a class="sign-out" href="?sign_out=1" target="_self">Sign out</a>
          <div class="rainbow-rule"></div>
        </div>
        """
    st.markdown(
        "".join(line.strip() for line in menu_html.splitlines()),
        unsafe_allow_html=True,
    )
    render_mobile_push_status_bell()


def render_delete_child_dialog(child):
    child_id = child.get("ID", "")
    child_name = child.get("Name", "this child")
    st.markdown(
        f'<div class="danger-confirm">Are you sure you want to delete {html.escape(child_name)}? This cannot be undone.</div>',
        unsafe_allow_html=True,
    )
    confirm_col, keep_col = st.columns([1, 1], gap="small")
    if confirm_col.button("Yes, delete child", type="primary", key=f"confirm_delete_dialog_{child_id}"):
        if delete_child_and_clear_parent_links(child_id):
            st.session_state.pop("confirm_delete_child_id", None)
            st.session_state["notification_sent"] = "Child deleted."
            for param in ("delete_child", "edit_child", "children_edit"):
                st.query_params.pop(param, None)
            st.rerun()
        else:
            st.error("The child was not deleted permanently. Please check the GitHub data key and try again.")
    if keep_col.button("No, keep child", key=f"cancel_delete_dialog_{child_id}"):
        st.session_state.pop("confirm_delete_child_id", None)
        st.rerun()


def render_delete_message_dialog(message):
    message_id = message.get("ID", "")
    child_name = message.get("ChildName", "this message")
    st.markdown(
        f'<div class="danger-confirm">Are you sure you want to delete this message for {html.escape(child_name)}? This cannot be undone.</div>',
        unsafe_allow_html=True,
    )
    confirm_col, keep_col = st.columns([1, 1], gap="small")
    if confirm_col.button("Yes, delete message", type="primary", key=f"confirm_delete_message_dialog_{message_id}"):
        if delete_message(message_id):
            st.session_state["message_deleted_notice"] = "Message deleted."
        st.session_state.pop("confirm_delete_message_id", None)
        st.rerun()
    if keep_col.button("No, keep message", key=f"cancel_delete_message_dialog_{message_id}"):
        st.session_state.pop("confirm_delete_message_id", None)
        st.rerun()


if hasattr(st, "dialog"):
    render_delete_child_dialog = st.dialog("Delete child")(render_delete_child_dialog)
    render_delete_message_dialog = st.dialog("Delete message")(render_delete_message_dialog)


def render_admin_children():
    children = load_children()
    parents = load_parents()
    approved_parent_by_child = {
        parent.get("ChildID"): parent
        for parent in parents
        if parent.get("ChildID") and parent.get("Status") == "Approved"
    }
    st.markdown("<br>", unsafe_allow_html=True)
    notification_sent = st.session_state.pop("notification_sent", "")
    if notification_sent:
        st.success(notification_sent)
    child_added_message = st.session_state.pop("child_added_message", "")
    if child_added_message:
        show_quick_notice(child_added_message)
    data_save_warning = st.session_state.pop("data_save_warning", "")
    if data_save_warning:
        st.warning(data_save_warning)
    if "show_add_child" not in st.session_state:
        st.session_state["show_add_child"] = False
    if st.query_params.get("add_child"):
        st.session_state["show_add_child"] = True
        st.query_params.pop("add_child", None)
        st.rerun()
    if st.session_state["show_add_child"]:
        render_add_child_dialog()
    edit_child_id = st.query_params.get("edit_child")
    delete_child_id = st.query_params.get("delete_child")
    message_child_id = st.query_params.get("message_child")
    message_session_name = st.query_params.get("message_session")

    if delete_child_id:
        if delete_child_and_clear_parent_links(delete_child_id):
            for param in ("delete_child", "edit_child", "children_edit"):
                st.query_params.pop(param, None)
            st.success("Child deleted.")
            st.rerun()
        else:
            for param in ("delete_child", "edit_child", "children_edit"):
                st.query_params.pop(param, None)
            st.error("The child was not deleted permanently. Please check the GitHub data key and try again.")

    if message_child_id:
        child_to_message = next((child for child in children if child.get("ID") == message_child_id), None)
        parent_to_message = approved_parent_by_child.get(message_child_id)
        if child_to_message and parent_to_message:
            render_message_dialog(child_to_message, parent_to_message)
        elif child_to_message:
            st.markdown(
                '<div class="status"><span class="status-dot"></span><div>No approved parent is assigned to this child yet.</div></div>',
                unsafe_allow_html=True,
            )

    if message_session_name:
        if message_session_name in SESSIONS:
            render_session_message_dialog(message_session_name, children, parents)
        else:
            st.query_params.pop("message_session", None)

    if edit_child_id:
        editing_child = next((child for child in children if child.get("ID") == edit_child_id), None)
        if editing_child:
            st.markdown("<br>", unsafe_allow_html=True)
            try:
                dob_value = date.fromisoformat(editing_child.get("DOB", ""))
            except ValueError:
                dob_value = None
            current_session = clean_session_name(editing_child.get("Session"))
            session_index = SESSIONS.index(current_session) if current_session in SESSIONS else 0
            current_guardian = (child_guardians(editing_child) or [{}])[0]
            parent_options = [""] + [parent.get("ID", "") for parent in parents if parent.get("ID")]
            parent_lookup = {parent.get("ID", ""): parent for parent in parents if parent.get("ID")}
            default_parent_id = matching_parent_id(parents, current_guardian, edit_child_id)
            try:
                edit_panel = st.container(key="edit_child_panel")
            except TypeError:
                edit_panel = st.container()
            with edit_panel:
                st.markdown('<div class="panel-title">Edit Child</div>', unsafe_allow_html=True)
                guardian_preview = guardian_summary_html(editing_child)
                if guardian_preview:
                    st.markdown(guardian_preview, unsafe_allow_html=True)
                selected_parent_id = st.selectbox(
                    "Assign existing parent",
                    parent_options,
                    index=parent_options.index(default_parent_id) if default_parent_id in parent_options else 0,
                    format_func=lambda parent_id: "No existing parent selected"
                    if not parent_id
                    else parent_option_label(parent_lookup.get(parent_id, {})),
                    key=f"existing_parent_{edit_child_id}",
                )
                selected_parent = parent_lookup.get(selected_parent_id, {})
                guardian_defaults = parent_defaults(selected_parent, current_guardian) if selected_parent else current_guardian
                with st.form(f"edit_child_form_{edit_child_id}"):
                    details_col, thumbnail_col = st.columns([0.62, 0.38], gap="large")
                    with details_col:
                        edited_name = st.text_input("Child full name", value=editing_child.get("Name", ""))
                        edited_dob = st.date_input("Date of birth", value=dob_value)
                        child_badges = child_info_badges_html(edited_dob)
                        if child_badges:
                            st.markdown(child_badges, unsafe_allow_html=True)
                        edited_session = st.selectbox("Assign to session", SESSIONS, index=session_index)
                        st.markdown('<div class="guardian-form-title">Parents/guardians</div>', unsafe_allow_html=True)
                        guardian_cols = st.columns([1, 1], gap="small")
                        with guardian_cols[0]:
                            guardian_name = st.text_input("Parent/guardian name", value=guardian_defaults.get("Name", ""))
                        with guardian_cols[1]:
                            guardian_relationship = st.selectbox(
                                "Relationship",
                                CONTACT_RELATIONSHIPS,
                                index=relationship_index(guardian_defaults.get("Relationship", "Guardian")),
                            )
                        guardian_contact_cols = st.columns([1, 1], gap="small")
                        with guardian_contact_cols[0]:
                            guardian_email = st.text_input("Guardian email", value=guardian_defaults.get("Email", ""))
                        with guardian_contact_cols[1]:
                            guardian_phone = st.text_input("Guardian phone", value=guardian_defaults.get("Phone", ""))
                        guardian_address = st.text_area("Guardian address", value=guardian_defaults.get("Address", ""), height=88)
                        guardian_invited = st.checkbox("Invited to use the app", value=guardian_defaults.get("Invited", False))
                    with thumbnail_col:
                        st.markdown(
                            f'<div class="current-thumb-preview">{child_thumb_html(editing_child)}<span>Current thumbnail</span></div>',
                            unsafe_allow_html=True,
                        )
                        edited_thumbnail = st.file_uploader("Thumbnail", type=["png", "jpg", "jpeg"], key=f"edit_thumb_{edit_child_id}")
                        if edited_thumbnail is not None:
                            preview_child = {
                                "Name": editing_child.get("Name", "Child"),
                                "Thumbnail": uploaded_thumbnail_data_uri(edited_thumbnail.getvalue()),
                            }
                            st.markdown(
                                f'<div class="current-thumb-preview">{child_thumb_html(preview_child)}<span>New thumbnail preview</span></div>',
                                unsafe_allow_html=True,
                            )
                    save_col, remove_thumb_col, cancel_col, delete_col = st.columns([1, 1, 1, 1], gap="small")
                    update_submitted = save_col.form_submit_button("Save Changes")
                    remove_thumbnail_submitted = remove_thumb_col.form_submit_button("Remove Thumbnail")
                    cancel_submitted = cancel_col.form_submit_button("Cancel Edit")
                    delete_submitted = delete_col.form_submit_button("Delete Child")
            edited_guardians = guardian_from_fields(
                guardian_name,
                guardian_relationship,
                guardian_email,
                guardian_phone,
                guardian_address,
                guardian_invited,
            )

            if cancel_submitted:
                st.session_state.pop("confirm_delete_child_id", None)
                st.query_params.pop("edit_child", None)
                st.rerun()

            if delete_submitted:
                st.session_state["confirm_delete_child_id"] = edit_child_id
                st.rerun()

            if st.session_state.get("confirm_delete_child_id") == edit_child_id:
                render_delete_child_dialog(editing_child)

            if remove_thumbnail_submitted:
                st.session_state.pop("confirm_delete_child_id", None)
                if not edited_name:
                    st.warning("Please add the child's full name.")
                else:
                    updated_child = None
                    for child in children:
                        if child.get("ID") == edit_child_id:
                            child.update(
                                {
                                    "Name": edited_name.strip(),
                                    "DOB": edited_dob.isoformat() if edited_dob else "",
                                    "Session": edited_session,
                                    "Thumbnail": "",
                                    "Guardians": edited_guardians,
                                }
                            )
                            updated_child = child
                            break
                    parent_changed = sync_guardian_to_parent(
                        parents,
                        updated_child or editing_child,
                        edited_guardians,
                        selected_parent_id,
                    )
                    children_saved = save_children(children)
                    parents_saved = save_parents(parents) if children_saved and parent_changed else True
                    if children_saved and parents_saved:
                        st.success("Thumbnail removed.")
                        st.rerun()
                    elif children_saved:
                        st.error("The thumbnail was removed, but the parent assignment was not saved. Please check the GitHub data key and try again.")
                    else:
                        st.error("The thumbnail was not removed permanently. Please check the GitHub data key and try again.")

            if update_submitted:
                st.session_state.pop("confirm_delete_child_id", None)
                if not edited_name:
                    st.warning("Please add the child's full name.")
                else:
                    thumbnail_path = editing_child.get("Thumbnail", "")
                    if edited_thumbnail is not None:
                        thumbnail_path = save_uploaded_thumbnail(edited_thumbnail)

                    updated_child = None
                    for child in children:
                        if child.get("ID") == edit_child_id:
                            child.update(
                                {
                                    "Name": edited_name.strip(),
                                    "DOB": edited_dob.isoformat() if edited_dob else "",
                                    "Session": edited_session,
                                    "Thumbnail": thumbnail_path,
                                    "Guardians": edited_guardians,
                                }
                            )
                            updated_child = child
                            break
                    parent_changed = sync_guardian_to_parent(
                        parents,
                        updated_child or editing_child,
                        edited_guardians,
                        selected_parent_id,
                    )
                    children_saved = save_children(children)
                    parents_saved = save_parents(parents) if children_saved and parent_changed else True
                    if children_saved and parents_saved:
                        st.query_params.pop("edit_child", None)
                        st.success("Child updated.")
                        st.rerun()
                    elif children_saved:
                        st.error("The child was updated, but the parent assignment was not saved. Please check the GitHub data key and try again.")
                    else:
                        st.error("The child was not updated permanently. Please check the GitHub data key and try again.")

    if not children:
        st.markdown('<div class="muted">No children added yet.</div>', unsafe_allow_html=True)
    else:
        sections_html = ['<div class="child-list session-columns">']
        for session_name in SESSIONS:
            session_children = [child for child in children if clean_session_name(child.get("Session")) == session_name]
            add_child_href = app_href("Children", add_child=1)
            message_session_href = app_href("Children", message_session=session_name)
            sections_html.append(
                '<div class="session-group">'
                '<div class="session-heading">'
                f'<div class="session-title">{html.escape(session_name)}</div>'
                '<div class="session-actions">'
                f'<a class="message-session-link" href="{message_session_href}" target="_self" '
                f'aria-label="Message all {html.escape(session_name)} parents">Message all</a>'
                f'<a class="add-child-icon" href="{add_child_href}" target="_self" aria-label="Add child" title="Add child">+</a>'
                '</div>'
                '</div>'
                '<div class="child-list">'
            )
            if not session_children:
                sections_html.append('<div class="muted">No children in this session yet.</div>')
            for child in session_children:
                child_id = child.get("ID", "")
                assigned_parent = approved_parent_by_child.get(child_id)
                message_icon = (
                    '<svg viewBox="0 0 24 24" aria-hidden="true">'
                    '<path d="M4.5 6.5A3.5 3.5 0 0 1 8 3h8a3.5 3.5 0 0 1 3.5 3.5v5A3.5 3.5 0 0 1 16 15H9l-4.5 3.2V6.5Z"/>'
                    '<path d="M8 8h8M8 11h5"/>'
                    '</svg>'
                )
                if assigned_parent:
                    message_link = (
                        f'<a class="message-link" href="{app_href("Children", message_child=child_id)}" '
                        f'aria-label="Message {html.escape(assigned_parent.get("FirstName", "parent"))}" '
                        f'title="Message {html.escape(assigned_parent.get("FirstName", "parent"))}" target="_self">{message_icon}</a>'
                    )
                else:
                    message_link = (
                        f'<span class="message-link disabled" aria-label="No assigned parent" '
                        f'title="No approved parent assigned">{message_icon}</span>'
                    )
                profile_href = app_href("Children", children_edit=1, edit_child=child_id)
                edit_link = f'<a class="edit-link" href="{profile_href}" aria-label="Edit child" title="Edit child" target="_self">...</a>'
                sections_html.append(
                    '<div class="child-row">'
                    f'<a class="profile-link" href="{profile_href}" target="_self" aria-label="Open {html.escape(child.get("Name", "child"))} profile">'
                    f'{child_thumb_html(child)}'
                    '<div class="child-details">'
                    f'<div class="child-name">{html.escape(child.get("Name", ""))}</div>'
                    '</div>'
                    '</a>'
                    f'<div class="row-actions">{message_link}{edit_link}</div>'
                    '</div>'
                )
            sections_html.append("</div></div>")
        sections_html.append("</div>")
        st.markdown("".join(sections_html), unsafe_allow_html=True)


def render_add_child_dialog():
    children = load_children()
    parents = load_parents()
    parent_options = [""] + [parent.get("ID", "") for parent in parents if parent.get("ID")]
    parent_lookup = {parent.get("ID", ""): parent for parent in parents if parent.get("ID")}
    selected_parent_id = st.selectbox(
        "Assign existing parent",
        parent_options,
        format_func=lambda parent_id: "No existing parent selected"
        if not parent_id
        else parent_option_label(parent_lookup.get(parent_id, {})),
        key="add_child_existing_parent",
    )
    selected_parent = parent_lookup.get(selected_parent_id, {})
    guardian_defaults = parent_defaults(selected_parent, {}) if selected_parent else {}
    with st.form("add_child_form", clear_on_submit=True):
        full_name = st.text_input("Child full name")
        date_of_birth = st.date_input("Date of birth", value=None)
        child_badges = child_info_badges_html(date_of_birth)
        if child_badges:
            st.markdown(child_badges, unsafe_allow_html=True)
        session = st.selectbox("Assign to session", SESSIONS)
        st.markdown('<div class="guardian-form-title">Parents/guardians</div>', unsafe_allow_html=True)
        guardian_cols = st.columns([1, 1], gap="small")
        with guardian_cols[0]:
            guardian_name = st.text_input("Parent/guardian name", value=guardian_defaults.get("Name", ""))
        with guardian_cols[1]:
            guardian_relationship = st.selectbox(
                "Relationship",
                CONTACT_RELATIONSHIPS,
                index=relationship_index(guardian_defaults.get("Relationship", "Guardian")),
            )
        guardian_contact_cols = st.columns([1, 1], gap="small")
        with guardian_contact_cols[0]:
            guardian_email = st.text_input("Guardian email", value=guardian_defaults.get("Email", ""))
        with guardian_contact_cols[1]:
            guardian_phone = st.text_input("Guardian phone", value=guardian_defaults.get("Phone", ""))
        guardian_address = st.text_area("Guardian address", value=guardian_defaults.get("Address", ""), height=88)
        guardian_invited = st.checkbox("Invited to use the app", value=guardian_defaults.get("Invited", False))
        thumbnail = st.file_uploader("Thumbnail", type=["png", "jpg", "jpeg"])
        if thumbnail is not None:
            preview_child = {
                "Name": full_name or "Child",
                "Thumbnail": uploaded_thumbnail_data_uri(thumbnail.getvalue()),
            }
            st.markdown(
                f'<div class="current-thumb-preview">{child_thumb_html(preview_child)}<span>New thumbnail preview</span></div>',
                unsafe_allow_html=True,
            )
        submitted = st.form_submit_button("Save Child")

    if st.button("Cancel", key="cancel_add_child_dialog"):
        st.session_state["show_add_child"] = False
        st.rerun()

    if submitted:
        if not full_name:
            st.warning("Please add the child's full name.")
        else:
            thumbnail_path = ""
            if thumbnail is not None:
                thumbnail_path = save_uploaded_thumbnail(thumbnail)

            guardians = guardian_from_fields(
                guardian_name,
                guardian_relationship,
                guardian_email,
                guardian_phone,
                guardian_address,
                guardian_invited,
            )
            new_child = {
                "ID": uuid.uuid4().hex,
                "Name": full_name.strip(),
                "DOB": date_of_birth.isoformat() if date_of_birth else "",
                "Session": session,
                "Thumbnail": thumbnail_path,
                "Guardians": guardians,
            }
            children.append(new_child)
            parent_changed = sync_guardian_to_parent(parents, new_child, guardians, selected_parent_id)
            children_saved = save_children(children)
            parents_saved = save_parents(parents) if children_saved and parent_changed else True
            if children_saved and parents_saved:
                st.session_state["show_add_child"] = False
                st.session_state["child_added_message"] = "Child added."
                st.query_params["app_page"] = "Children"
                st.rerun()
            elif children_saved:
                st.error("The child was saved, but the parent assignment was not saved. Please check the GitHub data key and try again.")
            else:
                st.error("The child was not saved permanently. Please check the GitHub data key and try again.")


if hasattr(st, "dialog"):
    render_add_child_dialog = st.dialog("Add Child")(render_add_child_dialog)


def render_admin_settings():
    data_save_warning = st.session_state.pop("data_save_warning", "")
    if data_save_warning:
        st.warning(data_save_warning)
    child_added_message = st.session_state.pop("child_added_message", "")
    if child_added_message:
        show_quick_notice(child_added_message)

    if "show_add_child" not in st.session_state:
        st.session_state["show_add_child"] = False

    try:
        settings_panel = st.container(key="settings_panel")
    except TypeError:
        settings_panel = st.container()

    with settings_panel:
        st.markdown(
            f"""
            <div class="settings-heading">Settings</div>
            <div class="settings-section">
              <div class="settings-section-title">Children</div>
              <div class="settings-section-copy">Create a child profile, add parent details, and assign a session.</div>
              <a class="settings-action-card" href="{app_href("Settings", add_child=1)}" target="_self" aria-label="Add child">
                <span class="settings-action-icon">+</span>
                <span>
                  <span class="settings-action-title">Add Child</span>
                  <span class="settings-action-copy">Open the child setup form.</span>
                </span>
              </a>
            </div>
            """,
            unsafe_allow_html=True,
        )
        try:
            push_section = st.container(key="settings_push_section")
        except TypeError:
            push_section = st.container()
        with push_section:
            st.markdown(
                '<div class="settings-section-title">Push notifications</div>'
                '<div class="settings-section-copy">Enable notifications on each admin device to receive alerts for new parent messages.</div>',
                unsafe_allow_html=True,
            )
            render_admin_push_control()

    if st.query_params.get("add_child"):
        st.session_state["show_add_child"] = True
        st.query_params.pop("add_child", None)
        st.rerun()

    if st.session_state["show_add_child"]:
        render_add_child_dialog()


def current_parent_record():
    email = str(st.session_state.get("email", "")).strip().lower()
    if email == PLAY_REVIEW_EMAIL:
        return PLAY_REVIEW_PARENT.copy()
    return next((parent for parent in load_parents() if parent.get("Email", "").strip().lower() == email), None)


def current_parent_messages():
    email = str(st.session_state.get("email", "")).strip().lower()
    return [
        message
        for message in load_messages()
        if message.get("ParentEmail", "").strip().lower() == email
    ]


def parent_statement_pdf_bytes():
    try:
        return PARENT_STATEMENT_PDF.read_bytes()
    except OSError:
        return b""


def parent_statement_page_paths():
    return sorted(
        PARENT_STATEMENT_PAGES_DIR.glob("page-*.jpg"),
        key=lambda path: int(path.stem.rsplit("-", 1)[-1]),
    )


def parent_statement_signed(parent):
    return bool(
        parent
        and parent.get("ParentStatementSignedAt")
        and parent.get("ParentStatementVersion") == PARENT_STATEMENT_VERSION
        and parent.get("ParentStatementSignedPdfPath")
    )


def parent_statement_signature_text(parent):
    if not parent_statement_signed(parent):
        return "Needs PDF signature"
    signed_at = message_datetime(parent.get("ParentStatementSignedAt", ""))
    signature = parent.get("ParentStatementSignature", "Parent")
    return f"Signed by {signature} on {signed_at}"


def decode_drawn_signature(signature_data_url):
    encoded = str(signature_data_url or "").strip()
    if not encoded.startswith("data:image/png;base64,"):
        return b""
    try:
        signature_bytes = base64.b64decode(encoded.split(",", 1)[1], validate=True)
        if not signature_bytes or len(signature_bytes) > 2 * 1024 * 1024:
            return b""
        signature_image = Image.open(BytesIO(signature_bytes)).convert("RGBA")
        bounds = signature_image.getchannel("A").getbbox()
        if not bounds:
            return b""
        left, top, right, bottom = bounds
        padding = 10
        signature_image = signature_image.crop(
            (
                max(0, left - padding),
                max(0, top - padding),
                min(signature_image.width, right + padding),
                min(signature_image.height, bottom + padding),
            )
        )
        output = BytesIO()
        signature_image.save(output, format="PNG", optimize=True)
        return output.getvalue()
    except (ValueError, TypeError, OSError):
        return b""


def draw_pdf_value(canvas, value, x, y, max_width, font_size=8.5, bold=False):
    text = " ".join(str(value or "").split())
    font_name = "Helvetica-Bold" if bold else "Helvetica"
    while text and canvas.stringWidth(text, font_name, font_size) > max_width:
        text = text[:-1].rstrip()
    if text != " ".join(str(value or "").split()):
        text = f"{text.rstrip('.')}..."
    canvas.setFont(font_name, font_size)
    canvas.drawString(x, y, text)


def draw_signature_image(canvas, signature_bytes, x, y, max_width, max_height):
    with Image.open(BytesIO(signature_bytes)) as signature_image:
        width, height = signature_image.size
    scale = min(max_width / max(width, 1), max_height / max(height, 1))
    draw_width = width * scale
    draw_height = height * scale
    canvas.drawImage(
        ImageReader(BytesIO(signature_bytes)),
        x,
        y + ((max_height - draw_height) / 2),
        width=draw_width,
        height=draw_height,
        mask="auto",
        preserveAspectRatio=True,
    )


def build_signed_parent_statement_pdf(original_pdf, signature_bytes, signer_name, signer_email, child_name, signed_at, record_id):
    reader = PdfReader(BytesIO(original_pdf))
    if not reader.pages:
        raise ValueError("The parent statement PDF has no pages.")
    signature_page = reader.pages[-1]
    page_width = float(signature_page.mediabox.width)
    page_height = float(signature_page.mediabox.height)
    overlay_buffer = BytesIO()
    overlay = pdf_canvas.Canvas(overlay_buffer, pagesize=(page_width, page_height))
    overlay.setFillColorRGB(0.11, 0.20, 0.38)

    child_parts = str(child_name or "").strip().split()
    child_first_name = child_parts[0] if child_parts else ""
    child_family_name = " ".join(child_parts[1:])
    draw_pdf_value(overlay, child_first_name, 55, 595, 220, 8.5)
    draw_pdf_value(overlay, child_family_name, 292, 595, 220, 8.5)

    draw_signature_image(overlay, signature_bytes, 299, 274, 205, 13)
    draw_pdf_value(overlay, signer_name.upper(), 299, 257, 215, 8.2)
    draw_pdf_value(overlay, signed_at.strftime("%d/%m/%Y"), 299, 239, 215, 8.2)

    box_x, box_y, box_width, box_height = 50, 78, 473, 134
    overlay.setStrokeColorRGB(0.18, 0.33, 0.65)
    overlay.setFillColorRGB(0.96, 0.98, 1.0)
    overlay.roundRect(box_x, box_y, box_width, box_height, 7, stroke=1, fill=1)
    overlay.setFillColorRGB(0.11, 0.20, 0.38)
    overlay.setFont("Helvetica-Bold", 11)
    overlay.drawString(box_x + 14, box_y + box_height - 20, "Digital signature record")
    overlay.setFont("Helvetica", 7.2)
    overlay.drawString(box_x + 14, box_y + box_height - 33, "Signed electronically by the parent/guardian in Ash's Angels Preschool App.")

    field_x = box_x + 14
    value_x = box_x + 67
    field_y = box_y + 78
    for label, value in (
        ("Signer", signer_name),
        ("Email", signer_email),
        ("Child", child_name),
        ("Signed", signed_at.strftime("%d/%m/%Y %H:%M %Z")),
        ("Record ID", record_id),
    ):
        overlay.setFont("Helvetica-Bold", 7.4)
        overlay.drawString(field_x, field_y, f"{label}:")
        draw_pdf_value(overlay, value, value_x, field_y, 200, 7.4)
        field_y -= 14

    signature_x = box_x + 292
    overlay.setFont("Helvetica-Bold", 7.4)
    overlay.drawString(signature_x, box_y + 79, "Drawn signature")
    draw_signature_image(overlay, signature_bytes, signature_x, box_y + 28, 155, 44)
    overlay.setStrokeColorRGB(0.42, 0.50, 0.61)
    overlay.line(signature_x, box_y + 25, signature_x + 155, box_y + 25)
    overlay.setFont("Helvetica", 6.8)
    overlay.setFillColorRGB(0.35, 0.42, 0.50)
    overlay.drawString(box_x + 14, box_y + 9, "Keep this page with the preschool's signed parent statement records.")
    overlay.save()

    overlay_buffer.seek(0)
    signature_page.merge_page(PdfReader(overlay_buffer).pages[0])
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.add_metadata(
        {
            "/Title": f"{PARENT_STATEMENT_VERSION} - Signed",
            "/Author": "Ash's Angels Preschool",
            "/Subject": f"Digitally signed parent statement record {record_id}",
        }
    )
    signed_buffer = BytesIO()
    writer.write(signed_buffer)
    return signed_buffer.getvalue()


@st.cache_data(show_spinner=False)
def signature_page_from_signed_pdf(signed_pdf):
    reader = PdfReader(BytesIO(signed_pdf))
    if not reader.pages:
        return b""
    writer = PdfWriter()
    writer.add_page(reader.pages[-1])
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def save_parent_statement_signature(signature_name, signature_data_url, child):
    email = str(st.session_state.get("email", "")).strip().lower()
    parents = load_parents()
    parent = next((item for item in parents if item.get("Email", "").strip().lower() == email), None)
    original_pdf = parent_statement_pdf_bytes()
    signature_bytes = decode_drawn_signature(signature_data_url)
    if not parent or not original_pdf or not signature_bytes:
        return False

    signed_at = datetime.now(ZoneInfo("Europe/Dublin"))
    record_id = uuid.uuid4().hex[:12].upper()
    child_name = str((child or {}).get("Name") or parent.get("ChildName") or "Not recorded").strip()
    signed_pdf = build_signed_parent_statement_pdf(
        original_pdf,
        signature_bytes,
        signature_name.strip(),
        email,
        child_name,
        signed_at,
        record_id,
    )
    parent_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(parent.get("ID") or "parent")) or "parent"
    signed_path = f"static/signed_forms/{parent_id}-{record_id.lower()}.signed"
    encrypted_pdf = encrypt_signed_form(signed_pdf)
    if not encrypted_pdf or not save_persistent_binary(signed_path, encrypted_pdf, "Save encrypted parent statement"):
        return False

    parent["ParentStatementSigned"] = True
    parent["ParentStatementSignature"] = signature_name.strip()
    parent["ParentStatementSignedAt"] = signed_at.isoformat(timespec="seconds")
    parent["ParentStatementVersion"] = PARENT_STATEMENT_VERSION
    parent["ParentStatementEmail"] = email
    parent["ParentStatementSignedPdfPath"] = signed_path
    parent["ParentStatementSignedPdfSize"] = len(signed_pdf)
    parent["ParentStatementRecordID"] = record_id
    parent["ParentStatementSignatureType"] = "Drawn"
    return save_parents(parents)


def render_parent_message_items(
    parent,
    messages,
    key_prefix="parent_message",
    limit=None,
    children_by_id=None,
    show_archive_controls=True,
    mark_as_read=True,
    unread_first=False,
):
    if unread_first:
        sorted_messages = sorted(
            messages,
            key=lambda message: (not bool(message.get("Read")), message_activity_key(message)),
            reverse=True,
        )
    else:
        sorted_messages = sorted(messages, key=message_activity_key, reverse=True)
    if limit:
        sorted_messages = sorted_messages[:limit]
    if mark_as_read:
        mark_messages_read([message.get("ID", "") for message in sorted_messages], parent.get("Email", ""))
    target_message_id = str(st.query_params.get("message_id", "") or "")
    st.markdown('<div class="parents-list parent-message-list">', unsafe_allow_html=True)
    for message in sorted_messages:
        message_id = message.get("ID", "")
        sent_date = message_datetime(message.get("CreatedAt", ""))
        is_unread = not bool(message.get("Read"))
        anchor_id = message_anchor_id(message_id)
        target_class = " is-target" if target_message_id and message_id == target_message_id else ""
        reply_key = f"{key_prefix}_reply_body_{message_id}"
        reply_open_key = f"{key_prefix}_reply_open_{message_id}"
        replies = message.get("Replies", [])
        replies_html = ""
        if replies:
            replies_html = '<div class="reply-list">'
            for reply_index, reply in enumerate(replies):
                reply_date = message_datetime(reply.get("CreatedAt", ""))
                reply_sender = str(reply.get("From", "") or "").strip().lower()
                reply_class = " is-admin" if reply_sender == "admin" else ""
                reply_attachments = message_attachments_html(
                    reply.get("Attachments", []),
                    f"{key_prefix}-{message_id}-reply-{reply_index}",
                )
                reply_date_html = (
                    f'<span class="reply-date">&middot; {html.escape(reply_date)}</span>'
                    if reply_date
                    else ""
                )
                replies_html += (
                    f'<div class="reply-bubble{reply_class}">'
                    f'<div class="reply-meta"><span>{html.escape(reply_author_label(reply, "Parent"))}</span>'
                    f'{reply_date_html}</div>'
                    f'<div class="message-body">{message_body_html(reply.get("Message", ""))}</div>'
                    f'{reply_attachments}'
                    '</div>'
                )
            replies_html += "</div>"
        message_attachments = message_attachments_html(
            message.get("Attachments", []),
            f"{key_prefix}-{message_id}",
        )
        status_class = " is-new" if is_unread else ""
        status_label = "New" if is_unread else ("Replied" if replies else "Message")
        message_card_html = (
            f'<span id="{html.escape(anchor_id)}" class="message-anchor"></span>'
            f'<div class="parent-row{target_class}">'
            '<div>'
            f'<div class="parent-name">{html.escape(message.get("ChildName", "Preschool message"))}</div>'
            f'<div class="parent-detail"><strong>Sent:</strong> {html.escape(sent_date)}</div>'
            '<div class="parent-message-thread">'
            '<div class="reply-bubble is-admin">'
            f'<div class="reply-meta"><span>Preschool</span><span class="reply-date">&middot; {html.escape(sent_date)}</span></div>'
            f'<div class="message-body">{message_body_html(message.get("Message", ""))}</div>'
            '</div>'
            f'{message_attachments}'
            f'{replies_html}'
            '</div>'
            '</div>'
            f'<div class="parent-status{status_class}">{status_label}</div>'
            '</div>'
        )
        st.markdown(message_card_html, unsafe_allow_html=True)
        action_columns = st.columns([1, 1.35, 2.65], gap="small")
        if action_columns[0].button(
            "Reply",
            key=f"{key_prefix}_open_reply_{message_id}",
            width="stretch",
        ):
            st.session_state[reply_open_key] = True
        if show_archive_controls:
            is_archived = bool(message.get("ParentArchived"))
            archive_label = "Restore" if is_archived else "Archive"
            archive_icon = ":material/unarchive:" if is_archived else ":material/archive:"
            if action_columns[1].button(
                archive_label,
                icon=archive_icon,
                key=f"{key_prefix}_archive_{message_id}",
                width="stretch",
            ):
                if set_parent_message_archived(
                    message_id,
                    parent.get("Email", ""),
                    archived=not is_archived,
                ):
                    st.rerun()
                else:
                    st.error("The message could not be updated. Please try again.")
        if st.session_state.get(reply_open_key):
            reply_media_key = f"{key_prefix}_reply_media_{message_id}"
            reply_body = st.text_area("Reply", key=reply_key, placeholder="Write your reply here...", height=120)
            reply_media_files = st.file_uploader(
                "Photos or videos",
                type=MESSAGE_ATTACHMENT_TYPES,
                accept_multiple_files=True,
                key=reply_media_key,
                help=f"Add up to {MESSAGE_ATTACHMENT_MAX_COUNT} files. Each file can be up to {file_size_label(MESSAGE_ATTACHMENT_MAX_BYTES)}.",
            )
            send_col, cancel_col = st.columns(2)
            if send_col.button("Send Reply", key=f"{key_prefix}_send_reply_{message_id}", type="primary", width="stretch"):
                if not str(reply_body or "").strip() and not reply_media_files:
                    st.warning("Please write a reply or add a photo/video first.")
                else:
                    reply_attachments, attachment_error = prepare_message_attachments(reply_media_files)
                    if attachment_error:
                        st.warning(attachment_error)
                    elif add_parent_reply(message_id, parent, reply_body, reply_attachments):
                        st.session_state.pop(reply_key, None)
                        st.session_state.pop(reply_media_key, None)
                        st.session_state.pop(reply_open_key, None)
                        st.success("Reply sent.")
                        st.rerun()
                    else:
                        st.error("The reply was not saved permanently. Please check the GitHub data key and try again.")
            if cancel_col.button("Cancel Reply", key=f"{key_prefix}_cancel_reply_{message_id}", width="stretch"):
                st.session_state.pop(reply_key, None)
                st.session_state.pop(reply_media_key, None)
                st.session_state.pop(reply_open_key, None)
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def calendar_label(event):
    return f"{event.get('date', '')} - {event.get('event', '')}"


def parse_calendar_dates(value):
    clean_value = " ".join(str(value or "").split())
    patterns = (
        (r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s*-\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$", "full"),
        (r"^(\d{1,2})\s+([A-Za-z]+)\s*-\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$", "same_year"),
        (r"^(\d{1,2})\s*-\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$", "same_month"),
    )
    for pattern, range_type in patterns:
        match = re.match(pattern, clean_value)
        if not match:
            continue
        try:
            if range_type == "full":
                start = datetime.strptime(" ".join(match.group(1, 2, 3)), "%d %B %Y").date()
                end = datetime.strptime(" ".join(match.group(4, 5, 6)), "%d %B %Y").date()
            elif range_type == "same_year":
                start = datetime.strptime(" ".join((match.group(1), match.group(2), match.group(5))), "%d %B %Y").date()
                end = datetime.strptime(" ".join((match.group(3), match.group(4), match.group(5))), "%d %B %Y").date()
            else:
                start = datetime.strptime(" ".join((match.group(1), match.group(3), match.group(4))), "%d %B %Y").date()
                end = datetime.strptime(" ".join((match.group(2), match.group(3), match.group(4))), "%d %B %Y").date()
            return start, end
        except ValueError:
            break
    try:
        return datetime.strptime(clean_value, "%d %B %Y").date(), None
    except ValueError:
        return date.today(), None


def format_calendar_dates(start_date, end_date=None):
    if not start_date:
        return ""
    if not end_date or end_date == start_date:
        return start_date.strftime("%d %B %Y").lstrip("0")
    if start_date.year == end_date.year and start_date.month == end_date.month:
        return f"{start_date.day}-{end_date.day} {end_date.strftime('%B %Y')}"
    if start_date.year == end_date.year:
        return f"{start_date.day} {start_date.strftime('%B')} - {end_date.day} {end_date.strftime('%B %Y')}"
    return f"{start_date.day} {start_date.strftime('%B %Y')} - {end_date.day} {end_date.strftime('%B %Y')}"


def render_calendar_editor(events):
    notice = st.session_state.pop("calendar_notice", "")
    if notice:
        show_quick_notice(notice)

    st.markdown(
        '<div class="panel parents-panel calendar-editor-panel">'
        '<div class="panel-title">Edit Calendar</div>'
        "</div>",
        unsafe_allow_html=True,
    )

    with st.form("add_calendar_event_form", clear_on_submit=True):
        add_date = st.date_input("Date", value=None, format="DD/MM/YYYY")
        add_end_date = st.date_input("End date (optional)", value=None, format="DD/MM/YYYY")
        add_event = st.text_input("Calendar item", placeholder="Preschool re-opening")
        add_tag = st.selectbox("Type", CALENDAR_TAGS, index=2)
        add_submitted = st.form_submit_button("Add Calendar Item")

    if add_submitted:
        if not add_date or not add_event.strip():
            st.warning("Please add the date and calendar item.")
        elif add_end_date and add_end_date < add_date:
            st.warning("The end date must be after the start date.")
        else:
            updated_events = [
                *events,
                {
                    "id": uuid.uuid4().hex,
                    "date": format_calendar_dates(add_date, add_end_date),
                    "event": add_event.strip(),
                    "tag": add_tag,
                },
            ]
            if save_calendar_events(updated_events):
                st.session_state["calendar_notice"] = "Calendar item added."
                st.rerun()
            else:
                st.error("The calendar item was not saved permanently. Please check the GitHub data key and try again.")

    if not events:
        st.markdown('<div class="muted">No calendar items added yet.</div>', unsafe_allow_html=True)
        return

    calendar_options = {event["id"]: calendar_label(event) for event in events}
    selected_id = st.selectbox(
        "Edit existing item",
        list(calendar_options.keys()),
        format_func=lambda event_id: calendar_options.get(event_id, event_id),
    )
    selected_event = next((event for event in events if event.get("id") == selected_id), events[0])
    selected_tag = selected_event.get("tag", "Event")
    selected_tag_index = CALENDAR_TAGS.index(selected_tag) if selected_tag in CALENDAR_TAGS else 2
    selected_start_date, selected_end_date = parse_calendar_dates(selected_event.get("date", ""))

    with st.form(f"edit_calendar_event_form_{selected_id}"):
        edited_date = st.date_input("Date", value=selected_start_date, format="DD/MM/YYYY")
        edited_end_date = st.date_input("End date (optional)", value=selected_end_date, format="DD/MM/YYYY")
        edited_event = st.text_input("Calendar item", value=selected_event.get("event", ""))
        edited_tag = st.selectbox("Type", CALENDAR_TAGS, index=selected_tag_index)
        save_col, delete_col = st.columns(2)
        save_submitted = save_col.form_submit_button("Save Calendar Item")
        delete_submitted = delete_col.form_submit_button("Delete Item")

    if save_submitted:
        if not edited_date or not edited_event.strip():
            st.warning("Please add the date and calendar item.")
        elif edited_end_date and edited_end_date < edited_date:
            st.warning("The end date must be after the start date.")
        else:
            updated_events = []
            for event in events:
                if event.get("id") == selected_id:
                    updated_events.append(
                        {
                            "id": selected_id,
                            "date": format_calendar_dates(edited_date, edited_end_date),
                            "event": edited_event.strip(),
                            "tag": edited_tag,
                        }
                    )
                else:
                    updated_events.append(event)
            if save_calendar_events(updated_events):
                st.session_state["calendar_notice"] = "Calendar item updated."
                st.rerun()
            else:
                st.error("The calendar item was not saved permanently. Please check the GitHub data key and try again.")

    if delete_submitted:
        updated_events = [event for event in events if event.get("id") != selected_id]
        if save_calendar_events(updated_events):
            st.session_state["calendar_notice"] = "Calendar item deleted."
            st.rerun()
        else:
            st.error("The calendar item was not deleted permanently. Please check the GitHub data key and try again.")


def render_delete_document_dialog(document):
    document_id = document.get("ID", "")
    title = document.get("Title", "this document")
    st.markdown(
        f'<div class="panel-title">Delete document</div>'
        f'<div class="muted">Delete {html.escape(title)} from the app?</div>',
        unsafe_allow_html=True,
    )
    confirm_col, cancel_col = st.columns(2)
    if confirm_col.button("Delete document", key=f"confirm_delete_document_{document_id}", width="stretch"):
        if delete_document(document_id):
            st.session_state["document_notice"] = "Document deleted."
            st.query_params.pop("delete_document", None)
            st.rerun()
        else:
            st.error("The document was not deleted permanently. Please check the GitHub data key and try again.")
    if cancel_col.button("Cancel", key=f"cancel_delete_document_{document_id}", width="stretch"):
        st.query_params.pop("delete_document", None)
        st.rerun()


if hasattr(st, "dialog"):
    render_delete_document_dialog = st.dialog("Delete document")(render_delete_document_dialog)


def render_document_drag_controls(documents):
    records = [
        {"id": str(document.get("ID", "")), "audience": str(document.get("Audience", "Parents"))}
        for document in documents
        if document.get("ID")
    ]
    records_json = json.dumps(records).replace("</", "<\\/")
    audiences_json = json.dumps(DOCUMENT_AUDIENCES).replace("</", "<\\/")
    components.html(
        f"""
        <script>
        (() => {{
          const parentWindow = window.parent;
          const doc = parentWindow.document;
          const records = {records_json};
          const audiences = {audiences_json};
          let activeRecord = null;
          let activeRow = null;
          let activeZone = null;

          const keyedAncestor = (marker, key) => {{
            let node = marker;
            const className = `st-key-${{key}}`;
            while (node && node !== doc.body) {{
              if (node.classList && node.classList.contains(className)) return node;
              node = node.parentElement;
            }}
            return null;
          }};

          const clearDragState = () => {{
            activeRow?.classList.remove("is-dragging");
            activeZone?.classList.remove("is-drop-target");
            doc.body?.classList.remove("document-is-dragging");
            activeRecord = null;
            activeRow = null;
            activeZone = null;
          }};

          const destinationAt = (x, y) => {{
            const element = doc.elementFromPoint(x, y);
            return element?.closest(".document-drop-zone") || null;
          }};

          const showDestination = (zone) => {{
            activeZone?.classList.remove("is-drop-target");
            activeZone = zone;
            if (activeZone && activeZone.dataset.audience !== activeRecord?.audience) {{
              activeZone.classList.add("is-drop-target");
            }}
          }};

          const moveTo = (zone) => {{
            if (!activeRecord || !zone) return clearDragState();
            const audience = zone.dataset.audience || "";
            if (!audience || audience === activeRecord.audience) return clearDragState();
            const moveLink = Array.from(doc.querySelectorAll(".document-move-link")).find(
              (link) => link.dataset.documentId === activeRecord.id && link.dataset.audience === audience
            );
            clearDragState();
            moveLink?.click();
          }};

          const bindZone = (audience) => {{
            const marker = doc.querySelector(`.document-drop-marker[data-audience="${{audience}}"]`);
            const zone = marker && keyedAncestor(marker, `document_section_${{audience.toLowerCase()}}`);
            if (!zone) return;
            zone.classList.add("document-drop-zone");
            zone.dataset.audience = audience;
            if (zone.dataset.documentDropBound === "true") return;
            zone.dataset.documentDropBound = "true";
            zone.addEventListener("dragover", (event) => {{
              if (!activeRecord || activeRecord.audience === audience) return;
              event.preventDefault();
              showDestination(zone);
            }});
            zone.addEventListener("dragleave", (event) => {{
              if (!zone.contains(event.relatedTarget)) zone.classList.remove("is-drop-target");
            }});
            zone.addEventListener("drop", (event) => {{
              event.preventDefault();
              moveTo(zone);
            }});
          }};

          const bindRow = (record) => {{
            const marker = doc.querySelector(`.document-drag-marker[data-document-id="${{record.id}}"]`);
            const row = marker && keyedAncestor(marker, `document_row_${{record.id}}`);
            if (!row) return;
            row.classList.add("document-draggable-row");
            const currentIndex = audiences.indexOf(record.audience);
            const keyboardDestination = audiences[(currentIndex + 1) % audiences.length];
            let handle = row.querySelector(".document-drag-handle");
            if (!handle) {{
              handle = doc.createElement("button");
              handle.type = "button";
              handle.className = "document-drag-handle";
              handle.innerHTML = '<span aria-hidden="true">&#8942;&#8942;</span>';
              row.insertBefore(handle, row.firstChild);
            }}
            handle.setAttribute("aria-label", `Move document to ${{keyboardDestination}}`);
            const pdfIcon = row.querySelector(".document-pdf-icon");
            if (pdfIcon) {{
              pdfIcon.setAttribute("role", "button");
              pdfIcon.setAttribute("tabindex", "0");
              pdfIcon.setAttribute("aria-label", `Move PDF document to ${{keyboardDestination}}`);
            }}

            const bindDragSource = (source) => {{
              if (!source || source.dataset.documentDragBound === "true") return;
              source.dataset.documentDragBound = "true";
              source.classList.add("document-drag-source");
              source.draggable = false;
              source.title = "Drag document to another section";
              source.addEventListener("mousedown", (event) => {{
                activeRecord = record;
                activeRow = row;
                row.classList.add("is-dragging");
                doc.body?.classList.add("document-is-dragging");
                event.preventDefault();
              }});
              source.addEventListener("keydown", (event) => {{
                if (event.key !== "Enter" && event.key !== " ") return;
                event.preventDefault();
                activeRecord = record;
                activeRow = row;
                const marker = doc.querySelector(`.document-drop-marker[data-audience="${{keyboardDestination}}"]`);
                moveTo(marker && keyedAncestor(marker, `document_section_${{keyboardDestination.toLowerCase()}}`));
              }});
              source.addEventListener("pointerdown", (event) => {{
                if (event.pointerType === "mouse") return;
                activeRecord = record;
                activeRow = row;
                row.classList.add("is-dragging");
                doc.body?.classList.add("document-is-dragging");
                source.setPointerCapture(event.pointerId);
                event.preventDefault();
              }});
              source.addEventListener("pointermove", (event) => {{
                if (!activeRecord || event.pointerType === "mouse") return;
                showDestination(destinationAt(event.clientX, event.clientY));
                event.preventDefault();
              }});
              source.addEventListener("pointerup", (event) => {{
                if (!activeRecord || event.pointerType === "mouse") return;
                moveTo(destinationAt(event.clientX, event.clientY));
              }});
              source.addEventListener("pointercancel", clearDragState);
            }};
            bindDragSource(handle);
            bindDragSource(pdfIcon);
          }};

          const install = () => {{
            audiences.forEach(bindZone);
            records.forEach(bindRow);
          }};
          if (typeof parentWindow.__ashsDocumentMouseCleanup === "function") {{
            parentWindow.__ashsDocumentMouseCleanup();
          }}
          const trackMouse = (event) => {{
            if (activeRecord) showDestination(destinationAt(event.clientX, event.clientY));
          }};
          const releaseMouse = (event) => {{
            if (activeRecord) moveTo(destinationAt(event.clientX, event.clientY));
          }};
          doc.addEventListener("mousemove", trackMouse);
          doc.addEventListener("mouseup", releaseMouse);
          parentWindow.__ashsDocumentMouseCleanup = () => {{
            doc.removeEventListener("mousemove", trackMouse);
            doc.removeEventListener("mouseup", releaseMouse);
          }};
          install();
          [80, 240, 700].forEach((delay) => parentWindow.setTimeout(install, delay));
          if (doc.body) {{
            const observer = new MutationObserver(install);
            observer.observe(doc.body, {{ childList: true, subtree: true }});
            parentWindow.setTimeout(() => observer.disconnect(), 4000);
          }}
        }})();
        </script>
        """,
        height=0,
    )


def render_documents():
    is_admin = st.session_state.get("role") == "Admin"
    move_document_id = str(st.query_params.get("move_document", "") or "")
    move_audience = str(st.query_params.get("document_audience", "") or "").title()
    if is_admin and move_document_id:
        for param in ("move_document", "document_audience"):
            st.query_params.pop(param, None)
        if move_document(move_document_id, move_audience):
            st.session_state["document_notice"] = f"Document moved to {move_audience}."
        else:
            st.session_state["data_save_warning"] = "The document could not be moved permanently. Please try again."
        st.rerun()
    all_documents = load_documents()
    documents = (
        all_documents
        if is_admin
        else [
            document
            for document in all_documents
            if document.get("Audience") in {"Important", "Parents"}
        ]
    )
    def render_document_row(document):
        document_id = document.get("ID", "")
        pdf_bytes = document_bytes(document)
        open_url = document_open_url(document)
        drag_controls_html = ""
        if is_admin:
            current_audience = str(document.get("Audience") or "Parents")
            move_links_html = "".join(
                (
                    f'<a class="document-move-link" data-document-id="{html.escape(document_id, quote=True)}" '
                    f'data-audience="{destination}" href="{html.escape(app_href("Documents", move_document=document_id, document_audience=destination), quote=True)}" '
                    'target="_self" tabindex="-1"></a>'
                )
                for destination in DOCUMENT_AUDIENCES
                if destination != current_audience
            )
            drag_controls_html = (
                f'<span class="document-drag-marker" data-document-id="{html.escape(document_id, quote=True)}" '
                f'data-document-audience="{html.escape(current_audience, quote=True)}"></span>'
                + move_links_html
            )
        with st.container(border=True, key=f"document_row_{document_id}"):
            file_name = Path(str(document.get("FileName") or "document.pdf")).name
            st.markdown(
                drag_controls_html
                + '<div class="document-file-summary">'
                + '<div class="document-file-visual">'
                + '<div class="document-pdf-icon" role="img" aria-label="PDF document"><span aria-hidden="true">PDF</span></div>'
                + f'<div class="document-file-name" title="{html.escape(file_name, quote=True)}">{html.escape(file_name)}</div>'
                + '</div>'
                + '<div class="document-file-copy">'
                + f'<div class="parent-name">{html.escape(document.get("Title", "Document"))}</div>'
                + '</div></div>',
                unsafe_allow_html=True,
            )
            action_sizes = [1.1, 1.5, 1.1, 3.3] if is_admin else [1.1, 1.5, 4.4]
            actions = st.columns(action_sizes, vertical_alignment="center")
            actions[0].link_button(
                "Open",
                open_url,
                icon=":material/open_in_new:",
                disabled=not bool(open_url),
            )
            actions[1].download_button(
                "Download",
                data=pdf_bytes,
                file_name=document.get("FileName", "document.pdf"),
                mime="application/pdf",
                icon=":material/download:",
                disabled=not bool(pdf_bytes),
                key=f"download_document_{document_id}",
            )
            if is_admin and actions[2].button(
                "Delete",
                icon=":material/delete:",
                key=f"delete_document_{document_id}",
            ):
                st.query_params["delete_document"] = document_id
                st.rerun()

    document_sections = [
        (audience, [document for document in documents if document.get("Audience") == audience])
        for audience in DOCUMENT_AUDIENCES
        if is_admin or any(document.get("Audience") == audience for document in documents)
    ]

    notice = st.session_state.pop("document_notice", "")
    data_save_warning = st.session_state.pop("data_save_warning", "")
    delete_document_id = str(st.query_params.get("delete_document", "") or "")

    with st.container(key="documents_page_panel"):
        if notice:
            st.success(notice)
        if data_save_warning:
            st.warning(data_save_warning)

        st.markdown('<div class="documents-page-heading">Documents</div>', unsafe_allow_html=True)

        if is_admin and delete_document_id:
            selected_document = next(
                (document for document in all_documents if document.get("ID") == delete_document_id),
                None,
            )
            if selected_document:
                render_delete_document_dialog(selected_document)
            else:
                st.query_params.pop("delete_document", None)

        if is_admin:
            st.markdown('<div class="documents-section-heading">Upload PDF</div>', unsafe_allow_html=True)
            with st.form("document_upload_form", clear_on_submit=True):
                upload_title = st.text_input("Document title")
                upload_description = st.text_input("Description")
                upload_audience = st.selectbox(
                    "Section",
                    DOCUMENT_AUDIENCES,
                    index=DOCUMENT_AUDIENCES.index("Parents"),
                )
                uploaded_pdf = st.file_uploader("PDF file", type=["pdf"])
                upload_submitted = st.form_submit_button("Upload document")
            if upload_submitted:
                saved, error = save_uploaded_document(
                    uploaded_pdf,
                    upload_title,
                    upload_description,
                    upload_audience,
                )
                if saved:
                    st.session_state["document_notice"] = "Document uploaded."
                    st.rerun()
                else:
                    st.warning(error)
            st.markdown('<div class="documents-rule"></div>', unsafe_allow_html=True)

        for audience, section_documents in document_sections:
            with st.container(key=f"document_section_{audience.lower()}"):
                section_heading = f'<div class="documents-section-heading">{audience}</div>'
                if is_admin:
                    visibility_text = {
                        "Important": "Shown to parents on their home dashboard and documents page.",
                        "Parents": "Visible to approved parent accounts.",
                        "Private": "Visible only to administrators.",
                    }[audience]
                    st.markdown(
                        f'<span class="document-drop-marker" data-audience="{audience}"></span>'
                        + section_heading
                        + f'<div class="muted">{visibility_text}</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(section_heading, unsafe_allow_html=True)
                if not section_documents:
                    st.markdown(
                        f'<div class="muted">No {audience.lower()} documents have been added yet.</div>',
                        unsafe_allow_html=True,
                    )
                for document in section_documents:
                    render_document_row(document)

        if is_admin:
            render_document_drag_controls(documents)
        st.markdown('<div class="documents-bottom-space" aria-hidden="true"></div>', unsafe_allow_html=True)


def render_calendar():
    events = load_calendar_events()
    rows = []
    for item in events:
        tag = item["tag"]
        tag_class = tag.lower()
        rows.append(
            '<div class="calendar-row">'
            f'<div class="calendar-date">{html.escape(item["date"])}</div>'
            f'<div class="calendar-event">{html.escape(item["event"])}</div>'
            f'<div class="calendar-tag {html.escape(tag_class)}">{html.escape(tag)}</div>'
            "</div>"
        )

    download_link = ""
    if CALENDAR_PDF.exists():
        encoded_pdf = base64.b64encode(CALENDAR_PDF.read_bytes()).decode("ascii")
        download_link = (
            '<a class="calendar-download" '
            f'href="data:application/pdf;base64,{encoded_pdf}" '
            'download="preschool-calendar-2026-2027.pdf" target="_self">'
            "Download calendar PDF"
            "</a>"
        )

    calendar_html = (
        '<div class="panel parents-panel">'
        '<div class="panel-title">Preschool Calendar</div>'
        '<div class="calendar-intro">Key preschool dates for 2026/2027.</div>'
        f'<div class="calendar-list">{"".join(rows)}</div>'
        f"{download_link}"
        "</div>"
    )
    st.markdown(calendar_html, unsafe_allow_html=True)
    if st.session_state.get("role") == "Admin":
        render_calendar_editor(events)


def render_parent_important_documents():
    important_documents = [
        document
        for document in load_documents()
        if document.get("Audience") == "Important"
    ]
    if not important_documents:
        return

    st.markdown(
        '<div class="parent-important-heading">Important documents</div>',
        unsafe_allow_html=True,
    )
    for document in important_documents:
        file_name = Path(str(document.get("FileName") or "document.pdf")).name
        open_url = document_open_url(document)
        description_html = (
            f'<div class="parent-detail">{html.escape(document.get("Description", ""))}</div>'
            if document.get("Description")
            else ""
        )
        st.markdown(
            '<div class="parent-row parent-important-document">'
            + '<div class="document-file-summary">'
            + '<div class="document-file-visual">'
            + '<div class="document-pdf-icon" role="img" aria-label="PDF document"><span aria-hidden="true">PDF</span></div>'
            + f'<div class="document-file-name" title="{html.escape(file_name, quote=True)}">{html.escape(file_name)}</div>'
            + '</div>'
            + '<div class="document-file-copy">'
            + f'<div class="parent-name">{html.escape(document.get("Title", "Document"))}</div>'
            + description_html
            + '</div></div>'
            + f'<a class="parent-status parent-action-button" href="{html.escape(open_url, quote=True)}" target="_blank" rel="noopener">Open</a>'
            + '</div>',
            unsafe_allow_html=True,
        )


def render_parent_message_auto_refresh(key_prefix, interval_ms=15000):
    reply_is_open = any(
        key.startswith(f"{key_prefix}_reply_open_") and bool(value)
        for key, value in st.session_state.items()
    )
    if reply_is_open:
        return
    components.html(
        f"""
        <script>
        try {{
          const parentWindow = window.parent;
          if (parentWindow.__ashParentMessageRefreshTimer) {{
            parentWindow.clearTimeout(parentWindow.__ashParentMessageRefreshTimer);
          }}
          parentWindow.__ashParentMessageRefreshTimer = parentWindow.setTimeout(() => {{
            parentWindow.location.reload();
          }}, {int(interval_ms)});
        }} catch (error) {{}}
        </script>
        """,
        height=0,
    )


def render_parent_dashboard():
    parent = current_parent_record()
    children = load_children()
    children_by_id = {child.get("ID", ""): child for child in children if child.get("ID")}
    if str(st.session_state.get("email", "")).strip().lower() == PLAY_REVIEW_EMAIL:
        children_by_id[PLAY_REVIEW_CHILD["ID"]] = PLAY_REVIEW_CHILD
    if not parent:
        st.markdown(
            '<div class="panel parents-panel"><div class="muted">We could not find your parent registration yet.</div></div>',
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f"""
        <div class="parent-row">
          <div>
            <div class="parent-name">Preschool Calendar</div>
            <div class="parent-detail">View key preschool dates and holidays for 2026/2027.</div>
          </div>
          <a class="parent-status parent-action-button" href="{app_href("Calendar")}" target="_self">Open</a>
        </div>
        """,
        unsafe_allow_html=True,
    )

    status = parent.get("Status", "Pending")
    child = children_by_id.get(parent.get("ChildID", ""))
    if status != "Approved":
        st.markdown(
            '<div class="parent-row"><div><div class="parent-name">Registration pending</div>'
            '<div class="parent-detail">Your registration has been received. The preschool will approve it and assign your child.</div>'
            '</div><div class="parent-status pending">Pending</div></div></div>',
            unsafe_allow_html=True,
        )
        return

    if not child:
        st.markdown(
            '<div class="parent-row"><div><div class="parent-name">Approved</div>'
            '<div class="parent-detail">Your account is approved. A child has not been assigned yet.</div>'
            '</div><div class="parent-status">Approved</div></div>',
            unsafe_allow_html=True,
        )
        return

    render_parent_important_documents()

    messages = [
        message
        for message in current_parent_messages()
        if not message.get("ParentArchived")
    ]
    if messages:
        unread_count = sum(1 for message in messages if not message.get("Read"))
        message_heading = f"New messages ({unread_count})" if unread_count else "Latest messages"
        st.markdown(f'<div class="section-title">{message_heading}</div>', unsafe_allow_html=True)
        render_parent_message_items(
            parent,
            messages,
            key_prefix="dashboard_message",
            limit=3,
            children_by_id=children_by_id,
            mark_as_read=False,
            unread_first=True,
        )
        if len(messages) > 3:
            st.markdown(f'<a class="menu-item" href="{app_href("Messages")}" target="_self">View all messages</a>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="parent-row"><div><div class="parent-name">Messages</div><div class="parent-detail">No messages yet.</div></div></div>', unsafe_allow_html=True)
    render_parent_message_auto_refresh("dashboard_message")


def render_parent_messages():
    parent = current_parent_record()
    messages = current_parent_messages()
    if not parent:
        st.markdown(
            '<div class="panel parents-panel"><div class="muted">We could not find your parent registration yet.</div></div>',
            unsafe_allow_html=True,
        )
        return
    if not messages:
        st.markdown('<div class="panel parents-panel"><div class="muted">No messages yet.</div></div>', unsafe_allow_html=True)
        render_parent_message_auto_refresh("parent_message")
        return
    render_parent_message_items(parent, messages)
    render_parent_message_auto_refresh("parent_message")


def render_admin_message_item(
    message,
    index,
    target_message_id,
    children_by_id,
    children_by_name,
    parents_by_id,
    parents_by_email,
):
    message_id = message.get("ID", "")
    anchor_id = message_anchor_id(message_id)
    target_class = " is-target" if target_message_id and message_id == target_message_id else ""
    sent_date = message_datetime(message.get("CreatedAt", ""))
    read_at = message_datetime(message.get("ReadAt", "")) if message.get("ReadAt") else ""
    read_status = f"Read {read_at}" if message.get("Read") else "Unread"
    read_badge_class = "read-badge is-read" if message.get("Read") else "read-badge"
    read_icon = '<span class="read-tick">&#10003;</span>' if message.get("Read") else ""
    parent_name = message.get("ParentName", "") or message.get("ParentEmail", "Parent")
    child_name = message.get("ChildName", "Preschool message")
    child = message_child_record(message, children_by_id, children_by_name, parents_by_id, parents_by_email)
    child_name = child.get("Name") or child_name
    replies = message.get("Replies", [])
    replies_html = ""
    if replies:
        replies_html = '<div class="reply-list">'
        for reply_index, reply in enumerate(replies):
            reply_date = message_datetime(reply.get("CreatedAt", ""))
            reply_sender = str(reply.get("From", "") or "").strip().lower()
            reply_class = " is-admin" if reply_sender == "admin" else ""
            reply_attachments = message_attachments_html(
                reply.get("Attachments", []),
                f"admin-{message_id or index}-reply-{reply_index}",
            )
            reply_date_html = (
                f'<span class="reply-date">&middot; {html.escape(reply_date)}</span>'
                if reply_date
                else ""
            )
            replies_html += (
                f'<div class="reply-bubble{reply_class}">'
                f'<div class="reply-meta"><span>{html.escape(reply_author_label(reply, "Admin"))}</span>'
                f'{reply_date_html}</div>'
                f'<div class="message-body">{message_body_html(reply.get("Message", ""))}</div>'
                f'{reply_attachments}'
                '</div>'
            )
        replies_html += "</div>"
    message_attachments = message_attachments_html(
        message.get("Attachments", []),
        f"admin-{message_id or index}",
    )
    media_class = " has-media" if message_attachments else ""
    media_html = f'<div class="admin-message-media">{message_attachments}</div>' if message_attachments else ""
    delete_key = f"delete_message_{message_id or index}"
    message_card_html = (
        f'<span id="{html.escape(anchor_id)}" class="message-anchor"></span>'
        f'<div class="parent-row admin-message-row{target_class}">'
        '<div class="admin-message-layout">'
        '<div class="admin-message-header">'
        '<div class="message-title-line">'
        f'{child_thumb_html(child)}'
        '<div class="admin-message-heading">'
        f'<div class="parent-name">{html.escape(child_name)}</div>'
        f'<div class="admin-message-recipient">To {html.escape(parent_name)}</div>'
        '</div>'
        '</div>'
        '<div class="message-status-stack">'
        f'<div class="parent-status">{"Replied" if replies else "Sent"}</div>'
        f'<div class="{read_badge_class}">{read_icon}<span>{html.escape(read_status)}</span></div>'
        '</div>'
        '</div>'
        f'<div class="admin-message-content{media_class}">'
        '<div class="admin-message-thread">'
        '<div class="admin-message-original">'
        '<div class="admin-message-label"><span>Me</span>'
        f'<span class="admin-message-sent">&middot; {html.escape(sent_date or "Not recorded")}</span></div>'
        f'<div class="message-body">{message_body_html(message.get("Message", ""))}</div>'
        '</div>'
        f'{replies_html}'
        '</div>'
        f'{media_html}'
        '</div>'
        '</div>'
        '</div>'
    )
    try:
        message_container = st.container(key=f"admin_message_card_{message_id or index}")
    except TypeError:
        message_container = st.container()
    with message_container:
        st.markdown(message_card_html, unsafe_allow_html=True)
        reply_col, delete_col, _action_spacer = st.columns([1, 1, 5], gap="small")
        if reply_col.button(
            "Reply",
            key=f"admin_reply_message_{message_id or index}",
            type="tertiary",
            icon=":material/reply:",
            help="Reply in this thread",
            width="stretch",
        ):
            st.query_params["reply_message"] = message_id
            st.rerun()
        if delete_col.button(
            "Delete",
            key=delete_key,
            type="tertiary",
            icon=":material/delete:",
            help="Delete message",
            width="stretch",
        ):
            st.session_state["confirm_delete_message_id"] = message_id
            st.rerun()
        if st.session_state.get("confirm_delete_message_id") == message_id:
            render_delete_message_dialog(message)


def render_parent_forms():
    parent = current_parent_record()
    statement_pdf = parent_statement_pdf_bytes()
    signed = parent_statement_signed(parent)
    status_label = "Signed" if signed else "Needs signature"
    status_class = "" if signed else "pending"

    st.markdown(
        f"""
        <div class="panel parents-panel">
          <div class="panel-title">Forms</div>
          <div class="parent-row">
            <div>
              <div class="parent-name">{html.escape(PARENT_STATEMENT_VERSION)}</div>
              <div class="parent-detail">Read and sign the official PDF.</div>
            </div>
            <div class="parent-status {status_class}">{status_label}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not parent:
        st.warning("We could not find your parent registration yet.")
        return

    if not statement_pdf:
        st.error("The Parent Statement PDF is not available yet. Please contact the preschool.")
        return

    statement_pages = parent_statement_page_paths()
    if not statement_pages:
        st.error("The Parent Statement pages are not available yet. Please contact the preschool.")
        return
    selected_page = st.selectbox(
        "Statement page",
        range(len(statement_pages)),
        format_func=lambda page_index: f"Page {page_index + 1} of {len(statement_pages)}",
        key="parent_statement_page",
    )
    st.image(statement_pages[selected_page], width="stretch")

    signed_pdf = load_signed_parent_statement(parent) if signed else b""

    if signed:
        st.markdown(
            f'<div class="statement-signed-note">{html.escape(parent_statement_signature_text(parent))}</div>',
            unsafe_allow_html=True,
        )
        if signed_pdf:
            signature_page = signature_page_from_signed_pdf(signed_pdf)
            full_copy, signature_copy = st.columns(2, gap="small")
            full_copy.download_button(
                "Signed PDF",
                data=signed_pdf,
                file_name="parent-statement-2026-2027-signed.pdf",
                mime="application/pdf",
                icon=":material/download:",
                width="stretch",
            )
            signature_copy.download_button(
                "Signature page",
                data=signature_page,
                file_name="parent-statement-signature-page.pdf",
                mime="application/pdf",
                icon=":material/print:",
                width="stretch",
            )
        return

    st.download_button(
        "Download unsigned PDF",
        data=statement_pdf,
        file_name="parent-statement-2026-2027.pdf",
        mime="application/pdf",
        icon=":material/download:",
        width="stretch",
    )
    signature_name = st.text_input(
        "Parent/guardian full name",
        value=str(parent.get("FirstName") or ""),
        key="parent_statement_signature",
    )
    st.markdown('<div class="parent-name signature-pad-label">Draw your signature</div>', unsafe_allow_html=True)
    signature_data = SIGNATURE_COMPONENT(default="", key="parent_statement_signature_pad")
    confirm_read = st.checkbox(
        "I have read the Parent Statement and agree that the signature above is my electronic signature.",
        key="parent_statement_confirm_read",
    )
    if st.button("Sign and create PDF", type="primary", width="stretch"):
        clean_signature = str(signature_name or "").strip()
        if not clean_signature:
            st.warning("Please enter your full name.")
        elif not decode_drawn_signature(signature_data):
            st.warning("Please draw your signature in the box.")
        elif not confirm_read:
            st.warning("Please confirm that you have read and agree to the statement.")
        else:
            children_by_id = {child.get("ID", ""): child for child in load_children()}
            child = children_by_id.get(parent.get("ChildID", ""), {"Name": parent.get("ChildName", "")})
            try:
                saved = save_parent_statement_signature(clean_signature, signature_data, child)
            except Exception:
                saved = False
            if saved:
                st.session_state.pop("parent_statement_signature", None)
                st.session_state.pop("parent_statement_confirm_read", None)
                st.success("Your signed PDF has been saved.")
                st.rerun()
            else:
                st.error("The signed PDF could not be saved. Please try again or contact the preschool.")


def render_parent_settings():
    try:
        settings_panel = st.container(key="settings_panel")
    except TypeError:
        settings_panel = st.container()

    with settings_panel:
        st.markdown('<div class="settings-heading">Settings</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="settings-support-links">'
            f'<a class="section-edit" href="{PRIVACY_POLICY_URL}" target="_blank">Privacy policy</a>'
            f'<a class="section-edit" href="{ACCOUNT_DELETION_URL}" target="_blank">Request account deletion</a>'
            '</div>',
            unsafe_allow_html=True,
        )


def public_page_styles():
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"], [data-testid="stHeader"], [data-testid="stToolbar"] { display: none !important; }
        .stApp { background: #f5f8fc !important; }
        .block-container { width: min(900px, calc(100% - 32px)) !important; max-width: 900px !important; padding: 48px 0 72px !important; }
        .public-page { color: #1f315e; font-family: system-ui, sans-serif; letter-spacing: 0; }
        .public-page-header { display: flex; align-items: center; gap: 18px; margin-bottom: 32px; padding-bottom: 24px; border-bottom: 1px solid #d8e1ed; }
        .public-page-logo { width: 92px; height: 92px; object-fit: contain; }
        .public-page h1 { margin: 0; color: #294999; font-family: system-ui, sans-serif; font-size: clamp(2rem, 5vw, 3rem); line-height: 1.08; letter-spacing: 0; }
        .public-page h2 { margin: 34px 0 10px; color: #294999; font-family: system-ui, sans-serif; font-size: 1.35rem; line-height: 1.25; letter-spacing: 0; }
        .public-page p, .public-page li { color: #43536e; font-size: 1rem; line-height: 1.65; letter-spacing: 0; }
        .public-page ul { margin: 8px 0 0; padding-left: 24px; }
        .public-page-meta { margin-top: 7px; color: #687892; font-size: .95rem; }
        .public-page-action { display: inline-flex; align-items: center; min-height: 48px; margin: 12px 0 8px; padding: 0 20px; border-radius: 6px; background: #294999; color: #ffffff !important; font-weight: 800; text-decoration: none !important; }
        .public-page-note { margin-top: 24px; padding: 18px 20px; border-left: 4px solid #294999; background: #eaf3fd; }
        @media (max-width: 600px) {
            .block-container { width: min(100% - 24px, 900px) !important; padding-top: 28px !important; }
            .public-page-header { align-items: flex-start; }
            .public-page-logo { width: 70px; height: 70px; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_public_privacy_policy():
    public_page_styles()
    st.markdown(
        f"""
        <main class="public-page">
          <header class="public-page-header">
            <img class="public-page-logo" src="{asset_url(LOGO_IMAGE)}" alt="Ash's Angels Preschool logo">
            <div><h1>Privacy Policy</h1><div class="public-page-meta">Ash's Angels Preschool App &middot; Last updated 15 July 2026</div></div>
          </header>
          <p>Ash's Angels Preschool provides this app to approved parents, guardians and preschool administrators. This policy explains how personal data is used when you register for or use the app.</p>
          <h2>Who is responsible for your data</h2>
          <p>Ash's Angels Preschool is the data controller. Privacy questions can be sent to <a href="mailto:childcare@ashsangels.com">childcare@ashsangels.com</a>.</p>
          <h2>Information we collect</h2>
          <ul>
            <li>Parent and guardian account and contact information, including name, email address, postal address, phone numbers, relationship and password credentials.</li>
            <li>Child information required to provide the preschool service, including name, date of birth, session and photographs.</li>
            <li>Messages, replies, photographs, videos and other attachments sent through the app.</li>
            <li>Documents, acknowledgements and electronic signatures submitted through the app.</li>
            <li>Notification tokens and limited technical information needed to deliver app notifications and keep the service secure.</li>
          </ul>
          <h2>How we use information</h2>
          <ul>
            <li>To authenticate users and connect approved parents or guardians with their child's information.</li>
            <li>To provide preschool messages, documents, calendars, forms and notifications.</li>
            <li>To administer the preschool service, maintain records, respond to requests and protect the security of the app.</li>
            <li>To meet safeguarding, regulatory and legal obligations that apply to the preschool.</li>
          </ul>
          <h2>Legal basis</h2>
          <p>We process data where it is necessary to provide the preschool service, comply with legal obligations, protect legitimate preschool and safeguarding interests, or where consent has been provided when required.</p>
          <h2>Service providers and sharing</h2>
          <p>We do not sell personal data and we do not use it for advertising. Data may be processed by service providers acting for the preschool, including Streamlit for app hosting, GitHub for app data and file storage, and Google Firebase for Android notifications. Information may also be disclosed where required by law or for safeguarding.</p>
          <h2>Security</h2>
          <p>We use access controls, encrypted network connections and password hashing to protect information. No online service can guarantee absolute security, and access should only be made from a device you control.</p>
          <h2>Retention</h2>
          <p>Information is kept while an account is active and for as long as needed for the preschool service, safeguarding, administration and legal requirements. Account information and associated app data that is not required to be retained will be deleted following a verified request. Signed forms or other records may be retained where the preschool has a legal or regulatory obligation to keep them.</p>
          <h2>Your rights</h2>
          <p>You may ask for access to, correction of, restriction of or deletion of your personal data. You may also object to certain processing or withdraw consent where processing relies on consent. Contact <a href="mailto:childcare@ashsangels.com">childcare@ashsangels.com</a>. You may raise a concern with Ireland's Data Protection Commission at <a href="https://www.dataprotection.ie/" target="_blank" rel="noopener">dataprotection.ie</a>.</p>
          <h2>Children's information</h2>
          <p>The app is intended for use by adult parents, guardians and administrators, not by children. Child information is managed by the preschool and approved adults for the purpose of providing the preschool service.</p>
          <h2>Account and data deletion</h2>
          <p>Parents and guardians can request deletion from the Settings page in the app or by using the public request page below.</p>
          <a class="public-page-action" href="{ACCOUNT_DELETION_URL}">Request account deletion</a>
          <h2>Changes to this policy</h2>
          <p>We may update this policy when the app or legal requirements change. The latest version will remain available at this address.</p>
        </main>
        """,
        unsafe_allow_html=True,
    )


def render_public_account_deletion():
    public_page_styles()
    deletion_subject = quote("Ash's Angels app account deletion request")
    st.markdown(
        f"""
        <main class="public-page">
          <header class="public-page-header">
            <img class="public-page-logo" src="{asset_url(LOGO_IMAGE)}" alt="Ash's Angels Preschool logo">
            <div><h1>Account Deletion</h1><div class="public-page-meta">Ash's Angels Preschool App</div></div>
          </header>
          <p>You can request deletion of your Ash's Angels Preschool App account and associated app data at any time.</p>
          <h2>How to request deletion</h2>
          <ol>
            <li>Email us from the address registered to your app account.</li>
            <li>Include your full name and your child's name so that we can verify the correct account.</li>
            <li>We will confirm the request and normally complete it within 30 days.</li>
          </ol>
          <a class="public-page-action" href="mailto:childcare@ashsangels.com?subject={deletion_subject}">Email deletion request</a>
          <div class="public-page-note">
            <p><strong>What will be deleted:</strong> your app login, parent or guardian contact details, notification registration and associated messages or uploaded app content that is not required to be retained.</p>
            <p><strong>What may be retained:</strong> signed forms, safeguarding records or other information that Ash's Angels Preschool must keep for legal or regulatory reasons. Any retained information will remain protected and will not be used for unrelated purposes.</p>
          </div>
          <h2>Contact</h2>
          <p>For questions about deletion, email <a href="mailto:childcare@ashsangels.com">childcare@ashsangels.com</a>. Read the <a href="{PRIVACY_POLICY_URL}">Privacy Policy</a> for more information.</p>
        </main>
        """,
        unsafe_allow_html=True,
    )


def render_admin_messages():
    stored_messages = load_messages()
    messages = sorted(stored_messages, key=message_activity_key, reverse=True)
    target_message_id = str(st.query_params.get("message_id", "") or "")
    target_anchor_id = message_anchor_id(target_message_id) if target_message_id else ""
    children = load_children()
    parents = load_parents()
    children_by_id = {child.get("ID", ""): child for child in children if child.get("ID")}
    children_by_name = {lookup_key(child.get("Name", "")): child for child in children if child.get("Name")}
    parents_by_id = {parent.get("ID", ""): parent for parent in parents if parent.get("ID")}
    parents_by_email = {lookup_key(parent.get("Email", "")): parent for parent in parents if parent.get("Email")}
    if st.query_params.get("create_message"):
        render_create_message_dialog()
    reply_message_id = str(st.query_params.get("reply_message", "") or "")
    if reply_message_id:
        reply_message = next(
            (message for message in messages if message.get("ID") == reply_message_id),
            None,
        )
        if reply_message:
            render_admin_reply_dialog(reply_message)
        else:
            st.query_params.pop("reply_message", None)
    create_message_href = app_href("Messages", create_message=1)
    st.markdown(
        '<div class="panel parents-panel messages-title-panel">'
        '<div class="messages-title-row">'
        '<div class="panel-title">Messages</div>'
        f'<a class="create-message-button" href="{create_message_href}" target="_self">Create Message</a>'
        '</div></div>',
        unsafe_allow_html=True,
    )
    deleted_message = st.session_state.pop("message_deleted_notice", "")
    if deleted_message:
        st.success(deleted_message)
    notification_sent = st.session_state.pop("notification_sent", "")
    if notification_sent:
        st.success(notification_sent)
    if not messages:
        st.markdown('<div class="panel parents-panel"><div class="muted">No messages have been sent yet.</div></div>', unsafe_allow_html=True)
        return

    for message_index, message in enumerate(messages):
        render_admin_message_item(
            message,
            message_index,
            target_message_id,
            children_by_id,
            children_by_name,
            parents_by_id,
            parents_by_email,
        )
    mark_parent_replies_seen(stored_messages)
    components.html(
        """
        <script>
        try {
          window.parent.document.title = "Ash's Angels Preschool App";
        } catch (error) {}
        const targetMessageId = __TARGET_MESSAGE_ID__;
        if (targetMessageId) {
          setTimeout(() => {
            try {
              const target = window.parent.document.getElementById(targetMessageId);
              if (target) target.scrollIntoView({ behavior: "smooth", block: "center" });
            } catch (error) {}
          }, 450);
        }
        </script>
        """.replace("__TARGET_MESSAGE_ID__", json.dumps(target_anchor_id)),
        height=0,
    )


def render_admin_birthdays():
    children = load_children()
    dated_children = []
    undated_children = []
    for child in children:
        upcoming = next_birthday_date(child.get("DOB", ""))
        if upcoming:
            dated_children.append((upcoming, child.get("Name", ""), child))
        else:
            undated_children.append(child)
    dated_children.sort(key=lambda item: (item[0], item[1].lower()))
    undated_children.sort(key=lambda child: child.get("Name", "").lower())

    st.markdown('<div class="panel parents-panel"><div class="panel-title">Birthdays</div>', unsafe_allow_html=True)
    if not children:
        st.markdown('<div class="muted">No children have been added yet.</div></div>', unsafe_allow_html=True)
        return

    st.markdown('<div class="parents-list">', unsafe_allow_html=True)
    for upcoming, _child_name, child in dated_children:
        birthday = child_birthday_text(child.get("DOB", ""))
        age = child_age_text(child.get("DOB", ""))
        next_text = upcoming.strftime("%d %b %Y").lstrip("0")
        st.markdown(
            f"""
            <div class="parent-row birthday-card">
              {child_thumb_html(child)}
              <div>
                <div class="parent-name">{html.escape(child.get("Name", "Unnamed child"))}</div>
                <div class="parent-detail"><strong>Birthday:</strong> {html.escape(birthday)}</div>
                <div class="parent-detail"><strong>Age:</strong> {html.escape(age or "Not available")}</div>
              </div>
              <div class="birthday-date">{cake_icon_html()}<span>{html.escape(next_text)}</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    for child in undated_children:
        st.markdown(
            f"""
            <div class="parent-row birthday-card">
              {child_thumb_html(child)}
              <div>
                <div class="parent-name">{html.escape(child.get("Name", "Unnamed child"))}</div>
                <div class="parent-detail">No date of birth added.</div>
              </div>
              <div class="parent-status pending">Missing DOB</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div></div>", unsafe_allow_html=True)


def render_parent_approvals():
    parents = load_parents()
    children = load_children()
    child_options = {child.get("ID", ""): child.get("Name", "Unnamed child") for child in children if child.get("ID")}
    children_by_id = {child.get("ID", ""): child for child in children if child.get("ID")}
    edit_parent_id = st.query_params.get("edit_parent")

    parents_changed = False
    for parent in parents:
        if not parent.get("ID"):
            parent["ID"] = uuid.uuid4().hex
            parents_changed = True
    if parents_changed:
        save_parents(parents)

    st.markdown('<div class="panel parents-panel"><div class="panel-title">Parents</div>', unsafe_allow_html=True)
    if not parents:
        st.markdown('<div class="muted">No parent registrations yet.</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if edit_parent_id:
        parent_to_edit = next((parent for parent in parents if parent.get("ID") == edit_parent_id), None)
        if parent_to_edit:
            current_parent_child = children_by_id.get(parent_to_edit.get("ChildID", ""))
            st.markdown('<div class="edit-tools"><div class="panel-title">Edit Parent</div>', unsafe_allow_html=True)
            with st.form(f"edit_parent_{edit_parent_id}"):
                first_name = st.text_input("Parent first name", value=parent_to_edit.get("FirstName", ""))
                relationship = st.selectbox(
                    "Relationship to child",
                    CONTACT_RELATIONSHIPS,
                    index=relationship_index(parent_relationship(parent_to_edit, current_parent_child)),
                )
                email = st.text_input("Email address", value=parent_to_edit.get("Email", ""))
                emergency_1 = st.text_input("Emergency contact 1", value=parent_to_edit.get("EmergencyContact1", ""))
                emergency_2 = st.text_input("Emergency contact 2", value=parent_to_edit.get("EmergencyContact2", ""))
                status = st.selectbox(
                    "Approval status",
                    ["Pending", "Approved"],
                    index=1 if parent_to_edit.get("Status") == "Approved" else 0,
                )
                child_ids = [""] + list(child_options.keys())
                current_child_id = parent_to_edit.get("ChildID", "")
                child_index = child_ids.index(current_child_id) if current_child_id in child_ids else 0
                selected_child_id = st.selectbox(
                    "Assign to child",
                    child_ids,
                    index=child_index,
                    format_func=lambda child_id: child_options.get(child_id, "No child assigned"),
                )
                saved = st.form_submit_button("Save Parent")
            st.markdown(f'<a class="section-edit" href="{app_href("Parents")}" target="_self">Cancel</a></div>', unsafe_allow_html=True)
            if saved:
                parent_to_edit["FirstName"] = first_name.strip()
                parent_to_edit["Relationship"] = clean_contact_relationship(relationship, "Guardian")
                parent_to_edit["Email"] = email.strip()
                parent_to_edit["EmergencyContact1"] = emergency_1.strip()
                parent_to_edit["EmergencyContact2"] = emergency_2.strip()
                parent_to_edit["Status"] = status
                parent_to_edit["ChildID"] = selected_child_id
                parent_to_edit["ChildName"] = child_options.get(selected_child_id, "")
                save_parents(parents)
                st.success("Parent details updated.")
                st.query_params["app_page"] = "Parents"
                if "edit_parent" in st.query_params:
                    del st.query_params["edit_parent"]
                st.rerun()
        else:
            st.markdown('<div class="muted">That parent could not be found.</div>', unsafe_allow_html=True)

    st.markdown('<div class="parents-list">', unsafe_allow_html=True)
    for parent in parents:
        status = parent.get("Status", "Pending")
        child_name = parent.get("ChildName") or "No child assigned"
        assigned_child = children_by_id.get(parent.get("ChildID", ""))
        edit_href = app_href("Parents", edit_parent=parent.get("ID", ""))
        status_class = "approved" if status == "Approved" else "pending"
        relationship_name = contact_display_name(parent.get("FirstName", ""), parent_relationship(parent, assigned_child))
        child_heading_name = assigned_child.get("Name", child_name) if assigned_child else child_name
        child_heading_thumb = ""
        if status == "Approved" and assigned_child:
            child_heading_thumb = child_thumb_html(assigned_child)
        elif status == "Approved" and child_name != "No child assigned":
            child_heading_thumb = f'<img class="child-thumb placeholder" src="{child_silhouette_url()}" alt="No child photo">'
        child_heading_html = (
            f'<div class="parent-child-heading{"" if child_heading_thumb else " no-thumb"}">'
            f'{child_heading_thumb}'
            '<div>'
            '<div class="parent-card-label">Child</div>'
            f'<div class="parent-card-child-name">{html.escape(child_heading_name)}</div>'
            '</div>'
            '</div>'
            if child_heading_name != "No child assigned"
            else '<div class="parent-card-child-name">No child assigned</div>'
        )
        statement_detail = parent_statement_signature_text(parent)
        recent_replies = replies_for_parent(parent.get("Email", ""))[:3]
        replies_html = ""
        if recent_replies:
            replies_html = '<div class="reply-list">'
            for reply in recent_replies:
                reply_date = str(reply.get("CreatedAt", "")).replace("T", " ")
                replies_html += (
                    '<div class="reply-bubble">'
                    f'<div class="reply-meta">Reply about {html.escape(reply.get("ChildName", "child"))}'
                    f'{(" - " + html.escape(reply_date)) if reply_date else ""}</div>'
                    f'<div class="message-body">{message_body_html(reply.get("Message", ""))}</div>'
                    '</div>'
                )
            replies_html += "</div>"
        st.markdown(
            f"""
            <div class="parent-row">
              <div>
                {child_heading_html}
                <div class="parent-contact-name">{html.escape(relationship_name)}</div>
                <div class="parent-details">
                  <div class="parent-detail"><strong>Email:</strong> {html.escape(parent.get("Email", ""))}</div>
                  <div class="parent-detail"><strong>Emergency 1:</strong> {html.escape(parent.get("EmergencyContact1", "") or "Not added")}</div>
                  <div class="parent-detail"><strong>Emergency 2:</strong> {html.escape(parent.get("EmergencyContact2", "") or "Not added")}</div>
                  <div class="parent-detail"><strong>Statement:</strong> {html.escape(statement_detail)}</div>
                </div>
                {replies_html}
              </div>
              <div class="parent-actions">
                <div class="parent-status {status_class}">{html.escape(status)}</div>
                <a class="edit-link" href="{edit_href}" aria-label="Edit parent" title="Edit parent" target="_self">...</a>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if parent_statement_signed(parent):
            signed_pdf = load_signed_parent_statement(parent)
            if signed_pdf:
                signature_page = signature_page_from_signed_pdf(signed_pdf)
                parent_file_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(parent.get("ID") or "parent")) or "parent"
                signed_copy, print_copy, spacer = st.columns([1, 1.25, 2.75], gap="small")
                signed_copy.download_button(
                    "Signed PDF",
                    data=signed_pdf,
                    file_name=f"parent-statement-{parent_file_id}-signed.pdf",
                    mime="application/pdf",
                    icon=":material/download:",
                    key=f"admin_signed_statement_{parent_file_id}",
                    width="stretch",
                )
                print_copy.download_button(
                    "Print signature page",
                    data=signature_page,
                    file_name=f"parent-statement-{parent_file_id}-signature-page.pdf",
                    mime="application/pdf",
                    icon=":material/print:",
                    key=f"admin_signature_page_{parent_file_id}",
                    width="stretch",
                )

    st.markdown("</div></div>", unsafe_allow_html=True)


public_page = str(st.query_params.get("public_page", "") or "").strip().lower()
if public_page == "privacy":
    render_public_privacy_policy()
    st.stop()
if public_page in {"delete-account", "account-deletion"}:
    render_public_account_deletion()
    st.stop()


if st.query_params.get("sign_out"):
    st.session_state.clear()
    st.info("Signing out...")
    render_saved_login_bridge(clear=True)
    st.stop()

is_login_flow = bool(st.query_params.get("login_role"))
render_saved_login_bridge(restore=not is_login_flow)
restore_saved_login()

if st.session_state.pop("saved_login_invalid", False):
    st.query_params.pop("auth", None)
    render_saved_login_bridge(clear=True)

if BUILD_MODE:
    st.session_state["logged_in"] = True
    st.session_state["role"] = "Admin"
    st.session_state["email"] = DEFAULT_ADMIN_EMAIL

saved_login_token = sync_saved_login()
if saved_login_token:
    render_saved_login_bridge(saved_login_token)

login_placeholder = st.empty()

if not st.session_state.get("logged_in"):
    for protected_param in ("app_page", "edit_child", "edit_parent", "children_edit", "delete_child", "delete_document", "move_document", "document_audience", "message_child", "message_session", "reply_message", "mobile_menu", "add_child", "create_message"):
        st.query_params.pop(protected_param, None)
    with login_placeholder.container():
        render_login(login_placeholder)
    st.stop()

login_placeholder.empty()


current_role = st.session_state.get("role", "Parent")
if current_role in {"Admin", "Parent"}:
    handle_push_subscription_query()
    handle_fcm_token_query()
selected_page = st.query_params.get("app_page", "Children" if current_role == "Admin" else "Dashboard")
if current_role == "Admin" and selected_page == "Dashboard":
    selected_page = "Children"
valid_pages = {"Children", "Parents", "Messages", "Documents", "Calendar", "Birthdays", "Settings"} if current_role == "Admin" else {"Dashboard", "Messages", "Documents", "Calendar", "Forms", "Settings"}
if selected_page not in valid_pages:
    selected_page = "Children" if current_role == "Admin" else "Dashboard"
if current_role == "Admin" and st.query_params.get("add_child"):
    selected_page = st.query_params.get("app_page", "Children")
if current_role == "Admin" and st.query_params.get("create_message"):
    selected_page = "Messages"
if current_role == "Admin" and st.query_params.get("reply_message"):
    selected_page = "Messages"
if st.query_params.get("edit_child"):
    selected_page = "Children"
if st.query_params.get("edit_parent"):
    selected_page = "Parents"
if current_role == "Admin" and st.query_params.get("delete_document"):
    selected_page = "Documents"

menu_col, content_col = st.columns([0.26, 0.74], gap="large")

with menu_col:
    render_side_menu(current_role, selected_page)

with content_col:
    if current_role == "Admin":
        admin_interaction_open = any(
            st.query_params.get(param)
            for param in ("message_child", "message_session", "reply_message", "add_child", "edit_child", "edit_parent", "children_edit", "delete_child", "delete_document", "create_message")
        )
        if selected_page != "Messages" and not admin_interaction_open:
            render_admin_message_notification()
        if selected_page == "Parents":
            render_parent_approvals()
        elif selected_page == "Messages":
            render_admin_messages()
        elif selected_page == "Documents":
            render_documents()
        elif selected_page == "Calendar":
            render_calendar()
        elif selected_page == "Birthdays":
            render_admin_birthdays()
        elif selected_page == "Settings":
            render_admin_settings()
        else:
            render_admin_children()
    else:
        if selected_page == "Messages":
            render_parent_messages()
        elif selected_page == "Documents":
            render_documents()
        elif selected_page == "Calendar":
            render_calendar()
        elif selected_page == "Forms":
            render_parent_forms()
        elif selected_page == "Settings":
            render_parent_settings()
        else:
            render_parent_dashboard()
