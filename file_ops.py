"""
File operations engine for Windows: directory traversal, CRUD, clipboard actions,
Recycle Bin integration, and archive creation.
"""
import os
import shutil
import stat
import string
import ctypes
from ctypes import wintypes
from typing import List, Dict, Any, Optional
import zipfile
import mimetypes

# Windows Shell API definitions for Recycle Bin
class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ('hwnd', wintypes.HWND),
        ('wFunc', wintypes.UINT),
        ('pFrom', wintypes.LPCWSTR),
        ('pTo', wintypes.LPCWSTR),
        ('fFlags', wintypes.WORD),
        ('fAnyOperationsAborted', wintypes.BOOL),
        ('hNameMappings', wintypes.LPVOID),
        ('lpszProgressTitle', wintypes.LPCWSTR),
    ]

FO_DELETE = 3
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_SILENT = 0x0004
FOF_NOERRORUI = 0x0400


def get_windows_drives() -> List[Dict[str, Any]]:
    """
    Enumerates all active logical drives on Windows with labels and disk usage.
    """
    drives = []
    if os.name != 'nt':
        return [{"letter": "/", "root": "/", "label": "Root", "total_gb": 0, "free_gb": 0}]

    kernel32 = ctypes.windll.kernel32
    vol_buf = ctypes.create_unicode_buffer(1024)
    fs_buf = ctypes.create_unicode_buffer(1024)

    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if os.path.exists(root):
            label = ""
            try:
                if kernel32.GetVolumeInformationW(root, vol_buf, 1024, None, None, None, fs_buf, 1024):
                    label = vol_buf.value
            except Exception:
                pass

            total_gb = 0.0
            free_gb = 0.0
            try:
                usage = shutil.disk_usage(root)
                total_gb = round(usage.total / (1024**3), 1)
                free_gb = round(usage.free / (1024**3), 1)
            except Exception:
                pass

            drives.append({
                "letter": f"{letter}:",
                "root": root,
                "label": label or f"Local Disk ({letter}:)",
                "total_gb": total_gb,
                "free_gb": free_gb
            })

    return drives


def sanitize_path(target_path: str, root_restriction: str = "") -> str:
    """
    Normalizes and canonicalizes paths, preventing path traversal attacks.
    If root_restriction is configured, enforces boundary checking.
    """
    if not target_path or target_path.strip() == "":
        # Default to first available drive or user profile
        drives = get_windows_drives()
        return drives[0]["root"] if drives else os.path.abspath(os.sep)

    clean_path = os.path.normpath(target_path)
    # Ensure Windows drive path like 'C:' has trailing slash
    if len(clean_path) == 2 and clean_path[1] == ':':
        clean_path += '\\'

    abs_path = os.path.realpath(clean_path)

    if root_restriction and root_restriction.strip():
        canonical_root = os.path.realpath(root_restriction)
        if not (abs_path == canonical_root or abs_path.startswith(canonical_root + os.sep)):
            raise PermissionError(f"Access denied: path escapes designated root '{root_restriction}'")

    return abs_path


def is_hidden_file(entry: os.DirEntry) -> bool:
    """
    Checks if a file/folder is hidden on Windows or Unix.
    """
    if entry.name.startswith('.'):
        return True
    if os.name == 'nt':
        try:
            return bool(entry.stat().st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN)
        except Exception:
            return False
    return False


def get_item_category(name: str, is_dir: bool) -> str:
    """
    Classifies file types into high-level categories for UI badges and icons.
    """
    if is_dir:
        return "folder"
    ext = os.path.splitext(name)[1].lower()
    if ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico", ".tiff"]:
        return "image"
    if ext in [".mp4", ".webm", ".mkv", ".mov", ".avi", ".wmv", ".flv"]:
        return "video"
    if ext in [".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac", ".wma"]:
        return "audio"
    if ext in [".pdf"]:
        return "pdf"
    if ext in [".zip", ".tar", ".gz", ".rar", ".7z", ".bz2", ".xz"]:
        return "archive"
    if ext in [".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json", ".xml", ".yaml", ".yml",
               ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".java", ".php", ".sh", ".bat", ".ps1", ".sql"]:
        return "code"
    if ext in [".txt", ".md", ".log", ".rtf", ".csv", ".tsv"]:
        return "text"
    if ext in [".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"]:
        return "document"
    if ext in [".exe", ".msi", ".dll", ".bin"]:
        return "executable"
    return "file"


def list_directory(dir_path: str, show_hidden: bool = False, root_restriction: str = "") -> Dict[str, Any]:
    """
    Scans a directory and returns its metadata, drive info, and contents.
    """
    target = sanitize_path(dir_path, root_restriction)
    if not os.path.exists(target):
        raise FileNotFoundError(f"Directory not found: {target}")
    if not os.path.isdir(target):
        raise NotADirectoryError(f"Path is not a directory: {target}")

    items = []
    parent = os.path.dirname(target.rstrip('\\/'))
    if parent and parent != target and not parent.endswith(':'):
        # Normal parent
        pass
    elif len(target) <= 3 and target[1:2] == ':':
        # Already at root of drive e.g. C:\
        parent = None
    else:
        parent = None

    try:
        with os.scandir(target) as scanner:
            for entry in scanner:
                try:
                    if not show_hidden and is_hidden_file(entry):
                        continue

                    is_dir = entry.is_dir(follow_symlinks=False)
                    st = entry.stat(follow_symlinks=False)
                    ext = "" if is_dir else os.path.splitext(entry.name)[1].lower()
                    
                    # Quick child count for directory if accessible
                    child_count = None
                    if is_dir:
                        try:
                            # fast sampling
                            child_count = len(os.listdir(entry.path))
                        except Exception:
                            child_count = 0

                    items.append({
                        "name": entry.name,
                        "path": entry.path,
                        "is_dir": is_dir,
                        "size": 0 if is_dir else st.st_size,
                        "modified": st.st_mtime,
                        "extension": ext,
                        "category": get_item_category(entry.name, is_dir),
                        "child_count": child_count,
                        "is_hidden": is_hidden_file(entry)
                    })
                except (PermissionError, FileNotFoundError, OSError):
                    continue
    except PermissionError:
        raise PermissionError(f"Access denied to folder: {target}")

    # Build breadcrumb fragments
    breadcrumbs = []
    # If on Windows, root is drive letter e.g. C:\
    drive, path_tail = os.path.splitdrive(target)
    if drive:
        drive_root = drive + "\\"
        breadcrumbs.append({"name": drive, "path": drive_root})
        parts = [p for p in path_tail.split(os.sep) if p]
        curr = drive_root
        for part in parts:
            curr = os.path.join(curr, part)
            breadcrumbs.append({"name": part, "path": curr})
    else:
        parts = [p for p in target.split(os.sep) if p]
        curr = "/"
        breadcrumbs.append({"name": "Root", "path": "/"})
        for part in parts:
            curr = os.path.join(curr, part)
            breadcrumbs.append({"name": part, "path": curr})

    return {
        "current_path": target,
        "parent_path": parent,
        "breadcrumbs": breadcrumbs,
        "items": items,
        "total_items": len(items)
    }


def create_new_folder(parent_dir: str, folder_name: str, root_restriction: str = "") -> str:
    parent = sanitize_path(parent_dir, root_restriction)
    folder_name = folder_name.strip().strip('\\/<>:"|?*')
    if not folder_name:
        raise ValueError("Invalid folder name")
    new_dir = os.path.join(parent, folder_name)
    if os.path.exists(new_dir):
        raise FileExistsError(f"Directory already exists: {folder_name}")
    os.makedirs(new_dir, exist_ok=False)
    return new_dir


def create_new_file(parent_dir: str, file_name: str, content: str = "", root_restriction: str = "") -> str:
    parent = sanitize_path(parent_dir, root_restriction)
    file_name = file_name.strip().strip('\\/<>:"|?*')
    if not file_name:
        raise ValueError("Invalid file name")
    new_file = os.path.join(parent, file_name)
    if os.path.exists(new_file):
        raise FileExistsError(f"File already exists: {file_name}")
    with open(new_file, 'w', encoding='utf-8') as f:
        f.write(content)
    return new_file


def rename_item(old_path: str, new_name: str, root_restriction: str = "") -> str:
    source = sanitize_path(old_path, root_restriction)
    new_name = new_name.strip().strip('\\/<>:"|?*')
    if not new_name:
        raise ValueError("Invalid new name")
    parent = os.path.dirname(source)
    destination = os.path.join(parent, new_name)
    if os.path.exists(destination):
        raise FileExistsError(f"An item named '{new_name}' already exists in this folder")
    os.rename(source, destination)
    return destination


def delete_item(target_path: str, permanent: bool = False, root_restriction: str = "") -> bool:
    source = sanitize_path(target_path, root_restriction)
    if not os.path.exists(source):
        raise FileNotFoundError(f"Item not found: {source}")

    if not permanent and os.name == 'nt':
        # Double null-terminated string for SHFileOperationW
        pFrom = source + "\0\0"
        fileop = SHFILEOPSTRUCTW()
        fileop.wFunc = FO_DELETE
        fileop.pFrom = pFrom
        fileop.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
        res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(fileop))
        if res == 0 and not fileop.fAnyOperationsAborted:
            return True

    # Permanent delete
    if os.path.isdir(source):
        shutil.rmtree(source)
    else:
        os.remove(source)
    return True


def copy_or_move(sources: List[str], dest_dir: str, is_cut: bool = False, root_restriction: str = "") -> List[str]:
    dest = sanitize_path(dest_dir, root_restriction)
    if not os.path.isdir(dest):
        raise NotADirectoryError(f"Destination is not a directory: {dest}")

    results = []
    for src_path in sources:
        src = sanitize_path(src_path, root_restriction)
        if not os.path.exists(src):
            continue

        base_name = os.path.basename(src.rstrip('\\/'))
        target_dest = os.path.join(dest, base_name)

        # Handle destination collisions by appending ' (copy)' or increment
        counter = 1
        name_root, name_ext = os.path.splitext(base_name)
        while os.path.exists(target_dest):
            if is_cut and src == target_dest:
                # Moving into identical path, no-op
                break
            target_dest = os.path.join(dest, f"{name_root} ({counter}){name_ext}")
            counter += 1

        if is_cut:
            shutil.move(src, target_dest)
        else:
            if os.path.isdir(src):
                shutil.copytree(src, target_dest)
            else:
                shutil.copy2(src, target_dest)
        results.append(target_dest)

    return results


def read_text_file(target_path: str, max_bytes: int = 10 * 1024 * 1024, root_restriction: str = "") -> str:
    path = sanitize_path(target_path, root_restriction)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found: {path}")

    size = os.path.getsize(path)
    if size > max_bytes:
        raise ValueError(f"File size ({round(size/(1024*1024), 1)} MB) exceeds preview limit ({max_bytes//(1024*1024)} MB)")

    # Read binary and attempt multiple standard encodings
    with open(path, 'rb') as f:
        data = f.read()

    for enc in ['utf-8', 'utf-8-sig', 'cp1252', 'shift_jis', 'latin-1']:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue

    return data.decode('utf-8', errors='replace')


def write_text_file(target_path: str, content: str, root_restriction: str = "") -> int:
    path = sanitize_path(target_path, root_restriction)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return os.path.getsize(path)


def create_zip_archive(paths: List[str], output_zip_path: str, root_restriction: str = "") -> str:
    """
    Creates a .zip archive containing the specified files and folders.
    """
    with zipfile.ZipFile(output_zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            clean_p = sanitize_path(p, root_restriction)
            if not os.path.exists(clean_p):
                continue
            base_name = os.path.basename(clean_p.rstrip('\\/'))
            if os.path.isdir(clean_p):
                for root, _, files in os.walk(clean_p):
                    for file in files:
                        file_path = os.path.join(root, file)
                        rel_path = os.path.relpath(file_path, os.path.dirname(clean_p))
                        zf.write(file_path, arcname=rel_path)
            else:
                zf.write(clean_p, arcname=base_name)
    return output_zip_path
