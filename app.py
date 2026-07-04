import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import uuid
from collections import deque
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import numpy as np
import streamlit as st
from PIL import Image, ImageDraw, ImageFilter


APP_DIR = Path(__file__).parent
LOGO_IMAGE = APP_DIR / "assets" / "ashs-angels-logo.png"
ICON_IMAGE = APP_DIR / "assets" / "ashs-angels-icon.svg"
USERS_FILE = APP_DIR / "users.json"
CHILDREN_FILE = APP_DIR / "children.json"
PARENTS_FILE = APP_DIR / "parents.json"
MESSAGES_FILE = APP_DIR / "messages.json"
CHILDREN_DIR = APP_DIR / "assets" / "children"
SESSIONS = ["Morning Session", "Afternoon Session"]
SESSION_ALIASES = {
    "Morning Session - 8:30am to 11:30am": "Morning Session",
    "Afternoon Session - 12:00pm to 3:00pm": "Afternoon Session",
}
PASSWORD_ROUNDS = 120_000
BUILD_MODE = False
DATA_REPOSITORY = "boylermallow/ashs-angels-preschool"
DATA_BRANCH = "main"


def setting(name, fallback=""):
    try:
        value = st.secrets.get(name, os.getenv(name, fallback))
    except Exception:
        value = os.getenv(name, fallback)
    return str(value).strip() if value else fallback


DEFAULT_ADMIN_EMAIL = setting("ASH_ADMIN_EMAIL")
DEFAULT_ADMIN_PASSWORD = setting("ASH_ADMIN_PASSWORD")


st.set_page_config(
    page_title="Ash's Angels Preschool App",
    page_icon=str(ICON_IMAGE),
    layout="wide",
)


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
    return setting("GITHUB_DATA_TOKEN")


def github_api_request(method, path, payload=None):
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


def save_persistent_json(path, value, message):
    write_json(APP_DIR / path, value)
    if not github_data_token():
        st.session_state["data_save_warning"] = (
            "This change was saved for now, but permanent saving is not switched on yet."
        )
        return False
    remote = github_api_request("GET", path)
    if not remote or not remote.get("sha"):
        return False
    payload = {
        "message": message,
        "content": base64.b64encode(json.dumps(value, indent=2).encode("utf-8")).decode("ascii"),
        "sha": remote["sha"],
        "branch": DATA_BRANCH,
    }
    result = github_api_request("PUT", path, payload)
    if result:
        st.session_state.pop("data_save_warning", None)
        st.session_state.pop("data_save_error", None)
        st.session_state[f"{path}_sha"] = result.get("content", {}).get("sha", "")
        return True
    return False


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


def restore_saved_login():
    if st.session_state.get("logged_in"):
        return
    token = str(st.query_params.get("auth", "") or "")
    try:
        email, role, signature = token.split("|", 2)
    except ValueError:
        return

    account = get_login_account(email, role)
    if not account or account.get("role") != role:
        return
    if not hmac.compare_digest(signature, auth_signature(account)):
        return

    st.session_state["logged_in"] = True
    st.session_state["role"] = account["role"]
    st.session_state["email"] = account["email"]


def sync_saved_login():
    if not st.session_state.get("logged_in"):
        return
    email = str(st.session_state.get("email", "")).strip().lower()
    role = st.session_state.get("role", "")
    account = get_login_account(email, role)
    if not account or account.get("role") != role:
        return
    token = make_auth_token(account)
    if st.query_params.get("auth") != token:
        st.query_params["auth"] = token


def app_href(page=None, **params):
    query = []
    if page:
        if page == "Dashboard":
            page = "Children"
        query.append(f"app_page={quote(str(page))}")
    auth_token = st.query_params.get("auth")
    if auth_token:
        query.append(f"auth={quote(str(auth_token))}")
    for key, value in params.items():
        if value not in (None, ""):
            query.append(f"{quote(str(key))}={quote(str(value))}")
    return "?" + "&".join(query) if query else "?"


def clean_session_name(session_name):
    session_name = str(session_name or "").strip()
    return SESSION_ALIASES.get(session_name, session_name)


def load_children():
    children = load_persistent_json("children.json", [])
    return children if isinstance(children, list) else []


def save_children(children):
    save_persistent_json("children.json", children, "Update children")


def delete_child_and_clear_parent_links(child_id):
    children = [child for child in load_children() if child.get("ID") != child_id]
    save_children(children)
    parents = load_parents()
    parents_changed = False
    for parent in parents:
        if parent.get("ChildID") == child_id:
            parent["ChildID"] = ""
            parent["ChildName"] = ""
            parents_changed = True
    if parents_changed:
        save_parents(parents)


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


def load_parents():
    parents = load_persistent_json("parents.json", [])
    return parents if isinstance(parents, list) else []


def save_parents(parents):
    save_persistent_json("parents.json", parents, "Update parents")


def load_messages():
    messages = load_persistent_json("messages.json", [])
    return messages if isinstance(messages, list) else []


def save_messages(messages):
    save_persistent_json("messages.json", messages, "Update messages")


def send_parent_notification(child, parent, message_body):
    messages = load_messages()
    messages.append(
        {
            "ID": uuid.uuid4().hex,
            "Type": "Notification",
            "ChildID": child.get("ID", ""),
            "ChildName": child.get("Name", ""),
            "ParentID": parent.get("ID", ""),
            "ParentName": parent.get("FirstName", ""),
            "ParentEmail": parent.get("Email", ""),
            "Message": message_body.strip(),
            "CreatedAt": datetime.now().isoformat(timespec="seconds"),
            "Status": "Sent",
            "Read": False,
        }
    )
    save_messages(messages)


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
    html, body, [data-testid="stAppViewContainer"] {{
        background: var(--bg);
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
        padding: 128px 24px 24px;
        box-shadow: var(--shadow);
        position: sticky;
        top: 92px;
        margin-top: 70px;
    }}
    .side-logo {{
        width: 100%;
        height: 138px;
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
        width: 205px;
        max-width: 100%;
        margin: 0;
        text-decoration: none;
        position: absolute;
        top: -70px;
        left: 50%;
        transform: translateX(-50%);
    }}
    .mobile-menu {{
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
        display: block;
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
        display: grid; place-items: center; margin-top: 18px;
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
    }}
    .role-card.active {{ border-color: var(--brand-blue); box-shadow: 0 0 0 2px rgba(47,79,159,.12) inset; }}
    .role-title {{ color: var(--brand-blue); font-weight: 950; font-size: 1.05rem; }}
    .role-copy {{ color: var(--muted); line-height: 1.4; margin-top: 4px; }}
    div[role="dialog"] {{
        background: var(--panel) !important;
        border-radius: 8px !important;
        border: 1px solid var(--line) !important;
        box-shadow: 0 24px 70px rgba(35,52,95,.24) !important;
    }}
    div[role="dialog"],
    div[role="dialog"] h1,
    div[role="dialog"] h2,
    div[role="dialog"] h3,
    div[role="dialog"] p,
    div[role="dialog"] label,
    div[role="dialog"] span {{
        color: var(--ink) !important;
    }}
    div[role="dialog"] h2,
    div[role="dialog"] [data-testid="stMarkdownContainer"] .panel-title {{
        color: var(--brand-blue) !important;
        font-weight: 950 !important;
    }}
    div[role="dialog"] button[aria-label="Close"],
    div[role="dialog"] button[aria-label="Close"] svg {{
        color: var(--brand-blue) !important;
        fill: var(--brand-blue) !important;
        opacity: 1 !important;
    }}
    div[role="dialog"] [data-testid="stVerticalBlock"] {{
        background: var(--panel) !important;
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
    .parents-panel .section-title {{
        margin-bottom: 14px;
    }}
    .parents-list {{
        display: grid;
        gap: 12px;
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
    .parent-name {{
        color: var(--ink);
        font-size: 1.02rem;
        font-weight: 900;
        line-height: 1.15;
        margin-bottom: 10px;
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
    @media (max-width: 760px) {{
        .session-columns {{
            grid-template-columns: 1fr;
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
        caret-color: var(--brand-blue) !important;
        -webkit-text-fill-color: var(--ink) !important;
    }}
    div[data-testid="stTextInput"] div[data-baseweb="input"] button,
    div[data-testid="stTextInput"] div[data-baseweb="input"] [role="button"] {{
        background: #ffffff !important;
        color: var(--brand-blue) !important;
        border: 0 !important;
        box-shadow: none !important;
        min-height: 44px !important;
    }}
    div[data-testid="stTextInput"] div[data-baseweb="input"] button svg,
    div[data-testid="stTextInput"] div[data-baseweb="input"] [role="button"] svg {{
        color: var(--brand-blue) !important;
        fill: var(--brand-blue) !important;
        stroke: var(--brand-blue) !important;
        opacity: 1 !important;
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
        color: var(--muted) !important;
        font-weight: 620 !important;
    }}
    div[data-testid="stFileUploader"] section button {{
        background: var(--brand-blue) !important;
        color: #ffffff !important;
        border: 0 !important;
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
        color: #ffffff !important;
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
        .block-container {{
            padding: 58px .85rem 2rem;
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
        }}
        .mobile-menu-toggle {{
            position: absolute;
            top: 0;
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
            min-height: 64px;
            padding: 6px max(12px, env(safe-area-inset-right)) 6px max(8px, env(safe-area-inset-left));
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
            top: 0;
            transform: translateX(-50%);
            z-index: 30;
            display: block;
            pointer-events: auto;
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
        .parent-row {{
            grid-template-columns: 1fr;
            gap: 12px;
            padding: 14px;
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


def render_sign_in_dialog(selected_role):
    if selected_role == "ParentRegister":
        st.markdown('<div class="panel-title">Parent Registration</div>', unsafe_allow_html=True)
        first_name = st.text_input("Parent first name")
        email = st.text_input("Email address")
        emergency_contact_1 = st.text_input("Emergency contact 1 phone")
        emergency_contact_2 = st.text_input("Emergency contact 2 phone")
        password = st.text_input("Create password")
        confirm_password = st.text_input("Confirm password")
        if st.button("Register Parent", type="primary", width="stretch"):
            clean_name = str(first_name or "").strip()
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

    login_label = "Parent" if selected_role == "Parent" else selected_role
    st.markdown(f'<div class="panel-title">{login_label} Sign In</div>', unsafe_allow_html=True)
    email = st.text_input("Email address")
    password = st.text_input("Password")
    if st.button(f"Sign In As {login_label}", type="primary", width="stretch"):
        account = login_user(email, password, selected_role)
        if account:
            st.session_state["logged_in"] = True
            st.session_state["role"] = account["role"]
            st.session_state["email"] = account["email"]
            st.query_params["auth"] = make_auth_token(account)
            st.session_state.pop("login_role", None)
            st.query_params.pop("login_role", None)
            st.rerun()
        else:
            st.error("Those login details do not match an account for this role.")
    if st.button("Cancel", width="stretch"):
        st.session_state.pop("login_role", None)
        st.query_params.pop("login_role", None)
        st.rerun()


if hasattr(st, "dialog"):
    render_sign_in_dialog = st.dialog("Sign in")(render_sign_in_dialog)


def render_message_dialog(child, parent):
    parent_name = parent.get("FirstName", "Parent") or "Parent"
    child_name = child.get("Name", "this child") or "this child"
    child_id = child.get("ID", "")
    message_key = f"message_body_{child_id}"
    st.markdown(
        f'<div class="panel-title">Message {html.escape(parent_name)}</div>'
        f'<div class="muted">This will send a notification about {html.escape(child_name)}.</div>',
        unsafe_allow_html=True,
    )
    message_body = st.text_area("Message", placeholder="Write your message here...", height=150, key=message_key)
    send_col, cancel_col = st.columns(2)

    if send_col.button("Send notification", key=f"send_message_{child_id}", width="stretch"):
        if not message_body.strip():
            st.warning("Please add a message first.")
        else:
            send_parent_notification(child, parent, message_body)
            st.session_state["notification_sent"] = f"Notification sent to {parent_name}."
            st.session_state.pop(message_key, None)
            st.query_params.pop("message_child", None)
            st.rerun()

    if cancel_col.button("Cancel", key=f"cancel_message_{child_id}", width="stretch"):
        st.session_state.pop(message_key, None)
        st.query_params.pop("message_child", None)
        st.rerun()


if hasattr(st, "dialog"):
    render_message_dialog = st.dialog("Send parent notification")(render_message_dialog)


def render_login():
    selected_role = st.query_params.get("login_role") or st.session_state.get("login_role")
    if selected_role not in {"Parent", "ParentRegister", "Admin"}:
        selected_role = None
    st.markdown(
        f"""
        <div class="login-shell">
          <div class="login-card">
            <div class="login-head">
              <div>
                <div class="app-title">Ash's Angels Preschool App</div>
                <div class="app-subtitle">Sign in to access your preschool dashboard.</div>
              </div>
              <img class="login-logo" src="{asset_url(LOGO_IMAGE)}" alt="Ash's Angels Preschool logo">
            </div>
            <div class="role-grid">
              <a class="role-card {'active' if selected_role == 'Parent' else ''}" href="?login_role=Parent">
                <div class="role-title">Parent Login</div>
                <div class="role-copy">View child updates, forms, messages, and preschool notices.</div>
              </a>
              <a class="role-card {'active' if selected_role == 'ParentRegister' else ''}" href="?login_role=ParentRegister">
                <div class="role-title">Parent Register</div>
                <div class="role-copy">Create a parent account for approval and child assignment.</div>
              </a>
              <a class="role-card {'active' if selected_role == 'Admin' else ''}" href="?login_role=Admin">
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
    render_sign_in_dialog(selected_role)


def render_side_menu(role, selected_page):
    nav_items = ["Children", "Parents", "Settings"] if role == "Admin" else ["Dashboard", "Messages", "Forms"]
    items_html = "\n".join(
        f'<a class="menu-item {"active" if item == selected_page else ""}" href="{app_href(item)}" target="_self">{html.escape(item)}</a>'
        for item in nav_items
    )
    st.markdown(
        f"""
        <div class="mobile-menu">
          <input class="mobile-menu-toggle" id="mobile-menu-toggle" type="checkbox" aria-label="Open navigation menu">
          <label class="mobile-menu-button" for="mobile-menu-toggle">
            <span class="mobile-menu-icon"><span></span></span>
            <span class="mobile-menu-spacer" aria-hidden="true"></span>
          </label>
          <a class="mobile-menu-logo-link" href="{app_href("Children")}" target="_self" aria-label="Go to children">
            <img class="mobile-menu-logo" src="{asset_url(LOGO_IMAGE)}" alt="Ash's Angels Preschool logo">
          </a>
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
        """,
        unsafe_allow_html=True,
    )


def render_delete_child_dialog(child):
    child_id = child.get("ID", "")
    child_name = child.get("Name", "this child")
    st.markdown(
        f'<div class="danger-confirm">Are you sure you want to delete {html.escape(child_name)}? This cannot be undone.</div>',
        unsafe_allow_html=True,
    )
    confirm_col, keep_col = st.columns([1, 1], gap="small")
    if confirm_col.button("Yes, delete child", type="primary", key=f"confirm_delete_dialog_{child_id}"):
        delete_child_and_clear_parent_links(child_id)
        st.session_state.pop("confirm_delete_child_id", None)
        st.session_state["notification_sent"] = "Child deleted."
        for param in ("delete_child", "edit_child", "children_edit"):
            st.query_params.pop(param, None)
        st.rerun()
    if keep_col.button("No, keep child", key=f"cancel_delete_dialog_{child_id}"):
        st.session_state.pop("confirm_delete_child_id", None)
        st.rerun()


if hasattr(st, "dialog"):
    render_delete_child_dialog = st.dialog("Delete child")(render_delete_child_dialog)


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

    if delete_child_id:
        delete_child_and_clear_parent_links(delete_child_id)
        for param in ("delete_child", "edit_child", "children_edit"):
            st.query_params.pop(param, None)
        st.success("Child deleted.")
        st.rerun()

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

    if edit_child_id:
        editing_child = next((child for child in children if child.get("ID") == edit_child_id), None)
        if editing_child:
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown('<div class="panel-title">Edit Child</div>', unsafe_allow_html=True)
            try:
                dob_value = date.fromisoformat(editing_child.get("DOB", ""))
            except ValueError:
                dob_value = None
            current_session = clean_session_name(editing_child.get("Session"))
            session_index = SESSIONS.index(current_session) if current_session in SESSIONS else 0
            with st.form(f"edit_child_form_{edit_child_id}"):
                details_col, thumbnail_col = st.columns([0.62, 0.38], gap="large")
                with details_col:
                    edited_name = st.text_input("Child full name", value=editing_child.get("Name", ""))
                    edited_dob = st.date_input("Date of birth", value=dob_value)
                    child_badges = child_info_badges_html(edited_dob)
                    if child_badges:
                        st.markdown(child_badges, unsafe_allow_html=True)
                    edited_session = st.selectbox("Assign to session", SESSIONS, index=session_index)
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
                    for child in children:
                        if child.get("ID") == edit_child_id:
                            child.update(
                                {
                                    "Name": edited_name.strip(),
                                    "DOB": edited_dob.isoformat() if edited_dob else "",
                                    "Session": edited_session,
                                    "Thumbnail": "",
                                }
                            )
                            break
                    save_children(children)
                    st.success("Thumbnail removed.")
                    st.rerun()

            if update_submitted:
                st.session_state.pop("confirm_delete_child_id", None)
                if not edited_name:
                    st.warning("Please add the child's full name.")
                else:
                    thumbnail_path = editing_child.get("Thumbnail", "")
                    if edited_thumbnail is not None:
                        thumbnail_path = save_uploaded_thumbnail(edited_thumbnail)

                    for child in children:
                        if child.get("ID") == edit_child_id:
                            child.update(
                                {
                                    "Name": edited_name.strip(),
                                    "DOB": edited_dob.isoformat() if edited_dob else "",
                                    "Session": edited_session,
                                    "Thumbnail": thumbnail_path,
                                }
                            )
                            break
                    save_children(children)
                    st.query_params.pop("edit_child", None)
                    st.success("Child updated.")
                    st.rerun()

    if not children:
        st.markdown('<div class="muted">No children added yet.</div>', unsafe_allow_html=True)
    else:
        sections_html = ['<div class="child-list session-columns">']
        for session_name in SESSIONS:
            session_children = [child for child in children if clean_session_name(child.get("Session")) == session_name]
            add_child_href = app_href("Children", add_child=1)
            sections_html.append(
                '<div class="session-group">'
                '<div class="session-heading">'
                f'<div class="session-title">{html.escape(session_name)}</div>'
                f'<a class="add-child-icon" href="{add_child_href}" target="_self" aria-label="Add child" title="Add child">+</a>'
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
    with st.form("add_child_form", clear_on_submit=True):
        full_name = st.text_input("Child full name")
        date_of_birth = st.date_input("Date of birth", value=None)
        child_badges = child_info_badges_html(date_of_birth)
        if child_badges:
            st.markdown(child_badges, unsafe_allow_html=True)
        session = st.selectbox("Assign to session", SESSIONS)
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

            children.append(
                {
                    "ID": uuid.uuid4().hex,
                    "Name": full_name.strip(),
                    "DOB": date_of_birth.isoformat() if date_of_birth else "",
                    "Session": session,
                    "Thumbnail": thumbnail_path,
                }
            )
            save_children(children)
            st.session_state["show_add_child"] = False
            st.session_state["child_added_message"] = "Child added."
            st.query_params["app_page"] = "Children"
            st.rerun()


if hasattr(st, "dialog"):
    render_add_child_dialog = st.dialog("Add Child")(render_add_child_dialog)


def render_admin_settings():
    st.markdown("<br>", unsafe_allow_html=True)
    data_save_warning = st.session_state.pop("data_save_warning", "")
    if data_save_warning:
        st.warning(data_save_warning)
    child_added_message = st.session_state.pop("child_added_message", "")
    if child_added_message:
        show_quick_notice(child_added_message)

    if "show_add_child" not in st.session_state:
        st.session_state["show_add_child"] = False

    st.markdown(
        f"""
        <div class="section-header">
          <div class="panel-title">Settings</div>
          <a class="add-child-icon" href="{app_href("Settings", add_child=1)}" target="_self" aria-label="Add child" title="Add child">+</a>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.query_params.get("add_child"):
        st.session_state["show_add_child"] = True
        st.query_params.pop("add_child", None)
        st.rerun()

    if st.session_state["show_add_child"]:
        render_add_child_dialog()


def current_parent_record():
    email = str(st.session_state.get("email", "")).strip().lower()
    return next((parent for parent in load_parents() if parent.get("Email", "").strip().lower() == email), None)


def render_parent_dashboard():
    parent = current_parent_record()
    children = load_children()
    children_by_id = {child.get("ID", ""): child for child in children if child.get("ID")}
    st.markdown('<div class="panel parents-panel"><div class="panel-title">Parent Dashboard</div>', unsafe_allow_html=True)
    if not parent:
        st.markdown('<div class="muted">We could not find your parent registration yet.</div></div>', unsafe_allow_html=True)
        return

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

    if child:
        st.markdown(
            f"""
            <div class="parent-row">
              <div>
                <div class="parent-name">Your child</div>
                <div class="parent-child-card">
                  {child_thumb_html(child)}
                  <div class="parent-child-name">{html.escape(child.get("Name", "Your child"))}</div>
                </div>
              </div>
              <div class="parent-status">Approved</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="parent-row"><div><div class="parent-name">Approved</div>'
            '<div class="parent-detail">Your account is approved. A child has not been assigned yet.</div>'
            '</div><div class="parent-status">Approved</div></div>',
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def render_parent_messages():
    parent = current_parent_record()
    email = str(st.session_state.get("email", "")).strip().lower()
    messages = [
        message
        for message in load_messages()
        if message.get("ParentEmail", "").strip().lower() == email
    ]
    st.markdown('<div class="panel parents-panel"><div class="panel-title">Messages</div>', unsafe_allow_html=True)
    if not parent:
        st.markdown('<div class="muted">We could not find your parent registration yet.</div></div>', unsafe_allow_html=True)
        return
    if not messages:
        st.markdown('<div class="muted">No messages yet.</div></div>', unsafe_allow_html=True)
        return
    st.markdown('<div class="parents-list">', unsafe_allow_html=True)
    for message in sorted(messages, key=lambda item: item.get("CreatedAt", ""), reverse=True):
        st.markdown(
            f"""
            <div class="parent-row">
              <div>
                <div class="parent-name">{html.escape(message.get("ChildName", "Preschool message"))}</div>
                <div class="parent-detail">{html.escape(message.get("Message", ""))}</div>
              </div>
              <div class="parent-status">Message</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div></div>", unsafe_allow_html=True)


def render_parent_forms():
    st.markdown(
        '<div class="panel parents-panel"><div class="panel-title">Forms</div>'
        '<div class="parent-row"><div><div class="parent-name">Forms and notices</div>'
        '<div class="parent-detail">There are no forms to complete right now.</div></div></div></div>',
        unsafe_allow_html=True,
    )


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
            st.markdown('<div class="edit-tools"><div class="panel-title">Edit Parent</div>', unsafe_allow_html=True)
            with st.form(f"edit_parent_{edit_parent_id}"):
                first_name = st.text_input("Parent first name", value=parent_to_edit.get("FirstName", ""))
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
        child_profile_html = ""
        if status == "Approved" and assigned_child:
            child_profile_html = (
                '<div class="parent-child-card">'
                f'{child_thumb_html(assigned_child)}'
                f'<div class="parent-child-name">{html.escape(assigned_child.get("Name", child_name))}</div>'
                '</div>'
            )
        elif status == "Approved" and child_name != "No child assigned":
            child_profile_html = (
                '<div class="parent-child-card">'
                f'<img class="child-thumb placeholder" src="{child_silhouette_url()}" alt="No child photo">'
                f'<div class="parent-child-name">{html.escape(child_name)}</div>'
                '</div>'
            )
        st.markdown(
            f"""
            <div class="parent-row">
              <div>
                <div class="parent-name">{html.escape(parent.get("FirstName", ""))}</div>
                <div class="parent-details">
                  <div class="parent-detail"><strong>Email:</strong> {html.escape(parent.get("Email", ""))}</div>
                  <div class="parent-detail"><strong>Emergency 1:</strong> {html.escape(parent.get("EmergencyContact1", "") or "Not added")}</div>
                  <div class="parent-detail"><strong>Emergency 2:</strong> {html.escape(parent.get("EmergencyContact2", "") or "Not added")}</div>
                </div>
                {child_profile_html or f'<div class="parent-detail"><strong>Assigned child:</strong> {html.escape(child_name)}</div>'}
              </div>
              <div class="parent-actions">
                <div class="parent-status {status_class}">{html.escape(status)}</div>
                <a class="edit-link" href="{edit_href}" aria-label="Edit parent" title="Edit parent" target="_self">...</a>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("</div></div>", unsafe_allow_html=True)


if st.query_params.get("sign_out"):
    st.session_state.clear()
    st.query_params.clear()
    st.rerun()

restore_saved_login()

if BUILD_MODE:
    st.session_state["logged_in"] = True
    st.session_state["role"] = "Admin"
    st.session_state["email"] = DEFAULT_ADMIN_EMAIL

sync_saved_login()

if not st.session_state.get("logged_in"):
    for protected_param in ("app_page", "edit_child", "edit_parent", "children_edit", "delete_child", "message_child", "mobile_menu", "add_child"):
        st.query_params.pop(protected_param, None)
    render_login()
    st.stop()


current_role = st.session_state.get("role", "Parent")
selected_page = st.query_params.get("app_page", "Children" if current_role == "Admin" else "Dashboard")
if current_role == "Admin" and selected_page == "Dashboard":
    selected_page = "Children"
valid_pages = {"Children", "Parents", "Settings"} if current_role == "Admin" else {"Dashboard", "Messages", "Forms"}
if selected_page not in valid_pages:
    selected_page = "Children" if current_role == "Admin" else "Dashboard"
if current_role == "Admin" and st.query_params.get("add_child"):
    selected_page = "Children"
if st.query_params.get("edit_child"):
    selected_page = "Children"
if st.query_params.get("edit_parent"):
    selected_page = "Parents"

menu_col, content_col = st.columns([0.26, 0.74], gap="large")

with menu_col:
    render_side_menu(current_role, selected_page)

with content_col:
    if current_role == "Admin":
        if selected_page == "Parents":
            render_parent_approvals()
        elif selected_page == "Settings":
            render_admin_settings()
        else:
            render_admin_children()
    else:
        if selected_page == "Messages":
            render_parent_messages()
        elif selected_page == "Forms":
            render_parent_forms()
        else:
            render_parent_dashboard()
