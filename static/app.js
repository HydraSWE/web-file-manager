/**
 * Hydra Files - Mobile-First Web File Manager Application
 * Implements Hydra Obsidian Design Standards & Touch Interactions
 */

const STATE = {
  appName: 'Web File Manager',
  currentPath: '',
  parentPath: null,
  items: [],
  filteredItems: [],
  drives: [],
  selectedPaths: new Set(),
  clipboard: JSON.parse(localStorage.getItem('wfm_clipboard') || 'null'), // { sources: [], isCut: false }
  viewMode: localStorage.getItem('wfm_viewMode') || 'grid', // 'grid' | 'list'
  categoryFilter: 'all',
  searchQuery: '',
  contextItem: null,
  isSelectMode: false,
  authToken: localStorage.getItem('wfm_token') || '',
  activeEditorPath: '',
  editorDirty: false,
  networkInfo: null,
  
  // Image Viewer Zoom & Pan State
  zoomScale: 1.0,
  panX: 0,
  panY: 0,
  isPanning: false,
  startPanX: 0,
  startPanY: 0,
  touchInitialDist: 0,
  touchInitialScale: 1.0
};

// ============================================================
// Initialization & Startup
// ============================================================

document.addEventListener('DOMContentLoaded', async () => {
  setupKeyboardShortcuts();
  setupDragAndDrop();
  updateViewToggleUI();
  updateClipboardUI();

  // Check auth requirement & configuration
  try {
    const res = await fetch('/api/config');
    const config = await res.json();
    STATE.networkInfo = config;

    if (config.app_name) {
      STATE.appName = config.app_name;
      document.title = `${STATE.appName} - Mobile-First Local Web File Manager`;
      const headerTitle = document.getElementById('appHeaderTitle');
      if (headerTitle) headerTitle.textContent = STATE.appName;
    }

    if (config.app_icon) {
      const logoContainer = document.getElementById('appLogoContainer');
      if (logoContainer) {
        logoContainer.innerHTML = `<img src="${config.app_icon}" class="w-full h-full object-cover rounded-xl" onerror="this.parentElement.innerHTML='<i data-lucide=\\'folder\\' class=\\'w-5 h-5 text-brand-400\\'></i>'; if (window.lucide) lucide.createIcons();">`;
      }
    }

    if (config.auth_required && !STATE.authToken) {
      showAuthModal();
      return;
    }
  } catch (err) {
    console.error('Config fetch error:', err);
  }

  await fetchDrives();
  await loadDirectory('');
});

// Modal scroll lock helper
function toggleModalScrollLock(isOpen) {
  if (isOpen) {
    document.body.classList.add('modal-open');
  } else {
    // Only remove if no other modal is currently visible
    const openModals = document.querySelectorAll('#previewModal:not(.hidden), #editorModal:not(.hidden), #uploadModal:not(.hidden), #inputModal:not(.hidden), #deleteModal:not(.hidden), #qrModal:not(.hidden), #authModal:not(.hidden), #contextSheet:not(.hidden)');
    if (openModals.length === 0) {
      document.body.classList.remove('modal-open');
    }
  }
}

// ============================================================
// Authentication
// ============================================================

function showAuthModal() {
  document.getElementById('authModal').classList.remove('hidden');
  toggleModalScrollLock(true);
  document.getElementById('pinInput').focus();
}

async function submitPinAuth() {
  const pin = document.getElementById('pinInput').value.trim();
  if (!pin) return;

  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pin })
    });
    if (res.ok) {
      const data = await res.json();
      STATE.authToken = data.token;
      localStorage.setItem('wfm_token', data.token);
      document.getElementById('authModal').classList.add('hidden');
      toggleModalScrollLock(false);
      showToast(`${STATE.appName} unlocked`, 'success');
      await fetchDrives();
      await loadDirectory('');
    } else {
      showToast('Invalid PIN. Please try again.', 'error');
      document.getElementById('pinInput').value = '';
    }
  } catch (err) {
    showToast('Auth error: ' + err.message, 'error');
  }
}

// ============================================================
// API Helper with Auth Token
// ============================================================

async function apiFetch(url, options = {}) {
  const headers = options.headers || {};
  if (STATE.authToken) {
    headers['X-Auth-Token'] = STATE.authToken;
  }
  options.headers = headers;

  const res = await fetch(url, options);
  if (res.status === 401) {
    showAuthModal();
    throw new Error('Unauthorized');
  }
  return res;
}

// ============================================================
// Drive Enumeration with Storage Meters
// ============================================================

async function fetchDrives() {
  try {
    const res = await apiFetch('/api/drives');
    if (!res.ok) return;
    STATE.drives = await res.json();

    const driveList = document.getElementById('driveList');
    driveList.innerHTML = '';

    STATE.drives.forEach(d => {
      const btn = document.createElement('button');
      btn.className = 'w-full px-3.5 py-2.5 text-left hover:bg-surface-hover flex flex-col gap-1.5 text-xs transition touch-press border-b border-slate-800/60 last:border-0';
      btn.onclick = () => {
        closeDriveDropdown();
        loadDirectory(d.root);
      };

      let usedPct = 0;
      let usageSub = '';
      if (d.total_gb > 0) {
        const usedGb = (d.total_gb - d.free_gb).toFixed(1);
        usedPct = Math.min(100, Math.round(((d.total_gb - d.free_gb) / d.total_gb) * 100));
        usageSub = `${d.free_gb} GB free of ${d.total_gb} GB`;
      }

      btn.innerHTML = `
        <div class="flex items-center justify-between w-full">
          <div class="flex items-center gap-2 min-w-0">
            <i data-lucide="hard-drive" class="w-4 h-4 text-brand-400 shrink-0"></i>
            <span class="font-bold text-slate-100 truncate">${escapeHtml(d.label)}</span>
          </div>
          <span class="font-mono text-brand-400 font-bold ml-2 shrink-0">${escapeHtml(d.letter)}</span>
        </div>
        ${d.total_gb > 0 ? `
          <div class="w-full space-y-1">
            <div class="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
              <div class="h-full rounded-full ${usedPct > 90 ? 'bg-red-500' : 'bg-brand-500'}" style="width: ${usedPct}%"></div>
            </div>
            <div class="flex justify-between text-[10px] text-slate-400 font-mono">
              <span>${usageSub}</span>
              <span>${usedPct}% used</span>
            </div>
          </div>
        ` : ''}
      `;
      driveList.appendChild(btn);
    });

    if (window.lucide) lucide.createIcons();
  } catch (err) {
    console.error('Failed to enumerate drives:', err);
  }
}

function toggleDriveDropdown() {
  const dd = document.getElementById('driveDropdown');
  dd.classList.toggle('hidden');
}

function closeDriveDropdown() {
  document.getElementById('driveDropdown').classList.add('hidden');
}

document.addEventListener('click', (e) => {
  const btn = document.getElementById('driveBtn');
  const dd = document.getElementById('driveDropdown');
  if (btn && dd && !btn.contains(e.target) && !dd.contains(e.target)) {
    dd.classList.add('hidden');
  }
});

// ============================================================
// Directory Loading & Rendering
// ============================================================

async function loadDirectory(path = '') {
  showLoadingSkeleton();
  deselectAll();

  try {
    const encPath = encodeURIComponent(path);
    const res = await apiFetch(`/api/fs/list?path=${encPath}`);
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Directory access error');
    }

    const data = await res.json();
    STATE.currentPath = data.current_path;
    STATE.parentPath = data.parent_path;
    STATE.items = data.items;

    // Update Drive label in header
    const currentDrive = STATE.drives.find(d => STATE.currentPath.toLowerCase().startsWith(d.root.toLowerCase()));
    document.getElementById('currentDriveLabel').textContent = currentDrive ? currentDrive.label : (data.breadcrumbs[0]?.name || 'Drives');

    // Update parent navigation button state
    document.getElementById('parentDirBtn').disabled = !STATE.parentPath;

    // Render breadcrumb navigation
    renderBreadcrumbs(data.breadcrumbs);

    // Update filter counts & render items
    updateFilterCounts();
    applyFilters();
  } catch (err) {
    showToast(err.message, 'error');
    renderItems([]);
  }
}

function refreshFolder() {
  loadDirectory(STATE.currentPath);
}

function navigateUp() {
  if (STATE.parentPath) {
    loadDirectory(STATE.parentPath);
  }
}

function renderBreadcrumbs(crumbs) {
  const container = document.getElementById('breadcrumbs');
  container.innerHTML = '';

  crumbs.forEach((crumb, idx) => {
    const isLast = idx === crumbs.length - 1;
    const btn = document.createElement('button');
    btn.className = `px-2.5 py-1 rounded-xl text-xs flex items-center gap-1 font-semibold transition touch-press ${
      isLast ? 'bg-brand-500/15 text-brand-400 border border-brand-500/30' : 'text-slate-400 hover:text-white hover:bg-surface-hover'
    }`;
    btn.textContent = crumb.name;
    btn.onclick = () => loadDirectory(crumb.path);
    container.appendChild(btn);

    if (!isLast) {
      const sep = document.createElement('span');
      sep.className = 'text-slate-600';
      sep.innerHTML = '<i data-lucide="chevron-right" class="w-3.5 h-3.5"></i>';
      container.appendChild(sep);
    }
  });

  if (window.lucide) lucide.createIcons();
  container.scrollLeft = container.scrollWidth;
}

// ============================================================
// Filtering, Search & Counts
// ============================================================

function updateFilterCounts() {
  const counts = { all: STATE.items.length, folder: 0, image: 0, video: 0, audio: 0, code: 0, archive: 0 };
  STATE.items.forEach(it => {
    if (counts[it.category] !== undefined) counts[it.category]++;
  });
  Object.keys(counts).forEach(k => {
    const el = document.getElementById(`count_${k}`);
    if (el) el.textContent = `(${counts[k]})`;
  });
}

function handleSearch(query) {
  STATE.searchQuery = query.toLowerCase().trim();
  const clearBtn = document.getElementById('clearSearchBtn');
  if (clearBtn) clearBtn.classList.toggle('hidden', !STATE.searchQuery);
  applyFilters();
}

function clearSearch() {
  document.getElementById('searchInput').value = '';
  const mob = document.getElementById('mobileSearchInput');
  if (mob) mob.value = '';
  document.getElementById('clearSearchBtn')?.classList.add('hidden');
  STATE.searchQuery = '';
  applyFilters();
}

function toggleMobileSearch() {
  const bar = document.getElementById('mobileSearchBar');
  bar.classList.toggle('hidden');
  if (!bar.classList.contains('hidden')) {
    document.getElementById('mobileSearchInput').focus();
  }
}

function setCategoryFilter(category) {
  STATE.categoryFilter = category;
  document.querySelectorAll('.cat-pill').forEach(btn => {
    const isActive = btn.getAttribute('data-cat') === category;
    btn.className = `cat-pill px-3 py-1 rounded-full font-semibold shrink-0 transition text-xs flex items-center gap-1 ${
      isActive ? 'bg-brand-500 text-white shadow-md shadow-brand-500/20' : 'bg-surface-input text-slate-400 hover:text-slate-200'
    }`;
  });
  applyFilters();
}

function applyFilters() {
  let list = STATE.items;

  if (STATE.categoryFilter !== 'all') {
    list = list.filter(item => item.category === STATE.categoryFilter);
  }

  if (STATE.searchQuery) {
    list = list.filter(item => item.name.toLowerCase().includes(STATE.searchQuery));
  }

  list.sort((a, b) => {
    if (a.is_dir && !b.is_dir) return -1;
    if (!a.is_dir && b.is_dir) return 1;
    return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' });
  });

  STATE.filteredItems = list;
  renderItems(list);
}

// ============================================================
// Item Rendering (Grid & List View)
// ============================================================

function renderItems(items) {
  const container = document.getElementById('fileContainer');
  const emptyState = document.getElementById('emptyState');

  container.innerHTML = '';
  if (items.length === 0) {
    emptyState.classList.remove('hidden');
    return;
  }
  emptyState.classList.add('hidden');

  if (STATE.viewMode === 'grid') {
    container.className = 'grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2.5 sm:gap-3.5';
    items.forEach(item => container.appendChild(createGridCard(item)));
  } else {
    container.className = 'flex flex-col divide-y divide-slate-800/80 bg-surface-card/60 border border-slate-800 rounded-3xl overflow-hidden';
    items.forEach(item => container.appendChild(createListRow(item)));
  }

  if (window.lucide) lucide.createIcons();
}

function createGridCard(item) {
  const isSelected = STATE.selectedPaths.has(item.path);
  const card = document.createElement('div');
  card.className = `group relative rounded-2xl p-3 flex flex-col items-center text-center transition cursor-pointer select-none touch-press border ${
    isSelected
      ? 'bg-brand-500/20 border-brand-500 shadow-lg shadow-brand-500/15'
      : 'bg-surface-card hover:bg-surface-hover border-slate-800 hover:border-slate-700 glow-card'
  }`;

  setupLongPress(card, () => openContextMenu(item));

  card.onclick = (e) => {
    if (e.target.closest('.action-btn') || e.target.closest('.select-checkbox')) return;
    if (STATE.isSelectMode) {
      toggleSelectItem(item.path);
    } else if (item.is_dir) {
      loadDirectory(item.path);
    } else {
      openPreviewModal(item);
    }
  };

  const iconMarkup = getItemIconMarkup(item, 'w-10 h-10');
  const sizeText = item.is_dir ? (item.child_count !== null ? `${item.child_count} items` : 'Folder') : formatBytes(item.size);

  card.innerHTML = `
    <!-- Checkbox in select mode -->
    <div class="absolute top-2 left-2 z-10 select-checkbox ${STATE.isSelectMode ? 'block' : 'hidden group-hover:block'}">
      <input type="checkbox" ${isSelected ? 'checked' : ''} onchange="toggleSelectItem('${escapeJs(item.path)}')"
             class="w-4 h-4 rounded text-brand-500 bg-surface-input border-slate-700 focus:ring-0 cursor-pointer">
    </div>

    <!-- 3-Dots Context Menu Button -->
    <button onclick="event.stopPropagation(); openContextMenu(${escapeJsonAttr(item)})"
            class="action-btn absolute top-2 right-2 p-1.5 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 transition">
      <i data-lucide="more-vertical" class="w-4 h-4"></i>
    </button>

    <!-- Thumbnail / Icon -->
    <div class="w-14 h-14 rounded-2xl bg-surface-input/80 flex items-center justify-center my-2 overflow-hidden shadow-inner shrink-0 border border-slate-800/60">
      ${iconMarkup}
    </div>

    <!-- Name & Meta -->
    <div class="w-full min-w-0 mt-1">
      <p class="text-xs font-bold text-slate-200 truncate group-hover:text-brand-400 transition" title="${escapeHtml(item.name)}">
        ${escapeHtml(item.name)}
      </p>
      <p class="text-[10px] text-slate-400 mt-0.5 truncate font-mono">${sizeText}</p>
    </div>
  `;

  return card;
}

function createListRow(item) {
  const isSelected = STATE.selectedPaths.has(item.path);
  const row = document.createElement('div');
  row.className = `group flex items-center justify-between px-4 py-3 hover:bg-surface-hover transition cursor-pointer select-none touch-press ${
    isSelected ? 'bg-brand-500/15' : ''
  }`;

  setupLongPress(row, () => openContextMenu(item));

  row.onclick = (e) => {
    if (e.target.closest('.action-btn') || e.target.closest('.select-checkbox')) return;
    if (STATE.isSelectMode) {
      toggleSelectItem(item.path);
    } else if (item.is_dir) {
      loadDirectory(item.path);
    } else {
      openPreviewModal(item);
    }
  };

  const iconMarkup = getItemIconMarkup(item, 'w-6 h-6');
  const sizeText = item.is_dir ? (item.child_count !== null ? `${item.child_count} items` : 'Folder') : formatBytes(item.size);
  const dateText = formatDate(item.modified);

  row.innerHTML = `
    <div class="flex items-center gap-3 min-w-0 pr-2">
      <!-- Checkbox -->
      <div class="select-checkbox ${STATE.isSelectMode ? 'block' : 'hidden sm:group-hover:block'}">
        <input type="checkbox" ${isSelected ? 'checked' : ''} onchange="toggleSelectItem('${escapeJs(item.path)}')"
               class="w-4 h-4 rounded text-brand-500 bg-surface-input border-slate-700 focus:ring-0 cursor-pointer">
      </div>

      <!-- Icon -->
      <div class="w-9 h-9 rounded-xl bg-surface-input flex items-center justify-center shrink-0 overflow-hidden border border-slate-800/60">
        ${iconMarkup}
      </div>

      <!-- Name & Meta -->
      <div class="min-w-0">
        <div class="text-xs sm:text-sm font-bold text-slate-200 truncate group-hover:text-brand-400 transition">
          ${escapeHtml(item.name)}
        </div>
        <div class="text-[10px] text-slate-400 sm:hidden flex items-center gap-2 font-mono mt-0.5">
          <span>${sizeText}</span>
          <span>•</span>
          <span>${dateText}</span>
        </div>
      </div>
    </div>

    <!-- Metadata & Context Button -->
    <div class="flex items-center gap-4 shrink-0 font-mono">
      <span class="text-xs text-slate-400 hidden sm:inline w-20 text-right">${sizeText}</span>
      <span class="text-xs text-slate-400 hidden md:inline w-32 text-right">${dateText}</span>
      <button onclick="event.stopPropagation(); openContextMenu(${escapeJsonAttr(item)})"
              class="action-btn p-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-700 transition">
        <i data-lucide="more-vertical" class="w-4 h-4"></i>
      </button>
    </div>
  `;

  return row;
}

function getItemIconMarkup(item, sizeClasses = 'w-8 h-8') {
  if (item.is_dir) {
    return `<i data-lucide="folder" class="${sizeClasses} text-amber-400 fill-amber-400/20"></i>`;
  }

  if (item.category === 'image') {
    const rawUrl = `/api/fs/raw?path=${encodeURIComponent(item.path)}&token=${STATE.authToken}`;
    return `<img src="${rawUrl}" loading="lazy" class="w-full h-full object-cover rounded-xl" onerror="this.onerror=null; this.parentElement.innerHTML='<i data-lucide=\\'image\\' class=\\'w-6 h-6 text-emerald-400\\'></i>'">`;
  }

  switch (item.category) {
    case 'video':
      return `<i data-lucide="film" class="${sizeClasses} text-rose-400"></i>`;
    case 'audio':
      return `<i data-lucide="music" class="${sizeClasses} text-violet-400"></i>`;
    case 'code':
      return `<i data-lucide="code-2" class="${sizeClasses} text-cyan-400"></i>`;
    case 'pdf':
      return `<i data-lucide="file-text" class="${sizeClasses} text-red-400"></i>`;
    case 'archive':
      return `<i data-lucide="archive" class="${sizeClasses} text-amber-500"></i>`;
    case 'text':
      return `<i data-lucide="file-text" class="${sizeClasses} text-slate-300"></i>`;
    case 'document':
      return `<i data-lucide="file-spreadsheet" class="${sizeClasses} text-brand-400"></i>`;
    case 'executable':
      return `<i data-lucide="binary" class="${sizeClasses} text-teal-400"></i>`;
    default:
      return `<i data-lucide="file" class="${sizeClasses} text-slate-400"></i>`;
  }
}

function showLoadingSkeleton() {
  const container = document.getElementById('fileContainer');
  const glyphs = ['✦', '◆', '✶', '❋', '✸'];
  const glyph = glyphs[Math.floor(Math.random() * glyphs.length)];
  container.innerHTML = `
    <div class="col-span-full py-20 flex flex-col items-center justify-center text-slate-400">
      <div class="text-2xl text-brand-400 animate-spin mb-2">${glyph}</div>
      <p class="text-xs font-mono tracking-wider">READING FILESYSTEM...</p>
    </div>
  `;
}

// ============================================================
// Multi-Selection State & Actions
// ============================================================

function toggleSelectionMode() {
  STATE.isSelectMode = !STATE.isSelectMode;
  document.getElementById('selectModeBtn').classList.toggle('bg-brand-500/30', STATE.isSelectMode);
  document.getElementById('selectModeBtn').classList.toggle('text-brand-400', STATE.isSelectMode);
  if (!STATE.isSelectMode) deselectAll();
  applyFilters();
}

function toggleSelectItem(path) {
  if (STATE.selectedPaths.has(path)) {
    STATE.selectedPaths.delete(path);
  } else {
    STATE.selectedPaths.add(path);
  }
  updateSelectionUI();
  applyFilters();
}

function selectAll() {
  STATE.filteredItems.forEach(item => STATE.selectedPaths.add(item.path));
  updateSelectionUI();
  applyFilters();
}

function deselectAll() {
  STATE.selectedPaths.clear();
  updateSelectionUI();
}

function updateSelectionUI() {
  const bar = document.getElementById('batchActionBar');
  const badge = document.getElementById('selectedCountBadge');
  const count = STATE.selectedPaths.size;

  if (count > 0) {
    bar.classList.remove('hidden');
    badge.textContent = count;
  } else {
    bar.classList.add('hidden');
  }
}

async function batchDelete() {
  const paths = Array.from(STATE.selectedPaths);
  if (paths.length === 0) return;
  openDeleteModal(paths, `${paths.length} selected items`);
}

function batchClipboard(isCut) {
  const paths = Array.from(STATE.selectedPaths);
  if (paths.length === 0) return;
  setClipboard(paths, isCut);
  deselectAll();
}

async function batchDownloadZip() {
  const paths = Array.from(STATE.selectedPaths);
  if (paths.length === 0) return;

  showToast('Packaging items into ZIP...', 'info');
  try {
    const res = await apiFetch('/api/fs/download-zip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paths })
    });
    if (!res.ok) throw new Error('ZIP archive creation failed');

    const blob = await res.blob();
    const downloadUrl = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = downloadUrl;
    a.download = `bundle_${Date.now()}.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    showToast('Download started', 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// ============================================================
// Clipboard Operations (Copy / Cut / Paste)
// ============================================================

function setClipboard(sources, isCut) {
  STATE.clipboard = { sources, isCut };
  localStorage.setItem('wfm_clipboard', JSON.stringify(STATE.clipboard));
  updateClipboardUI();
  showToast(`${isCut ? 'Cut' : 'Copied'} ${sources.length} item(s)`, 'info');
}

function updateClipboardUI() {
  const hasItems = STATE.clipboard && STATE.clipboard.sources && STATE.clipboard.sources.length > 0;
  const count = hasItems ? STATE.clipboard.sources.length : 0;

  const mobBtn = document.getElementById('mobilePasteBtn');
  const deskBtn = document.getElementById('desktopPasteBtn');
  const mobBadge = document.getElementById('mobileClipboardBadge');
  const deskCount = document.getElementById('desktopClipboardCount');

  if (hasItems) {
    mobBtn.classList.remove('hidden');
    deskBtn.classList.remove('hidden');
    if (mobBadge) mobBadge.textContent = count;
    if (deskCount) deskCount.textContent = count;
  } else {
    mobBtn.classList.add('hidden');
    deskBtn.classList.add('hidden');
  }
}

async function pasteClipboard() {
  if (!STATE.clipboard || !STATE.clipboard.sources || STATE.clipboard.sources.length === 0) return;

  const { sources, isCut } = STATE.clipboard;
  showToast(`Pasting ${sources.length} item(s)...`, 'info');

  try {
    const res = await apiFetch('/api/fs/clipboard/paste', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sources,
        dest_dir: STATE.currentPath,
        is_cut: isCut
      })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Paste failed');
    }

    showToast('Paste completed successfully', 'success');
    if (isCut) {
      STATE.clipboard = null;
      localStorage.removeItem('wfm_clipboard');
      updateClipboardUI();
    }
    refreshFolder();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// ============================================================
// Item Context Menu / Bottom Sheet
// ============================================================

function openContextMenu(item) {
  STATE.contextItem = item;
  document.getElementById('contextItemName').textContent = item.name;
  document.getElementById('contextItemMeta').textContent = `${
    item.is_dir ? 'Folder' : formatBytes(item.size)
  } • Modified ${formatDate(item.modified)}`;

  const editBtn = document.getElementById('ctxEditBtn');
  const canEdit = !item.is_dir && (item.category === 'code' || item.category === 'text');
  editBtn.classList.toggle('hidden', !canEdit);

  const previewBtn = document.getElementById('ctxPreviewBtn');
  previewBtn.classList.toggle('hidden', item.is_dir);

  document.getElementById('ctxDownloadText').textContent = item.is_dir ? 'Download as ZIP' : 'Download';

  document.getElementById('contextBackdrop').classList.remove('hidden');
  document.getElementById('contextSheet').classList.remove('hidden');
  toggleModalScrollLock(true);
  if (window.lucide) lucide.createIcons();
}

function closeContextMenu() {
  document.getElementById('contextBackdrop').classList.add('hidden');
  document.getElementById('contextSheet').classList.add('hidden');
  toggleModalScrollLock(false);
  STATE.contextItem = null;
}

async function handleContextAction(action) {
  const item = STATE.contextItem;
  if (!item) return;
  closeContextMenu();

  switch (action) {
    case 'preview':
      openPreviewModal(item);
      break;
    case 'edit':
      openEditorModal(item.path);
      break;
    case 'download':
      if (item.is_dir) {
        STATE.selectedPaths.clear();
        STATE.selectedPaths.add(item.path);
        batchDownloadZip();
      } else {
        const url = `/api/fs/raw?path=${encodeURIComponent(item.path)}&download=true&token=${STATE.authToken}`;
        window.location.href = url;
      }
      break;
    case 'copy':
      setClipboard([item.path], false);
      break;
    case 'cut':
      setClipboard([item.path], true);
      break;
    case 'rename':
      openRenameModal(item);
      break;
    case 'delete':
      openDeleteModal([item.path], item.name);
      break;
  }
}

// ============================================================
// File Previewer Modal with Pinch-to-Zoom
// ============================================================

function openPreviewModal(item) {
  const modal = document.getElementById('previewModal');
  const title = document.getElementById('previewTitle');
  const body = document.getElementById('previewBody');
  const editBtn = document.getElementById('previewEditBtn');
  const dlBtn = document.getElementById('previewDownloadBtn');
  const zoomControls = document.getElementById('imageZoomControls');

  title.textContent = item.name;
  dlBtn.onclick = () => {
    window.location.href = `/api/fs/raw?path=${encodeURIComponent(item.path)}&download=true&token=${STATE.authToken}`;
  };

  const rawUrl = `/api/fs/raw?path=${encodeURIComponent(item.path)}&token=${STATE.authToken}`;
  body.innerHTML = '';

  const canEdit = item.category === 'code' || item.category === 'text';
  editBtn.classList.toggle('hidden', !canEdit);
  if (canEdit) {
    editBtn.onclick = () => {
      closePreviewModal();
      openEditorModal(item.path);
    };
  }

  // Reset zoom state
  STATE.zoomScale = 1.0;
  STATE.panX = 0;
  STATE.panY = 0;
  zoomControls.classList.add('hidden');

  modal.classList.remove('hidden');
  toggleModalScrollLock(true);

  if (item.category === 'image') {
    zoomControls.classList.remove('hidden');
    updateZoomPercentUI();

    body.innerHTML = `
      <div id="pinchViewport" class="pinch-viewport">
        <img id="pinchImg" src="${rawUrl}" class="pinch-image max-h-[82vh] max-w-full object-contain rounded-2xl shadow-2xl">
      </div>
    `;
    setupPinchToZoom();
  } else if (item.category === 'video') {
    body.innerHTML = `
      <video controls autoplay class="max-h-[80vh] max-w-full rounded-2xl shadow-2xl bg-black">
        <source src="${rawUrl}">
        Your browser does not support the video tag.
      </video>
    `;
  } else if (item.category === 'audio') {
    body.innerHTML = `
      <div class="bg-surface-card border border-slate-700/80 p-8 rounded-3xl shadow-2xl flex flex-col items-center gap-4 w-full max-w-md glow-hydra">
        <div class="w-20 h-20 rounded-2xl bg-violet-600/20 text-violet-400 flex items-center justify-center">
          <i data-lucide="music" class="w-10 h-10"></i>
        </div>
        <h4 class="font-bold text-slate-100 text-center truncate max-w-xs">${escapeHtml(item.name)}</h4>
        <audio controls autoplay class="w-full">
          <source src="${rawUrl}">
        </audio>
      </div>
    `;
  } else if (item.category === 'pdf') {
    body.innerHTML = `<iframe src="${rawUrl}" class="w-full h-[82vh] rounded-2xl border border-slate-800 shadow-2xl"></iframe>`;
  } else if (canEdit) {
    body.innerHTML = `
      <div class="w-full h-[80vh] flex flex-col bg-surface-card border border-slate-800 rounded-3xl overflow-hidden shadow-2xl">
        <div class="px-4 py-2.5 bg-surface-window border-b border-slate-800 flex justify-between items-center text-xs text-slate-400 font-mono">
          <span>Read-only View</span>
          <button onclick="navigator.clipboard.writeText(document.getElementById('previewTextContent').innerText); showToast('Copied to clipboard', 'info');" class="hover:text-white flex items-center gap-1">
            <i data-lucide="copy" class="w-3.5 h-3.5"></i> Copy
          </button>
        </div>
        <pre class="flex-1 p-4 overflow-auto font-mono text-xs text-slate-300 leading-relaxed whitespace-pre-wrap"><code id="previewTextContent">Loading content...</code></pre>
      </div>
    `;
    apiFetch(`/api/fs/text?path=${encodeURIComponent(item.path)}`)
      .then(res => res.json())
      .then(data => {
        const el = document.getElementById('previewTextContent');
        if (el) el.textContent = data.content;
      })
      .catch(err => {
        const el = document.getElementById('previewTextContent');
        if (el) el.textContent = 'Failed to load text: ' + err.message;
      });
  } else {
    body.innerHTML = `
      <div class="text-center p-8 bg-surface-card border border-slate-800 rounded-3xl max-w-sm">
        <i data-lucide="file" class="w-12 h-12 text-slate-500 mx-auto mb-3"></i>
        <h4 class="font-bold text-slate-200">${escapeHtml(item.name)}</h4>
        <p class="text-xs text-slate-400 mt-1 mb-4">No in-browser preview available.</p>
        <button onclick="window.location.href='${rawUrl}&download=true'" class="px-5 py-2.5 rounded-2xl bg-brand-500 hover:bg-brand-600 text-white text-xs font-bold shadow-lg shadow-brand-500/20">Download File</button>
      </div>
    `;
  }

  if (window.lucide) lucide.createIcons();
}

function closePreviewModal() {
  const modal = document.getElementById('previewModal');
  const body = document.getElementById('previewBody');
  body.querySelectorAll('video, audio').forEach(el => el.pause());
  body.innerHTML = '';
  modal.classList.add('hidden');
  toggleModalScrollLock(false);
}

// Pinch-to-zoom & pan implementation
function setupPinchToZoom() {
  const viewport = document.getElementById('pinchViewport');
  const img = document.getElementById('pinchImg');
  if (!viewport || !img) return;

  function applyTransform() {
    img.style.transform = `translate(${STATE.panX}px, ${STATE.panY}px) scale(${STATE.zoomScale})`;
    updateZoomPercentUI();
  }

  // Wheel zoom on desktop
  viewport.addEventListener('wheel', (e) => {
    e.preventDefault();
    const delta = e.deltaY < 0 ? 0.2 : -0.2;
    STATE.zoomScale = Math.min(5.0, Math.max(0.5, STATE.zoomScale + delta));
    applyTransform();
  }, { passive: false });

  // Touch handlers for mobile
  viewport.addEventListener('touchstart', (e) => {
    if (e.touches.length === 2) {
      STATE.touchInitialDist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
      STATE.touchInitialScale = STATE.zoomScale;
    } else if (e.touches.length === 1 && STATE.zoomScale > 1.0) {
      STATE.isPanning = true;
      STATE.startPanX = e.touches[0].clientX - STATE.panX;
      STATE.startPanY = e.touches[0].clientY - STATE.panY;
    }
  }, { passive: true });

  viewport.addEventListener('touchmove', (e) => {
    if (e.touches.length === 2 && STATE.touchInitialDist > 0) {
      const currentDist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
      const ratio = currentDist / STATE.touchInitialDist;
      STATE.zoomScale = Math.min(5.0, Math.max(0.5, STATE.touchInitialScale * ratio));
      applyTransform();
    } else if (e.touches.length === 1 && STATE.isPanning) {
      STATE.panX = e.touches[0].clientX - STATE.startPanX;
      STATE.panY = e.touches[0].clientY - STATE.startPanY;
      applyTransform();
    }
  }, { passive: true });

  viewport.addEventListener('touchend', (e) => {
    if (e.touches.length < 2) STATE.touchInitialDist = 0;
    if (e.touches.length === 0) STATE.isPanning = false;
  });
}

function adjustImageZoom(amount) {
  STATE.zoomScale = Math.min(5.0, Math.max(0.5, STATE.zoomScale + amount));
  const img = document.getElementById('pinchImg');
  if (img) img.style.transform = `translate(${STATE.panX}px, ${STATE.panY}px) scale(${STATE.zoomScale})`;
  updateZoomPercentUI();
}

function resetImageZoom() {
  STATE.zoomScale = 1.0;
  STATE.panX = 0;
  STATE.panY = 0;
  const img = document.getElementById('pinchImg');
  if (img) img.style.transform = `translate(0px, 0px) scale(1)`;
  updateZoomPercentUI();
}

function updateZoomPercentUI() {
  const el = document.getElementById('zoomPercentText');
  if (el) el.textContent = `${Math.round(STATE.zoomScale * 100)}%`;
}

function editFromPreview() {
  const path = STATE.activeEditorPath;
  closePreviewModal();
  if (STATE.contextItem) openEditorModal(STATE.contextItem.path);
}

// ============================================================
// In-Browser Code / Text Editor
// ============================================================

async function openEditorModal(filePath) {
  STATE.activeEditorPath = filePath;
  STATE.editorDirty = false;
  document.getElementById('editorTitle').textContent = filePath.split(/[\\/]/).pop();
  document.getElementById('editorStatus').textContent = 'Loading...';
  document.getElementById('editorTextarea').value = '';
  document.getElementById('editorModal').classList.remove('hidden');
  toggleModalScrollLock(true);

  try {
    const res = await apiFetch(`/api/fs/text?path=${encodeURIComponent(filePath)}`);
    if (!res.ok) throw new Error('Failed to load file');
    const data = await res.json();
    document.getElementById('editorTextarea').value = data.content;
    document.getElementById('editorStatus').textContent = 'Saved';
    document.getElementById('editorStatus').className = 'text-[9px] uppercase font-mono font-bold tracking-wider px-2 py-0.5 rounded-full bg-slate-800 text-slate-400';
  } catch (err) {
    showToast(err.message, 'error');
    closeEditorModal();
  }
}

function markEditorDirty() {
  if (!STATE.editorDirty) {
    STATE.editorDirty = true;
    document.getElementById('editorStatus').textContent = 'Modified';
    document.getElementById('editorStatus').className = 'text-[9px] uppercase font-mono font-bold tracking-wider px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400';
  }
}

async function saveEditorContent() {
  if (!STATE.activeEditorPath) return;
  const content = document.getElementById('editorTextarea').value;

  try {
    const res = await apiFetch('/api/fs/text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: STATE.activeEditorPath,
        content
      })
    });
    if (!res.ok) throw new Error('Save failed');

    STATE.editorDirty = false;
    document.getElementById('editorStatus').textContent = 'Saved';
    document.getElementById('editorStatus').className = 'text-[9px] uppercase font-mono font-bold tracking-wider px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400';
    showToast('File saved successfully', 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function closeEditorModal() {
  if (STATE.editorDirty && !confirm('You have unsaved changes. Discard them?')) return;
  document.getElementById('editorModal').classList.add('hidden');
  toggleModalScrollLock(false);
  STATE.activeEditorPath = '';
  STATE.editorDirty = false;
}

// ============================================================
// Creation & Rename Modals
// ============================================================

function openNewFolderModal() {
  openInputModal('Create New Folder', '', async (name) => {
    try {
      const res = await apiFetch('/api/fs/folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dir_path: STATE.currentPath, name })
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Folder creation failed');
      }
      showToast(`Created folder "${name}"`, 'success');
      refreshFolder();
    } catch (err) {
      showToast(err.message, 'error');
    }
  });
}

function openNewFileModal() {
  openInputModal('Create New File', '', async (name) => {
    try {
      const res = await apiFetch('/api/fs/file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dir_path: STATE.currentPath, name, content: '' })
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'File creation failed');
      }
      showToast(`Created file "${name}"`, 'success');
      refreshFolder();
    } catch (err) {
      showToast(err.message, 'error');
    }
  });
}

function openRenameModal(item) {
  openInputModal(`Rename ${item.is_dir ? 'Folder' : 'File'}`, item.name, async (newName) => {
    try {
      const res = await apiFetch('/api/fs/rename', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: item.path, new_name: newName })
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Rename failed');
      }
      showToast(`Renamed to "${newName}"`, 'success');
      refreshFolder();
    } catch (err) {
      showToast(err.message, 'error');
    }
  });
}

function openInputModal(title, initialValue, onConfirm) {
  document.getElementById('inputModalTitle').textContent = title;
  const field = document.getElementById('inputModalField');
  field.value = initialValue;
  document.getElementById('inputModal').classList.remove('hidden');
  toggleModalScrollLock(true);
  field.focus();

  document.getElementById('inputModalConfirmBtn').onclick = () => {
    const val = field.value.trim();
    if (val) {
      closeInputModal();
      onConfirm(val);
    }
  };
}

function closeInputModal() {
  document.getElementById('inputModal').classList.add('hidden');
  toggleModalScrollLock(false);
}

// ============================================================
// Deletion Modal
// ============================================================

function openDeleteModal(paths, label) {
  document.getElementById('deleteItemPrompt').textContent = `Delete ${label}?`;
  document.getElementById('deleteModal').classList.remove('hidden');
  toggleModalScrollLock(true);

  document.getElementById('deleteConfirmBtn').onclick = async () => {
    const permanent = document.getElementById('deleteModePermanent').checked;
    closeDeleteModal();
    showToast(`Deleting ${paths.length} item(s)...`, 'info');

    try {
      const res = await apiFetch('/api/fs/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paths, permanent })
      });
      const data = await res.json();
      if (data.errors && data.errors.length > 0) {
        showToast(`Deletion error: ${data.errors[0].error}`, 'error');
      } else {
        showToast(`Successfully deleted ${paths.length} item(s)`, 'success');
      }
      deselectAll();
      refreshFolder();
    } catch (err) {
      showToast(err.message, 'error');
    }
  };
}

function closeDeleteModal() {
  document.getElementById('deleteModal').classList.add('hidden');
  toggleModalScrollLock(false);
}

// ============================================================
// File Upload & Drag-and-Drop
// ============================================================

function openUploadModal() {
  document.getElementById('uploadProgressContainer').classList.add('hidden');
  document.getElementById('uploadModal').classList.remove('hidden');
  toggleModalScrollLock(true);
}

function closeUploadModal() {
  document.getElementById('uploadModal').classList.add('hidden');
  toggleModalScrollLock(false);
}

function handleFileSelected(event) {
  const files = event.target.files;
  if (!files || files.length === 0) return;
  uploadFilesList(files);
}

function setupDragAndDrop() {
  window.addEventListener('dragover', (e) => e.preventDefault());
  window.addEventListener('drop', (e) => {
    e.preventDefault();
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      uploadFilesList(e.dataTransfer.files);
    }
  });
}

function uploadFilesList(files) {
  const formData = new FormData();
  formData.append('dir_path', STATE.currentPath);
  for (let i = 0; i < files.length; i++) {
    formData.append('files', files[i]);
  }

  const pContainer = document.getElementById('uploadProgressContainer');
  const pBar = document.getElementById('uploadProgressBar');
  const pText = document.getElementById('uploadPercent');
  const pStatus = document.getElementById('uploadStatusText');

  pContainer.classList.remove('hidden');
  pBar.style.width = '0%';
  pText.textContent = '0%';
  pStatus.textContent = `Uploading ${files.length} file(s)...`;

  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/fs/upload', true);
  if (STATE.authToken) {
    xhr.setRequestHeader('X-Auth-Token', STATE.authToken);
  }

  xhr.upload.onprogress = (e) => {
    if (e.lengthComputable) {
      const pct = Math.round((e.loaded / e.total) * 100);
      pBar.style.width = `${pct}%`;
      pText.textContent = `${pct}%`;
    }
  };

  xhr.onload = () => {
    if (xhr.status === 200) {
      showToast(`Uploaded ${files.length} file(s) successfully!`, 'success');
      closeUploadModal();
      refreshFolder();
    } else {
      showToast('Upload error: ' + xhr.responseText, 'error');
    }
  };

  xhr.onerror = () => showToast('Network error during upload', 'error');
  xhr.send(formData);
}

// ============================================================
// Mobile QR Code Modal
// ============================================================

async function openQrModal() {
  const modal = document.getElementById('qrModal');
  const urlDisplay = document.getElementById('qrUrlText');
  const qrcodeCanvas = document.getElementById('qrcodeCanvas');

  try {
    const res = await apiFetch('/api/network/qr');
    const data = await res.json();
    urlDisplay.textContent = data.mobile_url;

    qrcodeCanvas.innerHTML = '';
    new QRCode(qrcodeCanvas, {
      text: data.mobile_url,
      width: 180,
      height: 180,
      colorDark: '#090d16',
      colorLight: '#ffffff',
      correctLevel: QRCode.CorrectLevel.H
    });

    modal.classList.remove('hidden');
    toggleModalScrollLock(true);
  } catch (err) {
    showToast('Failed to generate QR code', 'error');
  }
}

function closeQrModal() {
  document.getElementById('qrModal').classList.add('hidden');
  toggleModalScrollLock(false);
}

function copyQrUrl() {
  const url = document.getElementById('qrUrlText').textContent;
  navigator.clipboard.writeText(url);
  showToast('Copied Mobile URL to clipboard!', 'info');
}

// ============================================================
// View Mode Toggle (Grid vs List)
// ============================================================

function toggleViewMode() {
  STATE.viewMode = STATE.viewMode === 'grid' ? 'list' : 'grid';
  localStorage.setItem('wfm_viewMode', STATE.viewMode);
  updateViewToggleUI();
  applyFilters();
}

function updateViewToggleUI() {
  const icon = document.getElementById('viewToggleIcon');
  if (icon) {
    icon.setAttribute('data-lucide', STATE.viewMode === 'grid' ? 'layout-list' : 'layout-grid');
    if (window.lucide) lucide.createIcons();
  }
}

// ============================================================
// Helpers & Utilities
// ============================================================

function formatBytes(bytes, decimals = 1) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

function formatDate(epochSec) {
  if (!epochSec) return '';
  const d = new Date(epochSec * 1000);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/[&<>'"]/g, tag => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    "'": '&#39;',
    '"': '&quot;'
  }[tag] || tag));
}

function escapeJs(str) {
  if (!str) return '';
  return str.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

function escapeJsonAttr(obj) {
  return JSON.stringify(obj).replace(/"/g, '&quot;');
}

function setupLongPress(element, callback, delay = 500) {
  let timer;
  element.addEventListener('touchstart', () => {
    timer = setTimeout(callback, delay);
  }, { passive: true });
  element.addEventListener('touchend', () => clearTimeout(timer));
  element.addEventListener('touchmove', () => clearTimeout(timer));
}

function setupKeyboardShortcuts() {
  window.addEventListener('keydown', (e) => {
    // Focus search on '/'
    if (e.key === '/' && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
      e.preventDefault();
      document.getElementById('searchInput')?.focus();
    }
    // Save editor on Ctrl+S
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      const editorModal = document.getElementById('editorModal');
      if (!editorModal.classList.contains('hidden')) {
        e.preventDefault();
        saveEditorContent();
      }
    }
    // Escape to close all modals
    if (e.key === 'Escape') {
      closeContextMenu();
      closePreviewModal();
      closeInputModal();
      closeDeleteModal();
      closeUploadModal();
      closeQrModal();
    }
  });
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  const colors = {
    info: 'bg-brand-500/90 text-white border-brand-400/50 shadow-brand-500/20',
    success: 'bg-emerald-600/90 text-white border-emerald-500/50 shadow-emerald-500/20',
    error: 'bg-red-600/90 text-white border-red-500/50 shadow-red-500/20'
  };

  toast.className = `p-3.5 rounded-2xl border backdrop-blur-md shadow-2xl text-xs font-bold flex items-center justify-between gap-3 pointer-events-auto transition-all transform duration-300 translate-y-2 opacity-0 glow-hydra ${colors[type] || colors.info}`;
  toast.innerHTML = `
    <span>${escapeHtml(message)}</span>
    <button onclick="this.parentElement.remove()" class="p-1 opacity-75 hover:opacity-100">&times;</button>
  `;

  container.appendChild(toast);
  requestAnimationFrame(() => {
    toast.classList.remove('translate-y-2', 'opacity-0');
  });

  setTimeout(() => {
    toast.classList.add('opacity-0', 'translate-y-2');
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}
