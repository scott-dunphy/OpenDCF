/* ============================================================
   OpenDCF — Frontend Application
   Single-page app with hash routing, API integration, Chart.js
   ============================================================ */

const IS_TAURI = typeof window !== 'undefined'
    && (window.location.protocol === 'tauri:' || '__TAURI_INTERNALS__' in window);
const BACKEND_ORIGIN = IS_TAURI ? 'http://127.0.0.1:8011' : '';
const API = `${BACKEND_ORIGIN}/api/v1`;
const HEALTH_URL = `${BACKEND_ORIGIN}/health`;
const $app = () => document.getElementById('app');
const $bc = () => document.getElementById('breadcrumb');

// ─── Formatters ───────────────────────────────────────────────

const fmt = {
    currency(val, decimals = 0) {
        const n = parseFloat(val);
        if (isNaN(n)) return '—';
        const abs = Math.abs(n);
        if (abs >= 1e9) return (n < 0 ? '-' : '') + '$' + (abs / 1e9).toFixed(1) + 'B';
        if (abs >= 1e6) return (n < 0 ? '-' : '') + '$' + (abs / 1e6).toFixed(1) + 'M';
        return (n < 0 ? '-' : '') + '$' + abs.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
    },
    currencyExact(val) {
        const n = parseFloat(val);
        if (isNaN(n)) return '—';
        return (n < 0 ? '-' : '') + '$' + Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
    },
    pct(val, decimals = 2) {
        const n = parseFloat(val);
        if (isNaN(n)) return '—';
        return (n * 100).toFixed(decimals) + '%';
    },
    num(val, decimals = 0) {
        const n = parseFloat(val);
        if (isNaN(n)) return '—';
        return n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
    },
    sf(val, areaUnit) {
        const n = parseFloat(val);
        if (isNaN(n)) return '—';
        const suffix = areaUnit === 'unit' ? ' Units' : ' SF';
        return n.toLocaleString('en-US', { maximumFractionDigits: 0 }) + suffix;
    },
    date(val) {
        if (!val) return '—';
        const d = new Date(val + 'T00:00:00');
        return d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
    },
    dateFull(val) {
        if (!val) return '—';
        const d = new Date(val + 'T00:00:00');
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    },
    perSf(val, areaUnit) {
        const n = parseFloat(val);
        if (isNaN(n)) return '—';
        if (areaUnit === 'unit') {
            return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
        }
        return '$' + n.toFixed(2) + '/SF';
    },
    multiple(val) {
        const n = parseFloat(val);
        if (isNaN(n)) return '—';
        return n.toFixed(2) + 'x';
    },
    years(val) {
        const n = parseFloat(val);
        if (isNaN(n)) return '—';
        return n.toFixed(1) + ' yrs';
    },
    typeLabel(t) {
        return (t || '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    }
};

function escapeHtmlAttr(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function fiscalYearLabel(cf) {
    if (!cf || cf.year == null) return 'Year';
    return `Year ${cf.year}`;
}

function fiscalYearRangeLabel(cf) {
    if (!cf || !cf.period_start || !cf.period_end) return '';
    return `${fmt.date(cf.period_start)} - ${fmt.date(cf.period_end)}`;
}


// ─── API Client ───────────────────────────────────────────────

const api = {
    async get(path) {
        const res = await fetch(API + path);
        if (!res.ok) {
            const text = await res.text().catch(() => '');
            throw new Error(`GET ${path} → ${res.status}: ${text}`);
        }
        return res.json();
    },
    async post(path, data = {}) {
        const res = await fetch(API + path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!res.ok) {
            const text = await res.text().catch(() => '');
            throw new Error(`POST ${path} → ${res.status}: ${text}`);
        }
        if (res.status === 204) return null;
        return res.json();
    },
    async put(path, data = {}) {
        const res = await fetch(API + path, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!res.ok) {
            const text = await res.text().catch(() => '');
            throw new Error(`PUT ${path} → ${res.status}: ${text}`);
        }
        if (res.status === 204) return null;
        return res.json();
    },
    async patch(path, data = {}) {
        const res = await fetch(API + path, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!res.ok) {
            const text = await res.text().catch(() => '');
            throw new Error(`PATCH ${path} → ${res.status}: ${text}`);
        }
        if (res.status === 204) return null;
        return res.json();
    },
    async del(path) {
        const res = await fetch(API + path, { method: 'DELETE' });
        if (!res.ok) {
            const text = await res.text().catch(() => '');
            throw new Error(`DELETE ${path} → ${res.status}: ${text}`);
        }
        return null;
    },
};


// ─── Health Check ─────────────────────────────────────────────

async function checkHealth() {
    const el = document.getElementById('apiStatus');
    try {
        await fetch(HEALTH_URL);
        el.className = 'api-status connected';
        el.querySelector('span').textContent = 'API Connected';
    } catch {
        el.className = 'api-status error';
        el.querySelector('span').textContent = 'API Offline';
    }
}


// ─── Toast ────────────────────────────────────────────────────

function toast(msg, type = 'info') {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3200);
}


// ─── SVG Icons ───────────────────────────────────────────

const icons = {
    edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>',
    trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>',
    plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>',
    detail: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>',
};


// ─── Generic Form Builder ────────────────────────────────

const PERCENT_NUMBER_KEYS = new Set([
    'escalation_pct_annual',
    'renewal_probability',
    'discount_rate',
    'exit_cap_rate',
    'interest_rate',
    'cpi_floor',
    'cpi_cap',
    'same_growth',
    'same_vacancy',
    'same_credit',
    'same_renewal',
]);

function isPercentNumberField(field) {
    if (!field || field.type !== 'number') return false;
    if (field.asPercent === true) return true;
    if (field.asPercent === false) return false;
    const key = field.key || '';
    return key.endsWith('_pct') || key.endsWith('_rate') || PERCENT_NUMBER_KEYS.has(key);
}

function isPerSfNumberField(field) {
    if (!field || field.type !== 'number') return false;
    if (field.asPerSf === true) return true;
    if (field.asPerSf === false) return false;
    const key = (field.key || '').toLowerCase();
    const label = (field.label || '').toUpperCase();
    return key.includes('_per_sf') || label.includes('/SF');
}

function parseClipboardMatrix(text) {
    return String(text || '')
        .replace(/\r/g, '')
        .split('\n')
        .filter((row, i, rows) => !(i === rows.length - 1 && row === ''))
        .map(row => row.split('\t'));
}

function areFieldsPasteCompatible(sourceField, targetField) {
    if (!sourceField || !targetField) return false;
    if (sourceField.type === targetField.type) return true;
    const sourceTextLike = sourceField.type === 'text' || sourceField.type === 'textarea';
    const targetTextLike = targetField.type === 'text' || targetField.type === 'textarea';
    return sourceTextLike && targetTextLike;
}

function normalizePastedDate(raw) {
    const v = String(raw || '').trim();
    if (v === '') return '';
    if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return v;
    const us = v.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
    if (!us) return null;
    const mm = us[1].padStart(2, '0');
    const dd = us[2].padStart(2, '0');
    return `${us[3]}-${mm}-${dd}`;
}

function normalizePastedValue(raw, field, inputEl) {
    const text = String(raw || '').trim();
    if (text === '') return { ok: true, value: '' };

    if (field.type === 'checkbox') {
        const v = text.toLowerCase();
        if (['true', 'yes', 'y', '1'].includes(v)) return { ok: true, value: true };
        if (['false', 'no', 'n', '0'].includes(v)) return { ok: true, value: false };
        return { ok: false };
    }

    if (field.type === 'number') {
        const hasPercent = text.includes('%');
        const cleaned = text.replace(/[$,\s]/g, '').replace(/%/g, '');
        if (cleaned === '') return { ok: true, value: '' };
        let n = parseFloat(cleaned);
        if (Number.isNaN(n)) return { ok: false };
        if (isPercentNumberField(field) && !hasPercent && Math.abs(n) <= 1) n *= 100;
        const min = field.min != null ? parseFloat(String(field.min)) : null;
        const max = field.max != null ? parseFloat(String(field.max)) : null;
        if (min != null && !Number.isNaN(min) && n < min) return { ok: false };
        if (max != null && !Number.isNaN(max) && n > max) return { ok: false };
        return { ok: true, value: String(n) };
    }

    if (field.type === 'date') {
        const normalized = normalizePastedDate(text);
        if (normalized == null) return { ok: false };
        return { ok: true, value: normalized };
    }

    if (field.type === 'select' && inputEl && inputEl.tagName === 'SELECT') {
        const options = Array.from(inputEl.options || []);
        const direct = options.find(opt => opt.value === text);
        if (direct) return { ok: true, value: direct.value };
        const byLabel = options.find(opt => opt.textContent?.trim().toLowerCase() === text.toLowerCase());
        if (byLabel) return { ok: true, value: byLabel.value };
        return { ok: false };
    }

    return { ok: true, value: text };
}

const FORM_MEMORY_STORAGE_KEY = 'opendcf_form_memory_v1';

function getFormMemoryStore() {
    try {
        const raw = localStorage.getItem(FORM_MEMORY_STORAGE_KEY);
        if (!raw) return {};
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === 'object' ? parsed : {};
    } catch {
        return {};
    }
}

function setFormMemoryStore(store) {
    try {
        localStorage.setItem(FORM_MEMORY_STORAGE_KEY, JSON.stringify(store));
    } catch {
        // ignore storage failures
    }
}

function deriveFormMemoryKey(title, fields) {
    const keySig = (fields || [])
        .filter((f) => f && f.key && f.type !== 'section')
        .map((f) => `${f.key}:${f.type || 'text'}`)
        .join('|');
    return `${title || 'form'}::${keySig}`;
}

function readFormMemory(memoryKey) {
    if (!memoryKey) return {};
    const store = getFormMemoryStore();
    const row = store[memoryKey];
    return row && typeof row === 'object' ? row : {};
}

function writeFormMemory(memoryKey, values, fields) {
    if (!memoryKey || !values) return;
    const next = {};
    (fields || []).forEach((f) => {
        if (!f || !f.key || f.type === 'section') return;
        const v = values[f.key];
        if (f.type === 'checkbox') {
            next[f.key] = !!v;
            return;
        }
        if (v == null || v === '') return;
        next[f.key] = v;
    });
    const store = getFormMemoryStore();
    store[memoryKey] = next;
    setFormMemoryStore(store);
}

function showFormModal({ title, fields, initialValues, onSubmit, wide, smartPaste = false, memoryKey }) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    const modal = document.createElement('div');
    modal.className = 'modal' + (wide ? ' wide' : '');
    overlay.appendChild(modal);

    const titleEl = document.createElement('div');
    titleEl.className = 'modal-title';
    titleEl.textContent = title;
    modal.appendChild(titleEl);

    const formBody = document.createElement('div');
    modal.appendChild(formBody);

    const resolvedMemoryKey = memoryKey || deriveFormMemoryKey(title, fields);
    const memoryDefaults = initialValues ? {} : readFormMemory(resolvedMemoryKey);
    const hasMemoryDefaults = !initialValues && Object.keys(memoryDefaults).length > 0;

    if (hasMemoryDefaults) {
        const memoryHint = document.createElement('div');
        memoryHint.className = 'form-memory-hint';
        memoryHint.textContent = 'Prefilled from your last entry.';
        modal.insertBefore(memoryHint, formBody);
    }

    const inputEls = {};  // key → input element
    let currentRow = null;
    let currentRowCount = 0;
    const collapsedSections = new Set();  // tracks collapsed section labels

    function getVisibleInputEntries() {
        const entries = [];
        fields.forEach((f) => {
            if (!f || !f.key || f.type === 'section') return;
            const el = inputEls[f.key];
            if (!el || !formBody.contains(el)) return;
            entries.push({ key: f.key, field: f, el });
        });
        return entries;
    }

    function markPasteInvalid(el) {
        el.classList.add('paste-invalid');
        window.setTimeout(() => el.classList.remove('paste-invalid'), 1600);
    }

    function dispatchFieldEvents(entry) {
        const isSelect = entry.el.tagName === 'SELECT';
        if (entry.field.type === 'checkbox') {
            entry.el.dispatchEvent(new Event('change', { bubbles: true }));
            return;
        }
        entry.el.dispatchEvent(new Event('input', { bubbles: true }));
        if (isSelect) entry.el.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function getValues() {
        const vals = {};
        const fieldKeys = new Set();
        fields.forEach(f => {
            if (!f.key) return;
            fieldKeys.add(f.key);
            const el = inputEls[f.key];
            if (!el) return;
            if (f.type === 'checkbox') vals[f.key] = el.checked;
            else if (f.type === 'number') {
                if (el.value === '') {
                    vals[f.key] = null;
                } else {
                    let n = parseFloat(el.value);
                    if (isPercentNumberField(f)) n = n / 100;
                    vals[f.key] = n;
                }
            } else if (f.type === 'date') {
                vals[f.key] = el.value || null;
            } else vals[f.key] = el.value;
        });
        // Include values from custom field hidden inputs not in fields array
        Object.keys(inputEls).forEach(key => {
            if (fieldKeys.has(key)) return;
            const el = inputEls[key];
            if (!el) return;
            if (el.value === '') vals[key] = null;
            else {
                const n = parseFloat(el.value);
                vals[key] = isNaN(n) ? el.value : n;
            }
        });
        return vals;
    }

    function renderFields() {
        formBody.innerHTML = '';
        currentRow = null;
        currentRowCount = 0;
        let currentCollapsibleWrap = null;  // wrapper div for collapsible section content
        const vals = Object.keys(inputEls).length > 0
            ? getValues()
            : (initialValues || memoryDefaults || {});

        // Initialize default-collapsed sections on first render
        fields.forEach(f => {
            if (f.type === 'section' && f.collapsible && f.defaultCollapsed && !collapsedSections._initialized) {
                collapsedSections.add(f.label);
            }
        });
        collapsedSections._initialized = true;

        fields.forEach(f => {
            // Conditional visibility
            if (f.visibleWhen && !f.visibleWhen(vals)) return;

            if (f.type === 'section') {
                currentRow = null;
                currentRowCount = 0;
                currentCollapsibleWrap = null;
                const sec = document.createElement('div');
                sec.className = 'form-section' + (f.collapsible ? ' form-section-collapsible' : '');
                if (f.collapsible) {
                    const isCollapsed = collapsedSections.has(f.label);
                    const chevron = document.createElement('span');
                    chevron.className = 'form-section-chevron' + (isCollapsed ? ' collapsed' : '');
                    chevron.textContent = '\u25BE';
                    sec.appendChild(chevron);
                    const txt = document.createTextNode(' ' + f.label);
                    sec.appendChild(txt);
                    if (f.collapsedSummary) {
                        const badge = document.createElement('span');
                        badge.className = 'form-section-badge';
                        badge.textContent = typeof f.collapsedSummary === 'function' ? f.collapsedSummary(vals) : f.collapsedSummary;
                        sec.appendChild(badge);
                    }
                    const wrap = document.createElement('div');
                    wrap.className = 'form-section-body';
                    if (isCollapsed) wrap.style.display = 'none';
                    sec.addEventListener('click', () => {
                        if (collapsedSections.has(f.label)) {
                            collapsedSections.delete(f.label);
                            wrap.style.display = '';
                            chevron.classList.remove('collapsed');
                        } else {
                            collapsedSections.add(f.label);
                            wrap.style.display = 'none';
                            chevron.classList.add('collapsed');
                        }
                    });
                    formBody.appendChild(sec);
                    formBody.appendChild(wrap);
                    currentCollapsibleWrap = wrap;
                } else {
                    sec.textContent = f.label;
                    formBody.appendChild(sec);
                    currentCollapsibleWrap = null;
                }
                return;
            }

            const appendTarget = currentCollapsibleWrap || formBody;

            if (f.type === 'custom' && f.render) {
                currentRow = null;
                currentRowCount = 0;
                const container = document.createElement('div');
                f.render(container, vals, (key, value) => {
                    // setValue callback: update hidden inputs
                    if (!inputEls[key]) {
                        const hidden = document.createElement('input');
                        hidden.type = 'hidden';
                        hidden.id = 'form_' + key;
                        container.appendChild(hidden);
                        inputEls[key] = hidden;
                    }
                    inputEls[key].value = value;
                });
                appendTarget.appendChild(container);
                return;
            }

            if (f.type === 'checkbox') {
                currentRow = null;
                currentRowCount = 0;
                const row = document.createElement('div');
                row.className = 'form-checkbox-row';
                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.id = 'form_' + f.key;
                const initVal = vals[f.key] != null ? vals[f.key] : (f.default || false);
                cb.checked = !!initVal;
                cb.addEventListener('change', () => renderFields());
                const lbl = document.createElement('label');
                lbl.htmlFor = 'form_' + f.key;
                lbl.textContent = f.label;
                row.appendChild(cb);
                row.appendChild(lbl);
                appendTarget.appendChild(row);
                inputEls[f.key] = cb;
                return;
            }

            const group = document.createElement('div');
            group.className = 'form-group';

            const label = document.createElement('label');
            label.className = 'form-label';
            const pctSuffix = isPercentNumberField(f) && !String(f.label || '').includes('%') ? ' (%)' : '';
            label.textContent = f.label + pctSuffix + (f.required ? ' *' : '');
            group.appendChild(label);

            let input;
            if (f.type === 'select') {
                input = document.createElement('select');
                input.className = 'form-input';
                (f.options || []).forEach(opt => {
                    const o = document.createElement('option');
                    if (typeof opt === 'string') { o.value = opt; o.textContent = fmt.typeLabel(opt); }
                    else { o.value = opt.value; o.textContent = opt.label; }
                    input.appendChild(o);
                });
            } else if (f.type === 'textarea') {
                input = document.createElement('textarea');
                input.className = 'form-input';
                input.rows = 3;
            } else {
                input = document.createElement('input');
                input.className = 'form-input';
                input.type = f.type || 'text';
                if (f.step) {
                    const stepNum = parseFloat(String(f.step));
                    if (!Number.isNaN(stepNum) && isPercentNumberField(f)) input.step = String(stepNum * 100);
                    else input.step = f.step;
                }
                if (f.min != null) input.min = f.min;
                if (f.max != null) input.max = f.max;
            }

            const rawInitVal = vals[f.key] != null ? vals[f.key] : (f.default != null ? f.default : '');
            let initVal = rawInitVal;
            if (isPercentNumberField(f) && rawInitVal !== '' && rawInitVal != null) {
                const n = parseFloat(rawInitVal);
                initVal = Number.isNaN(n) ? '' : (n * 100).toFixed(2);
            } else if (isPerSfNumberField(f) && rawInitVal !== '' && rawInitVal != null) {
                const n = parseFloat(rawInitVal);
                initVal = Number.isNaN(n) ? '' : n.toFixed(2);
            }
            input.value = initVal;
            input.id = 'form_' + f.key;
            if (f.required) input.required = true;
            if (f.type === 'select') input.addEventListener('change', () => renderFields());
            if (f.suggestions && f.suggestions.length > 0 && input.tagName === 'INPUT') {
                const datalistId = `form_${f.key}_suggestions`;
                input.setAttribute('list', datalistId);
                const datalist = document.createElement('datalist');
                datalist.id = datalistId;
                f.suggestions.forEach((s) => {
                    const opt = document.createElement('option');
                    opt.value = typeof s === 'string' ? s : s.value;
                    datalist.appendChild(opt);
                });
                group.appendChild(datalist);
            }
            group.appendChild(input);

            const percentHelp = isPercentNumberField(f) ? 'Enter as percent (e.g., 5.00 for 5%).' : '';
            if (f.helpText || percentHelp) {
                const help = document.createElement('div');
                help.className = 'form-help';
                help.textContent = [percentHelp, f.helpText || ''].filter(Boolean).join(' ');
                group.appendChild(help);
            }

            if (f.afterLabel) {
                const after = document.createElement('span');
                after.innerHTML = f.afterLabel;
                label.appendChild(document.createTextNode(' '));
                label.appendChild(after);
            }

            inputEls[f.key] = input;

            // Handle half-width pairing
            if (f.half) {
                if (!currentRow || currentRowCount >= 2) {
                    currentRow = document.createElement('div');
                    currentRow.className = 'form-row';
                    appendTarget.appendChild(currentRow);
                    currentRowCount = 0;
                }
                currentRow.appendChild(group);
                currentRowCount++;
            } else {
                currentRow = null;
                currentRowCount = 0;
                appendTarget.appendChild(group);
            }
        });
    }

    renderFields();

    formBody.addEventListener('paste', (event) => {
        if (!smartPaste) return;
        const target = event.target;
        if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement)) return;
        if (!target.id || !target.id.startsWith('form_')) return;
        const startKey = target.id.slice(5);
        const visibleEntries = getVisibleInputEntries();
        const startIdx = visibleEntries.findIndex(e => e.key === startKey);
        if (startIdx < 0) return;

        const matrix = parseClipboardMatrix(event.clipboardData?.getData('text/plain') || '');
        if (matrix.length === 0 || (matrix.length === 1 && matrix[0].length === 1 && matrix[0][0] === '')) return;
        const flatValues = matrix.flat();
        const startEntry = visibleEntries[startIdx];
        const compatibleTargets = visibleEntries
            .slice(startIdx)
            .filter(entry => areFieldsPasteCompatible(startEntry.field, entry.field));

        const singleCellPaste = flatValues.length === 1;
        const shouldFillDown = singleCellPaste && startEntry.field.type === 'number' && compatibleTargets.length > 1;
        const shouldHandleBulk = flatValues.length > 1 || shouldFillDown;
        if (!shouldHandleBulk) return;

        event.preventDefault();

        let applied = 0;
        let invalid = 0;
        if (shouldFillDown) {
            const sourceValue = flatValues[0];
            compatibleTargets.forEach((entry) => {
                const normalized = normalizePastedValue(sourceValue, entry.field, entry.el);
                if (!normalized.ok) {
                    invalid++;
                    markPasteInvalid(entry.el);
                    return;
                }
                if (entry.field.type === 'checkbox') entry.el.checked = !!normalized.value;
                else entry.el.value = normalized.value;
                dispatchFieldEvents(entry);
                applied++;
            });
        } else {
            compatibleTargets.slice(0, flatValues.length).forEach((entry, idx) => {
                const normalized = normalizePastedValue(flatValues[idx], entry.field, entry.el);
                if (!normalized.ok) {
                    invalid++;
                    markPasteInvalid(entry.el);
                    return;
                }
                if (entry.field.type === 'checkbox') entry.el.checked = !!normalized.value;
                else entry.el.value = normalized.value;
                dispatchFieldEvents(entry);
                applied++;
            });
            if (flatValues.length > compatibleTargets.length) invalid += (flatValues.length - compatibleTargets.length);
        }

        if (invalid > 0) toast(`Pasted ${applied} value(s), ${invalid} invalid`, 'error');
        else if (applied > 1) toast(`Pasted ${applied} value(s)`, 'success');
    });

    // Actions
    const actions = document.createElement('div');
    actions.className = 'modal-actions';
    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'btn btn-secondary';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.onclick = () => overlay.remove();
    const submitBtn = document.createElement('button');
    submitBtn.className = 'btn btn-primary';
    submitBtn.textContent = initialValues ? 'Save Changes' : 'Create';
    actions.appendChild(cancelBtn);
    actions.appendChild(submitBtn);
    modal.appendChild(actions);

    submitBtn.onclick = async () => {
        const vals = getValues();
        // Build payload: in edit mode, only changed fields
        let payload;
        if (initialValues) {
            payload = {};
            fields.forEach(f => {
                if (f.type === 'section') return;
                if (f.visibleWhen && !f.visibleWhen(vals)) return;
                const v = vals[f.key];
                if (v !== initialValues[f.key] && !(v == null && initialValues[f.key] == null)) {
                    payload[f.key] = v;
                }
            });
        } else {
            payload = {};
            fields.forEach(f => {
                if (f.type === 'section') return;
                if (f.visibleWhen && !f.visibleWhen(vals)) return;
                const v = vals[f.key];
                if (v != null && v !== '') payload[f.key] = v;
            });
        }
        submitBtn.textContent = 'Saving...';
        submitBtn.disabled = true;
        try {
            await onSubmit(payload, overlay);
            if (!initialValues) writeFormMemory(resolvedMemoryKey, vals, fields);
        } catch (err) {
            toast('Error: ' + err.message, 'error');
            submitBtn.textContent = initialValues ? 'Save Changes' : 'Create';
            submitBtn.disabled = false;
        }
    };

    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
    document.body.appendChild(overlay);
    // Focus first visible input
    const firstInput = formBody.querySelector('input, select, textarea');
    if (firstInput) firstInput.focus();
    return overlay;
}


function formatBulkEditorValue(value, column) {
    if (value == null || value === '') return '';
    if (column.type === 'number') {
        const n = parseFloat(value);
        if (Number.isNaN(n)) return '';
        if (isPercentNumberField(column)) return (n * 100).toFixed(2);
        return String(n);
    }
    if (column.type === 'checkbox') return !!value;
    return String(value);
}

function parseBulkEditorValue(inputEl, column) {
    if (column.type === 'checkbox') return inputEl.checked;
    if (column.type === 'number') {
        if (inputEl.value === '') return null;
        const n = parseFloat(inputEl.value);
        if (Number.isNaN(n)) return null;
        return isPercentNumberField(column) ? (n / 100) : n;
    }
    const v = inputEl.value;
    return v === '' ? null : v;
}

function rowHasUserValue(row, columns) {
    return (columns || []).some((col) => {
        const v = row[col.key];
        if (col.type === 'checkbox') return !!v;
        return v != null && v !== '';
    });
}

function buildNewBulkRow(columns, seedRow = null) {
    const row = { id: null };
    (columns || []).forEach((col) => {
        if (!col || !col.key) return;
        if (col.cloneOnAdd === false) {
            if (col.default != null) row[col.key] = col.default;
            else row[col.key] = col.type === 'checkbox' ? false : null;
            return;
        }
        const seedVal = seedRow ? seedRow[col.key] : null;
        if (seedVal != null && seedVal !== '') row[col.key] = seedVal;
        else if (col.default != null) row[col.key] = col.default;
        else row[col.key] = col.type === 'checkbox' ? false : null;
    });
    return row;
}

function showBulkTableEditorModal({
    title,
    columns,
    rows,
    onSave,
    addLabel = 'Add Row',
    intro = '',
    extraTools = [],
}) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    const modal = document.createElement('div');
    modal.className = 'modal wide bulk-editor-modal';
    overlay.appendChild(modal);

    const initialRows = (rows && rows.length > 0)
        ? rows.map(r => ({ ...r }))
        : [buildNewBulkRow(columns)];
    let workingRows = initialRows.map(r => ({ ...r }));
    const deletedIds = [];

    const colDefs = (columns || []).filter(c => c && c.key);
    const tableColCount = colDefs.length;

    function render() {
        modal.innerHTML = `
            <div class="modal-title">${escapeHtmlAttr(title)}</div>
            ${intro ? `<div class="form-memory-hint">${escapeHtmlAttr(intro)}</div>` : ''}
            <div class="bulk-editor-tools">
                <button class="btn btn-secondary btn-sm" id="bulkAddRow">${icons.plus} ${addLabel}</button>
                <button class="btn btn-secondary btn-sm" id="bulkFillDown">Fill Empty From Above</button>
                <button class="btn btn-secondary btn-sm" id="bulkCopyFirst">Copy First Row To Empty Cells</button>
                ${extraTools.map((t, i) => `<button class="btn btn-secondary btn-sm" id="bulkExtraTool${i}">${escapeHtmlAttr(t.label)}</button>`).join('')}
            </div>
            <div class="bulk-editor-wrap">
                <table class="data-table bulk-editor-table" id="bulkEditorTable">
                    <thead>
                        <tr>
                            ${colDefs.map(c => `<th${c.align === 'right' ? ' class="right"' : ''}>${escapeHtmlAttr(c.label)}</th>`).join('')}
                            <th class="col-actions"></th>
                        </tr>
                    </thead>
                    <tbody>
                        ${workingRows.map((row, rowIdx) => `
                            <tr data-row-index="${rowIdx}" data-row-id="${escapeHtmlAttr(row.id || '')}">
                                ${colDefs.map((col, colIdx) => {
                                    const value = formatBulkEditorValue(row[col.key], col);
                                    if (col.type === 'checkbox') {
                                        return `<td data-col-index="${colIdx}" class="${col.align === 'right' ? 'right' : ''}">
                                            <input type="checkbox" class="bulk-input-checkbox" data-col-key="${col.key}" ${value ? 'checked' : ''} />
                                        </td>`;
                                    }
                                    if (col.type === 'select') {
                                        const opts = (col.options || []).map((opt) => {
                                            const option = typeof opt === 'string' ? { value: opt, label: fmt.typeLabel(opt) } : opt;
                                            const selected = String(option.value) === String(value ?? '') ? 'selected' : '';
                                            return `<option value="${escapeHtmlAttr(option.value)}" ${selected}>${escapeHtmlAttr(option.label)}</option>`;
                                        }).join('');
                                        return `<td data-col-index="${colIdx}" class="${col.align === 'right' ? 'right' : ''}">
                                            <select class="form-input bulk-input" data-col-key="${col.key}">${opts}</select>
                                        </td>`;
                                    }
                                    const inputType = col.type === 'date' ? 'date' : (col.type === 'number' ? 'number' : 'text');
                                    const stepAttr = col.step ? `step="${isPercentNumberField(col) ? parseFloat(String(col.step)) * 100 : col.step}"` : '';
                                    const minAttr = col.min != null ? `min="${col.min}"` : '';
                                    const maxAttr = col.max != null ? `max="${col.max}"` : '';
                                    const placeholderAttr = col.placeholder ? `placeholder="${escapeHtmlAttr(col.placeholder)}"` : '';
                                    return `<td data-col-index="${colIdx}" class="${col.align === 'right' ? 'right' : ''}">
                                        <input type="${inputType}" class="form-input bulk-input" data-col-key="${col.key}" value="${escapeHtmlAttr(value)}" ${stepAttr} ${minAttr} ${maxAttr} ${placeholderAttr} />
                                    </td>`;
                                }).join('')}
                                <td class="col-actions">
                                    <button class="btn-icon danger" data-delete-row="${rowIdx}" title="Delete row">${icons.trash}</button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
            <div class="modal-actions">
                <button class="btn btn-secondary" id="bulkCancel">Cancel</button>
                <button class="btn btn-primary" id="bulkSave">Save All</button>
            </div>
        `;

        const table = modal.querySelector('#bulkEditorTable');
        const tbody = table.querySelector('tbody');

        function snapshotRowsFromDom() {
            const snapshot = [];
            tbody.querySelectorAll('tr[data-row-index]').forEach((tr) => {
                const row = { id: tr.getAttribute('data-row-id') || null };
                tr.querySelectorAll('[data-col-key]').forEach((inputEl) => {
                    const colKey = inputEl.getAttribute('data-col-key');
                    const col = colDefs.find(c => c.key === colKey);
                    if (!col) return;
                    row[colKey] = parseBulkEditorValue(inputEl, col);
                });
                snapshot.push(row);
            });
            return snapshot;
        }

        function commitSnapshot() {
            workingRows = snapshotRowsFromDom();
        }

        modal.querySelector('#bulkAddRow').onclick = () => {
            commitSnapshot();
            const seed = workingRows.length > 0 ? workingRows[workingRows.length - 1] : null;
            workingRows.push(buildNewBulkRow(colDefs, seed));
            render();
        };

        modal.querySelector('#bulkFillDown').onclick = () => {
            commitSnapshot();
            for (let i = 1; i < workingRows.length; i++) {
                colDefs.forEach((col) => {
                    const current = workingRows[i][col.key];
                    if (current != null && current !== '') return;
                    const prev = workingRows[i - 1][col.key];
                    if (prev == null || prev === '') return;
                    workingRows[i][col.key] = prev;
                });
            }
            render();
        };

        modal.querySelector('#bulkCopyFirst').onclick = () => {
            commitSnapshot();
            if (workingRows.length === 0) return;
            const first = workingRows[0];
            for (let i = 1; i < workingRows.length; i++) {
                colDefs.forEach((col) => {
                    const current = workingRows[i][col.key];
                    if (current != null && current !== '') return;
                    const firstVal = first[col.key];
                    if (firstVal == null || firstVal === '') return;
                    workingRows[i][col.key] = firstVal;
                });
            }
            render();
        };

        // Extra tool buttons
        extraTools.forEach((tool, i) => {
            const btn = modal.querySelector(`#bulkExtraTool${i}`);
            if (btn) btn.onclick = () => tool.onClick(workingRows, render, commitSnapshot);
        });

        tbody.querySelectorAll('[data-delete-row]').forEach((btn) => {
            btn.onclick = () => {
                commitSnapshot();
                const idx = parseInt(btn.getAttribute('data-delete-row'), 10);
                const row = workingRows[idx];
                if (row && row.id) deletedIds.push(row.id);
                workingRows.splice(idx, 1);
                if (workingRows.length === 0) workingRows.push(buildNewBulkRow(colDefs));
                render();
            };
        });

        table.addEventListener('paste', (event) => {
            const target = event.target;
            if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement)) return;
            const td = target.closest('td[data-col-index]');
            const tr = target.closest('tr[data-row-index]');
            if (!td || !tr) return;
            const startRow = parseInt(tr.getAttribute('data-row-index') || '-1', 10);
            const startCol = parseInt(td.getAttribute('data-col-index') || '-1', 10);
            if (startRow < 0 || startCol < 0) return;

            const matrix = parseClipboardMatrix(event.clipboardData?.getData('text/plain') || '');
            if (matrix.length === 0) return;

            const singleCell = matrix.length === 1 && matrix[0].length === 1;
            const maxRows = table.querySelectorAll('tbody tr').length;
            if (!singleCell && matrix[0].length > tableColCount) return;

            event.preventDefault();

            let applied = 0;
            let invalid = 0;
            if (singleCell) {
                const raw = matrix[0][0];
                for (let r = startRow; r < maxRows; r++) {
                    const input = table.querySelector(`tr[data-row-index="${r}"] td[data-col-index="${startCol}"] [data-col-key]`);
                    if (!input) continue;
                    const colKey = input.getAttribute('data-col-key');
                    const col = colDefs.find(c => c.key === colKey);
                    if (!col) continue;
                    const normalized = normalizePastedValue(raw, col, input);
                    if (!normalized.ok) {
                        invalid++;
                        markPasteInvalid(input);
                        continue;
                    }
                    if (col.type === 'checkbox') input.checked = !!normalized.value;
                    else input.value = normalized.value;
                    applied++;
                }
            } else {
                matrix.forEach((rowVals, rowOffset) => {
                    const r = startRow + rowOffset;
                    if (r >= maxRows) return;
                    rowVals.forEach((raw, colOffset) => {
                        const c = startCol + colOffset;
                        if (c >= colDefs.length) return;
                        const input = table.querySelector(`tr[data-row-index="${r}"] td[data-col-index="${c}"] [data-col-key]`);
                        if (!input) return;
                        const colKey = input.getAttribute('data-col-key');
                        const col = colDefs.find(k => k.key === colKey);
                        if (!col) return;
                        const normalized = normalizePastedValue(raw, col, input);
                        if (!normalized.ok) {
                            invalid++;
                            markPasteInvalid(input);
                            return;
                        }
                        if (col.type === 'checkbox') input.checked = !!normalized.value;
                        else input.value = normalized.value;
                        applied++;
                    });
                });
            }

            if (invalid > 0) toast(`Pasted ${applied} value(s), ${invalid} invalid`, 'error');
            else if (applied > 1) toast(`Pasted ${applied} value(s)`, 'success');
        });

        modal.querySelector('#bulkCancel').onclick = () => overlay.remove();
        modal.querySelector('#bulkSave').onclick = async () => {
            const saveBtn = modal.querySelector('#bulkSave');
            const previousText = saveBtn.textContent;
            saveBtn.textContent = 'Saving...';
            saveBtn.disabled = true;
            try {
                commitSnapshot();
                const finalRows = workingRows.filter(row => rowHasUserValue(row, colDefs));
                await onSave({ rows: finalRows, deletedIds }, overlay);
            } catch (err) {
                toast('Error: ' + err.message, 'error');
                saveBtn.textContent = previousText;
                saveBtn.disabled = false;
            }
        };
    }

    render();
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
    document.body.appendChild(overlay);
    const firstInput = modal.querySelector('.bulk-input, .bulk-input-checkbox');
    if (firstInput) firstInput.focus();
    return overlay;
}


// ─── Delete Confirmation ─────────────────────────────────

function showDeleteConfirm(label, onConfirm) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
        <div class="modal" style="width:400px">
            <div class="modal-title danger">Delete ${label}?</div>
            <div class="modal-warning">This action cannot be undone. All associated data will be permanently removed.</div>
            <div class="modal-actions">
                <button class="btn btn-secondary" id="delCancel">Cancel</button>
                <button class="btn btn-danger" id="delConfirm">Delete</button>
            </div>
        </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector('#delCancel').onclick = () => overlay.remove();
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
    overlay.querySelector('#delConfirm').onclick = async () => {
        const btn = overlay.querySelector('#delConfirm');
        btn.textContent = 'Deleting...';
        btn.disabled = true;
        try {
            await onConfirm();
            overlay.remove();
        } catch (err) {
            toast('Delete failed: ' + err.message, 'error');
            btn.textContent = 'Delete';
            btn.disabled = false;
        }
    };
}


// ─── Router ───────────────────────────────────────────────────

const routes = [];

function addRoute(pattern, handler) {
    // Convert /property/:id to regex
    const paramNames = [];
    const regex = new RegExp('^' + pattern.replace(/:(\w+)/g, (_, name) => {
        paramNames.push(name);
        return '([^/]+)';
    }) + '$');
    routes.push({ regex, paramNames, handler });
}

async function navigate() {
    const hash = location.hash || '#/dashboard';
    const path = hash.slice(1); // remove #

    for (const route of routes) {
        const match = path.match(route.regex);
        if (match) {
            const params = {};
            route.paramNames.forEach((name, i) => params[name] = match[i + 1]);
            $app().innerHTML = '<div class="loading-screen"><div class="loading-spinner"></div><p>Loading...</p></div>';
            try {
                await route.handler(params);
            } catch (err) {
                console.error('Route error:', err);
                $app().innerHTML = `
                    <div class="empty-state">
                        <h3>Something went wrong</h3>
                        <p>${err.message}</p>
                        <br><a href="#/dashboard" class="btn btn-secondary">Back to Dashboard</a>
                    </div>`;
            }
            return;
        }
    }
    // Default: dashboard
    location.hash = '#/dashboard';
}


// ─── Breadcrumb Helper ────────────────────────────────────────

function setBreadcrumb(items) {
    const bc = $bc();
    bc.innerHTML = items.map((item, i) => {
        if (i === items.length - 1) {
            return `<span class="current">${item.label}</span>`;
        }
        return `<a href="${item.href}">${item.label}</a><span class="sep">/</span>`;
    }).join('');
}


// ─── Chart.js Global Config ──────────────────────────────────

Chart.defaults.color = '#86868b';
Chart.defaults.borderColor = '#e8e8ed';
Chart.defaults.font.family = "'Inter', -apple-system, sans-serif";
Chart.defaults.font.size = 11;
Chart.defaults.plugins.legend.display = false;
Chart.defaults.plugins.tooltip.backgroundColor = '#1d1d1f';
Chart.defaults.plugins.tooltip.borderColor = '#1d1d1f';
Chart.defaults.plugins.tooltip.borderWidth = 0;
Chart.defaults.plugins.tooltip.cornerRadius = 8;
Chart.defaults.plugins.tooltip.titleFont = { family: "'Inter', sans-serif", size: 12, weight: 600 };
Chart.defaults.plugins.tooltip.bodyFont = { family: "'Inter', sans-serif", size: 11 };
Chart.defaults.plugins.tooltip.padding = 10;


// ═══════════════════════════════════════════════════════════════
// FIELD DEFINITIONS
// ═══════════════════════════════════════════════════════════════

const PROPERTY_TYPES = ['office', 'retail', 'industrial', 'mixed_use', 'multifamily', 'self_storage'];
const AREA_UNITS = ['sf', 'unit'];

const PROPERTY_FIELDS = [
    { key: 'name', label: 'Property Name', type: 'text', required: true },
    { key: 'property_type', label: 'Property Type', type: 'select', options: PROPERTY_TYPES, required: true, half: true },
    { key: 'area_unit', label: 'Area Unit', type: 'select', options: AREA_UNITS, half: true, default: 'sf' },
    { key: 'total_area', label: 'Total Area', type: 'number', required: true, step: '1', half: true },
    { key: 'year_built', label: 'Year Built', type: 'number', step: '1', half: true },
    { key: 'address_line1', label: 'Address Line 1', type: 'text' },
    { key: 'address_line2', label: 'Address Line 2', type: 'text' },
    { key: 'city', label: 'City', type: 'text', half: true },
    { key: 'state', label: 'State', type: 'text', half: true },
    { key: 'zip_code', label: 'Zip Code', type: 'text', half: true },
    { key: 'analysis_start_date', label: 'Analysis Start Date', type: 'date', required: true, half: true },
    { key: 'analysis_period_months', label: 'Analysis Period (months)', type: 'number', step: '1', default: 120, half: true },
    { key: 'fiscal_year_end_month', label: 'Fiscal Year End Month', type: 'number', step: '1', default: 12, min: 1, max: 12, half: true },
    { key: 'comment', label: 'Comment / Source Note', type: 'textarea' },
];

function buildSuiteFields(marketProfiles, areaUnit, simplifyUnitAssumptions = false) {
    const isUnit = areaUnit === 'unit';
    const areaFieldLabel = isUnit ? 'Unit Count' : 'Area (SF)';
    const mlaOptions = [
        { value: '', label: '— Auto (match by space type) —' },
        ...(marketProfiles || []).map(m => ({ value: m.id, label: `${fmt.typeLabel(m.space_type)} — ${fmt.perSf(m.market_rent_per_unit, areaUnit)}` }))
    ];
    const fields = [
        { key: 'suite_name', label: isUnit ? 'Unit Type Name' : 'Suite Name', type: 'text', required: true },
        { key: 'area', label: areaFieldLabel, type: 'number', required: true, step: '1', half: true },
        {
            key: 'space_type',
            label: isUnit ? 'Unit Type' : 'Space Type',
            type: 'text',
            required: true,
            half: true,
            helpText: simplifyUnitAssumptions
                ? 'Unit type key used by rent roll assumptions (e.g., studio, 1br, climate_5x10).'
                : 'e.g., office, retail, industrial'
        },
    ];
    if (!simplifyUnitAssumptions) {
        fields.push({ key: 'floor', label: 'Floor', type: 'number', step: '1', half: true });
    }
    if (!simplifyUnitAssumptions) {
        fields.push({
            key: 'market_leasing_profile_id',
            label: 'Market Leasing Profile',
            type: 'select',
            options: mlaOptions,
            half: true,
            helpText: 'Assign MLA for renewal/new-tenant modeling',
        });
    }
    fields.push({ key: 'is_available', label: 'Available for leasing', type: 'checkbox', default: true });
    fields.push({ key: 'comment', label: 'Comment / Source Note', type: 'textarea' });
    return fields;
}

function buildTenantFields(propertyType = '') {
    const isUnit = propertyType === 'multifamily' || propertyType === 'self_storage';
    const fields = [
        { key: 'name', label: isUnit ? 'Resident Name' : 'Tenant Name', type: 'text', required: true },
    ];
    if (!isUnit) {
        fields.push({ key: 'credit_rating', label: 'Credit Rating', type: 'text', half: true });
        fields.push({ key: 'industry', label: 'Industry', type: 'text', half: true });
    }
    fields.push({ key: 'contact_name', label: 'Contact Name', type: 'text', half: true });
    fields.push({ key: 'contact_email', label: 'Contact Email', type: 'text', half: true });
    fields.push({ key: 'comment', label: 'Comment / Source Note', type: 'textarea' });
    return fields;
}
const TENANT_FIELDS = buildTenantFields();

function buildUnitTypeFields(areaUnit = 'unit') {
    return [
        { key: 'suite_name', label: 'Unit Type Name', type: 'text', required: true, half: true, helpText: 'e.g., Studio, 1BR, 2BR, 5x10 Climate' },
        { key: 'space_type', label: 'Unit Type Key', type: 'text', required: true, half: true, helpText: 'Used to link market assumptions (e.g., studio, 1br, climate_5x10)' },
        { key: 'area', label: areaUnit === 'unit' ? 'Unit Count' : 'Area', type: 'number', required: true, step: '1', half: true },
        { key: 'is_vacant', label: 'Vacant (no current lease)', type: 'checkbox', default: false, half: true },
        { type: 'section', label: 'Current Lease' },
        { key: 'resident_name', label: 'Resident Name', type: 'text', half: true, visibleWhen: v => !v.is_vacant, helpText: 'Optional — leave blank for unnamed occupancy' },
        { key: 'base_rent_per_unit', label: 'Rent $/Unit/mo', type: 'number', required: true, step: '0.01', half: true, visibleWhen: v => !v.is_vacant },
        { key: 'lease_start_date', label: 'Lease Start', type: 'date', required: true, half: true, visibleWhen: v => !v.is_vacant },
        { key: 'lease_end_date', label: 'Lease End', type: 'date', required: true, half: true, visibleWhen: v => !v.is_vacant },
    ];
}

const ESCALATION_TYPES = ['flat', 'pct_annual', 'cpi', 'fixed_step'];
const RECOVERY_TYPES = ['nnn', 'full_service_gross', 'modified_gross', 'base_year_stop', 'none'];
const LEASE_TYPES = ['in_place', 'market', 'month_to_month'];

function buildLeaseFields(suites, tenants, onNewTenant, recoveryStructures, includeSuite = true, areaUnit = 'sf', propertyType = '') {
    const rsOptions = [
        { value: '', label: '— None —' },
        ...(recoveryStructures || []).map(rs => ({ value: rs.id, label: rs.name }))
    ];
    const fields = [
        { key: 'tenant_id', label: 'Tenant', type: 'select', options: [{ value: '', label: '— None (Vacant) —' }, ...tenants.map(t => ({ value: t.id, label: t.name }))], afterLabel: onNewTenant ? `<button type="button" class="form-inline-link" id="inlineNewTenant">+ New Tenant</button>` : undefined },
        { key: 'lease_type', label: 'Lease Type', type: 'select', options: LEASE_TYPES, default: 'in_place', half: true },
        { key: 'comment', label: 'Comment / Source Note', type: 'textarea' },
        { key: 'rent_payment_frequency', label: 'Payment Frequency', type: 'select', options: [{ value: 'annual', label: 'Annual ($/SF/yr)' }, { value: 'monthly', label: 'Monthly ($/unit/mo)' }], default: 'annual', half: true },
        {
            key: 'base_rent_per_unit',
            label: 'Base Rent',
            type: 'number',
            required: true,
            step: '0.01',
            half: true,
            asPerSf: areaUnit !== 'unit',
            helpText: 'Per unit per payment frequency above',
        },
        { key: 'lease_start_date', label: 'Start Date', type: 'date', required: true, half: true },
        { key: 'lease_end_date', label: 'End Date', type: 'date', required: true, half: true },
        { type: 'section', label: 'Escalation', collapsible: true, collapsedSummary: (v) => v.escalation_type ? fmt.typeLabel(v.escalation_type) : 'Flat' },
        { key: 'escalation_type', label: 'Escalation Type', type: 'select', options: ESCALATION_TYPES, default: 'flat', half: true },
        { key: 'escalation_pct_annual', label: 'Annual Escalation %', type: 'number', step: '0.0025', half: true, helpText: 'Enter percent, e.g. 3.00 = 3%', visibleWhen: v => v.escalation_type === 'pct_annual' },
        { key: 'cpi_floor', label: 'CPI Floor', type: 'number', step: '0.005', half: true, visibleWhen: v => v.escalation_type === 'cpi' },
        { key: 'cpi_cap', label: 'CPI Cap', type: 'number', step: '0.005', half: true, visibleWhen: v => v.escalation_type === 'cpi' },
        { type: 'section', label: 'Recovery', collapsible: true, collapsedSummary: (v) => v.recovery_structure_id ? 'Template' : (v.recovery_type ? fmt.typeLabel(v.recovery_type) : 'NNN') },
        { key: 'recovery_structure_id', label: 'Recovery Structure', type: 'select', options: rsOptions, half: true, helpText: 'Assign a template or set recovery type manually below' },
        { key: 'recovery_type', label: 'Recovery Type', type: 'select', options: RECOVERY_TYPES, default: 'nnn', half: true, helpText: 'Fallback when no template assigned' },
        { key: 'pro_rata_share_pct', label: 'Pro Rata Share %', type: 'number', step: '0.01', half: true, helpText: 'Enter percent (0-100). Leave blank for auto.' },
        { key: 'base_year', label: 'Base Year', type: 'number', step: '1', half: true, visibleWhen: v => v.recovery_type === 'base_year_stop' },
        { key: 'base_year_stop_amount', label: 'Base Year Stop $', type: 'number', step: '0.01', half: true, visibleWhen: v => v.recovery_type === 'base_year_stop' },
        { key: 'expense_stop_per_sf', label: 'Expense Stop $/SF', type: 'number', step: '0.01', half: true, visibleWhen: v => v.recovery_type === 'modified_gross' },
        { type: 'section', label: 'Percentage Rent', collapsible: true, defaultCollapsed: true },
        { key: 'pct_rent_breakpoint', label: 'Breakpoint ($)', type: 'number', step: '0.01', half: true },
        { key: 'pct_rent_rate', label: 'Pct Rent Rate', type: 'number', step: '0.005', half: true, helpText: 'Enter percent, e.g. 6.00 = 6%' },
        { key: 'projected_annual_sales_per_sf', label: 'Projected Sales $/SF/yr', type: 'number', step: '0.01', half: true, visibleWhen: v => v.pct_rent_rate > 0 },
        { type: 'section', label: 'Renewal', collapsible: true, defaultCollapsed: true, collapsedSummary: 'Uses market defaults if empty' },
        { key: 'renewal_probability', label: 'Renewal Probability', type: 'number', step: '0.05', half: true, helpText: 'Enter percent (0-100)' },
        { key: 'renewal_rent_spread_pct', label: 'Renewal Rent Adjustment', type: 'number', step: '0.01', half: true, helpText: 'e.g. 5.00 = 5% above market, -5.00 = 5% below' },
    ];
    if (includeSuite) {
        const unitSuffix = areaUnit === 'unit' ? ' Units' : ' SF';
        fields.unshift({
            key: 'suite_id',
            label: areaUnit === 'unit' ? 'Unit Type' : 'Suite',
            type: 'select',
            required: true,
            options: suites.map(s => ({ value: s.id, label: `${s.suite_name} (${fmt.num(s.area)}${unitSuffix})` })),
        });
    }
    fields.forEach((f) => {
        if (f.key === 'recovery_structure_id') {
            f.helpText = 'Assign a template. Leave blank to set recovery manually below.';
        }
        if (f.key === 'recovery_type' || f.key === 'pro_rata_share_pct') {
            f.visibleWhen = (v) => !v.recovery_structure_id;
        }
        if (f.key === 'base_year' || f.key === 'base_year_stop_amount') {
            f.visibleWhen = (v) => !v.recovery_structure_id && v.recovery_type === 'base_year_stop';
        }
        if (f.key === 'expense_stop_per_sf') {
            f.visibleWhen = (v) => !v.recovery_structure_id && v.recovery_type === 'modified_gross';
        }
    });

    // Smart defaults by property type
    const isMultifamily = propertyType === 'multifamily' || propertyType === 'self_storage';
    const isRetail = propertyType === 'retail';
    if (isMultifamily) {
        // Hide commercial-only sections and fields
        const hideKeys = new Set([
            'recovery_structure_id', 'recovery_type', 'pro_rata_share_pct',
            'base_year', 'base_year_stop_amount', 'expense_stop_per_sf',
            'pct_rent_breakpoint', 'pct_rent_rate', 'projected_annual_sales_per_sf',
            'rent_payment_frequency', 'renewal_probability', 'renewal_rent_spread_pct',
        ]);
        const hideSections = new Set(['Recovery', 'Percentage Rent', 'Escalation', 'Renewal']);
        fields.forEach(f => {
            if (f.type === 'section' && hideSections.has(f.label)) {
                f.visibleWhen = () => false;
            }
            if (hideKeys.has(f.key)) {
                f.visibleWhen = () => false;
            }
            // Hide escalation fields
            if (['escalation_type', 'escalation_pct_annual', 'cpi_floor', 'cpi_cap'].includes(f.key)) {
                f.visibleWhen = () => false;
            }
            // Default payment frequency to monthly for unit properties
            if (f.key === 'rent_payment_frequency') {
                f.default = 'monthly';
            }
            // Adjust base rent label
            if (f.key === 'base_rent_per_unit') {
                f.helpText = '$/unit/month';
            }
        });
    } else if (!isRetail) {
        // Office/industrial: hide percentage rent by default (keep section header collapsed)
        fields.forEach(f => {
            if (f.type === 'section' && f.label === 'Percentage Rent') {
                f.defaultCollapsed = true;
            }
        });
    }

    return fields;
}

const STANDARD_EXPENSE_CATEGORIES = ['real_estate_taxes', 'insurance', 'cam', 'utilities', 'management_fee', 'repairs_maintenance', 'general_admin', 'other'];
const MULTIFAMILY_EXPENSE_CATEGORIES = ['real_estate_taxes', 'insurance', 'utilities', 'management_fee', 'repairs_maintenance', 'payroll', 'marketing', 'general_admin', 'contract_services', 'other'];

function buildExpenseFields(propertyType) {
    const isMultifamily = propertyType === 'multifamily' || propertyType === 'self_storage';
    const categories = isMultifamily ? MULTIFAMILY_EXPENSE_CATEGORIES : STANDARD_EXPENSE_CATEGORIES;
    const fields = [
        {
            key: 'category',
            label: 'Category',
            type: 'text',
            required: true,
            suggestions: categories,
            helpText: 'Use a standard category or enter your own custom category.',
        },
        { key: 'description', label: 'Description', type: 'text' },
        { key: 'comment', label: 'Comment / Source Note', type: 'textarea' },
        { key: 'base_year_amount', label: 'Base Year Amount ($)', type: 'number', required: true, step: '0.01', half: true, visibleWhen: v => !v.is_pct_of_egi },
        { key: 'growth_rate_pct', label: 'Annual Growth Rate', type: 'number', step: '0.005', default: 0.03, half: true, helpText: 'Enter percent, e.g. 3.00 = 3%', visibleWhen: v => !v.is_pct_of_egi },
    ];
    if (!isMultifamily) {
        fields.push(
            { key: 'is_recoverable', label: 'Recoverable from tenants', type: 'checkbox', default: true },
            { key: 'is_gross_up_eligible', label: 'Gross-up eligible', type: 'checkbox', default: false },
            { key: 'gross_up_vacancy_pct', label: 'Gross-Up Vacancy %', type: 'number', step: '0.01', half: true, helpText: 'Enter percent', visibleWhen: v => v.is_gross_up_eligible },
        );
    }
    fields.push(
        { key: 'is_pct_of_egi', label: '% of EGI (instead of fixed amount)', type: 'checkbox', default: false },
        { key: 'pct_of_egi', label: 'Percentage of EGI', type: 'number', step: '0.005', half: true, helpText: 'Enter percent, e.g. 4.00 = 4%', visibleWhen: v => v.is_pct_of_egi },
    );
    return fields;
}
const EXPENSE_FIELDS = buildExpenseFields();

const OTHER_INCOME_FIELDS = [
    { key: 'category', label: 'Category', type: 'text', required: true, helpText: 'e.g., parking, signage, telecom, laundry' },
    { key: 'description', label: 'Description', type: 'text' },
    { key: 'comment', label: 'Comment / Source Note', type: 'textarea' },
    { key: 'base_year_amount', label: 'Base Year Amount ($)', type: 'number', required: true, step: '0.01', half: true },
    { key: 'growth_rate_pct', label: 'Annual Growth Rate', type: 'number', step: '0.005', default: 0.03, half: true, helpText: 'Enter percent, e.g. 3.00 = 3%' },
];

const MARKET_FIELDS = [
    { key: 'space_type', label: 'Space Type', type: 'text', required: true, helpText: 'Must match suite space types to link' },
    { key: 'description', label: 'Description', type: 'text' },
    { key: 'comment', label: 'Comment / Source Note', type: 'textarea' },
    { key: 'market_rent_per_unit', label: 'Market Rent ($/SF/yr)', type: 'number', required: true, step: '0.01', half: true },
    { key: 'rent_growth_rate_pct', label: 'Rent Growth Rate', type: 'number', step: '0.005', default: 0.03, half: true, helpText: 'Enter percent' },
    { type: 'section', label: 'New Tenant Assumptions' },
    { key: 'new_lease_term_months', label: 'Lease Term (months)', type: 'number', step: '1', default: 60, half: true },
    { key: 'new_tenant_ti_per_sf', label: 'TI ($/SF)', type: 'number', step: '0.01', default: 0, half: true },
    { key: 'new_tenant_lc_pct', label: 'Leasing Commission %', type: 'number', step: '0.005', default: 0.06, half: true, helpText: 'Enter percent' },
    { key: 'new_tenant_free_rent_months', label: 'Free Rent (months)', type: 'number', step: '1', default: 0, half: true },
    { key: 'downtime_months', label: 'Downtime (months)', type: 'number', step: '1', default: 3, half: true },
    { type: 'section', label: 'Renewal Assumptions' },
    { key: 'renewal_probability', label: 'Renewal Probability', type: 'number', step: '0.05', default: 0.65, half: true, helpText: 'Enter percent' },
    { key: 'renewal_lease_term_months', label: 'Renewal Term (months)', type: 'number', step: '1', default: 60, half: true },
    { key: 'renewal_ti_per_sf', label: 'Renewal TI ($/SF)', type: 'number', step: '0.01', default: 0, half: true },
    { key: 'renewal_lc_pct', label: 'Renewal LC %', type: 'number', step: '0.005', default: 0.03, half: true, helpText: 'Enter percent' },
    { key: 'renewal_free_rent_months', label: 'Renewal Free Rent (months)', type: 'number', step: '1', default: 0, half: true },
    { key: 'renewal_rent_adjustment_pct', label: 'Renewal Rent Adjustment', type: 'number', step: '0.01', default: 0, half: true, helpText: 'e.g. 5.00 = 5% above market' },
    { type: 'section', label: 'Vacancy & Credit' },
    { key: 'general_vacancy_pct', label: 'General Vacancy %', type: 'number', step: '0.005', default: 0.05, half: true, helpText: 'Enter percent' },
    { key: 'credit_loss_pct', label: 'Credit Loss %', type: 'number', step: '0.005', default: 0.01, half: true, helpText: 'Enter percent' },
];

const CONCESSION_TIMING_OPTIONS = [
    { value: 'blended', label: 'Blended' },
    { value: 'timed', label: 'Timed by Year' },
];

function buildMarketFields(areaUnit, includeSpaceType = true) {
    const isUnit = areaUnit === 'unit';
    if (!isUnit) {
        if (includeSpaceType) return MARKET_FIELDS;
        return MARKET_FIELDS.filter(f => f.key !== 'space_type');
    }

    const unitFields = [
        { key: 'description', label: 'Description', type: 'text' },
        { key: 'comment', label: 'Comment / Source Note', type: 'textarea' },
        { key: 'market_rent_per_unit', label: 'Market Rent ($/Unit/mo)', type: 'number', required: true, step: '0.01', half: true },
        { key: 'rent_growth_rate_pct', label: 'Rent Growth Rate', type: 'number', step: '0.005', default: 0.03, half: true, helpText: 'Enter percent' },
        { key: 'general_vacancy_pct', label: 'General Vacancy %', type: 'number', step: '0.005', default: 0.05, half: true, helpText: 'Enter percent' },
        { key: 'credit_loss_pct', label: 'Credit Loss %', type: 'number', step: '0.005', default: 0.01, half: true, helpText: 'Enter percent' },
        { key: 'renewal_probability', label: 'Renewal Probability', type: 'number', step: '0.05', default: 0.65, half: true, helpText: 'Used as annual turnover proxy (1 - renewal)' },
        { key: 'new_tenant_free_rent_months', label: 'New Lease Concession (months)', type: 'number', step: '1', default: 0, half: true, helpText: 'Expected months free on turnover leases' },
        { key: 'renewal_free_rent_months', label: 'Renewal Concession (months)', type: 'number', step: '1', default: 0, half: true, helpText: 'Expected months free on renewal leases' },
        { key: 'concession_timing_mode', label: 'Concession Timing', type: 'select', options: CONCESSION_TIMING_OPTIONS, default: 'blended', half: true },
        {
            type: 'custom',
            key: '_concession_timing_table',
            visibleWhen: v => v.concession_timing_mode === 'timed',
            render: (container, vals, setValue) => {
                const yearKeys = [
                    { key: 'concession_year1_months', label: 'Year 1' },
                    { key: 'concession_year2_months', label: 'Year 2' },
                    { key: 'concession_year3_months', label: 'Year 3' },
                    { key: 'concession_year4_months', label: 'Year 4' },
                    { key: 'concession_year5_months', label: 'Year 5' },
                    { key: 'concession_stabilized_months', label: 'Year 6+' },
                ];
                container.className = 'concession-timing-table';
                container.innerHTML = `
                    <div class="form-label" style="margin-bottom:8px">Concession Schedule (months free per year)</div>
                    <div class="concession-grid">
                        ${yearKeys.map(yk => `
                            <div class="concession-cell">
                                <label class="concession-cell-label">${yk.label}</label>
                                <input type="number" step="0.25" min="0" max="12" class="form-input concession-cell-input" data-ck="${yk.key}"
                                    value="${vals[yk.key] != null ? vals[yk.key] : ''}" placeholder="0">
                            </div>
                        `).join('')}
                    </div>`;
                yearKeys.forEach(yk => {
                    const inp = container.querySelector(`[data-ck="${yk.key}"]`);
                    const initVal = vals[yk.key] != null ? String(vals[yk.key]) : '';
                    setValue(yk.key, initVal);
                    inp.addEventListener('input', () => setValue(yk.key, inp.value));
                });
            },
        },
        { key: 'new_tenant_ti_per_sf', label: 'Turnover Cost ($/Unit/turn)', type: 'number', step: '0.01', default: 0, half: true, helpText: 'Used in occupancy model as turnover cost per turn' },
    ];
    if (!includeSpaceType) return unitFields;
    return [
        { key: 'space_type', label: 'Unit Type', type: 'text', required: true, helpText: 'Must match suite space type (e.g., studio, 1br, climate_5x10)' },
        ...unitFields,
    ];
}

function buildPayloadFromBulkRow(row, columns) {
    const payload = {};
    (columns || []).forEach((col) => {
        if (!col || !col.key) return;
        if (col.type === 'checkbox') {
            payload[col.key] = !!row[col.key];
            return;
        }
        const v = row[col.key];
        if (v == null || v === '') return;
        payload[col.key] = v;
    });
    return payload;
}

function summarizeBulkFailures(results) {
    const failed = results.filter(r => r.status === 'rejected');
    if (failed.length === 0) return null;
    return failed[0].reason?.message || 'Unknown error';
}

function defaultMarketProfileValues(areaUnit) {
    const common = {
        market_rent_per_unit: null,
        rent_growth_rate_pct: 0.03,
        new_lease_term_months: 60,
        new_tenant_ti_per_sf: 0,
        new_tenant_lc_pct: 0.06,
        new_tenant_free_rent_months: 0,
        downtime_months: areaUnit === 'unit' ? 1 : 3,
        renewal_probability: areaUnit === 'unit' ? 0.70 : 0.65,
        renewal_lease_term_months: 60,
        renewal_ti_per_sf: 0,
        renewal_lc_pct: 0.03,
        renewal_free_rent_months: 0,
        renewal_rent_adjustment_pct: 0,
        general_vacancy_pct: 0.05,
        credit_loss_pct: 0.01,
        concession_timing_mode: 'blended',
        concession_year1_months: null,
        concession_year2_months: null,
        concession_year3_months: null,
        concession_year4_months: null,
        concession_year5_months: null,
        concession_stabilized_months: null,
        comment: null,
        description: null,
    };
    return common;
}

function openMarketAssumptionWorkspace(propertyId, property, marketProfiles) {
    const areaUnit = property.area_unit || 'sf';
    const isUnit = areaUnit === 'unit';
    const defaults = defaultMarketProfileValues(areaUnit);
    const suiteTypes = [...new Set((property.suites || []).map((s) => s.space_type).filter(Boolean))];
    const byType = {};
    (marketProfiles || []).forEach((p) => { byType[p.space_type] = p; });

    const rows = [];
    suiteTypes.forEach((spaceType) => {
        const existing = byType[spaceType];
        if (existing) rows.push({ ...defaults, ...existing, id: existing.id, space_type: existing.space_type });
        else rows.push({ ...defaults, id: null, space_type: spaceType });
    });
    (marketProfiles || []).forEach((p) => {
        if (suiteTypes.includes(p.space_type)) return;
        rows.push({ ...defaults, ...p, id: p.id, space_type: p.space_type });
    });
    if (rows.length === 0) rows.push({ ...defaults, id: null, space_type: '' });

    const columns = [
        { key: 'space_type', label: isUnit ? 'Unit Type' : 'Space Type', type: 'text', required: true, cloneOnAdd: false },
        { key: 'market_rent_per_unit', label: isUnit ? 'Mkt Rent $/Unit/mo' : 'Mkt Rent $/SF/yr', type: 'number', step: '0.01', align: 'right' },
        { key: 'rent_growth_rate_pct', label: 'Growth %', type: 'number', step: '0.005', asPercent: true, align: 'right', default: 0.03 },
        { key: 'general_vacancy_pct', label: 'Vacancy %', type: 'number', step: '0.005', asPercent: true, align: 'right', default: 0.05 },
        { key: 'credit_loss_pct', label: 'Credit %', type: 'number', step: '0.005', asPercent: true, align: 'right', default: 0.01 },
        { key: 'renewal_probability', label: 'Renewal %', type: 'number', step: '0.01', asPercent: true, align: 'right', default: isUnit ? 0.70 : 0.65 },
        { key: 'new_tenant_ti_per_sf', label: isUnit ? 'Turnover $/Unit' : 'New TI $/SF', type: 'number', step: '0.01', align: 'right', default: 0 },
        { key: 'new_tenant_free_rent_months', label: 'New Concession (mo)', type: 'number', step: '0.25', align: 'right', default: 0 },
        { key: 'renewal_free_rent_months', label: 'Renewal Concession (mo)', type: 'number', step: '0.25', align: 'right', default: 0 },
        { key: 'concession_timing_mode', label: 'Concession Timing', type: 'select', options: CONCESSION_TIMING_OPTIONS, default: 'blended' },
        { key: 'comment', label: 'Comment', type: 'text', cloneOnAdd: false },
    ];

    showBulkTableEditorModal({
        title: 'Assumption Workspace',
        columns,
        rows,
        addLabel: isUnit ? 'Add Unit Type' : 'Add Space Type',
        intro: 'Spreadsheet-style assumptions editor. Paste ranges directly from Excel/Sheets; use fill-down tools to minimize clicks.',
        onSave: async ({ rows: finalRows, deletedIds }, overlay) => {
            const validationError = finalRows.find((r) => !r.space_type || String(r.space_type).trim() === '');
            if (validationError) throw new Error('Each row needs a space/unit type.');
            const missingRent = finalRows.find((r) => !r.id && (r.market_rent_per_unit == null || r.market_rent_per_unit === ''));
            if (missingRent) throw new Error('New market profile rows require market rent.');

            const uniqueDeletedIds = Array.from(new Set(deletedIds || []));
            const deleteOps = uniqueDeletedIds.map((id) => api.del(`/properties/${propertyId}/market-profiles/${id}`));
            const upsertOps = finalRows.map((row) => {
                const payload = buildPayloadFromBulkRow(row, columns);
                const spaceType = String(payload.space_type || '').trim();
                delete payload.space_type;
                if (row.id) {
                    return api.put(`/properties/${propertyId}/market-profiles/${row.id}`, payload);
                }
                const createBody = { ...defaults, ...payload, space_type: spaceType };
                return api.post(`/properties/${propertyId}/market-profiles`, createBody);
            });

            const results = await Promise.allSettled([...deleteOps, ...upsertOps]);
            const firstFailure = summarizeBulkFailures(results);
            if (firstFailure) throw new Error(firstFailure);

            overlay.remove();
            toast('Market assumptions updated', 'success');
            propertyView({ id: propertyId });
        },
    });
}

function openExpenseWorkspace(propertyId, expenses, propertyType) {
    const isMultifamily = propertyType === 'multifamily' || propertyType === 'self_storage';
    const defaults = {
        category: '',
        description: null,
        comment: null,
        base_year_amount: 0,
        growth_rate_pct: 0.03,
        is_recoverable: !isMultifamily,
        is_pct_of_egi: false,
        pct_of_egi: null,
        is_gross_up_eligible: false,
        gross_up_vacancy_pct: null,
    };
    const rows = (expenses || []).map((e) => ({ ...defaults, ...e, id: e.id }));
    if (rows.length === 0) rows.push({ ...defaults, id: null });
    const columns = [
        { key: 'category', label: 'Category', type: 'text', required: true, default: '' },
        { key: 'description', label: 'Description', type: 'text', cloneOnAdd: false },
        { key: 'base_year_amount', label: 'Base Amount $', type: 'number', step: '0.01', align: 'right', default: 0 },
        { key: 'growth_rate_pct', label: 'Growth %', type: 'number', step: '0.005', asPercent: true, align: 'right', default: 0.03 },
        ...(!isMultifamily ? [{ key: 'is_recoverable', label: 'Recoverable', type: 'checkbox', default: true }] : []),
        { key: 'is_pct_of_egi', label: '% EGI', type: 'checkbox', default: false },
        { key: 'pct_of_egi', label: 'Pct of EGI %', type: 'number', step: '0.005', asPercent: true, align: 'right' },
        { key: 'comment', label: 'Comment', type: 'text', cloneOnAdd: false },
    ];
    showBulkTableEditorModal({
        title: 'Expense Workspace',
        columns,
        rows,
        intro: 'Edit all operating expenses in one pass. Add rows from the previous row pattern and paste multi-cell ranges.',
        extraTools: [
            {
                label: 'Set All Growth Rates',
                onClick: (workingRows, rerender, commitSnapshot) => {
                    const rate = prompt('Enter growth rate % to apply to all expenses (e.g. 3 for 3%):');
                    if (rate == null || rate.trim() === '') return;
                    const n = parseFloat(rate);
                    if (isNaN(n)) { toast('Invalid number', 'error'); return; }
                    commitSnapshot();
                    workingRows.forEach(r => { r.growth_rate_pct = n / 100; });
                    rerender();
                    toast(`Set all growth rates to ${n}%`, 'success');
                }
            }
        ],
        onSave: async ({ rows: finalRows, deletedIds }, overlay) => {
            const invalid = finalRows.find((r) => !r.category || String(r.category).trim() === '');
            if (invalid) throw new Error('Each expense row needs a category.');

            const uniqueDeletedIds = Array.from(new Set(deletedIds || []));
            const deleteOps = uniqueDeletedIds.map((id) => api.del(`/properties/${propertyId}/expenses/${id}`));
            const upsertOps = finalRows.map((row) => {
                const payload = buildPayloadFromBulkRow(row, columns);
                if (row.id) return api.put(`/properties/${propertyId}/expenses/${row.id}`, payload);
                return api.post(`/properties/${propertyId}/expenses`, { ...defaults, ...payload, category: String(payload.category || '').trim() });
            });
            const results = await Promise.allSettled([...deleteOps, ...upsertOps]);
            const firstFailure = summarizeBulkFailures(results);
            if (firstFailure) throw new Error(firstFailure);

            overlay.remove();
            toast('Expenses updated', 'success');
            propertyView({ id: propertyId });
        },
    });
}

function openOtherIncomeWorkspace(propertyId, items) {
    const defaults = {
        category: '',
        description: null,
        comment: null,
        base_year_amount: 0,
        growth_rate_pct: 0.03,
    };
    const rows = (items || []).map((i) => ({ ...defaults, ...i, id: i.id }));
    if (rows.length === 0) rows.push({ ...defaults, id: null });
    const columns = [
        { key: 'category', label: 'Category', type: 'text', required: true, default: '' },
        { key: 'description', label: 'Description', type: 'text', cloneOnAdd: false },
        { key: 'base_year_amount', label: 'Base Amount $', type: 'number', step: '0.01', align: 'right', default: 0 },
        { key: 'growth_rate_pct', label: 'Growth %', type: 'number', step: '0.005', asPercent: true, align: 'right', default: 0.03 },
        { key: 'comment', label: 'Comment', type: 'text', cloneOnAdd: false },
    ];
    showBulkTableEditorModal({
        title: 'Other Income Workspace',
        columns,
        rows,
        intro: 'Manage all custom revenue lines together with low-click bulk editing and paste support.',
        onSave: async ({ rows: finalRows, deletedIds }, overlay) => {
            const invalid = finalRows.find((r) => !r.category || String(r.category).trim() === '');
            if (invalid) throw new Error('Each revenue row needs a category.');

            const uniqueDeletedIds = Array.from(new Set(deletedIds || []));
            const deleteOps = uniqueDeletedIds.map((id) => api.del(`/properties/${propertyId}/other-income/${id}`));
            const upsertOps = finalRows.map((row) => {
                const payload = buildPayloadFromBulkRow(row, columns);
                if (row.id) return api.put(`/properties/${propertyId}/other-income/${row.id}`, payload);
                return api.post(`/properties/${propertyId}/other-income`, { ...defaults, ...payload, category: String(payload.category || '').trim() });
            });
            const results = await Promise.allSettled([...deleteOps, ...upsertOps]);
            const firstFailure = summarizeBulkFailures(results);
            if (firstFailure) throw new Error(firstFailure);

            overlay.remove();
            toast('Other income updated', 'success');
            propertyView({ id: propertyId });
        },
    });
}

function openUnitMarketQuickSetup(propertyId, property, marketProfiles) {
    const spaceTypes = [...new Set((property.suites || []).map(s => s.space_type))];
    if (spaceTypes.length === 0) {
        toast('Add at least one suite/unit type first', 'error');
        return;
    }
    const mlaByType = {};
    (marketProfiles || []).forEach(m => { mlaByType[m.space_type] = m; });

    const fields = [
        { key: 'apply_same_all', label: 'Apply same assumptions to all unit types', type: 'checkbox', default: false },
        { key: 'same_rent', label: 'Market Rent ($/Unit/mo, all types)', type: 'number', step: '0.01', half: true, visibleWhen: v => v.apply_same_all },
        { key: 'same_growth', label: 'Rent Growth (all types)', type: 'number', step: '0.005', default: 0.03, half: true, helpText: 'Enter percent', visibleWhen: v => v.apply_same_all },
        { key: 'same_vacancy', label: 'Vacancy % (all types)', type: 'number', step: '0.005', default: 0.05, half: true, helpText: 'Enter percent', visibleWhen: v => v.apply_same_all },
        { key: 'same_credit', label: 'Credit Loss % (all types)', type: 'number', step: '0.005', default: 0.01, half: true, helpText: 'Enter percent', visibleWhen: v => v.apply_same_all },
        { key: 'same_renewal', label: 'Renewal Prob (all types)', type: 'number', step: '0.05', default: 0.65, half: true, helpText: 'Used as turnover proxy', visibleWhen: v => v.apply_same_all },
        { key: 'same_new_concession', label: 'New Lease Concession (mo, all types)', type: 'number', step: '1', default: 0, half: true, visibleWhen: v => v.apply_same_all },
        { key: 'same_renewal_concession', label: 'Renewal Concession (mo, all types)', type: 'number', step: '1', default: 0, half: true, visibleWhen: v => v.apply_same_all },
        { key: 'same_concession_timing_mode', label: 'Concession Timing (all types)', type: 'select', options: CONCESSION_TIMING_OPTIONS, default: 'blended', half: true, visibleWhen: v => v.apply_same_all },
        {
            type: 'custom',
            key: '_same_concession_table',
            visibleWhen: v => v.apply_same_all && v.same_concession_timing_mode === 'timed',
            render: (container, vals, setValue) => {
                const yearKeys = [
                    { key: 'same_concession_year1_months', label: 'Year 1' },
                    { key: 'same_concession_year2_months', label: 'Year 2' },
                    { key: 'same_concession_year3_months', label: 'Year 3' },
                    { key: 'same_concession_year4_months', label: 'Year 4' },
                    { key: 'same_concession_year5_months', label: 'Year 5' },
                    { key: 'same_concession_stabilized_months', label: 'Year 6+' },
                ];
                container.className = 'concession-timing-table';
                container.innerHTML = `
                    <div class="form-label" style="margin-bottom:8px">Concession Schedule — all types (months free)</div>
                    <div class="concession-grid">
                        ${yearKeys.map(yk => `
                            <div class="concession-cell">
                                <label class="concession-cell-label">${yk.label}</label>
                                <input type="number" step="0.25" min="0" max="12" class="form-input concession-cell-input" data-ck="${yk.key}"
                                    value="${vals[yk.key] != null ? vals[yk.key] : ''}" placeholder="0">
                            </div>
                        `).join('')}
                    </div>`;
                yearKeys.forEach(yk => {
                    const inp = container.querySelector(`[data-ck="${yk.key}"]`);
                    setValue(yk.key, vals[yk.key] != null ? String(vals[yk.key]) : '');
                    inp.addEventListener('input', () => setValue(yk.key, inp.value));
                });
            },
        },
        { key: 'same_turnover', label: 'Turnover Cost ($/Unit, all types)', type: 'number', step: '0.01', default: 0, half: true, visibleWhen: v => v.apply_same_all },
        { key: 'same_comment', label: 'Comment / Source Note (all types)', type: 'textarea', visibleWhen: v => v.apply_same_all },
    ];

    spaceTypes.forEach((st, i) => {
        const mla = mlaByType[st];
        if (i > 0) fields.push({ type: 'section', label: '' });
        fields.push({ type: 'section', label: fmt.typeLabel(st) });
        fields.push({
            key: `rent_${st}`,
            label: 'Market Rent ($/Unit/mo)',
            type: 'number',
            step: '0.01',
            half: true,
            default: mla ? parseFloat(mla.market_rent_per_unit) : '',
            visibleWhen: v => !v.apply_same_all,
        });
        fields.push({
            key: `growth_${st}`,
            label: 'Rent Growth',
            type: 'number',
            step: '0.005',
            asPercent: true,
            half: true,
            default: mla ? parseFloat(mla.rent_growth_rate_pct) : 0.03,
            helpText: 'Enter percent',
            visibleWhen: v => !v.apply_same_all,
        });
        fields.push({
            key: `vacancy_${st}`,
            label: 'Vacancy %',
            type: 'number',
            step: '0.005',
            asPercent: true,
            half: true,
            default: mla ? parseFloat(mla.general_vacancy_pct) : 0.05,
            helpText: 'Enter percent',
            visibleWhen: v => !v.apply_same_all,
        });
        fields.push({
            key: `credit_${st}`,
            label: 'Credit Loss %',
            type: 'number',
            step: '0.005',
            asPercent: true,
            half: true,
            default: mla ? parseFloat(mla.credit_loss_pct) : 0.01,
            helpText: 'Enter percent',
            visibleWhen: v => !v.apply_same_all,
        });
        fields.push({
            key: `renewal_${st}`,
            label: 'Renewal Prob',
            type: 'number',
            step: '0.05',
            asPercent: true,
            half: true,
            default: mla ? parseFloat(mla.renewal_probability) : 0.65,
            helpText: 'Used as turnover proxy',
            visibleWhen: v => !v.apply_same_all,
        });
        fields.push({
            key: `turnover_${st}`,
            label: 'Turnover Cost ($/Unit)',
            type: 'number',
            step: '0.01',
            half: true,
            default: mla ? parseFloat(mla.new_tenant_ti_per_sf) : 0,
            visibleWhen: v => !v.apply_same_all,
        });
        fields.push({
            key: `new_concession_${st}`,
            label: 'New Lease Concession (months)',
            type: 'number',
            step: '1',
            half: true,
            default: mla ? parseFloat(mla.new_tenant_free_rent_months || 0) : 0,
            visibleWhen: v => !v.apply_same_all,
        });
        fields.push({
            key: `renewal_concession_${st}`,
            label: 'Renewal Concession (months)',
            type: 'number',
            step: '1',
            half: true,
            default: mla ? parseFloat(mla.renewal_free_rent_months || 0) : 0,
            visibleWhen: v => !v.apply_same_all,
        });
        fields.push({
            key: `timing_mode_${st}`,
            label: 'Concession Timing',
            type: 'select',
            options: CONCESSION_TIMING_OPTIONS,
            half: true,
            default: mla ? (mla.concession_timing_mode || 'blended') : 'blended',
            visibleWhen: v => !v.apply_same_all,
        });
        fields.push({
            key: `c_y1_${st}`,
            label: 'Year 1 Concession (months)',
            type: 'number',
            step: '0.25',
            half: true,
            default: mla && mla.concession_year1_months != null ? parseFloat(mla.concession_year1_months) : '',
            visibleWhen: v => !v.apply_same_all && v[`timing_mode_${st}`] === 'timed',
        });
        fields.push({
            key: `c_y2_${st}`,
            label: 'Year 2 Concession (months)',
            type: 'number',
            step: '0.25',
            half: true,
            default: mla && mla.concession_year2_months != null ? parseFloat(mla.concession_year2_months) : '',
            visibleWhen: v => !v.apply_same_all && v[`timing_mode_${st}`] === 'timed',
        });
        fields.push({
            key: `c_y3_${st}`,
            label: 'Year 3 Concession (months)',
            type: 'number',
            step: '0.25',
            half: true,
            default: mla && mla.concession_year3_months != null ? parseFloat(mla.concession_year3_months) : '',
            visibleWhen: v => !v.apply_same_all && v[`timing_mode_${st}`] === 'timed',
        });
        fields.push({
            key: `c_y4_${st}`,
            label: 'Year 4 Concession (months)',
            type: 'number',
            step: '0.25',
            half: true,
            default: mla && mla.concession_year4_months != null ? parseFloat(mla.concession_year4_months) : '',
            visibleWhen: v => !v.apply_same_all && v[`timing_mode_${st}`] === 'timed',
        });
        fields.push({
            key: `c_y5_${st}`,
            label: 'Year 5 Concession (months)',
            type: 'number',
            step: '0.25',
            half: true,
            default: mla && mla.concession_year5_months != null ? parseFloat(mla.concession_year5_months) : '',
            visibleWhen: v => !v.apply_same_all && v[`timing_mode_${st}`] === 'timed',
        });
        fields.push({
            key: `c_ys_${st}`,
            label: 'Year 6+ Concession (months)',
            type: 'number',
            step: '0.25',
            half: true,
            default: mla && mla.concession_stabilized_months != null ? parseFloat(mla.concession_stabilized_months) : '',
            visibleWhen: v => !v.apply_same_all && v[`timing_mode_${st}`] === 'timed',
        });
        fields.push({
            key: `comment_${st}`,
            label: 'Comment / Source Note',
            type: 'textarea',
            default: mla ? (mla.comment || '') : '',
            visibleWhen: v => !v.apply_same_all,
        });
    });

    showFormModal({
        title: 'Rent Roll Assumptions: Multifamily / Self-Storage',
        fields,
        wide: true,
        onSubmit: async (data, overlay) => {
            for (const st of spaceTypes) {
                const existing = mlaByType[st];
                const sharedMode = !!data.apply_same_all;
                const rent = sharedMode
                    ? ((data.same_rent != null && data.same_rent !== '') ? data.same_rent : existing?.market_rent_per_unit)
                    : data[`rent_${st}`];
                if (rent == null || rent === '') continue;
                const growth = sharedMode
                    ? (data.same_growth ?? parseFloat(existing?.rent_growth_rate_pct ?? 0.03))
                    : (data[`growth_${st}`] ?? parseFloat(existing?.rent_growth_rate_pct ?? 0.03));
                const vacancy = sharedMode
                    ? (data.same_vacancy ?? parseFloat(existing?.general_vacancy_pct ?? 0.05))
                    : (data[`vacancy_${st}`] ?? parseFloat(existing?.general_vacancy_pct ?? 0.05));
                const credit = sharedMode
                    ? (data.same_credit ?? parseFloat(existing?.credit_loss_pct ?? 0.01))
                    : (data[`credit_${st}`] ?? parseFloat(existing?.credit_loss_pct ?? 0.01));
                const renewal = sharedMode
                    ? (data.same_renewal ?? parseFloat(existing?.renewal_probability ?? 0.65))
                    : (data[`renewal_${st}`] ?? parseFloat(existing?.renewal_probability ?? 0.65));
                const turnover = sharedMode
                    ? (data.same_turnover ?? parseFloat(existing?.new_tenant_ti_per_sf ?? 0))
                    : (data[`turnover_${st}`] ?? parseFloat(existing?.new_tenant_ti_per_sf ?? 0));
                const newConcessionMonthsRaw = sharedMode
                    ? (data.same_new_concession ?? parseFloat(existing?.new_tenant_free_rent_months ?? 0))
                    : (data[`new_concession_${st}`] ?? parseFloat(existing?.new_tenant_free_rent_months ?? 0));
                const renewalConcessionMonthsRaw = sharedMode
                    ? (data.same_renewal_concession ?? parseFloat(existing?.renewal_free_rent_months ?? 0))
                    : (data[`renewal_concession_${st}`] ?? parseFloat(existing?.renewal_free_rent_months ?? 0));
                const newConcessionMonths = Math.max(0, Math.round(Number(newConcessionMonthsRaw || 0)));
                const renewalConcessionMonths = Math.max(0, Math.round(Number(renewalConcessionMonthsRaw || 0)));
                const concessionTimingMode = sharedMode
                    ? (data.same_concession_timing_mode || existing?.concession_timing_mode || 'blended')
                    : (data[`timing_mode_${st}`] || existing?.concession_timing_mode || 'blended');
                const concessionYear1Months = sharedMode
                    ? (data.same_concession_year1_months ?? existing?.concession_year1_months ?? null)
                    : (data[`c_y1_${st}`] ?? existing?.concession_year1_months ?? null);
                const concessionYear2Months = sharedMode
                    ? (data.same_concession_year2_months ?? existing?.concession_year2_months ?? null)
                    : (data[`c_y2_${st}`] ?? existing?.concession_year2_months ?? null);
                const concessionYear3Months = sharedMode
                    ? (data.same_concession_year3_months ?? existing?.concession_year3_months ?? null)
                    : (data[`c_y3_${st}`] ?? existing?.concession_year3_months ?? null);
                const concessionYear4Months = sharedMode
                    ? (data.same_concession_year4_months ?? existing?.concession_year4_months ?? null)
                    : (data[`c_y4_${st}`] ?? existing?.concession_year4_months ?? null);
                const concessionYear5Months = sharedMode
                    ? (data.same_concession_year5_months ?? existing?.concession_year5_months ?? null)
                    : (data[`c_y5_${st}`] ?? existing?.concession_year5_months ?? null);
                const concessionStabilizedMonths = sharedMode
                    ? (data.same_concession_stabilized_months ?? existing?.concession_stabilized_months ?? null)
                    : (data[`c_ys_${st}`] ?? existing?.concession_stabilized_months ?? null);
                const comment = sharedMode
                    ? (data.same_comment ?? existing?.comment ?? null)
                    : (data[`comment_${st}`] ?? existing?.comment ?? null);
                const body = {
                    market_rent_per_unit: rent,
                    rent_growth_rate_pct: growth,
                    general_vacancy_pct: vacancy,
                    credit_loss_pct: credit,
                    renewal_probability: renewal,
                    new_tenant_ti_per_sf: turnover,
                    new_tenant_free_rent_months: newConcessionMonths,
                    renewal_free_rent_months: renewalConcessionMonths,
                    concession_timing_mode: concessionTimingMode,
                    concession_year1_months: concessionYear1Months,
                    concession_year2_months: concessionYear2Months,
                    concession_year3_months: concessionYear3Months,
                    concession_year4_months: concessionYear4Months,
                    concession_year5_months: concessionYear5Months,
                    concession_stabilized_months: concessionStabilizedMonths,
                    comment,
                };
                if (existing) {
                    await api.put(`/properties/${propertyId}/market-profiles/${existing.id}`, body);
                } else {
                    await api.post(`/properties/${propertyId}/market-profiles`, {
                        space_type: st,
                        ...body,
                    });
                }
            }
            overlay.remove();
            toast('Rent roll assumptions updated', 'success');
            propertyView({ id: propertyId });
        }
    });
}

function openUnitInPlaceRentEditor(propertyId, allLeases) {
    const leases = (allLeases || []).filter(l => l && l.id);
    if (leases.length === 0) {
        toast('No leases available to edit', 'error');
        return;
    }

    const fields = [];
    leases.forEach((l, i) => {
        if (i > 0) fields.push({ type: 'section', label: '' });
        const suiteName = l.suite?.suite_name || 'Suite';
        const tenantName = l.tenant?.name || (l.tenant_id ? 'Leased' : 'Vacant');
        fields.push({ type: 'section', label: `${suiteName} — ${tenantName}` });
        fields.push({
            key: `rent_${l.id}`,
            label: 'Rent/Unit ($/mo)',
            type: 'number',
            step: '1',
            half: true,
            default: parseFloat(l.base_rent_per_unit),
        });
    });

    showFormModal({
        title: 'Edit In-Place Rent/Unit',
        fields,
        wide: true,
        smartPaste: true,
        onSubmit: async (data, overlay) => {
            const updates = leases
                .map((l) => {
                    const key = `rent_${l.id}`;
                    if (!(key in data)) return null;
                    const nextRent = data[key];
                    if (nextRent == null || nextRent === '') return null;
                    const current = parseFloat(l.base_rent_per_unit);
                    if (Math.abs(nextRent - current) < 1e-9) return null;
                    return { leaseId: l.id, base_rent_per_unit: nextRent };
                })
                .filter(Boolean);

            if (updates.length === 0) {
                overlay.remove();
                toast('No rent changes to save', 'info');
                return;
            }

            let failedCount = 0;
            let firstError = '';
            try {
                const result = await api.patch('/leases/bulk', {
                    atomic: false,
                    updates: updates.map((u) => ({
                        lease_id: u.leaseId,
                        fields: { base_rent_per_unit: u.base_rent_per_unit },
                    })),
                });
                failedCount = (result?.failed || []).length;
                if (failedCount > 0) {
                    const firstFailure = result.failed[0];
                    firstError = firstFailure?.detail || 'Unknown error';
                }
            } catch (err) {
                // Fallback for older backends without the bulk endpoint.
                const fallback = await Promise.allSettled(
                    updates.map((u) => api.put(`/leases/${u.leaseId}`, { base_rent_per_unit: u.base_rent_per_unit }))
                );
                const failed = fallback.filter(r => r.status === 'rejected');
                failedCount = failed.length;
                if (failedCount > 0) {
                    firstError = failed[0].reason?.message || err.message || 'Unknown error';
                }
            }

            if (failedCount > 0) {
                throw new Error(`Saved ${updates.length - failedCount}/${updates.length}. ${failedCount} failed (${firstError}).`);
            }

            overlay.remove();
            toast('In-place rents updated', 'success');
            propertyView({ id: propertyId });
        }
    });
}

function buildValuationFields(propertyType = '') {
    const isUnit = propertyType === 'multifamily' || propertyType === 'self_storage';
    const reservesLabel = isUnit ? 'Capital Reserves $/Unit/yr' : 'Capital Reserves $/SF/yr';
    const fields = [
    { key: 'name', label: 'Valuation Name', type: 'text', required: true },
    { key: 'description', label: 'Description', type: 'text' },
    { key: 'comment', label: 'Comment / Source Note', type: 'textarea' },
    {
        key: 'analysis_start_date_override',
        label: 'Analysis Start Date Override',
        type: 'date',
        half: true,
        helpText: 'Optional. Leave blank to use the property analysis start date.',
    },
    { key: 'discount_rate', label: 'Discount Rate', type: 'number', required: true, step: '0.0025', default: 0.08, half: true, helpText: 'Enter percent' },
    { key: 'exit_cap_rate', label: 'Exit Cap Rate', type: 'number', required: true, step: '0.0025', default: 0.065, half: true, helpText: 'Enter percent' },
    { key: 'exit_costs_pct', label: 'Exit Costs %', type: 'number', step: '0.005', default: 0.02, half: true, helpText: 'Enter percent' },
    {
        key: 'transfer_tax_preset',
        label: 'Transfer Tax Preset',
        type: 'select',
        default: 'none',
        half: true,
        options: [
            { value: 'none', label: 'None' },
            { value: 'custom_rate', label: 'Custom Flat Rate' },
            { value: 'la_city_ula', label: 'Los Angeles: City + ULA' },
            { value: 'san_francisco_transfer', label: 'San Francisco Transfer Tax' },
            { value: 'nyc_nys_commercial', label: 'NYC + NYS Commercial' },
            { value: 'philadelphia_realty_transfer', label: 'Philadelphia Realty Transfer' },
            { value: 'dc_deed_transfer_recordation', label: 'Washington, DC Deed Taxes' },
            { value: 'wa_state_reet', label: 'Washington State REET' },
        ],
    },
    {
        key: 'transfer_tax_custom_rate',
        label: 'Custom Transfer Tax %',
        type: 'number',
        step: '0.0025',
        half: true,
        helpText: 'Used when preset is Custom Flat Rate.',
        visibleWhen: v => v.transfer_tax_preset === 'custom_rate',
    },
    { key: 'capital_reserves_per_unit', label: reservesLabel, type: 'number', step: '0.05', default: 0.25, half: true },
    { key: 'exit_cap_applied_to_year', label: 'Exit Cap Applied to Year', type: 'number', step: '1', default: -1, half: true, helpText: '-1 = forward year (Hold + 1 NOI)' },
    { key: 'use_mid_year_convention', label: 'Use mid-year discounting', type: 'checkbox', default: false },
    ];
    if (!isUnit) {
        fields.push({ key: 'apply_stabilized_gross_up', label: 'Apply stabilized gross-up', type: 'checkbox', default: true });
        fields.push({
            key: 'stabilized_occupancy_pct',
            label: 'Stabilized Occupancy %',
            type: 'number',
            step: '0.005',
            default: 0.95,
            half: true,
            helpText: 'Optional global gross-up target. Leave blank to use each expense line target.',
            visibleWhen: v => v.apply_stabilized_gross_up,
        });
    }
    fields.push({ type: 'section', label: 'Financing', collapsible: true, defaultCollapsed: true });
    fields.push({ key: 'loan_amount', label: 'Loan Amount ($)', type: 'number', step: '1', half: true });
    fields.push({ key: 'interest_rate', label: 'Interest Rate', type: 'number', step: '0.0025', half: true, helpText: 'Enter percent' });
    fields.push({ key: 'amortization_months', label: 'Amortization (months)', type: 'number', step: '1', half: true });
    fields.push({ key: 'loan_term_months', label: 'Loan Term (months)', type: 'number', step: '1', half: true });
    fields.push({ key: 'io_period_months', label: 'Interest-Only Period (months)', type: 'number', step: '1', default: 0, half: true });
    return fields;
}
const VALUATION_FIELDS = buildValuationFields();


const RECOVERY_STRUCTURE_FIELDS = [
    { key: 'name', label: 'Name', type: 'text', required: true },
    { key: 'description', label: 'Description', type: 'text' },
    { key: 'comment', label: 'Comment / Source Note', type: 'textarea' },
    { key: 'default_recovery_type', label: 'Default Recovery Type', type: 'select', options: RECOVERY_TYPES, default: 'nnn', helpText: 'Used for expense categories not listed in items below' },
];

const RECOVERY_ITEM_FIELDS = [
    {
        key: 'expense_category',
        label: 'Expense Category',
        type: 'text',
        required: true,
        suggestions: STANDARD_EXPENSE_CATEGORIES,
        half: true,
        helpText: 'Use a standard category or enter your own custom category.',
    },
    { key: 'recovery_type', label: 'Recovery Type', type: 'select', required: true, options: RECOVERY_TYPES, half: true },
    { key: 'base_year_stop_amount', label: 'Base Year Stop ($)', type: 'number', step: '0.01', half: true, visibleWhen: v => v.recovery_type === 'base_year_stop' },
    { key: 'cap_per_sf_annual', label: 'Cap $/SF/yr', type: 'number', step: '0.01', half: true },
    { key: 'floor_per_sf_annual', label: 'Floor $/SF/yr', type: 'number', step: '0.01', half: true },
    { key: 'admin_fee_pct', label: 'Admin Fee %', type: 'number', step: '0.005', half: true, helpText: 'Enter percent, e.g. 15.00 = 15%' },
    { key: 'comment', label: 'Comment / Source Note', type: 'textarea' },
];

const CAPITAL_PROJECT_FIELDS = [
    { key: 'description', label: 'Description', type: 'text', required: true },
    { key: 'comment', label: 'Comment / Source Note', type: 'textarea' },
    { key: 'total_amount', label: 'Total Amount ($)', type: 'number', required: true, step: '1', half: true },
    { key: 'start_date', label: 'Start Date', type: 'date', required: true, half: true },
    { key: 'duration_months', label: 'Duration (months)', type: 'number', required: true, step: '1', half: true },
];

const RENT_STEP_FIELDS = [
    { key: 'effective_date', label: 'Effective Date', type: 'date', required: true, half: true },
    { key: 'rent_per_unit', label: 'Rent ($/SF/yr)', type: 'number', required: true, step: '0.01', half: true },
    { key: 'comment', label: 'Comment / Source Note', type: 'textarea' },
];

const FREE_RENT_FIELDS = [
    { key: 'start_date', label: 'Start Date', type: 'date', required: true, half: true },
    { key: 'end_date', label: 'End Date', type: 'date', required: true, half: true },
    { key: 'applies_to_base_rent', label: 'Applies to base rent', type: 'checkbox', default: true },
    { key: 'applies_to_recoveries', label: 'Applies to recoveries', type: 'checkbox', default: false },
    { key: 'comment', label: 'Comment / Source Note', type: 'textarea' },
];

const EXPENSE_RECOVERY_OVERRIDE_FIELDS = [
    {
        key: 'expense_category',
        label: 'Expense Category',
        type: 'text',
        required: true,
        suggestions: STANDARD_EXPENSE_CATEGORIES,
        helpText: 'Use a standard category or enter your own custom category.',
    },
    { key: 'recovery_type', label: 'Recovery Type', type: 'select', required: true, options: RECOVERY_TYPES },
    { key: 'base_year_stop_amount', label: 'Base Year Stop ($)', type: 'number', step: '0.01', half: true, visibleWhen: v => v.recovery_type === 'base_year_stop' },
    { key: 'cap_per_sf_annual', label: 'Cap $/SF/yr', type: 'number', step: '0.01', half: true },
    { key: 'floor_per_sf_annual', label: 'Floor $/SF/yr', type: 'number', step: '0.01', half: true },
    { key: 'admin_fee_pct', label: 'Admin Fee %', type: 'number', step: '0.005', half: true, helpText: 'Enter percent, e.g. 5.00 = 5%' },
    { key: 'comment', label: 'Comment / Source Note', type: 'textarea' },
];


// ─── Rent Schedule Builder ────────────────────────────────

async function showRentScheduleBuilder(leaseId, propertyId, areaUnit = 'sf') {
    const lease = await api.get(`/leases/${leaseId}`);
    const tenantName = lease.tenant ? lease.tenant.name : 'Lease';
    const baseRent = parseFloat(lease.base_rent_per_unit);
    const isUnit = areaUnit === 'unit';
    const rentUnitLabel = isUnit ? '$/Unit/mo' : '$/SF/yr';

    let overlay;

    async function render() {
        const fresh = await api.get(`/leases/${leaseId}`);
        const steps = [...fresh.rent_steps].sort((a, b) => a.effective_date.localeCompare(b.effective_date));

        // Build schedule table: base rent + all steps
        let schedule = [{ date: fresh.lease_start_date, rent: parseFloat(fresh.base_rent_per_unit), isBase: true }];
        steps.forEach(s => {
            schedule.push({ date: s.effective_date, rent: parseFloat(s.rent_per_unit), id: s.id });
        });

        const scheduleRows = schedule.map((row, i) => {
            const prevRent = i > 0 ? schedule[i - 1].rent : row.rent;
            const pctChange = i > 0 && prevRent > 0 ? ((row.rent - prevRent) / prevRent * 100).toFixed(2) + '%' : '—';
            return `<tr>
                <td>${fmt.dateFull(row.date)}</td>
                <td class="mono right">${fmt.perSf(row.rent)}</td>
                <td class="mono right">${pctChange}</td>
                <td class="col-actions">${row.isBase
                    ? '<span style="font-size:0.73rem;color:var(--text-tertiary)">Base</span>'
                    : `<button class="btn-icon danger" data-del-step="${row.id}" title="Remove">${icons.trash}</button>`
                }</td>
            </tr>`;
        }).join('');

        const content = `
            <div class="modal wide">
                <div class="modal-title">${tenantName} — Rent Schedule</div>
                <p style="font-size:0.87rem;color:var(--text-secondary);margin-bottom:16px">
                    Base rent: ${fmt.perSf(fresh.base_rent_per_unit)} starting ${fmt.dateFull(fresh.lease_start_date)}.
                    Add steps below to define a custom rent schedule.
                </p>
                <div class="data-table-wrap" style="margin-bottom:16px">
                    <table class="data-table" style="margin-bottom:0">
                        <thead><tr><th>Effective Date</th><th class="right">Rent ${rentUnitLabel}</th><th class="right">Change</th><th class="col-actions"></th></tr></thead>
                        <tbody>${scheduleRows}</tbody>
                    </table>
                </div>

                <div class="form-section" style="display:flex;justify-content:space-between;align-items:center">
                    <span>Add Rent Step</span>
                </div>
                <div class="form-row" style="margin-bottom:8px">
                    <div class="form-group">
                        <label class="form-label">Effective Date</label>
                        <input class="form-input" type="date" id="rsDate" />
                    </div>
                    <div class="form-group">
                        <label class="form-label">Rent ${rentUnitLabel}</label>
                        <input class="form-input" type="number" step="0.01" id="rsRent" placeholder="Enter amount" />
                    </div>
                </div>
                <div class="form-row" style="margin-bottom:12px">
                    <div class="form-group">
                        <label class="form-label">— or — % Increase from previous</label>
                        <input class="form-input" type="number" step="0.5" id="rsPct" placeholder="e.g. 3 for 3%" />
                        <div class="form-help">Enter a percentage; the rent amount will be calculated automatically</div>
                    </div>
                    <div class="form-group" style="display:flex;align-items:flex-end">
                        <button class="btn btn-primary btn-sm" id="addStepBtn" style="width:100%">${icons.plus} Add Step</button>
                    </div>
                </div>

                <div class="modal-actions">
                    <button class="btn btn-secondary" id="closeSchedule">Done</button>
                </div>
            </div>`;

        if (!overlay) {
            overlay = document.createElement('div');
            overlay.className = 'modal-overlay';
            document.body.appendChild(overlay);
        }
        overlay.innerHTML = content;

        // Close
        const closeBtn = overlay.querySelector('#closeSchedule');
        closeBtn.onclick = () => { overlay.remove(); if (propertyId) propertyView({ id: propertyId }); };
        overlay.addEventListener('click', (e) => { if (e.target === overlay) { overlay.remove(); if (propertyId) propertyView({ id: propertyId }); } }, { once: true });

        // Auto-calc rent from %
        const pctInput = overlay.querySelector('#rsPct');
        const rentInput = overlay.querySelector('#rsRent');
        pctInput.addEventListener('input', () => {
            const pct = parseFloat(pctInput.value);
            if (!isNaN(pct)) {
                // Find the last rent in schedule
                const lastRent = schedule[schedule.length - 1].rent;
                rentInput.value = (lastRent * (1 + pct / 100)).toFixed(2);
            }
        });
        rentInput.addEventListener('input', () => { pctInput.value = ''; });

        // Add step
        overlay.querySelector('#addStepBtn').onclick = async () => {
            const dateVal = overlay.querySelector('#rsDate').value;
            const rentVal = parseFloat(rentInput.value);
            if (!dateVal) { toast('Enter an effective date', 'error'); return; }
            if (isNaN(rentVal) || rentVal <= 0) { toast('Enter a valid rent amount', 'error'); return; }
            try {
                await api.post(`/leases/${leaseId}/rent-steps`, { effective_date: dateVal, rent_per_unit: rentVal });
                toast('Rent step added', 'success');
                render();
            } catch (err) {
                toast('Error: ' + err.message, 'error');
            }
        };

        // Delete steps
        overlay.querySelectorAll('[data-del-step]').forEach(btn => {
            btn.onclick = async () => {
                await api.del(`/leases/${leaseId}/rent-steps/${btn.dataset.delStep}`);
                toast('Rent step removed', 'success');
                render();
            };
        });
    }

    render();
}


// ─── Lease Detail Modal (sub-resources) ──────────────────

async function showLeaseDetailModal(leaseId, propertyId, marketProfiles, propertyType = '', areaUnit = 'sf') {
    const lease = await api.get(`/leases/${leaseId}`);
    const tenantName = lease.tenant ? lease.tenant.name : 'Vacant';

    // Find the matching market profile for this lease's suite
    const mps = marketProfiles || [];
    const suiteSpaceType = lease.suite ? lease.suite.space_type : null;
    const matchedMarket = suiteSpaceType ? mps.find(m => m.space_type === suiteSpaceType) : null;

    function renderSubTable(items, columns, emptyMsg) {
        if (!items || items.length === 0) {
            return `<div style="color:var(--text-tertiary);font-size:0.87rem;padding:12px 0">${emptyMsg}</div>`;
        }
        return `<table class="data-table" style="margin-bottom:0">
            <thead><tr>${columns.map(c => `<th${c.right ? ' class="right"' : ''}>${c.label}</th>`).join('')}<th></th></tr></thead>
            <tbody>${items.map(item => `<tr>
                ${columns.map(c => `<td${c.right ? ' class="right mono"' : ''}>${c.fmt ? c.fmt(item[c.key]) : item[c.key]}</td>`).join('')}
                <td><button class="btn-icon danger" data-delete-sub="${item.id}" data-sub-type="${c_type}" title="Remove">${icons.trash}</button></td>
            </tr>`).join('')}</tbody>
        </table>`;
    }

    // Build the modal content dynamically (so we can re-render on add/delete)
    let overlay;

    const isMultifamilyLease = propertyType === 'multifamily' || propertyType === 'self_storage';
    const rentUnitLabel = areaUnit === 'unit' ? '$/Unit/mo' : '$/SF/yr';

    async function render() {
        const fresh = await api.get(`/leases/${leaseId}`);
        const content = `
            <div class="modal wide" style="width:700px">
                <div class="modal-title">${tenantName} — Lease Details</div>
                <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:20px">
                    <div><div class="info-item-label">Lease Type</div><div class="info-item-value">${fmt.typeLabel(fresh.lease_type)}</div></div>
                    <div><div class="info-item-label">Term</div><div class="info-item-value">${fmt.date(fresh.lease_start_date)} – ${fmt.date(fresh.lease_end_date)}</div></div>
                    <div><div class="info-item-label">Base Rent</div><div class="info-item-value" style="color:var(--accent)">${fmt.perSf(fresh.base_rent_per_unit)}</div></div>
                    ${isMultifamilyLease ? '' : `<div><div class="info-item-label">Escalation</div><div class="info-item-value">${fmt.typeLabel(fresh.escalation_type)}${fresh.escalation_pct_annual ? ' (' + fmt.pct(fresh.escalation_pct_annual) + ')' : ''}</div></div>`}
                    ${isMultifamilyLease ? '' : `<div><div class="info-item-label">Recovery</div><div class="info-item-value">${fmt.typeLabel(fresh.recovery_type)}</div></div>`}
                </div>

                <!-- Effective Assumptions (resolved values the engine will use) -->
                ${matchedMarket ? `
                <div class="effective-assumptions">
                    <div class="effective-assumptions-title">Effective Assumptions (resolved)</div>
                    <div class="effective-assumptions-grid">
                        <div>
                            <span class="effective-label">${isMultifamilyLease ? 'Retention Rate' : 'Renewal Probability'}</span>
                            <span class="effective-value">${fresh.renewal_probability != null ? fmt.pct(fresh.renewal_probability) + ' <em>(lease override)</em>' : fmt.pct(matchedMarket.renewal_probability) + ' <em>(market default)</em>'}</span>
                        </div>
                        ${isMultifamilyLease ? '' : `<div>
                            <span class="effective-label">Renewal Rent Adjustment</span>
                            <span class="effective-value">${fresh.renewal_rent_spread_pct != null ? fmt.pct(fresh.renewal_rent_spread_pct) + ' <em>(lease override)</em>' : fmt.pct(matchedMarket.renewal_rent_adjustment_pct) + ' <em>(market default)</em>'}</span>
                        </div>`}
                        <div>
                            <span class="effective-label">Market Rent</span>
                            <span class="effective-value">${fmt.perSf(matchedMarket.market_rent_per_unit)}</span>
                        </div>
                        ${isMultifamilyLease ? '' : `<div>
                            <span class="effective-label">Recovery Type</span>
                            <span class="effective-value">${fresh.recovery_structure_id ? 'From template' : fmt.typeLabel(fresh.recovery_type)}${fresh.expense_recovery_overrides.length > 0 ? ' + ' + fresh.expense_recovery_overrides.length + ' override(s)' : ''}</span>
                        </div>`}
                    </div>
                </div>` : ''}

                <!-- Rent Schedule -->
                <div class="form-section" style="display:flex;justify-content:space-between;align-items:center">
                    <span>Rent Schedule (${fresh.rent_steps.length} step${fresh.rent_steps.length !== 1 ? 's' : ''})</span>
                    <button class="btn btn-primary btn-sm" id="openRentSchedule">${icons.edit} Edit Schedule</button>
                </div>
                <div style="margin-bottom:16px">
                    ${fresh.rent_steps.length === 0
                        ? '<div style="color:var(--text-tertiary);font-size:0.87rem;padding:4px 0">No custom rent steps. Rent escalates per the escalation type above.</div>'
                        : `<div class="data-table-wrap"><table class="data-table" style="margin-bottom:0">
                            <thead><tr><th>Effective Date</th><th class="right">Rent ${rentUnitLabel}</th></tr></thead>
                            <tbody>${fresh.rent_steps.sort((a, b) => a.effective_date.localeCompare(b.effective_date)).map(rs => `<tr>
                                <td>${fmt.dateFull(rs.effective_date)}</td>
                                <td class="mono right">${fmt.perSf(rs.rent_per_unit)}</td>
                            </tr>`).join('')}</tbody>
                        </table></div>`
                    }
                </div>

                <!-- Free Rent Periods -->
                <div class="form-section" style="display:flex;justify-content:space-between;align-items:center">
                    <span>Free Rent Periods (${fresh.free_rent_periods.length})</span>
                    <button class="btn btn-secondary btn-sm" id="addFreeRent">${icons.plus} Add</button>
                </div>
                <div class="data-table-wrap" style="margin-bottom:16px" id="freeRentTable">
                    ${fresh.free_rent_periods.length === 0
                        ? '<div style="color:var(--text-tertiary);font-size:0.87rem;padding:12px 0">No free rent periods.</div>'
                        : `<table class="data-table" style="margin-bottom:0">
                            <thead><tr><th>Start</th><th>End</th><th>Base Rent</th><th>Recoveries</th><th></th></tr></thead>
                            <tbody>${fresh.free_rent_periods.sort((a, b) => a.start_date.localeCompare(b.start_date)).map(fr => `<tr>
                                <td>${fmt.dateFull(fr.start_date)}</td>
                                <td>${fmt.dateFull(fr.end_date)}</td>
                                <td>${fr.applies_to_base_rent ? 'Yes' : 'No'}</td>
                                <td>${fr.applies_to_recoveries ? 'Yes' : 'No'}</td>
                                <td><button class="btn-icon danger" data-del-frp="${fr.id}" title="Remove">${icons.trash}</button></td>
                            </tr>`).join('')}</tbody>
                        </table>`
                    }
                </div>

                <!-- Expense Recovery Overrides -->
                ${isMultifamilyLease ? '' : `<div class="form-section" style="display:flex;justify-content:space-between;align-items:center">
                    <span>Expense Recovery Overrides (${fresh.expense_recovery_overrides.length})</span>
                    <button class="btn btn-secondary btn-sm" id="addRecoveryOverride">${icons.plus} Add</button>
                </div>
                <div class="data-table-wrap" style="margin-bottom:8px" id="recoveryTable">
                    ${fresh.expense_recovery_overrides.length === 0
                        ? '<div style="color:var(--text-tertiary);font-size:0.87rem;padding:12px 0">No per-category overrides. Using lease-level recovery type for all expenses.</div>'
                        : `<table class="data-table" style="margin-bottom:0">
                            <thead><tr><th>Category</th><th>Recovery</th><th class="right">Cap/SF</th><th class="right">Floor/SF</th><th class="right">Admin %</th><th></th></tr></thead>
                            <tbody>${fresh.expense_recovery_overrides.map(ero => `<tr>
                                <td class="tenant-name">${fmt.typeLabel(ero.expense_category)}</td>
                                <td>${fmt.typeLabel(ero.recovery_type)}</td>
                                <td class="mono right">${ero.cap_per_sf_annual ? fmt.perSf(ero.cap_per_sf_annual) : '—'}</td>
                                <td class="mono right">${ero.floor_per_sf_annual ? fmt.perSf(ero.floor_per_sf_annual) : '—'}</td>
                                <td class="mono right">${ero.admin_fee_pct ? fmt.pct(ero.admin_fee_pct) : '—'}</td>
                                <td><button class="btn-icon danger" data-del-ero="${ero.id}" title="Remove">${icons.trash}</button></td>
                            </tr>`).join('')}</tbody>
                        </table>`
                    }
                </div>`}

                <div class="modal-actions">
                    <button class="btn btn-secondary" id="closeDetail">Close</button>
                </div>
            </div>`;

        if (!overlay) {
            overlay = document.createElement('div');
            overlay.className = 'modal-overlay';
            document.body.appendChild(overlay);
        }
        overlay.innerHTML = content;

        // Close handlers
        overlay.querySelector('#closeDetail').onclick = () => { overlay.remove(); if (propertyId) propertyView({ id: propertyId }); };
        overlay.addEventListener('click', (e) => { if (e.target === overlay) { overlay.remove(); if (propertyId) propertyView({ id: propertyId }); } }, { once: true });

        // Open Rent Schedule Builder
        overlay.querySelector('#openRentSchedule').onclick = () => {
            overlay.remove();
            overlay = null;
            showRentScheduleBuilder(leaseId, propertyId, areaUnit);
        };

        // Add Free Rent Period
        overlay.querySelector('#addFreeRent').onclick = () => {
            showFormModal({
                title: 'Add Free Rent Period',
                fields: FREE_RENT_FIELDS,
                onSubmit: async (data, formOverlay) => {
                    await api.post(`/leases/${leaseId}/free-rent-periods`, data);
                    formOverlay.remove();
                    toast('Free rent period added', 'success');
                    render();
                }
            });
        };

        // Delete Free Rent Period
        overlay.querySelectorAll('[data-del-frp]').forEach(btn => {
            btn.onclick = async (e) => {
                e.stopPropagation();
                const frpId = btn.dataset.delFrp;
                await api.del(`/leases/${leaseId}/free-rent-periods/${frpId}`);
                toast('Free rent period removed', 'success');
                render();
            };
        });

        // Add Expense Recovery Override
        overlay.querySelector('#addRecoveryOverride').onclick = () => {
            showFormModal({
                title: 'Add Expense Recovery Override',
                fields: EXPENSE_RECOVERY_OVERRIDE_FIELDS,
                onSubmit: async (data, formOverlay) => {
                    await api.post(`/leases/${leaseId}/expense-recoveries`, data);
                    formOverlay.remove();
                    toast('Recovery override added', 'success');
                    render();
                }
            });
        };

        // Delete Expense Recovery Override
        overlay.querySelectorAll('[data-del-ero]').forEach(btn => {
            btn.onclick = async (e) => {
                e.stopPropagation();
                const eroId = btn.dataset.delEro;
                await api.del(`/leases/${leaseId}/expense-recoveries/${eroId}`);
                toast('Recovery override removed', 'success');
                render();
            };
        });
    }

    render();
}


// ═══════════════════════════════════════════════════════════════
// VIEWS
// ═══════════════════════════════════════════════════════════════

// ─── Dashboard ────────────────────────────────────────────────

async function dashboardView() {
    setBreadcrumb([{ label: 'Dashboard' }]);

    let properties;
    try {
        properties = await api.get('/properties');
    } catch {
        $app().innerHTML = `
            <div class="empty-state">
                <h3>Cannot connect to API</h3>
                <p>Make sure the server is running: <code style="color:var(--accent)">uvicorn src.main:app --reload</code></p>
                <p style="margin-top:8px">Then seed example data: <code style="color:var(--accent)">python seed_data.py</code></p>
            </div>`;
        return;
    }

    // Fetch valuations for each property in parallel
    const valuationsByProp = {};
    await Promise.all(properties.map(async (p) => {
        try {
            valuationsByProp[p.id] = await api.get(`/properties/${p.id}/valuations`);
        } catch { valuationsByProp[p.id] = []; }
    }));

    // Calculate portfolio KPIs
    const totalSF = properties.reduce((s, p) => s + parseFloat(p.total_area), 0);
    let totalNPV = 0;
    let completedCount = 0;
    let totalIRR = 0;

    properties.forEach(p => {
        const vals = valuationsByProp[p.id] || [];
        const completed = vals.filter(v => v.status === 'completed');
        completed.forEach(v => {
            if (v.result_npv) { totalNPV += parseFloat(v.result_npv); }
            if (v.result_irr) { totalIRR += parseFloat(v.result_irr); completedCount++; }
        });
    });

    const avgIRR = completedCount > 0 ? totalIRR / completedCount : 0;

    const html = `
        <div class="page-header">
            <h1 class="page-title">Portfolio Dashboard</h1>
            <p class="page-subtitle">Commercial real estate valuation overview</p>
        </div>

        <div class="kpi-row">
            <div class="kpi-card">
                <div class="kpi-label">Properties</div>
                <div class="kpi-value">${properties.length}</div>
                <div class="kpi-subtext">Active assets</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Total Area</div>
                <div class="kpi-value">${fmt.num(totalSF)}</div>
                <div class="kpi-subtext">Square feet</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Portfolio Value</div>
                <div class="kpi-value accent">${fmt.currency(totalNPV)}</div>
                <div class="kpi-subtext">Net present value</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Avg. IRR</div>
                <div class="kpi-value green">${completedCount > 0 ? fmt.pct(avgIRR) : '—'}</div>
                <div class="kpi-subtext">${completedCount} valuation${completedCount !== 1 ? 's' : ''} completed</div>
            </div>
        </div>

        <div class="section-header">
            <h2 class="section-title">Properties</h2>
            <button class="btn btn-primary btn-sm" id="newPropertyBtn">${icons.plus} New Property</button>
        </div>

        <div class="property-grid">
            ${properties.length === 0 ? `
                <div class="empty-state" style="grid-column: 1/-1">
                    <h3>No properties yet</h3>
                    <p>Click "New Property" above or run <code style="color:var(--accent)">python seed_data.py</code> to load example data</p>
                </div>
            ` : properties.map(p => {
                const vals = valuationsByProp[p.id] || [];
                const lastCompleted = vals.find(v => v.status === 'completed');
                const npv = lastCompleted ? fmt.currency(lastCompleted.result_npv) : '—';
                const capRate = lastCompleted && lastCompleted.result_going_in_cap_rate
                    ? fmt.pct(lastCompleted.result_going_in_cap_rate) : '—';
                const location = [p.city, p.state].filter(Boolean).join(', ') || '—';

                return `
                    <div class="property-card" onclick="location.hash='#/property/${p.id}'">
                        <div class="property-card-header">
                            <div>
                                <div class="property-card-name">${p.name}</div>
                                <div class="property-card-location">${location}</div>
                            </div>
                            <div style="display:flex;align-items:flex-start;gap:6px">
                                <span class="property-type-badge badge-${p.property_type}">${fmt.typeLabel(p.property_type)}</span>
                                <div class="card-actions">
                                    <button class="btn-icon" data-edit-property="${p.id}" title="Edit">${icons.edit}</button>
                                    <button class="btn-icon danger" data-delete-property="${p.id}" title="Delete">${icons.trash}</button>
                                </div>
                            </div>
                        </div>
                        <div class="property-card-stats">
                            <div>
                                <div class="property-stat-label">Area</div>
                                <div class="property-stat-value">${fmt.sf(p.total_area, p.area_unit)}</div>
                            </div>
                            <div>
                                <div class="property-stat-label">Analysis</div>
                                <div class="property-stat-value">${Math.round(p.analysis_period_months / 12)} yr</div>
                            </div>
                            <div>
                                <div class="property-stat-label">NPV</div>
                                <div class="property-stat-value" style="color:var(--accent)">${npv}</div>
                            </div>
                            <div>
                                <div class="property-stat-label">Cap Rate</div>
                                <div class="property-stat-value">${capRate}</div>
                            </div>
                        </div>
                    </div>`;
            }).join('')}
        </div>`;

    $app().innerHTML = html;

    // New Property
    document.getElementById('newPropertyBtn').addEventListener('click', () => {
        showFormModal({
            title: 'New Property',
            fields: PROPERTY_FIELDS,
            onSubmit: async (data, overlay) => {
                await api.post('/properties', data);
                overlay.remove();
                toast('Property created', 'success');
                dashboardView();
            }
        });
    });

    // Edit Property (from card)
    document.querySelectorAll('[data-edit-property]').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const pid = btn.dataset.editProperty;
            const prop = properties.find(p => p.id === pid);
            showFormModal({
                title: 'Edit Property',
                fields: PROPERTY_FIELDS,
                initialValues: prop,
                onSubmit: async (data, overlay) => {
                    await api.put(`/properties/${pid}`, data);
                    overlay.remove();
                    toast('Property updated', 'success');
                    dashboardView();
                }
            });
        });
    });

    // Delete Property (from card)
    document.querySelectorAll('[data-delete-property]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const pid = btn.dataset.deleteProperty;
            const prop = properties.find(p => p.id === pid);
            showDeleteConfirm(prop.name, async () => {
                await api.del(`/properties/${pid}`);
                toast('Property deleted', 'success');
                dashboardView();
            });
        });
    });
}


// ─── Property Detail ──────────────────────────────────────────

async function propertyView({ id }) {
    // Load everything in parallel
    const [property, expenses, otherIncomeItems, marketProfiles, valuations, recoveryStructures, capitalProjects] = await Promise.all([
        api.get(`/properties/${id}`),
        api.get(`/properties/${id}/expenses`),
        api.get(`/properties/${id}/other-income`).catch(() => []),
        api.get(`/properties/${id}/market-profiles`),
        api.get(`/properties/${id}/valuations`),
        api.get(`/properties/${id}/recovery-structures`).catch(() => []),
        api.get(`/properties/${id}/capital-projects`).catch(() => []),
    ]);

    // Load leases for each suite in parallel
    const leasesBySuite = {};
    await Promise.all(property.suites.map(async (suite) => {
        try {
            leasesBySuite[suite.id] = await api.get(`/suites/${suite.id}/leases`);
        } catch { leasesBySuite[suite.id] = []; }
    }));

    const location = [property.address_line1, property.city, property.state, property.zip_code].filter(Boolean).join(', ');
    const simplifyUnitAssumptions = property.property_type === 'multifamily' || property.property_type === 'self_storage';
    const totalArea = parseFloat(property.total_area);
    const occupiedArea = property.suites.reduce((sum, s) => {
        const hasLease = (leasesBySuite[s.id] || []).some(l => l.lease_type !== 'market');
        return sum + (hasLease ? parseFloat(s.area) : 0);
    }, 0);
    const occupancyPct = totalArea > 0 ? occupiedArea / totalArea : 0;

    setBreadcrumb([
        { label: 'Dashboard', href: '#/dashboard' },
        { label: property.name }
    ]);

    const allLeases = property.suites.flatMap(s =>
        (leasesBySuite[s.id] || []).map(l => ({ ...l, suite: s }))
    );
    const suiteAreaById = {};
    (property.suites || []).forEach(s => { suiteAreaById[s.id] = parseFloat(s.area || 0); });
    const completedValuations = [...valuations]
        .filter(v => v.status === 'completed')
        .sort((a, b) => new Date(b.updated_at || b.created_at || 0) - new Date(a.updated_at || a.created_at || 0));

    $app().innerHTML = `
        <div class="property-header">
            <div class="property-header-left">
                <h1 class="property-header-title">${property.name}</h1>
                <div class="property-header-address">${location || 'No address specified'}</div>
                <div class="property-header-badges">
                    <span class="property-type-badge badge-${property.property_type}">${fmt.typeLabel(property.property_type)}</span>
                    <span class="status-badge" style="background:var(--blue-bg);color:var(--accent)">${fmt.sf(property.total_area, property.area_unit)}</span>
                    ${property.year_built ? `<span class="status-badge" style="background:var(--bg-secondary);color:var(--text-secondary)">Built ${property.year_built}</span>` : ''}
                </div>
            </div>
            <div class="property-header-actions">
                <button class="btn btn-secondary btn-sm" id="editPropertyBtn">${icons.edit} Edit Property</button>
                <button class="btn btn-danger btn-sm" id="deletePropertyBtn">${icons.trash} Delete</button>
            </div>
        </div>

        <div class="kpi-row" style="margin-bottom:24px">
            <div class="kpi-card">
                <div class="kpi-label">Total Area</div>
                <div class="kpi-value">${fmt.sf(totalArea, property.area_unit)}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Suites</div>
                <div class="kpi-value">${property.suites.length}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Occupancy</div>
                <div class="kpi-value ${occupancyPct >= 0.9 ? 'green' : ''}">${fmt.pct(occupancyPct, 1)}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Analysis Period</div>
                <div class="kpi-value">${Math.round(property.analysis_period_months / 12)} Years</div>
                <div class="kpi-subtext">From ${fmt.date(property.analysis_start_date)}</div>
            </div>
        </div>

        <div class="tab-bar" id="tabBar">
            <button class="tab-item active" data-tab="rent-roll">Rent Roll</button>
            <button class="tab-item" data-tab="operating-budget">Operating Budget</button>
            ${simplifyUnitAssumptions ? '' : '<button class="tab-item" data-tab="market">Market Profiles</button>'}
            <button class="tab-item" data-tab="capital">Capital Projects</button>
            ${simplifyUnitAssumptions ? '' : '<button class="tab-item" data-tab="recovery-audit">Tenant Recovery Audit</button>'}
            <button class="tab-item" data-tab="valuations">Valuations</button>
            ${simplifyUnitAssumptions ? '' : '<button class="tab-item tab-item--subtle" data-tab="recovery">Recovery Structures</button>'}
        </div>

        <div class="tab-content active" id="tab-rent-roll">
            ${renderRentRollTab(property, allLeases, marketProfiles)}
        </div>
        <div class="tab-content" id="tab-operating-budget">
            ${renderOperatingBudgetTab(expenses, otherIncomeItems, totalArea, property.area_unit, property.property_type)}
        </div>
        ${simplifyUnitAssumptions ? '' : `<div class="tab-content" id="tab-market">
            ${renderMarketTab(marketProfiles, property)}
        </div>`}
        <div class="tab-content" id="tab-capital">
            ${renderCapitalProjectsTab(capitalProjects, id)}
        </div>
        ${simplifyUnitAssumptions ? '' : `<div class="tab-content" id="tab-recovery">
            ${renderRecoveryStructuresTab(recoveryStructures, id)}
        </div>
        <div class="tab-content" id="tab-recovery-audit">
            ${renderRecoveryAuditTab(completedValuations)}
        </div>`}
        <div class="tab-content" id="tab-valuations">
            ${renderValuationsTab(valuations, id)}
        </div>`;

    // Tab switching
    document.getElementById('tabBar').addEventListener('click', (e) => {
        const tab = e.target.closest('.tab-item');
        if (!tab) return;
        document.querySelectorAll('.tab-item').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        const content = document.getElementById('tab-' + tab.dataset.tab);
        if (content) content.classList.add('active');
    });

    // Recovery Audit tab interactions
    const auditValuationSel = document.getElementById('recoveryAuditValuationSelect');
    const auditTenantSel = document.getElementById('recoveryAuditTenantSelect');
    const auditSummaryEl = document.getElementById('recoveryAuditSummary');
    const auditTableEl = document.getElementById('recoveryAuditTable');
    const openAuditValuationBtn = document.getElementById('openAuditValuationBtn');
    let auditRows = [];

    function renderAuditRows(rows, tenantFilter) {
        const all = Array.isArray(rows) ? rows : [];
        const filtered = (tenantFilter && tenantFilter !== '__all__')
            ? all.filter(r => (r.tenant_name || 'Vacant/Spec') === tenantFilter)
            : all;
        const propertyArea = parseFloat(property.total_area);
        const mgPoolAnnualByKey = {};
        filtered.forEach((r) => {
            if (r.recovery_type !== 'modified_gross') return;
            const key = `${r.year}|${r.period_start}|${r.suite_id}|${r.lease_id}`;
            mgPoolAnnualByKey[key] = (mgPoolAnnualByKey[key] || 0) + parseFloat(r.annual_expense_after_gross_up || 0);
        });
        const totalWeighted = filtered.reduce((sum, r) => sum + parseFloat(r.weighted_monthly_recovery || 0), 0);
        if (auditSummaryEl) {
            auditSummaryEl.textContent = `${filtered.length} row${filtered.length === 1 ? '' : 's'} • Weighted recovery total ${fmt.currencyExact(totalWeighted)}`;
        }
        if (!auditTableEl) return;
        if (filtered.length === 0) {
            auditTableEl.innerHTML = '<div class="empty-state"><h3>No audit rows for this tenant</h3><p>Choose another tenant or valuation.</p></div>';
            return;
        }

        const impl = (r) => {
            if (r.recovery_type === 'nnn') return 'NNN: grossed expense × pro rata share';
            if (r.recovery_type === 'base_year_stop') {
                return `Base-year stop: max(0, grossed expense − stop ${r.base_year_stop_amount != null ? fmt.currencyExact(r.base_year_stop_amount) : '$0'}) × pro rata`;
            }
            if (r.recovery_type === 'modified_gross') {
                return `Modified gross: pooled modified-gross expenses use stop/SF ${r.expense_stop_per_sf != null ? fmt.perSf(r.expense_stop_per_sf, property.area_unit) : '$0'}; excess allocated by category share`;
            }
            if (r.recovery_type === 'full_service_gross' || r.recovery_type === 'none') return 'No recovery';
            return fmt.typeLabel(r.recovery_type);
        };

        const body = filtered.map((r) => `<tr>
            <td>${r.year}</td>
            <td>${fmt.date(r.period_start)}</td>
            <td>${r.suite_name || r.suite_id}</td>
            <td>${r.tenant_name || 'Vacant/Spec'}</td>
            <td class="mono right">${fmt.num(suiteAreaById[r.suite_id])}</td>
            <td>${fmt.typeLabel(r.expense_category)}</td>
            <td>${fmt.typeLabel(r.recovery_type)}</td>
            <td>${impl(r)}</td>
            <td class="mono right">${(() => {
                const area = parseFloat(property.total_area);
                if (!Number.isFinite(area) || area <= 0) return '—';
                return fmt.perSf(parseFloat(r.annual_expense_before_gross_up || 0) / area, property.area_unit);
            })()}</td>
            <td class="mono right">${(() => {
                const area = parseFloat(property.total_area);
                if (!Number.isFinite(area) || area <= 0) return '—';
                return fmt.perSf(parseFloat(r.annual_expense_after_gross_up || 0) / area, property.area_unit);
            })()}</td>
            <td class="mono right">${(() => {
                if (r.recovery_type !== 'modified_gross') return '—';
                if (!Number.isFinite(propertyArea) || propertyArea <= 0) return '—';
                const key = `${r.year}|${r.period_start}|${r.suite_id}|${r.lease_id}`;
                const poolAnnual = mgPoolAnnualByKey[key] || 0;
                return fmt.perSf(poolAnnual / propertyArea, property.area_unit);
            })()}</td>
            <td class="mono right">${(() => {
                if (r.recovery_type !== 'modified_gross') return '—';
                if (!Number.isFinite(propertyArea) || propertyArea <= 0) return '—';
                const stop = parseFloat(r.expense_stop_per_sf || 0);
                const key = `${r.year}|${r.period_start}|${r.suite_id}|${r.lease_id}`;
                const poolAnnual = mgPoolAnnualByKey[key] || 0;
                const poolPerSf = poolAnnual / propertyArea;
                const excess = Math.max(0, poolPerSf - stop);
                return fmt.perSf(excess, property.area_unit);
            })()}</td>
            <td class="mono right">${(() => {
                if (r.recovery_type !== 'modified_gross') return '—';
                const key = `${r.year}|${r.period_start}|${r.suite_id}|${r.lease_id}`;
                const poolAnnual = mgPoolAnnualByKey[key] || 0;
                if (!Number.isFinite(poolAnnual) || poolAnnual <= 0) return '—';
                const catAnnual = parseFloat(r.annual_expense_after_gross_up || 0);
                return fmt.pct(catAnnual / poolAnnual);
            })()}</td>
            <td class="mono right">${fmt.currencyExact(r.base_year_stop_amount)}</td>
            <td class="mono right">${r.expense_stop_per_sf != null ? fmt.perSf(r.expense_stop_per_sf, property.area_unit) : '—'}</td>
            <td class="mono right">${r.cap_per_sf_annual != null ? fmt.perSf(r.cap_per_sf_annual, property.area_unit) : '—'}</td>
            <td class="mono right">${r.floor_per_sf_annual != null ? fmt.perSf(r.floor_per_sf_annual, property.area_unit) : '—'}</td>
            <td class="mono right">${r.admin_fee_pct != null ? fmt.pct(r.admin_fee_pct) : '—'}</td>
            <td class="mono right">${fmt.pct(r.pro_rata_share_pct)}</td>
            <td class="mono right">${fmt.currencyExact(r.annual_recovery_before_proration)}</td>
            <td class="mono right">${fmt.pct(r.proration_factor)}</td>
            <td>${r.is_recovery_free_rent_abatement ? '<span class="negative">Yes</span>' : 'No'}</td>
            <td class="mono right"><strong>${fmt.currencyExact(r.weighted_monthly_recovery)}</strong></td>
        </tr>`).join('');
        auditTableEl.innerHTML = `
            <div class="data-table-wrap">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Year</th>
                            <th>Month</th>
                            <th>Suite</th>
                            <th>Tenant</th>
                            <th class="right">Tenant SF</th>
                            <th>Expense</th>
                            <th>Recovery Type</th>
                            <th>Implementation</th>
                            <th class="right">Actual Exp/SF (Pre GU)</th>
                            <th class="right">Actual Exp/SF (Post GU)</th>
                            <th class="right">Pooled Exp/SF</th>
                            <th class="right">Excess Over Stop/SF</th>
                            <th class="right">Category Share %</th>
                            <th class="right">Base Stop $</th>
                            <th class="right">Stop/SF</th>
                            <th class="right">Cap/SF</th>
                            <th class="right">Floor/SF</th>
                            <th class="right">Admin %</th>
                            <th class="right">Pro Rata</th>
                            <th class="right">Annual Recovery</th>
                            <th class="right">Proration</th>
                            <th>FR Abated</th>
                            <th class="right">Weighted Monthly</th>
                        </tr>
                    </thead>
                    <tbody>${body}</tbody>
                </table>
            </div>`;
    }

    async function loadRecoveryAudit() {
        if (!auditValuationSel || !auditTenantSel || !auditTableEl) return;
        const vid = auditValuationSel.value;
        if (!vid) {
            auditRows = [];
            auditTenantSel.innerHTML = '<option value="__all__">All Tenants</option>';
            renderAuditRows([], '__all__');
            return;
        }
        auditTableEl.innerHTML = '<div class="empty-state"><h3>Loading audit…</h3></div>';
        try {
            auditRows = await api.get(`/valuations/${vid}/reports/recovery-audit`);
        } catch (err) {
            auditRows = [];
            auditTableEl.innerHTML = `<div class="empty-state"><h3>Could not load recovery audit</h3><p>${err.message}</p></div>`;
            return;
        }
        const tenantNames = [...new Set(auditRows.map(r => r.tenant_name || 'Vacant/Spec'))].sort((a, b) => a.localeCompare(b));
        auditTenantSel.innerHTML = [
            '<option value="__all__">All Tenants</option>',
            ...tenantNames.map(name => `<option value="${name.replace(/"/g, '&quot;')}">${name}</option>`),
        ].join('');
        renderAuditRows(auditRows, '__all__');
    }

    if (auditValuationSel && auditTenantSel) {
        auditValuationSel.addEventListener('change', () => {
            if (openAuditValuationBtn) openAuditValuationBtn.setAttribute('data-valuation-id', auditValuationSel.value || '');
            loadRecoveryAudit();
        });
        auditTenantSel.addEventListener('change', () => renderAuditRows(auditRows, auditTenantSel.value));
        if (openAuditValuationBtn) {
            openAuditValuationBtn.addEventListener('click', () => {
                const vid = openAuditValuationBtn.getAttribute('data-valuation-id');
                if (vid) location.hash = `#/valuation/${vid}`;
            });
        }
        const pendingValuationId = sessionStorage.getItem('opendcf_recovery_audit_valuation_id');
        if (pendingValuationId && [...auditValuationSel.options].some(o => o.value === pendingValuationId)) {
            auditValuationSel.value = pendingValuationId;
        }
        loadRecoveryAudit();
        sessionStorage.removeItem('opendcf_recovery_audit_valuation_id');
    }

    const pendingTab = sessionStorage.getItem('opendcf_property_tab');
    if (pendingTab) {
        const tabBtn = document.querySelector(`#tabBar .tab-item[data-tab="${pendingTab}"]`);
        if (tabBtn) tabBtn.click();
        sessionStorage.removeItem('opendcf_property_tab');
    }

    // Run valuation button
    document.querySelectorAll('[data-run-valuation]').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const vid = btn.dataset.runValuation;
            btn.textContent = 'Running...';
            btn.disabled = true;
            try {
                await api.post(`/valuations/${vid}/run`);
                toast('Valuation completed successfully', 'success');
                propertyView({ id });
            } catch (err) {
                toast('Valuation failed: ' + err.message, 'error');
                btn.textContent = 'Run';
                btn.disabled = false;
            }
        });
    });

    // New valuation button
    const newValBtn = document.getElementById('newValuationBtn');
    if (newValBtn) {
        newValBtn.addEventListener('click', () => showNewValuationModal(id, marketProfiles, property.property_type));
    }

    // Edit Property
    document.getElementById('editPropertyBtn').addEventListener('click', () => {
        showFormModal({
            title: 'Edit Property',
            fields: PROPERTY_FIELDS,
            initialValues: property,
            onSubmit: async (data, overlay) => {
                await api.put(`/properties/${id}`, data);
                overlay.remove();
                toast('Property updated', 'success');
                propertyView({ id });
            }
        });
    });

    // Delete Property
    document.getElementById('deletePropertyBtn').addEventListener('click', () => {
        showDeleteConfirm(property.name, async () => {
            await api.del(`/properties/${id}`);
            toast('Property deleted', 'success');
            location.hash = '#/dashboard';
        });
    });

    // Edit Market Rents (unit-type properties only — inline in rent roll)
    document.querySelectorAll('#editMktRentsBtn, #editMktRentsHdrBtn').forEach(btn => {
        btn.addEventListener('click', () => openMarketAssumptionWorkspace(id, property, marketProfiles));
    });

    const editRentUnitBtn = document.getElementById('editRentUnitBtn');
    if (editRentUnitBtn) {
        editRentUnitBtn.addEventListener('click', () => openUnitInPlaceRentEditor(id, allLeases));
    }

    const bulkMarketBtn = document.getElementById('bulkMarketBtn');
    if (bulkMarketBtn) {
        bulkMarketBtn.addEventListener('click', () => openMarketAssumptionWorkspace(id, property, marketProfiles));
    }

    // Quick market setup in Market tab for unit-type properties
    const quickUnitMarketBtn = document.getElementById('quickUnitMarketBtn');
    if (quickUnitMarketBtn) {
        quickUnitMarketBtn.addEventListener('click', () => openUnitMarketQuickSetup(id, property, marketProfiles));
    }

    // ── Multifamily: unified unit type add/edit ──
    const newUnitTypeBtn = document.getElementById('newUnitTypeBtn');
    if (newUnitTypeBtn) {
        newUnitTypeBtn.addEventListener('click', () => {
            showFormModal({
                title: 'Add Unit Type',
                fields: buildUnitTypeFields(property.area_unit),
                onSubmit: async (data, overlay) => {
                    // Create the suite
                    const suiteData = {
                        suite_name: data.suite_name,
                        space_type: data.space_type,
                        area: data.area,
                        is_available: true,
                    };
                    const suite = await api.post(`/properties/${id}/suites`, suiteData);
                    // Create a lease if not vacant
                    if (!data.is_vacant && data.base_rent_per_unit) {
                        const leaseData = {
                            lease_type: 'in_place',
                            base_rent_per_unit: data.base_rent_per_unit,
                            rent_payment_frequency: 'monthly',
                            lease_start_date: data.lease_start_date,
                            lease_end_date: data.lease_end_date,
                            escalation_type: 'flat',
                            recovery_type: 'none',
                        };
                        // Optionally create tenant from resident name
                        if (data.resident_name && data.resident_name.trim()) {
                            const tenant = await api.post(`/properties/${id}/tenants`, { name: data.resident_name.trim() });
                            leaseData.tenant_id = tenant.id;
                        }
                        await api.post(`/suites/${suite.id}/leases`, leaseData);
                    }
                    overlay.remove();
                    toast('Unit type added', 'success');
                    propertyView({ id });
                }
            });
        });
    }

    // Edit Unit Type (unified suite + lease edit for multifamily)
    document.querySelectorAll('[data-edit-unit-type]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const sid = btn.dataset.editUnitType;
            const suite = property.suites.find(s => s.id === sid);
            const lease = allLeases.find(l => l.suite.id === sid);
            // Build initial values from suite + lease
            const initialValues = {
                suite_name: suite.suite_name,
                space_type: suite.space_type,
                area: suite.area,
                is_vacant: !lease,
                resident_name: lease && lease.tenant ? lease.tenant.name : '',
                base_rent_per_unit: lease ? lease.base_rent_per_unit : '',
                lease_start_date: lease ? lease.lease_start_date : '',
                lease_end_date: lease ? lease.lease_end_date : '',
            };
            showFormModal({
                title: `Edit — ${suite.suite_name}`,
                fields: buildUnitTypeFields(property.area_unit),
                initialValues,
                onSubmit: async (data, overlay) => {
                    // Update suite
                    await api.put(`/properties/${id}/suites/${sid}`, {
                        suite_name: data.suite_name,
                        space_type: data.space_type,
                        area: data.area,
                        is_available: true,
                    });
                    if (data.is_vacant) {
                        // Delete existing lease if marking vacant
                        if (lease) {
                            await api.del(`/leases/${lease.id}`);
                        }
                    } else if (lease) {
                        // Update existing lease
                        const leaseUpdate = {
                            base_rent_per_unit: data.base_rent_per_unit,
                            lease_start_date: data.lease_start_date,
                            lease_end_date: data.lease_end_date,
                        };
                        // Handle resident name change
                        if (data.resident_name && data.resident_name.trim()) {
                            if (!lease.tenant || lease.tenant.name !== data.resident_name.trim()) {
                                const tenant = await api.post(`/properties/${id}/tenants`, { name: data.resident_name.trim() });
                                leaseUpdate.tenant_id = tenant.id;
                            }
                        } else if (lease.tenant) {
                            leaseUpdate.tenant_id = null;
                        }
                        await api.put(`/leases/${lease.id}`, leaseUpdate);
                    } else {
                        // Create new lease for previously vacant suite
                        const leaseData = {
                            lease_type: 'in_place',
                            base_rent_per_unit: data.base_rent_per_unit,
                            rent_payment_frequency: 'monthly',
                            lease_start_date: data.lease_start_date,
                            lease_end_date: data.lease_end_date,
                            escalation_type: 'flat',
                            recovery_type: 'none',
                        };
                        if (data.resident_name && data.resident_name.trim()) {
                            const tenant = await api.post(`/properties/${id}/tenants`, { name: data.resident_name.trim() });
                            leaseData.tenant_id = tenant.id;
                        }
                        await api.post(`/suites/${sid}/leases`, leaseData);
                    }
                    overlay.remove();
                    toast('Unit type updated', 'success');
                    propertyView({ id });
                }
            });
        });
    });

    // New Suite (commercial only — hidden for multifamily)
    const newSuiteBtn = document.getElementById('newSuiteBtn');
    if (newSuiteBtn) {
        newSuiteBtn.addEventListener('click', () => {
            showFormModal({
                title: 'New Suite',
                fields: buildSuiteFields(marketProfiles, property.area_unit, simplifyUnitAssumptions),
                onSubmit: async (data, overlay) => {
                    if (!data.market_leasing_profile_id) delete data.market_leasing_profile_id;
                    await api.post(`/properties/${id}/suites`, data);
                    overlay.remove();
                    toast('Suite created', 'success');
                    propertyView({ id });
                }
            });
        });
    }

    // Edit Suite (commercial only)
    document.querySelectorAll('[data-edit-suite]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const sid = btn.dataset.editSuite;
            const suite = property.suites.find(s => s.id === sid);
            showFormModal({
                title: 'Edit Suite',
                fields: buildSuiteFields(marketProfiles, property.area_unit, simplifyUnitAssumptions),
                initialValues: suite,
                onSubmit: async (data, overlay) => {
                    await api.put(`/properties/${id}/suites/${sid}`, data);
                    overlay.remove();
                    toast('Suite updated', 'success');
                    propertyView({ id });
                }
            });
        });
    });

    // Delete Suite
    document.querySelectorAll('[data-delete-suite]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const sid = btn.dataset.deleteSuite;
            const suite = property.suites.find(s => s.id === sid);
            showDeleteConfirm(suite.suite_name, async () => {
                await api.del(`/properties/${id}/suites/${sid}`);
                toast('Suite deleted', 'success');
                propertyView({ id });
            });
        });
    });

    // New Lease
    // Helper: open lease form with inline tenant creation
    function openLeaseForm(title, initialValues, onSubmit, opts = {}) {
        (async () => {
            let tenants = [];
            try { tenants = await api.get(`/properties/${id}/tenants`); } catch {}
            const onNewTenant = true;
            const leaseFields = buildLeaseFields(
                property.suites,
                tenants,
                onNewTenant,
                recoveryStructures,
                opts.includeSuite !== false,
                property.area_unit,
                property.property_type
            );
            const formOverlay = showFormModal({
                title,
                fields: leaseFields,
                wide: true,
                initialValues,
                onSubmit
            });
            // Wire up inline "+ New Tenant" button (inside the form)
            setTimeout(() => {
                const inlineBtn = formOverlay.querySelector('#inlineNewTenant');
                if (inlineBtn) {
                    inlineBtn.addEventListener('click', (e) => {
                        e.preventDefault();
                        showFormModal({
                            title: 'New Tenant',
                            fields: buildTenantFields(property.property_type),
                            onSubmit: async (data, tenantOverlay) => {
                                const newTenant = await api.post(`/properties/${id}/tenants`, data);
                                tenantOverlay.remove();
                                toast('Tenant created', 'success');
                                // Refresh the tenant dropdown in the lease form
                                const select = formOverlay.querySelector('#form_tenant_id');
                                if (select) {
                                    const opt = document.createElement('option');
                                    opt.value = newTenant.id;
                                    opt.textContent = newTenant.name;
                                    opt.selected = true;
                                    select.appendChild(opt);
                                }
                            }
                        });
                    });
                }
            }, 0);
        })();
    }

    const newLeaseBtn = document.getElementById('newLeaseBtn');
    if (newLeaseBtn) {
        newLeaseBtn.addEventListener('click', () => {
            openLeaseForm('New Lease', null, async (data, overlay) => {
                const suiteId = data.suite_id;
                delete data.suite_id;
                if (!data.tenant_id) delete data.tenant_id;
                await api.post(`/suites/${suiteId}/leases`, data);
                overlay.remove();
                toast('Lease created', 'success');
                propertyView({ id });
            });
        });
    }

    // Rent Schedule (direct button)
    document.querySelectorAll('[data-schedule-lease]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            showRentScheduleBuilder(btn.dataset.scheduleLease, id, property.area_unit);
        });
    });

    // Lease Detail (free rent, recoveries)
    document.querySelectorAll('[data-detail-lease]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            showLeaseDetailModal(btn.dataset.detailLease, id, marketProfiles, property.property_type, property.area_unit);
        });
    });

    // Edit Lease
    document.querySelectorAll('[data-edit-lease]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const lid = btn.dataset.editLease;
            const lease = allLeases.find(l => l.id === lid);
            openLeaseForm('Edit Lease', lease, async (data, overlay) => {
                if (data.tenant_id === '') data.tenant_id = null;
                await api.put(`/leases/${lid}`, data);
                overlay.remove();
                toast('Lease updated', 'success');
                propertyView({ id });
            }, { includeSuite: false });
        });
    });

    // Delete Lease
    document.querySelectorAll('[data-delete-lease]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const lid = btn.dataset.deleteLease;
            const lease = allLeases.find(l => l.id === lid);
            const lbl = lease.tenant ? lease.tenant.name + ' lease' : 'this lease';
            showDeleteConfirm(lbl, async () => {
                await api.del(`/leases/${lid}`);
                toast('Lease deleted', 'success');
                propertyView({ id });
            });
        });
    });

    // New Expense
    const expenseFields = buildExpenseFields(property.property_type);
    const newExpenseBtn = document.getElementById('newExpenseBtn');
    if (newExpenseBtn) {
        newExpenseBtn.addEventListener('click', () => {
            showFormModal({
                title: 'New Expense',
                fields: expenseFields,
                onSubmit: async (data, overlay) => {
                    await api.post(`/properties/${id}/expenses`, data);
                    overlay.remove();
                    toast('Expense created', 'success');
                    propertyView({ id });
                }
            });
        });
    }

    const bulkExpenseBtn = document.getElementById('bulkExpenseBtn');
    if (bulkExpenseBtn) {
        bulkExpenseBtn.addEventListener('click', () => openExpenseWorkspace(id, expenses, property.property_type));
    }

    // Edit Expense
    document.querySelectorAll('[data-edit-expense]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const eid = btn.dataset.editExpense;
            const exp = expenses.find(x => x.id === eid);
            showFormModal({
                title: 'Edit Expense',
                fields: expenseFields,
                initialValues: exp,
                onSubmit: async (data, overlay) => {
                    await api.put(`/properties/${id}/expenses/${eid}`, data);
                    overlay.remove();
                    toast('Expense updated', 'success');
                    propertyView({ id });
                }
            });
        });
    });

    // Delete Expense
    document.querySelectorAll('[data-delete-expense]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const eid = btn.dataset.deleteExpense;
            const exp = expenses.find(x => x.id === eid);
            showDeleteConfirm(exp.category + ' expense', async () => {
                await api.del(`/properties/${id}/expenses/${eid}`);
                toast('Expense deleted', 'success');
                propertyView({ id });
            });
        });
    });

    // New Other Income
    const newOtherIncomeBtn = document.getElementById('newOtherIncomeBtn');
    if (newOtherIncomeBtn) {
        newOtherIncomeBtn.addEventListener('click', () => {
            showFormModal({
                title: 'New Other Income',
                fields: OTHER_INCOME_FIELDS,
                onSubmit: async (data, overlay) => {
                    await api.post(`/properties/${id}/other-income`, data);
                    overlay.remove();
                    toast('Other income item created', 'success');
                    propertyView({ id });
                }
            });
        });
    }

    const bulkOtherIncomeBtn = document.getElementById('bulkOtherIncomeBtn');
    if (bulkOtherIncomeBtn) {
        bulkOtherIncomeBtn.addEventListener('click', () => openOtherIncomeWorkspace(id, otherIncomeItems));
    }

    // Edit Other Income
    document.querySelectorAll('[data-edit-other-income]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const itemId = btn.dataset.editOtherIncome;
            const item = otherIncomeItems.find(x => x.id === itemId);
            showFormModal({
                title: 'Edit Other Income',
                fields: OTHER_INCOME_FIELDS,
                initialValues: item,
                onSubmit: async (data, overlay) => {
                    await api.put(`/properties/${id}/other-income/${itemId}`, data);
                    overlay.remove();
                    toast('Other income item updated', 'success');
                    propertyView({ id });
                }
            });
        });
    });

    // Delete Other Income
    document.querySelectorAll('[data-delete-other-income]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const itemId = btn.dataset.deleteOtherIncome;
            const item = otherIncomeItems.find(x => x.id === itemId);
            showDeleteConfirm((item?.category || 'other income') + ' item', async () => {
                await api.del(`/properties/${id}/other-income/${itemId}`);
                toast('Other income item deleted', 'success');
                propertyView({ id });
            });
        });
    });

    // New Market Profile
    const newMarketBtn = document.getElementById('newMarketBtn');
    if (newMarketBtn) {
        newMarketBtn.addEventListener('click', () => {
            showFormModal({
                title: 'New Market Profile',
                fields: buildMarketFields(property.area_unit, true),
                wide: true,
                onSubmit: async (data, overlay) => {
                    await api.post(`/properties/${id}/market-profiles`, data);
                    overlay.remove();
                    toast('Market profile created', 'success');
                    propertyView({ id });
                }
            });
        });
    }

    // Edit Market Profile
    document.querySelectorAll('[data-edit-market]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const mid = btn.dataset.editMarket;
            const mp = marketProfiles.find(x => x.id === mid);
            showFormModal({
                title: 'Edit Market Profile',
                fields: buildMarketFields(property.area_unit, false),
                wide: true,
                initialValues: mp,
                onSubmit: async (data, overlay) => {
                    await api.put(`/properties/${id}/market-profiles/${mid}`, data);
                    overlay.remove();
                    toast('Market profile updated', 'success');
                    propertyView({ id });
                }
            });
        });
    });

    // Delete Market Profile
    document.querySelectorAll('[data-delete-market]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const mid = btn.dataset.deleteMarket;
            const mp = marketProfiles.find(x => x.id === mid);
            showDeleteConfirm(mp.space_type + ' market profile', async () => {
                await api.del(`/properties/${id}/market-profiles/${mid}`);
                toast('Market profile deleted', 'success');
                propertyView({ id });
            });
        });
    });

    // Edit Valuation
    document.querySelectorAll('[data-edit-valuation]').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const vid = btn.dataset.editValuation;
            const val = valuations.find(v => v.id === vid);
            showFormModal({
                title: 'Edit Valuation',
                fields: buildValuationFields(property.property_type),
                wide: true,
                initialValues: val,
                onSubmit: async (data, overlay) => {
                    await api.put(`/valuations/${vid}`, data);
                    overlay.remove();
                    toast('Valuation updated', 'success');
                    propertyView({ id });
                }
            });
        });
    });

    // Delete Valuation
    document.querySelectorAll('[data-delete-valuation]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const vid = btn.dataset.deleteValuation;
            const val = valuations.find(v => v.id === vid);
            showDeleteConfirm(val.name, async () => {
                await api.del(`/valuations/${vid}`);
                toast('Valuation deleted', 'success');
                propertyView({ id });
            });
        });
    });

    // --- Capital Project CRUD ---
    const newCapexBtn = document.getElementById('newCapexBtn');
    if (newCapexBtn) {
        newCapexBtn.addEventListener('click', () => {
            showFormModal({
                title: 'New Capital Project',
                fields: CAPITAL_PROJECT_FIELDS,
                onSubmit: async (data, overlay) => {
                    await api.post(`/properties/${id}/capital-projects`, data);
                    overlay.remove();
                    toast('Capital project created', 'success');
                    propertyView({ id });
                }
            });
        });
    }

    document.querySelectorAll('[data-edit-capex]').forEach(btn => {
        btn.addEventListener('click', () => {
            const cpId = btn.dataset.editCapex;
            const cp = capitalProjects.find(c => c.id === cpId);
            showFormModal({
                title: 'Edit Capital Project',
                fields: CAPITAL_PROJECT_FIELDS,
                initialValues: cp,
                onSubmit: async (data, overlay) => {
                    await api.put(`/properties/${id}/capital-projects/${cpId}`, data);
                    overlay.remove();
                    toast('Capital project updated', 'success');
                    propertyView({ id });
                }
            });
        });
    });

    document.querySelectorAll('[data-delete-capex]').forEach(btn => {
        btn.addEventListener('click', () => {
            const cpId = btn.dataset.deleteCapex;
            const cp = capitalProjects.find(c => c.id === cpId);
            showDeleteConfirm(cp.description, async () => {
                await api.del(`/properties/${id}/capital-projects/${cpId}`);
                toast('Capital project deleted', 'success');
                propertyView({ id });
            });
        });
    });

    // --- Recovery Structure CRUD ---
    const newRsBtn = document.getElementById('newRecoveryStructureBtn');
    if (newRsBtn) {
        newRsBtn.addEventListener('click', () => {
            showFormModal({
                title: 'New Recovery Structure',
                fields: RECOVERY_STRUCTURE_FIELDS,
                onSubmit: async (data, overlay) => {
                    await api.post(`/properties/${id}/recovery-structures`, data);
                    overlay.remove();
                    toast('Recovery structure created', 'success');
                    propertyView({ id });
                }
            });
        });
    }

    document.querySelectorAll('[data-edit-rs]').forEach(btn => {
        btn.addEventListener('click', () => {
            const rsId = btn.dataset.editRs;
            const rs = recoveryStructures.find(r => r.id === rsId);
            showFormModal({
                title: 'Edit Recovery Structure',
                fields: RECOVERY_STRUCTURE_FIELDS,
                initialValues: rs,
                onSubmit: async (data, overlay) => {
                    await api.put(`/properties/${id}/recovery-structures/${rsId}`, data);
                    overlay.remove();
                    toast('Recovery structure updated', 'success');
                    propertyView({ id });
                }
            });
        });
    });

    document.querySelectorAll('[data-delete-rs]').forEach(btn => {
        btn.addEventListener('click', () => {
            const rsId = btn.dataset.deleteRs;
            const rs = recoveryStructures.find(r => r.id === rsId);
            showDeleteConfirm(rs.name, async () => {
                await api.del(`/properties/${id}/recovery-structures/${rsId}`);
                toast('Recovery structure deleted', 'success');
                propertyView({ id });
            });
        });
    });

    document.querySelectorAll('[data-add-rs-item]').forEach(btn => {
        btn.addEventListener('click', () => {
            const rsId = btn.dataset.addRsItem;
            showFormModal({
                title: 'Add Category Override',
                fields: RECOVERY_ITEM_FIELDS,
                onSubmit: async (data, overlay) => {
                    await api.post(`/properties/${id}/recovery-structures/${rsId}/items`, data);
                    overlay.remove();
                    toast('Category override added', 'success');
                    propertyView({ id });
                }
            });
        });
    });

    document.querySelectorAll('[data-del-rs-item]').forEach(btn => {
        btn.addEventListener('click', async () => {
            const itemId = btn.dataset.delRsItem;
            const rsId = btn.dataset.rsId;
            await api.del(`/properties/${id}/recovery-structures/${rsId}/items/${itemId}`);
            toast('Category override removed', 'success');
            propertyView({ id });
        });
    });
}


function renderRentRollTab(property, allLeases, marketProfiles) {
    const mlaMap = {};
    (marketProfiles || []).forEach(m => { mlaMap[m.id] = m; });
    const mlaByType = {};
    (marketProfiles || []).forEach(m => { mlaByType[m.space_type] = m; });
    const au = property.area_unit;
    const isUnit = au === 'unit';
    const simplifyUnitAssumptions = property.property_type === 'multifamily' || property.property_type === 'self_storage';
    const areaLabel = isUnit ? 'Units' : 'Area (SF)';
    const rentLabel = isUnit ? 'Rent/Unit' : 'Rent/SF';

    // ── Multifamily: unified one-row-per-unit-type layout ──
    if (simplifyUnitAssumptions) {
        const rows = property.suites.map(suite => {
            const leases = allLeases.filter(l => l.suite.id === suite.id);
            const mla = mlaByType[suite.space_type];
            const lease = leases[0]; // one lease per unit type
            const isVacant = !lease;
            const displayName = lease && lease.tenant ? lease.tenant.name : '';
            const annualRent = lease ? parseFloat(lease.base_rent_per_unit) * parseFloat(suite.area) : 0;

            const actions = `<div class="card-actions" style="display:inline-flex;gap:4px;align-items:center">
                <button class="btn-icon" data-edit-unit-type="${suite.id}" title="Edit unit type">${icons.edit}</button>
                <button class="btn-icon danger" data-delete-suite="${suite.id}" title="Delete unit type">${icons.trash}</button>
            </div>`;

            return `<tr>
                <td>${actions}</td>
                <td>${suite.suite_name}</td>
                <td>${suite.space_type}</td>
                <td class="mono right">${fmt.num(suite.area)}</td>
                <td class="${isVacant ? 'vacant' : 'tenant-name'}">${isVacant ? 'Vacant' : displayName || 'Occupied'}</td>
                <td>${lease ? fmt.date(lease.lease_start_date) : '—'}</td>
                <td>${lease ? fmt.date(lease.lease_end_date) : '—'}</td>
                <td class="mono right" style="color:var(--accent)">${mla ? fmt.perSf(mla.market_rent_per_unit, au) : '<span style="color:var(--text-tertiary)">—</span>'}</td>
                <td class="mono right">${lease ? fmt.perSf(lease.base_rent_per_unit, au) : '—'}</td>
                <td class="mono right">${mla ? fmt.pct(mla.rent_growth_rate_pct) : '<span style="color:var(--text-tertiary)">—</span>'}</td>
                <td class="mono right">${annualRent > 0 ? fmt.currencyExact(annualRent) : '—'}</td>
            </tr>`;
        }).join('');

        const totalRent = allLeases.reduce((s, l) => s + parseFloat(l.base_rent_per_unit) * parseFloat(l.suite.area), 0);
        const colCount = 11;

        return `
            <div class="section-header">
                <h3 class="section-title">Rent Roll</h3>
                <div class="btn-group">
                    <button class="btn btn-primary btn-sm" id="newUnitTypeBtn">${icons.plus} Add Unit Type</button>
                </div>
            </div>
            <div class="page-subtitle" style="margin-bottom:10px">Each row is a unit type. Market assumptions are managed inline via the <button class="btn-icon" id="editMktRentsBtn" title="Assumption workspace" style="vertical-align:middle">${icons.edit}</button> buttons below.</div>
            <div class="data-table-wrap">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th></th>
                            <th>Unit Type</th>
                            <th>Key</th>
                            <th class="right">${areaLabel}</th>
                            <th>Resident</th>
                            <th>Start</th>
                            <th>End</th>
                            <th class="right">Mkt Rent <button class="btn-icon" id="editMktRentsHdrBtn" title="Edit market rents" style="vertical-align:middle">${icons.edit}</button></th>
                            <th class="right">${rentLabel} <button class="btn-icon" id="editRentUnitBtn" title="Edit in-place rents" style="vertical-align:middle">${icons.edit}</button></th>
                            <th class="right">Growth</th>
                            <th class="right">Annual Rent</th>
                        </tr>
                    </thead>
                    <tbody>${rows || `<tr><td colspan="${colCount}" style="text-align:center;color:var(--text-tertiary);padding:32px">No unit types yet. Click "Add Unit Type" to get started.</td></tr>`}</tbody>
                    ${totalRent > 0 ? `<tfoot>
                        <tr>
                            <td colspan="${colCount - 1}" style="text-align:right">Total Annual Rent</td>
                            <td style="text-align:right">${fmt.currencyExact(totalRent)}</td>
                        </tr>
                    </tfoot>` : ''}
                </table>
            </div>`;
    }

    // ── Commercial: original multi-row layout ──
    const rows = property.suites.map(suite => {
        const leases = allLeases.filter(l => l.suite.id === suite.id);
        const suiteActions = `<div class="card-actions" style="display:inline-flex">
            <button class="btn-icon" data-edit-suite="${suite.id}" title="Edit suite">${icons.edit}</button>
            <button class="btn-icon danger" data-delete-suite="${suite.id}" title="Delete suite">${icons.trash}</button>
        </div>`;

        if (leases.length === 0) {
            return `<tr>
                <td>${suite.suite_name} ${suiteActions}</td>
                <td>${suite.space_type}</td>
                <td class="mono right">${fmt.num(suite.area)}</td>
                <td class="vacant">Vacant</td>
                <td>—</td>
                <td>—</td>
                <td>—</td>
                <td class="mono right">—</td>
                <td class="mono right">—</td>
                <td>—</td>
                <td class="col-actions"></td>
            </tr>`;
        }
        return leases.map((l, i) => {
            const displayName = l.tenant ? l.tenant.name : (l.tenant_id ? 'Leased' : 'Vacant');
            const stepCount = (l.rent_steps || []).length;
            const frpCount = (l.free_rent_periods || []).length + (l.expense_recovery_overrides || []).length;
            const leaseActions = `<div class="card-actions" style="display:inline-flex;gap:4px;align-items:center">
                <button class="btn btn-secondary btn-sm" data-schedule-lease="${l.id}" style="padding:4px 10px;font-size:0.73rem">Schedule${stepCount ? ' (' + stepCount + ')' : ''}</button>
                <button class="btn-icon" data-detail-lease="${l.id}" title="Free rent & recovery overrides${frpCount ? ' (' + frpCount + ')' : ''}">${icons.detail}</button>
                <button class="btn-icon" data-edit-lease="${l.id}" title="Edit lease">${icons.edit}</button>
                <button class="btn-icon danger" data-delete-lease="${l.id}" title="Delete lease">${icons.trash}</button>
            </div>`;
            return `<tr>
                <td>${i === 0 ? suite.suite_name + ' ' + suiteActions : ''}</td>
                <td>${i === 0 ? suite.space_type : ''}</td>
                <td class="mono right">${i === 0 ? fmt.num(suite.area) : ''}</td>
                <td class="tenant-name">${displayName}</td>
                <td>${fmt.typeLabel(l.lease_type)}</td>
                <td>${fmt.date(l.lease_start_date)}</td>
                <td>${fmt.date(l.lease_end_date)}</td>
                <td class="mono right">${fmt.perSf(l.base_rent_per_unit, au)}</td>
                <td class="mono right">${fmt.currencyExact(parseFloat(l.base_rent_per_unit) * parseFloat(suite.area))}</td>
                <td>${fmt.typeLabel(l.recovery_type)}</td>
                <td class="col-actions">${leaseActions}</td>
            </tr>`;
        }).join('');
    }).join('');

    const totalRent = allLeases.reduce((s, l) => {
        const area = parseFloat(l.suite.area);
        return s + parseFloat(l.base_rent_per_unit) * area;
    }, 0);
    const colCount = 11;

    return `
        <div class="section-header">
            <h3 class="section-title">Rent Roll</h3>
            <div class="btn-group">
                <button class="btn btn-secondary btn-sm" id="newSuiteBtn">${icons.plus} New Suite</button>
                <button class="btn btn-primary btn-sm" id="newLeaseBtn">${icons.plus} New Lease</button>
            </div>
        </div>
        <div class="data-table-wrap">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Suite</th>
                        <th>Type</th>
                        <th class="right">${areaLabel}</th>
                        <th>Tenant</th>
                        <th>Lease Type</th>
                        <th>Start</th>
                        <th>End</th>
                        <th class="right">${rentLabel}</th>
                        <th class="right">Annual Rent</th>
                        <th>Recovery</th>
                        <th class="col-actions"></th>
                    </tr>
                </thead>
                <tbody>${rows || `<tr><td colspan="${colCount}" style="text-align:center;color:var(--text-tertiary);padding:32px">No suites or leases yet</td></tr>`}</tbody>
                ${totalRent > 0 ? `<tfoot>
                    <tr>
                        <td colspan="${colCount - 3}" style="text-align:right">Total Annual Rent</td>
                        <td style="text-align:right">${fmt.currencyExact(totalRent)}</td>
                        <td colspan="2"></td>
                    </tr>
                </tfoot>` : ''}
            </table>
        </div>`;
}


function renderOperatingBudgetTab(expenses, otherIncomeItems, totalArea, areaUnit, propertyType) {
    return `
        ${renderExpensesTab(expenses, totalArea, areaUnit, propertyType)}
        <div style="margin-top:32px">
            ${renderOtherIncomeTab(otherIncomeItems)}
        </div>`;
}

function renderExpensesTab(expenses, totalArea, areaUnit, propertyType) {
    const isMultifamily = propertyType === 'multifamily' || propertyType === 'self_storage';
    const perUnitLabel = areaUnit === 'unit' ? '$/Unit' : '$/SF';
    const totalExp = expenses.reduce((s, e) => s + (e.is_pct_of_egi ? 0 : parseFloat(e.base_year_amount)), 0);
    const colCount = isMultifamily ? 6 : 7;
    const rows = expenses.map(e => `
        <tr>
            <td class="tenant-name">${fmt.typeLabel(e.category)}</td>
            <td>${e.description || '—'}</td>
            <td class="mono right">${e.is_pct_of_egi ? fmt.pct(e.pct_of_egi) + ' of EGI' : fmt.currencyExact(e.base_year_amount)}</td>
            <td class="mono right">${e.is_pct_of_egi ? '—' : fmt.perSf(parseFloat(e.base_year_amount) / totalArea, areaUnit)}</td>
            <td class="mono right">${e.is_pct_of_egi ? '—' : fmt.pct(e.growth_rate_pct)}</td>
            ${isMultifamily ? '' : `<td>${e.is_recoverable ? 'Yes' : 'No'}</td>`}
            <td class="col-actions">
                <div class="card-actions" style="display:inline-flex">
                    <button class="btn-icon" data-edit-expense="${e.id}" title="Edit">${icons.edit}</button>
                    <button class="btn-icon danger" data-delete-expense="${e.id}" title="Delete">${icons.trash}</button>
                </div>
            </td>
        </tr>`).join('');

    return `
        <div class="section-header">
            <h3 class="section-title">Operating Expenses</h3>
            <div class="btn-group">
                <button class="btn btn-secondary btn-sm" id="bulkExpenseBtn">Bulk Edit</button>
                <button class="btn btn-primary btn-sm" id="newExpenseBtn">${icons.plus} New Expense</button>
            </div>
        </div>
        <div class="data-table-wrap">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Category</th>
                        <th>Description</th>
                        <th class="right">Base Amount</th>
                        <th class="right">${perUnitLabel}</th>
                        <th class="right">Growth</th>
                        ${isMultifamily ? '' : '<th>Recoverable</th>'}
                        <th class="col-actions"></th>
                    </tr>
                </thead>
                <tbody>${rows || `<tr><td colspan="${colCount}" style="text-align:center;color:var(--text-tertiary);padding:32px">No expenses defined</td></tr>`}</tbody>
                ${totalExp > 0 ? `<tfoot>
                    <tr>
                        <td colspan="2">Total (excl. % of EGI items)</td>
                        <td style="text-align:right">${fmt.currencyExact(totalExp)}</td>
                        <td style="text-align:right">${fmt.perSf(totalExp / totalArea, areaUnit)}</td>
                        <td colspan="3"></td>
                    </tr>
                </tfoot>` : ''}
            </table>
        </div>`;
}

function renderOtherIncomeTab(items) {
    const total = items.reduce((s, i) => s + parseFloat(i.base_year_amount), 0);
    const rows = items.map(i => `
        <tr>
            <td class="tenant-name">${fmt.typeLabel(i.category)}</td>
            <td>${i.description || '—'}</td>
            <td class="mono right">${fmt.currencyExact(i.base_year_amount)}</td>
            <td class="mono right">${fmt.pct(i.growth_rate_pct)}</td>
            <td class="col-actions">
                <div class="card-actions" style="display:inline-flex">
                    <button class="btn-icon" data-edit-other-income="${i.id}" title="Edit">${icons.edit}</button>
                    <button class="btn-icon danger" data-delete-other-income="${i.id}" title="Delete">${icons.trash}</button>
                </div>
            </td>
        </tr>`).join('');

    return `
        <div class="section-header">
            <h3 class="section-title">Custom Revenue Line Items</h3>
            <div class="btn-group">
                <button class="btn btn-secondary btn-sm" id="bulkOtherIncomeBtn">Bulk Edit</button>
                <button class="btn btn-primary btn-sm" id="newOtherIncomeBtn">${icons.plus} New Revenue Item</button>
            </div>
        </div>
        <div class="data-table-wrap">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Category</th>
                        <th>Description</th>
                        <th class="right">Base Amount</th>
                        <th class="right">Growth</th>
                        <th class="col-actions"></th>
                    </tr>
                </thead>
                <tbody>${rows || '<tr><td colspan="5" style="text-align:center;color:var(--text-tertiary);padding:32px">No custom revenue items defined</td></tr>'}</tbody>
                ${total > 0 ? `<tfoot>
                    <tr>
                        <td colspan="2">Total</td>
                        <td style="text-align:right">${fmt.currencyExact(total)}</td>
                        <td colspan="2"></td>
                    </tr>
                </tfoot>` : ''}
            </table>
        </div>`;
}


function renderMarketTab(profiles, property) {
    const au = property.area_unit;
    const isUnit = au === 'unit';
    return `
        <div class="section-header">
            <h3 class="section-title">Market Leasing Profiles</h3>
            <div style="display:flex;gap:8px">
                <button class="btn btn-secondary btn-sm" id="bulkMarketBtn">Assumption Workspace</button>
                ${isUnit ? '<button class="btn btn-secondary btn-sm" id="quickUnitMarketBtn">Legacy Quick Setup</button>' : ''}
                <button class="btn btn-primary btn-sm" id="newMarketBtn">${icons.plus} New Market Profile</button>
            </div>
        </div>
        ${isUnit ? '<div class="page-subtitle" style="margin-bottom:12px">Assumption Workspace gives spreadsheet-style entry with bulk paste, fill-down, and auto-population for all unit types.</div>' : ''}
        ${profiles.length === 0 ? '<div class="empty-state"><h3>No market profiles</h3><p>Add a market profile to enable renewal and new-tenant modeling.</p></div>' : `
        <div class="property-grid" style="grid-template-columns: repeat(auto-fill, minmax(300px, 1fr))">
            ${profiles.map(p => `
                <div class="property-card" style="cursor:default">
                    <div class="property-card-header">
                        <div>
                            <div class="property-card-name">${fmt.typeLabel(p.space_type)}</div>
                            <div class="property-card-location">${p.description || 'Market assumptions'}</div>
                        </div>
                        <div class="card-actions">
                            <button class="btn-icon" data-edit-market="${p.id}" title="Edit">${icons.edit}</button>
                            <button class="btn-icon danger" data-delete-market="${p.id}" title="Delete">${icons.trash}</button>
                        </div>
                    </div>
                    <div style="margin-top:16px">
                        <div class="info-grid" style="grid-template-columns:1fr 1fr; gap:10px; margin-bottom:0">
                            <div>
                                <div class="info-item-label">Market Rent</div>
                                <div class="info-item-value" style="color:var(--accent)">${fmt.perSf(p.market_rent_per_unit, au)}</div>
                            </div>
                            <div>
                                <div class="info-item-label">Rent Growth</div>
                                <div class="info-item-value">${fmt.pct(p.rent_growth_rate_pct)}</div>
                            </div>
                            <div>
                                <div class="info-item-label">Renewal Prob.</div>
                                <div class="info-item-value">${fmt.pct(p.renewal_probability)}</div>
                            </div>
                            <div>
                                <div class="info-item-label">Concession Timing</div>
                                <div class="info-item-value">${fmt.typeLabel(p.concession_timing_mode || 'blended')}</div>
                            </div>
                            <div>
                                <div class="info-item-label">New Concession</div>
                                <div class="info-item-value">${p.new_tenant_free_rent_months || 0} mo</div>
                            </div>
                            <div>
                                <div class="info-item-label">Renewal Concession</div>
                                <div class="info-item-value">${p.renewal_free_rent_months || 0} mo</div>
                            </div>
                            ${(p.concession_timing_mode || 'blended') === 'timed' ? `
                            <div>
                                <div class="info-item-label">Timed Concessions</div>
                                <div class="info-item-value">
                                    Y1 ${p.concession_year1_months ?? '—'} | Y2 ${p.concession_year2_months ?? '—'} | Y3 ${p.concession_year3_months ?? '—'} | Y4 ${p.concession_year4_months ?? '—'} | Y5 ${p.concession_year5_months ?? '—'} | Y6+ ${p.concession_stabilized_months ?? '—'}
                                </div>
                            </div>` : ''}
                            <div>
                                <div class="info-item-label">New TI${au === 'unit' ? '/Unit' : '/SF'}</div>
                                <div class="info-item-value">${fmt.perSf(p.new_tenant_ti_per_sf, au)}</div>
                            </div>
                            <div>
                                <div class="info-item-label">Downtime</div>
                                <div class="info-item-value">${p.downtime_months} mo</div>
                            </div>
                            <div>
                                <div class="info-item-label">Vacancy</div>
                                <div class="info-item-value">${fmt.pct(p.general_vacancy_pct)}</div>
                            </div>
                        </div>
                    </div>
                </div>`).join('')}
        </div>`}`;
}


function renderCapitalProjectsTab(projects, propertyId) {
    const rows = projects.map(cp => {
        const monthly = parseFloat(cp.total_amount) / cp.duration_months;
        return `<tr>
            <td class="tenant-name">${cp.description}</td>
            <td class="mono right">${fmt.currencyExact(cp.total_amount)}</td>
            <td>${fmt.dateFull(cp.start_date)}</td>
            <td class="mono right">${cp.duration_months} mo</td>
            <td class="mono right">${fmt.currencyExact(monthly)}</td>
            <td class="col-actions">
                <div class="card-actions" style="display:inline-flex">
                    <button class="btn-icon" data-edit-capex="${cp.id}" title="Edit">${icons.edit}</button>
                    <button class="btn-icon danger" data-delete-capex="${cp.id}" title="Delete">${icons.trash}</button>
                </div>
            </td>
        </tr>`;
    }).join('');

    return `
        <div class="section-header">
            <h3 class="section-title">Building Improvements</h3>
            <button class="btn btn-primary btn-sm" id="newCapexBtn">${icons.plus} New Project</button>
        </div>
        <div class="data-table-wrap">
            <table class="data-table">
                <thead><tr>
                    <th>Description</th><th class="right">Total Cost</th><th>Start Date</th><th class="right">Duration</th><th class="right">Monthly Spend</th><th class="col-actions"></th>
                </tr></thead>
                <tbody>${rows || '<tr><td colspan="6" style="text-align:center;color:var(--text-tertiary);padding:32px">No capital projects scheduled</td></tr>'}</tbody>
            </table>
        </div>`;
}


function renderRecoveryStructuresTab(structures, propertyId) {
    const cards = structures.map(rs => {
        const itemRows = rs.items.map(item => `
            <tr>
                <td class="tenant-name">${fmt.typeLabel(item.expense_category)}</td>
                <td>${fmt.typeLabel(item.recovery_type)}</td>
                <td class="mono right">${item.cap_per_sf_annual ? fmt.perSf(item.cap_per_sf_annual) : '—'}</td>
                <td class="mono right">${item.floor_per_sf_annual ? fmt.perSf(item.floor_per_sf_annual) : '—'}</td>
                <td class="mono right">${item.admin_fee_pct ? fmt.pct(item.admin_fee_pct) : '—'}</td>
                <td class="col-actions">
                    <button class="btn-icon danger" data-del-rs-item="${item.id}" data-rs-id="${rs.id}" title="Remove">${icons.trash}</button>
                </td>
            </tr>`).join('');

        return `
            <div class="property-card" style="cursor:default;margin-bottom:16px">
                <div class="property-card-header">
                    <div>
                        <div class="property-card-name">${rs.name}</div>
                        <div class="property-card-location">Default: ${fmt.typeLabel(rs.default_recovery_type)}${rs.description ? ' — ' + rs.description : ''}</div>
                    </div>
                    <div class="card-actions">
                        <button class="btn-icon" data-edit-rs="${rs.id}" title="Edit">${icons.edit}</button>
                        <button class="btn-icon danger" data-delete-rs="${rs.id}" title="Delete">${icons.trash}</button>
                    </div>
                </div>
                ${rs.items.length > 0 ? `
                <div class="data-table-wrap" style="margin-top:16px">
                    <table class="data-table" style="margin-bottom:0">
                        <thead><tr><th>Category</th><th>Recovery</th><th class="right">Cap/SF</th><th class="right">Floor/SF</th><th class="right">Admin %</th><th class="col-actions"></th></tr></thead>
                        <tbody>${itemRows}</tbody>
                    </table>
                </div>` : '<div style="margin-top:12px;color:var(--text-tertiary);font-size:0.87rem">No per-category overrides — all expenses use the default recovery type.</div>'}
                <div style="margin-top:12px">
                    <button class="btn btn-secondary btn-sm" data-add-rs-item="${rs.id}">${icons.plus} Add Category Override</button>
                </div>
            </div>`;
    }).join('');

    return `
        <div class="section-header">
            <h3 class="section-title">Recovery Structures</h3>
            <button class="btn btn-primary btn-sm" id="newRecoveryStructureBtn">${icons.plus} New Recovery Structure</button>
        </div>
        ${cards || '<div class="empty-state"><h3>No recovery structures</h3><p>Create a reusable recovery template to assign to leases.</p></div>'}`;
}


function renderValuationsTab(valuations, propertyId) {
    const items = valuations.map(v => {
        const isCompleted = v.status === 'completed';
        return `
            <div class="valuation-item" ${isCompleted ? `onclick="location.hash='#/valuation/${v.id}'"` : ''}>
                <div class="valuation-item-left">
                    <div class="valuation-item-name">${v.name}</div>
                    <div class="valuation-item-meta">
                        Discount: ${fmt.pct(v.discount_rate)} &middot; Exit Cap: ${fmt.pct(v.exit_cap_rate)}
                        ${v.loan_amount ? ' &middot; Levered' : ''}
                    </div>
                </div>
                <div class="valuation-item-right">
                    ${isCompleted ? `
                        <div class="valuation-item-metric">
                            <div class="valuation-item-metric-label">NPV</div>
                            <div class="valuation-item-metric-value">${fmt.currency(v.result_npv)}</div>
                        </div>
                        <div class="valuation-item-metric">
                            <div class="valuation-item-metric-label">IRR</div>
                            <div class="valuation-item-metric-value">${v.result_irr ? fmt.pct(v.result_irr) : '—'}</div>
                        </div>
                    ` : `
                        <button class="btn btn-primary btn-sm" data-run-valuation="${v.id}">Run</button>
                    `}
                    <span class="status-badge status-${v.status}">${v.status}</span>
                    <div class="card-actions">
                        <button class="btn-icon" data-edit-valuation="${v.id}" title="Edit">${icons.edit}</button>
                        <button class="btn-icon danger" data-delete-valuation="${v.id}" title="Delete">${icons.trash}</button>
                    </div>
                </div>
            </div>`;
    }).join('');

    return `
        <div class="section-header">
            <h3 class="section-title">Valuations</h3>
            <button class="btn btn-primary btn-sm" id="newValuationBtn">${icons.plus} New Valuation</button>
        </div>
        <div class="valuation-list">
            ${items || '<div class="empty-state"><h3>No valuations</h3><p>Create a new valuation to get started.</p></div>'}
        </div>`;
}


function renderRecoveryAuditTab(completedValuations) {
    if (!completedValuations || completedValuations.length === 0) {
        return `
            <div class="section-header">
                <h3 class="section-title">Tenant Recovery Audit</h3>
            </div>
            <div class="empty-state">
                <h3>No completed valuations</h3>
                <p>Run at least one valuation to generate tenant recovery audit rows.</p>
            </div>`;
    }

    const valuationOptions = completedValuations.map(v => (
        `<option value="${v.id}">${v.name} (${fmt.dateFull(v.updated_at || v.created_at)})</option>`
    )).join('');

    return `
        <div class="section-header">
            <h3 class="section-title">Tenant Recovery Audit</h3>
            <button class="btn btn-secondary btn-sm" id="openAuditValuationBtn" data-valuation-id="${completedValuations[0].id}">Open Valuation</button>
        </div>
        <div class="page-subtitle" style="margin-bottom:12px">
            Select a valuation and tenant to review recoveries by expense line, including stops, caps/floors, admin fees, proration, and free-rent abatement.
        </div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px">
            <div>
                <label for="recoveryAuditValuationSelect" style="display:block;font-size:0.78rem;color:var(--text-tertiary);margin-bottom:4px">Valuation</label>
                <select id="recoveryAuditValuationSelect" class="form-input" style="min-width:280px">${valuationOptions}</select>
            </div>
            <div>
                <label for="recoveryAuditTenantSelect" style="display:block;font-size:0.78rem;color:var(--text-tertiary);margin-bottom:4px">Tenant</label>
                <select id="recoveryAuditTenantSelect" class="form-input" style="min-width:220px">
                    <option value="__all__">All Tenants</option>
                </select>
            </div>
        </div>
        <div id="recoveryAuditSummary" style="font-size:0.84rem;color:var(--text-secondary);margin-bottom:10px">Select a valuation to load audit rows.</div>
        <div id="recoveryAuditTable"></div>`;
}


// ─── Help / Glossary ──────────────────────────────────────────

async function helpView() {
    setBreadcrumb([
        { label: 'Dashboard', href: '#/dashboard' },
        { label: 'Help & Glossary' }
    ]);

    $app().innerHTML = `
        <div class="page-header">
            <h1 class="page-title">Help & Glossary</h1>
            <p class="page-subtitle">Formulas, definitions, and worked examples for key calculations in OpenDCF.</p>
        </div>

        <div class="help-grid">
            <section class="help-card">
                <h3>Revenue Waterfall</h3>
                <div class="help-row"><strong>Gross Potential Rent (GPR)</strong><span>Contract base rent before free rent/vacancy.</span></div>
                <div class="help-row"><strong>Scheduled Rent</strong><span><code>GPR + Free Rent</code> (free rent is negative).</span></div>
                <div class="help-row"><strong>Unit-Type Concession Drag (Multifamily / Storage)</strong><span>For market-occupancy months, expected free-rent drag uses <code>((1 - Renewal Prob) × New Concession Mo + Renewal Prob × Renewal Concession Mo) / 12</code> applied to monthly market rent.</span></div>
                <div class="help-row"><strong>Timed Concession Mode</strong><span>Override blended drag with explicit concession months by analysis year (Y1-Y5 and Y6+ stabilized).</span></div>
                <div class="help-row"><strong>Gross Potential Income (GPI)</strong><span><code>Scheduled Rent + Recoveries + % Rent + Other Income</code>.</span></div>
                <div class="help-row"><strong>Effective Gross Income (EGI)</strong><span><code>GPI - General Vacancy - Credit Loss</code>.</span></div>
                <div class="help-example">
                    Example: If <code>GPR=1,000,000</code>, <code>Free Rent=-50,000</code>, <code>Recoveries=120,000</code>, <code>Other Income=30,000</code>, <code>General Vacancy=95,000</code>, <code>Credit Loss=19,000</code>, then <code>EGI=986,000</code>.
                </div>
            </section>

            <section class="help-card">
                <h3>NOI, CFBD, and Debt</h3>
                <div class="help-row"><strong>Operating Expenses</strong><span>Fixed expenses plus management fee (% of EGI if configured).</span></div>
                <div class="help-row"><strong>NOI</strong><span><code>EGI - Operating Expenses</code>.</span></div>
                <div class="help-row"><strong>CFBD</strong><span><code>NOI + TI + LC + Capital Reserves + Building Improvements</code> (cost items are negative).</span></div>
                <div class="help-row"><strong>Levered Cash Flow</strong><span><code>CFBD - Debt Service</code>.</span></div>
                <div class="help-example">
                    Example: <code>EGI=986,000</code>, <code>OpEx=320,000</code> gives <code>NOI=666,000</code>. If TI/LC/Reserves/CapEx total <code>-140,000</code>, then <code>CFBD=526,000</code>.
                </div>
            </section>

            <section class="help-card">
                <h3>Expense Recoveries</h3>
                <div class="help-row"><strong>NNN</strong><span><code>Recovery = Expense × Pro Rata Share</code>.</span></div>
                <div class="help-row"><strong>Base Year Stop</strong><span><code>Recovery = max(0, Expense - Stop) × Pro Rata Share</code>.</span></div>
                <div class="help-row"><strong>Modified Gross (pooled)</strong><span>Stop test uses pooled modified-gross expenses, then allocates by category share.</span></div>
                <div class="help-row"><strong>Full Service Gross / None</strong><span>Recovery is zero unless category overrides change type.</span></div>
                <div class="help-example">
                    Modified Gross example: pooled post-gross-up expenses are <code>$25.18/SF</code>, stop is <code>$11.00/SF</code>, tenant area <code>15,000 SF</code>.<br>
                    Excess = <code>14.18/SF</code>, tenant pooled annual recovery = <code>14.18 × 15,000 = 212,700</code> (rounded).<br>
                    If Real Estate Taxes are <code>35.75%</code> of the pool, tax recovery is <code>~76,013</code> annual.
                </div>
            </section>

            <section class="help-card">
                <h3>Gross-Up (Expense Stabilization)</h3>
                <div class="help-row"><strong>When applied</strong><span>For expenses marked gross-up eligible, only when actual occupancy is below target occupancy.</span></div>
                <div class="help-row"><strong>Formula</strong><span><code>Grossed Expense = Actual Expense × (Reference Occupancy / Actual Occupancy)</code>.</span></div>
                <div class="help-row"><strong>Reference occupancy</strong><span>Valuation-level stabilized occupancy if set; otherwise each expense line’s gross-up target.</span></div>
                <div class="help-example">
                    Example: CAM is <code>$360,000</code> at <code>80%</code> occupancy, reference is <code>95%</code>.<br>
                    Grossed CAM = <code>360,000 × (0.95 / 0.80) = 427,500</code>.
                </div>
            </section>

            <section class="help-card">
                <h3>Reversion / Terminal Value</h3>
                <div class="help-row"><strong>Default NOI basis</strong><span>By default, sale uses <code>Year N+1 NOI</code> (Hold + 1).</span></div>
                <div class="help-row"><strong>Gross Reversion</strong><span><code>NOI Basis / Exit Cap Rate</code>.</span></div>
                <div class="help-row"><strong>Net Reversion (Terminal Value)</strong><span><code>Gross Reversion - Exit Costs - Transfer Tax</code>.</span></div>
                <div class="help-example">
                    Example: <code>NOI=1,200,000</code>, <code>Exit Cap=6.0%</code> gives gross reversion <code>20,000,000</code>.<br>
                    If exit costs are <code>2.0%</code> and transfer tax is <code>1.0%</code>, net reversion is <code>19,400,000</code>.
                </div>
            </section>

            <section class="help-card">
                <h3>DCF Metrics</h3>
                <div class="help-row"><strong>NPV</strong><span>Present value of annual CFBD plus terminal value discounted at the valuation discount rate.</span></div>
                <div class="help-row"><strong>IRR</strong><span>Discount rate where NPV of the modeled cash flow series equals zero.</span></div>
                <div class="help-row"><strong>Going-In Cap</strong><span><code>Year 1 NOI / Implied Purchase Price</code>.</span></div>
                <div class="help-row"><strong>Average Occupancy</strong><span>Average of modeled monthly occupancy over the analysis horizon.</span></div>
                <div class="help-row"><strong>WALT</strong><span>Area-weighted remaining lease term (active in-place leases at analysis start).</span></div>
            </section>

            <section class="help-card">
                <h3>Tenant Recovery Audit Columns</h3>
                <div class="help-row"><strong>Actual Exp/SF (Pre/Post GU)</strong><span>Category annual expense divided by total property SF, before and after gross-up.</span></div>
                <div class="help-row"><strong>Pooled Exp/SF</strong><span>Total modified-gross pool per SF for the same month/lease group.</span></div>
                <div class="help-row"><strong>Excess Over Stop/SF</strong><span><code>max(0, Pooled Exp/SF - Stop/SF)</code>.</span></div>
                <div class="help-row"><strong>Category Share %</strong><span>Category post-GU annual amount divided by pooled post-GU annual amount.</span></div>
                <div class="help-row"><strong>Weighted Monthly</strong><span><code>(Annual Recovery / 12) × Proration × Free-Rent Flag × Scenario Weight</code>.</span></div>
            </section>
        </div>`;
}


// ─── Tenants View ────────────────────────────────────────────

async function tenantsView({ propertyId } = {}) {
    setBreadcrumb([
        { label: 'Dashboard', href: '#/dashboard' },
        { label: 'Tenants' }
    ]);

    let properties;
    try {
        properties = await api.get('/properties');
    } catch (err) {
        $app().innerHTML = `<div class="empty-state"><h3>Cannot load properties</h3><p>${err.message}</p></div>`;
        return;
    }

    if (!properties || properties.length === 0) {
        $app().innerHTML = `
            <div class="empty-state">
                <h3>No properties found</h3>
                <p>Create a property first. Tenants are scoped to each property.</p>
                <br><a href="#/dashboard" class="btn btn-secondary">Back to Dashboard</a>
            </div>`;
        return;
    }

    const selectedPropertyId = propertyId || properties[0].id;
    const selectedProperty = properties.find(p => p.id === selectedPropertyId) || properties[0];

    let tenants;
    try {
        tenants = await api.get(`/properties/${selectedProperty.id}/tenants`);
    } catch (err) {
        $app().innerHTML = `<div class="empty-state"><h3>Cannot load tenants</h3><p>${err.message}</p></div>`;
        return;
    }

    const propertyOptions = properties.map(p => (
        `<option value="${p.id}" ${p.id === selectedProperty.id ? 'selected' : ''}>${p.name}</option>`
    )).join('');

    const isUnitTenants = selectedProperty.property_type === 'multifamily' || selectedProperty.property_type === 'self_storage';
    const rows = tenants.map(t => `
        <tr>
            <td class="tenant-name">${t.name}</td>
            ${isUnitTenants ? '' : `<td>${t.credit_rating || '—'}</td>`}
            ${isUnitTenants ? '' : `<td>${t.industry || '—'}</td>`}
            <td>${t.contact_name || '—'}</td>
            <td>${t.contact_email || '—'}</td>
            <td>
                <div class="card-actions" style="display:inline-flex">
                    <button class="btn-icon" data-edit-tenant="${t.id}" title="Edit">${icons.edit}</button>
                    <button class="btn-icon danger" data-delete-tenant="${t.id}" title="Delete">${icons.trash}</button>
                </div>
            </td>
        </tr>`).join('');

    $app().innerHTML = `
        <div class="page-header">
            <h1 class="page-title">Tenants</h1>
            <p class="page-subtitle">${tenants.length} tenant${tenants.length !== 1 ? 's' : ''} for ${selectedProperty.name}</p>
        </div>

        <div class="section-header">
            <h2 class="section-title">Property</h2>
        </div>
        <div style="max-width:380px;margin-bottom:16px">
            <select id="tenantPropertySelect" class="form-input">${propertyOptions}</select>
        </div>

        <div class="section-header">
            <h2 class="section-title">Property Tenants</h2>
            <button class="btn btn-primary btn-sm" id="newTenantBtn">${icons.plus} New Tenant</button>
        </div>

        <div class="data-table-wrap">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        ${isUnitTenants ? '' : '<th>Credit Rating</th>'}
                        ${isUnitTenants ? '' : '<th>Industry</th>'}
                        <th>Contact</th>
                        <th>Email</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody>${rows || `<tr><td colspan="${isUnitTenants ? 4 : 6}" style="text-align:center;color:var(--text-tertiary);padding:32px">No tenants yet</td></tr>`}</tbody>
            </table>
        </div>`;

    const propertySelect = document.getElementById('tenantPropertySelect');
    if (propertySelect) {
        propertySelect.addEventListener('change', () => {
            location.hash = `#/tenants/${propertySelect.value}`;
        });
    }

    // New Tenant
    document.getElementById('newTenantBtn').addEventListener('click', () => {
        showFormModal({
            title: 'New Tenant',
            fields: buildTenantFields(selectedProperty.property_type),
            onSubmit: async (data, overlay) => {
                await api.post(`/properties/${selectedProperty.id}/tenants`, data);
                overlay.remove();
                toast('Tenant created', 'success');
                tenantsView({ propertyId: selectedProperty.id });
            }
        });
    });

    // Edit Tenant
    document.querySelectorAll('[data-edit-tenant]').forEach(btn => {
        btn.addEventListener('click', () => {
            const tid = btn.dataset.editTenant;
            const t = tenants.find(x => x.id === tid);
            showFormModal({
                title: 'Edit Tenant',
                fields: buildTenantFields(selectedProperty.property_type),
                initialValues: t,
                onSubmit: async (data, overlay) => {
                    await api.put(`/properties/${selectedProperty.id}/tenants/${tid}`, data);
                    overlay.remove();
                    toast('Tenant updated', 'success');
                    tenantsView({ propertyId: selectedProperty.id });
                }
            });
        });
    });

    // Delete Tenant
    document.querySelectorAll('[data-delete-tenant]').forEach(btn => {
        btn.addEventListener('click', () => {
            const tid = btn.dataset.deleteTenant;
            const t = tenants.find(x => x.id === tid);
            showDeleteConfirm(t.name, async () => {
                await api.del(`/properties/${selectedProperty.id}/tenants/${tid}`);
                toast('Tenant deleted', 'success');
                tenantsView({ propertyId: selectedProperty.id });
            });
        });
    });
}


// ─── New Valuation Modal ──────────────────────────────────────

function showNewValuationModal(propertyId, marketProfiles, propertyType = '') {
    // Compute dynamic stabilized occupancy default from market vacancy rates
    const mps = marketProfiles || [];
    const avgVacancy = mps.length > 0
        ? mps.reduce((s, m) => s + parseFloat(m.general_vacancy_pct || 0.05), 0) / mps.length
        : 0.05;
    const dynamicOccupancy = Math.round((1 - avgVacancy) * 10000) / 10000;
    const fields = buildValuationFields(propertyType).map(f =>
        f.key === 'stabilized_occupancy_pct' ? { ...f, default: dynamicOccupancy } : f
    );
    showFormModal({
        title: 'New Valuation',
        fields,
        wide: true,
        onSubmit: async (data, overlay) => {
            const val = await api.post(`/properties/${propertyId}/valuations`, data);
            // Auto-run after creation
            const submitBtn = overlay.querySelector('.btn-primary');
            if (submitBtn) submitBtn.textContent = 'Running...';
            try {
                await api.post(`/valuations/${val.id}/run`);
                toast('Valuation completed!', 'success');
            } catch (err) {
                toast('Created but run failed: ' + err.message, 'error');
            }
            overlay.remove();
            location.hash = `#/valuation/${val.id}`;
        }
    });
}


// ─── Valuation Detail ─────────────────────────────────────────

async function valuationView({ id }) {
    const [valuation, fullReport] = await Promise.all([
        api.get(`/valuations/${id}`),
        api.get(`/valuations/${id}/reports/full`).catch(() => null),
    ]);

    // Get property + market profiles + expenses (for reversion gross-up disclosure)
    let property, marketProfiles = [], expenses = [];
    try {
        [property, marketProfiles, expenses] = await Promise.all([
            api.get(`/properties/${valuation.property_id}`),
            api.get(`/properties/${valuation.property_id}/market-profiles`),
            api.get(`/properties/${valuation.property_id}/expenses`),
        ]);
    } catch { property = null; }

    const crumbs = [{ label: 'Dashboard', href: '#/dashboard' }];
    if (property) crumbs.push({ label: property.name, href: `#/property/${valuation.property_id}` });
    crumbs.push({ label: valuation.name });
    setBreadcrumb(crumbs);
    const effectiveStartDate = valuation.analysis_start_date_override || (property ? property.analysis_start_date : null);
    const startDateLabel = effectiveStartDate ? fmt.date(effectiveStartDate) : '—';
    const startDateSuffix = valuation.analysis_start_date_override ? ' (Override)' : '';

    // Shared action button wiring (used for both draft and completed states)
    function wireValuationActions() {
        // Edit
        const editBtn = document.getElementById('valEditBtn');
        if (editBtn) {
            editBtn.onclick = () => {
                showFormModal({
                    title: 'Edit Valuation',
                    fields: buildValuationFields(property ? property.property_type : ''),
                    wide: true,
                    initialValues: valuation,
                    onSubmit: async (data, overlay) => {
                        await api.put(`/valuations/${id}`, data);
                        overlay.remove();
                        toast('Valuation updated', 'success');
                        valuationView({ id });
                    }
                });
            };
        }
        // Delete
        const deleteBtn = document.getElementById('valDeleteBtn');
        if (deleteBtn) {
            deleteBtn.onclick = () => {
                showDeleteConfirm(valuation.name, async () => {
                    await api.del(`/valuations/${id}`);
                    toast('Valuation deleted', 'success');
                    if (property) location.hash = `#/property/${property.id}`;
                    else location.hash = '#/dashboard';
                });
            };
        }
        // Run / Re-run
        const runBtn = document.getElementById('valRunBtn');
        if (runBtn) {
            runBtn.onclick = async () => {
                runBtn.textContent = 'Running...';
                runBtn.disabled = true;
                try {
                    await api.post(`/valuations/${id}/run`);
                    toast('Valuation completed!', 'success');
                    valuationView({ id });
                } catch (err) {
                    toast('Error: ' + err.message, 'error');
                    runBtn.textContent = fullReport ? 'Re-run' : 'Run Valuation';
                    runBtn.disabled = false;
                }
            };
        }
        // Export rent roll (Excel)
        const exportBtn = document.getElementById('valExportRentRollBtn');
        if (exportBtn) {
            exportBtn.onclick = async () => {
                const original = exportBtn.textContent;
                exportBtn.textContent = 'Exporting...';
                exportBtn.disabled = true;
                try {
                    const res = await fetch(`${API}/valuations/${id}/reports/rent-roll.xlsx`);
                    if (!res.ok) {
                        const text = await res.text().catch(() => '');
                        throw new Error(`Export failed (${res.status}) ${text}`);
                    }
                    const blob = await res.blob();
                    const cd = res.headers.get('Content-Disposition') || '';
                    const match = cd.match(/filename=\"?([^"]+)\"?/i);
                    const filename = match ? match[1] : `rent-roll-${id}.xlsx`;
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    URL.revokeObjectURL(url);
                    toast('Rent roll exported', 'success');
                } catch (err) {
                    toast('Error: ' + err.message, 'error');
                } finally {
                    exportBtn.textContent = original;
                    exportBtn.disabled = false;
                }
            };
        }
        // Open dedicated tenant recovery audit page/tab
        const auditBtn = document.getElementById('valAuditBtn');
        if (auditBtn && valuation.property_id) {
            auditBtn.onclick = () => {
                sessionStorage.setItem('opendcf_property_tab', 'recovery-audit');
                sessionStorage.setItem('opendcf_recovery_audit_valuation_id', valuation.id);
                location.hash = `#/property/${valuation.property_id}`;
            };
        }
    }

    const isMultifamilyVal = property && (property.property_type === 'multifamily' || property.property_type === 'self_storage');
    const actionButtons = `
        <div class="property-header-actions">
            <button class="btn btn-secondary btn-sm" id="valExportRentRollBtn">Export Rent Roll (Excel)</button>
            ${isMultifamilyVal ? '' : '<button class="btn btn-secondary btn-sm" id="valAuditBtn">Tenant Recovery Audit</button>'}
            <button class="btn btn-secondary btn-sm" id="valEditBtn">${icons.edit} Edit</button>
            <button class="btn btn-primary btn-sm" id="valRunBtn">${fullReport && fullReport.key_metrics ? 'Re-run' : 'Run Valuation'}</button>
            <button class="btn btn-danger btn-sm" id="valDeleteBtn">${icons.trash} Delete</button>
        </div>`;

    if (!fullReport || !fullReport.key_metrics) {
        $app().innerHTML = `
            <div class="property-header">
                <div class="property-header-left">
                    <h1 class="property-header-title">${valuation.name}</h1>
                    <div class="property-header-address">Status: ${valuation.status} &middot; Start ${startDateLabel}${startDateSuffix}${valuation.error_message ? ' — ' + valuation.error_message : ''}</div>
                </div>
                ${actionButtons}
            </div>
            <div class="empty-state">
                <h3>Valuation not yet run</h3>
                <p>This valuation is in <strong>${valuation.status}</strong> status. Click "Run Valuation" above to execute.</p>
                ${valuation.error_message ? `<p style="color:var(--red);margin-top:12px">${valuation.error_message}</p>` : ''}
            </div>`;
        wireValuationActions();
        return;
    }

    const km = fullReport.key_metrics;
    const cf = fullReport.annual_cash_flows;
    const tenants = fullReport.tenant_cash_flows;
    const expirations = fullReport.lease_expiration_schedule;
    const showLeaseExpirations = !property || (
        property.property_type !== 'multifamily' && property.property_type !== 'self_storage'
    );

    $app().innerHTML = `
        <div class="property-header">
            <div class="property-header-left">
                <h1 class="property-header-title">${valuation.name}</h1>
                <div class="property-header-address">${property ? property.name : ''} &middot; Start ${startDateLabel}${startDateSuffix} &middot; ${fmt.pct(valuation.discount_rate)} discount &middot; ${fmt.pct(valuation.exit_cap_rate)} exit cap${valuation.loan_amount ? ' &middot; Levered' : ''}</div>
            </div>
            ${actionButtons}
        </div>

        <!-- Key Metrics -->
        <div class="metrics-grid">
            <div class="metric-card highlight">
                <div class="metric-label">Net Present Value</div>
                <div class="metric-value accent">${fmt.currency(km.npv)}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">IRR</div>
                <div class="metric-value">${km.irr ? fmt.pct(km.irr) : '—'}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Going-In Cap</div>
                <div class="metric-value">${fmt.pct(km.going_in_cap_rate)}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Terminal Value</div>
                <div class="metric-value">${fmt.currency(km.terminal_value)}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Avg Occupancy</div>
                <div class="metric-value">${fmt.pct(km.avg_occupancy_pct, 1)}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">WALT</div>
                <div class="metric-value">${km.weighted_avg_lease_term_years != null ? fmt.years(km.weighted_avg_lease_term_years) : '—'}</div>
            </div>
        </div>

        <!-- Charts Row -->
        <div class="two-col">
            <div class="chart-container">
                <div class="chart-title">Net Operating Income</div>
                <div class="chart-wrap"><canvas id="noiChart"></canvas></div>
            </div>
            <div class="chart-container">
                <div class="chart-title">Cash Flow Before Debt</div>
                <div class="chart-wrap"><canvas id="cfbdChart"></canvas></div>
            </div>
        </div>

        ${showLeaseExpirations && expirations.length > 0 ? `
        <div class="chart-container">
            <div class="chart-title">Lease Expiration Schedule</div>
            <div class="chart-wrap"><canvas id="expChart"></canvas></div>
        </div>` : ''}

        <!-- Annual Cash Flow Table -->
        <div class="section-header">
            <h3 class="section-title">Annual Cash Flow Summary</h3>
        </div>
        <div class="cf-table-wrap" id="cfTableWrap">
            ${renderCashFlowTable(cf, tenants, marketProfiles, property ? property.area_unit : 'sf')}
        </div>
        ${renderReversionValueSection(valuation, km, cf, expenses)}
    `;

    // Render charts
    renderNOIChart(cf);
    renderCFBDChart(cf);
    if (showLeaseExpirations && expirations.length > 0) renderExpirationChart(expirations);

    wireValuationActions();

    // Expandable cash flow rows
    document.querySelectorAll('#cfTable tr.expandable').forEach(row => {
        row.querySelector('td').addEventListener('click', () => {
            const groupId = row.dataset.toggle;
            const isExpanded = row.classList.toggle('expanded');
            document.querySelectorAll(`#cfTable tr.sub-row[data-group="${groupId}"]`).forEach(sub => {
                sub.classList.toggle('visible', isExpanded);
            });
        });
    });

    // MLA hover tooltips on tenant sub-rows
    document.querySelectorAll('#cfTable .mla-hover[data-mla]').forEach(el => {
        el.addEventListener('mouseenter', () => showMlaTip(el, decodeURIComponent(el.dataset.mla)));
        el.addEventListener('mouseleave', hideMlaTip);
    });
}

function renderReversionValueSection(valuation, keyMetrics, cashFlows, expenses = []) {
    if (!valuation || !keyMetrics || !cashFlows || cashFlows.length === 0) return '';

    const asNum = (v) => {
        const n = parseFloat(v);
        return Number.isFinite(n) ? n : 0;
    };

    const exitCapRate = asNum(valuation.exit_cap_rate);
    const exitCostsPct = asNum(valuation.exit_costs_pct);
    const terminalValue = asNum(keyMetrics.terminal_value);
    const transferTaxPreset = String(
        valuation.transfer_tax_preset || keyMetrics.terminal_transfer_tax_preset || 'none'
    );
    const transferTaxCustomRate = asNum(valuation.transfer_tax_custom_rate);
    const holdYear = cashFlows[cashFlows.length - 1].year;
    const exitYearSetting = Number.isFinite(Number(valuation.exit_cap_applied_to_year))
        ? Number(valuation.exit_cap_applied_to_year)
        : -1;
    const presetLabels = {
        none: 'None',
        custom_rate: 'Custom Flat Rate',
        la_city_ula: 'Los Angeles: City + ULA',
        san_francisco_transfer: 'San Francisco Transfer Tax',
        nyc_nys_commercial: 'NYC + NYS Commercial',
        philadelphia_realty_transfer: 'Philadelphia Realty Transfer',
        dc_deed_transfer_recordation: 'Washington, DC Deed Taxes',
        wa_state_reet: 'Washington State REET',
    };
    const presetLabel = presetLabels[transferTaxPreset] || fmt.typeLabel(transferTaxPreset);
    const calcTransferTax = (gross, preset, customRate) => {
        if (!Number.isFinite(gross) || gross <= 0) return 0;
        const code = String(preset || 'none').toLowerCase();
        if (code === 'none') return 0;
        if (code === 'custom_rate') return gross * Math.max(0, customRate || 0);
        if (code === 'la_city_ula') {
            const ula = gross > 10600000 ? 0.055 : (gross > 5300000 ? 0.04 : 0);
            return gross * (0.0045 + ula);
        }
        if (code === 'san_francisco_transfer') {
            let rate = 0.03;
            if (gross < 250000) rate = 0.005;
            else if (gross < 1000000) rate = 0.0068;
            else if (gross < 5000000) rate = 0.0075;
            else if (gross < 10000000) rate = 0.0225;
            else if (gross < 25000000) rate = 0.0275;
            return gross * rate;
        }
        if (code === 'nyc_nys_commercial') {
            const nyc = gross < 500000 ? 0.01425 : 0.02625;
            const nys = 0.004 + (gross >= 2000000 ? 0.0025 : 0);
            return gross * (nyc + nys);
        }
        if (code === 'philadelphia_realty_transfer') return gross * 0.04278;
        if (code === 'dc_deed_transfer_recordation') return gross * (gross < 400000 ? 0.022 : 0.029);
        if (code === 'wa_state_reet') {
            let tax = 0;
            const b1 = 525000;
            const b2 = 1525000;
            const b3 = 3025000;
            if (gross > 0) tax += Math.min(gross, b1) * 0.011;
            if (gross > b1) tax += (Math.min(gross, b2) - b1) * 0.0128;
            if (gross > b2) tax += (Math.min(gross, b3) - b2) * 0.0275;
            if (gross > b3) tax += (gross - b3) * 0.03;
            return tax;
        }
        return 0;
    };

    let noiBasis = asNum(keyMetrics.terminal_noi_basis);
    let noiLabel = '';
    let grossReversion = asNum(keyMetrics.terminal_gross_value);
    let exitCostsAmount = asNum(keyMetrics.terminal_exit_costs_amount);
    let transferTaxAmount = asNum(keyMetrics.terminal_transfer_tax_amount);
    const hasStoredBreakdown =
        keyMetrics.terminal_gross_value != null &&
        keyMetrics.terminal_noi_basis != null;

    if (!hasStoredBreakdown) {
        if (exitYearSetting === -1) {
            // Engine convention: default terminal value uses forward (Hold+1) NOI.
            noiLabel = `Year ${holdYear + 1} NOI (Hold + 1)`;
            const denominator = 1 - exitCostsPct;
            const grossFromTerminal = denominator > 0 ? terminalValue / denominator : 0;
            noiBasis = grossFromTerminal * exitCapRate;
        } else {
            noiLabel = `Year ${exitYearSetting} NOI`;
            const selectedYearCf = cashFlows.find((row) => row.year === exitYearSetting);
            if (selectedYearCf) {
                noiBasis = asNum(selectedYearCf.net_operating_income);
            } else {
                const denominator = 1 - exitCostsPct;
                const grossFromTerminal = denominator > 0 ? terminalValue / denominator : 0;
                noiBasis = grossFromTerminal * exitCapRate;
                noiLabel += ' (derived from terminal value)';
            }
        }
        grossReversion = exitCapRate > 0 ? noiBasis / exitCapRate : 0;
        exitCostsAmount = grossReversion * exitCostsPct;
        transferTaxAmount = 0;
    } else if (exitYearSetting === -1) {
        noiLabel = `Year ${holdYear + 1} NOI (Hold + 1)`;
    } else {
        noiLabel = `Year ${exitYearSetting} NOI`;
    }

    // Always reflect currently saved valuation assumption immediately, even before re-run.
    transferTaxAmount = calcTransferTax(grossReversion, transferTaxPreset, transferTaxCustomRate);
    const netReversion = grossReversion - exitCostsAmount - transferTaxAmount;
    const calcVariance = terminalValue - netReversion;
    const transferRate = grossReversion > 0 ? transferTaxAmount / grossReversion : 0;
    const grossUpEnabled = !!valuation.apply_stabilized_gross_up;
    const stabilizedOcc = valuation.stabilized_occupancy_pct != null ? asNum(valuation.stabilized_occupancy_pct) : null;
    const eligibleGrossUp = (expenses || []).filter(e => e.is_gross_up_eligible && !e.is_pct_of_egi);
    const grossUpCategoryList = [...new Set(eligibleGrossUp.map(e => fmt.typeLabel(e.category)))].join(', ');
    const grossUpNote = grossUpEnabled
        ? (stabilizedOcc != null
            ? `Enabled (global target ${fmt.pct(stabilizedOcc)})`
            : 'Enabled (using per-expense gross-up targets)')
        : 'Not applied';
    const grossUpRows = grossUpEnabled
        ? `
                    <tr>
                        <td>Gross-Up Setting</td>
                        <td>Apply stabilized gross-up to eligible operating expenses</td>
                        <td class="mono right">${grossUpNote}</td>
                    </tr>
                    <tr>
                        <td>Gross-Up Scope</td>
                        <td>Eligible expense categories in this property</td>
                        <td class="mono right">${eligibleGrossUp.length > 0 ? grossUpCategoryList : 'None marked eligible'}</td>
                    </tr>
        `
        : `
                    <tr>
                        <td>Gross-Up Setting</td>
                        <td>Apply stabilized gross-up to eligible operating expenses</td>
                        <td class="mono right">Not applied</td>
                    </tr>
        `;

    return `
        <div class="section-header" style="margin-top:20px">
            <h3 class="section-title">Reversion Value Calculation</h3>
        </div>
        <div class="data-table-wrap">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Component</th>
                        <th>Formula</th>
                        <th class="right">Value</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>${noiLabel}</td>
                        <td>NOI basis for sale</td>
                        <td class="mono right">${fmt.currencyExact(noiBasis)}</td>
                    </tr>
                    ${grossUpRows}
                    <tr>
                        <td>Gross Reversion</td>
                        <td>${fmt.currencyExact(noiBasis)} / ${fmt.pct(exitCapRate)}</td>
                        <td class="mono right">${fmt.currencyExact(grossReversion)}</td>
                    </tr>
                    <tr>
                        <td>Less: Exit Costs</td>
                        <td>${fmt.currencyExact(grossReversion)} × ${fmt.pct(exitCostsPct)}</td>
                        <td class="mono right negative">-${fmt.currencyExact(exitCostsAmount)}</td>
                    </tr>
                    <tr>
                        <td>Less: Transfer Tax</td>
                        <td>${presetLabel}${transferTaxAmount > 0 ? ` (${fmt.pct(transferRate)})` : ''}</td>
                        <td class="mono right negative">-${fmt.currencyExact(transferTaxAmount)}</td>
                    </tr>
                    <tr>
                        <td><strong>Net Reversion (Terminal Value)</strong></td>
                        <td>Gross Reversion − Exit Costs − Transfer Tax</td>
                        <td class="mono right"><strong>${fmt.currencyExact(netReversion)}</strong></td>
                    </tr>
                    <tr>
                        <td>Model Terminal Value (stored)</td>
                        <td>From valuation run output</td>
                        <td class="mono right">${fmt.currencyExact(terminalValue)}</td>
                    </tr>
                    <tr>
                        <td>Calculation Variance</td>
                        <td>Stored − Recomputed</td>
                        <td class="mono right ${Math.abs(calcVariance) > 1 ? 'negative' : ''}">${fmt.currencyExact(calcVariance)}</td>
                    </tr>
                </tbody>
            </table>
        </div>`;
}


function mlaTooltipHtml(m, area, areaUnit) {
    const au = areaUnit;
    return `<strong>${fmt.typeLabel(m.space_type)} Market Profile</strong>
${area ? `<span>Suite: ${fmt.sf(area, au)}</span>` : ''}
<span>Market Rent: ${fmt.perSf(m.market_rent_per_unit, au)}</span>
<span>Rent Growth: ${fmt.pct(m.rent_growth_rate_pct)}/yr</span>
<span>Renewal Prob: ${fmt.pct(m.renewal_probability)}</span>
<span>Downtime: ${m.downtime_months} mo</span>
<span>New TI: ${fmt.perSf(m.new_tenant_ti_per_sf, au)} | LC: ${fmt.pct(m.new_tenant_lc_pct)}</span>
<span>Renewal TI: ${fmt.perSf(m.renewal_ti_per_sf, au)} | LC: ${fmt.pct(m.renewal_lc_pct)}</span>
<span>Vacancy: ${fmt.pct(m.general_vacancy_pct)} | Credit Loss: ${fmt.pct(m.credit_loss_pct)}</span>`;
}

// Floating tooltip singleton (appended to body, positioned by JS)
let _mlaTip = null;
function showMlaTip(el, html) {
    if (!_mlaTip) { _mlaTip = document.createElement('div'); _mlaTip.className = 'mla-tip'; document.body.appendChild(_mlaTip); }
    _mlaTip.innerHTML = html;
    const r = el.getBoundingClientRect();
    _mlaTip.style.left = r.left + 'px';
    _mlaTip.style.top = (r.top - _mlaTip.offsetHeight - 8) + 'px';
    _mlaTip.classList.add('show');
}
function hideMlaTip() { if (_mlaTip) _mlaTip.classList.remove('show'); }

function renderCashFlowTable(cashFlows, tenants, mktProfiles, areaUnit) {
    if (!cashFlows || cashFlows.length === 0) return '<div class="empty-state"><p>No cash flow data</p></div>';
    const numYears = cashFlows.length;
    const hasTenants = tenants && tenants.length > 0;

    // Build market profile lookup by space_type for tooltips
    const mlaByType = {};
    (mktProfiles || []).forEach(m => { mlaByType[m.space_type] = m; });

    const header = `<tr>
        <th>Line Item</th>
        ${cashFlows.map(cf => `<th class="right" title="${fiscalYearRangeLabel(cf)}">${fiscalYearLabel(cf)}</th>`).join('')}
    </tr>`;

    const row = (label, field, cls = '') => `<tr class="${cls}">
        <td>${label}</td>
        ${cashFlows.map(cf => {
            const v = parseFloat(cf[field]);
            const neg = v < 0 ? 'negative' : '';
            return `<td class="${neg}">${fmt.currencyExact(v)}</td>`;
        }).join('')}
    </tr>`;

    // Expandable row: property total + hidden tenant sub-rows
    const expandableRow = (label, field, tenantField, cls = '') => {
        if (!hasTenants) return row(label, field, cls);
        const groupId = 'cfx_' + field;
        let html = `<tr class="${cls} expandable" data-toggle="${groupId}">
            <td><span class="expand-chevron">&#9654;</span>${label}</td>
            ${cashFlows.map(cf => {
                const v = parseFloat(cf[field]);
                const neg = v < 0 ? 'negative' : '';
                return `<td class="${neg}">${fmt.currencyExact(v)}</td>`;
            }).join('')}
        </tr>`;
        // Sub-rows per tenant
        tenants.forEach((t, ti) => {
            const vals = t[tenantField] || [];
            // Skip if all zeros
            if (vals.every(v => parseFloat(v) === 0)) return;
            const tenantLabel = `${t.suite_name}${t.tenant_name ? ' — ' + t.tenant_name : ''}`;
            const scenarioTag = t.scenario !== 'in_place' ? ` <span style="font-size:0.67rem;opacity:0.7">${fmt.typeLabel(t.scenario)}</span>` : '';
            const mla = mlaByType[t.space_type];
            const mlaAttr = mla ? ` data-mla="${encodeURIComponent(mlaTooltipHtml(mla, t.area, areaUnit))}"` : '';
            html += `<tr class="sub-row" data-group="${groupId}">
                <td><span class="mla-hover"${mlaAttr}>${tenantLabel}${scenarioTag}</span></td>
                ${vals.slice(0, numYears).map(v => {
                    const n = parseFloat(v);
                    const neg = n < 0 ? 'negative' : '';
                    return `<td class="${neg}">${fmt.currencyExact(n)}</td>`;
                }).join('')}
            </tr>`;
        });
        return html;
    };

    // Expandable expense row with per-category detail
    const expandableExpenseRow = () => {
        // Collect all unique categories across years
        const categories = new Set();
        cashFlows.forEach(cf => {
            if (cf.expense_detail) Object.keys(cf.expense_detail).forEach(k => categories.add(k));
        });
        if (categories.size === 0) return row('Operating Expenses', 'operating_expenses');
        const groupId = 'cfx_opex';
        let html = `<tr class="expandable" data-toggle="${groupId}">
            <td><span class="expand-chevron">&#9654;</span>Operating Expenses</td>
            ${cashFlows.map(cf => {
                const v = parseFloat(cf.operating_expenses);
                const neg = v < 0 ? 'negative' : '';
                return `<td class="${neg}">${fmt.currencyExact(v)}</td>`;
            }).join('')}
        </tr>`;
        [...categories].sort().forEach(cat => {
            html += `<tr class="sub-row" data-group="${groupId}">
                <td>${fmt.typeLabel(cat)}</td>
                ${cashFlows.map(cf => {
                    const v = cf.expense_detail ? parseFloat(cf.expense_detail[cat] || 0) : 0;
                    const neg = v < 0 ? 'negative' : '';
                    return `<td class="${neg}">${fmt.currencyExact(v)}</td>`;
                }).join('')}
            </tr>`;
        });
        return html;
    };

    // Expandable other income row with per-category detail
    const expandableOtherIncomeRow = () => {
        const categories = new Set();
        cashFlows.forEach(cf => {
            if (cf.other_income_detail) Object.keys(cf.other_income_detail).forEach(k => categories.add(k));
        });
        if (categories.size === 0) return row('Other Income', 'other_income');
        const groupId = 'cfx_other_income';
        let html = `<tr class="expandable" data-toggle="${groupId}">
            <td><span class="expand-chevron">&#9654;</span>Other Income</td>
            ${cashFlows.map(cf => {
                const v = parseFloat(cf.other_income);
                const neg = v < 0 ? 'negative' : '';
                return `<td class="${neg}">${fmt.currencyExact(v)}</td>`;
            }).join('')}
        </tr>`;
        [...categories].sort().forEach(cat => {
            html += `<tr class="sub-row" data-group="${groupId}">
                <td>${fmt.typeLabel(cat)}</td>
                ${cashFlows.map(cf => {
                    const v = cf.other_income_detail ? parseFloat(cf.other_income_detail[cat] || 0) : 0;
                    const neg = v < 0 ? 'negative' : '';
                    return `<td class="${neg}">${fmt.currencyExact(v)}</td>`;
                }).join('')}
            </tr>`;
        });
        return html;
    };

    // (TI/LC now shown as separate expandable rows below)

    return `<table class="cf-table" id="cfTable">
        <thead>${header}</thead>
        <tbody>
            <tr class="subtotal">
                <td>Market Rent Potential</td>
                ${cashFlows.map(cf => {
                    const v = parseFloat(cf.gross_potential_rent) - parseFloat(cf.absorption_vacancy) - parseFloat(cf.loss_to_lease);
                    return `<td>${fmt.currencyExact(v)}</td>`;
                }).join('')}
            </tr>
            ${expandableRow('Turnover Vacancy', 'absorption_vacancy', 'annual_turnover_vacancy')}
            ${expandableRow('Loss to Lease', 'loss_to_lease', 'annual_loss_to_lease')}
            ${expandableRow('Scheduled Base Rent', 'gross_potential_rent', 'annual_base_rent')}
            ${expandableRow('Free Rent', 'free_rent', 'annual_free_rent')}
            ${expandableRow('Expense Recoveries', 'expense_recoveries', 'annual_recoveries')}
            ${row('Percentage Rent', 'percentage_rent')}
            ${expandableOtherIncomeRow()}
            ${row('Gross Potential Income', 'gross_potential_income', 'subtotal')}
            ${row('General Vacancy', 'general_vacancy_loss')}
            ${row('Credit Loss', 'credit_loss')}
            ${row('Effective Gross Income', 'effective_gross_income', 'subtotal')}
            ${expandableExpenseRow()}
            ${row('Net Operating Income', 'net_operating_income', 'total')}
            ${expandableRow('Tenant Improvements', 'tenant_improvements', 'annual_ti')}
            ${expandableRow('Leasing Commissions', 'leasing_commissions', 'annual_lc')}
            ${row('Capital Reserves', 'capital_reserves')}
            ${row('Building Improvements', 'building_improvements')}
            ${row('Cash Flow Before Debt', 'cash_flow_before_debt', 'total')}
            ${cashFlows[0].debt_service && parseFloat(cashFlows[0].debt_service) !== 0 ? `
                ${row('Debt Service', 'debt_service')}
                ${row('Levered Cash Flow', 'levered_cash_flow', 'total')}
            ` : ''}
        </tbody>
    </table>`;
}


function renderTenantDetail(tenants, yearCount) {
    const rows = tenants.map(t => `
        <tr>
            <td class="tenant-name">${t.suite_name}</td>
            <td>${t.tenant_name || '<span class="vacant">Vacant</span>'}</td>
            <td>${fmt.typeLabel(t.scenario)}</td>
            <td class="mono right">${fmt.num(t.area)}</td>
            ${t.annual_base_rent.map(v => `<td class="mono right">${fmt.currencyExact(v)}</td>`).join('')}
        </tr>`).join('');

    return `<div class="cf-table-wrap">
        <table class="cf-table">
            <thead><tr>
                <th>Suite</th><th>Tenant</th><th>Scenario</th><th class="right">Area</th>
                ${Array.from({ length: yearCount }, (_, i) => `<th class="right">Yr ${i + 1}</th>`).join('')}
            </tr></thead>
            <tbody>${rows}</tbody>
        </table>
    </div>`;
}


// ─── Charts ───────────────────────────────────────────────────

function renderNOIChart(cf) {
    const ctx = document.getElementById('noiChart');
    if (!ctx) return;
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: cf.map(c => fiscalYearLabel(c)),
            datasets: [{
                data: cf.map(c => parseFloat(c.net_operating_income)),
                backgroundColor: 'rgba(0, 113, 227, 0.65)',
                borderColor: 'rgba(0, 113, 227, 0.9)',
                borderWidth: 1,
                borderRadius: 4,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: { callback: v => fmt.currency(v) },
                    grid: { color: '#f0f0f5' }
                },
                x: { grid: { display: false } }
            },
            plugins: {
                tooltip: {
                    callbacks: { label: ctx => 'NOI: ' + fmt.currencyExact(ctx.raw) }
                }
            }
        }
    });
}


function renderCFBDChart(cf) {
    const ctx = document.getElementById('cfbdChart');
    if (!ctx) return;
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: cf.map(c => fiscalYearLabel(c)),
            datasets: [{
                data: cf.map(c => parseFloat(c.cash_flow_before_debt)),
                backgroundColor: cf.map(c => parseFloat(c.cash_flow_before_debt) >= 0
                    ? 'rgba(52, 199, 89, 0.55)'
                    : 'rgba(255, 59, 48, 0.55)'),
                borderColor: cf.map(c => parseFloat(c.cash_flow_before_debt) >= 0
                    ? 'rgba(52, 199, 89, 0.85)'
                    : 'rgba(255, 59, 48, 0.85)'),
                borderWidth: 1,
                borderRadius: 4,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    ticks: { callback: v => fmt.currency(v) },
                    grid: { color: '#f0f0f5' }
                },
                x: { grid: { display: false } }
            },
            plugins: {
                tooltip: {
                    callbacks: { label: ctx => 'CFBD: ' + fmt.currencyExact(ctx.raw) }
                }
            }
        }
    });
}


function renderExpirationChart(expirations) {
    const ctx = document.getElementById('expChart');
    if (!ctx) return;
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: expirations.map(e => `Year ${e.year}`),
            datasets: [{
                label: 'Expiring Area (SF)',
                data: expirations.map(e => parseFloat(e.expiring_area)),
                backgroundColor: 'rgba(255, 159, 10, 0.55)',
                borderColor: 'rgba(255, 159, 10, 0.85)',
                borderWidth: 1,
                borderRadius: 4,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: { callback: v => fmt.num(v) + ' SF' },
                    grid: { color: '#f0f0f5' }
                },
                x: { grid: { display: false } }
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        label: ctx => {
                            const e = expirations[ctx.dataIndex];
                            return [
                                `Area: ${fmt.sf(e.expiring_area)}`,
                                `Leases: ${e.expiring_leases}`,
                                `% of GLA: ${fmt.pct(e.pct_of_total_gla, 1)}`
                            ];
                        }
                    }
                }
            }
        }
    });
}


// ═══════════════════════════════════════════════════════════════
// REGISTER ROUTES & INIT
// ═══════════════════════════════════════════════════════════════

addRoute('/dashboard', dashboardView);
addRoute('/property/:id', propertyView);
addRoute('/tenants', tenantsView);
addRoute('/tenants/:propertyId', tenantsView);
addRoute('/help', helpView);
addRoute('/valuation/:id', valuationView);

window.addEventListener('hashchange', navigate);
window.addEventListener('DOMContentLoaded', () => {
    checkHealth();
    navigate();
    // Periodic health check
    setInterval(checkHealth, 30000);
});
