# 📁 Web File Manager - Mobile-First Local Web File Manager

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Tailwind CSS](https://img.shields.io/badge/frontend-Tailwind%20CSS-38bdf8.svg)](https://tailwindcss.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()

> A lightweight, self-contained, mobile-first Web File Manager for your local network. Browse, stream, edit, upload, and manage files between your PC and smartphone over Wi-Fi with **zero mobile apps installed** and **zero frontend build steps**.

---

## ⚡ Highlights

- 📱 **Mobile-First Touch Design**: Modern dark theme, 44px+ hit targets, bottom drawer context menus, long-press item actions, and fluid two-finger **pinch-to-zoom** on images.
- 🎨 **Lucide Iconography**: Beautiful, crisp vector icons for folders, drives, and file categories (code, archives, videos, audio, images, documents).
- 📷 **Instant QR Code Onboarding**: Terminal automatically generates and prints a scannable ASCII QR code on startup so you can point your phone camera and connect immediately.
- 💾 **Drive Navigation**: Dynamically lists and monitors all available storage drives with live storage usage gauges.
- 🗑️ **Safe Recycle Bin Deletion**: On Windows, file deletion integrates with the native Windows Shell API (`SHFileOperationW`) to move items safely to the **Windows Recycle Bin** instead of permanent deletion.
- 🎬 **In-Browser Media Previews**:
  - **Images**: High-resolution viewer with pan, rotate, and pinch-to-zoom.
  - **Videos**: HTTP Range-enabled video streaming with smooth seeking.
  - **Audio**: Custom audio player with duration and seek tracking.
  - **PDFs**: Embedded in-browser PDF reader.
  - **Code/Text**: Syntax-colored read-only viewer with 1-click clipboard copy.
- ✏️ **In-Browser Code / Text Editor**: Built-in editor with monospace typography, line numbers, and keyboard shortcuts (`Ctrl+S`).
- 📋 **Global Clipboard**: Copy or cut single or batch items and paste across directories with conflict auto-resolution (`file (1).txt`).
- 📦 **ZIP Bundling**: Download single files or multi-select entire folders as dynamically compressed `.zip` streams.
- 🔒 **Optional PIN Security**: Configurable 4-digit PIN authentication to restrict unauthorized access on shared Wi-Fi networks.

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

## 📱 Mobile Connection Tips

- **Explicit `http://` in Chrome**: When typing the address manually into Google Chrome on mobile, include the full `http://` protocol:
  ```
  http://192.168.x.x:8080
  ```
  *(Without `http://`, Chrome defaults to forcing `https://` which can trigger `ERR_TOO_MANY_RETRIES` on local development servers).*
- **Same Wi-Fi Router**: Ensure your phone is connected to the same Wi-Fi router (avoid guest networks or cellular data).
- **Windows Network Profile**: Ensure your Windows network connection is set to **Private Network** in Windows Settings -> Network & Internet.

---

## ⚙️ Configuration (`config.json` & Environment Variables)

You can customize behavior via `config.json` or by setting environment variables (`APP_NAME`, `APP_ICON`, `PORT`):

```json
{
  "app_name": "Web File Manager",
  "app_icon": "",
  "port": 8080,
  "host": "0.0.0.0",
  "root_path": "",
  "pin": "",
  "allow_recycle_bin": true,
  "allow_permanent_delete": true,
  "show_hidden_files": false
}
```

| Setting | Environment Var | Type | Description |
| :--- | :--- | :--- | :--- |
| `app_name` | `APP_NAME` | `string` | Custom branding name displayed on the UI and terminal. |
| `app_icon` | `APP_ICON` | `string` | Optional custom icon/logo image URL or path. Defaults to Lucide folder icon. |
| `port` | `PORT` | `number` | Port to bind server on (default `8080`). |
| `host` | `HOST` | `string` | Bind interface (`0.0.0.0` for all LAN interfaces). |
| `root_path` | `ROOT_PATH` | `string` | Restrict browsing to a specific folder (e.g. `"/home/user/files"`). Empty `""` grants access across all drives. |
| `pin` | `PIN` | `string` | Optional 4-digit PIN (e.g. `"1234"`). When set, users must enter this PIN before accessing filesystem APIs. |
| `allow_recycle_bin`| - | `boolean` | Enables Windows Recycle Bin support on deletion. |
| `allow_permanent_delete` | - | `boolean` | Allows users to bypass Recycle Bin for immediate deletion. |
| `show_hidden_files` | - | `boolean` | Whether to display dotfiles and hidden Windows files by default. |

---

## 🛠️ Tech Stack & Architecture

- **Backend**: Python 3.10+, [FastAPI](https://fastapi.tiangolo.com/), [Uvicorn](https://www.uvicorn.org/)
- **Frontend**: Single-Page Application (HTML5, [Tailwind CSS CDN](https://tailwindcss.com/), Vanilla JavaScript, [Lucide Icons](https://lucide.dev/))
- **Networking**: `0.0.0.0` interface binding with 3-tier LAN IP auto-detection (UDP socket routing -> hostname enumeration -> `ipconfig`/`ifconfig` fallback)
- **Zero Build Step**: No `npm`, `vite`, `webpack`, or Node.js required.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE) - Copyright (c) 2026 HydraSWE.
