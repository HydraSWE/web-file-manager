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
import secrets
import tempfile
import mimetypes
from typing import List, Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response, Depends, UploadFile, File, Form, Query, status
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

import file_ops
import network_utils
import qr_utils

# Base directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
STATIC_DIR = os.path.join(BASE_DIR, "static")

# Default Config
def load_config() -> dict:
    defaults = {
        "app_name": "Web File Manager",
        "app_icon": "",
        "port": 8080,
        "host": "0.0.0.0",
        "root_path": "",
        "pin": "",
        "allow_recycle_bin": True,
        "allow_permanent_delete": True,
        "show_hidden_files": False
    }
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
SESSION_TOKENS = set()

app = FastAPI(title="Web File Manager", docs_url=None, redoc_url=None)

# Enable CORS for local cross-origin if needed
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def verify_auth(request: Request):
    """
    Validates optional PIN authentication if configured.
    """
    pin_required = bool(config.get("pin", "").strip())
    if not pin_required:
        return True

    # Check header, query, or cookie
    token = request.headers.get("X-Auth-Token") or request.query_params.get("token") or request.cookies.get("wfm_token")
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
    return {"mobile_url": mobile_url, "lan_ip": lan_ip, "svg": svg}


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
    authorized: bool = Depends(verify_auth)
):
    dest = file_ops.sanitize_path(dir_path, config.get("root_path", ""))
    if not os.path.isdir(dest):
        raise HTTPException(status_code=400, detail="Invalid destination directory")

    saved_files = []
    for file in files:
        filename = file.filename or "upload.bin"
        filename = os.path.basename(filename)
        save_path = os.path.join(dest, filename)

        counter = 1
        name_root, name_ext = os.path.splitext(filename)
        while os.path.exists(save_path):
            save_path = os.path.join(dest, f"{name_root} ({counter}){name_ext}")
            counter += 1

        with open(save_path, "wb") as buffer:
            shutil_copy = True
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

        return FileResponse(
            path=temp_zip.name,
            filename=archive_name,
            media_type="application/zip",
            background=None
        )
    except Exception as e:
        if os.path.exists(temp_zip.name):
            os.remove(temp_zip.name)
        raise HTTPException(status_code=500, detail=str(e))


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
