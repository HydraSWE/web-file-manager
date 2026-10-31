# Hydra Web File Manager — Post-Release Architecture & Feature Specification

> **Version**: 2.0.0 (Post-Release Major Update)  
> **Status**: Production Ready / Ready for Public Release  
> **Platform**: Windows 10 / 11, Cross-Platform Mobile Web (iOS Safari, Android Chrome)  
> **Backend**: Python 3.10+, FastAPI, Uvicorn, WebSockets  
> **Frontend**: Vanilla JavaScript (ES6+), Tailwind CSS, Lucide Icons (Zero npm build steps)

---

## 📌 Executive Summary

Following the initial v1.0 release of the **Hydra Web File Manager**, this major feature rollout introduces five foundational capabilities designed for power users, developers, and mobile-to-PC workflows:

1. **Native Windows Script & Binary Execution Engine** (`.bat`, `.cmd`, `.ps1`, `.py`, `.exe`) with real-time browser terminal streaming and interactive `stdin`.
2. **Multitasking Messenger Chat Heads & Terminal Drawer UI** allowing users to freely browse files while background scripts run in floating, draggable edge bubbles.
3. **Deep Windows `desktop.ini` Folder Template & Custom Icon Integration** to view and assign custom folder artwork and native Windows folder icons directly from the web browser.
4. **Favorites & Pinned Quick Access System** with persistent multi-device synchronization and top-of-folder priority that survives hard server restarts.
5. **Advanced Clipboard with One-Click Paste Confirmation, Hold-to-Inspect Drawer, and Direct "Copy as Path"**.
6. **Natural Multi-Attribute File Sorting and Mobile UI De-cluttering**.

---

## 1. ⚡ Native Windows Script & Application Execution Engine

The execution engine provides secure, native execution of Windows scripts and binaries directly through the web interface, eliminating the need to connect via Remote Desktop, SSH, or physical keyboard.

```
📁 File Manager Web UI
         │
         ├──> Double-Click / Context Menu "Run"
         │            │
         │            ▼
         │   [ Execution Confirmation Dialog ]
         │   ├── Select Mode: Browser Terminal vs Desktop
         │   ├── Pass Optional CLI Arguments
         │   └── Validate Working Directory
         │            │
         ▼            ▼
   Mode A: Browser Terminal              Mode B: Desktop Launch
   ┌─────────────────────────────┐       ┌─────────────────────────────┐
   │ Background Subprocess       │       │ Native Interactive Session  │
   │ WebSocket Output Stream     │       │ Visible CMD / PowerShell    │
   │ Interactive stdin Input     │       │ Native GUI Binary (.exe)    │
   │ Process Tree Termination    │       │ Preserves Working Directory │
   └─────────────────────────────┘       └─────────────────────────────┘
```

### Supported File Types & Behaviors

| Extension | Execution Binary | Browser Terminal Mode | Windows Desktop Mode |
| :--- | :--- | :--- | :--- |
| **`.bat`** / **`.cmd`** | `cmd.exe` | Runs headless via `cmd.exe /D /C`; stdout & stderr piped to WebSocket. | Spawns visible interactive command prompt window (`cmd.exe /K`) on desktop. |
| **`.ps1`** | `powershell.exe` | Headless execution with `-NonInteractive -ExecutionPolicy Bypass -File`. | Spawns visible PowerShell window on desktop. |
| **`.py`** | Active Python runtime | Executes via server's Python virtual environment (`sys.executable`). | Spawns visible Python console window on desktop. |
| **`.exe`** | Native Windows PE | *Restricted for security/interactivity* | Launches native Windows GUI or CLI executable in interactive user session. |

### Key Execution Capabilities
- **Dual Execution Modes**:
  - **Browser Terminal**: Headless background execution capturing output streams with real-time ANSI terminal rendering, elapsed runtime counters, and process exit codes.
  - **Windows Desktop Launch**: Launches visible applications directly on the host desktop session, ideal for games, tools, or interactive batch files.
- **Interactive Standard Input (`stdin`)**:
  - Scripts prompting for interactive input (e.g. `set /p choice=`, Python `input()`) can receive text, `Enter`, and `Ctrl+C` interrupt signals over WebSocket or REST.
- **Process Tree Management & Termination**:
  - Stopping a script uses recursive process-tree termination (`taskkill /F /T /PID` on Windows) so child processes never remain orphaned.
- **Process History**:
  - Completed and terminated executions are logged in an in-memory ring buffer with exit codes, durations, and output logs.

---

## 2. 💬 Multitasking Messenger Chat Heads & Terminal Drawer UI

Inspired by Facebook Messenger's floating chat bubbles, this system enables true background multitasking: scripts run concurrently in the background while users freely navigate, upload, preview, and edit files.

```
┌────────────────────────────────────────────────────────┐
│ Web File Manager Screen                                │
│                                                        │
│  [Breadcrumbs: C: > Tools > Scripts ]                  │
│                                                        │
│  📁 build/     📁 src/        📄 config.json           │
│                                           ╭─────────╮  │
│                                           │  (>_)   │<── Floating 56px Bubble
│                                           │ RUNNING │  │  (Magnetic Snap-to-Edge)
│                                           ╰─────────╯  │
└────────────────────────────────────────────────────────┘
                           │ Tap Bubble
                           ▼
┌────────────────────────────────────────────────────────┐
│ [Bubble 1: build.bat] [Bubble 2: worker.py] [+] (Close)│ <── Top Process Avatars
│ ┌────────────────────────────────────────────────────┐ │
│ │ 💻 Terminal Drawer: build.bat (PID: 14208) [STOP]  │ │
│ │ -------------------------------------------------- │ │
│ │ Compiling assets...                                │ │
│ │ Output: 42 files bundled in 1.4s                   │ │
│ │ Done! Exit code: 0                                 │ │
│ └────────────────────────────────────────────────────┘ │
│ [ Enter command / input...                         ]   │ <── Interactive stdin
└────────────────────────────────────────────────────────┘
```

### Physics & Gesture Mechanics
- **Physics-Based Dragging**: Fluid touch and mouse pointer dragging with zero latency across X and Y axes.
- **Spring Edge-Snapping**: On release, uses a cubic-bezier spring curve (`cubic-bezier(0.175, 0.885, 0.32, 1.275)`) to smoothly dock to either the left or right screen edge with a 12px margin.
- **Smart Tap vs. Drag Threshold**: Movements under 5px register as a tap (opening the drawer); movements over 5px initiate smooth dragging.
- **Stacked Bubble Management**: When multiple scripts run simultaneously, the bubble displays a live task counter badge (`RUNNING 2`).
- **Authentic Process Avatars**: Dynamic high-fidelity icons for Python, PowerShell, Command Prompt, and Windows Executables.
- **Expanded Process Strip**: Tapping the bubble reveals a horizontal avatar bar (`[Bubble 1] [Bubble 2] [+]`) allowing 1-tap switching between parallel running processes without restarting or losing terminal scroll positions.

---

## 3. 🎨 Windows Folder Templates & Custom Icons (`desktop.ini`)

Hydra Web File Manager bridges the gap between Windows Explorer folder customization and web file management.

### Deep Windows Shell Integration
- **`desktop.ini` Parsing**: Inspects folders for native Windows Explorer customizations, including `IconResource` and `IconFile` directives, resolving relative and absolute icon paths.
- **Folder Artwork Detection**: Automatically checks for standard folder cover art (`folder.ico`, `folder.png`, `folder.jpg`, `cover.jpg`, `cover.png`, `logo.png`).
- **Visual Display**: Renders folder artwork directly on folder cards in Grid view and row items in List view.

### In-Browser Folder Logo Customizer
Users can assign custom folder logos directly from the web browser:
1. Long-press or click `...` on any folder and select **Set Folder Logo**.
2. Upload any image (`.png`, `.jpg`, `.webp`, `.ico`).
3. The server automatically:
   - Converts the uploaded image to a Windows Multi-Resolution `.ico` file (256x256, 128x128, 64x64, 48x48, 32x32, 16x16).
   - Generates or updates `desktop.ini` with `[.ShellClassInfo] IconResource=folder_icon.ico,0`.
   - Sets required Windows file attributes via `attrib +r <folder>` and `attrib +h +s desktop.ini`.
   - Triggers native Windows Explorer icon cache invalidation via `SHChangeNotify(SHCNE_ASSOCCHANGED)`.
4. The custom icon appears immediately in both the web interface and Windows Explorer.

---

## 4. ⭐ Favorites & Pinned Quick Access System

A persistent, cross-device bookmarking and quick-access engine for folders and files.

### Key Features
- **One-Tap Pinning**: Pin or unpin any file or directory from:
  - The 3-dots Context Menu / Mobile Bottom Sheet.
  - The top header star icon inside the File Preview modal.
  - The floating batch selection action bar.
- **Pinned Quick Access Shelf**:
  - A collapsible, touch-friendly shelf docked above the file view.
  - Clicking a pinned folder immediately navigates into it; clicking a pinned file opens its preview modal.
  - Includes quick unpin `×` buttons on each chip.
- **Visual Star Badges**:
  - Glowing amber star badge (`⭐`) rendered on cards in Grid view and beside names in List view.
- **Top-of-Folder Priority**:
  - Pinned folders and pinned files automatically float to the top of folder listings above non-pinned items.
- **Favorites Category Filter**:
  - A dedicated `Favorites (N)` filter pill in the filter bar filters the active view to favorited items with 1 tap.
- **Persistence Across Server Restarts**:
  - Favorites are stored on the server in `favorites.json` and mirrored in client-side `localStorage`, synchronizing bookmarks across desktop and mobile while surviving server reboots.

---

## 5. 📋 Advanced Clipboard & Paste Confirmation

Prevents accidental overwrites and enhances clipboard mobility between mobile and PC.

### 1. One-Click Paste Confirmation Modal
- Tapping the **Paste** button on mobile or desktop presents a confirmation dialog:
  - Displays the destination folder: `Into folder: "[Target Folder]"`.
  - Lists every file and folder queued for pasting with proper basenames and file icons.
  - Clearly identifies whether the operation is a **Copy (Duplicate)** or **Move (Cut)**.
  - Provides **Cancel**, **Clear**, and **Paste Here** actions.

### 2. Long-Press / Hold Clipboard Inspector
- Holding or long-pressing the **Paste** button on the navigation bar opens the **Clipboard Inspector**:
  - View all queued items with their full source paths and proper file names.
  - **Individual Removal**: Click `×` beside any specific item to remove it from the clipboard without clearing the rest.
  - **Clear All**: Purges the clipboard completely and dismisses the paste button.
  - **Paste Here**: Direct trigger to paste all remaining items into the current folder.

### 3. Copy as Path
- Added dedicated **`Copy as Path`** action in the context menu.
- Copies the exact Windows filesystem path (e.g. `D:\Tools\HYDRA\server.py`) directly to the system clipboard.
- Includes cross-platform fallbacks (`document.execCommand('copy')`) ensuring 100% reliability over local Wi-Fi HTTP on iOS Safari and Android Chrome without requiring SSL/HTTPS.

---

## 6. 🗂️ File Sorting & Mobile UI De-cluttering

- **Multi-Attribute Natural Sorting**:
  - Sort by **Name** (natural alphanumeric, e.g. `file2` before `file10`), **Date Modified**, **Size**, or **Extension / Type**.
  - Toggle between **Ascending** and **Descending** order.
  - Folders remain pinned at the top regardless of sort criteria.
  - Sort preferences persist in browser `localStorage`.
- **Header De-cluttering**:
  - Removed redundant `"Local Hub"` badges to prevent header wrapping on narrow mobile screens.
  - App title **Web File Manager** displays cleanly on a single line alongside drive selectors and toolbar icons.
  - Embedded high-resolution brand icons and dynamic favicons.

---

## 7. 🔌 Complete API Specification

### Execution Endpoints

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/execution/config` | Returns public execution capabilities and allowed file extensions. | No |
| `POST` | `/api/execution/start` | Starts script or binary execution in terminal or desktop mode. | Yes (`token`) |
| `GET` | `/api/execution/processes` | Lists active background processes owned by current session. | Yes (`token`) |
| `GET` | `/api/execution/process/{id}` | Retrieves execution status, duration, and exit code. | Yes (`token`) |
| `POST` | `/api/execution/stop/{id}` | Terminates process and all descendant child processes. | Yes (`token`) |
| `POST` | `/api/execution/stdin/{id}` | Sends interactive text input to a running terminal process. | Yes (`token`) |
| `GET` | `/api/execution/history` | Retrieves completed/terminated execution records. | Yes (`token`) |
| `WS` | `/ws/execution/{process_id}` | WebSocket stream for real-time stdout/stderr logs and status. | Yes (`?token=`) |

### Folder Icon Endpoints

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/fs/folder-icon` | Streams folder custom icon or artwork (`?path=...`). | Optional |
| `POST` | `/api/fs/folder-icon/set` | Uploads image, creates `.ico` + `desktop.ini`, and notifies shell. | Yes (`token`) |
| `POST` | `/api/fs/folder-icon/reset` | Resets folder back to default Windows icon. | Yes (`token`) |

### Favorites Endpoints

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/favorites` | Returns list of all favorited items. | Yes (`token`) |
| `POST` | `/api/favorites/toggle` | Toggles favorite status for a folder or file path. | Yes (`token`) |
| `POST` | `/api/favorites/batch` | Batch adds or removes multiple paths from favorites. | Yes (`token`) |
| `POST` | `/api/favorites/clear` | Purges all pinned favorites. | Yes (`token`) |

---

## 8. ⚙️ Configuration Reference (`config.json`)

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
    "enabled": true,
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

### Configuration Parameters

| Key | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `app_name` | `string` | `"Web File Manager"` | Branding title displayed in header, terminal, and browser tab. |
| `app_icon` | `string` | `"/static/app_icon.png"` | Path or URL to custom brand icon. |
| `port` | `integer` | `8080` (or `8088`) | Network port to bind server. |
| `host` | `string` | `"0.0.0.0"` | Bind interface (`0.0.0.0` binds to all LAN interfaces). |
| `root_path` | `string` | `""` | Restrict access to a specific folder. Empty string allows browsing all drives. |
| `pin` | `string` | `""` | Optional access PIN. When set, clients must authenticate before filesystem access. |
| `execution.enabled` | `boolean` | `false` | Master toggle for script and executable execution. |
| `execution.require_authentication` | `boolean` | `true` | Enforces valid session token before executing scripts. |
| `execution.require_confirmation` | `boolean` | `true` | Requires user confirmation modal before launching any script. |
| `execution.allowed_extensions` | `array` | `[".bat", ".cmd", ".ps1", ".py", ".exe"]` | Permitted executable extensions allowlist. |
| `execution.default_script_mode` | `string` | `"terminal"` | Default mode (`"terminal"` or `"desktop"`). |
| `execution.timeout_seconds` | `integer` | `300` | Max runtime in seconds for terminal-captured background scripts. |
| `execution.max_concurrent_processes`| `integer` | `3` | Maximum concurrent background executions permitted. |
| `execution.allow_desktop_execution` | `boolean` | `true` | Allows launching interactive consoles and binaries on host desktop. |

---

## 9. 🚀 Verification & Testing Summary

All features have been tested and verified in live Windows environments:
- **Execution Engine**: Verified `.bat` (dir, loops, exit codes), `.ps1` (system info, execution policy bypass), `.py` (stdout/stderr buffering and stdin), and `.exe` desktop launch.
- **Chat Heads Multitasking**: Verified smooth touch dragging, cubic-bezier edge docking, multi-process bubble switching, and ANSI color decoding.
- **Folder Icons**: Verified Windows `desktop.ini` generation, 6-resolution `.ico` conversion, and `SHChangeNotify` Explorer cache updates.
- **Favorites**: Verified star toggling, shelf chip rendering, top-of-folder sorting, and persistence across server hard restarts (`favorites.json`).
- **Clipboard**: Verified one-click paste confirmation, long-press inspector drawer, individual item deletion, and `Copy as Path` clipboard operations.
