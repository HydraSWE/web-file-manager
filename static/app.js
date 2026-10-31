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
  sortBy: localStorage.getItem('wfm_sortBy') || 'name', // 'name' | 'date' | 'size' | 'type'
  sortOrder: localStorage.getItem('wfm_sortOrder') || 'asc', // 'asc' | 'desc' 
  categoryFilter: 'all',
  favorites: [],
  favoritePaths: new Set(),
  previewItem: null,
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
  setupClipboardButtonInteractions();

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

    if (config.auth_required) {
      let tokenValid = false;
      if (STATE.authToken) {
        try {
          const checkRes = await fetch('/api/drives', {
            headers: { 'X-Auth-Token': STATE.authToken }
          });
          if (checkRes.ok) tokenValid = true;
        } catch (e) {}
      }
      if (!tokenValid) {
        STATE.authToken = '';
        localStorage.removeItem('wfm_token');
        showAuthModal();
        return;
      }
    }
  } catch (err) {
    console.error('Config fetch error:', err);
  }

  await fetchFavorites();
  await fetchDrives();
  await loadDirectory('');
});

// Modal scroll lock helper
function toggleModalScrollLock(isOpen) {
  if (isOpen) {
    document.body.classList.add('modal-open');
  } else {
    // Only remove if no other modal is currently visible
    const openModals = document.querySelectorAll('#previewModal:not(.hidden), #editorModal:not(.hidden), #uploadModal:not(.hidden), #inputModal:not(.hidden), #deleteModal:not(.hidden), #qrModal:not(.hidden), #authModal:not(.hidden), #contextSheet:not(.hidden), #pasteConfirmModal:not(.hidden), #clipboardInspectorModal:not(.hidden)');
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
      await fetchFavorites();
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
    btn.className = `px-2.5 py-1 rounded-xl text-xs flex items-center gap-1.5 font-semibold transition touch-press ${
      isLast ? 'bg-brand-500/15 text-brand-400 border border-brand-500/30' : 'text-slate-400 hover:text-white hover:bg-surface-hover'
    }`;

    let iconHtml = '';
    if (crumb.has_custom_icon) {
      const iconUrl = `/api/fs/folder-icon?path=${encodeURIComponent(crumb.path)}&token=${STATE.authToken}`;
      iconHtml = `<img src="${iconUrl}" class="w-3.5 h-3.5 object-contain rounded-sm shrink-0" onerror="this.remove()">`;
    } else if (crumb.is_drive) {
      iconHtml = `<i data-lucide="hard-drive" class="w-3 h-3 text-slate-400 shrink-0"></i>`;
    }

    btn.innerHTML = `${iconHtml}<span>${escapeHtml(crumb.name)}</span>`;
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
  const counts = { all: STATE.items.length, folder: 0, image: 0, video: 0, audio: 0, code: 0, archive: 0, favorites: 0 };
  STATE.items.forEach(it => {
    if (counts[it.category] !== undefined) counts[it.category]++;
    if (STATE.favoritePaths.has(normalizePath(it.path))) counts.favorites++;
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

  if (STATE.categoryFilter === 'favorites') {
    list = list.filter(item => STATE.favoritePaths.has(normalizePath(item.path)));
  } else if (STATE.categoryFilter !== 'all') {
    list = list.filter(item => item.category === STATE.categoryFilter);
  }

  if (STATE.searchQuery) {
    list = list.filter(item => item.name.toLowerCase().includes(STATE.searchQuery));
  }

  list.sort((a, b) => {
    // 1. Folders first
    if (a.is_dir && !b.is_dir) return -1;
    if (!a.is_dir && b.is_dir) return 1;

    // 2. Pinned items float to top of their section
    const isPinnedA = STATE.favoritePaths.has(normalizePath(a.path));
    const isPinnedB = STATE.favoritePaths.has(normalizePath(b.path));
    if (isPinnedA !== isPinnedB) {
      return isPinnedA ? -1 : 1;
    }

    let res = 0;
    if (STATE.sortBy === 'name') {
      res = a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' });
    } else if (STATE.sortBy === 'date') {
      res = (a.modified || 0) - (b.modified || 0);
    } else if (STATE.sortBy === 'size') {
      res = (a.size || 0) - (b.size || 0);
    } else if (STATE.sortBy === 'type') {
      const extA = (a.extension || '').toLowerCase();
      const extB = (b.extension || '').toLowerCase();
      res = extA.localeCompare(extB) || a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' });
    }

    return STATE.sortOrder === 'desc' ? -res : res;
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

    <!-- Pinned Star Badge -->
    ${STATE.favoritePaths.has(normalizePath(item.path)) ? `
    <div class="absolute top-2 right-8 text-amber-400 z-10 p-1 drop-shadow" title="Pinned Favorite">
      <i data-lucide="star" class="w-3.5 h-3.5 fill-amber-400"></i>
    </div>` : ''}

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
        <div class="text-xs sm:text-sm font-bold text-slate-200 truncate group-hover:text-brand-400 transition flex items-center gap-1.5">
          <span>${escapeHtml(item.name)}</span>
          ${STATE.favoritePaths.has(normalizePath(item.path)) ? `<i data-lucide="star" class="w-3.5 h-3.5 text-amber-400 fill-amber-400 shrink-0" title="Pinned Favorite"></i>` : ''}
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
    if (item.has_custom_icon) {
      const iconUrl = `/api/fs/folder-icon?path=${encodeURIComponent(item.path)}&token=${STATE.authToken}`;
      return `<img src="${iconUrl}" loading="lazy" class="${sizeClasses} object-contain rounded-lg drop-shadow" onerror="this.onerror=null; this.parentElement.innerHTML='<i data-lucide=\\'folder\\' class=\\'${sizeClasses} text-amber-400 fill-amber-400/20\\'></i>'; if(window.lucide)lucide.createIcons();">`;
    }
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

function getPathName(p) {
  if (!p) return '';
  const clean = String(p).replace(/[\\/]+$/, '');
  const parts = clean.split(/[\\/]/);
  return parts.pop() || clean;
}

function getClipboardItems() {
  if (!STATE.clipboard || !Array.isArray(STATE.clipboard.sources)) return [];
  return STATE.clipboard.sources.map(src => {
    if (typeof src === 'string') {
      return { path: src, name: getPathName(src) };
    }
    return {
      path: src.path,
      name: src.name || getPathName(src.path)
    };
  });
}

function setClipboard(sources, isCut) {
  STATE.clipboard = { sources, isCut };
  localStorage.setItem('wfm_clipboard', JSON.stringify(STATE.clipboard));
  updateClipboardUI();
  showToast(`${isCut ? 'Cut' : 'Copied'} ${sources.length} item(s)`, 'info');
}

function updateClipboardUI() {
  const items = getClipboardItems();
  const count = items.length;
  const hasItems = count > 0;

  const mobBtn = document.getElementById('mobilePasteBtn');
  const deskBtn = document.getElementById('desktopPasteBtn');
  const mobBadge = document.getElementById('mobileClipboardBadge');
  const deskCount = document.getElementById('desktopClipboardCount');

  if (mobBtn) mobBtn.classList.toggle('hidden', !hasItems);
  if (deskBtn) deskBtn.classList.toggle('hidden', !hasItems);
  if (mobBadge) mobBadge.textContent = count;
  if (deskCount) deskCount.textContent = count;

  setupClipboardButtonInteractions();
}

function setupClipboardButtonInteractions() {
  const mobBtn = document.getElementById('mobilePasteBtn');
  const deskBtn = document.getElementById('desktopPasteBtn');

  [mobBtn, deskBtn].forEach(btn => {
    if (!btn || btn._hasInteractions) return;
    btn._hasInteractions = true;

    let pressTimer = null;
    let didLongPress = false;

    // Mobile Touch
    btn.addEventListener('touchstart', (e) => {
      didLongPress = false;
      pressTimer = setTimeout(() => {
        didLongPress = true;
        if (navigator.vibrate) navigator.vibrate(40);
        openClipboardInspectorModal();
      }, 400);
    }, { passive: true });

    btn.addEventListener('touchend', (e) => {
      clearTimeout(pressTimer);
      if (didLongPress) {
        e.preventDefault();
        e.stopPropagation();
      }
    });

    btn.addEventListener('touchmove', () => {
      clearTimeout(pressTimer);
    });

    // Desktop Mouse
    btn.addEventListener('mousedown', (e) => {
      if (e.button !== 0) return;
      didLongPress = false;
      pressTimer = setTimeout(() => {
        didLongPress = true;
        openClipboardInspectorModal();
      }, 450);
    });

    btn.addEventListener('mouseup', () => {
      clearTimeout(pressTimer);
    });

    btn.addEventListener('mouseleave', () => {
      clearTimeout(pressTimer);
    });

    btn.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      openClipboardInspectorModal();
    });

    btn.onclick = (e) => {
      if (didLongPress) {
        didLongPress = false;
        e.preventDefault();
        e.stopPropagation();
        return;
      }
      openPasteConfirmModal();
    };
  });
}

function openPasteConfirmModal() {
  const items = getClipboardItems();
  if (items.length === 0) {
    showToast('Clipboard is empty', 'info');
    return;
  }

  const isCut = STATE.clipboard && STATE.clipboard.isCut;
  const modal = document.getElementById('pasteConfirmModal');
  const title = document.getElementById('pasteConfirmTitle');
  const target = document.getElementById('pasteConfirmTarget');
  const summary = document.getElementById('pasteConfirmSummary');
  const list = document.getElementById('pasteConfirmItemList');
  const btn = document.getElementById('pasteConfirmBtn');

  if (title) title.textContent = isCut ? 'Confirm Move (Cut)' : 'Confirm Paste (Copy)';
  if (btn) btn.textContent = isCut ? 'Move Here' : 'Paste Here';

  const destName = STATE.currentPath ? getPathName(STATE.currentPath) : 'Root Drive';
  if (target) target.textContent = `Into folder: "${destName}"`;
  if (summary) summary.textContent = `${items.length} item(s) to ${isCut ? 'move' : 'paste'}:`;

  if (list) {
    list.innerHTML = items.map(item => `
      <div class="flex items-center gap-2 py-1 px-2.5 rounded-xl bg-surface-card/60 border border-slate-800 text-xs">
        <i data-lucide="file" class="w-3.5 h-3.5 text-cyan-400 shrink-0"></i>
        <span class="font-semibold text-slate-200 truncate flex-1" title="${escapeHtml(item.path)}">${escapeHtml(item.name)}</span>
      </div>
    `).join('');
  }

  modal.classList.remove('hidden');
  toggleModalScrollLock(true);
  if (window.lucide) lucide.createIcons();
}

function closePasteConfirmModal() {
  const modal = document.getElementById('pasteConfirmModal');
  if (modal) modal.classList.add('hidden');
  toggleModalScrollLock(false);
}

function openClipboardInspectorModal() {
  const items = getClipboardItems();
  if (items.length === 0) {
    showToast('Clipboard is empty', 'info');
    return;
  }

  const isCut = STATE.clipboard && STATE.clipboard.isCut;
  const modal = document.getElementById('clipboardInspectorModal');
  const badge = document.getElementById('clipboardModeBadge');
  const countText = document.getElementById('clipboardItemCount');

  if (badge) {
    badge.textContent = isCut ? 'Cut (Move)' : 'Copy (Duplicate)';
    badge.className = isCut 
      ? 'text-[10px] font-mono px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-400 border border-amber-500/30 font-semibold'
      : 'text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 font-semibold';
  }
  if (countText) countText.textContent = `${items.length} item(s) on clipboard`;

  renderClipboardInspectorItems();

  modal.classList.remove('hidden');
  toggleModalScrollLock(true);
  if (window.lucide) lucide.createIcons();
}

function renderClipboardInspectorItems() {
  const items = getClipboardItems();
  const list = document.getElementById('clipboardItemsList');
  const countText = document.getElementById('clipboardItemCount');

  if (!list) return;
  if (countText) countText.textContent = `${items.length} item(s) on clipboard`;

  if (items.length === 0) {
    clearClipboardAction();
    return;
  }

  list.innerHTML = items.map((item, idx) => `
    <div class="flex items-center justify-between gap-2 p-2 hover:bg-surface-card/40 transition rounded-xl">
      <div class="min-w-0 flex items-center gap-2.5">
        <div class="w-7 h-7 rounded-lg bg-surface-card flex items-center justify-center shrink-0 border border-slate-800">
          <i data-lucide="file" class="w-3.5 h-3.5 text-cyan-400"></i>
        </div>
        <div class="min-w-0">
          <p class="text-xs font-bold text-slate-200 truncate" title="${escapeHtml(item.path)}">${escapeHtml(item.name)}</p>
          <p class="text-[10px] text-slate-400 font-mono truncate max-w-[220px] sm:max-w-[280px]">${escapeHtml(item.path)}</p>
        </div>
      </div>
      <button onclick="removeItemFromClipboard(${idx})" title="Remove item from clipboard" class="p-1.5 rounded-lg text-slate-400 hover:text-red-400 hover:bg-slate-800 transition">
        <i data-lucide="x" class="w-3.5 h-3.5"></i>
      </button>
    </div>
  `).join('');

  if (window.lucide) lucide.createIcons();
}

function closeClipboardInspectorModal() {
  const modal = document.getElementById('clipboardInspectorModal');
  if (modal) modal.classList.add('hidden');
  toggleModalScrollLock(false);
}

function clearClipboardAction() {
  STATE.clipboard = null;
  localStorage.removeItem('wfm_clipboard');
  updateClipboardUI();
  closePasteConfirmModal();
  closeClipboardInspectorModal();
  showToast('Clipboard cleared', 'info');
}

function removeItemFromClipboard(index) {
  if (!STATE.clipboard || !Array.isArray(STATE.clipboard.sources)) return;
  STATE.clipboard.sources.splice(index, 1);
  if (STATE.clipboard.sources.length === 0) {
    clearClipboardAction();
  } else {
    localStorage.setItem('wfm_clipboard', JSON.stringify(STATE.clipboard));
    updateClipboardUI();
    renderClipboardInspectorItems();
  }
}

async function executeConfirmedPaste() {
  closePasteConfirmModal();
  closeClipboardInspectorModal();

  if (!STATE.clipboard || !STATE.clipboard.sources || STATE.clipboard.sources.length === 0) return;

  const { sources, isCut } = STATE.clipboard;
  const paths = sources.map(s => typeof s === 'string' ? s : s.path);
  showToast(`Pasting ${paths.length} item(s)...`, 'info');

  try {
    const res = await apiFetch('/api/fs/clipboard/paste', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sources: paths,
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

async function pasteClipboard() {
  openPasteConfirmModal();
}

// ============================================================
// Item Context Menu / Bottom Sheet
// ============================================================

function openContextMenu(item) {
  STATE.contextItem = item;
  document.getElementById('contextItemName').textContent = item.name;

  const isPinned = STATE.favoritePaths.has(normalizePath(item.path));
  const pinText = document.getElementById('ctxPinText');
  const pinIcon = document.getElementById('ctxPinIcon');
  if (pinText && pinIcon) {
    if (isPinned) {
      pinText.textContent = 'Remove from Favorites';
      pinIcon.classList.add('fill-amber-400');
    } else {
      pinText.textContent = 'Pin to Favorites';
      pinIcon.classList.remove('fill-amber-400');
    }
  }
  document.getElementById('contextItemMeta').textContent = `${
    item.is_dir ? 'Folder' : formatBytes(item.size)
  } • Modified ${formatDate(item.modified)}`;

  const editBtn = document.getElementById('ctxEditBtn');
  const canEdit = !item.is_dir && (item.category === 'code' || item.category === 'text');
  editBtn.classList.toggle('hidden', !canEdit);

  const previewBtn = document.getElementById('ctxPreviewBtn');
  previewBtn.classList.toggle('hidden', item.is_dir);

  const folderIconBtn = document.getElementById('ctxFolderIconBtn');
  const folderIconResetBtn = document.getElementById('ctxFolderIconResetBtn');
  if (folderIconBtn) folderIconBtn.classList.toggle('hidden', !item.is_dir);
  if (folderIconResetBtn) folderIconResetBtn.classList.toggle('hidden', !item.is_dir || !item.has_custom_icon);

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
    case 'toggle_pin':
      togglePin(item);
      break;
    case 'set_folder_icon':
      STATE.folderIconTargetItem = item;
      document.getElementById('folderIconFileInput').click();
      break;
    case 'reset_folder_icon':
      resetFolderIcon(item.path);
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
      copyTextToClipboard(item.path);
      break;
    case 'copy_path':
      copyTextToClipboard(item.path);
      showToast('Path copied to clipboard', 'success');
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

async function uploadFolderIcon(file) {
  const item = STATE.folderIconTargetItem;
  if (!file || !item) return;
  const targetPath = item.path;
  const formData = new FormData();
  formData.append('path', targetPath);
  formData.append('file', file);

  showToast(`Updating Windows folder logo for "${item.name}"...`, 'info');
  try {
    const res = await apiFetch('/api/fs/folder-icon/set', {
      method: 'POST',
      body: formData
    });
    if (res.ok) {
      showToast('Folder logo updated successfully!', 'success');
      await loadDirectory(STATE.currentPath);
      await fetchFavorites();
    } else {
      const err = await res.json();
      showToast('Failed to set folder logo: ' + (err.detail || 'Unknown error'), 'error');
    }
  } catch (e) {
    showToast('Failed to upload logo: ' + e.message, 'error');
  } finally {
    const inp = document.getElementById('folderIconFileInput');
    if (inp) inp.value = '';
    STATE.folderIconTargetItem = null;
  }
}

async function resetFolderIcon(path) {
  if (!path) return;
  const formData = new FormData();
  formData.append('path', path);
  try {
    const res = await apiFetch('/api/fs/folder-icon/reset', {
      method: 'POST',
      body: formData
    });
    if (res.ok) {
      showToast('Reset to default folder icon', 'info');
      await loadDirectory(STATE.currentPath);
      await fetchFavorites();
    }
  } catch (e) {
    showToast('Error resetting icon: ' + e.message, 'error');
  }
}

// ============================================================
// File Previewer Modal with Pinch-to-Zoom
// ============================================================

function openPreviewModal(item) {
  STATE.previewItem = item;
  updatePreviewPinButton();
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
      closePasteConfirmModal();
      closeClipboardInspectorModal();
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
  const qrImg = document.getElementById('brandedQrImg');

  try {
    const res = await apiFetch('/api/network/qr');
    const data = await res.json();
    urlDisplay.textContent = data.mobile_url;

    if (qrImg && data.branded_qr_url) {
      qrImg.src = data.branded_qr_url;
    }

    modal.classList.remove('hidden');
    toggleModalScrollLock(true);
    if (window.lucide) lucide.createIcons();
  } catch (err) {
    showToast('Failed to load QR code', 'error');
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


// ============================================================
// File Sorting Controls
// ============================================================

function toggleSortMenu(e) {
  if (e) e.stopPropagation();
  const menu = document.getElementById('sortMenu');
  if (!menu) return;
  const isHidden = menu.classList.contains('hidden');
  if (isHidden) {
    updateSortMenuUI();
    menu.classList.remove('hidden');
  } else {
    menu.classList.add('hidden');
  }
}

function setSort(criterion) {
  if (STATE.sortBy === criterion) {
    STATE.sortOrder = STATE.sortOrder === 'asc' ? 'desc' : 'asc';
  } else {
    STATE.sortBy = criterion;
    STATE.sortOrder = (criterion === 'date' || criterion === 'size') ? 'desc' : 'asc';
  }
  localStorage.setItem('wfm_sortBy', STATE.sortBy);
  localStorage.setItem('wfm_sortOrder', STATE.sortOrder);
  updateSortMenuUI();
  applyFilters();
  const menu = document.getElementById('sortMenu');
  if (menu) menu.classList.add('hidden');
}

function toggleSortOrder(order) {
  STATE.sortOrder = order;
  localStorage.setItem('wfm_sortOrder', STATE.sortOrder);
  updateSortMenuUI();
  applyFilters();
  const menu = document.getElementById('sortMenu');
  if (menu) menu.classList.add('hidden');
}

function updateSortMenuUI() {
  document.querySelectorAll('.sort-opt').forEach(btn => {
    const sort = btn.dataset.sort;
    const isCurrent = STATE.sortBy === sort;
    const indicator = btn.querySelector('.sort-indicator');
    if (isCurrent) {
      btn.classList.add('text-brand-400', 'font-bold');
      btn.classList.remove('text-slate-300');
      if (indicator) {
        indicator.innerHTML = `<i data-lucide="${STATE.sortOrder === 'asc' ? 'arrow-up' : 'arrow-down'}" class="w-3.5 h-3.5"></i>`;
      }
    } else {
      btn.classList.remove('text-brand-400', 'font-bold');
      btn.classList.add('text-slate-300');
      if (indicator) indicator.innerHTML = '';
    }
  });

  document.querySelectorAll('.order-opt').forEach(btn => {
    const order = btn.dataset.order;
    const isCurrent = STATE.sortOrder === order;
    const indicator = btn.querySelector('.order-indicator');
    if (isCurrent) {
      btn.classList.add('text-brand-400', 'font-bold');
      btn.classList.remove('text-slate-300');
      if (indicator) indicator.innerHTML = '<i data-lucide="check" class="w-3.5 h-3.5"></i>';
    } else {
      btn.classList.remove('text-brand-400', 'font-bold');
      btn.classList.add('text-slate-300');
      if (indicator) indicator.innerHTML = '';
    }
  });

  const sortBtn = document.getElementById('sortBtn');
  if (sortBtn) {
    sortBtn.title = `Sorted by ${STATE.sortBy} (${STATE.sortOrder.toUpperCase()})`;
  }

  if (window.lucide) lucide.createIcons();
}

// Global click handler to dismiss dropdowns
document.addEventListener('click', (e) => {
  const sortMenu = document.getElementById('sortMenu');
  if (sortMenu && !sortMenu.classList.contains('hidden')) {
    if (!e.target.closest('#sortMenu') && !e.target.closest('#sortBtn')) {
      sortMenu.classList.add('hidden');
    }
  }
});


// ============================================================
// Pinned & Favorites Management
// ============================================================

function normalizePath(p) {
  if (!p) return '';
  return String(p).replace(/\\/g, '/').toLowerCase();
}

async function fetchFavorites() {
  try {
    const res = await apiFetch('/api/favorites');
    if (res.ok) {
      const data = await res.json();
      STATE.favorites = Array.isArray(data.favorites) ? data.favorites : [];
    } else {
      throw new Error('Favorites API response not OK');
    }
  } catch (err) {
    STATE.favorites = JSON.parse(localStorage.getItem('wfm_favorites') || '[]');
  }
  syncFavoritePaths();
  renderFavoritesShelf();
  updateFilterCounts();
}

function syncFavoritePaths() {
  STATE.favoritePaths = new Set(STATE.favorites.map(f => normalizePath(f.path)));
  try {
    localStorage.setItem('wfm_favorites', JSON.stringify(STATE.favorites));
  } catch (e) {}
}

async function togglePin(item) {
  if (!item || !item.path) return;
  const norm = normalizePath(item.path);
  const isPinned = STATE.favoritePaths.has(norm);

  if (isPinned) {
    STATE.favorites = STATE.favorites.filter(f => normalizePath(f.path) !== norm);
    showToast(`Unpinned "${item.name}" from favorites`, 'info');
  } else {
    STATE.favorites.push({
      path: item.path,
      name: item.name || item.path.split(/[\\/]/).pop() || item.path,
      is_dir: !!item.is_dir,
      has_custom_icon: !!item.has_custom_icon,
      pinned_at: Math.floor(Date.now() / 1000)
    });
    showToast(`⭐ Pinned "${item.name}" to favorites`, 'success');
  }

  syncFavoritePaths();
  renderFavoritesShelf();
  updateFilterCounts();
  applyFilters();

  try {
    const res = await apiFetch('/api/favorites/toggle', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        path: item.path,
        name: item.name,
        is_dir: item.is_dir
      })
    });
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data.favorites)) {
        STATE.favorites = data.favorites;
        syncFavoritePaths();
        renderFavoritesShelf();
        updateFilterCounts();
        applyFilters();
      }
    }
  } catch (e) {
    console.error('Server sync error for favorites:', e);
  }
}

function renderFavoritesShelf() {
  const shelf = document.getElementById('favoritesShelf');
  const list = document.getElementById('favoritesList');
  const badge = document.getElementById('favoritesCountBadge');
  if (!shelf || !list) return;

  if (STATE.favorites.length === 0) {
    shelf.classList.add('hidden');
    return;
  }

  shelf.classList.remove('hidden');
  if (badge) badge.textContent = STATE.favorites.length;

  list.innerHTML = '';
  STATE.favorites.forEach(fav => {
    const chip = document.createElement('div');
    chip.className = 'group flex items-center gap-2 px-3 py-1.5 rounded-xl bg-surface-card hover:bg-surface-hover border border-slate-700/80 hover:border-amber-500/50 shadow-sm transition shrink-0 cursor-pointer select-none touch-press';

    const isDir = fav.is_dir;
    let iconMarkup;
    if (isDir) {
      const iconUrl = `/api/fs/folder-icon?path=${encodeURIComponent(fav.path)}&token=${STATE.authToken}`;
      const showImg = fav.has_custom_icon;
      iconMarkup = `
        <span class="inline-flex items-center justify-center w-4 h-4 shrink-0 relative">
          <img src="${iconUrl}" 
               class="w-4 h-4 object-contain rounded-sm shrink-0" 
               style="${showImg ? '' : 'display:none;'}"
               onload="this.style.display='inline-block'; const f=this.nextElementSibling; if(f) f.style.display='none';" 
               onerror="this.style.display='none'; const f=this.nextElementSibling; if(f) f.style.display='inline-block';">
          <i data-lucide="folder" class="w-3.5 h-3.5 text-amber-400 fill-amber-400/20 shrink-0" style="${showImg ? 'display:none;' : ''}"></i>
        </span>
      `;
    } else {
      iconMarkup = '<i data-lucide="file" class="w-3.5 h-3.5 text-cyan-400 shrink-0"></i>';
    }

    chip.innerHTML = `
      ${iconMarkup}
      <span class="text-xs font-semibold text-slate-200 truncate max-w-[120px] sm:max-w-[180px]">${escapeHtml(fav.name)}</span>
      <button onclick="event.stopPropagation(); togglePin(${escapeJsonAttr(fav)})" title="Remove from favorites" class="text-slate-500 hover:text-amber-400 p-0.5 rounded-md hover:bg-slate-700/60 ml-0.5 transition">
        <i data-lucide="x" class="w-3 h-3"></i>
      </button>
    `;

    chip.onclick = (e) => {
      if (e.target.closest('button')) return;
      if (fav.is_dir) {
        loadDirectory(fav.path);
      } else {
        openPreviewModal(fav);
      }
    };

    list.appendChild(chip);
  });

  if (window.lucide) lucide.createIcons();
}

function updatePreviewPinButton() {
  const pinBtn = document.getElementById('previewPinBtn');
  const pinIcon = document.getElementById('previewPinIcon');
  if (!pinBtn || !pinIcon || !STATE.previewItem) return;

  const isPinned = STATE.favoritePaths.has(normalizePath(STATE.previewItem.path));
  if (isPinned) {
    pinIcon.classList.add('text-amber-400', 'fill-amber-400');
    pinIcon.classList.remove('text-slate-400');
    pinBtn.title = 'Remove from Favorites';
  } else {
    pinIcon.classList.remove('text-amber-400', 'fill-amber-400');
    pinIcon.classList.add('text-slate-400');
    pinBtn.title = 'Pin to Favorites';
  }
}

function togglePinCurrentPreview() {
  if (STATE.previewItem) {
    togglePin(STATE.previewItem);
    updatePreviewPinButton();
  }
}

async function batchTogglePin() {
  const selectedPaths = Array.from(STATE.selectedPaths);
  if (selectedPaths.length === 0) return;

  const allPinned = selectedPaths.every(p => STATE.favoritePaths.has(normalizePath(p)));
  const itemsToSync = [];

  for (const p of selectedPaths) {
    const norm = normalizePath(p);
    const item = STATE.items.find(i => normalizePath(i.path) === norm);
    const name = item ? item.name : (p.split(/[\\/]/).pop() || p);
    const isDir = item ? item.is_dir : false;

    if (allPinned) {
      STATE.favorites = STATE.favorites.filter(f => normalizePath(f.path) !== norm);
    } else {
      if (!STATE.favoritePaths.has(norm)) {
        STATE.favorites.push({
          path: p,
          name,
          is_dir: isDir,
          has_custom_icon: !!item?.has_custom_icon,
          pinned_at: Math.floor(Date.now() / 1000)
        });
      }
    }
    itemsToSync.push({ path: p, name, is_dir: isDir });
  }

  syncFavoritePaths();
  renderFavoritesShelf();
  updateFilterCounts();
  applyFilters();
  deselectAll();

  showToast(allPinned ? `Unpinned ${selectedPaths.length} items` : `⭐ Pinned ${selectedPaths.length} items to favorites`, 'success');

  try {
    const bRes = await apiFetch('/api/favorites/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items: itemsToSync, action: allPinned ? 'unpin' : 'pin' })
    });
    if (bRes.ok) {
      const bData = await bRes.json();
      if (Array.isArray(bData.favorites)) {
        STATE.favorites = bData.favorites;
        syncFavoritePaths();
        renderFavoritesShelf();
        updateFilterCounts();
        applyFilters();
      }
    }
  } catch (e) {
    console.error('Batch favorites sync error:', e);
  }
}

async function clearAllFavoritesPrompt() {
  if (STATE.favorites.length === 0) return;
  if (!confirm(`Are you sure you want to unpin all ${STATE.favorites.length} favorite items?`)) return;

  STATE.favorites = [];
  syncFavoritePaths();
  renderFavoritesShelf();
  updateFilterCounts();
  applyFilters();
  showToast('Cleared all pinned favorites', 'info');

  try {
    await apiFetch('/api/favorites/clear', {
      method: 'POST'
    });
  } catch (e) {
    console.error('Failed to clear favorites on server:', e);
  }
}

// Robust clipboard copy with HTTP/local Wi-Fi fallback
function copyTextToClipboard(text) {
  if (!text) return;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).catch(() => {
      fallbackCopyText(text);
    });
  } else {
    fallbackCopyText(text);
  }
}

function fallbackCopyText(text) {
  try {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    textarea.style.top = '-9999px';
    textarea.setAttribute('readonly', '');
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
  } catch (err) {
    console.warn('Fallback clipboard copy failed:', err);
  }
}
