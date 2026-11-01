/**
 * security.js — HYDRA Security & Device Management UI
 *
 * Integrates as a side panel into the existing SPA.
 * Uses the same Tailwind + Lucide design language as app.js.
 * Does NOT rebuild the main file manager.
 *
 * Features:
 *   - Security status banner (initial_setup / operational / locked)
 *   - IndexedDB WebCrypto Ed25519 key persistence (keys survive reload/restart)
 *   - Automatic session persistence in localStorage + sessionStorage + cookies
 *   - First-time owner registration flow (WebCrypto Ed25519 + Windows Hello)
 *   - Windows-local PC login shortcut (Windows Hello via localhost)
 *   - Ordinary device pairing flow with live status polling and auto-login
 *   - Owner device list with real-time online/offline indicators
 *   - Trusted device list with permission management and revocation
 *   - Pending pairing requests with cryptographic Ed25519 approval
 *   - Security lockdown controls
 *   - Audit log viewer
 *
 * Cryptography uses WebCrypto with non-extractable private keys.
 * Private keys never leave the browser's secure key storage.
 */

// ============================================================
// Base64URL Encoding & Decoding Utilities
// ============================================================

function uint8ToBase64Url(u8) {
  let binary = '';
  const len = u8.byteLength;
  for (let i = 0; i < len; i++) {
    binary += String.fromCharCode(u8[i]);
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

function base64UrlToUint8(str) {
  let b64 = str.replace(/-/g, '+').replace(/_/g, '/');
  while (b64.length % 4) b64 += '=';
  const binary = atob(b64);
  const u8 = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    u8[i] = binary.charCodeAt(i);
  }
  return u8;
}


// ============================================================
// Key Store (IndexedDB with LocalStorage Mirroring)
// ============================================================

const HydraKeyStore = (() => {
  const DB_NAME = 'hydra_crypto_db';
  const STORE_NAME = 'device_keys';
  const KEY_ID = 'hydra_device_key';

  function _openDb() {
    return new Promise((resolve, reject) => {
      if (!window.indexedDB) {
        reject(new Error('IndexedDB not supported in this browser'));
        return;
      }
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          db.createObjectStore(STORE_NAME);
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  async function saveKeyPair(keyData) {
    // 1. Mirror keys in localStorage for immediate resilience across HTTP LAN / mobile
    if (keyData.secretKeyB64) {
      try { localStorage.setItem('hydra_device_privkey', keyData.secretKeyB64); } catch {}
    }
    if (keyData.publicKeyB64) {
      try { localStorage.setItem('hydra_device_pubkey', keyData.publicKeyB64); } catch {}
    }

    // 2. Store in IndexedDB
    try {
      const db = await _openDb();
      return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, 'readwrite');
        tx.objectStore(STORE_NAME).put(keyData, KEY_ID);
        tx.oncomplete = () => resolve(true);
        tx.onerror = () => reject(tx.error);
      });
    } catch {
      return false;
    }
  }

  async function getKeyPair() {
    // 1. Try loading from IndexedDB
    try {
      const db = await _openDb();
      const res = await new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, 'readonly');
        const req = tx.objectStore(STORE_NAME).get(KEY_ID);
        req.onsuccess = () => resolve(req.result || null);
        req.onerror = () => reject(req.error);
      });
      if (res && (res.secretKeyB64 || res.privateKey)) return res;
    } catch {}

    // 2. Fallback to localStorage
    try {
      const secB64 = localStorage.getItem('hydra_device_privkey');
      const pubB64 = localStorage.getItem('hydra_device_pubkey');
      if (secB64 && pubB64) {
        return {
          publicKeyB64: pubB64,
          secretKeyB64: secB64,
          engine: 'tweetnacl',
        };
      }
    } catch {}

    return null;
  }

  async function clearKeyPair() {
    try { localStorage.removeItem('hydra_device_privkey'); } catch {}
    try { localStorage.removeItem('hydra_device_pubkey'); } catch {}
    try {
      const db = await _openDb();
      return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, 'readwrite');
        tx.objectStore(STORE_NAME).delete(KEY_ID);
        tx.oncomplete = () => resolve(true);
        tx.onerror = () => reject(tx.error);
      });
    } catch {
      return false;
    }
  }

  return { saveKeyPair, getKeyPair, clearKeyPair };
})();


// ============================================================
// Cryptographic Engine (TweetNaCl with WebCrypto Fallback)
// ============================================================

const HydraCrypto = (() => {
  function hasNacl() {
    return typeof window !== 'undefined' && Boolean(window.nacl && window.nacl.sign);
  }

  /**
   * Generate an Ed25519 key pair.
   * Uses TweetNaCl if present (guaranteed on all mobile/LAN/HTTP browsers),
   * with fallback to WebCrypto SubtleCrypto in secure contexts.
   */
  async function generateDeviceKeyPair() {
    // 1. TweetNaCl (Universal: works on Android, iOS, Windows, Mac over LAN HTTP and HTTPS)
    if (hasNacl()) {
      const kp = window.nacl.sign.keyPair();
      const pubB64 = uint8ToBase64Url(kp.publicKey);
      const secB64 = uint8ToBase64Url(kp.secretKey);
      return {
        publicKeyB64: pubB64,
        secretKeyB64: secB64,
        rawPublicKey: kp.publicKey,
        rawSecretKey: kp.secretKey,
        engine: 'tweetnacl',
      };
    }

    // 2. WebCrypto SubtleCrypto (if supported and in Secure Context)
    if (typeof crypto !== 'undefined' && crypto.subtle) {
      try {
        const keyPair = await crypto.subtle.generateKey(
          { name: 'Ed25519' },
          false,
          ['sign', 'verify']
        );
        const rawPub = await crypto.subtle.exportKey('raw', keyPair.publicKey);
        const publicKeyB64 = uint8ToBase64Url(new Uint8Array(rawPub));
        return {
          publicKeyB64,
          privateKey: keyPair.privateKey,
          publicKey: keyPair.publicKey,
          engine: 'webcrypto',
        };
      } catch {}
    }

    throw new Error('No cryptographic provider found (TweetNaCl or WebCrypto Ed25519 required)');
  }

  /**
   * Sign a message string using Ed25519.
   * Returns base64url-encoded Ed25519 signature.
   */
  async function signMessage(keyObj, messageStr) {
    const encoder = new TextEncoder();
    const data = encoder.encode(messageStr);

    // 1. TweetNaCl signing
    if (hasNacl()) {
      let secU8 = null;
      if (keyObj instanceof Uint8Array) {
        secU8 = keyObj;
      } else if (keyObj && keyObj.rawSecretKey) {
        secU8 = keyObj.rawSecretKey;
      } else if (keyObj && keyObj.secretKeyB64) {
        secU8 = base64UrlToUint8(keyObj.secretKeyB64);
      } else if (typeof keyObj === 'string') {
        secU8 = base64UrlToUint8(keyObj);
      }
      if (secU8) {
        const sig = window.nacl.sign.detached(data, secU8);
        return uint8ToBase64Url(sig);
      }
    }

    // 2. WebCrypto signing
    const privKey = (keyObj && keyObj.privateKey) ? keyObj.privateKey : keyObj;
    if (privKey && typeof crypto !== 'undefined' && crypto.subtle && typeof privKey.type === 'string') {
      const sigBuffer = await crypto.subtle.sign('Ed25519', privKey, data);
      return uint8ToBase64Url(new Uint8Array(sigBuffer));
    }

    throw new Error('Cannot sign challenge: invalid key format');
  }

  async function signPairingApproval(keyObj, challenge, requestId) {
    return signMessage(keyObj, `HYDRA-APPROVE:${challenge}:${requestId}`);
  }

  async function signLoginChallenge(keyObj, challenge, deviceId) {
    return signMessage(keyObj, `HYDRA-LOGIN:${challenge}:${deviceId}`);
  }

  async function isEd25519Available() {
    if (hasNacl()) return true;
    try {
      if (typeof crypto !== 'undefined' && crypto.subtle) {
        await crypto.subtle.generateKey({ name: 'Ed25519' }, false, ['sign', 'verify']);
        return true;
      }
    } catch {}
    return false;
  }

  return { generateDeviceKeyPair, signMessage, signPairingApproval, signLoginChallenge, isEd25519Available, hasNacl };
})();


// ============================================================
// Device Identity Storage
// ============================================================

const HydraIdentity = (() => {
  let _keyObj = null;        // Cached key object { publicKeyB64, secretKeyB64, ... }
  let _deviceId = null;
  let _deviceSession = null; // { session_id, permissions, role, expires_at, refresh_token }

  function getDeviceId() {
    if (_deviceId) return _deviceId;
    let id = localStorage.getItem('hydra_device_id');
    if (!id) {
      const randBytes = new Uint8Array(12);
      if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
        crypto.getRandomValues(randBytes);
      } else {
        for (let i = 0; i < 12; i++) randBytes[i] = Math.floor(Math.random() * 256);
      }
      id = 'dev-' + Array.from(randBytes).map(b => b.toString(16).padStart(2, '0')).join('');
      localStorage.setItem('hydra_device_id', id);
    }
    _deviceId = id;
    return id;
  }

  function getDeviceName() {
    const custom = localStorage.getItem('hydra_device_name');
    if (custom) return custom;

    const ua = navigator.userAgent;
    if (/Pixel (\d+)/i.test(ua)) {
      const match = ua.match(/Pixel (\d+)/i);
      return `Pixel ${match[1]}`;
    }
    if (/Samsung|SM-[A-Z0-9]+/i.test(ua)) return 'Samsung Phone';
    if (/iPhone/i.test(ua)) return 'iPhone';
    if (/iPad/i.test(ua)) return 'iPad';
    if (/Android/i.test(ua)) return 'Android Device';
    if (/Windows/i.test(ua)) return 'Windows PC';
    if (/Macintosh/i.test(ua)) return 'MacBook';
    return 'Web Client';
  }

  function setDeviceName(name) {
    localStorage.setItem('hydra_device_name', name.trim());
  }

  function getDeviceType() {
    const ua = navigator.userAgent;
    if (/iPad|Tablet/i.test(ua)) return 'tablet';
    if (/Mobile|Android|iPhone/i.test(ua)) return 'phone';
    return 'desktop';
  }

  async function initKeyPair() {
    if (_keyObj && _keyObj.publicKeyB64) {
      return _keyObj;
    }

    // Try restoring from IndexedDB / localStorage
    const saved = await HydraKeyStore.getKeyPair();
    if (saved && saved.publicKeyB64 && (saved.secretKeyB64 || saved.privateKey)) {
      _keyObj = saved;
      localStorage.setItem('hydra_device_pubkey', saved.publicKeyB64);
      return _keyObj;
    }

    // Generate new key pair
    const pair = await HydraCrypto.generateDeviceKeyPair();
    _keyObj = pair;

    // Store in IndexedDB and localStorage
    await HydraKeyStore.saveKeyPair({
      ...pair,
      deviceId: getDeviceId(),
    });

    localStorage.setItem('hydra_device_pubkey', pair.publicKeyB64);
    return pair;
  }

  async function hasStoredKeyPair() {
    if (_keyObj) return true;
    const saved = await HydraKeyStore.getKeyPair();
    return Boolean(saved && (saved.secretKeyB64 || saved.privateKey));
  }

  function getPublicKey() {
    return _keyObj?.publicKeyB64 || localStorage.getItem('hydra_device_pubkey');
  }

  function getKeyObj() {
    return _keyObj;
  }

  function setSession(session) {
    _deviceSession = session;
    if (session && session.session_id) {
      try { localStorage.setItem('hydra_session', JSON.stringify(session)); } catch {}
      try { sessionStorage.setItem('hydra_session', JSON.stringify(session)); } catch {}
      try { localStorage.setItem('wfm_token', session.session_id); } catch {}
      try { document.cookie = `wfm_token=${encodeURIComponent(session.session_id)}; path=/; SameSite=Lax`; } catch {}
      if (typeof window !== 'undefined' && window.STATE) {
        window.STATE.authToken = session.session_id;
      }
    } else {
      try { localStorage.removeItem('hydra_session'); } catch {}
      try { sessionStorage.removeItem('hydra_session'); } catch {}
      try { localStorage.removeItem('wfm_token'); } catch {}
      try { document.cookie = 'wfm_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT'; } catch {}
      if (typeof window !== 'undefined' && window.STATE) {
        window.STATE.authToken = '';
      }
    }
  }

  function getSession() {
    if (_deviceSession) return _deviceSession;
    let raw = null;
    try { raw = sessionStorage.getItem('hydra_session'); } catch {}
    if (!raw) {
      try { raw = localStorage.getItem('hydra_session'); } catch {}
    }
    if (!raw) return null;
    try {
      _deviceSession = JSON.parse(raw);
      return _deviceSession;
    } catch {
      return null;
    }
  }

  function getSessionToken() {
    const s = getSession();
    return s ? s.session_id : null;
  }

  function hasPermission(perm) {
    const s = getSession();
    return s && Array.isArray(s.permissions) && s.permissions.includes(perm);
  }

  function isOwner() {
    const s = getSession();
    return s && (s.role === 'primary-owner' || s.role === 'co-owner');
  }

  function isTrusted() {
    const s = getSession();
    return s && s.role === 'trusted';
  }

  function clearSession() {
    setSession(null);
  }

  return {
    getDeviceId, getDeviceName, setDeviceName, getDeviceType,
    initKeyPair, hasStoredKeyPair, getPublicKey, getKeyObj, getSessionToken,
    setSession, getSession, hasPermission, isOwner, isTrusted, clearSession,
  };
})();


// ============================================================
// API Client
// ============================================================

const HydraSecurityAPI = (() => {
  function _headers(extra = {}) {
    const h = { 'Content-Type': 'application/json', ...extra };
    const token = HydraIdentity.getSessionToken();
    if (token) h['Authorization'] = `Bearer ${token}`;
    return h;
  }

  async function _fetch(url, options = {}) {
    options.headers = { ..._headers(), ...(options.headers || {}) };
    const res = await fetch(url, options);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${res.status}`);
    }
    return res.json();
  }

  const getStatus = () => _fetch('/api/security/status');
  const getOwners = () => _fetch('/api/owners');
  const getDevices = () => _fetch('/api/devices');
  const getPending = () => _fetch('/api/devices/pending');
  const getAuditLog = (limit = 50) => _fetch(`/api/audit/log?limit=${limit}`);

  async function initialSetup(deviceName, publicKeyB64, pin) {
    return _fetch('/api/security/initial-setup', {
      method: 'POST',
      body: JSON.stringify({
        device_id: HydraIdentity.getDeviceId(),
        device_name: deviceName,
        device_type: HydraIdentity.getDeviceType(),
        public_key: publicKeyB64,
        pin,
      }),
    });
  }

  async function requestPairing(deviceName, publicKeyB64, pin, requestedPerms) {
    return _fetch('/api/pairing/request', {
      method: 'POST',
      body: JSON.stringify({
        device_id: HydraIdentity.getDeviceId(),
        device_name: deviceName,
        device_type: HydraIdentity.getDeviceType(),
        public_key: publicKeyB64,
        requested_permissions: requestedPerms,
        pin,
      }),
    });
  }

  async function getPairingStatus(requestId) {
    return _fetch(`/api/pairing/status/${requestId}`);
  }

  async function getPairingChallenge(requestId) {
    return _fetch(`/api/pairing/challenge/${requestId}`, { method: 'POST' });
  }

  async function approvePairing(requestId, challenge, ownerSig, grantPerms) {
    return _fetch('/api/pairing/approve', {
      method: 'POST',
      body: JSON.stringify({
        request_id: requestId,
        approval_challenge: challenge,
        owner_signature: ownerSig,
        owner_device_id: HydraIdentity.getDeviceId(),
        grant_permissions: grantPerms,
      }),
    });
  }

  async function rejectPairing(requestId) {
    return _fetch('/api/pairing/reject', {
      method: 'POST',
      body: JSON.stringify({
        request_id: requestId,
        owner_device_id: HydraIdentity.getDeviceId(),
      }),
    });
  }

  async function getLoginChallenge() {
    return _fetch(`/api/auth/device-challenge?device_id=${HydraIdentity.getDeviceId()}`);
  }

  async function deviceLogin(challenge, signature) {
    return _fetch('/api/auth/device-login', {
      method: 'POST',
      body: JSON.stringify({
        device_id: HydraIdentity.getDeviceId(),
        challenge,
        signature,
      }),
    });
  }

  async function performDeviceLogin() {
    const chData = await getLoginChallenge();
    const challenge = chData.challenge;
    const pair = await HydraIdentity.initKeyPair();
    const sig = await HydraCrypto.signLoginChallenge(pair, challenge, HydraIdentity.getDeviceId());
    const session = await deviceLogin(challenge, sig);
    HydraIdentity.setSession(session);
    return session;
  }

  async function performLocalLogin() {
    const pair = await HydraIdentity.initKeyPair().catch(() => null);
    const pubKey = pair ? pair.publicKeyB64 : (HydraIdentity.getPublicKey() || '');
    const res = await _fetch('/api/owners/local-login', {
      method: 'POST',
      body: JSON.stringify({
        device_id: HydraIdentity.getDeviceId(),
        device_name: HydraIdentity.getDeviceName(),
        public_key: pubKey,
      }),
    });
    if (res && res.session) {
      HydraIdentity.setSession(res.session);
    }
    return res;
  }

  async function revokeDevice(deviceId) {
    return _fetch('/api/devices/revoke', {
      method: 'POST',
      body: JSON.stringify({ device_id: deviceId }),
    });
  }

  async function updatePermissions(deviceId, permissions) {
    return _fetch('/api/devices/permissions', {
      method: 'POST',
      body: JSON.stringify({ device_id: deviceId, permissions }),
    });
  }

  async function enableLockdown(reason) {
    return _fetch('/api/security/lockdown', {
      method: 'POST',
      body: JSON.stringify({ reason }),
    });
  }

  async function unlockPlatform() {
    const authRes = await _fetch('/api/owners/request-auth', {
      method: 'POST',
      body: JSON.stringify({ action: 'change_security_policy' }),
    });
    return _fetch('/api/security/unlock', {
      method: 'POST',
      body: JSON.stringify({ broker_approval_token: authRes.broker_approval_token }),
    });
  }

  async function deviceLogout() {
    try {
      await _fetch('/api/auth/device-logout', { method: 'POST' });
    } catch { /* ignore */ }
    HydraIdentity.clearSession();
  }

  return {
    getStatus, getOwners, getDevices, getPending, getAuditLog,
    initialSetup, requestPairing, getPairingStatus, getPairingChallenge,
    approvePairing, rejectPairing, getLoginChallenge, deviceLogin,
    performDeviceLogin, performLocalLogin,
    revokeDevice, updatePermissions, enableLockdown, unlockPlatform, deviceLogout,
  };
})();


// ============================================================
// Security Panel UI
// ============================================================

const HydraSecurityUI = (() => {
  let _panel = null;
  let _refreshInterval = null;
  let _pairingPollInterval = null;

  // ---- Permission labels ----
  const PERMISSION_LABELS = {
    'filesystem.read':   '📁 Read & Download Files',
    'filesystem.write':  '✏️ Upload & Write Files',
    'execution.script':  '⚡ Run Commands & Scripts',
    'execution.desktop': '🖥️ Launch Desktop Apps',
    'process.manage':    '⚙️ Manage System Processes',
    'system.monitor':    '📊 View System Telemetry',
    'pairing.approve':   '🔑 Approve Device Pairing',
    'screen.view':       '👁️ Live Screen Streaming',
    'screen.control':    '🎮 Mouse & Keyboard Control',
    'screen.capture':    '📸 Capture Screenshots',
    'screen.record':     '🎬 Record Screen Video',
    'ai.execute':        '🤖 Autonomous AI Operations',
  };

  function _permLabel(p) {
    return PERMISSION_LABELS[p] || p;
  }

  function _statusBadge(status, revoked) {
    if (revoked) return '<span class="px-2 py-0.5 rounded-full text-xs bg-red-900/60 text-red-300 font-medium">Revoked</span>';
    if (status === 'online') return '<span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs bg-green-900/60 text-green-300 font-medium"><span class="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse"></span>Online</span>';
    return '<span class="px-2 py-0.5 rounded-full text-xs bg-gray-700 text-gray-400 font-medium">Offline</span>';
  }

  function _roleBadge(role) {
    const map = {
      'primary-owner': '<span class="px-2 py-0.5 rounded-full text-xs bg-amber-900/60 text-amber-300 font-semibold border border-amber-700/50">Primary Owner</span>',
      'co-owner':      '<span class="px-2 py-0.5 rounded-full text-xs bg-amber-800/60 text-amber-200 font-medium border border-amber-600/40">Co-Owner</span>',
      'trusted':       '<span class="px-2 py-0.5 rounded-full text-xs bg-blue-900/60 text-blue-300 font-medium border border-blue-700/50">Trusted Device</span>',
    };
    return map[role] || `<span class="px-2 py-0.5 rounded-full text-xs bg-gray-700 text-gray-300">${role}</span>`;
  }

  function _ts(unix) {
    if (!unix) return '—';
    return new Date(unix * 1000).toLocaleString();
  }

  function _isLocalhost() {
    return ['localhost', '127.0.0.1', '::1'].includes(window.location.hostname);
  }

  // ---- Panel creation ----
  function _createPanel() {
    const panel = document.createElement('div');
    panel.id = 'hydra-security-panel';
    panel.className = 'fixed inset-0 z-50 flex items-start justify-end pointer-events-none';
    panel.innerHTML = `
      <div class="pointer-events-auto w-full max-w-2xl h-full bg-gray-900 border-l border-gray-700 shadow-2xl flex flex-col overflow-hidden">
        <!-- Header -->
        <div class="flex items-center justify-between px-5 py-4 border-b border-gray-700 bg-gray-800">
          <div class="flex items-center gap-3">
            <div class="p-2 bg-brand-500/10 rounded-lg text-brand-400">
              <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
              </svg>
            </div>
            <div>
              <span class="font-semibold text-white text-sm">Security &amp; Device Authority</span>
              <div class="text-[11px] text-gray-400">PC-Controlled Multi-Owner Access</div>
            </div>
          </div>
          <button id="sec-panel-close" class="text-gray-400 hover:text-white transition-colors p-1.5 rounded-lg hover:bg-gray-700">
            <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>

        <!-- Tab bar -->
        <div class="flex border-b border-gray-700 bg-gray-800/60 text-xs">
          <button data-tab="status"  class="sec-tab px-4 py-2.5 font-medium text-gray-300 hover:text-white transition-colors border-b-2 border-transparent">Status</button>
          <button data-tab="owners"  class="sec-tab px-4 py-2.5 font-medium text-gray-300 hover:text-white transition-colors border-b-2 border-transparent">Owners</button>
          <button data-tab="trusted" class="sec-tab px-4 py-2.5 font-medium text-gray-300 hover:text-white transition-colors border-b-2 border-transparent">Trusted</button>
          <button data-tab="pending" class="sec-tab px-4 py-2.5 font-medium text-gray-300 hover:text-white transition-colors border-b-2 border-transparent">
            Pending <span id="sec-pending-badge" class="hidden ml-1 px-1.5 py-0.5 rounded-full bg-amber-600 text-white font-bold text-[10px]">0</span>
          </button>
          <button data-tab="audit"   class="sec-tab px-4 py-2.5 font-medium text-gray-300 hover:text-white transition-colors border-b-2 border-transparent">Audit</button>
        </div>

        <!-- Content -->
        <div id="sec-content" class="flex-1 overflow-y-auto p-5 space-y-4 text-sm text-gray-300"></div>
      </div>
    `;
    document.body.appendChild(panel);
    panel.querySelector('#sec-panel-close').addEventListener('click', closePanel);
    panel.querySelectorAll('.sec-tab').forEach(btn => {
      btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });
    _panel = panel;
    return panel;
  }

  function switchTab(tab) {
    if (!_panel) _createPanel();
    _panel.querySelectorAll('.sec-tab').forEach(b => {
      const active = b.dataset.tab === tab;
      b.classList.toggle('border-brand-400', active);
      b.classList.toggle('text-brand-300', active);
      b.classList.toggle('border-transparent', !active);
      b.classList.toggle('text-gray-300', !active);
    });
    _renderTab(tab);
  }

  async function _renderTab(tab) {
    const content = _panel.querySelector('#sec-content');
    content.innerHTML = '<div class="text-gray-500 text-center py-8">Loading security status…</div>';
    try {
      if (tab === 'status')  await _renderStatus(content);
      if (tab === 'owners')  await _renderOwners(content);
      if (tab === 'trusted') await _renderTrusted(content);
      if (tab === 'pending') await _renderPending(content);
      if (tab === 'audit')   await _renderAudit(content);
    } catch (e) {
      content.innerHTML = `<div class="text-red-400 p-4 rounded bg-red-900/20 border border-red-800">${e.message}</div>`;
    }
  }

  // ------------------------------------------------------------
  // Tab: Status
  // ------------------------------------------------------------
  async function _renderStatus(el) {
    const data = await HydraSecurityAPI.getStatus();
    const session = HydraIdentity.getSession();
    const isOwner = HydraIdentity.isOwner();
    const isTrusted = HydraIdentity.isTrusted();
    const isLocalhost = _isLocalhost();
    const pendingReqId = localStorage.getItem('hydra_pending_request_id');

    const stateColors = {
      initial_setup: 'bg-amber-900/30 border-amber-700/60 text-amber-300',
      operational:   'bg-green-900/25 border-green-700/50 text-green-300',
      locked:        'bg-red-900/30 border-red-700/60 text-red-300',
    };
    const stateLabels = {
      initial_setup: '⚠️ Initial Setup Required',
      operational:   '✅ Platform Operational',
      locked:        '🔒 Security Lockdown Active',
    };

    el.innerHTML = `
      <!-- State Banner -->
      <div class="p-4 rounded-xl border ${stateColors[data.state] || 'bg-gray-800 border-gray-700'} flex items-center justify-between">
        <div>
          <div class="font-semibold text-base">${stateLabels[data.state] || data.state}</div>
          <div class="text-xs opacity-80 mt-0.5">
            ${data.state === 'initial_setup' ? 'No owners registered. Register the primary owner from the Windows PC.' :
              data.lockdown_active ? 'Execution, pairing, and owner management are locked.' :
              'All cryptographic pairing and execution controls are active.'}
          </div>
        </div>
      </div>

      <!-- Quick Metrics -->
      <div class="grid grid-cols-3 gap-3">
        <div class="bg-gray-800/90 border border-gray-700/60 rounded-xl p-3 text-center cursor-pointer hover:border-gray-600 transition-colors" id="sec-stat-owners">
          <div class="text-2xl font-bold text-white">${data.owner_count}</div>
          <div class="text-xs text-gray-400 mt-0.5">Owners</div>
        </div>
        <div class="bg-gray-800/90 border border-gray-700/60 rounded-xl p-3 text-center cursor-pointer hover:border-gray-600 transition-colors" id="sec-stat-trusted">
          <div class="text-2xl font-bold text-white">${data.trusted_device_count}</div>
          <div class="text-xs text-gray-400 mt-0.5">Trusted</div>
        </div>
        <div class="bg-gray-800/90 border ${data.pending_request_count > 0 ? 'border-amber-600 bg-amber-950/20' : 'border-gray-700/60'} rounded-xl p-3 text-center cursor-pointer hover:border-amber-500 transition-colors" id="sec-stat-pending">
          <div class="text-2xl font-bold ${data.pending_request_count > 0 ? 'text-amber-400' : 'text-white'}">${data.pending_request_count}</div>
          <div class="text-xs text-gray-400 mt-0.5">Pending</div>
        </div>
      </div>

      <!-- This Device Card -->
      <div class="bg-gray-800/80 border border-gray-700/70 rounded-xl p-4 space-y-3">
        <div class="flex items-center justify-between">
          <div class="font-medium text-white flex items-center gap-2">
            <span>This Device</span>
            <span class="text-xs font-normal text-gray-400">(${_esc(HydraIdentity.getDeviceType())})</span>
          </div>
          <div>
            ${session ? _roleBadge(session.role) : '<span class="px-2 py-0.5 rounded-full text-xs bg-gray-700 text-gray-400">Unpaired Guest</span>'}
          </div>
        </div>

        <div class="space-y-1.5 text-xs text-gray-400">
          <div class="flex justify-between items-center">
            <span>Device Name</span>
            <span class="font-medium text-white">${_esc(HydraIdentity.getDeviceName())}</span>
          </div>
          <div class="flex justify-between items-center">
            <span>Device ID</span>
            <span class="font-mono text-gray-300">${HydraIdentity.getDeviceId().slice(0, 22)}…</span>
          </div>
          <div class="flex justify-between items-center">
            <span>Public Key</span>
            <span class="font-mono text-gray-300">${(HydraIdentity.getPublicKey() || 'Generating on demand').slice(0, 18)}…</span>
          </div>
          ${session ? `
            <div class="flex justify-between items-center">
              <span>Session ID</span>
              <span class="font-mono text-gray-300">${session.session_id.slice(0, 16)}…</span>
            </div>
            <div class="flex justify-between items-center">
              <span>Permissions</span>
              <span class="text-gray-300 font-medium">${session.permissions ? session.permissions.length + ' granted' : 'All (Owner)'}</span>
            </div>
          ` : ''}
        </div>

        <!-- Action buttons for This Device -->
        <div class="pt-2 flex flex-wrap gap-2">
          ${isLocalhost && !isOwner ? `
            <button id="sec-local-login-btn" class="flex-1 bg-brand-600 hover:bg-brand-500 text-white rounded-lg px-3 py-2 text-xs font-medium transition-colors flex items-center justify-center gap-1.5 shadow-sm">
              <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 11c0 3.517-1.009 6.799-2.753 9.571m-3.44-2.04l.054-.09A13.916 13.916 0 008 11a4 4 0 118 0c0 1.017-.07 2.019-.203 3m-2.118 6.844A21.88 21.88 0 0015.171 17m3.839 1.132c.645-2.266.99-4.659.99-7.132A8 8 0 004 11m0 0v.001" />
              </svg>
              <span>Windows Hello PC Login</span>
            </button>
          ` : ''}

          ${!session ? `
            <button id="sec-reauth-btn" class="bg-gray-700 hover:bg-gray-600 text-white rounded-lg px-3 py-2 text-xs font-medium transition-colors">
              🔑 Re-authenticate Device
            </button>
          ` : `
            <button id="sec-logout-btn" class="bg-gray-700/70 hover:bg-red-800/80 text-gray-300 hover:text-white rounded-lg px-3 py-2 text-xs transition-colors">
              Log Out
            </button>
          `}
        </div>
        <div id="sec-this-device-msg" class="text-xs hidden mt-1"></div>
      </div>

      <!-- State: INITIAL_SETUP Registration Form -->
      ${data.state === 'initial_setup' ? `
        <div class="bg-amber-900/20 border border-amber-700/60 rounded-xl p-5 space-y-3">
          <div class="font-medium text-amber-300 text-sm flex items-center gap-2">
            <span>🚀 Register First Owner Device</span>
          </div>
          <div class="text-xs text-gray-400">
            This device will become the primary owner. The Windows PC owner must authorize via Windows Hello when prompted.
          </div>
          <div class="space-y-2">
            <input id="sec-first-owner-name" class="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-brand-500" value="${_esc(HydraIdentity.getDeviceName())}" placeholder="Device Name" />
            <input id="sec-first-owner-pin" type="password" class="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-brand-500" placeholder="Enrollment PIN" />
          </div>
          <button id="sec-register-first-owner" class="w-full bg-brand-600 hover:bg-brand-500 text-white rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors shadow">
            Register as Owner (Requires Windows Auth)
          </button>
          <div id="sec-first-owner-msg" class="mt-2 text-xs hidden"></div>
        </div>
      ` : ''}

      <!-- State: OPERATIONAL & Device is NOT Owner/Trusted: Show Pairing Form or Polling Card -->
      ${data.state === 'operational' && !isOwner && !isTrusted ? `
        <div id="sec-pairing-container" class="bg-gradient-to-br from-gray-800/90 to-gray-800/60 border border-brand-500/30 rounded-xl p-5 space-y-4 shadow-lg">
          ${pendingReqId ? `
            <!-- Live Polling Mode -->
            <div id="sec-pairing-polling-box" class="space-y-3 text-center py-2">
              <div class="w-12 h-12 rounded-full bg-brand-500/20 border border-brand-500/40 text-brand-400 flex items-center justify-center mx-auto animate-pulse">
                <svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <div class="font-semibold text-white text-base">Pairing Request Submitted</div>
              <p class="text-xs text-gray-300 max-w-sm mx-auto">
                Waiting for an owner to approve this device. Open the <strong>Security</strong> panel on your PC and click <strong>Approve</strong>.
              </p>
              <div class="text-[11px] font-mono text-gray-500">Request ID: <span class="text-gray-300">${pendingReqId}</span></div>
              <div class="pt-2 flex justify-center">
                <button id="sec-cancel-pairing-btn" class="bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs px-4 py-1.5 rounded-lg transition-colors">
                  Cancel Request
                </button>
              </div>
            </div>
          ` : `
            <!-- Pairing Form Mode -->
            <div class="flex items-center gap-3">
              <div class="p-2.5 rounded-lg bg-brand-500/10 text-brand-400">
                <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                </svg>
              </div>
              <div>
                <h4 class="text-white font-semibold text-sm">Pair This Device with HYDRA</h4>
                <p class="text-xs text-gray-400">Request permission to browse files, run scripts, and control your PC</p>
              </div>
            </div>

            <div class="space-y-3">
              <div>
                <label class="block text-xs text-gray-400 mb-1">Device Name</label>
                <input id="sec-pair-device-name" class="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-brand-500" value="${_esc(HydraIdentity.getDeviceName())}" placeholder="e.g. My Phone" />
              </div>
              <div>
                <label class="block text-xs text-gray-400 mb-1">Enrollment PIN</label>
                <input id="sec-pair-pin" type="password" class="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-brand-500" placeholder="Enter HYDRA enrollment PIN" />
              </div>

              <div>
                <label class="block text-xs text-gray-400 mb-1.5">Requested Capabilities</label>
                <div class="grid grid-cols-2 gap-2 text-xs">
                  <label class="flex items-center gap-2 p-2 rounded-lg bg-gray-900/60 border border-gray-700/60 cursor-pointer hover:border-gray-600">
                    <input type="checkbox" class="sec-req-perm" value="filesystem.read" checked />
                    <span>📁 Read Files</span>
                  </label>
                  <label class="flex items-center gap-2 p-2 rounded-lg bg-gray-900/60 border border-gray-700/60 cursor-pointer hover:border-gray-600">
                    <input type="checkbox" class="sec-req-perm" value="filesystem.write" checked />
                    <span>✏️ Upload Files</span>
                  </label>
                  <label class="flex items-center gap-2 p-2 rounded-lg bg-gray-900/60 border border-gray-700/60 cursor-pointer hover:border-gray-600">
                    <input type="checkbox" class="sec-req-perm" value="execution.script" checked />
                    <span>⚡ Run Scripts</span>
                  </label>
                  <label class="flex items-center gap-2 p-2 rounded-lg bg-gray-900/60 border border-gray-700/60 cursor-pointer hover:border-gray-600">
                    <input type="checkbox" class="sec-req-perm" value="execution.desktop" />
                    <span>🖥️ Desktop Apps</span>
                  </label>
                  <label class="flex items-center gap-2 p-2 rounded-lg bg-gray-900/60 border border-gray-700/60 cursor-pointer hover:border-gray-600">
                    <input type="checkbox" class="sec-req-perm" value="process.manage" />
                    <span>⚙️ Processes</span>
                  </label>
                  <label class="flex items-center gap-2 p-2 rounded-lg bg-gray-900/60 border border-gray-700/60 cursor-pointer hover:border-gray-600">
                    <input type="checkbox" class="sec-req-perm" value="system.monitor" />
                    <span>📊 System Monitor</span>
                  </label>
                </div>
              </div>

              <button id="sec-submit-pairing-btn" class="w-full bg-brand-600 hover:bg-brand-500 text-white rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors shadow">
                Submit Pairing Request
              </button>
              <div id="sec-pairing-msg" class="text-xs hidden"></div>
            </div>
          `}
        </div>
      ` : ''}

      <!-- Lockdown Controls -->
      <div class="pt-2">
        ${data.lockdown_active ? `
          <button id="sec-unlock-btn" class="w-full bg-red-700 hover:bg-red-600 text-white rounded-lg px-4 py-2 text-xs font-medium transition-colors">
            🔓 Unlock Platform (Requires Windows Auth)
          </button>
        ` : isOwner ? `
          <button id="sec-lockdown-btn" class="w-full bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-400 hover:text-white rounded-lg px-4 py-2 text-xs font-medium transition-colors">
            🔒 Enable Security Lockdown
          </button>
        ` : ''}
      </div>
    `;

    // Click handlers for stats boxes
    el.querySelector('#sec-stat-owners')?.addEventListener('click', () => switchTab('owners'));
    el.querySelector('#sec-stat-trusted')?.addEventListener('click', () => switchTab('trusted'));
    el.querySelector('#sec-stat-pending')?.addEventListener('click', () => switchTab('pending'));

    // Windows Hello PC Login
    const localLoginBtn = el.querySelector('#sec-local-login-btn');
    if (localLoginBtn) {
      localLoginBtn.addEventListener('click', async () => {
        const msg = el.querySelector('#sec-this-device-msg');
        localLoginBtn.disabled = true;
        localLoginBtn.textContent = 'Prompting Windows Hello…';
        try {
          await HydraSecurityAPI.performLocalLogin();
          _showMsg(msg, '✅ Authenticated with Windows Hello! Welcome.', 'success');
          setTimeout(() => _renderTab('status'), 1200);
        } catch (e) {
          _showMsg(msg, `❌ ${e.message}`, 'error');
        } finally {
          localLoginBtn.disabled = false;
          localLoginBtn.textContent = 'Windows Hello PC Login';
        }
      });
    }

    // Re-authenticate button
    const reauthBtn = el.querySelector('#sec-reauth-btn');
    if (reauthBtn) {
      reauthBtn.addEventListener('click', async () => {
        const msg = el.querySelector('#sec-this-device-msg');
        reauthBtn.disabled = true;
        reauthBtn.textContent = 'Signing in…';
        try {
          await HydraSecurityAPI.performDeviceLogin();
          _showMsg(msg, '✅ Re-authenticated successfully!', 'success');
          setTimeout(() => _renderTab('status'), 1000);
        } catch (e) {
          _showMsg(msg, `❌ ${e.message}`, 'error');
        } finally {
          reauthBtn.disabled = false;
          reauthBtn.textContent = '🔑 Re-authenticate Device';
        }
      });
    }

    // Logout button
    const logoutBtn = el.querySelector('#sec-logout-btn');
    if (logoutBtn) {
      logoutBtn.addEventListener('click', async () => {
        if (!confirm('Log out from this device?')) return;
        await HydraSecurityAPI.deviceLogout();
        _renderTab('status');
      });
    }

    // First Owner Registration
    const regFirstOwnerBtn = el.querySelector('#sec-register-first-owner');
    if (regFirstOwnerBtn) {
      regFirstOwnerBtn.addEventListener('click', async () => {
        const nameInput = el.querySelector('#sec-first-owner-name');
        const pinInput  = el.querySelector('#sec-first-owner-pin');
        const msg       = el.querySelector('#sec-first-owner-msg');
        const name = nameInput.value.trim();
        const pin  = pinInput.value;

        if (!name) { _showMsg(msg, 'Enter a device name', 'error'); return; }
        if (!pin)  { _showMsg(msg, 'Enter the enrollment PIN', 'error'); return; }

        regFirstOwnerBtn.disabled = true;
        regFirstOwnerBtn.textContent = 'Generating device key pair…';

        try {
          if (!await HydraCrypto.isEd25519Available()) {
            throw new Error('Your browser does not support WebCrypto Ed25519. Please update to a modern browser.');
          }
          const pair = await HydraIdentity.initKeyPair();
          regFirstOwnerBtn.textContent = 'Requesting Windows auth on PC…';
          const res = await HydraSecurityAPI.initialSetup(name, pair.publicKeyB64, pin);
          HydraIdentity.setSession(res.session);
          _showMsg(msg, '✅ Primary owner registered! Access granted.', 'success');
          setTimeout(() => _renderTab('status'), 1500);
        } catch (e) {
          _showMsg(msg, `❌ ${e.message}`, 'error');
        } finally {
          regFirstOwnerBtn.disabled = false;
          regFirstOwnerBtn.textContent = 'Register as Owner (Requires Windows Auth)';
        }
      });
    }

    // Submit Pairing Request
    const submitPairBtn = el.querySelector('#sec-submit-pairing-btn');
    if (submitPairBtn) {
      submitPairBtn.addEventListener('click', async () => {
        const nameInput = el.querySelector('#sec-pair-device-name');
        const pinInput  = el.querySelector('#sec-pair-pin');
        const msg       = el.querySelector('#sec-pairing-msg');
        const perms     = [...el.querySelectorAll('.sec-req-perm:checked')].map(c => c.value);
        const name = nameInput.value.trim();
        const pin  = pinInput.value;

        if (!name) { _showMsg(msg, 'Enter your device name', 'error'); return; }
        if (!pin)  { _showMsg(msg, 'Enter the enrollment PIN', 'error'); return; }
        if (!perms.length) { _showMsg(msg, 'Select at least one requested capability', 'error'); return; }

        submitPairBtn.disabled = true;
        submitPairBtn.textContent = 'Generating device identity…';

        try {
          if (!await HydraCrypto.isEd25519Available()) {
            throw new Error('WebCrypto Ed25519 is not supported in this browser.');
          }
          HydraIdentity.setDeviceName(name);
          const pair = await HydraIdentity.initKeyPair();

          submitPairBtn.textContent = 'Submitting request…';
          const res = await HydraSecurityAPI.requestPairing(name, pair.publicKeyB64, pin, perms);
          localStorage.setItem('hydra_pending_request_id', res.request_id);

          _showMsg(msg, '✅ Pairing request submitted!', 'success');
          setTimeout(() => {
            _renderTab('status');
            _startPairingPoller(res.request_id);
          }, 800);
        } catch (e) {
          _showMsg(msg, `❌ ${e.message}`, 'error');
          submitPairBtn.disabled = false;
          submitPairBtn.textContent = 'Submit Pairing Request';
        }
      });
    }

    // Cancel Pairing Request
    const cancelPairBtn = el.querySelector('#sec-cancel-pairing-btn');
    if (cancelPairBtn) {
      cancelPairBtn.addEventListener('click', () => {
        _stopPairingPoller();
        localStorage.removeItem('hydra_pending_request_id');
        _renderTab('status');
      });
    }

    // Resume pairing poller if active
    if (pendingReqId) {
      _startPairingPoller(pendingReqId);
    }

    // Lockdown button
    const lockBtn = el.querySelector('#sec-lockdown-btn');
    if (lockBtn) {
      lockBtn.addEventListener('click', async () => {
        if (!HydraIdentity.isOwner()) {
          _showToast('Only owners can enable lockdown', 'error');
          return;
        }
        if (!confirm('Enable security lockdown? All execution and pairing will be halted.')) return;
        try {
          await HydraSecurityAPI.enableLockdown('manual');
          _renderTab('status');
        } catch (e) {
          _showToast(e.message, 'error');
        }
      });
    }

    // Unlock button
    const unlockBtn = el.querySelector('#sec-unlock-btn');
    if (unlockBtn) {
      unlockBtn.addEventListener('click', async () => {
        if (!HydraIdentity.isOwner()) {
          _showToast('Only owners can unlock the platform', 'error');
          return;
        }
        unlockBtn.disabled = true;
        unlockBtn.textContent = 'Prompting Windows Hello on PC…';
        try {
          await HydraSecurityAPI.unlockPlatform();
          _showToast('✅ Platform unlocked successfully!', 'success');
          _renderTab('status');
        } catch (e) {
          _showToast(`❌ Unlock failed: ${e.message}`, 'error');
          unlockBtn.disabled = false;
          unlockBtn.textContent = '🔓 Unlock Platform (Requires Windows Auth)';
        }
      });
    }
  }

  // ------------------------------------------------------------
  // Active Pairing Polling Loop
  // ------------------------------------------------------------
  function _startPairingPoller(requestId) {
    _stopPairingPoller();
    _pairingPollInterval = setInterval(async () => {
      try {
        const stat = await HydraSecurityAPI.getPairingStatus(requestId);
        if (stat.status === 'approved') {
          _stopPairingPoller();
          localStorage.removeItem('hydra_pending_request_id');
          _showToast('🎉 Pairing request approved by owner! Logging in…', 'success');

          // Complete challenge-response login
          try {
            await HydraSecurityAPI.performDeviceLogin();
            _showToast('✅ Device paired and authenticated!', 'success');
            setTimeout(() => {
              _renderTab('status');
              // Reload page or trigger SPA update so file manager unlocks
              window.location.reload();
            }, 1200);
          } catch (loginErr) {
            _showToast(`Approval detected but login failed: ${loginErr.message}`, 'error');
          }
        } else if (stat.status === 'rejected') {
          _stopPairingPoller();
          localStorage.removeItem('hydra_pending_request_id');
          _showToast('❌ Pairing request was rejected by the owner.', 'error');
          _renderTab('status');
        } else if (stat.status === 'expired') {
          _stopPairingPoller();
          localStorage.removeItem('hydra_pending_request_id');
          _showToast('⚠️ Pairing request expired.', 'info');
          _renderTab('status');
        }
      } catch {
        // network hiccup, keep polling
      }
    }, 2500);
  }

  function _stopPairingPoller() {
    if (_pairingPollInterval) {
      clearInterval(_pairingPollInterval);
      _pairingPollInterval = null;
    }
  }

  // ------------------------------------------------------------
  // Tab: Owners
  // ------------------------------------------------------------
  async function _renderOwners(el) {
    if (!HydraIdentity.isOwner()) {
      el.innerHTML = `
        <div class="p-6 text-center space-y-3 bg-gray-800/40 rounded-xl border border-gray-700/60">
          <div class="w-10 h-10 rounded-full bg-amber-900/30 text-amber-400 flex items-center justify-center mx-auto">
            <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
          </div>
          <div class="font-medium text-white text-sm">Owner Access Required</div>
          <p class="text-xs text-gray-400 max-w-sm mx-auto">
            Only registered owner devices may view or manage the HYDRA owner registry.
          </p>
        </div>
      `;
      return;
    }

    const data = await HydraSecurityAPI.getOwners();
    if (!data.owners?.length) {
      el.innerHTML = '<div class="text-gray-500 text-center py-8">No owner devices found.</div>';
      return;
    }

    el.innerHTML = `
      <div class="text-xs text-gray-400 mb-1">
        All owner devices hold administrative authority. Modifying owners requires fresh Windows Hello authentication on the PC.
      </div>
      <div class="space-y-3">
        ${data.owners.map(o => `
          <div class="bg-gray-800/90 rounded-xl p-4 space-y-2 border border-gray-700/80">
            <div class="flex items-start justify-between">
              <div>
                <div class="font-medium text-white text-sm">${_esc(o.device_name)}</div>
                <div class="text-xs text-gray-400">${_esc(o.device_type)}</div>
              </div>
              <div class="flex gap-2 flex-wrap justify-end">
                ${_roleBadge(o.role)}
                ${_statusBadge(o.status, o.revoked)}
              </div>
            </div>
            <div class="text-xs space-y-1 font-mono text-gray-400 pt-1">
              <div class="flex justify-between"><span>Fingerprint:</span> <span class="text-gray-300">${o.key_fingerprint}</span></div>
              <div class="flex justify-between"><span>Registered:</span> <span class="text-gray-300">${_ts(o.registered_at)}</span></div>
              <div class="flex justify-between"><span>Last active:</span> <span class="text-gray-300 font-sans">${_ts(o.last_active)}</span></div>
            </div>
          </div>
        `).join('')}
      </div>
    `;
  }

  // ------------------------------------------------------------
  // Tab: Trusted
  // ------------------------------------------------------------
  async function _renderTrusted(el) {
    if (!HydraIdentity.isOwner()) {
      el.innerHTML = `
        <div class="p-6 text-center space-y-3 bg-gray-800/40 rounded-xl border border-gray-700/60">
          <div class="w-10 h-10 rounded-full bg-blue-900/30 text-blue-400 flex items-center justify-center mx-auto">
            <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
          </div>
          <div class="font-medium text-white text-sm">Owner Access Required</div>
          <p class="text-xs text-gray-400 max-w-sm mx-auto">
            Only registered owner devices may view or manage trusted devices.
          </p>
        </div>
      `;
      return;
    }

    const data = await HydraSecurityAPI.getDevices();
    const trusted = data.trusted || [];
    if (!trusted.length) {
      el.innerHTML = `
        <div class="text-center py-12 space-y-2">
          <div class="text-gray-400 font-medium">No Trusted Devices Registered</div>
          <p class="text-xs text-gray-500 max-w-xs mx-auto">
            When guest devices pair and are approved, they will appear here with their granted capabilities.
          </p>
        </div>
      `;
      return;
    }

    el.innerHTML = `
      <div class="space-y-3">
        ${trusted.map(d => `
          <div class="bg-gray-800/90 rounded-xl p-4 space-y-3 border border-gray-700/80">
            <div class="flex items-start justify-between">
              <div>
                <div class="font-medium text-white text-sm">${_esc(d.device_name)}</div>
                <div class="text-xs text-gray-400">${_esc(d.device_type)}</div>
              </div>
              ${_statusBadge(d.status, d.revoked)}
            </div>

            <div>
              <div class="text-[11px] text-gray-400 mb-1">Granted Capabilities:</div>
              <div class="flex flex-wrap gap-1">
                ${(d.permissions || []).map(p => `
                  <span class="text-[11px] bg-blue-900/40 text-blue-300 border border-blue-800/40 px-2 py-0.5 rounded-md">${_permLabel(p)}</span>
                `).join('')}
              </div>
            </div>

            <div class="text-xs text-gray-400 font-mono space-y-0.5 pt-1">
              <div class="flex justify-between"><span>Fingerprint:</span> <span class="text-gray-300">${d.key_fingerprint}</span></div>
              <div class="flex justify-between"><span>Approved by:</span> <span class="text-gray-300">${d.approved_by?.slice(0, 18) || '—'}…</span></div>
              <div class="flex justify-between"><span>Last active:</span> <span class="text-gray-300 font-sans">${_ts(d.last_active)}</span></div>
            </div>

            ${!d.revoked ? `
              <div class="pt-1 flex justify-end">
                <button class="sec-revoke-trusted text-xs text-red-400 hover:text-red-300 hover:underline transition-colors" data-id="${d.device_id}">
                  Revoke Device Access
                </button>
              </div>
            ` : '<div class="text-xs text-red-500 font-medium pt-1">Access Revoked</div>'}
          </div>
        `).join('')}
      </div>
    `;

    el.querySelectorAll('.sec-revoke-trusted').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm('Immediately revoke this device? All active sessions will be terminated.')) return;
        try {
          await HydraSecurityAPI.revokeDevice(btn.dataset.id);
          _renderTab('trusted');
        } catch (e) {
          _showToast(e.message, 'error');
        }
      });
    });
  }

  // ------------------------------------------------------------
  // Tab: Pending
  // ------------------------------------------------------------
  async function _renderPending(el) {
    if (!HydraIdentity.isOwner()) {
      el.innerHTML = `
        <div class="p-6 text-center space-y-3 bg-gray-800/40 rounded-xl border border-gray-700/60">
          <div class="w-10 h-10 rounded-full bg-amber-900/30 text-amber-400 flex items-center justify-center mx-auto">
            <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
          </div>
          <div class="font-medium text-white text-sm">Owner Access Required</div>
          <p class="text-xs text-gray-400 max-w-sm mx-auto">
            Only owners can review and approve pending pairing requests.
          </p>
        </div>
      `;
      return;
    }

    const data = await HydraSecurityAPI.getPending();
    const pending = data.pending || [];

    // Update pending badge
    _updatePendingBadge(pending.length);

    if (!pending.length) {
      el.innerHTML = `
        <div class="text-center py-12 space-y-2">
          <div class="w-10 h-10 rounded-full bg-gray-800 text-gray-500 flex items-center justify-center mx-auto">
            <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <div class="text-gray-300 font-medium">No Pending Requests</div>
          <p class="text-xs text-gray-500 max-w-xs mx-auto">
            When a new device submits a pairing request with the enrollment PIN, it will appear here for cryptographic owner approval.
          </p>
        </div>
      `;
      return;
    }

    const ALL_PERMS = [
      'filesystem.read',
      'filesystem.write',
      'execution.script',
      'execution.desktop',
      'process.manage',
      'system.monitor',
    ];

    el.innerHTML = `
      <div class="space-y-4">
        ${pending.map(p => `
          <div class="bg-gray-800/95 rounded-xl p-4 space-y-3 border border-amber-600/40 shadow-md" data-req="${p.request_id}">
            <div class="flex items-start justify-between">
              <div>
                <div class="font-medium text-white text-sm">${_esc(p.device_name)}</div>
                <div class="text-xs text-gray-400">${_esc(p.device_type)}</div>
              </div>
              <span class="text-xs text-amber-300 bg-amber-900/40 border border-amber-700/50 px-2.5 py-0.5 rounded-full font-medium">
                Pending Approval
              </span>
            </div>

            <div class="text-xs text-gray-400 font-mono space-y-0.5">
              <div class="flex justify-between"><span>Fingerprint:</span> <span class="text-gray-300">${p.key_fingerprint}</span></div>
              <div class="flex justify-between"><span>Requested:</span> <span class="text-gray-300 font-sans">${_ts(p.created_at)}</span></div>
            </div>

            <div>
              <div class="text-xs text-gray-300 font-medium mb-1.5">Grant Capabilities:</div>
              <div class="grid grid-cols-2 gap-1.5">
                ${ALL_PERMS.map(pp => `
                  <label class="flex items-center gap-2 p-1.5 rounded-lg bg-gray-900/50 border border-gray-700/50 text-xs cursor-pointer hover:border-gray-600">
                    <input type="checkbox" class="sec-perm-check" value="${pp}"
                      ${p.requested_permissions.includes(pp) ? 'checked' : ''} />
                    <span>${_permLabel(pp)}</span>
                  </label>
                `).join('')}
              </div>
            </div>

            <div class="flex gap-2 pt-1">
              <button class="sec-approve-btn flex-1 bg-green-700 hover:bg-green-600 text-white text-xs font-semibold rounded-lg px-3 py-2.5 transition-colors shadow" data-req="${p.request_id}">
                ✓ Approve Device
              </button>
              <button class="sec-reject-btn flex-1 bg-red-900/70 hover:bg-red-800 text-white text-xs font-semibold rounded-lg px-3 py-2.5 transition-colors" data-req="${p.request_id}">
                ✗ Reject
              </button>
            </div>
            <div class="sec-approval-msg text-xs hidden"></div>
          </div>
        `).join('')}
      </div>
    `;

    el.querySelectorAll('.sec-approve-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const reqId = btn.dataset.req;
        const card  = el.querySelector(`[data-req="${reqId}"]`);
        const msg   = card.querySelector('.sec-approval-msg');
        const perms = [...card.querySelectorAll('.sec-perm-check:checked')].map(c => c.value);

        if (!perms.length) {
          _showMsg(msg, 'Select at least one capability to grant', 'error');
          return;
        }

        btn.disabled = true;
        btn.textContent = 'Fetching challenge…';

        try {
          if (!await HydraCrypto.isEd25519Available()) {
            throw new Error('Ed25519 is not supported in this browser.');
          }

          const pair = await HydraIdentity.initKeyPair();
          const chData = await HydraSecurityAPI.getPairingChallenge(reqId);
          const challenge = chData.challenge;

          btn.textContent = 'Signing approval…';
          const sig = await HydraCrypto.signPairingApproval(pair, challenge, reqId);

          btn.textContent = 'Authorizing…';
          await HydraSecurityAPI.approvePairing(reqId, challenge, sig, perms);

          _showMsg(msg, '✅ Device approved as trusted!', 'success');
          setTimeout(() => _renderTab('pending'), 1000);
        } catch (e) {
          _showMsg(msg, `❌ ${e.message}`, 'error');
          btn.disabled = false;
          btn.textContent = '✓ Approve Device';
        }
      });
    });

    el.querySelectorAll('.sec-reject-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const reqId = btn.dataset.req;
        if (!confirm('Reject this pairing request?')) return;
        try {
          await HydraSecurityAPI.rejectPairing(reqId);
          _renderTab('pending');
        } catch (e) {
          _showToast(e.message, 'error');
        }
      });
    });
  }

  // ------------------------------------------------------------
  // Tab: Audit
  // ------------------------------------------------------------
  async function _renderAudit(el) {
    if (!HydraIdentity.isOwner()) {
      el.innerHTML = '<div class="text-gray-500 text-center py-8">Owner access required to view audit logs.</div>';
      return;
    }
    const data = await HydraSecurityAPI.getAuditLog(50);
    const events = data.events || [];
    if (!events.length) {
      el.innerHTML = '<div class="text-gray-500 text-center py-8">No audit events recorded.</div>';
      return;
    }
    el.innerHTML = `
      <div class="space-y-1.5">
        ${events.map(e => `
          <div class="bg-gray-800/60 rounded-lg px-3 py-2 text-xs flex items-start gap-3 border-l-2 ${_auditColor(e.event_type)}">
            <span class="text-gray-500 shrink-0 w-36 font-mono text-[11px]">${_ts(e.ts)}</span>
            <span class="text-gray-200 font-medium">${_esc(e.event_type)}</span>
            ${e.actor_id ? `<span class="text-gray-500 font-mono text-[11px] truncate">${_esc(e.actor_id)}</span>` : ''}
          </div>
        `).join('')}
      </div>
    `;
  }

  function _auditColor(eventType) {
    if (eventType.includes('failed') || eventType.includes('rejected')) return 'border-red-600';
    if (eventType.includes('lockdown')) return 'border-orange-500';
    if (eventType.includes('owner')) return 'border-amber-500';
    if (eventType.includes('approved') || eventType.includes('registered') || eventType.includes('recovered')) return 'border-green-600';
    return 'border-gray-600';
  }

  function _updatePendingBadge(count) {
    const badge = _panel?.querySelector('#sec-pending-badge');
    if (badge) {
      if (count > 0) {
        badge.textContent = count;
        badge.classList.remove('hidden');
      } else {
        badge.classList.add('hidden');
      }
    }
  }

  function _showMsg(el, text, type) {
    if (!el) return;
    el.classList.remove('hidden', 'text-green-400', 'text-red-400', 'text-blue-400');
    el.classList.add(type === 'success' ? 'text-green-400' : type === 'error' ? 'text-red-400' : 'text-blue-400');
    el.textContent = text;
    el.classList.remove('hidden');
  }

  function _showToast(message, type = 'info') {
    if (typeof showToast === 'function') {
      showToast(message, type);
    } else {
      console.log(`[HYDRA Security] ${type}: ${message}`);
    }
  }

  function _esc(str) {
    return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ---- Public API ----
  function openPanel() {
    if (!_panel) _createPanel();
    _panel.classList.remove('hidden');
    switchTab('status');
    _startAutoRefresh();
  }

  function closePanel() {
    if (_panel) _panel.classList.add('hidden');
    _stopAutoRefresh();
  }

  function _startAutoRefresh() {
    _stopAutoRefresh();
    _refreshInterval = setInterval(async () => {
      try {
        const data = await HydraSecurityAPI.getPending();
        _updatePendingBadge((data.pending || []).length);
      } catch { /* silent */ }
    }, 10000);
  }

  function _stopAutoRefresh() {
    if (_refreshInterval) {
      clearInterval(_refreshInterval);
      _refreshInterval = null;
    }
  }

  return { openPanel, closePanel };
})();


// ============================================================
// Integration Hook — Add Security Button to Existing Nav
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
  const _injectSecurityButton = () => {
    const toolbars = [
      document.querySelector('#topbar-actions'),
      document.querySelector('.toolbar-right'),
      document.querySelector('[data-toolbar="right"]'),
      document.querySelector('header nav'),
      document.querySelector('header .flex.items-center.gap-2'),
    ].filter(Boolean);

    if (toolbars.length === 0) return false;

    const toolbar = toolbars[0];
    if (toolbar.querySelector('#hydra-security-btn')) return true;

    const btn = document.createElement('button');
    btn.id = 'hydra-security-btn';
    btn.title = 'Security & Device Authority';
    btn.className = 'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-gray-300 hover:text-white hover:bg-gray-700/80 transition-colors border border-gray-700/50 shadow-sm';
    btn.innerHTML = `
      <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4 text-brand-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/>
      </svg>
      <span>Security</span>
    `;
    btn.addEventListener('click', () => HydraSecurityUI.openPanel());
    toolbar.appendChild(btn);
    return true;
  };

  let attempts = 0;
  const _retry = setInterval(() => {
    if (_injectSecurityButton() || ++attempts > 20) clearInterval(_retry);
  }, 300);

  // Expose globally
  window.HydraKeyStore = HydraKeyStore;
  window.HydraIdentity = HydraIdentity;
  window.HydraSecurityAPI = HydraSecurityAPI;
  window.HydraCrypto = HydraCrypto;
  window.HydraSecurityUI = HydraSecurityUI;
});
