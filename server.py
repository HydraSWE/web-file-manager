"""
FastAPI Backend Server for Mobile-First Web File Manager.
Binds to 0.0.0.0, serves REST APIs, enables file streaming with Range requests,
and serves the single-page frontend.
"""
import os
import sys

# Ensure Windows console supports UTF-8 characters and emojis safely
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import json
import time
import secrets
import tempfile
import mimetypes
from typing import List, Optional
from pathlib import Path

try:
    from fastapi import FastAPI, HTTPException, Request, Response, Depends, UploadFile, File, Form, Query, Body, status, WebSocket, WebSocketDisconnect
    from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, HTMLResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
except ImportError as _err:
    print("\n" + "=" * 60)
    print(f" [HYDRA ERROR] Missing required dependency: {_err.name}")
    print(" Please install required dependencies by running:")
    print("     pip install --prefer-binary -r requirements.txt")
    print(" Or use the startup launcher:")
    print("     run.bat (Windows)  /  run.sh (Linux/macOS)")
    print("=" * 60 + "\n")
    sys.exit(1)
import urllib.parse
import json as _json

import file_ops
import network_utils
import qr_utils

# Ensure .env variables are loaded into os.environ
if hasattr(qr_utils, "_load_env_file"):
    qr_utils._load_env_file()

from execution.manager import init_execution_manager
from execution import terminal as terminal_mod

# ==========================================
# Security subsystem bootstrap
# ==========================================
from security.database import init_db as _init_security_db
from security.session_manager import (
    validate_session as _validate_device_session,
    extract_session_from_request as _extract_device_session_token,
    migrate_legacy_sessions,
)
from security.device_registry import (
    is_owner as _is_device_owner,
    is_trusted as _is_device_trusted,
)
from security.lockdown import is_locked_down as _is_locked_down
from security.permissions import Permission as _Permission
from security.router import security_router

# Base directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
STATIC_DIR = os.path.join(BASE_DIR, "static")

# Default Config
def load_config() -> dict:
    defaults = {
        "app_name": "Web File Manager",
        "app_icon": "/static/app_icon.png" if os.path.exists(os.path.join(STATIC_DIR, "app_icon.png")) else "",
        "port": 8080,
        "host": "0.0.0.0",
        "root_path": "",
        "pin": "",
        "allow_recycle_bin": True,
        "allow_permanent_delete": True,
        "show_hidden_files": False,
        "execution": {
            "enabled": True,
            "require_authentication": True,
            "require_confirmation": True,
            "allowed_extensions": [".bat", ".cmd", ".ps1", ".py", ".exe"],
            "default_script_mode": "terminal",
            "timeout_seconds": 300,
            "max_concurrent_processes": 3,
            "allow_desktop_execution": True,
            "allowed_roots": [],
            "powershell_override_policy": False
        }
    }

    # Auto-initialize config.json from config.example.json if missing
    if not os.path.exists(CONFIG_FILE):
        example_cfg = os.path.join(BASE_DIR, "config.example.json")
        if os.path.exists(example_cfg):
            try:
                import shutil
                shutil.copyfile(example_cfg, CONFIG_FILE)
            except Exception:
                pass
        else:
            try:
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(defaults, f, indent=2)
            except Exception:
                pass

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                defaults.update(data)
        except Exception:
            pass

    # Environment variables override config file
    if os.environ.get("APP_NAME"):
        defaults["app_name"] = os.environ["APP_NAME"].strip()
    if os.environ.get("APP_ICON"):
        defaults["app_icon"] = os.environ["APP_ICON"].strip()
    if os.environ.get("PORT"):
        try:
            defaults["port"] = int(os.environ["PORT"])
        except ValueError:
            pass

    return defaults

config = load_config()

SESSIONS_FILE = os.path.join(BASE_DIR, ".sessions.json")

def load_sessions() -> set:
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
        except Exception:
            pass
    return set()

def save_sessions(tokens: set):
    try:
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(tokens), f)
    except Exception:
        pass

SESSION_TOKENS = load_sessions()

# Initialise execution manager after config is loaded
_execution_manager = init_execution_manager(config)


app = FastAPI(title="Web File Manager", docs_url=None, redoc_url=None)

# ==========================================
# Security system init (must run before any request)
# ==========================================
_broker_proc = None

def _start_broker_if_needed():
    global _broker_proc
    if os.name != "nt":
        return
    broker_script = os.path.join(BASE_DIR, "local_broker", "broker.py")
    if not os.path.isfile(broker_script):
        return

    # Check if broker pipe is already accessible
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        GENERIC_READ = 0x80000000
        GENERIC_WRITE = 0x40000000
        OPEN_EXISTING = 3
        h = k32.CreateFileW(r"\\.\pipe\HydraAuthBroker", GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None)
        if h != -1 and h != 0xFFFFFFFFFFFFFFFF:
            k32.CloseHandle(h)
            return  # Already running
    except Exception:
        pass

    try:
        import subprocess
        _broker_proc = subprocess.Popen(
            [sys.executable, broker_script],
            cwd=BASE_DIR,
        )
        import logging as _logging
        _logging.getLogger(__name__).info("Windows Auth Broker auto-started (PID %s)", _broker_proc.pid)
        import time as _time
        _time.sleep(0.5)
    except Exception as e:
        import logging as _logging
        _logging.getLogger(__name__).warning("Could not auto-start Windows Auth Broker: %s", e)


@app.on_event("startup")
async def _startup_security():
    """Initialise security DB, auto-start Windows broker, and migrate legacy sessions on startup."""
    try:
        _init_security_db()
        # Auto-start local Windows Auth Broker on Windows if not already running
        _start_broker_if_needed()
        # Migrate legacy plaintext sessions + PIN (idempotent)
        migrate_legacy_sessions(SESSION_TOKENS, config)
    except Exception as _e:
        import logging as _logging
        _logging.getLogger(__name__).error("Security subsystem init failed: %s", _e)


@app.on_event("shutdown")
async def _shutdown_security():
    """Cleanly terminate child broker process on server shutdown."""
    global _broker_proc
    if _broker_proc:
        try:
            _broker_proc.terminate()
            _broker_proc.wait(timeout=2)
        except Exception:
            try:
                _broker_proc.kill()
            except Exception:
                pass
        _broker_proc = None

# Mount security router (all /api/security/*, /api/pairing/*, /api/devices/*, etc.)
app.include_router(security_router)

# Enable CORS for local cross-origin if needed
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2[0-9]|3[0-1])\.\d+\.\d+)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def is_allowed_ws_origin(origin: Optional[str], host: Optional[str]) -> bool:
    """Validate WebSocket Origin header against allowed local/LAN hosts."""
    if not origin:
        return True
    try:
        parsed = urllib.parse.urlparse(origin)
        hostname = (parsed.hostname or "").lower()
        netloc = parsed.netloc.lower()
        if host and netloc == host.lower():
            return True
        if hostname in ("localhost", "127.0.0.1"):
            return True
        if hostname.startswith("192.168.") or hostname.startswith("10."):
            return True
        if hostname.startswith("172."):
            parts = hostname.split(".")
            if len(parts) == 4 and parts[1].isdigit() and 16 <= int(parts[1]) <= 31:
                return True
        return False
    except Exception:
        return False


def verify_auth(request: Request):
    """
    Validates optional PIN authentication if configured.
    Supports X-Auth-Token, Authorization: Bearer, query param, or cookie.
    """
    pin_required = bool(config.get("pin", "").strip())
    if not pin_required:
        return True

    # Check header, Authorization bearer, query, or cookie
    token = (
        request.headers.get("X-Auth-Token")
        or request.query_params.get("token")
        or request.cookies.get("wfm_token")
    )
    if not token:
        auth_header = request.headers.get("Authorization", "").strip()
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()

    if token:
        dev_session = _validate_device_session(token)
        if dev_session:
            request.state.device_session = dev_session
            return True

    if token and token in SESSION_TOKENS:
        return True

    pin = request.headers.get("X-Auth-Pin") or request.query_params.get("pin")
    if pin and pin.strip() == config.get("pin", "").strip():
        return True

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


# ==========================================
# Authentication & System Endpoints
# ==========================================

@app.get("/api/config")
async def get_client_config():
    lan_ip = network_utils.get_lan_ip()
    port = config.get("port", 8080)
    mobile_url = f"http://{lan_ip}:{port}"
    return {
        "app_name": config.get("app_name", "Web File Manager"),
        "app_icon": config.get("app_icon", ""),
        "auth_required": bool(config.get("pin", "").strip()),
        "root_restricted": bool(config.get("root_path", "").strip()),
        "allow_recycle_bin": config.get("allow_recycle_bin", True),
        "allow_permanent_delete": config.get("allow_permanent_delete", True),
        "show_hidden_files": config.get("show_hidden_files", False),
        "lan_ip": lan_ip,
        "port": port,
        "mobile_url": mobile_url
    }


@app.post("/api/auth/login")
async def auth_login(payload: dict):
    pin = payload.get("pin", "").strip()
    configured_pin = config.get("pin", "").strip()

    if not configured_pin or pin == configured_pin:
        token = secrets.token_hex(16)
        SESSION_TOKENS.add(token)
        save_sessions(SESSION_TOKENS)
        response = JSONResponse({"success": True, "token": token})
        response.set_cookie(key="wfm_token", value=token, max_age=86400 * 7, httponly=False)
        return response

    raise HTTPException(status_code=401, detail="Invalid PIN")


@app.get("/api/network/qr")
async def get_qr_code():
    lan_ip = network_utils.get_lan_ip()
    port = config.get("port", 8080)
    mobile_url = f"http://{lan_ip}:{port}"
    svg = qr_utils.get_qr_svg(mobile_url)
    return {
        "mobile_url": mobile_url,
        "lan_ip": lan_ip,
        "svg": svg,
        "branded_qr_url": f"/api/network/qr-image?t={int(port)}"
    }


@app.get("/api/network/qr-image")
async def get_branded_qr_image():
    lan_ip = network_utils.get_lan_ip()
    port = config.get("port", 8080)
    mobile_url = f"http://{lan_ip}:{port}"
    try:
        png_bytes = qr_utils.generate_branded_qr_png(mobile_url)
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/drives")
async def get_drives(authorized: bool = Depends(verify_auth)):
    root = config.get("root_path", "").strip()
    if root:
        return [{
            "letter": "ROOT",
            "root": root,
            "label": f"Root ({os.path.basename(root) or root})",
            "total_gb": 0,
            "free_gb": 0
        }]
    return file_ops.get_windows_drives()


# ==========================================
# Filesystem Browsing & CRUD Endpoints
# ==========================================

@app.get("/api/fs/list")
async def list_files(
    path: str = Query(default=""),
    hidden: Optional[bool] = Query(default=None),
    authorized: bool = Depends(verify_auth)
):
    try:
        show_hidden = config.get("show_hidden_files", False) if hidden is None else hidden
        root_restrict = config.get("root_path", "")
        data = file_ops.list_directory(path, show_hidden=show_hidden, root_restriction=root_restrict)
        return data
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (FileNotFoundError, NotADirectoryError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list directory: {e}")


@app.get("/api/fs/raw")
async def get_raw_file(
    path: str,
    download: bool = Query(default=False),
    authorized: bool = Depends(verify_auth)
):
    """
    Streams file with HTTP Range support for audio/video streaming, image preview, or direct download.
    """
    try:
        safe_path = file_ops.sanitize_path(path, config.get("root_path", ""))
        if not os.path.isfile(safe_path):
            raise HTTPException(status_code=404, detail="File not found")

        mime, _ = mimetypes.guess_type(safe_path)
        mime = mime or "application/octet-stream"
        filename = os.path.basename(safe_path)

        # Starlette's FileResponse automatically handles HTTP Range headers for streaming media
        headers = {}
        if download:
            headers["Content-Disposition"] = f'attachment; filename="{filename}"'

        return FileResponse(
            path=safe_path,
            media_type=mime,
            filename=filename if download else None,
            headers=headers
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/fs/text")
async def get_text_file(path: str, authorized: bool = Depends(verify_auth)):
    try:
        content = file_ops.read_text_file(path, root_restriction=config.get("root_path", ""))
        return {"path": path, "filename": os.path.basename(path), "content": content}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=413, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/fs/text")
async def save_text_file(payload: dict, authorized: bool = Depends(verify_auth)):
    path = payload.get("path", "")
    content = payload.get("content", "")
    try:
        size = file_ops.write_text_file(path, content, root_restriction=config.get("root_path", ""))
        return {"success": True, "size": size}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/fs/file")
async def create_file(payload: dict, authorized: bool = Depends(verify_auth)):
    dir_path = payload.get("dir_path", "")
    name = payload.get("name", "")
    content = payload.get("content", "")
    try:
        new_path = file_ops.create_new_file(dir_path, name, content, root_restriction=config.get("root_path", ""))
        return {"success": True, "path": new_path}
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/fs/folder")
async def create_folder(payload: dict, authorized: bool = Depends(verify_auth)):
    dir_path = payload.get("dir_path", "")
    name = payload.get("name", "")
    try:
        new_path = file_ops.create_new_folder(dir_path, name, root_restriction=config.get("root_path", ""))
        return {"success": True, "path": new_path}
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/fs/rename")
async def rename_path(payload: dict, authorized: bool = Depends(verify_auth)):
    path = payload.get("path", "")
    new_name = payload.get("new_name", "")
    try:
        target = file_ops.rename_item(path, new_name, root_restriction=config.get("root_path", ""))
        return {"success": True, "new_path": target}
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/fs/delete")
async def delete_items(payload: dict, authorized: bool = Depends(verify_auth)):
    paths: List[str] = payload.get("paths", [])
    permanent: bool = payload.get("permanent", False)
    root_restrict = config.get("root_path", "")

    deleted = []
    errors = []
    for p in paths:
        try:
            file_ops.delete_item(p, permanent=permanent, root_restriction=root_restrict)
            deleted.append(p)
        except Exception as e:
            errors.append({"path": p, "error": str(e)})

    return {"success": len(errors) == 0, "deleted": deleted, "errors": errors}


@app.post("/api/fs/clipboard/paste")
async def paste_clipboard(payload: dict, authorized: bool = Depends(verify_auth)):
    sources: List[str] = payload.get("sources", [])
    dest_dir: str = payload.get("dest_dir", "")
    is_cut: bool = payload.get("is_cut", False)

    try:
        results = file_ops.copy_or_move(sources, dest_dir, is_cut=is_cut, root_restriction=config.get("root_path", ""))
        return {"success": True, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/fs/upload")
async def upload_files(
    dir_path: str = Form(...),
    files: List[UploadFile] = File(...),
    relative_paths: Optional[str] = Form(None),
    authorized: bool = Depends(verify_auth)
):
    dest = file_ops.sanitize_path(dir_path, config.get("root_path", ""))
    if not os.path.isdir(dest):
        raise HTTPException(status_code=400, detail="Invalid destination directory")

    rel_path_list = []
    if relative_paths:
        try:
            rel_path_list = json.loads(relative_paths)
        except Exception:
            rel_path_list = []

    saved_files = []
    for idx, file in enumerate(files):
        rel_path = None
        if idx < len(rel_path_list) and rel_path_list[idx]:
            rel_path = rel_path_list[idx]
        elif file.filename and ('/' in file.filename or '\\' in file.filename):
            rel_path = file.filename

        if rel_path:
            clean_rel = os.path.normpath(rel_path.replace('\\', '/')).lstrip('/\\')
            parts = [p for p in clean_rel.split(os.sep) if p and p != '..']
            if not parts:
                parts = ["upload.bin"]
            target_subfolder = os.path.join(dest, *parts[:-1]) if len(parts) > 1 else dest
            os.makedirs(target_subfolder, exist_ok=True)
            filename = parts[-1]
            save_path = os.path.join(target_subfolder, filename)
        else:
            filename = file.filename or "upload.bin"
            filename = os.path.basename(filename)
            save_path = os.path.join(dest, filename)

        counter = 1
        name_root, name_ext = os.path.splitext(filename)
        parent_dir = os.path.dirname(save_path)
        while os.path.exists(save_path):
            save_path = os.path.join(parent_dir, f"{name_root} ({counter}){name_ext}")
            counter += 1

        with open(save_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):  # 1MB chunk
                buffer.write(chunk)
        saved_files.append(save_path)

    return {"success": True, "count": len(saved_files), "saved": saved_files}


@app.post("/api/fs/download-zip")
async def download_zip(payload: dict, authorized: bool = Depends(verify_auth)):
    paths: List[str] = payload.get("paths", [])
    if not paths:
        raise HTTPException(status_code=400, detail="No items selected for download")

    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    temp_zip.close()

    try:
        file_ops.create_zip_archive(paths, temp_zip.name, root_restriction=config.get("root_path", ""))
        archive_name = "archive.zip"
        if len(paths) == 1:
            base = os.path.basename(paths[0].rstrip('\\/'))
            archive_name = f"{base}.zip"
        else:
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_name = f"hydra_bundle_{timestamp}.zip"

        from starlette.background import BackgroundTask
        task = BackgroundTask(os.remove, temp_zip.name)
        return FileResponse(
            path=temp_zip.name,
            filename=archive_name,
            media_type="application/zip",
            background=task
        )
    except Exception as e:
        if os.path.exists(temp_zip.name):
            os.remove(temp_zip.name)
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# Favorites / Pinned Storage
# ==========================================

FAVORITES_FILE = os.path.join(BASE_DIR, "favorites.json")

def load_favorites() -> list:
    if os.path.exists(FAVORITES_FILE):
        try:
            with open(FAVORITES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            return []
    return []

def save_favorites(favs: list):
    try:
        with open(FAVORITES_FILE, "w", encoding="utf-8") as f:
            json.dump(favs, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving favorites: {e}")

def enrich_favorites(favs: list) -> list:
    for f in favs:
        if f.get("is_dir"):
            try:
                f["has_custom_icon"] = bool(file_ops.get_folder_custom_icon(f.get("path", "")))
            except Exception:
                f["has_custom_icon"] = False
        else:
            f["has_custom_icon"] = False
    return favs

@app.get("/api/favorites")
async def get_favorites(authorized: bool = Depends(verify_auth)):
    favs = load_favorites()
    return {"favorites": enrich_favorites(favs)}


# ==========================================
# Folder Custom Icon / Logo Endpoints
# ==========================================

@app.get("/api/fs/folder-icon")
async def get_folder_icon(path: str, authorized: bool = Depends(verify_auth)):
    """
    Returns custom folder logo / icon (converted to PNG if ICO).
    """
    safe_path = file_ops.sanitize_path(path, config.get("root_path", ""))
    if not os.path.isdir(safe_path):
        raise HTTPException(status_code=404, detail="Folder not found")

    icon_path = file_ops.get_folder_custom_icon(safe_path)
    if not icon_path or not os.path.isfile(icon_path):
        raise HTTPException(status_code=404, detail="No custom icon found for folder")

    ext = os.path.splitext(icon_path)[1].lower()
    if ext == ".ico":
        try:
            import io
            from PIL import Image
            img = Image.open(icon_path)
            if hasattr(img, "n_frames") and img.n_frames > 1:
                largest_img = None
                max_area = 0
                for frame in range(img.n_frames):
                    img.seek(frame)
                    area = img.size[0] * img.size[1]
                    if area > max_area:
                        max_area = area
                        largest_img = img.copy()
                img = largest_img or img
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return Response(content=buf.getvalue(), media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to decode icon: {e}")
    else:
        mime, _ = mimetypes.guess_type(icon_path)
        return FileResponse(icon_path, media_type=mime or "image/png", headers={"Cache-Control": "public, max-age=3600"})


@app.post("/api/fs/folder-icon/set")
async def set_folder_icon(
    path: str = Form(...),
    file: UploadFile = File(...),
    authorized: bool = Depends(verify_auth)
):
    """
    Upload and apply a custom logo/icon to a folder (updates Windows desktop.ini & Explorer).
    """
    safe_path = file_ops.sanitize_path(path, config.get("root_path", ""))
    if not os.path.isdir(safe_path):
        raise HTTPException(status_code=404, detail="Folder not found")

    try:
        content = await file.read()
        file_ops.set_folder_custom_icon(safe_path, content)
        return {"success": True, "path": safe_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set folder icon: {e}")


@app.post("/api/fs/folder-icon/reset")
async def reset_folder_icon(
    path: str = Form(...),
    authorized: bool = Depends(verify_auth)
):
    """
    Reset folder logo back to default Windows folder icon.
    """
    safe_path = file_ops.sanitize_path(path, config.get("root_path", ""))
    if not os.path.isdir(safe_path):
        raise HTTPException(status_code=404, detail="Folder not found")

    file_ops.reset_folder_custom_icon(safe_path)
    return {"success": True, "path": safe_path}

@app.post("/api/favorites/toggle")
async def toggle_favorite(payload: dict, authorized: bool = Depends(verify_auth)):
    raw_path = payload.get("path", "").strip()
    if not raw_path:
        raise HTTPException(status_code=400, detail="Path is required")
        
    target_path = os.path.normpath(raw_path)
    favs = load_favorites()
    existing_idx = next((i for i, f in enumerate(favs) if os.path.normcase(os.path.normpath(f.get("path", ""))) == os.path.normcase(target_path)), -1)
    
    if existing_idx >= 0:
        favs.pop(existing_idx)
        pinned = False
    else:
        name = payload.get("name") or os.path.basename(target_path) or target_path
        is_dir = payload.get("is_dir")
        if is_dir is None:
            is_dir = os.path.isdir(target_path)
        favs.append({
            "path": target_path,
            "name": name,
            "is_dir": bool(is_dir),
            "pinned_at": int(time.time())
        })
        pinned = True
        
    save_favorites(favs)
    return {"pinned": pinned, "favorites": enrich_favorites(favs)}

@app.post("/api/favorites/batch")
async def batch_favorites(payload: dict, authorized: bool = Depends(verify_auth)):
    items = payload.get("items", [])
    action = payload.get("action", "pin")
    favs = load_favorites()
    
    for it in items:
        raw_path = it.get("path", "").strip()
        if not raw_path:
            continue
        target_path = os.path.normpath(raw_path)
        existing_idx = next((i for i, f in enumerate(favs) if os.path.normcase(os.path.normpath(f.get("path", ""))) == os.path.normcase(target_path)), -1)
        
        if action == "unpin" and existing_idx >= 0:
            favs.pop(existing_idx)
        elif action == "pin" and existing_idx < 0:
            favs.append({
                "path": target_path,
                "name": it.get("name") or os.path.basename(target_path) or target_path,
                "is_dir": bool(it.get("is_dir") if it.get("is_dir") is not None else os.path.isdir(target_path)),
                "pinned_at": int(time.time())
            })
            
    save_favorites(favs)
    return {"favorites": enrich_favorites(favs)}

@app.post("/api/favorites/clear")
async def clear_favorites(authorized: bool = Depends(verify_auth)):
    save_favorites([])
    return {"success": True, "favorites": []}




# ==========================================
# Execution Engine Endpoints
# ==========================================

def _get_exec_token(request: Request) -> str:
    """
    Extract auth token for execution endpoints.
    Execution ALWAYS requires a session token — never falls through on empty PIN.
    This is stricter than verify_auth() which bypasses auth when PIN is unconfigured.
    """
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    token = (
        request.headers.get("X-Auth-Token")
        or request.query_params.get("token")
        or request.cookies.get("wfm_token")
        or ""
    )
    return token.strip()


def verify_exec_auth(request: Request) -> str:
    """
    Dependency: validate that the request has a valid session token for execution.
    Returns the token string on success (used as process ownership key).
    Raises 401 if not authenticated.
    Raises 403 if execution is disabled or security lockdown is active.
    """
    # Check security lockdown first
    if _is_locked_down():
        raise HTTPException(status_code=503, detail="Security lockdown is active — execution blocked")

    if not _execution_manager.enabled:
        raise HTTPException(status_code=403, detail="File execution is disabled")

    if _execution_manager.require_authentication:
        token = _get_exec_token(request)
        if not token:
            raise HTTPException(status_code=401, detail="Execution requires authentication")

        dev_session = _validate_device_session(token)
        if dev_session:
            perms = dev_session.get("permissions", [])
            if _Permission.EXECUTION_SCRIPT not in perms and _Permission.EXECUTION_DESKTOP not in perms:
                raise HTTPException(status_code=403, detail="Device lacks execution permissions")
            request.state.device_session = dev_session
            return token

        # If a PIN is configured, the token must be in SESSION_TOKENS
        pin_required = bool(config.get("pin", "").strip())
        if pin_required and token not in SESSION_TOKENS:
            raise HTTPException(status_code=401, detail="Invalid or expired session token")

        # If no PIN is configured but require_authentication is True,
        # we still require a token — but any token issued by /api/auth/login is valid.
        # The user must have logged in (even with an empty PIN) to get a token.
        if not pin_required and token not in SESSION_TOKENS:
            raise HTTPException(status_code=401, detail="Execution requires a valid session — please log in first")

        return token
    else:
        # require_authentication is False (admin explicitly disabled it)
        token = _get_exec_token(request)
        return token or "anon"


@app.get("/api/execution/config")
async def get_execution_config():
    """
    Return the public execution configuration (enabled state, allowed extensions, etc.).
    Does not require auth — the frontend needs this to decide whether to show the Run button.
    """
    return _execution_manager.get_config_dict()


@app.post("/api/execution/start")
async def start_execution(
    payload: dict,
    token: str = Depends(verify_exec_auth),
):
    """
    Start execution of a script or executable.

    Request body:
      {
        "path": "<absolute file path>",
        "mode": "terminal" | "desktop"
      }

    Returns the execution record with process_id for WebSocket connection.
    """
    file_path = payload.get("path", "").strip()
    mode = payload.get("mode", "terminal").strip()

    if not file_path:
        raise HTTPException(status_code=400, detail="path is required")
    if mode not in ("terminal", "desktop"):
        raise HTTPException(status_code=400, detail="mode must be 'terminal' or 'desktop'")

    try:
        root_restriction = config.get("root_path", "")
        record = await _execution_manager.start_execution(
            file_path=file_path,
            mode=mode,
            owner_token=token,
            root_restriction=root_restriction,
        )
        return record
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execution error: {type(e).__name__}")


@app.get("/api/execution/processes")
async def list_processes(token: str = Depends(verify_exec_auth)):
    """List all active (running) execution jobs for the current user."""
    records = await _execution_manager.get_active_processes(token)
    return {"processes": records}


@app.get("/api/execution/process/{process_id}")
async def get_process(process_id: str, token: str = Depends(verify_exec_auth)):
    """Get the status of a specific execution job."""
    record = await _execution_manager.get_process_status(process_id, token)
    if not record:
        raise HTTPException(status_code=404, detail="Process not found or access denied")
    return record


@app.post("/api/execution/stop/{process_id}")
async def stop_process(process_id: str, token: str = Depends(verify_exec_auth)):
    """Terminate a running execution job. Only the owner can stop their own process."""
    success = await _execution_manager.stop_process(process_id, token)
    if not success:
        raise HTTPException(status_code=404, detail="Process not found or access denied")
    return {"success": True, "process_id": process_id}


@app.post("/api/execution/stdin/{process_id}")
async def send_process_stdin(
    process_id: str,
    payload: dict = Body(...),
    token: str = Depends(verify_exec_auth),
):
    """Send standard input (stdin) to an active terminal process."""
    input_text = payload.get("input", "")
    success = await _execution_manager.send_stdin(process_id, token, input_text)
    if not success:
        raise HTTPException(status_code=400, detail="Process not running or stdin not writable")
    return {"success": True, "process_id": process_id}


@app.get("/api/execution/history")
async def get_execution_history(token: str = Depends(verify_exec_auth)):
    """Return completed/failed execution history for the current user."""
    records = await _execution_manager.get_history(token)
    return {"history": records}


@app.websocket("/ws/execution/{process_id}")
async def execution_websocket(websocket: WebSocket, process_id: str):
    """
    WebSocket endpoint for real-time terminal output streaming.

    Authentication:
      Send token as query parameter: /ws/execution/{id}?token=<token>
      This is necessary because WebSocket clients cannot set custom headers in browsers.

    Protocol:
      Server → Client messages (JSON):
        {"type": "output", "stream": "stdout"|"stderr", "data": "<text>", "t": <timestamp>}
        {"type": "status", "status": "<status>", "exit_code": <int>|null}
        {"type": "error", "message": "<safe error message>"}
        {"type": "history", "lines": [...]}   # initial replay if process already has output

    The connection is closed by the server when the process completes.
    """
    # 1. Validate Origin header
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if origin and not is_allowed_ws_origin(origin, host):
        logger.warning("Rejected WebSocket connection from unauthorized origin: %s", origin)
        await websocket.close(code=4003, reason="Forbidden: Cross-origin WebSocket access denied")
        return

    # 2. Verify execution enabled
    if not _execution_manager.enabled:
        await websocket.close(code=4003, reason="File execution is disabled")
        return

    # 3. Authenticate token
    token = websocket.query_params.get("token", "").strip()
    if not token:
        token = websocket.cookies.get("wfm_token", "").strip()

    if _is_locked_down():
        await websocket.close(code=4003, reason="Security lockdown is active")
        return

    if _execution_manager.require_authentication:
        if not token:
            await websocket.close(code=4001, reason="Authentication required")
            return
        is_valid_token = (token in SESSION_TOKENS) or (_validate_device_session(token) is not None)
        if not is_valid_token:
            await websocket.close(code=4001, reason="Invalid or expired session token")
            return
    else:
        if not token:
            token = "anon"

    # 4. Strict process ownership verification BEFORE accepting
    record = await _execution_manager.pm.get(process_id)
    if not record:
        hist = await _execution_manager.pm.get_history()
        matching = [r for r in hist if r.process_id == process_id]
        if matching:
            record = matching[0]

    if not record:
        await websocket.close(code=4004, reason="Process not found")
        return

    # Reject connection immediately if ownership verification fails
    # NEVER use SESSION_TOKENS membership as a substitute for process ownership!
    if record.owner_token != token:
        logger.warning("Rejected WebSocket access to process %s: token mismatch", process_id)
        await websocket.close(code=4003, reason="Access denied: process belongs to another session")
        return

    # 5. All security checks passed — accept connection
    await websocket.accept()

    try:
        record_dict = record.to_dict()

        # Get the output buffer for this process (terminal mode only)
        buf = terminal_mod.get_buffer(process_id)

        if buf is None:
            # Process may already be complete or was desktop mode
            if record_dict:
                await websocket.send_json({
                    "type": "status",
                    "status": record_dict.get("status", "unknown"),
                    "exit_code": record_dict.get("exit_code"),
                })
            else:
                await websocket.send_json({"type": "error", "message": "No output stream available"})
            await websocket.close()
            return

        # Replay existing output first (in case client connected after process started)
        existing = await buf.get_all()
        if existing:
            await websocket.send_json({"type": "history", "lines": existing})

        # Stream new output until process completes or client disconnects
        start_idx = len(existing)
        async for line_data in buf.iterate_from(start_idx):
            try:
                await websocket.send_json({
                    "type": "output",
                    "stream": line_data["s"],
                    "data": line_data["d"],
                    "t": line_data["t"],
                })
            except WebSocketDisconnect:
                break
            except Exception:
                break

        # Send final status
        try:
            final_record = await _execution_manager.get_process_status(process_id, token)
            if not final_record:
                # Check history
                history = await _execution_manager.get_history(token)
                matching = [r for r in history if r.get("process_id") == process_id]
                final_record = matching[0] if matching else None

            if final_record:
                await websocket.send_json({
                    "type": "status",
                    "status": final_record.get("status", "unknown"),
                    "exit_code": final_record.get("exit_code"),
                    "duration_sec": final_record.get("duration_sec"),
                })
        except Exception:
            pass

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": f"Stream error: {type(e).__name__}"})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ==========================================
# Frontend SPA & Static Mounts
# ==========================================

os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def serve_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return HTMLResponse("<h3>Web File Manager: index.html not found.</h3>", status_code=404)


# ==========================================
# Main Execution Entrypoint
# ==========================================

if __name__ == "__main__":
    cfg = load_config()
    host = cfg.get("host", "0.0.0.0")
    port = int(cfg.get("port", 8080))
    app_name = cfg.get("app_name", "Web File Manager")
    lan_ip = network_utils.get_lan_ip()

    print("=" * 64)
    print(f"  🚀 {app_name} Server")
    print(f"  💻 PC Local Access:    http://127.0.0.1:{port}")
    print(f"  📱 Mobile / Wi-Fi URL: http://{lan_ip}:{port}")
    print(f"  🔒 Auth PIN Protection: {'Enabled' if cfg.get('pin') else 'Disabled'}")
    print("=" * 64)

    # Print ASCII QR code directly into terminal
    qr_utils.print_terminal_qr(f"http://{lan_ip}:{port}")

    uvicorn.run("server:app", host=host, port=port, reload=False)

