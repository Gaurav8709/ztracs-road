// Global HTML escape function for XSS prevention (E21)
function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
window.escapeHtml = escapeHtml;

/**
 * Z-TRACS Road Intelligence - Main Web Application Controller with Real RBAC
 * Implements Section 12, 29 (Authentication & Role Enforcement), Audit Trails, and Screen Routing.
 */

const state = {
  currentUser: null, // { username, role }
  token: null,
  currentInspectionId: 'DEMO-001',
  inspections: [],
  detections: [],
  selectedDefect: null,
  alerts: [],
  pollingTimer: null
};

// --- Secure API Fetch Helper (Requirement 3 & 4) ---
async function apiFetch(url, options = {}) {
  const token = state.token || localStorage.getItem("ztracs_token");
  options.headers = options.headers || {};
  
  if (token) {
    options.headers["Authorization"] = `Bearer ${token}`;
  }
  
  if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }

  const resolvedUrl = (typeof resolveApiUrl === "function") ? resolveApiUrl(url) : url;
  const res = await fetch(resolvedUrl, options);

  if (res.status === 401) {
    handleLogout();
    showLoginError("Authentication required or session expired. Please log in.");
    throw new Error("Unauthorized");
  } else if (res.status === 403) {
    const err = await res.json().catch(() => ({}));
    showToast(err.detail || "Permission denied: Your role cannot perform this action.", "error");
    throw new Error("Forbidden");
  }

  return res;
}
window.apiFetch = apiFetch;

// --- Authentication & Login Handlers (Requirement 2 & 4) ---
async function handleLoginForm(e) {
  e.preventDefault();
  const usernameInput = document.getElementById("login-username").value.trim();
  const passwordInput = document.getElementById("login-password").value;
  const submitBtn = document.getElementById("btn-submit-login");

  submitBtn.disabled = true;
  submitBtn.innerHTML = `<span>⏳</span> Authenticating...`;

  try {
    const res = await fetch((typeof resolveApiUrl === 'function') ? resolveApiUrl('/api/auth/login') : '/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: usernameInput, password: passwordInput })
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Login failed" }));
      showLoginError(err.detail || "Invalid username or password");
      submitBtn.disabled = false;
      submitBtn.innerHTML = `<span>🔒</span> Sign In to Z-TRACS`;
      return;
    }

    const data = await res.json();
    state.token = data.access_token;
    state.currentUser = data.user;

    localStorage.setItem("ztracs_token", data.access_token);
    localStorage.setItem("ztracs_user", JSON.stringify(data.user));

    // Hide Login Overlay
    const overlay = document.getElementById("login-overlay");
    if (overlay) {
      overlay.classList.add("hidden");
      overlay.classList.remove("flex");
    }
    document.getElementById("login-error-container").classList.add("hidden");

    // Apply role-based UI constraints
    applyRoleUIConstraints(data.user.role);

    showToast(`Welcome back, ${data.user.username} (${data.user.role.toUpperCase()})!`);
    
    // Load dashboard data
    fetchOverview();

  } catch (err) {
    console.error("Login error:", err);
    showLoginError("Connection failed. Check server status.");
  } finally {
    submitBtn.disabled = false;
    submitBtn.innerHTML = `<span>🔒</span> Sign In to Z-TRACS`;
  }
}
window.handleLoginForm = handleLoginForm;

// --- Register Screen Handlers (Gap Fix 1) ---
function showRegisterCard() {
  document.getElementById("login-card")?.classList.add("hidden");
  document.getElementById("register-card")?.classList.remove("hidden");
  document.getElementById("register-error-container")?.classList.add("hidden");
  document.getElementById("login-error-container")?.classList.add("hidden");
  document.getElementById("login-success-container")?.classList.add("hidden");
}
window.showRegisterCard = showRegisterCard;

function showLoginCard(successMsg = null) {
  document.getElementById("register-card")?.classList.add("hidden");
  document.getElementById("login-card")?.classList.remove("hidden");
  document.getElementById("register-error-container")?.classList.add("hidden");
  document.getElementById("login-error-container")?.classList.add("hidden");

  const successBox = document.getElementById("login-success-container");
  const successText = document.getElementById("login-success-text");
  if (successMsg && successBox && successText) {
    successText.innerText = successMsg;
    successBox.classList.remove("hidden");
  } else if (successBox) {
    successBox.classList.add("hidden");
  }
}
window.showLoginCard = showLoginCard;

async function handleRegisterForm(e) {
  e.preventDefault();
  const username = document.getElementById("register-username").value.trim();
  const full_name = document.getElementById("register-fullname").value.trim();
  const password = document.getElementById("register-password").value;
  const confirm_password = document.getElementById("register-confirm-password").value;
  const submitBtn = document.getElementById("btn-submit-register");
  const errBox = document.getElementById("register-error-container");
  const errText = document.getElementById("register-error-text");

  errBox.classList.add("hidden");
  submitBtn.disabled = true;
  submitBtn.innerHTML = `<span>⏳</span> Registering...`;

  try {
    const res = await fetch((typeof resolveApiUrl === "function") ? resolveApiUrl("/api/auth/register") : "/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, full_name, password, confirm_password })
    });

    const data = await res.json().catch(() => ({ detail: "Registration failed." }));

    if (!res.ok) {
      errText.innerText = data.detail || "Registration failed. Please check inputs.";
      errBox.classList.remove("hidden");
      return;
    }

    // Success: send user back to login with success message
    document.getElementById("form-register").reset();
    showLoginCard("Registration successful! Please log in with your credentials.");
    const loginUser = document.getElementById("login-username");
    if (loginUser) loginUser.value = username;
    const loginPass = document.getElementById("login-password");
    if (loginPass) loginPass.value = "";
    showToast("Registration successful! Please log in.");

  } catch (err) {
    console.error("Register error:", err);
    errText.innerText = "Network error. Unable to reach server.";
    errBox.classList.remove("hidden");
  } finally {
    submitBtn.disabled = false;
    submitBtn.innerHTML = `<span>📝</span> Register Account`;
  }
}
window.handleRegisterForm = handleRegisterForm;


function showLoginError(msg) {
  const container = document.getElementById("login-error-container");
  const text = document.getElementById("login-error-text");
  if (container && text) {
    text.innerText = msg;
    container.classList.remove("hidden");
  }
}

function handleLogout(silent = false) {
  state.token = null;
  state.currentUser = null;
  localStorage.removeItem("ztracs_token");
  localStorage.removeItem("ztracs_user");

  const overlay = document.getElementById("login-overlay");
  if (overlay) {
    overlay.classList.remove("hidden");
    overlay.classList.add("flex");
  }
  showLoginCard();
  if (!silent) {
    showToast("Logged out successfully.");
  }
}
window.handleLogout = handleLogout;

// --- Role-Based UI Constraints (Gap Fix 2 & 4) ---
function applyRoleUIConstraints(role) {
  role = (role || "viewer").toLowerCase();
  
  // Update header badge
  const nameEl = document.getElementById("active-user-name");
  const badgeEl = document.getElementById("active-role-badge");
  const roleLabel = document.getElementById("active-role-label");

  if (nameEl && state.currentUser) nameEl.innerText = state.currentUser.username;
  if (badgeEl) {
    badgeEl.innerText = role.toUpperCase();
    badgeEl.className = `px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase ${
      role === 'admin' ? 'bg-cyan-950 text-cyan-400 border border-cyan-800' :
      (role === 'inspector' ? 'bg-amber-950 text-amber-400 border border-amber-800' :
      'bg-slate-800 text-slate-300 border border-slate-700')
    }`;
  }
  if (roleLabel) roleLabel.innerText = role.toUpperCase();

  const initiateBtn = document.getElementById("btn-initiate-inspection") || document.querySelector(".admin-only");
  const newSurveyTab = document.getElementById("nav-tab-new-survey") || document.querySelector('button[data-screen="screen-new-inspection"]');
  const usersTab = document.getElementById("nav-tab-users");
  const demoResetBtn = document.getElementById("btn-demo-mode");
  const submitSurveyBtn = document.querySelector('#form-new-inspection button[type="submit"]');

  if (role === 'viewer') {
    // Viewer: completely hide New Survey tab and Initiate Inspection button (Gap Fix 4)
    if (initiateBtn) initiateBtn.classList.add("hidden");
    if (newSurveyTab) {
      newSurveyTab.classList.add("hidden");
      newSurveyTab.classList.remove("opacity-40", "pointer-events-none");
    }
    if (usersTab) usersTab.classList.add("hidden");
    if (demoResetBtn) demoResetBtn.classList.add("opacity-40", "pointer-events-none");
    if (submitSurveyBtn) submitSurveyBtn.classList.add("hidden");
  } else if (role === 'inspector') {
    // Inspector: Can create surveys and initiate inspection, but no demo reset and no users tab
    if (initiateBtn) initiateBtn.classList.remove("hidden");
    if (newSurveyTab) {
      newSurveyTab.classList.remove("hidden", "opacity-40", "pointer-events-none");
    }
    if (usersTab) usersTab.classList.add("hidden");
    if (demoResetBtn) demoResetBtn.classList.add("opacity-40", "pointer-events-none");
    if (submitSurveyBtn) submitSurveyBtn.classList.remove("hidden");
  } else {
    // Admin: Full access + Users tab visible
    if (initiateBtn) initiateBtn.classList.remove("hidden");
    if (newSurveyTab) {
      newSurveyTab.classList.remove("hidden", "opacity-40", "pointer-events-none");
    }
    if (usersTab) usersTab.classList.remove("hidden");
    if (demoResetBtn) demoResetBtn.classList.remove("opacity-40", "pointer-events-none");
    if (submitSurveyBtn) submitSurveyBtn.classList.remove("hidden");
  }
}

// --- Screen Navigation ---
function navigateToScreen(screenId) {
  const userRole = (state.currentUser?.role || "viewer").toLowerCase();

  // Role checks for restricted screens
  if (screenId === 'screen-users') {
    if (userRole !== 'admin') {
      showToast("Access restricted: Administrator role required.", "error");
      screenId = 'screen-command';
    } else {
      loadUsersList();
    }
  }

  if (screenId === 'screen-new-inspection' && userRole === 'viewer') {
    showToast("Access restricted: Viewers cannot create new surveys.", "error");
    screenId = 'screen-command';
  }

  const screens = document.querySelectorAll(".screen-view");
  screens.forEach(s => s.classList.add("hidden"));

  const targetScreen = document.getElementById(screenId);
  if (targetScreen) {
    targetScreen.classList.remove("hidden");
  }

  const tabs = document.querySelectorAll(".nav-tab");
  tabs.forEach(t => {
    if (t.getAttribute("data-screen") === screenId) {
      t.classList.add("active");
    } else {
      t.classList.remove("active");
    }
  });

  if (screenId === 'screen-map') {
    setTimeout(() => {
      if (!window.mapInstance && window.initRoadMap) {
        window.initRoadMap();
      }
      if (window.mapInstance) {
        window.mapInstance.invalidateSize();
      }
      if (window.loadMapData) {
        window.loadMapData(state.currentInspectionId);
      }
    }, 80);
  } else if (screenId === 'screen-evidence') {
    const currentId = state.currentInspectionId || "DEMO-001";
    loadInspectionVideo(currentId);
    loadDetections(currentId);
  }
}
window.navigateToScreen = navigateToScreen;

// --- Load Inspections & Analytics ---
async function fetchOverview() {
  try {
    const res = await apiFetch(`/api/analytics/overview?inspection_id=${state.currentInspectionId}`);
    const data = await res.json();

    document.getElementById("kpi-inspected-distance").innerText = `${data.inspected_distance_km} KM`;
    document.getElementById("kpi-total-defects").innerText = data.total_defects.toLocaleString();
    document.getElementById("kpi-critical-defects").innerText = data.critical_defects;
    document.getElementById("kpi-high-risk-segs").innerText = data.high_risk_segments;
    document.getElementById("kpi-avg-condition").innerText = `${data.average_condition_score}/100`;

    if (window.renderAnalyticsCharts) {
      window.renderAnalyticsCharts(data);
    }

    await loadInspectionsList();
    await loadDetections(state.currentInspectionId);
    await loadAlerts();
    await loadModelsRegistry();

  } catch (err) {
    console.error("Error fetching overview:", err);
  }
}


async function loadModelsRegistry() {
  try {
    const res = await apiFetch('/api/models');
    if (!res.ok) return;
    const models = await res.json();
    const container = document.getElementById("models-registry-list");
    if (!container) return;
    container.innerHTML = models.map(m => `
      <div class="p-3.5 rounded-lg bg-slate-900/60 border border-slate-800 space-y-2">
        <div class="flex items-center justify-between">
          <span class="font-mono text-xs font-bold text-cyan-400">${escapeHtml(m.id)}</span>
          <span class="text-[10px] px-1.5 py-0.5 rounded font-mono ${m.is_mock ? 'bg-amber-950 text-amber-300 border border-amber-800' : 'bg-emerald-950 text-emerald-300 border border-emerald-800'}">
            ${m.is_mock ? 'MOCK CV' : 'PRODUCTION'}
          </span>
        </div>
        <div class="text-xs text-white font-medium">${escapeHtml(m.name)}</div>
        <p class="text-[11px] text-slate-400 leading-relaxed">${escapeHtml(m.description)}</p>
      </div>
    `).join('');
  } catch (err) {
    console.warn("Error loading models registry:", err);
  }
}

function populateSurveySelectors(inspections) {
  const selects = document.querySelectorAll('.survey-switcher-select');
  if (!selects.length) return;

  const currentVal = state.currentInspectionId || 'DEMO-001';
  let optionsHtml = '';

  if (Array.isArray(inspections) && inspections.length > 0) {
    optionsHtml = inspections.map(insp => {
      const road = insp.road_name || 'Corridor';
      const name = insp.name || insp.id;
      return `<option value="${escapeHtml(insp.id)}">${escapeHtml(insp.id)} - ${escapeHtml(name)} (${escapeHtml(insp.status)})</option>`;
    }).join('');
  } else {
    optionsHtml = `<option value="DEMO-001">DEMO-001 (NH-48 Expressway)</option>`;
  }

  selects.forEach(sel => {
    sel.innerHTML = optionsHtml;
    sel.value = currentVal;
  });
}
window.populateSurveySelectors = populateSurveySelectors;

function switchActiveSurvey(surveyId) {
  if (!surveyId) return;
  state.currentInspectionId = surveyId;

  // Sync all dropdowns
  document.querySelectorAll('.survey-switcher-select').forEach(sel => {
    sel.value = surveyId;
  });

  // Sync active badge
  const badge = document.getElementById("command-active-survey-badge");
  if (badge) badge.innerText = `Active: ${surveyId}`;

  // Sync download buttons data-download-report attribute
  document.querySelectorAll('[data-download-report]').forEach(btn => {
    btn.setAttribute('data-download-report', surveyId);
  });

  // Re-fetch overview KPIs & charts for selected survey ID
  fetchOverview();

  // If GIS Map screen is visible, update GIS map
  const mapScreen = document.getElementById('screen-map');
  if (mapScreen && !mapScreen.classList.contains('hidden')) {
    if (window.loadMapData) {
      window.loadMapData(surveyId);
    }
  }

  // If Evidence screen is visible, load video & detections for this survey
  const evScreen = document.getElementById('screen-evidence');
  if (evScreen && !evScreen.classList.contains('hidden')) {
    loadInspectionVideo(surveyId);
    loadDetections(surveyId);
  }

  showToast(`Switched view to Survey: ${surveyId}`);
}
window.switchActiveSurvey = switchActiveSurvey;

async function loadInspectionsList() {
  try {
    const res = await apiFetch('/api/inspections');
    state.inspections = await res.json();
    populateSurveySelectors(state.inspections);

    const tbody = document.getElementById("inspections-table-body");
    if (!tbody) return;

    tbody.innerHTML = "";
    state.inspections.forEach(insp => {
      const tr = document.createElement("tr");
      tr.className = "border-b border-slate-800 hover:bg-slate-800/40 text-xs transition";
      
      const statusBadge = getStatusBadge(insp.status);
      
      tr.innerHTML = `
        <td class="py-3 px-4 font-mono font-bold text-cyan-400">${escapeHtml(insp.id)}</td>
        <td class="py-3 px-4 text-slate-200 font-medium">${escapeHtml(insp.name)}</td>
        <td class="py-3 px-4 text-slate-400">${escapeHtml(insp.road_name)}</td>
        <td class="py-3 px-4 font-mono">${escapeHtml(insp.model_version)}</td>
        <td class="py-3 px-4">${statusBadge}</td>
        <td class="py-3 px-4 font-mono font-bold text-slate-300">${escapeHtml(insp.defect_count)}</td>
        <td class="py-3 px-4">
          <div class="flex items-center gap-2">
            <button data-action="view-inspection" data-insp-id="${escapeHtml(insp.id)}" class="btn-view-inspection px-2.5 py-1 bg-cyan-500/20 text-cyan-300 hover:bg-cyan-500/30 rounded border border-cyan-500/30 font-semibold">
              Open
            </button>
            <button data-action="download-report" data-insp-id="${escapeHtml(insp.id)}" class="btn-download-report px-2.5 py-1 bg-slate-700/60 text-slate-200 hover:bg-slate-700 rounded border border-slate-600 font-semibold">
              PDF
            </button>
          </div>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Error loading inspections:", err);
  }
}

function getStatusBadge(status) {
  switch (status) {
    case 'COMPLETED':
      return `<span class="px-2 py-0.5 rounded text-[11px] font-bold badge-good">COMPLETED</span>`;
    case 'PROCESSING':
    case 'AI_ANALYSIS':
    case 'GEO_REFERENCING':
    case 'AGGREGATION':
      return `<span class="px-2 py-0.5 rounded text-[11px] font-bold bg-cyan-500/20 text-cyan-400 border border-cyan-500/40 animate-pulse">${status}</span>`;
    case 'QUEUED':
    case 'UPLOADED':
    case 'CREATED':
      return `<span class="px-2 py-0.5 rounded text-[11px] font-bold badge-monitor">${status}</span>`;
    case 'FAILED':
      return `<span class="px-2 py-0.5 rounded text-[11px] font-bold badge-critical">FAILED</span>`;
    default:
      return `<span class="px-2 py-0.5 rounded text-[11px] font-bold bg-slate-700 text-slate-300">${status}</span>`;
  }
}


function isUrlExpiredOrExpiringSoon(url, bufferSec = 30) {
  if (!url) return false;
  try {
    const parsed = new URL(url, window.location.origin);
    const expires = parseInt(parsed.searchParams.get('expires'), 10);
    if (!expires || isNaN(expires)) return false;
    const nowSec = Math.floor(Date.now() / 1000);
    return (expires - bufferSec) <= nowSec;
  } catch (e) {
    return false;
  }
}

function extractRawMediaUrl(url) {
  if (!url) return '';
  try {
    let path = url.split('?')[0];
    if (path.includes('://')) {
      path = new URL(path).pathname;
    }
    const prefixes = ['/static/media/evidence/', '/api/media/evidence/', 'static/media/evidence/'];
    for (const p of prefixes) {
      if (path.startsWith(p)) {
        path = path.slice(p.length);
      }
    }
    return path.replace(/^\/+/, '');
  } catch (e) {
    return url;
  }
}

async function loadDetections(inspectionId) {
  try {
    const res = await apiFetch(`/api/inspections/${inspectionId}/detections`);
    state.detections = await res.json();

    // Sign evidence URLs in batches of up to 100 files (Requirements 7 & 8)
    const filesToSign = [];
    state.detections.forEach(d => {
      if (d.evidence_orig_url) {
        const needsSign = !d.evidence_orig_url.includes('signature=') || isUrlExpiredOrExpiringSoon(d.evidence_orig_url, 30);
        if (needsSign) filesToSign.push(extractRawMediaUrl(d.evidence_orig_url));
      }
      if (d.evidence_anno_url) {
        const needsSign = !d.evidence_anno_url.includes('signature=') || isUrlExpiredOrExpiringSoon(d.evidence_anno_url, 30);
        if (needsSign) filesToSign.push(extractRawMediaUrl(d.evidence_anno_url));
      }
    });

    const uniqueFiles = Array.from(new Set(filesToSign)).filter(Boolean);
    if (uniqueFiles.length > 0) {
      for (let i = 0; i < uniqueFiles.length; i += 100) {
        const batch = uniqueFiles.slice(i, i + 100);
        try {
          const signRes = await apiFetch('/api/media/sign-batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ files: batch, type: 'evidence' })
          });
          if (signRes.ok) {
            const signData = await signRes.json();
            const signedMap = signData.signed || {};
            state.detections.forEach(d => {
              const rawOrig = extractRawMediaUrl(d.evidence_orig_url);
              const rawAnno = extractRawMediaUrl(d.evidence_anno_url);
              if (signedMap[rawOrig]) d.evidence_orig_url = signedMap[rawOrig].url;
              else if (signedMap[d.evidence_orig_url]) d.evidence_orig_url = signedMap[d.evidence_orig_url].url;

              if (signedMap[rawAnno]) d.evidence_anno_url = signedMap[rawAnno].url;
              else if (signedMap[d.evidence_anno_url]) d.evidence_anno_url = signedMap[d.evidence_anno_url].url;
            });
          }
        } catch (signErr) {
          console.warn("Evidence batch sign error:", signErr);
        }
      }
    }

    if (window.renderVideoTimelineChips) {
      window.renderVideoTimelineChips(state.detections);
    }

    renderEvidenceDefectsTable(state.detections);

    if (state.detections.length > 0) {
      const flagship = state.detections.find(d => d.detection_id === 'DEF-POT-00124') || state.detections[0];
      selectDefectForEvidence(flagship);
    }
  } catch (err) {
    console.error("Error loading detections:", err);
  }
}

function renderEvidenceDefectsTable(detections) {
  const tbody = document.getElementById("evidence-defects-table");
  if (!tbody) return;

  tbody.innerHTML = "";
  detections.forEach(d => {
    const tr = document.createElement("tr");
    tr.id = `row-det-${d.id}`;
    tr.className = "border-b border-slate-800/80 hover:bg-slate-800/50 cursor-pointer text-xs transition";
    
    const sevClass = d.severity === 'critical' ? 'text-red-400 font-bold' : (d.severity === 'high' ? 'text-orange-400 font-semibold' : 'text-amber-400');
    
    tr.innerHTML = `
      <td class="py-2.5 px-3 font-mono text-cyan-400 font-semibold">${escapeHtml(d.detection_id)}</td>
      <td class="py-2.5 px-3 capitalize font-medium text-slate-200">${escapeHtml(d.defect_type)}</td>
      <td class="py-2.5 px-3 ${sevClass} uppercase text-[10px]">${escapeHtml(d.severity)}</td>
      <td class="py-2.5 px-3 text-cyan-300 font-mono">${Math.round(d.confidence * 100)}%</td>
      <td class="py-2.5 px-3 font-mono text-slate-300">${escapeHtml(d.timestamp_formatted)}</td>
      <td class="py-2.5 px-3 font-mono text-slate-400">${escapeHtml(d.road_segment_id)}</td>
    `;

    tr.onclick = () => {
      selectDefectForEvidence(d);
      if (window.jumpVideoToTimestamp) {
        window.jumpVideoToTimestamp(d.timestamp, d.id);
      }
    };

    tbody.appendChild(tr);
  });
}

function selectDefectForEvidence(d) {
  state.selectedDefect = d;

  document.querySelectorAll("#evidence-defects-table tr").forEach(r => r.classList.remove("bg-cyan-950/40", "border-cyan-500/50"));
  const row = document.getElementById(`row-det-${d.id}`);
  if (row) row.classList.add("bg-cyan-950/40", "border-cyan-500/50");

  document.getElementById("ev-defect-id").innerText = d.detection_id;
  document.getElementById("ev-type").innerText = d.defect_type.toUpperCase();
  document.getElementById("ev-confidence").innerText = `${(d.confidence * 100).toFixed(1)}%`;
  document.getElementById("ev-severity").innerText = d.severity.toUpperCase();
  document.getElementById("ev-severity").className = `px-2 py-0.5 rounded text-xs font-bold uppercase ${
    d.severity === 'critical' ? 'badge-critical' : (d.severity === 'high' ? 'badge-high-risk' : 'badge-monitor')
  }`;
  document.getElementById("ev-location").innerText = `${d.latitude.toFixed(5)}, ${d.longitude.toFixed(5)}`;
  document.getElementById("ev-segment").innerText = d.road_segment_id;
  document.getElementById("ev-timestamp").innerText = `${d.timestamp_formatted} (Frame ${d.frame_id})`;
  document.getElementById("ev-model").innerText = `${d.model_version || 'RoadDefect-v1.0'} (Mock CV)`;

  const gpsEl = document.getElementById("ev-gps-source");
  if (gpsEl) gpsEl.innerText = d.gps_source || "interpolated from corridor geometry";

  const mockBadge = document.getElementById("ev-mock-badge");
  if (mockBadge) mockBadge.style.display = (d.is_mock !== false) ? 'inline-block' : 'none';

  async function resolveSignedEvidence(url, forceResign = false) {
    if (!url) return '';
    if (!forceResign && url.includes('signature=') && !isUrlExpiredOrExpiringSoon(url, 30)) {
      return url;
    }
    const raw = extractRawMediaUrl(url);
    try {
      const res = await apiFetch('/api/media/sign-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ files: [raw], type: 'evidence' })
      });
      if (res.ok) {
        const data = await res.json();
        if (data.signed && (data.signed[raw] || data.signed[url])) {
          return (data.signed[raw] || data.signed[url]).url;
        }
      }
    } catch (e) {
      console.warn("Sign fallback error:", e);
    }
    return url;
  }

  const elOrig = document.getElementById("img-original-evidence");
  if (elOrig) {
    elOrig.onerror = async function() {
      if (this.dataset.retried === "true") return;
      this.dataset.retried = "true";
      const resigned = await resolveSignedEvidence(d.evidence_orig_url, true);
      if (resigned) this.src = (typeof resolveApiUrl === "function") ? resolveApiUrl(resigned) : resigned;
    };
    resolveSignedEvidence(d.evidence_orig_url).then(signedOrig => {
      elOrig.dataset.retried = "false";
      if (signedOrig) elOrig.src = (typeof resolveApiUrl === "function") ? resolveApiUrl(signedOrig) : signedOrig;
    });
  }

  const elAnno = document.getElementById("img-annotated-evidence");
  if (elAnno) {
    elAnno.onerror = async function() {
      if (this.dataset.retried === "true") return;
      this.dataset.retried = "true";
      const resigned = await resolveSignedEvidence(d.evidence_anno_url, true);
      if (resigned) this.src = (typeof resolveApiUrl === "function") ? resolveApiUrl(resigned) : resigned;
    };
    resolveSignedEvidence(d.evidence_anno_url).then(signedAnno => {
      elAnno.dataset.retried = "false";
      if (signedAnno) elAnno.src = (typeof resolveApiUrl === "function") ? resolveApiUrl(signedAnno) : signedAnno;
    });
  }

  const pBadge = document.getElementById("ev-priority-rec");
  if (pBadge) {
    if (d.severity === 'critical') {
      pBadge.innerHTML = `<span class="badge-critical px-2.5 py-1 rounded text-xs font-bold">P1 — Immediate Intervention Assessment</span>`;
    } else if (d.severity === 'high') {
      pBadge.innerHTML = `<span class="badge-high-risk px-2.5 py-1 rounded text-xs font-bold">P2 — Planned Resurfacing Action</span>`;
    } else {
      pBadge.innerHTML = `<span class="badge-monitor px-2.5 py-1 rounded text-xs font-bold">P3 — Monitor / Scheduled Maintenance</span>`;
    }
  }
}
window.selectDefectForEvidence = selectDefectForEvidence;

async function loadAlerts() {
  try {
    const res = await apiFetch('/api/alerts');
    state.alerts = await res.json();
    const unread = state.alerts.filter(a => !a.is_read);

    const badge = document.getElementById("alert-badge");
    if (badge) {
      badge.innerText = unread.length;
      badge.style.display = unread.length > 0 ? 'inline-flex' : 'none';
    }

    const banner = document.getElementById("critical-alert-banner");
    if (banner && unread.length > 0) {
      const firstAlert = unread[0];
      document.getElementById("banner-alert-msg").innerText = firstAlert.message;
      banner.classList.remove("hidden");
    } else if (banner) {
      banner.classList.add("hidden");
    }
  } catch (err) {
    console.error("Error loading alerts:", err);
  }
}

async function triggerDemoReset() {
  const btn = document.getElementById("btn-demo-mode");
  const originalText = btn.innerHTML;
  btn.innerHTML = `<span class="animate-spin inline-block mr-1">↻</span> Loading Demo...`;
  btn.disabled = true;

  try {
    const res = await apiFetch('/api/demo/reset', { method: 'POST' });
    const data = await res.json();
    
    state.currentInspectionId = 'DEMO-001';
    await fetchOverview();
    
    if (window.loadMapData) {
      window.loadMapData('DEMO-001');
    }

    navigateToScreen('screen-command');
    showToast("Section 38 Golden Demo Inspection loaded successfully!");
  } catch (err) {
    console.error("Error resetting demo:", err);
    showToast("Error loading demo mode", "error");
  } finally {
    btn.innerHTML = originalText;
    btn.disabled = false;
  }
}
window.triggerDemoReset = triggerDemoReset;

let selectedVideoFile = null;

function setupVideoUpload() {
  const dropzone = document.getElementById("video-upload-dropzone");
  const fileInput = document.getElementById("form-video-file");
  const promptEl = document.getElementById("dropzone-prompt");
  const infoEl = document.getElementById("dropzone-file-info");
  const filenameEl = document.getElementById("dropzone-filename");
  const filesizeEl = document.getElementById("dropzone-filesize");
  const removeBtn = document.getElementById("btn-remove-video");
  const errorEl = document.getElementById("upload-error-msg");

  if (!dropzone || !fileInput) return;

  function clearSelectedFile() {
    selectedVideoFile = null;
    fileInput.value = "";
    if (infoEl) infoEl.classList.add("hidden");
    if (promptEl) promptEl.classList.remove("hidden");
    if (errorEl) {
      errorEl.classList.add("hidden");
      errorEl.innerText = "";
    }
    dropzone.classList.remove("border-cyan-500", "bg-cyan-950/20");
  }

  function handleFile(file) {
    if (!file) return;
    if (errorEl) {
      errorEl.classList.add("hidden");
      errorEl.innerText = "";
    }

    const validExts = [".mp4", ".mov"];
    const ext = "." + (file.name.split(".").pop() || "").toLowerCase();
    const isVideoType = file.type === "video/mp4" || file.type === "video/quicktime" || validExts.includes(ext);

    if (!isVideoType) {
      clearSelectedFile();
      if (errorEl) {
        errorEl.innerText = `Invalid file format (${ext.toUpperCase() || 'unknown'}). Only MP4 and MOV video files are supported.`;
        errorEl.classList.remove("hidden");
      }
      showToast("Only .mp4 and .mov video files are accepted.", "error");
      return;
    }

    selectedVideoFile = file;
    if (promptEl) promptEl.classList.add("hidden");
    if (infoEl) infoEl.classList.remove("hidden");
    if (filenameEl) filenameEl.innerText = file.name;
    
    const sizeMb = (file.size / (1024 * 1024)).toFixed(2);
    if (filesizeEl) filesizeEl.innerText = `${sizeMb} MB (${file.size.toLocaleString()} bytes)`;
    
    dropzone.classList.add("border-cyan-500", "bg-cyan-950/20");
  }

  dropzone.addEventListener("click", (e) => {
    if (e.target === removeBtn || removeBtn?.contains(e.target)) {
      e.stopPropagation();
      clearSelectedFile();
      return;
    }
    fileInput.click();
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files && fileInput.files[0]) {
      handleFile(fileInput.files[0]);
    }
  });

  if (removeBtn) {
    removeBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      clearSelectedFile();
    });
  }

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropzone.classList.add("border-cyan-400", "bg-cyan-950/30", "scale-[1.01]");
  });

  dropzone.addEventListener("dragleave", (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropzone.classList.remove("border-cyan-400", "scale-[1.01]");
    if (!selectedVideoFile) {
      dropzone.classList.remove("bg-cyan-950/30");
    }
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropzone.classList.remove("border-cyan-400", "scale-[1.01]");
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFile(e.dataTransfer.files[0]);
    }
  });

  // Handle RTSP vs Video upload toggle
  const sourceSelect = document.getElementById("form-source-type");
  const modeSelect = document.getElementById("form-proc-mode");
  const videoSec = document.getElementById("video-upload-section");
  const rtspContainer = document.getElementById("rtsp-url-container");

  function toggleRtspMode() {
    const isRtspSource = sourceSelect && sourceSelect.value === "RTSP Stream";
    const isRtspMode = modeSelect && modeSelect.value === "RTSP";
    if (isRtspSource || isRtspMode) {
      if (rtspContainer) rtspContainer.classList.remove("hidden");
      if (modeSelect) modeSelect.value = "RTSP";
      if (sourceSelect && sourceSelect.value !== "RTSP Stream") sourceSelect.value = "RTSP Stream";
    } else {
      if (rtspContainer) rtspContainer.classList.add("hidden");
      if (videoSec) videoSec.classList.remove("hidden");
    }
  }

  if (sourceSelect) sourceSelect.addEventListener("change", toggleRtspMode);
  if (modeSelect) modeSelect.addEventListener("change", toggleRtspMode);
}

async function handleNewInspectionSubmit(e) {
  e.preventDefault();

  const name = document.getElementById("form-inspection-name").value;
  const roadId = document.getElementById("form-road-id").value;
  const roadName = document.getElementById("form-road-id").selectedOptions[0].text;
  const source = document.getElementById("form-source-type").value;
  const model = document.getElementById("form-model-version").value;
  const mode = document.getElementById("form-proc-mode") ? document.getElementById("form-proc-mode").value : "Batch";
  const inspectionDate = document.getElementById("form-inspection-date") ? document.getElementById("form-inspection-date").value : "";
  const location = document.getElementById("form-location") ? document.getElementById("form-location").value : "";
  const rtspUrlInput = document.getElementById("form-rtsp-url");
  const rtspUrl = rtspUrlInput ? rtspUrlInput.value.trim() : "";

  try {
    const payloadBody = {
      name,
      road_id: roadId,
      road_name: roadName,
      source_type: source,
      model_version: model,
      processing_mode: mode,
      inspection_date: inspectionDate,
      location: location
    };

    if (mode === "RTSP" || source === "RTSP Stream" || rtspUrl.startsWith("rtsp://")) {
      if (!rtspUrl || !rtspUrl.startsWith("rtsp://")) {
        throw new Error("Please enter a valid RTSP URL starting with rtsp:// (e.g. rtsp://192.168.1.100:554/live)");
      }
      payloadBody.rtsp_url = rtspUrl;
      payloadBody.processing_mode = "RTSP";
      payloadBody.source_type = "RTSP Stream";
    }

    const createRes = await apiFetch('/api/inspections', {
      method: 'POST',
      body: payloadBody
    });
    const newInsp = await createRes.json();
    state.currentInspectionId = newInsp.id;

    if (rtspUrl && rtspUrl.startsWith("rtsp://")) {
      await apiFetch(`/api/inspections/${newInsp.id}/attach-rtsp-stream`, {
        method: 'POST',
        body: { rtsp_url: rtspUrl }
      });
    } else if (selectedVideoFile) {

      let uploadedDirectlyToS3 = false;

      // Check if S3 storage is enabled (when USE_S3_STORAGE=true)
      let s3Enabled = false;
      try {
        const stRes = await apiFetch('/api/storage/status');
        if (stRes.ok) {
          const stData = await stRes.json();
          s3Enabled = Boolean(stData && stData.s3_enabled);
        }
      } catch (stErr) {
        s3Enabled = false;
      }

      // Attempt Browser -> S3 Direct Upload via Presigned URL when USE_S3_STORAGE=true
      if (s3Enabled) {
        try {
          const presignRes = await apiFetch('/api/media/presigned-upload', {
            method: 'POST',
            body: {
              filename: selectedVideoFile.name,
              content_type: selectedVideoFile.type || 'video/mp4',
              type: 'video'
            }
          });

          if (presignRes.ok) {
            const presignData = await presignRes.json();
            const putUrl = presignData.url || presignData.upload_url;
            if (putUrl && presignData.saved_filename) {
              const s3PutRes = await fetch(putUrl, {
                method: 'PUT',
                headers: {
                  'Content-Type': selectedVideoFile.type || 'video/mp4'
                },
                body: selectedVideoFile
              });

              if (s3PutRes.ok) {
                await apiFetch(`/api/inspections/${newInsp.id}/attach-s3-video`, {
                  method: 'POST',
                  body: {
                    saved_filename: presignData.saved_filename
                  }
                });
                uploadedDirectlyToS3 = true;
              }
            }
          }
        } catch (s3Err) {
          console.warn("Direct S3 upload failed, falling back to server upload:", s3Err);
        }
      }

      // Fallback: Direct Server Upload via multipart/form-data (when USE_S3_STORAGE=false or S3 direct upload failed)
      if (!uploadedDirectlyToS3) {
        const formData = new FormData();
        formData.append('file', selectedVideoFile);
        
        const uploadUrl = (typeof resolveApiUrl === "function") ? resolveApiUrl(`/api/inspections/${newInsp.id}/upload`) : `/api/inspections/${newInsp.id}/upload`;
        const uploadRes = await fetch(uploadUrl, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${state.token}`
          },
          body: formData
        });
        if (!uploadRes.ok) {
          const errData = await uploadRes.json().catch(() => ({}));
          throw new Error(errData.detail || "Video upload failed");
        }
      }
    }

    await apiFetch(`/api/inspections/${newInsp.id}/start`, { method: 'POST' });

    navigateToScreen('screen-live');
    startProcessingTracker(newInsp.id);

  } catch (err) {
    console.error("Error submitting inspection:", err);
    showToast(err.message || "Failed to initiate inspection", "error");
  }
}
window.handleNewInspectionSubmit = handleNewInspectionSubmit;

function startProcessingTracker(inspectionId) {
  if (state.pollingTimer) clearInterval(state.pollingTimer);

  const trackerLabel = document.getElementById("live-tracker-id");
  if (trackerLabel) trackerLabel.innerText = inspectionId;

  state.pollingTimer = setInterval(async () => {
    try {
      const res = await apiFetch(`/api/inspections/${inspectionId}/status`);
      const statusData = await res.json();

      const bar = document.getElementById("live-progress-bar");
      const pctLabel = document.getElementById("live-progress-pct");
      if (bar) bar.style.width = `${statusData.progress_percent}%`;
      if (pctLabel) pctLabel.innerText = `${statusData.progress_percent}%`;

      const stageEl = document.getElementById("live-current-stage");
      if (stageEl) stageEl.innerText = statusData.current_stage;

      const framesEl = document.getElementById("live-frames-count");
      if (framesEl) framesEl.innerText = `${statusData.processed_frames.toLocaleString()} / ${statusData.total_frames.toLocaleString()}`;

      const defectsEl = document.getElementById("live-defects-count");
      if (defectsEl) defectsEl.innerText = statusData.defect_count;

      const mockBadge = document.getElementById("live-mock-badge");
      if (mockBadge) {
        mockBadge.style.display = (statusData.is_mock !== false) ? 'inline-block' : 'none';
      }

      updateStepCheckmarks(statusData.status, statusData.progress_percent);
      appendTerminalLog(`[${new Date().toLocaleTimeString()}] Stage: ${statusData.current_stage} (${statusData.progress_percent}%) - Frames: ${statusData.processed_frames}/${statusData.total_frames}, Defects: ${statusData.defect_count}`);

      if (statusData.status === 'COMPLETED') {
        clearInterval(state.pollingTimer);
        appendTerminalLog(`[${new Date().toLocaleTimeString()}] PIPELINE COMPLETED. Geo-referenced outputs saved.`);
        document.getElementById("btn-live-view-results")?.classList.remove("hidden");
        state.currentInspectionId = inspectionId;
        loadInspectionVideo(inspectionId);
        fetchOverview();
      } else if (statusData.status === 'FAILED') {
        clearInterval(state.pollingTimer);
        appendTerminalLog(`[${new Date().toLocaleTimeString()}] PIPELINE FAILED: ${statusData.error_message || 'Processing aborted'}`);
        showToast(`Pipeline failed: ${statusData.error_message || 'Error occurred'}`, "error");
      }

    } catch (err) {
      console.error("Polling error:", err);
      clearInterval(state.pollingTimer);
    }
  }, 2000); // Poll every 2 seconds per D7
}

function updateStepCheckmarks(status, progress) {
  const steps = [
    { id: "step-upload", min: 10 },
    { id: "step-queue", min: 15 },
    { id: "step-frames", min: 25 },
    { id: "step-inference", min: 70 },
    { id: "step-geo", min: 85 },
    { id: "step-aggregation", min: 95 },
    { id: "step-complete", min: 100 }
  ];

  steps.forEach(s => {
    const el = document.getElementById(s.id);
    if (!el) return;
    if (progress >= s.min) {
      el.className = "flex items-center gap-2 text-xs font-semibold text-emerald-400";
      el.querySelector(".step-icon").innerHTML = "✓";
    } else if (progress > s.min - 15) {
      el.className = "flex items-center gap-2 text-xs font-semibold text-cyan-400 animate-pulse";
      el.querySelector(".step-icon").innerHTML = "⏳";
    } else {
      el.className = "flex items-center gap-2 text-xs font-medium text-slate-500";
      el.querySelector(".step-icon").innerHTML = "○";
    }
  });
}

function appendTerminalLog(msg) {
  const term = document.getElementById("live-terminal-logs");
  if (!term) return;
  const p = document.createElement("div");
  p.className = "font-mono text-[11px] text-slate-300 leading-tight";
  p.innerText = msg;
  term.appendChild(p);
  term.scrollTop = term.scrollHeight;
}

// --- Secure PDF Report Download with Blob (Gap Fix 3) ---
async function downloadReport(inspectionId = state.currentInspectionId) {
  try {
    showToast("Generating PoC executive PDF report...");
    const res = await apiFetch(`/api/reports/${inspectionId}/pdf`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Failed to download PDF report" }));
      showToast(err.detail || "PDF download failed", "error");
      return;
    }
    const blob = await res.blob();
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = blobUrl;
    a.download = `ZTRACS_Report_${inspectionId}.pdf`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(blobUrl), 10000);
    showToast("PDF report downloaded successfully!");
  } catch (err) {
    console.error("Report download error:", err);
    showToast("Report download failed", "error");
  }
}
window.downloadReport = downloadReport;

function showToast(message, type = "info") {
  const toast = document.getElementById("toast-notification");
  if (!toast) return;

  toast.innerText = message;
  toast.className = `fixed bottom-6 right-6 z-[10000] px-4 py-3 rounded-lg shadow-xl text-xs font-semibold backdrop-blur-md border ${
    type === 'error' ? 'bg-red-950/90 text-red-200 border-red-500/40' : 'bg-slate-900/95 text-cyan-300 border-cyan-500/40'
  }`;
  toast.classList.remove("hidden");

  setTimeout(() => {
    toast.classList.add("hidden");
  }, 3500);
}
window.showToast = showToast;

window.inspectSpecificDefect = async function(defectDbId, timestampSec) {
  navigateToScreen('screen-evidence');
  if (state.detections.length === 0) {
    await loadDetections(state.currentInspectionId);
  }
  let d = state.detections.find(det => det.id === defectDbId || det.detection_id === defectDbId);
  if (!d) {
    try {
      const res = await apiFetch(`/api/detections/${defectDbId}`);
      if (res.ok) d = await res.json();
    } catch (e) {}
  }
  if (d) {
    selectDefectForEvidence(d);
  }
  if (window.jumpVideoToTimestamp) {
    window.jumpVideoToTimestamp(timestampSec, defectDbId);
  }
};


async function loadInspectionVideo(inspectionId) {
  try {
    const res = await apiFetch(`/api/inspections/${inspectionId}`);
    if (res.ok) {
      const data = await res.json();
      const rawUrl = data.video_url || "demo_road.mp4";
      const filename = rawUrl.split('/').pop().split('?')[0];

      // Sign the video URL (Fix 2)
      let videoSrc = rawUrl;
      try {
        const signRes = await apiFetch(`/api/media/sign?file=${encodeURIComponent(filename)}`);
        if (signRes.ok) {
          const signData = await signRes.json();
          videoSrc = signData.url;
        }
      } catch (signErr) {
        console.warn("Failed to sign video URL, using fallback URL:", signErr);
      }

      const player = document.getElementById("inspection-video-player");
      if (player && videoSrc) {
        player.src = (typeof resolveApiUrl === "function") ? resolveApiUrl(videoSrc) : videoSrc;
        player.load();
      }
    }
  } catch(e) {
    console.error("Error loading inspection video:", e);
  }
}
window.loadInspectionVideo = loadInspectionVideo;

window.viewInspection = function(id) {
  switchActiveSurvey(id);
  navigateToScreen('screen-evidence');
};

window.filterEvidenceBySegment = function(segId) {
  const filtered = state.detections.filter(d => d.road_segment_id === segId);
  if (filtered.length > 0) {
    selectDefectForEvidence(filtered[0]);
    if (window.jumpVideoToTimestamp) {
      window.jumpVideoToTimestamp(filtered[0].timestamp, filtered[0].id);
    }
  }
};

// --- App Initialization with Auth Verification ---
document.addEventListener("DOMContentLoaded", async () => {
  if (window.initRoadMap) window.initRoadMap();
  if (window.initVideoSync) window.initVideoSync();
  setupVideoUpload();

  document.querySelectorAll(".nav-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      const targetScreen = tab.getAttribute("data-screen");
      navigateToScreen(targetScreen);
    });
  });

  const demoBtn = document.getElementById("btn-demo-mode");
  if (demoBtn) demoBtn.addEventListener("click", triggerDemoReset);

  const newForm = document.getElementById("form-new-inspection");
  if (newForm) newForm.addEventListener("submit", handleNewInspectionSubmit);

  // Check saved authentication (Gap Fix 5)
  const savedToken = localStorage.getItem("ztracs_token");
  const savedUserStr = localStorage.getItem("ztracs_user");

  if (savedToken && savedUserStr) {
    try {
      state.token = savedToken;
      state.currentUser = JSON.parse(savedUserStr);

      // Verify token with backend
      const res = await fetch((typeof resolveApiUrl === "function") ? resolveApiUrl("/api/auth/me") : "/api/auth/me", {
        headers: { "Authorization": `Bearer ${savedToken}` }
      });

      if (res.ok) {
        const profile = await res.json();
        state.currentUser = profile;
        const overlay = document.getElementById("login-overlay");
        if (overlay) {
          overlay.classList.add("hidden");
          overlay.classList.remove("flex");
        }
        applyRoleUIConstraints(profile.role);
        fetchOverview();
        return;
      } else {
        // Saved session check failed or token expired
        handleLogout(true);
        return;
      }
    } catch (err) {
      console.warn("Failed to restore session:", err);
      handleLogout(true);
      return;
    }
  }

  // Not authenticated: clear token and show Login Screen
  handleLogout(true);
});


// --- Users Management Page Handlers (Admin Only - Gap Fix 2) ---
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

async function loadUsersList() {
  const tbody = document.getElementById("users-table-body");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="6" class="py-6 text-center text-slate-500 font-sans">Loading users from server...</td></tr>`;

  try {
    const res = await apiFetch("/api/users");
    const users = await res.json();

    if (!Array.isArray(users) || users.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="py-6 text-center text-slate-500 font-sans">No registered users found.</td></tr>`;
      return;
    }

    tbody.innerHTML = users.map(u => {
      const isSelf = state.currentUser && state.currentUser.username.toLowerCase() === u.username.toLowerCase();
      const roleBadge = u.role === 'admin'
        ? `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-cyan-950 text-cyan-400 border border-cyan-800 uppercase">ADMIN</span>`
        : (u.role === 'inspector'
          ? `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-950 text-amber-400 border border-amber-800 uppercase">INSPECTOR</span>`
          : `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-800 text-slate-300 border border-slate-700 uppercase">VIEWER</span>`);

      return `
        <tr class="hover:bg-slate-800/40 transition">
          <td class="py-3 px-4">
            <div class="font-sans font-bold text-white">${escapeHtml(u.username)}</div>
            <div class="font-sans text-[11px] text-slate-400">${escapeHtml(u.full_name || '—')}</div>
          </td>
          <td class="py-3 px-4 text-slate-400 text-[11px]">${escapeHtml(u.id)}</td>
          <td class="py-3 px-4 text-slate-400 text-[11px]">${escapeHtml(u.created_at || '—')}</td>
          <td class="py-3 px-4" id="role-badge-${escapeHtml(u.id)}">${roleBadge}</td>
          <td class="py-3 px-4">
            <select id="role-select-${escapeHtml(u.id)}" class="bg-slate-950 border border-slate-700 rounded px-2.5 py-1 text-xs text-white focus:outline-none focus:border-cyan-500 font-sans" ${isSelf ? 'disabled title="Cannot change your own role"' : ''}>
              <option value="viewer" ${u.role === 'viewer' ? 'selected' : ''}>viewer</option>
              <option value="inspector" ${u.role === 'inspector' ? 'selected' : ''}>inspector</option>
              <option value="admin" ${u.role === 'admin' ? 'selected' : ''}>admin</option>
            </select>
          </td>
          <td class="py-3 px-4 text-right">
            ${isSelf ? '<span class="text-slate-500 text-[11px] italic font-sans">Current User</span>' : `
              <button data-action="update-role" data-user-id="${escapeHtml(u.id)}" data-username="${escapeHtml(u.username)}" class="btn-update-role px-3 py-1 bg-cyan-600 hover:bg-cyan-500 text-slate-950 font-bold text-xs rounded transition font-sans">
                Update
              </button>
            `}
          </td>
        </tr>
      `;
    }).join("");

  } catch (err) {
    console.error("Failed to load users:", err);
    tbody.innerHTML = `<tr><td colspan="6" class="py-6 text-center text-red-400 font-sans">Failed to load users list.</td></tr>`;
  }
}
window.loadUsersList = loadUsersList;

async function handleRoleChange(userId, username) {
  const select = document.getElementById(`role-select-${userId}`);
  if (!select) return;
  const newRole = select.value;

  try {
    const res = await apiFetch(`/api/users/${userId}/role`, {
      method: "PATCH",
      body: { role: newRole }
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Role update failed" }));
      showToast(err.detail || "Failed to update role", "error");
      return;
    }

    showToast(`Role for ${username} changed to ${newRole.toUpperCase()}!`);
    loadUsersList();
  } catch (err) {
    console.error("Role update failed:", err);
    showToast("Role update failed", "error");
  }
}
window.handleRoleChange = handleRoleChange;

// Safe event delegation for inspections and user management tables (Requirement 9)
document.addEventListener('click', function(e) {
  const viewInspBtn = e.target.closest('.btn-view-inspection');
  if (viewInspBtn) {
    const inspId = viewInspBtn.getAttribute('data-insp-id');
    if (inspId && window.viewInspection) {
      window.viewInspection(inspId);
    }
    return;
  }
  const downloadBtn = e.target.closest('.btn-download-report');
  if (downloadBtn) {
    const inspId = downloadBtn.getAttribute('data-insp-id');
    if (inspId && window.downloadReport) {
      window.downloadReport(inspId);
    }
    return;
  }
  const updateRoleBtn = e.target.closest('.btn-update-role');
  if (updateRoleBtn) {
    const userId = updateRoleBtn.getAttribute('data-user-id');
    const username = updateRoleBtn.getAttribute('data-username');
    return;
  }
});

document.addEventListener('change', function(e) {
  if (e.target && e.target.classList.contains('survey-switcher-select')) {
    if (window.switchActiveSurvey) {
      window.switchActiveSurvey(e.target.value);
    }
  }
});
