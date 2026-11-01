# 🚀 Web File Manager - Mobile-First Local Web File Manager

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Tailwind CSS](https://img.shields.io/badge/frontend-Tailwind%20CSS-38bdf8.svg)](https://tailwindcss.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()

> A lightweight, self-contained, mobile-first Web File Manager for your local network. Browse, stream, edit, upload, manage, and execute files between your PC and smartphone over Wi-Fi with **zero mobile apps installed** and **zero frontend build steps**.

---

## ✨ Highlights & Capabilities

- 📱 **Mobile-First Touch Design**: Modern dark theme, 44px+ hit targets, bottom drawer context menus, long-press actions, and fluid two-finger **pinch-to-zoom** on images.
- 🛡️ **PC-Controlled Multi-Owner Security & Universal Device Pairing**:
  - **Windows PC Root Authority**: The Windows PC is the sole root authority; remote devices receive delegated capabilities and can never independently hijack or own the PC.
  - **Universal LAN Mobile Cryptography**: Locally bundled TweetNaCl (`nacl.min.js`) enables audited RFC 8032 Ed25519 cryptographic pairing and challenge-response signing over plain HTTP local Wi-Fi connections on Android and iOS browsers with zero external network or build steps.
  - **Windows Authentication Broker**: Named pipe IPC (`\\.\pipe\HydraAuthBroker`) prompts native **Windows Hello** (biometrics / PIN) on the PC screen for first-time owner registration, co-owner elevation, and security unlocks.
  - **Granular Capability Permissions**: Fine-grained per-device authorization (`filesystem.read`, `filesystem.write`, `execution.script`, `execution.desktop`, `process.manage`, `system.monitor`).
  - **Emergency Security Lockdown**: 1-click platform freeze across all connected devices, strictly requiring local Windows Hello on the PC to restore operations.
  - **Windows-Local Recovery**: Automatic local recovery on `localhost:8088` via Windows Hello if browser storage is cleared.
- 📦 **Bulk Multi-Select & Conflict-Free Selection Engine**:
  - Desktop left-click marquee drag selection and mobile touch long-press lasso with haptic feedback.
  - Conflict-free interaction: single-click opens files/folders normally when 0 selected; card clicks toggle selection when active; dedicated checkbox badge.
- 🛡️ **Smart Download Engine (Name Protection vs. Nested ZIPs)**:
  - Single files download directly with exact original filename and extension preserved (zero unwanted ZIP wrapping).
  - Selected folders and multi-file selections stream as cleanly nested `.zip` archives with automatic background temp file cleanup.
- 📤 **Mobile Multi-Upload & Recursive Directory Ingestion**:
  - 1-tap multi-file selection from phone photo galleries or document pickers.
  - Upload complete nested folder hierarchies via `webkitdirectory` or desktop drag-and-drop.
  - Floating non-blocking upload drawer with real-time transfer speed (`MB/s`) and progress bar.
- ⚡ **Native Windows File Execution Engine**: Securely run scripts (`.bat`, `.cmd`, `.ps1`, `.py`) and desktop applications (`.exe`) directly from your browser.
  - **Browser Terminal**: Real-time WebSocket output streaming, ANSI color support, elapsed duration timers, process exit codes, and interactive standard input (`stdin`).
  - **Windows Desktop**: Launch applications or visible CMD/PowerShell consoles directly on the host desktop session preserving working directories.
- 💬 **Multitasking Messenger Chat Heads & Terminal Drawer**:
  - Background scripts run inside a floating, draggable edge bubble (Chat Head) with physics and magnetic spring edge-snapping.
  - Stack counter badge (`RUNNING 2`) for concurrent tasks and process-specific logos (Python, PowerShell, CMD, EXE).
  - Expandable drawer with horizontal process avatar tabs (`[Bubble 1] [Bubble 2] [+]`) to multitask freely while background processes run.
- 🎨 **Folder Templates & Windows `desktop.ini` Icons**:
  - Automatically detects folder artwork (`folder.ico`, `folder.png`, `cover.jpg`) and native Windows `desktop.ini` customizations.
  - **In-Browser Folder Logo Customizer**: Upload any image to automatically convert it into a multi-size Windows `.ico`, generate `desktop.ini`, apply system attributes (`attrib +r`), and refresh Windows Explorer icon cache.
- ⭐ **Favorites & Pinned Quick Access System**:
  - Star/pin any folder or file with 1 tap.
  - Pinned Quick Access Shelf right above files for instant folder jumping or file preview.
  - Pinned items float to the top of folder listings and persist across server hard restarts via `favorites.json`.
- 📋 **Advanced Clipboard with Confirmation & Inspector**:
  - **Paste Confirmation Modal**: One-click paste prompts confirmation showing destination folder and item names, preventing accidental pastes.
  - **Clipboard Inspector**: Long-press or hold the Paste button on navigation to inspect queued items, delete individual items, or clear all.
  - **Copy as Path**: 1-tap copy of absolute Windows filesystem paths directly to the system clipboard with HTTP mobile fallback.
- 🗂️ **Multi-Attribute File Sorting**: Naturally sort by Name, Date Modified, Size, or Extension (ascending/descending) with folders pinned at top.
- 🔍 **Dynamic Category Filtering**: Fast filter pills for Folders, Images, Videos, Audio, Code, Archives, and Favorites with live counts.
- 📷 **Instant QR Code Onboarding**: Terminal prints a scannable ASCII QR code and serves high-res halftone branded QR codes for 1-second mobile camera connections.
- 💽 **Drive Navigation**: Dynamically lists and monitors all available storage drives with live storage usage gauges.
- 🗑️ **Safe Windows Recycle Bin Deletion**: Integrates with the native Windows Shell API (`SHFileOperationW`) to safely move items to the **Windows Recycle Bin** instead of permanent deletion.
- 🎬 **In-Browser Media Previews**:
  - **Images**: High-resolution viewer with pan, rotate, and pinch-to-zoom.
  - **Videos**: HTTP Range-enabled video streaming with smooth seeking.
  - **Audio**: Custom audio player with duration and seek tracking.
  - **PDFs**: Embedded in-browser PDF reader.
  - **Code/Text**: Syntax-colored read-only viewer with 1-click clipboard copy.
- 📝 **In-Browser Code / Text Editor**: Built-in editor with monospace typography, line numbers, and keyboard shortcuts (`Ctrl+S`).
- 📦 **ZIP Bundling**: Download single files or multi-select entire folders as dynamically compressed `.zip` streams.
- 🔒 **PIN & Session Security**: Configurable PIN authentication and scoped session token verification for remote browsing and execution control.

---

## 🚀 Quick Start

### Windows
1. Clone this repository:
   ```cmd
   git clone https://github.com/HydraSWE/web-file-manager.git
   cd web-file-manager
   ```
2. Double-click **`run.bat`** (it automatically detects your Python environment and installs dependencies if needed).
3. Connect your smartphone to the same Wi-Fi network and scan the ASCII QR code printed in the terminal!

*(Optional)* If Windows Defender Firewall blocks inbound connections on your network, right-click **`open_firewall.bat`** and run as Administrator once.

### Linux / macOS
```bash
git clone https://github.com/HydraSWE/web-file-manager.git
cd web-file-manager
chmod +x run.sh
./run.sh
```

---

## ⚙️ Configuration (`config.json` & Environment Variables)

You can customize behavior via `config.json` or by setting environment variables (`APP_NAME`, `APP_ICON`, `PORT`):

```json
{
  "app_name": "Web File Manager",
  "app_icon": "/static/app_icon.png",
  "port": 8088,
  "host": "0.0.0.0",
  "root_path": "",
  "pin": "",
  "allow_recycle_bin": true,
  "allow_permanent_delete": true,
  "show_hidden_files": false,
  "execution": {
    "enabled": false,
    "require_authentication": true,
    "require_confirmation": true,
    "allowed_extensions": [
      ".bat",
      ".cmd",
      ".ps1",
      ".py",
      ".exe"
    ],
    "default_script_mode": "terminal",
    "timeout_seconds": 300,
    "max_concurrent_processes": 3,
    "allow_desktop_execution": true
  }
}
```

| Setting | Environment Var | Type | Description |
| :--- | :--- | :--- | :--- |
| `app_name` | `APP_NAME` | `string` | Custom branding name displayed on the UI and terminal. |
| `app_icon` | `APP_ICON` | `string` | Optional custom icon/logo image URL or path. Defaults to `/static/app_icon.png`. |
| `port` | `PORT` | `number` | Port to bind server on (default `8080` or `8088`). |
| `host` | `HOST` | `string` | Bind interface (`0.0.0.0` for all LAN interfaces). |
| `root_path` | `ROOT_PATH` | `string` | Restrict browsing to a specific folder. Empty `""` grants access across all drives. |
| `pin` | `PIN` | `string` | Optional PIN. When set, users must enter this PIN before accessing filesystem APIs. |
| `allow_recycle_bin`| - | `boolean` | Enables Windows Recycle Bin support on deletion. |
| `allow_permanent_delete` | - | `boolean` | Allows users to bypass Recycle Bin for immediate deletion. |
| `show_hidden_files` | - | `boolean` | Whether to display dotfiles and hidden Windows files by default. |
| `execution.enabled` | - | `boolean` | Master switch for script and binary execution. **Disabled by default (`false`)** for security. |
| `execution.require_authentication` | - | `boolean` | Enforces authenticated session token before permitting execution requests. |
| `execution.require_confirmation` | - | `boolean` | Prompts with an execution confirmation dialog before starting any process. |
| `execution.allowed_extensions` | - | `list[str]` | Whitelist of permitted executable file extensions (`[".bat", ".cmd", ".ps1", ".py", ".exe"]`). |
| `execution.default_script_mode` | - | `string` | Default execution mode for scripts: `"terminal"` or `"desktop"`. |
| `execution.timeout_seconds` | - | `number` | Maximum runtime in seconds for browser-terminal captured processes (default `300`). |
| `execution.max_concurrent_processes` | - | `number` | Maximum number of concurrent executing jobs permitted (default `3`). |
| `execution.allow_desktop_execution` | - | `boolean` | Permits launching interactive consoles and GUI windows on the Windows desktop. |

---

## 🔒 File Execution Engine & Security

The execution engine provides native Windows script and executable launching capabilities with enterprise-grade security controls:

### Execution Modes

| Extension | Supported Modes | Description |
| :--- | :--- | :--- |
| `.bat` / `.cmd` | Browser Terminal OR Windows CMD | Run via `cmd.exe /D /C` with stdout/stderr capture or visible Windows CMD console (`/K`). |
| `.ps1` | Browser Terminal OR Windows PowerShell | Run via `powershell.exe -NonInteractive -ExecutionPolicy Bypass -File` or visible PowerShell console. |
| `.py` | Browser Terminal OR Windows console | Run via current Python environment (`sys.executable`) with output capture or visible console. |
| `.exe` | Windows Desktop only | Launch native Windows GUI/CLI binaries with `DETACHED_PROCESS` or `CREATE_NEW_CONSOLE`. |

### Security Invariants

1. **Disabled by Default**: Execution is explicitly turned off in `config.json` (`"enabled": false`) and returns HTTP 403 unless explicitly enabled by the administrator.
2. **Session Authorization**: Execution requires a valid session token even when the file manager PIN is empty. Unauthenticated requests are rejected with HTTP 401.
3. **No `shell=True`**: All commands use explicit binary paths and argument arrays; untrusted inputs are never concatenated into shell command strings.
4. **Strict Path Canonicalization**: All targets are canonicalized via `os.path.realpath` to resolve symbolic links and directory traversal sequences (`..`) before validation against configured boundaries.
5. **Process Isolation**: Each execution job is associated with the authenticated session token that initiated it; users cannot inspect, stream, or terminate other users' jobs.
6. **Process Tree Termination**: Stopping a running process on Windows uses `taskkill /F /T /PID` to cleanly terminate the process and all spawned child processes.

---

## 📖 Additional Documentation & Changelog

For detailed architectural diagrams, WebSocket protocols, and full release specifications, see:
- 📄 [**NEW_FEATURES_POST_RELEASE.md**](NEW_FEATURES_POST_RELEASE.md) (formerly `POST_RELEASE_UPDATES.md`) — Comprehensive technical guide to script execution, chat heads multitasking, and folder template customization.
- 📄 [**V3_FEATURES_SPECIFICATION.md**](V3_FEATURES_SPECIFICATION.md) — Comprehensive technical specification for Version 3.0: PC-Controlled Multi-Owner Security & Cryptographic Device Pairing, Universal LAN Mobile Cryptography (TweetNaCl), Conflict-Free Bulk Multi-Select, Name-Protected Smart Downloads, and Mobile Multi-Upload with Recursive Directory Ingestion.

---

## 🛠️ Tech Stack & Architecture

- **Backend**: Python 3.10+, [FastAPI](https://fastapi.tiangolo.com/), [Uvicorn](https://www.uvicorn.org/), WebSockets
- **Execution Engine**: Native Windows Process API (`asyncio.create_subprocess_exec`, `subprocess.Popen`, Windows Creation Flags)
- **Frontend**: Single-Page Application (HTML5, [Tailwind CSS CDN](https://tailwindcss.com/), Vanilla JavaScript, [Lucide Icons](https://lucide.dev/))
- **Networking**: `0.0.0.0` interface binding with 3-tier LAN IP auto-detection (UDP socket routing -> hostname enumeration -> `ipconfig`/`ifconfig` fallback)
- **Cryptography & Security**: TweetNaCl (Pure JS RFC 8032 Ed25519), WebCrypto API, Argon2id, Windows Named Pipe IPC (`\\.\pipe\HydraAuthBroker`), Windows Hello / CredUI
- **Zero Build Step**: No `npm`, `vite`, `webpack`, or Node.js required.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE) - Copyright (c) 2026 HydraSWE.
