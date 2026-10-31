// ============================================================
// HYDRA MULTITASKING EXECUTION ENGINE — CHAT HEADS & DRAWER
// ============================================================

const EXECUTABLE_EXTENSIONS = new Set(['.bat', '.cmd', '.ps1', '.py', '.exe']);
const TERMINAL_EXTENSIONS = new Set(['.bat', '.cmd', '.ps1', '.py']);

const CH_CONFIG = {
  SZ: 58,
  GAP: 66,
  colors: {
    bat: '#0284c7', // Cyan / Oceanic blue
    cmd: '#0284c7',
    py:  '#d97706', // Amber / Gold
    ps1: '#2563eb', // Indigo / PowerShell blue
    exe: '#7c3aed', // Purple
    default: '#0891b2'
  }
};

// Official Real Vector Logos
const CH_REAL_LOGOS = {
  py: `<svg viewBox="0 0 128 128" class="w-7 h-7" style="filter:drop-shadow(0 2px 4px rgba(0,0,0,0.5));">
         <path d="M63.7 0c-16.1 0-30.2 1.3-30.2 14.1v10.5h30.8v4.5H23.5C9.7 29.1 0 37.6 0 54.1c0 14.6 9.4 24.3 23.5 24.9h7.7v-10.9c0-8.9 7.7-16.5 16.5-16.5h30.8c7.3 0 13.2-6.1 13.2-13.4V14.1C91.7 1.3 79.8 0 63.7 0zm-8.8 8.6c2.7 0 4.8 2.2 4.8 4.8 0 2.7-2.2 4.8-4.8 4.8-2.7 0-4.8-2.2-4.8-4.8 0-2.7 2.1-4.8 4.8-4.8z" fill="#387eb8"/>
         <path d="M64.3 128c16.1 0 30.2-1.3 30.2-14.1V103.4H63.7v-4.5h40.8c13.8 0 23.5-8.5 23.5-25 0-14.6-9.4-24.3-23.5-24.9h-7.7v10.9c0 8.9-7.7 16.5-16.5 16.5H46c-7.3 0-13.2 6.1-13.2 13.4v19.1c0 12.8 11.9 14.1 28 14.1h3.5zm8.8-8.6c-2.7 0-4.8-2.2-4.8-4.8 0-2.7 2.2-4.8 4.8-4.8 2.7 0 4.8 2.2 4.8 4.8 0 2.7-2.1 4.8-4.8 4.8z" fill="#ffe052"/>
       </svg>`,
  bat: `<svg viewBox="0 0 24 24" class="w-6 h-6" style="filter:drop-shadow(0 2px 4px rgba(0,0,0,0.5));">
          <rect width="22" height="18" x="1" y="3" rx="4" fill="#0f172a" stroke="#0284c7" stroke-width="1.8"/>
          <path d="M6 8l4 4-4 4" stroke="#38bdf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M12 16h6" stroke="#38bdf8" stroke-width="2" stroke-linecap="round"/>
        </svg>`,
  cmd: `<svg viewBox="0 0 24 24" class="w-6 h-6" style="filter:drop-shadow(0 2px 4px rgba(0,0,0,0.5));">
          <rect width="22" height="18" x="1" y="3" rx="4" fill="#0f172a" stroke="#0284c7" stroke-width="1.8"/>
          <path d="M6 8l4 4-4 4" stroke="#38bdf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M12 16h6" stroke="#38bdf8" stroke-width="2" stroke-linecap="round"/>
        </svg>`,
  ps1: `<svg viewBox="0 0 48 48" class="w-6 h-6" style="filter:drop-shadow(0 2px 4px rgba(0,0,0,0.5));">
          <rect width="44" height="38" x="2" y="5" rx="7" fill="#0c5395" stroke="#38bdf8" stroke-width="1.5"/>
          <path d="M12 15l11 9-11 9" fill="none" stroke="#ffffff" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>
          <line x1="26" y1="33" x2="36" y2="33" stroke="#ffffff" stroke-width="3.5" stroke-linecap="round"/>
        </svg>`,
  exe: `<svg viewBox="0 0 24 24" class="w-6 h-6" style="filter:drop-shadow(0 2px 4px rgba(0,0,0,0.5));">
          <rect width="20" height="20" x="2" y="2" rx="4" fill="#1e1b4b" stroke="#8b5cf6" stroke-width="1.5"/>
          <circle cx="12" cy="12" r="3" fill="#a78bfa"/>
          <path d="M12 6v2m0 8v2m-6-6h2m8 0h2" stroke="#a78bfa" stroke-width="1.5" stroke-linecap="round"/>
        </svg>`
};

function getTaskRealLogoSvg(ext) {
  const clean = (ext || '').replace(/^\./, '').toLowerCase();
  return CH_REAL_LOGOS[clean] || CH_REAL_LOGOS.bat;
}

const EXECUTION_STATE = {
  config: null,
  pendingItem: null,
};

// Multi-process Chat Heads State
const CH_STATE = {
  tasks: [],          // Array of running/recent task objects
  front: null,        // process_id of topmost stack bubble
  open: null,         // process_id currently displayed in the drawer (null if collapsed)
  stack: { x: window.innerWidth - CH_CONFIG.SZ - 12, y: 220 },
  hidden: false,
  dragging: false,
  fly: 0,
  dragId: null,
  dragPos: null,
  els: {},            // DOM element map: { [id]: HTMLElement, add: HTMLElement }
  durationTimer: null
};

function isExecutableItem(item) {
  if (!item || item.is_dir) return false;
  const ext = (item.extension || '').toLowerCase();
  return EXECUTABLE_EXTENSIONS.has(ext);
}

function supportsTerminalMode(item) {
  if (!item) return false;
  const ext = (item.extension || '').toLowerCase();
  return TERMINAL_EXTENSIONS.has(ext);
}

function getTaskColor(ext) {
  const clean = (ext || '').replace(/^\./, '').toLowerCase();
  return CH_CONFIG.colors[clean] || CH_CONFIG.colors.default;
}

// ── Fetch Execution Config ───────────────────────────────────

async function fetchExecutionConfig() {
  try {
    const res = await fetch('/api/execution/config');
    if (res.ok) {
      EXECUTION_STATE.config = await res.json();
    }
  } catch (e) {
    // Config unavailable
  }
}

function isExecutionEnabled() {
  return EXECUTION_STATE.config && EXECUTION_STATE.config.enabled === true;
}

async function updateContextMenuRunButton(item) {
  const btn = document.getElementById('ctxRunBtn');
  if (!btn) return;
  if (!EXECUTION_STATE.config) {
    await fetchExecutionConfig();
  }
  const shouldShow = isExecutionEnabled() && isExecutableItem(item);
  btn.classList.toggle('hidden', !shouldShow);
}

// ── Confirmation Modal ───────────────────────────────────────

function openRunConfirmModal(item) {
  if (!isExecutionEnabled()) {
    showToast('File execution is disabled in configuration', 'error');
    return;
  }
  if (!isExecutableItem(item)) {
    showToast('This file type cannot be executed', 'error');
    return;
  }

  EXECUTION_STATE.pendingItem = item;
  const isExeOnly = !supportsTerminalMode(item);

  const nameEl = document.getElementById('runConfirmFilename');
  if (nameEl) nameEl.textContent = item.name;

  const modeSelector = document.getElementById('runModeSelector');
  if (modeSelector) {
    if (isExeOnly) {
      modeSelector.classList.add('hidden');
    } else {
      modeSelector.classList.remove('hidden');
      const defaultMode = EXECUTION_STATE.config?.default_script_mode || 'terminal';
      const termRadio = document.getElementById('runModeTerminal');
      const deskRadio = document.getElementById('runModeDesktop');
      if (defaultMode === 'desktop' && deskRadio) deskRadio.checked = true;
      else if (termRadio) termRadio.checked = true;

      const desktopLabel = document.getElementById('runModeDesktopLabel');
      if (desktopLabel) {
        desktopLabel.classList.toggle('hidden', !EXECUTION_STATE.config?.allow_desktop_execution);
      }
    }
  }

  const modal = document.getElementById('runConfirmModal');
  if (modal) {
    modal.classList.remove('hidden');
    toggleModalScrollLock(true);
    const btn = document.getElementById('runConfirmBtn');
    if (btn) btn.focus();
    if (window.lucide) lucide.createIcons();
  }
}

function closeRunConfirmModal() {
  const modal = document.getElementById('runConfirmModal');
  if (modal) modal.classList.add('hidden');
  toggleModalScrollLock(false);
  EXECUTION_STATE.pendingItem = null;
}

async function executeConfirmedRun() {
  const item = EXECUTION_STATE.pendingItem;
  if (!item) return;

  let mode;
  if (!supportsTerminalMode(item)) {
    mode = 'desktop';
  } else {
    const selected = document.querySelector('input[name="runMode"]:checked');
    mode = selected ? selected.value : 'terminal';
  }

  closeRunConfirmModal();

  if (mode === 'terminal') {
    await startTerminalExecution(item);
  } else {
    await startDesktopExecution(item);
  }
}

async function startDesktopExecution(item) {
  try {
    showToast(`Launching ${item.name} on desktop...`, 'info');
    const res = await apiFetch('/api/execution/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: item.path, mode: 'desktop' }),
    });
    if (!res.ok) {
      const err = await res.json();
      showToast(`Launch failed: ${err.detail || 'Unknown error'}`, 'error');
      return;
    }
    const record = await res.json();
    showToast(`${item.name} launched on desktop (PID ${record.pid || '?'})`, 'success');
  } catch (err) {
    showToast(`Launch error: ${err.message}`, 'error');
  }
}

// ── Start Terminal Execution & Add Chat Head ─────────────────

async function startTerminalExecution(item) {
  const ext = (item.extension || '').replace(/^\./, '').toLowerCase();
  const color = getTaskColor(ext);

  try {
    const res = await apiFetch('/api/execution/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: item.path, mode: 'terminal' }),
    });

    if (!res.ok) {
      const err = await res.json();
      showToast(`Execution failed: ${err.detail || 'Unknown error'}`, 'error');
      return;
    }

    const record = await res.json();
    const processId = record.process_id;

    // Create task data structure
    const task = {
      processId: processId,
      name: item.name,
      ext: ext.toUpperCase() || 'RUN',
      color: color,
      pid: record.pid || null,
      startTime: Date.now(),
      status: 'running',
      exitCode: null,
      logs: [],
      lineCount: 0,
      ws: null
    };

    CH_STATE.tasks.push(task);
    CH_STATE.hidden = false;
    CH_STATE.front = processId;

    // Rebuild Chat Heads UI and connect WebSocket stream
    buildChatheads();
    connectTaskWebSocket(task);
    openChatheadsDrawer(processId);

    showToast(`Started ${item.name} in background`, 'success');
  } catch (err) {
    showToast(`Error starting ${item.name}: ${err.message}`, 'error');
  }
}

// ── WebSocket Streaming per Task ─────────────────────────────

function connectTaskWebSocket(task) {
  if (task.ws) {
    try { task.ws.close(); } catch (e) {}
    task.ws = null;
  }

  const token = (typeof STATE !== 'undefined' && STATE.authToken) ? STATE.authToken : '';
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${proto}//${location.host}/ws/execution/${task.processId}?token=${encodeURIComponent(token)}`;

  const ws = new WebSocket(wsUrl);
  task.ws = ws;

  ws.onopen = () => {
    task.status = 'running';
    updateTaskUIStatus(task);
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);

      if (msg.type === 'history') {
        (msg.lines || []).forEach(line => appendTaskLog(task, line.d, line.s));
      } else if (msg.type === 'output') {
        appendTaskLog(task, msg.data, msg.stream);
      } else if (msg.type === 'status') {
        task.status = msg.status;
        task.exitCode = msg.exit_code;
        if (msg.duration_sec) task.durationSec = msg.duration_sec;
        updateTaskUIStatus(task);
      } else if (msg.type === 'error') {
        appendTaskLog(task, `[Error: ${msg.message}]\n`, 'stderr');
      }
    } catch (e) {
      appendTaskLog(task, event.data, 'stdout');
    }
  };

  ws.onerror = () => {
    appendTaskLog(task, '\n[WebSocket stream connection error]\n', 'stderr');
  };

  ws.onclose = () => {
    task.ws = null;
    updateTaskUIStatus(task);
  };
}

function appendTaskLog(task, text, stream = 'stdout') {
  task.logs.push({ text, stream });
  task.lineCount += (text.match(/\n/g) || []).length;

  // If this task is actively open in the drawer, render immediately
  if (CH_STATE.open === task.processId) {
    const output = document.getElementById('terminalOutput');
    if (output) {
      const span = document.createElement('span');
      span.className = stream === 'stderr' ? 'text-red-400' : 'text-slate-300';
      span.textContent = text;
      output.appendChild(span);

      const lc = document.getElementById('terminalLineCount');
      if (lc) lc.textContent = `${task.lineCount} lines`;

      const autoScroll = document.getElementById('terminalAutoScroll');
      if (autoScroll && autoScroll.checked) {
        const wrap = document.getElementById('terminalOutputWrap');
        if (wrap) wrap.scrollTop = wrap.scrollHeight;
      }
    }
  }
}

function updateTaskUIStatus(task) {
  if (CH_STATE.open === task.processId) {
    const badge = document.getElementById('chPanelStatus');
    if (badge) {
      badge.textContent = (task.status || 'running').toUpperCase();
      if (task.status === 'running') {
        badge.className = 'text-[9px] uppercase font-mono font-bold tracking-wider px-2 py-0.5 rounded-full bg-teal-600/20 text-teal-400 border border-teal-500/30';
      } else if (task.status === 'completed') {
        badge.className = 'text-[9px] uppercase font-mono font-bold tracking-wider px-2 py-0.5 rounded-full bg-emerald-600/20 text-emerald-400 border border-emerald-500/30';
      } else {
        badge.className = 'text-[9px] uppercase font-mono font-bold tracking-wider px-2 py-0.5 rounded-full bg-red-600/20 text-red-400 border border-red-500/30';
      }
    }

    const stopBtn = document.getElementById('chPanelStopBtn');
    if (stopBtn) {
      const isRunning = task.status === 'running';
      stopBtn.disabled = !isRunning;
      stopBtn.classList.toggle('opacity-50', !isRunning);
    }
  }

  // Update pulse dot on chathead
  const el = CH_STATE.els[task.processId];
  if (el) {
    const dot = el.querySelector('.pulse-dot');
    if (dot) {
      if (task.status === 'running') {
        dot.style.background = 'var(--ch-success)';
        dot.classList.add('pulse');
      } else {
        dot.style.background = task.status === 'completed' ? '#10b981' : '#ef4444';
        dot.classList.remove('pulse');
      }
    }
  }
}

// ── Chat Heads Physics & Layout Engine ───────────────────────

function buildChatheads() {
  Object.values(CH_STATE.els).forEach(e => e.remove());
  CH_STATE.els = {};

  CH_STATE.tasks.forEach(task => {
    CH_STATE.els[task.processId] = createHeadElement(task.processId, task.ext, task.color);
  });

  CH_STATE.els.add = createHeadElement('add', '+', null);
  clampStack();
  layoutChatheads();
}

function createHeadElement(id, label, color) {
  const e = document.createElement('div');
  e.className = 'chathead' + (id === 'add' ? ' add' : '');
  e.tabIndex = 0;
  e.setAttribute('role', 'button');
  e.setAttribute('aria-label', id === 'add' ? 'Minimize and browse' : 'Process task head');

  if (id === 'add') {
    e.innerHTML = '<span class="text-2xl font-light text-slate-400">+</span>';
  } else {
    const logoSvg = getTaskRealLogoSvg(label);
    e.innerHTML = `<div class="icon-wrap w-8 h-8 flex items-center justify-center pointer-events-none">${logoSvg}</div>` +
      '<div class="pulse-dot pulse"></div>' +
      '<span class="bd"></span>';
  }

  bindHeadGestures(e, id);
  document.body.appendChild(e);
  return e;
}

function getStackOrder() {
  const front = CH_STATE.front;
  return [front, ...CH_STATE.tasks.map(t => t.processId).filter(i => i !== front)].filter(i => CH_STATE.tasks.some(t => t.processId === i));
}

function clampStack() {
  const st = CH_STATE.stack;
  st.x = Math.min(Math.max(8, st.x), window.innerWidth - CH_CONFIG.SZ - 8);
  st.y = Math.min(Math.max(20, st.y), window.innerHeight - CH_CONFIG.SZ - 90);
}

function layoutChatheads() {
  const W = window.innerWidth, H = window.innerHeight;
  const exp = CH_STATE.open !== null;
  const n = CH_STATE.tasks.length + 1;
  const x0 = (W - n * CH_CONFIG.GAP + 8) / 2;
  const st = CH_STATE.stack;
  const side = st.x < W / 2 ? 1 : -1;
  const ord = getStackOrder();
  const tot = CH_STATE.tasks.length;

  const restoreBtn = document.getElementById('chathead-restore');
  if (restoreBtn) restoreBtn.style.display = (CH_STATE.hidden && tot > 0) ? 'block' : 'none';

  CH_STATE.tasks.forEach((task, i) => {
    const e = CH_STATE.els[task.processId];
    if (!e) return;
    const k = ord.indexOf(task.processId);
    const bd = e.querySelector('.bd');

    e.classList.toggle('act', exp && CH_STATE.open === task.processId);
    const off = CH_STATE.hidden;
    const hid = !exp && k > 1; // Show max 2 layers stacked when collapsed
    e.classList.toggle('off', off);
    e.classList.toggle('hid', hid);

    const g = exp && CH_STATE.dragId === task.processId && CH_STATE.dragPos;
    const kk = Math.min(k, 1);
    const x = g ? g.x : exp ? x0 + i * CH_CONFIG.GAP : st.x + kk * side * 12;
    const y = g ? g.y : exp ? 56 : st.y + kk * 2;

    e.style.transitionDelay = (CH_STATE.dragging || document.body.classList.contains('chathead-flying')) ? '0ms' : (exp ? i * 35 : k * 25) + 'ms';
    e.style.transform = `translate3d(${x}px, ${y}px, 0) scale(${off ? 0.6 : g ? 1.12 : CH_STATE.dragging && !exp ? 1.08 : 1})`;
    e.style.zIndex = g ? 60 : exp ? 50 : 50 - k;

    // Show task counter on top bubble when collapsed with multiple tasks
    const showBadge = !exp && k === 0 && tot > 1;
    if (bd) {
      bd.style.display = showBadge ? 'grid' : 'none';
      bd.textContent = tot;
    }
  });

  const a = CH_STATE.els.add;
  if (a) {
    a.style.transform = `translate3d(${x0 + CH_STATE.tasks.length * CH_CONFIG.GAP}px, 56px, 0) scale(${exp ? 1 : 0.6})`;
    a.style.zIndex = 50;
    a.classList.toggle('off', !exp);
  }
}

// ── Touch and Mouse Pointer Gestures with Spring Velocity ───

function bindHeadGestures(e, id) {
  let sx, sy, ox, oy, moved = false, on = false, ind = false, raf = 0, pend = null, samples = [];
  const del = document.getElementById('chathead-del');
  const panel = document.getElementById('chathead-panel');
  const near = (x, y) => Math.hypot(x - window.innerWidth / 2, y - (window.innerHeight - 60)) < 70;

  const tap = () => {
    if (id === 'add') {
      closeChatheadsDrawer();
    } else {
      openChatheadsDrawer(id);
    }
  };

  e.addEventListener('pointerdown', ev => {
    cancelAnimationFrame(CH_STATE.fly);
    document.body.classList.remove('chathead-flying');
    on = true; moved = false; pend = null; samples = [];
    sx = ev.clientX; sy = ev.clientY;
    ox = CH_STATE.stack.x; oy = CH_STATE.stack.y;
    ind = CH_STATE.open !== null && id !== 'add';

    if (ind) {
      const n = CH_STATE.tasks.length + 1;
      ox = (window.innerWidth - n * CH_CONFIG.GAP + 8) / 2 + CH_STATE.tasks.findIndex(t => t.processId === id) * CH_CONFIG.GAP;
      oy = 56;
    }
    e.setPointerCapture(ev.pointerId);
  });

  e.addEventListener('pointermove', ev => {
    if (!on || id === 'add') return;
    const dx = ev.clientX - sx, dy = ev.clientY - sy;

    if (!moved && Math.hypot(dx, dy) > 6) {
      moved = true;
      CH_STATE.dragging = true;
      document.body.classList.add('chathead-dragging');
      if (del) del.classList.add('on');
      if (ind && panel) panel.classList.add('away');
    }
    if (!moved) return;

    const now = performance.now();
    samples.push({ t: now, x: ev.clientX, y: ev.clientY });
    while (samples.length > 1 && now - samples[0].t > 100) samples.shift();

    pend = { x: ox + dx, y: oy + dy, hot: near(ev.clientX, ev.clientY) };
    if (!raf) {
      raf = requestAnimationFrame(() => {
        raf = 0;
        if (!pend) return;
        if (ind) {
          CH_STATE.dragId = id;
          CH_STATE.dragPos = { x: pend.x, y: pend.y };
        } else {
          CH_STATE.stack.x = pend.x;
          CH_STATE.stack.y = pend.y;
        }
        if (del) del.classList.toggle('hot', pend.hot);
        layoutChatheads();
      });
    }
  });

  const end = ev => {
    if (!on) return;
    on = false;
    cancelAnimationFrame(raf);
    raf = 0;
    document.body.classList.remove('chathead-dragging');
    CH_STATE.dragging = false;
    if (del) del.classList.remove('on', 'hot');
    if (panel) panel.classList.remove('away');

    if (!moved) {
      tap();
      return;
    }

    // Dragged inside the expanded top row: reorder or drop on dismiss
    if (ind) {
      CH_STATE.dragId = null;
      if (near(ev.clientX, ev.clientY)) {
        stopTerminalProcess(id);
        return;
      }
      if (pend && pend.y < 150) {
        const n = CH_STATE.tasks.length + 1;
        const x0 = (window.innerWidth - n * CH_CONFIG.GAP + 8) / 2;
        const i = CH_STATE.tasks.findIndex(t => t.processId === id);
        const j = Math.max(0, Math.min(CH_STATE.tasks.length - 1, Math.round((pend.x - x0) / CH_CONFIG.GAP)));
        if (i >= 0) {
          const m = CH_STATE.tasks.splice(i, 1)[0];
          CH_STATE.tasks.splice(j, 0, m);
        }
      }
      layoutChatheads();
      return;
    }

    // Dragged while collapsed: check dismiss or snap to edge
    if (pend) {
      CH_STATE.stack.x = pend.x;
      CH_STATE.stack.y = pend.y;
    }

    if (near(ev.clientX, ev.clientY)) {
      // Dismiss stack
      CH_STATE.hidden = true;
      layoutChatheads();
      return;
    }

    // Calculate throw velocity for spring hand-off
    let vx = 0, vy = 0;
    const a = samples[0], b = samples[samples.length - 1];
    if (a && b && b.t > a.t) {
      vx = (b.x - a.x) / (b.t - a.t) * 1000;
      vy = (b.y - a.y) / (b.t - a.t) * 1000;
    }
    vx = Math.max(-3000, Math.min(3000, vx));
    vy = Math.max(-3000, Math.min(3000, vy));

    const W = window.innerWidth, H = window.innerHeight;
    const px = CH_STATE.stack.x + vx * 0.2;
    const py = CH_STATE.stack.y + vy * 0.2;
    springTo(px + CH_CONFIG.SZ / 2 < W / 2 ? 8 : W - CH_CONFIG.SZ - 8, Math.min(Math.max(20, py), H - CH_CONFIG.SZ - 90), vx, vy);
  };

  e.addEventListener('pointerup', end);
  e.addEventListener('pointercancel', end);
}

function springTo(tx, ty, vx, vy) {
  cancelAnimationFrame(CH_STATE.fly);
  document.body.classList.add('chathead-flying');
  const st = CH_STATE.stack, k = 230, c = 22;
  let last = performance.now();

  const step = now => {
    const dt = Math.min(0.032, (now - last) / 1000);
    last = now;
    vx += (-k * (st.x - tx) - c * vx) * dt;
    vy += (-k * (st.y - ty) - c * vy) * dt;
    st.x += vx * dt;
    st.y += vy * dt;
    layoutChatheads();

    if (Math.abs(vx) + Math.abs(vy) < 10 && Math.abs(st.x - tx) + Math.abs(st.y - ty) < 0.6) {
      st.x = tx;
      st.y = ty;
      layoutChatheads();
      document.body.classList.remove('chathead-flying');
      return;
    }
    CH_STATE.fly = requestAnimationFrame(step);
  };
  CH_STATE.fly = requestAnimationFrame(step);
}

// ── Drawer Open, Close & Switch ──────────────────────────────

function openChatheadsDrawer(processId) {
  if (CH_STATE.open === processId) {
    closeChatheadsDrawer(); // Tap active head again: collapse
    return;
  }

  const task = CH_STATE.tasks.find(t => t.processId === processId);
  if (!task) return;

  CH_STATE.open = processId;
  CH_STATE.front = processId;

  // Header display
  const avatar = document.getElementById('chPanelAvatar');
  if (avatar) {
    avatar.innerHTML = getTaskRealLogoSvg(task.ext);
    avatar.className = 'w-8 h-8 rounded-xl bg-slate-800 flex items-center justify-center shrink-0 border border-slate-700/80 p-1';
  }

  const title = document.getElementById('chPanelTitle');
  if (title) title.textContent = task.name;

  const meta = document.getElementById('chPanelMeta');
  if (meta) {
    const elapsed = Math.round((Date.now() - task.startTime) / 1000);
    meta.textContent = `PID ${task.pid || '?'} • Elapsed: ${elapsed}s`;
  }

  updateTaskUIStatus(task);
  renderActiveTerminalLogs(task);

  const veil = document.getElementById('chathead-veil');
  if (veil) veil.classList.add('on');

  const panel = document.getElementById('chathead-panel');
  if (panel) panel.classList.add('on');

  startDurationTimer(task);
  layoutChatheads();
}

function closeChatheadsDrawer() {
  CH_STATE.open = null;
  const veil = document.getElementById('chathead-veil');
  if (veil) veil.classList.remove('on');

  const panel = document.getElementById('chathead-panel');
  if (panel) panel.classList.remove('on');

  const inp = document.getElementById('chStdinInput');
  if (inp) inp.blur();

  if (CH_STATE.durationTimer) {
    clearInterval(CH_STATE.durationTimer);
    CH_STATE.durationTimer = null;
  }

  layoutChatheads();
}

function renderActiveTerminalLogs(task) {
  const output = document.getElementById('terminalOutput');
  if (!output) return;

  output.textContent = '';
  task.logs.forEach(item => {
    const span = document.createElement('span');
    span.className = item.stream === 'stderr' ? 'text-red-400' : 'text-slate-300';
    span.textContent = item.text;
    output.appendChild(span);
  });

  const lc = document.getElementById('terminalLineCount');
  if (lc) lc.textContent = `${task.lineCount} lines`;

  const wrap = document.getElementById('terminalOutputWrap');
  if (wrap) wrap.scrollTop = wrap.scrollHeight;
}

function clearTerminalOutput() {
  const task = CH_STATE.tasks.find(t => t.processId === CH_STATE.open);
  if (task) {
    task.logs = [];
    task.lineCount = 0;
  }
  const output = document.getElementById('terminalOutput');
  if (output) output.textContent = '';
  const lc = document.getElementById('terminalLineCount');
  if (lc) lc.textContent = '0 lines';
}

function startDurationTimer(task) {
  if (CH_STATE.durationTimer) clearInterval(CH_STATE.durationTimer);
  CH_STATE.durationTimer = setInterval(() => {
    if (!CH_STATE.open || CH_STATE.open !== task.processId) return;
    const meta = document.getElementById('chPanelMeta');
    if (meta) {
      const elapsed = Math.round((Date.now() - task.startTime) / 1000);
      meta.textContent = `PID ${task.pid || '?'} • Elapsed: ${elapsed}s`;
    }
  }, 1000);
}

// ── Stop Process & Interactive Stdin ─────────────────────────

async function stopTerminalProcess(targetId) {
  const processId = targetId || CH_STATE.open;
  if (!processId) return;

  try {
    const res = await apiFetch(`/api/execution/stop/${processId}`, { method: 'POST' });
    if (!res.ok) {
      const err = await res.json();
      showToast(`Stop failed: ${err.detail || 'Unknown error'}`, 'error');
      return;
    }

    showToast('Process terminated', 'info');

    // Remove from active tasks or mark terminated
    const idx = CH_STATE.tasks.findIndex(t => t.processId === processId);
    if (idx >= 0) {
      const task = CH_STATE.tasks[idx];
      if (task.ws) {
        try { task.ws.close(); } catch (e) {}
      }

      // Animate remove head
      const el = CH_STATE.els[processId];
      if (el) {
        delete CH_STATE.els[processId];
        el.classList.add('off');
        setTimeout(() => el.remove(), 300);
      }

      CH_STATE.tasks.splice(idx, 1);
      if (CH_STATE.front === processId) {
        CH_STATE.front = CH_STATE.tasks[0] ? CH_STATE.tasks[0].processId : null;
      }

      if (CH_STATE.open === processId) {
        if (CH_STATE.tasks.length > 0) {
          const next = CH_STATE.tasks[Math.min(idx, CH_STATE.tasks.length - 1)];
          CH_STATE.open = null;
          openChatheadsDrawer(next.processId);
        } else {
          closeChatheadsDrawer();
          CH_STATE.hidden = true;
        }
      }
      layoutChatheads();
    }
  } catch (e) {
    showToast('Failed to stop process', 'error');
  }
}

async function sendTerminalStdin() {
  const inp = document.getElementById('chStdinInput');
  if (!inp) return;
  const val = inp.value.trim();
  if (!val) return;
  await sendTerminalKey(val);
  inp.value = '';
}

async function sendTerminalKey(keyData) {
  const processId = CH_STATE.open;
  if (!processId) return;

  try {
    const res = await apiFetch(`/api/execution/stdin/${processId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ input: keyData }),
    });

    if (!res.ok) {
      const err = await res.json();
      showToast(`Stdin failed: ${err.detail || 'Process not accepting input'}`, 'error');
    }
  } catch (e) {
    showToast('Failed to send input to process', 'error');
  }
}

// ── Bind Global Event Listeners ──────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  await fetchExecutionConfig();

  const veil = document.getElementById('chathead-veil');
  if (veil) veil.onclick = closeChatheadsDrawer;

  const restoreBtn = document.getElementById('chathead-restore');
  if (restoreBtn) {
    restoreBtn.onclick = () => {
      CH_STATE.hidden = false;
      CH_STATE.stack = { x: window.innerWidth - CH_CONFIG.SZ - 12, y: 220 };
      clampStack();
      layoutChatheads();
    };
  }

  const stdinInput = document.getElementById('chStdinInput');
  if (stdinInput) {
    stdinInput.addEventListener('keydown', e => {
      if (e.key === 'Enter') sendTerminalStdin();
    });
  }

  window.addEventListener('resize', () => {
    clampStack();
    layoutChatheads();
  });
});

// Keyboard: Escape collapses drawer or closes confirmation
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    const panel = document.getElementById('chathead-panel');
    if (panel && panel.classList.contains('on')) {
      closeChatheadsDrawer();
    }
    const rc = document.getElementById('runConfirmModal');
    if (rc && !rc.classList.contains('hidden')) {
      closeRunConfirmModal();
    }
  }
});

// ── Context Menu & Card Click Integration ───────────────────

(function patchOpenContextMenu() {
  const originalFn = window.openContextMenu;
  window.openContextMenu = function(item) {
    if (originalFn) originalFn(item);
    updateContextMenuRunButton(item);
  };
})();

(function patchHandleContextAction() {
  const originalFn = window.handleContextAction;
  window.handleContextAction = async function(action) {
    if (action === 'run') {
      const item = STATE.contextItem;
      if (!item) return;
      closeContextMenu();
      openRunConfirmModal(item);
      return;
    }
    if (originalFn) return originalFn(action);
  };
})();

(function patchCardClick() {
  const origGrid = window.createGridCard;
  if (origGrid) {
    window.createGridCard = function(item) {
      const card = origGrid(item);
      if (isExecutableItem(item) && isExecutionEnabled()) {
        card.onclick = function(e) {
          if (e.target.closest('.action-btn') || e.target.closest('.select-checkbox')) return;
          if (STATE.isSelectMode) {
            toggleSelectItem(item.path);
            return;
          }
          if (item.is_dir) {
            loadDirectory(item.path);
            return;
          }
          openRunConfirmModal(item);
        };
      }
      return card;
    };
  }

  const origList = window.createListRow;
  if (origList) {
    window.createListRow = function(item) {
      const row = origList(item);
      if (isExecutableItem(item) && isExecutionEnabled()) {
        row.onclick = function(e) {
          if (e.target.closest('.action-btn') || e.target.closest('.select-checkbox')) return;
          if (STATE.isSelectMode) {
            toggleSelectItem(item.path);
            return;
          }
          openRunConfirmModal(item);
        };
      }
      return row;
    };
  }
})();
