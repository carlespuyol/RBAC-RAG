/* ============================================================
   SecureRAG UI — app.js
   Hash-based SPA router + API client + 8 page controllers
   No build tools. No frameworks. Pure DOM.
   ============================================================ */

'use strict';

// ── API client ───────────────────────────────────────────────────────────────

const API = {
  base: '',  // same origin

  async get(path) {
    const r = await fetch(this.base + path);
    if (!r.ok) throw new Error(`GET ${path} → ${r.status} ${r.statusText}`);
    return r.json();
  },

  async post(path, body) {
    const r = await fetch(this.base + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      let msg = `${r.status} ${r.statusText}`;
      try { const e = await r.json(); msg = e.message || e.detail || msg; } catch (_) {}
      throw new Error(msg);
    }
    return r.json();
  },

  async upload(path, formData) {
    const r = await fetch(this.base + path, { method: 'POST', body: formData });
    if (!r.ok) {
      let msg = `${r.status} ${r.statusText}`;
      try { const e = await r.json(); msg = e.message || e.detail || msg; } catch (_) {}
      throw new Error(msg);
    }
    return r.json();
  },
};

// ── Toast notifications ──────────────────────────────────────────────────────

function showToast(message, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  const icons = {
    success: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
    error:   '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    info:    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
  };
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `${icons[type] || icons.info}<span>${escHtml(message)}</span>`;
  container.appendChild(toast);
  setTimeout(() => { toast.style.opacity = '0'; toast.style.transition = 'opacity 300ms'; setTimeout(() => toast.remove(), 300); }, duration);
}

// ── Utilities ────────────────────────────────────────────────────────────────

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function fmtTs(ts) {
  if (!ts) return '–';
  try { return new Date(ts).toLocaleString(); } catch (_) { return ts; }
}

function fmtMs(ms) {
  if (ms == null) return '–';
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms/1000).toFixed(2)} s`;
}

function copyToClipboard(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = 'Copy'; btn.classList.remove('copied'); }, 2000);
  });
}

function codeBlock(code, lang = '') {
  const id = 'cb_' + Math.random().toString(36).slice(2);
  return `<div class="code-block-wrap">
    <pre class="code-block" id="${id}">${escHtml(code)}</pre>
    <button class="copy-btn" onclick="copyToClipboard(document.getElementById('${id}').textContent,this)">Copy</button>
  </div>`;
}

function subcatBadgeClass(subcat) {
  const map = {
    identity: 'cat-personal', contact_details: 'cat-personal',
    employment_history: 'cat-professional', skills_and_tools: 'cat-professional', references: 'cat-professional',
    academic_degrees: 'cat-education', certifications_training: 'cat-education',
    salary_expectation: 'cat-compensation', current_compensation: 'cat-compensation',
    recruiter_notes: 'cat-evaluation', interview_feedback: 'cat-evaluation',
  };
  return map[subcat] || 'badge-grey';
}

// ── Hash router ──────────────────────────────────────────────────────────────

const PAGES = ['dashboard','query','ingest','audit','roles','config','howto','architecture'];

function navigate(page) {
  window.location.hash = page;
}

function activatePage(page) {
  if (!PAGES.includes(page)) page = 'dashboard';

  // Show/hide pages
  PAGES.forEach(p => {
    const el = document.getElementById('page-' + p);
    if (el) el.classList.toggle('active', p === page);
  });

  // Update nav links
  document.querySelectorAll('.nav-link').forEach(a => {
    const href = a.getAttribute('href').slice(1); // strip #
    a.classList.toggle('active', href === page);
  });

  // Page-specific load logic
  if (page === 'dashboard') loadDashboard();
  if (page === 'query')     loadRoleCards();
  if (page === 'ingest')    loadRecentIngestions();
  if (page === 'audit')     loadAudit();
  if (page === 'roles')     loadRolesMatrix();
  if (page === 'config')    loadConfig();
  if (page === 'howto')     renderHowto();
  if (page === 'architecture') renderArchitecture();
}

window.addEventListener('hashchange', () => {
  activatePage(window.location.hash.slice(1));
});

// ── Dashboard ────────────────────────────────────────────────────────────────

let dashboardTimer = null;

async function loadDashboard() {
  clearInterval(dashboardTimer);
  await refreshDashboard();
  dashboardTimer = setInterval(refreshDashboard, 15000);
}

async function refreshDashboard() {
  try {
    const health = await API.get('/api/v1/health');
    setServiceCard('api', 'ok', 'API Server', 'FastAPI · uvicorn', '');
    setServiceCard('db',  'ok', 'ChromaDB', health.chroma_collection, `${health.document_count} docs`);
    setServiceCard('kafka', health.kafka_enabled ? 'ok' : 'warning',
      'Kafka', health.kafka_enabled ? 'Connected' : 'Disabled (direct mode)', '');

    document.getElementById('stat-docs').textContent = health.document_count ?? '–';
    document.getElementById('stat-collection').textContent = health.chroma_collection ?? '–';

    setHeaderHealth('ok');
  } catch (e) {
    setServiceCard('api', 'error', 'API Server', 'Could not reach server', '');
    setHeaderHealth('error');
  }

  try {
    const roles = await API.get('/api/v1/roles');
    document.getElementById('stat-roles').textContent = roles.roles?.length ?? '–';
  } catch (_) {}
}

function setServiceCard(key, status, name, detail, extra) {
  const dot  = document.getElementById(`svc-${key}-dot`);
  const txt  = document.getElementById(`svc-${key}-txt`);
  const det  = document.getElementById(`svc-${key}-detail`);
  const cls  = status === 'ok' ? 'green' : status === 'warning' ? 'amber' : 'red';
  const label = status === 'ok' ? 'Online' : status === 'warning' ? 'Degraded' : 'Offline';
  if (dot) { dot.className = `status-dot ${cls}`; }
  if (txt) { txt.textContent = label + (extra ? ` · ${extra}` : ''); txt.className = `service-status-text ${status}`; }
  if (det && detail) det.textContent = detail;
}

function setHeaderHealth(status) {
  const dot = document.getElementById('header-dot');
  const lbl = document.getElementById('header-status');
  if (status === 'ok') { dot.className = 'status-dot green'; lbl.textContent = 'Healthy'; }
  else                 { dot.className = 'status-dot red';   lbl.textContent = 'Unreachable'; }
}

// ── Query / Chat page ────────────────────────────────────────────────────────

let rolesData = [];
let selectedRole = null;
let chatMessages = [];

async function loadRoleCards() {
  try {
    const data = await API.get('/api/v1/roles');
    rolesData = data.roles || [];
    const container = document.getElementById('role-cards');
    container.innerHTML = '';
    rolesData.forEach(r => {
      const card = document.createElement('div');
      card.className = 'role-card' + (r.name === selectedRole ? ' selected' : '');
      card.innerHTML = `<div class="role-name">${escHtml(r.name)}</div>
        <div class="role-desc">${escHtml(r.description || '')}</div>`;
      card.onclick = () => {
        selectedRole = r.name;
        document.querySelectorAll('.role-card').forEach(c => c.classList.remove('selected'));
        card.classList.add('selected');
      };
      container.appendChild(card);
    });
    if (!selectedRole && rolesData.length) {
      selectedRole = rolesData[0].name;
      container.firstChild?.classList.add('selected');
    }
  } catch (e) {
    console.error('Failed to load roles', e);
  }
}

async function submitQuery() {
  const query = document.getElementById('q-input').value.trim();
  const errDiv = document.getElementById('query-error');
  errDiv.classList.add('hidden');

  if (!query) return;
  if (!selectedRole) { errDiv.textContent = 'Please select a role first.'; errDiv.classList.remove('hidden'); return; }

  const candidateId = document.getElementById('q-candidate').value.trim() || null;
  const topK = parseInt(document.getElementById('q-topk').value, 10);

  // Add user bubble
  appendChatBubble('user', query, null);
  document.getElementById('q-input').value = '';

  const sendBtn = document.getElementById('q-send');
  sendBtn.disabled = true;
  sendBtn.innerHTML = '<span class="chat-spinner"></span>';

  // Thinking placeholder
  const thinkId = 'think-' + Date.now();
  const thinkWrap = document.createElement('div');
  thinkWrap.className = 'chat-bubble-wrap assistant';
  thinkWrap.id = thinkId;
  thinkWrap.innerHTML = `<div class="chat-bubble assistant"><span class="chat-spinner"></span> Thinking…</div>`;
  const history = document.getElementById('chat-history');
  history.appendChild(thinkWrap);
  history.scrollTop = history.scrollHeight;

  try {
    const payload = { role: selectedRole, query, top_k: topK };
    if (candidateId) payload.candidate_id = candidateId;
    const result = await API.post('/api/v1/chat', payload);

    thinkWrap.remove();
    appendChatBubble('assistant', result.answer, result);
  } catch (e) {
    thinkWrap.remove();
    errDiv.textContent = `Error: ${e.message}`;
    errDiv.classList.remove('hidden');
  } finally {
    sendBtn.disabled = false;
    sendBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>';
  }
}

function appendChatBubble(role, text, meta) {
  const history = document.getElementById('chat-history');
  const welcome = document.getElementById('chat-welcome');
  if (welcome) welcome.style.display = 'none';

  const wrap = document.createElement('div');
  wrap.className = `chat-bubble-wrap ${role}`;

  let inner = `<div class="chat-bubble ${role}">${escHtml(text)}</div>`;

  if (meta && role === 'assistant') {
    // Subcategory badges
    const badges = (meta.allowed_subcategories || []).map(s =>
      `<span class="badge ${subcatBadgeClass(s)}">${escHtml(s)}</span>`).join('');

    // Sources accordion
    const srcs = (meta.sources || []).map(s =>
      `<div>${escHtml(s.candidate_id)} · ${escHtml(s.subcategory)} · chunk ${s.chunk_index}</div>`
    ).join('');
    const srcId = 'src-' + Date.now();

    inner += `<div class="chat-meta">
      ${meta.chunks_retrieved ?? 0} chunks · ${fmtMs(meta.latency_ms)} · ${escHtml(selectedRole)}
    </div>`;
    if (badges) inner += `<div class="chat-badges">${badges}</div>`;
    if (srcs) inner += `
      <button class="chat-sources-toggle" onclick="document.getElementById('${srcId}').classList.toggle('hidden')">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
        ${meta.sources.length} source(s)
      </button>
      <div class="chat-sources hidden" id="${srcId}">${srcs}</div>`;
  }

  wrap.innerHTML = inner;
  history.appendChild(wrap);
  history.scrollTop = history.scrollHeight;
}

function clearChat() {
  const history = document.getElementById('chat-history');
  history.innerHTML = `<div class="chat-welcome" id="chat-welcome">
    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
    <p>Select a role on the left and type your question below</p>
  </div>`;
}

// ── Ingest page ───────────────────────────────────────────────────────────────

let selectedFile = null;

function handleFileSelect(file) {
  if (!file) return;
  selectedFile = file;
  const dropZone = document.getElementById('drop-zone');
  dropZone.querySelector('p').innerHTML = `<strong>${escHtml(file.name)}</strong> (${(file.size/1024).toFixed(1)} KB)`;
  dropZone.style.borderColor = 'var(--color-accent)';

  // Auto-fill candidate ID from filename
  const cid = document.getElementById('ingest-candidate');
  if (!cid.value) {
    const base = file.name.replace(/\.pdf$/i, '').replace(/[^a-zA-Z0-9]+/g, '_').toLowerCase();
    cid.value = base;
  }
  document.getElementById('ingest-btn').disabled = false;
}

function setupDropZone() {
  const dz = document.getElementById('drop-zone');
  if (!dz) return;
  dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('dragover'); });
  dz.addEventListener('dragleave', () => dz.classList.remove('dragover'));
  dz.addEventListener('drop', e => {
    e.preventDefault();
    dz.classList.remove('dragover');
    const f = e.dataTransfer.files[0];
    if (f && f.type === 'application/pdf') handleFileSelect(f);
    else showToast('Please drop a PDF file', 'error');
  });
}

async function submitIngest() {
  if (!selectedFile) return;
  const candidateId = document.getElementById('ingest-candidate').value.trim();
  if (!candidateId) { showToast('Please enter a candidate ID', 'error'); return; }

  const btn = document.getElementById('ingest-btn');
  btn.disabled = true;

  const progWrap = document.getElementById('ingest-progress-wrap');
  const progBar  = document.getElementById('ingest-progress');
  const progLbl  = document.getElementById('ingest-progress-label');
  progWrap.classList.remove('hidden');
  progBar.style.width = '30%';
  progLbl.textContent = 'Uploading…';

  const fd = new FormData();
  fd.append('file', selectedFile);
  fd.append('candidate_id', candidateId);

  try {
    progBar.style.width = '60%';
    progLbl.textContent = 'Processing…';
    const result = await API.upload('/api/v1/ingest', fd);
    progBar.style.width = '100%';
    progBar.classList.add('success');
    progLbl.textContent = 'Done!';

    const resultDiv = document.getElementById('ingest-result');
    const resultBody = document.getElementById('ingest-result-body');
    resultDiv.style.display = 'block';
    resultBody.innerHTML = `
      <div class="flex items-center gap-8 mb-8">
        <span class="badge badge-green">${escHtml(result.status || 'ok')}</span>
        <span class="text-sm text-muted">${escHtml(result.message || '')}</span>
      </div>
      <div class="text-sm"><strong>Chunks stored:</strong> ${result.chunk_count ?? result.chunks_stored ?? '–'}</div>
      <div class="text-sm"><strong>Candidate:</strong> ${escHtml(candidateId)}</div>
    `;
    showToast(`Ingested ${result.chunk_count ?? result.chunks_stored ?? '?'} chunks for ${candidateId}`, 'success');
    loadRecentIngestions();
  } catch (e) {
    progBar.style.width = '100%';
    progBar.style.background = 'var(--color-error)';
    progLbl.textContent = 'Failed: ' + e.message;
    showToast('Ingest failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    setTimeout(() => { progWrap.classList.add('hidden'); progBar.style.width='0%'; progBar.classList.remove('success'); progBar.style.background=''; }, 3000);
  }
}

async function loadRecentIngestions() {
  const container = document.getElementById('ingest-recent-list');
  if (!container) return;
  try {
    const data = await API.get('/api/v1/audit/queries?n=30');
    const ingests = (data.entries || []).filter(e => e.event_type === 'ingest' || e.source_file);
    if (!ingests.length) { container.innerHTML = '<div class="text-dim text-sm">No ingestion events found.</div>'; return; }
    container.innerHTML = ingests.slice(0,10).map(e => `
      <div class="flex items-center gap-8" style="padding:6px 0;border-bottom:1px solid var(--color-border)">
        <span class="badge badge-blue">ingest</span>
        <span class="text-sm">${escHtml(e.candidate_id || '–')}</span>
        <span class="text-muted text-xs" style="margin-left:auto">${fmtTs(e.timestamp)}</span>
      </div>`).join('');
  } catch (e) {
    container.innerHTML = '<div class="text-dim text-sm">Could not load recent ingestions.</div>';
  }
}

// ── Audit page ────────────────────────────────────────────────────────────────

let auditData = [];
let auditTimer = null;

async function loadAudit() {
  const n = document.getElementById('audit-n')?.value || 100;
  try {
    const data = await API.get(`/api/v1/audit/queries?n=${n}`);
    auditData = data.entries || [];
    populateAuditRoleFilter();
    renderAudit();
  } catch (e) {
    document.getElementById('audit-tbody').innerHTML =
      `<tr><td colspan="7" class="empty-state">Failed to load audit: ${escHtml(e.message)}</td></tr>`;
  }
}

function populateAuditRoleFilter() {
  const sel = document.getElementById('audit-role-filter');
  if (!sel) return;
  const current = sel.value;
  const roles = [...new Set(auditData.map(e => e.role).filter(Boolean))].sort();
  sel.innerHTML = '<option value="">All roles</option>' +
    roles.map(r => `<option value="${escHtml(r)}" ${r===current?'selected':''}>${escHtml(r)}</option>`).join('');
}

function renderAudit() {
  const roleF = document.getElementById('audit-role-filter')?.value || '';
  const typeF = document.getElementById('audit-type-filter')?.value || '';
  const tbody = document.getElementById('audit-tbody');

  let rows = auditData;
  if (roleF) rows = rows.filter(e => e.role === roleF);
  if (typeF) rows = rows.filter(e => (e.event_type || (e.source_file ? 'ingest' : 'query')) === typeF);

  if (!rows.length) { tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No matching entries.</td></tr>'; return; }

  tbody.innerHTML = rows.map((e, i) => {
    const type = e.event_type || (e.source_file ? 'ingest' : 'query');
    const preview = e.query || e.source_file || '–';
    const typeBadge = type === 'query'
      ? '<span class="badge badge-blue">query</span>'
      : '<span class="badge badge-orange">ingest</span>';
    return `<tr data-idx="${i}" onclick="toggleAuditRow(this, ${i})">
      <td class="mono">${fmtTs(e.timestamp)}</td>
      <td>${typeBadge}</td>
      <td>${escHtml(e.role || '–')}</td>
      <td class="truncate" title="${escHtml(preview)}">${escHtml(preview.length > 60 ? preview.slice(0,60)+'…' : preview)}</td>
      <td>${escHtml(e.candidate_id || '–')}</td>
      <td>${e.result_count ?? e.chunk_count ?? '–'}</td>
      <td>${fmtMs(e.latency_ms)}</td>
    </tr>`;
  }).join('');
}

function toggleAuditRow(tr, idx) {
  const existing = tr.nextSibling;
  if (existing && existing.classList.contains('expanded-row')) {
    existing.remove();
    return;
  }
  const e = auditData[idx];
  const expanded = document.createElement('tr');
  expanded.className = 'expanded-row';
  expanded.innerHTML = `<td colspan="7"><pre>${escHtml(JSON.stringify(e, null, 2))}</pre></td>`;
  tr.after(expanded);
}

function toggleAuditRefresh(enabled) {
  clearInterval(auditTimer);
  if (enabled) auditTimer = setInterval(loadAudit, 5000);
}

function exportAuditCsv() {
  const headers = ['timestamp','event_type','role','query','candidate_id','result_count','latency_ms'];
  const rows = auditData.map(e =>
    headers.map(h => JSON.stringify(e[h] ?? '')).join(',')
  );
  const csv = [headers.join(','), ...rows].join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `audit_${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
}

// ── Roles / RBAC Matrix page ──────────────────────────────────────────────────

const CATEGORY_ORDER = [
  { cat: 'personal_information',   label: 'Personal Information',   subcats: ['identity','contact_details'] },
  { cat: 'professional_background', label: 'Professional Background', subcats: ['employment_history','skills_and_tools','references'] },
  { cat: 'education',              label: 'Education',              subcats: ['academic_degrees','certifications_training'] },
  { cat: 'compensation',           label: 'Compensation',           subcats: ['salary_expectation','current_compensation'] },
  { cat: 'evaluation',             label: 'Evaluation',             subcats: ['recruiter_notes','interview_feedback'] },
];

const CAT_CSS = {
  personal_information: 'cat-personal',
  professional_background: 'cat-professional',
  education: 'cat-education',
  compensation: 'cat-compensation',
  evaluation: 'cat-evaluation',
};

async function loadRolesMatrix() {
  try {
    const data = await API.get('/api/v1/roles');
    const roles = data.roles || [];
    renderRBACMatrix(roles);
    renderRoleDescCards(roles);
  } catch (e) {
    showToast('Failed to load roles: ' + e.message, 'error');
  }
}

function renderRBACMatrix(roles) {
  const table = document.getElementById('rbac-matrix');
  let html = '<thead><tr><th>Subcategory</th>' +
    roles.map(r => `<th>${escHtml(r.name)}</th>`).join('') + '</tr></thead><tbody>';

  CATEGORY_ORDER.forEach(group => {
    const cls = CAT_CSS[group.cat] || '';
    html += `<tr class="category-header"><td colspan="${roles.length+1}"><span class="badge ${cls}">${escHtml(group.label)}</span></td></tr>`;
    group.subcats.forEach(sub => {
      html += `<tr><td>${escHtml(sub)}</td>` +
        roles.map(r => {
          const allowed = r.allowed_subcategories.includes(sub);
          return `<td>${allowed ? '<span class="matrix-allow">✓</span>' : '<span class="matrix-deny">✗</span>'}</td>`;
        }).join('') + '</tr>';
    });
  });
  html += '</tbody>';
  table.innerHTML = html;
}

function renderRoleDescCards(roles) {
  const container = document.getElementById('role-desc-cards');
  if (!container) return;
  container.innerHTML = roles.map(r => `
    <div class="card">
      <div class="card-title">${escHtml(r.name)}</div>
      <p class="text-muted text-sm" style="margin-bottom:12px">${escHtml(r.description || '')}</p>
      <div class="flex flex-wrap gap-4">
        ${r.allowed_subcategories.map(s => `<span class="badge ${subcatBadgeClass(s)}">${escHtml(s)}</span>`).join('')}
      </div>
    </div>`).join('');
}

async function reloadPolicies() {
  try {
    const res = await API.post('/api/v1/admin/reload-policies', {});
    showToast(res.message || 'Policies reloaded', 'success');
    loadRolesMatrix();
  } catch (e) {
    showToast('Failed: ' + e.message, 'error');
  }
}

// ── Config page ───────────────────────────────────────────────────────────────

async function loadConfig() {
  const errDiv = document.getElementById('config-error');
  errDiv.classList.add('hidden');
  try {
    const [cfg, health] = await Promise.all([
      API.get('/api/v1/config'),
      API.get('/api/v1/health'),
    ]);
    renderConfigCards(cfg, health);
  } catch (e) {
    errDiv.textContent = 'Could not load configuration: ' + e.message;
    errDiv.classList.remove('hidden');
  }
}

function cfgRow(label, value, mono = false) {
  return `<div class="flex items-center justify-between" style="padding:7px 0;border-bottom:1px solid rgba(45,51,71,0.4)">
    <span class="text-muted text-sm">${escHtml(label)}</span>
    <span class="${mono ? 'font-mono text-xs' : 'text-sm font-bold'}">${escHtml(String(value))}</span>
  </div>`;
}

function renderConfigCards(cfg, health) {
  const container = document.getElementById('config-cards');
  container.innerHTML = `
    <div class="card">
      <div class="card-title">API &amp; Auth</div>
      ${cfgRow('API Version', cfg.api_version)}
      ${cfgRow('Together.ai API Key', cfg.together_api_key_set ? '✓ Set' : '✗ Not set')}
    </div>
    <div class="card">
      <div class="card-title">Models</div>
      ${cfgRow('Embedding', cfg.embedding_model, true)}
      ${cfgRow('LLM', cfg.llm_model, true)}
      ${cfgRow('Temperature', cfg.llm_temperature)}
      ${cfgRow('Max Tokens', cfg.llm_max_tokens)}
    </div>
    <div class="card">
      <div class="card-title">Vector Store</div>
      ${cfgRow('Collection', cfg.chroma_collection, true)}
      ${cfgRow('Persist Dir', cfg.chroma_persist_dir, true)}
      ${cfgRow('Documents Indexed', health?.document_count ?? '–')}
    </div>
    <div class="card">
      <div class="card-title">Ingestion</div>
      ${cfgRow('Chunk Size', cfg.chunk_size + ' tokens')}
      ${cfgRow('Chunk Overlap', cfg.chunk_overlap + ' tokens')}
      ${cfgRow('Kafka Mode', cfg.kafka_enabled ? '✓ Enabled' : '✗ Disabled (direct)')}
    </div>
    <div class="card">
      <div class="card-title">Paths</div>
      ${cfgRow('Audit Log', cfg.audit_log_path, true)}
    </div>
  `;
}

// ── How-to-Run page (static) ──────────────────────────────────────────────────

function renderHowto() {
  const el = document.getElementById('howto-content');
  if (el.dataset.rendered) return;
  el.dataset.rendered = '1';

  el.innerHTML = `
<div class="doc-section">
  <h2>Prerequisites</h2>
  <ul>
    <li><strong>Python 3.12+</strong> — the runtime</li>
    <li><strong>pip</strong> — comes with Python</li>
    <li><strong>Together.ai account</strong> — free tier available at <code>together.ai</code> — provides embeddings + LLM</li>
    <li><strong>Docker + Docker Compose</strong> (optional) — only needed for Kafka mode</li>
    <li><strong>make</strong> (optional but recommended) — simplifies all commands</li>
  </ul>
</div>

<div class="doc-section">
  <h2>1 — First-time setup</h2>
  ${codeBlock(`# Clone / open the project
cd c:/work/RBAC-RAG/securerag

# Create and activate virtual environment
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash / WSL
# or: .venv\\Scripts\\activate.bat  on Windows CMD

# Install all dependencies
pip install -r requirements.txt

# Copy the example env file
make setup
# or manually:
cp .env.example .env`)}
  <p>Open <code>.env</code> in your editor and add your Together.ai key:</p>
  ${codeBlock(`TOGETHER_API_KEY=your_key_here`)}
</div>

<div class="doc-section">
  <h2>2 — Start the server</h2>
  ${codeBlock(`make start
# or directly:
cd securerag
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload`)}
  <p>Open <strong>http://localhost:8000</strong> — this UI will load automatically.</p>
  <p>The interactive API docs are at <a href="/docs" target="_blank">http://localhost:8000/docs</a>.</p>
</div>

<div class="doc-section">
  <h2>3 — Ingest a CV</h2>
  <p>Use the <a href="#ingest" onclick="navigate('ingest')">Ingest page</a> in this UI, or via CLI:</p>
  ${codeBlock(`# Using make (from repo root)
make ingest FILE=data/sample_cvs/Alice_Johnson_Security_Engineer.pdf

# Or directly:
curl -X POST http://localhost:8000/api/v1/ingest \\
  -F "file=@data/sample_cvs/Alice_Johnson_Security_Engineer.pdf" \\
  -F "candidate_id=alice"`)}
</div>

<div class="doc-section">
  <h2>4 — Run a query</h2>
  <p>Use the <a href="#query" onclick="navigate('query')">Query page</a> in this UI, or via CLI:</p>
  ${codeBlock(`# Using make
make query ROLE=hr_manager QUERY="Tell me about Alice's technical skills"

# Or curl:
curl -X POST http://localhost:8000/api/v1/chat \\
  -H "Content-Type: application/json" \\
  -d '{"role":"hr_manager","query":"Tell me about Alice","candidate_id":"alice","top_k":10}'`)}
</div>

<div class="doc-section">
  <h2>5 — Run tests</h2>
  ${codeBlock(`# All tests (requires TOGETHER_API_KEY for some integration tests)
make test

# Unit tests only — no API key required
make test-unit

# Run a specific test file
pytest tests/test_sample_cvs_pipeline.py -v`)}
</div>

<div class="doc-section">
  <h2>6 — Kafka mode (optional)</h2>
  <p>By default, Kafka is disabled and CVs are ingested directly. To enable event-driven ingestion:</p>
  ${codeBlock(`# Start Kafka + Zookeeper via Docker Compose
make infra-up

# Edit .env
KAFKA_ENABLED=true

# Restart the server
make start

# Tear down Kafka
make infra-down`)}
</div>

<div class="doc-section">
  <h2>7 — Stop the server</h2>
  <p>Press <span class="kbd">Ctrl</span><span class="kbd">C</span> in the terminal where the server is running. The server gracefully shuts down Kafka consumers.</p>
  ${codeBlock(`# Kill by port if needed (PowerShell)
Get-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess | Stop-Process

# or (bash)
kill $(lsof -ti:8000)`)}
</div>

<div class="doc-section">
  <h2>Environment variables reference</h2>
  <div class="table-wrap">
    <table class="env-table">
      <thead><tr><th>Variable</th><th>Default</th><th>Required</th><th>Description</th></tr></thead>
      <tbody>
        <tr><td>TOGETHER_API_KEY</td><td>–</td><td><span class="required">Yes</span></td><td>Together.ai API key for embeddings + LLM</td></tr>
        <tr><td>KAFKA_ENABLED</td><td>false</td><td><span class="optional">No</span></td><td>Enable Kafka event pipeline</td></tr>
        <tr><td>KAFKA_BOOTSTRAP_SERVERS</td><td>localhost:9092</td><td><span class="optional">No</span></td><td>Kafka broker address(es)</td></tr>
        <tr><td>CHROMA_PERSIST_DIR</td><td>./data/chroma_db</td><td><span class="optional">No</span></td><td>ChromaDB storage directory</td></tr>
        <tr><td>CHROMA_COLLECTION</td><td>cv_chunks</td><td><span class="optional">No</span></td><td>ChromaDB collection name</td></tr>
        <tr><td>EMBEDDING_MODEL</td><td>togethercomputer/m2-bert-80M-8k-retrieval</td><td><span class="optional">No</span></td><td>Together.ai embedding model</td></tr>
        <tr><td>LLM_MODEL</td><td>meta-llama/Llama-3.1-8B-Instruct</td><td><span class="optional">No</span></td><td>Together.ai LLM model</td></tr>
        <tr><td>LLM_TEMPERATURE</td><td>0.3</td><td><span class="optional">No</span></td><td>LLM sampling temperature</td></tr>
        <tr><td>LLM_MAX_TOKENS</td><td>1024</td><td><span class="optional">No</span></td><td>LLM max output tokens</td></tr>
        <tr><td>CHUNK_SIZE</td><td>512</td><td><span class="optional">No</span></td><td>Text splitter chunk size (chars)</td></tr>
        <tr><td>CHUNK_OVERLAP</td><td>64</td><td><span class="optional">No</span></td><td>Text splitter overlap (chars)</td></tr>
        <tr><td>AUDIT_LOG_PATH</td><td>./data/audit.jsonl</td><td><span class="optional">No</span></td><td>Path for JSONL audit log</td></tr>
        <tr><td>RBAC_POLICY_PATH</td><td>config/rbac_policies.yaml</td><td><span class="optional">No</span></td><td>RBAC policy YAML file</td></tr>
        <tr><td>INFO_MODEL_PATH</td><td>config/information_model.yaml</td><td><span class="optional">No</span></td><td>Information model YAML file</td></tr>
      </tbody>
    </table>
  </div>
</div>
`;
}

// ── Architecture Deep Dive page (static) ─────────────────────────────────────

function renderArchitecture() {
  const el = document.getElementById('arch-content');
  if (el.dataset.rendered) return;
  el.dataset.rendered = '1';

  el.innerHTML = `
<div class="doc-section">
  <h2>System Overview</h2>
  <p>SecureRAG is a Retrieval-Augmented Generation (RAG) pipeline with Role-Based Access Control (RBAC) enforced at the vector-store retrieval layer. The LLM is never exposed to data that a role is not authorized to see.</p>
  ${codeBlock(`┌──────────────────────────────────────────────────────────┐
│                     SecureRAG System                     │
│                                                          │
│  ┌─────────┐    ┌───────────────────────────────────┐   │
│  │  Client │───▶│         FastAPI REST API           │   │
│  └─────────┘    │  /chat  /ingest  /health  /roles  │   │
│                 └──────────────┬────────────────────┘   │
│                                │                         │
│           ┌────────────────────┼───────────────────┐     │
│           ▼                    ▼                   ▼     │
│     ┌───────────┐   ┌──────────────────┐  ┌────────────┐ │
│     │  Ingest   │   │  Query Pipeline  │  │ Audit Log  │ │
│     │ Pipeline  │   │  (RBAC enforced) │  │  (JSONL)   │ │
│     └─────┬─────┘   └────────┬─────────┘  └────────────┘ │
│           │                  │                            │
│           ▼                  ▼                            │
│     ┌───────────────────────────────────────────────┐     │
│     │         ChromaDB Vector Store                 │     │
│     │   (metadata: category, subcategory, cid)      │     │
│     └───────────────────────────────────────────────┘     │
│                              │                            │
│                              ▼                            │
│                     ┌─────────────────┐                   │
│                     │  Together.ai    │                   │
│                     │  Embeddings+LLM │                   │
│                     └─────────────────┘                   │
└──────────────────────────────────────────────────────────┘`)}
</div>

<div class="doc-section">
  <h2>Information Model</h2>
  <p>Every chunk of text is tagged with a <strong>category</strong> and <strong>subcategory</strong>. RBAC policies are written at the subcategory level, giving fine-grained control:</p>
  ${codeBlock(`personal_information
  ├── identity                 (name, DOB, nationality)
  └── contact_details          (email, phone, LinkedIn)

professional_background
  ├── employment_history       (job titles, employers, dates)
  ├── skills_and_tools         (technologies, frameworks)
  └── references               (referee names + contacts)

education
  ├── academic_degrees         (university, degree, grade)
  └── certifications_training  (certs, course completions)

compensation
  ├── salary_expectation       (desired salary range)
  └── current_compensation     (current base + bonus)

evaluation
  ├── recruiter_notes          (internal screening notes)
  └── interview_feedback       (post-interview assessments)`)}
  <p>Source: <code>config/information_model.yaml</code></p>
</div>

<div class="doc-section">
  <h2>Ingestion Pipeline</h2>
  <p>A PDF document flows through 4 stages before landing in ChromaDB:</p>
  ${codeBlock(`PDF File
   │
   ▼  src/extraction/pdf_extractor.py
PDFExtractor.extract(path, candidate_id)
   │  → List[Document]  (one per page)
   │  metadata: candidate_id, source_file, page_number
   │
   ▼  src/extraction/chunker.py
CVChunker.split(docs)
   │  → List[Document]  (LangChain RecursiveCharacterTextSplitter)
   │  metadata: + chunk_index
   │  chunk_size=512, chunk_overlap=64
   │
   ▼  src/extraction/semantic_classifier.py
SemanticClassifier.classify_chunks(chunks)
   │  → List[Document]  (LLM classifies each chunk)
   │  metadata: + category, subcategory
   │  Model: Together.ai Llama-3.1-8B-Instruct
   │
   ▼  src/embedding/vector_store.py
VectorStore.add_documents(classified_chunks)
   │  → List[str]  (ChromaDB document IDs)
   │  Embeddings: Together.ai m2-bert-80M-8k-retrieval (768-dim)
   │  Metadata stored verbatim — enables pre-retrieval RBAC filter
   ▼
ChromaDB collection: cv_chunks`)}
  <p>Kafka mode wraps this flow: the ingest endpoint publishes a message to the <code>cv.raw.intake</code> topic, and a background consumer thread calls the same pipeline asynchronously.</p>
</div>

<div class="doc-section">
  <h2>RBAC Enforcement — The Critical Section</h2>
  <p>This is the core security property of SecureRAG. The LLM <strong>never receives documents it is not authorized to see</strong> because the filter is applied <em>before</em> retrieval, not after.</p>
  <h3>How FilterBuilder works</h3>
  ${codeBlock(`# src/rbac/policy_engine.py
policy_engine.get_allowed_subcategories("technical_interviewer")
# → ['employment_history', 'skills_and_tools', 'academic_degrees',
#    'certifications_training', 'interview_feedback']

# src/rbac/filter_builder.py
filter_builder.build("technical_interviewer")
# → {"subcategory": {"$in": ["employment_history", "skills_and_tools", ...]}}

# Special case 1: hr_manager has wildcard ("*") → empty filter {}
# → ChromaDB returns all documents (maximum performance, no filter overhead)

# Special case 2: unknown role or empty subcategory list
# → {"subcategory": {"$in": []}}  → ChromaDB returns 0 results (deny-all)`)}
  <h3>Query pipeline code path</h3>
  ${codeBlock(`# src/rag/query_pipeline.py  — QueryPipeline.run()

1. policy_engine.get_allowed_subcategories(role)
   → [list of permitted subcategories for this role]

2. filter_builder.build(role, candidate_id=...)
   → ChromaDB metadata filter dict
   (candidate_id adds: {"$and": [{subcategory filter}, {candidate_id: ...}]})

3. vector_store.get_retriever(metadata_filter, top_k)
   → LangChain VectorStoreRetriever backed by Chroma

4. retriever.invoke(query)
   → List[Document]  — ONLY documents passing the metadata filter

5. context_assembler.assemble(docs)
   → Formatted string for LLM prompt
   Each doc labelled: [category/subcategory] (candidate: alice)

6. llm.invoke(prompt_with_context)
   → AIMessage with grounded answer

7. audit_logger.log_query(role, query, result_count, latency_ms, ...)
   → appended to data/audit.jsonl`)}
  <h3>ChromaDB metadata filter syntax</h3>
  ${codeBlock(`# Single subcategory (exact match)
{"subcategory": "employment_history"}

# Multiple subcategories ($in operator)
{"subcategory": {"$in": ["employment_history", "skills_and_tools"]}}

# Candidate scope (combined $and)
{"$and": [
  {"subcategory": {"$in": ["employment_history", "skills_and_tools"]}},
  {"candidate_id": "alice"}
]}

# hr_manager wildcard — no filter applied
{}`)}
</div>

<div class="doc-section">
  <h2>Query Pipeline — Full Sequence</h2>
  ${codeBlock(`POST /api/v1/chat
  { "role": "technical_interviewer", "query": "...", "candidate_id": "alice" }
         │
         ▼  src/api/middleware/auth.py
    RoleValidationMiddleware
    → 403 if role not in policy engine
         │
         ▼  src/api/routes/chat.py
    ChatRequest validated by Pydantic v2
         │
         ▼  src/rag/query_pipeline.py
    QueryPipeline.run(role, query, candidate_id, top_k)
    │
    ├─▶ PolicyEngine → allowed_subcategories
    ├─▶ FilterBuilder → metadata_filter
    ├─▶ VectorStore.get_retriever(filter, k)
    │      └─▶ ChromaDB.similarity_search_with_metadata_filter(query_embedding)
    │              → filtered List[Document]
    ├─▶ ContextAssembler.assemble(docs) → context_string
    ├─▶ LLMService.invoke(system_prompt + context + query) → answer
    └─▶ AuditLogger.log_query(...)
         │
         ▼  ChatResponse (Pydantic)
  {
    "answer": "...",
    "role": "technical_interviewer",
    "allowed_subcategories": ["employment_history", ...],
    "chunks_retrieved": 5,
    "sources": [{"candidate_id":"alice", "subcategory":"skills_and_tools", ...}],
    "latency_ms": 1234.5
  }`)}
</div>

<div class="doc-section">
  <h2>ChromaDB Metadata Schema</h2>
  <p>Every document stored in ChromaDB carries this metadata, enabling both RBAC filtering and candidate scoping:</p>
  ${codeBlock(`{
  "candidate_id":  "alice",               # string — candidate identifier
  "source_file":   "Alice_Johnson.pdf",   # string — original PDF filename
  "category":      "professional_background",  # top-level category
  "subcategory":   "skills_and_tools",    # fine-grained classification
  "page_number":   2,                     # integer — 1-indexed
  "chunk_index":   7                      # integer — 0-indexed within CV
}`)}
</div>

<div class="doc-section">
  <h2>Kafka Event Pipeline (optional)</h2>
  ${codeBlock(`When KAFKA_ENABLED=true:

Client  ──▶  POST /api/v1/ingest
              │
              ▼  src/ingestion/kafka_producer.py
         CVKafkaProducer.send("cv.raw.intake", {path, candidate_id})
              │
              ▼  Kafka broker (localhost:9092)
              │
              ▼  src/ingestion/kafka_consumer.py  (background thread)
         CVKafkaConsumer  (group: securerag-consumer)
              │
              ▼  processing_callback(path, candidate_id)
         → same direct ingest pipeline (extract→chunk→classify→embed)

DLQ: Failed messages → "cv.dlq" topic for manual inspection.

When KAFKA_ENABLED=false (default):
  POST /api/v1/ingest → direct_ingest_fn() called synchronously`)}
</div>

<div class="doc-section">
  <h2>Code Architecture Layers</h2>
  ${codeBlock(`┌─────────────────────────────────────────┐
│           API Layer                      │
│  src/api/main.py          — app factory  │
│  src/api/routes/          — endpoints    │
│  src/api/schemas.py       — Pydantic     │
│  src/api/middleware/auth.py — role check │
├─────────────────────────────────────────┤
│           RAG Layer                      │
│  src/rag/query_pipeline.py — orchestrate│
│  src/rag/context_assembler.py           │
│  src/rag/llm_service.py                 │
├─────────────────────────────────────────┤
│        Embedding Layer                   │
│  src/embedding/embedding_service.py     │
│  src/embedding/vector_store.py          │
├─────────────────────────────────────────┤
│        Extraction Layer                  │
│  src/extraction/pdf_extractor.py        │
│  src/extraction/chunker.py              │
│  src/extraction/semantic_classifier.py  │
├─────────────────────────────────────────┤
│           RBAC Layer                     │
│  src/rbac/policy_engine.py              │
│  src/rbac/filter_builder.py             │
│  src/rbac/audit_logger.py               │
├─────────────────────────────────────────┤
│        Ingestion Layer                   │
│  src/ingestion/kafka_producer.py        │
│  src/ingestion/kafka_consumer.py        │
│  src/ingestion/file_watcher.py          │
├─────────────────────────────────────────┤
│           Config Layer                   │
│  config/rbac_policies.yaml              │
│  config/information_model.yaml          │
└─────────────────────────────────────────┘`)}
</div>
`;
}

// ── Initialization ────────────────────────────────────────────────────────────

function init() {
  // Activate initial page from hash (default: dashboard)
  const hash = window.location.hash.slice(1) || 'dashboard';
  activatePage(hash);

  // Set up drag-drop zone
  setupDropZone();

  // Keep dashboard timer alive only while on dashboard
  window.addEventListener('hashchange', () => {
    if (!window.location.hash.includes('dashboard')) clearInterval(dashboardTimer);
  });
}

document.addEventListener('DOMContentLoaded', init);
