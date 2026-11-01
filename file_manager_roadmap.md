# Web File Manager — Version 3.0.0 Enhancement & Feature Roadmap

A structured reference list of upgrades, high-impact features, and UI/UX refinements for the **Version 3.0.0** release of **Web File Manager**.

---

## 🚀 Part 1: Major Power Features

### 1. Bulk Multi-Select & On-The-Fly ZIP Download ✅ [COMPLETED & IMPLEMENTED FOR v3.0]
- **Status**: Production-ready in v3.0.0.
- **Interaction**:
  - **Single Click**: Dedicated open behavior without selection conflicts.
  - **Checkmark Tap**: Toggles selection directly.
  - **Desktop Mouse**: Left-click drag marquee rectangle with real-time 2D AABB bounding collision.
  - **Mobile Touch**: 320ms long-hold drag lasso with haptic pulse.
  - **Key Modifiers**: `Ctrl`+click toggle and `Shift`+click range selection.
- **Bulk Actions**:
  - **Download as ZIP**: Streams a compressed `.zip` archive on the fly directly to the client via `/api/fs/download-zip` with automated FastAPI background task temp cleanup.
  - **Bulk Move / Copy**: Select multiple files/folders and move or copy them to a target folder in one action.
  - **Bulk Delete**: Delete multiple selected items with single confirmation.
- **Why it matters**: Crucial for mobile usability (e.g., pulling 20 photos off a PC in one tap).

---

### 2. Recursive Folder Uploads & Upload Progress Drawer ✅ [COMPLETED & IMPLEMENTED FOR v3.0]
- **Status**: Production-ready in v3.0.0.
- **Capabilities**:
  - Drag-and-drop entire folders from desktop or select via `webkitdirectory` (recursively recreates nested folder hierarchy as-is).
  - Mobile web multi-photo/video picker with fast background transfer over local Wi-Fi.
  - Floating non-blocking upload drawer showing overall progress ($0\% \to 100\%$), upload speed (MB/s), and active files.
- **Why it matters**: Essential when backing up large photo directories or project repositories without flattening directories.

---

### 3. Deep Nested File Search & Token Filters
- **Capabilities**:
  - Substring, extension, and regex search across nested subdirectories with cancellation tokens.
  - Search results view with instant parent-directory jump links.
- **Why it matters**: Quickly locate files buried several levels deep in large drives.

---

## 🎨 Part 2: UI / UX Tweaks & Polish

### 1. Quick Media Filter Chips (Top Bar)
- Instant 1-tap filtering pills under the search bar:
  `[ All ]` `[ 📷 Images ]` `[ 🎬 Videos ]` `[ 🎵 Audio ]` `[ 📄 Documents ]` `[ 📦 Archives ]`
- Filters current folder contents instantly without a page reload.

---

### 2. Visual Drive Capacity & Storage Usage Bars
- Display a color-coded storage capacity bar under each drive chip (e.g. `C: 382 GB / 512 GB — 25% free`).
- Visual indicator turns amber below $15\%$ and red below $5\%$ free space.

---

### 3. Quick-Access Bookmarks & Pinning
- "Pin" button in the folder action menu to bookmark frequently accessed paths (e.g., `Downloads`, `Pictures`, `Projects`).
- Pinned locations appear at the top of the sidebar / drive navigation row.

---

### 4. OLED Pure Black Theme Toggle
- Option to toggle between the current **Deep Navy (`#061a3d`)** theme and a **True OLED Black (`#000000`)** theme.
- Maximizes contrast and saves battery on mobile OLED/AMOLED screens.

---

### 5. 1-Click Stream URL Copy (VLC / MPV External Player)
- Quick "Copy Stream Link" option in the context menu for media files.
- Allows users to copy a direct HTTP Range URL to paste into VLC, MPV, or Kodi on Smart TVs / other devices.

---

### 6. Haptic Feedback & Touch Micro-interactions
- Subtle haptic vibration pulses (`navigator.vibrate`) on supported mobile devices when:
  - Long-pressing an item to open context menu.
  - Completing a file upload.
  - Deleting an item.

---

## 📋 Version 3.0 Release Phases

| Phase | Focus Area | Deliverables | Status |
| :---: | :--- | :--- | :---: |
| **Phase 1** | **Batch Operations** | Multi-Select Marquee/Touch Drag, Streaming ZIP Download | ✅ **Done** |
| **Phase 2** | **File Ingestion** | Recursive Folder Uploads, Progress Queue Drawer | 📋 Planned |
| **Phase 3** | **Search & Discovery** | Deep Recursive Subdirectory Search, Token Filters | 📋 Planned |
| **Phase 4** | **UX & Theme Polish** | OLED Black Theme, Storage Usage Bars, Stream Links | 📋 Planned |
