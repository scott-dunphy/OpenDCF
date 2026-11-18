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
    sf(val, areaUnit, propertyType = '') {
        const n = parseFloat(val);
        if (isNaN(n)) return '—';
        const suffix = areaUnit === 'unit'
            ? (propertyType === 'marina' ? ' Slips' : ' Units')
            : ' SF';
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
    // Monthly rows carry their analysis year; label them by month instead
    if (cf.period_start && cf.period_end
        && (new Date(cf.period_end) - new Date(cf.period_start)) < 32 * 86400000) {
        return fmt.date(cf.period_start);
    }
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

// Year-by-year rate tables (type: 'rateList') are entered as comma-separated percents.
function parseRateList(text) {
    return String(text || '').split(/[,;\s]+/).filter(Boolean)
        .map(s => parseFloat(s.replace('%', '')) / 100)
        .filter(n => !Number.isNaN(n));
}

function formatRateList(list) {
    return (list || []).map(v => (parseFloat(v) * 100).toFixed(2)).join(', ');
}

// Year-by-year plain numbers (type: 'numberList': months, dollars) are entered as a list.
// "120,000" is one number (thousands separators); "3, 2, 1" or "3;2;1" is three.
function parseNumberList(text) {
    return String(text || '').replace(/\$/g, '').split(/[;\s]+/).filter(Boolean)
        .flatMap(tok => (/^-?\d{1,3}(,\d{3})+(\.\d+)?$/.test(tok) ? [tok.replace(/,/g, '')] : tok.split(',')))
        .map(s => parseFloat(s))
        .filter(n => !Number.isNaN(n));
}

function formatNumberList(list) {
    return (list || []).map(v => String(parseFloat(v))).join('; ');
}

// Additional loans (type: 'loanList'), one per line:
// "label; amount; rate %; amortization months; term months; interest-only months; fees %".
// Blank amortization = 360, blank term = outstanding through the sale.
function parseLoanList(text) {
    const num = s => { const t = String(s || '').replace(/[$,%\s]/g, ''); return t === '' ? null : parseFloat(t); };
    return String(text || '').split('\n').map(line => line.split(';')).filter(p => p.length >= 3 && num(p[1]) != null)
        .map(([label, amount, rate, amort, term, io, fees]) => ({
            label: (label || '').trim() || null,
            loan_amount: num(amount),
            interest_rate: (num(rate) || 0) / 100,
            amortization_months: num(amort),
            loan_term_months: num(term),
            io_period_months: num(io) || 0,
            loan_fees_pct: (num(fees) || 0) / 100,
        }));
}

function formatLoanList(list) {
    const pct = v => String(+(parseFloat(v || 0) * 100).toFixed(4));
    return (list || []).map(l => [l.label || '', parseFloat(l.loan_amount), pct(l.interest_rate),
        l.amortization_months ?? '', l.loan_term_months ?? '', l.io_period_months || 0, pct(l.loan_fees_pct)].join('; '))
        .join('\n');
}

// Rent steps at lease months (type: 'stepList') are entered as "month: percent" pairs.
function parseStepList(text) {
    return String(text || '').split(/[,;]+/).map(s => s.split(':'))
        .filter(p => p.length === 2)
        .map(([m, pct]) => [parseInt(m, 10), parseFloat(pct.replace('%', '')) / 100])
        .filter(([m, pct]) => !Number.isNaN(m) && !Number.isNaN(pct));
}

function formatStepList(list) {
    return (list || []).map(([m, pct]) => `${m}: ${(parseFloat(pct) * 100).toFixed(2)}`).join(', ');
}

// Rent is a rate times area, or the whole space's $ amount (rent_basis 'total', e.g. an antenna on 0 SF)
function rentUnits(basis, area) {
    return basis === 'total' ? 1 : parseFloat(area);
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

// Edit forms pass onSubmit only the fields the user changed. An endpoint that replaces the whole
// record (or a handler that rebuilds the body) needs the unchanged values too: take them from the
// record being edited.
function withUnchanged(fields, record, changed) {
    const full = {};
    fields.forEach(f => { if (f.key && record && f.key in record) full[f.key] = record[f.key]; });
    return { ...full, ...changed };
}

// Underline a label's text and attach its tooltip (see tips.js)
function setLabelTip(label, tip) {
    if (!tip) return;
    const span = document.createElement('span');
    span.className = 'has-tip';
    span.tabIndex = 0;
    span.setAttribute('data-tip', tip);
    span.textContent = label.textContent;
    label.textContent = '';
    label.appendChild(span);
}

function showFormModal({ title, fields, initialValues, onSubmit, wide, smartPaste = false, memoryKey, defaults, submitLabel }) {
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
    const remembered = initialValues ? {} : readFormMemory(resolvedMemoryKey);
    const hasMemoryDefaults = !initialValues && Object.keys(remembered).length > 0;
    // `defaults` prefill a new record (over remembered values) without making the form an edit
    const memoryDefaults = initialValues ? {} : { ...remembered, ...(defaults || {}) };

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

    // Text a number field shows: percents as 5.00, $/SF to the cent; '' when not a number
    function numberInputText(f, raw) {
        const n = parseFloat(raw);
        if (Number.isNaN(n)) return '';
        if (isPercentNumberField(f)) return (n * 100).toFixed(2);
        if (isPerSfNumberField(f)) return n.toFixed(2);
        return String(n);
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
            else if (f.type === 'rateList') vals[f.key] = parseRateList(el.value);
            else if (f.type === 'numberList') vals[f.key] = parseNumberList(el.value);
            else if (f.type === 'loanList') vals[f.key] = parseLoanList(el.value);
            else if (f.type === 'stepList') vals[f.key] = parseStepList(el.value);
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
                    if (!inputEls[key] || !container.contains(inputEls[key])) {
                        const hidden = document.createElement('input');
                        hidden.type = 'hidden';
                        hidden.id = 'form_' + key;
                        container.appendChild(hidden);
                        inputEls[key] = hidden;
                    }
                    inputEls[key].value = value;
                });
                const customLabel = container.querySelector('.form-label');
                if (customLabel && !customLabel.children.length) setLabelTip(customLabel, fieldTip(f));
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
                setLabelTip(lbl, fieldTip(f));
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
            setLabelTip(label, fieldTip(f));
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
            } else if (f.type === 'textarea' || f.type === 'loanList') {
                input = document.createElement('textarea');
                input.className = 'form-input';
                input.rows = 3;
                if (f.placeholder) input.placeholder = f.placeholder;
            } else {
                input = document.createElement('input');
                input.className = 'form-input';
                input.type = (f.type === 'rateList' || f.type === 'stepList' || f.type === 'numberList') ? 'text' : (f.type || 'text');
                if (f.type === 'rateList') input.placeholder = 'e.g. 3.00, 3.00, 2.50';
                if (f.type === 'numberList') input.placeholder = f.placeholder || 'e.g. 6; 6; 4';
                if (f.type === 'stepList') input.placeholder = 'e.g. 61: 10.00';
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
            if (f.type === 'rateList') {
                initVal = Array.isArray(rawInitVal) ? formatRateList(rawInitVal) : '';
            } else if (f.type === 'numberList') {
                initVal = Array.isArray(rawInitVal) ? formatNumberList(rawInitVal) : '';
            } else if (f.type === 'loanList') {
                initVal = Array.isArray(rawInitVal) ? formatLoanList(rawInitVal) : '';
            } else if (f.type === 'stepList') {
                initVal = Array.isArray(rawInitVal) ? formatStepList(rawInitVal) : '';
            } else if ((isPercentNumberField(f) || isPerSfNumberField(f)) && rawInitVal !== '' && rawInitVal != null) {
                initVal = numberInputText(f, rawInitVal);
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

            // Handle half- and third-width rows
            if (f.half || f.third) {
                const per = f.third ? 3 : 2;
                if (!currentRow || currentRowCount >= per || Number(currentRow.dataset.per) !== per) {
                    currentRow = document.createElement('div');
                    currentRow.className = per === 3 ? 'form-row thirds' : 'form-row';
                    currentRow.dataset.per = per;
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
    submitBtn.textContent = submitLabel || (initialValues ? 'Save Changes' : 'Create');
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
                if (f.type === 'rateList') {
                    if (formatRateList(v) !== formatRateList(initialValues[f.key])) payload[f.key] = v;
                    return;
                }
                if (f.type === 'numberList') {
                    if (formatNumberList(v) !== formatNumberList(initialValues[f.key])) payload[f.key] = v;
                    return;
                }
                if (f.type === 'loanList') {
                    if (formatLoanList(v) !== formatLoanList(initialValues[f.key])) payload[f.key] = v;
                    return;
                }
                if (f.type === 'stepList') {
                    if (formatStepList(v) !== formatStepList(initialValues[f.key])) payload[f.key] = v;
                    return;
                }
                // A number shown rounded and left untouched keeps its stored precision
                if (f.type === 'number' && v != null && initialValues[f.key] != null
                    && numberInputText(f, v) === numberInputText(f, initialValues[f.key])) return;
                // An untouched blank field reads back as "" for a stored null: not a change
                const blank = (x) => x == null || x === '';
                if (v !== initialValues[f.key] && !(blank(v) && blank(initialValues[f.key]))) {
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
            submitBtn.textContent = submitLabel || (initialValues ? 'Save Changes' : 'Create');
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
    let pendingPaste = null;  // a tall paste waiting for the rows it needs

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
                            ${colDefs.map(c => {
                                const tip = fieldTip(c);
                                const text = tip ? `<span class="has-tip" tabindex="0" data-tip="${escapeHtmlAttr(tip)}">${escapeHtmlAttr(c.label)}</span>` : escapeHtmlAttr(c.label);
                                return `<th${c.align === 'right' ? ' class="right"' : ''}>${text}</th>`;
                            }).join('')}
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

        function applyPaste(target, pastedText, preventDefault) {
            if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement)) return;
            const td = target.closest('td[data-col-index]');
            const tr = target.closest('tr[data-row-index]');
            if (!td || !tr) return;
            const startRow = parseInt(tr.getAttribute('data-row-index') || '-1', 10);
            const startCol = parseInt(td.getAttribute('data-col-index') || '-1', 10);
            if (startRow < 0 || startCol < 0) return;

            const matrix = parseClipboardMatrix(pastedText);
            if (matrix.length === 0) return;

            const singleCell = matrix.length === 1 && matrix[0].length === 1;
            const maxRows = table.querySelectorAll('tbody tr').length;
            if (!singleCell && matrix[0].length > tableColCount) return;

            preventDefault();

            // A pasted block taller than the table adds rows, then pastes into the new table
            if (!singleCell && startRow + matrix.length > maxRows) {
                workingRows = snapshotRowsFromDom();
                while (workingRows.length < startRow + matrix.length) workingRows.push(buildNewBulkRow(colDefs));
                pendingPaste = { startRow, startCol, pastedText };
                render();
                return;
            }

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
        }

        table.addEventListener('paste', (event) => {
            applyPaste(event.target, event.clipboardData?.getData('text/plain') || '', () => event.preventDefault());
        });
        if (pendingPaste) {
            const { startRow, startCol, pastedText } = pendingPaste;
            pendingPaste = null;
            const cell = table.querySelector(`tr[data-row-index="${startRow}"] td[data-col-index="${startCol}"] [data-col-key]`);
            if (cell) applyPaste(cell, pastedText, () => {});
        }

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
            <div class="modal-title danger">Delete ${escapeHtmlAttr(label)}?</div>
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

// ─── Merge duplicate properties ───────────────────────────────
// The target keeps every valuation, comp, loan and portfolio membership of the chosen properties,
// which are then deleted (POST /properties/{id}/merge).
async function openMergeProperties(property) {
    const [groups, summaries] = await Promise.all([api.get('/properties/duplicates'), api.get('/properties/summary')]);
    const group = groups.find(g => g.properties.some(p => p.id === property.id));
    const likely = new Map((group ? group.properties : []).filter(p => p.id !== property.id).map(p => [p.id, p]));
    const candidates = summaries
        .filter(s => s.id !== property.id && s.property_type === property.property_type && s.area_unit === property.area_unit)
        .sort((a, b) => (likely.has(b.id) - likely.has(a.id)) || a.name.localeCompare(b.name));
    const describe = (s) => {
        const vals = likely.get(s.id)?.valuations;
        const valText = vals ? (vals.length ? vals.map(v => escapeHtmlAttr(v.name) + (v.review_status !== 'draft' ? ` (${v.review_status.replace('_', ' ')})` : '')).join(', ') : 'no valuations')
            : `${s.valuation_count} valuation${s.valuation_count === 1 ? '' : 's'}`;
        const area = parseFloat(s.total_area) === parseFloat(property.total_area) ? fmt.sf(s.total_area, s.area_unit, s.property_type)
            : `<span style="color:var(--warning, #b7791f)">${fmt.sf(s.total_area, s.area_unit, s.property_type)} (this property: ${fmt.sf(property.total_area, property.area_unit, property.property_type)})</span>`;
        return { valText, area };
    };
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
    document.body.appendChild(overlay);

    const pick = () => {
        overlay.innerHTML = `<div class="modal wide">
            <div class="modal-title">Merge duplicates into ${escapeHtmlAttr(property.name)}</div>
            <p style="color:var(--text-secondary);margin:0 0 12px">Tick the properties that are this same building. Their valuations, comparable sales, loans and portfolio memberships move here; the ticked properties are then deleted.</p>
            ${candidates.length ? `<div style="max-height:50vh;overflow:auto">${candidates.map(s => {
                const d = describe(s);
                return `<label style="display:flex;gap:10px;align-items:flex-start;padding:8px 0;border-bottom:1px solid var(--border-color, #e2e2e2);cursor:pointer">
                    <input type="checkbox" value="${s.id}" style="margin-top:3px">
                    <span><strong>${escapeHtmlAttr(s.name)}</strong>${likely.has(s.id) ? ' <span class="status-badge">Likely duplicate</span>' : ''}
                    <br><span style="color:var(--text-secondary);font-size:0.9em">${[s.city, s.state].filter(Boolean).map(escapeHtmlAttr).join(', ')}${s.city || s.state ? ' · ' : ''}${d.area} · ${d.valText}</span></span>
                </label>`;
            }).join('')}</div>` : `<p>No other ${fmt.typeLabel(property.property_type).toLowerCase()} properties to merge.</p>`}
            <div class="modal-actions">
                <button class="btn btn-secondary" id="mergeCancel">Cancel</button>
                <button class="btn btn-primary" id="mergeNext" disabled>Review merge…</button>
            </div>
        </div>`;
        const boxes = [...overlay.querySelectorAll('input[type=checkbox]')];
        const next = overlay.querySelector('#mergeNext');
        boxes.forEach(b => b.onchange = () => { next.disabled = !boxes.some(x => x.checked); });
        overlay.querySelector('#mergeCancel').onclick = () => overlay.remove();
        next.onclick = () => review(candidates.filter(s => boxes.find(b => b.value === s.id).checked));
    };

    const review = (chosen) => {
        overlay.innerHTML = `<div class="modal wide">
            <div class="modal-title danger">Merge ${chosen.length} propert${chosen.length === 1 ? 'y' : 'ies'} into ${escapeHtmlAttr(property.name)}?</div>
            <ul style="margin:0 0 12px;padding-left:20px">${chosen.map(s => {
                const d = describe(s);
                return `<li><strong>${escapeHtmlAttr(s.name)}</strong> — ${d.area}<br><span style="color:var(--text-secondary)">Moves: ${d.valText}, plus its comparable sales, loans, portfolio memberships and history</span></li>`;
            }).join('')}</ul>
            <div class="modal-warning">${chosen.length === 1 ? 'This property is' : 'These properties are'} then permanently deleted. This cannot be undone. Frozen (in review or approved) valuations move unchanged and keep their snapshots.</div>
            <div class="modal-actions">
                <button class="btn btn-secondary" id="mergeBack">Back</button>
                <button class="btn btn-danger" id="mergeGo">Merge and delete</button>
            </div>
        </div>`;
        overlay.querySelector('#mergeBack').onclick = pick;
        const go = overlay.querySelector('#mergeGo');
        go.onclick = async () => {
            go.disabled = true; go.textContent = 'Merging…';
            try {
                const result = await api.post(`/properties/${property.id}/merge`, { source_ids: chosen.map(s => s.id) });
                const changed = result.merged.filter(m => Object.keys(m.differences).length);
                overlay.remove();
                toast(`Merged ${result.merged.length} propert${result.merged.length === 1 ? 'y' : 'ies'}; ${result.valuations.length} valuation${result.valuations.length === 1 ? '' : 's'} moved`
                    + (changed.length ? `. Re-run moved drafts: ${changed.map(m => m.name).join(', ')} differed in ${[...new Set(changed.flatMap(m => Object.keys(m.differences)))].join(', ').replaceAll('_', ' ')}` : ''), 'success');
                location.hash = `#/property/${property.id}`;
                navigate();
            } catch (err) {
                toast('Merge failed: ' + err.message, 'error');
                go.disabled = false; go.textContent = 'Merge and delete';
            }
        };
    };
    pick();
}

// Dashboard: link to likely duplicate groups
async function renderDuplicateNotice() {
    const el = document.getElementById('duplicateNotice');
    if (!el) return;
    const groups = await api.get('/properties/duplicates').catch(() => []);
    if (!groups.length) return;
    el.innerHTML = `<button type="button" class="btn btn-secondary btn-sm" id="reviewDuplicatesBtn">${groups.length} possible duplicate group${groups.length === 1 ? '' : 's'} — review</button>`;
    el.querySelector('#reviewDuplicatesBtn').onclick = () => {
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
        overlay.innerHTML = `<div class="modal wide">
            <div class="modal-title">Possible duplicate properties</div>
            <p style="color:var(--text-secondary);margin:0 0 12px">Same name and type, and the same size or address. Open the one to keep and use More → Merge duplicates….</p>
            ${groups.map(g => `<div style="margin-bottom:12px"><strong>${escapeHtmlAttr(g.name)}</strong> · ${fmt.typeLabel(g.property_type)}
                <ul style="margin:4px 0 0;padding-left:20px">${g.properties.map(p => `<li><a href="#/property/${p.id}">${escapeHtmlAttr(p.name)}</a> — ${fmt.sf(p.total_area, p.area_unit, p.property_type)} · ${p.valuations.length ? p.valuations.map(v => escapeHtmlAttr(v.name)).join(', ') : 'no valuations'}</li>`).join('')}</ul></div>`).join('')}
            <div class="modal-actions"><button class="btn btn-secondary" id="dupClose">Close</button></div>
        </div>`;
        document.body.appendChild(overlay);
        overlay.querySelector('#dupClose').onclick = () => overlay.remove();
        overlay.querySelectorAll('a').forEach(a => a.addEventListener('click', () => overlay.remove()));
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

// Top-level sections. Each groups related routes; the sub-nav lists its pages.
const SECTIONS = {
    properties: { prefixes: ['/dashboard', '/property', '/valuation', '/tenants'] },
    portfolio: {
        prefixes: ['/funds', '/fund', '/portfolio', '/assumptions'],
        pages: [
            { href: '#/funds', label: 'Funds', match: ['/funds', '/fund/'] },
            { href: '#/portfolio', label: 'Cash flow rollup', match: ['/portfolio'] },
            { href: '#/assumptions', label: 'Assumptions library', match: ['/assumptions'] },
        ],
    },
    lending: {
        prefixes: ['/loans', '/loan', '/risk-runs', '/risk-run', '/simulations', '/simulation', '/admin'],
        pages: [
            { href: '#/loans', label: 'Loan book', match: ['/loans', '/loan/'] },
            { href: '#/risk-runs', label: 'Risk runs', match: ['/risk-runs', '/risk-run/'] },
            { href: '#/simulations', label: 'Simulations', match: ['/simulations', '/simulation/'] },
            { href: '#/admin', label: 'Risk settings', match: ['/admin'] },
        ],
    },
    more: { prefixes: ['/import', '/help'] },
};

function sectionForPath(path) {
    for (const [key, section] of Object.entries(SECTIONS)) {
        if (section.prefixes.some(p => path === p || path.startsWith(p + '/'))) return key;
    }
    return 'properties';
}

function renderShell(path) {
    const sectionKey = sectionForPath(path);
    document.querySelectorAll('#topnavLinks [data-section]').forEach(link => {
        link.classList.toggle('active', link.dataset.section === sectionKey);
    });
    const subnav = document.getElementById('subnav');
    const pages = SECTIONS[sectionKey].pages;
    if (!subnav) return;
    if (!pages) {
        subnav.hidden = true;
        subnav.innerHTML = '';
        return;
    }
    subnav.hidden = false;
    subnav.innerHTML = `<div class="subnav-inner">${pages.map(p => {
        const active = p.match.some(m => path === m || path.startsWith(m));
        return `<a href="${p.href}" class="subnav-link${active ? ' active' : ''}">${escapeHtmlAttr(p.label)}</a>`;
    }).join('')}</div>`;
}

// Dropdown menus: <div class="menu"><button class="menu-trigger">…</button><div class="menu-list">…</div></div>
document.addEventListener('click', (e) => {
    const trigger = e.target.closest('.menu-trigger');
    const openMenus = document.querySelectorAll('.menu.open');
    if (trigger) {
        const menu = trigger.closest('.menu');
        const wasOpen = menu.classList.contains('open');
        openMenus.forEach(m => m.classList.remove('open'));
        if (!wasOpen) menu.classList.add('open');
        return;
    }
    openMenus.forEach(m => m.classList.remove('open'));
});
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') document.querySelectorAll('.menu.open').forEach(m => m.classList.remove('open'));
});

function menuHtml(label, items, { primary = false, align = 'right' } = {}) {
    return `<div class="menu">
        <button type="button" class="btn ${primary ? 'btn-primary' : 'btn-secondary'} btn-sm menu-trigger" aria-haspopup="true">${label} <span class="menu-caret">▾</span></button>
        <div class="menu-list${align === 'right' ? ' menu-list--right' : ''}">${items.filter(Boolean).join('')}</div>
    </div>`;
}

function menuItem(id, label, { danger = false, hint = '' } = {}) {
    return `<button type="button" class="menu-item${danger ? ' menu-item--danger' : ''}" id="${id}">${label}${hint ? `<span class="menu-item-hint">${hint}</span>` : ''}</button>`;
}

// Placeholder in the shape of the page being loaded (styles in css/ws5.css)
function skeletonRows(n) {
    return `<div class="skeleton-rows">${'<div class="skeleton-row"></div>'.repeat(n)}</div>`;
}

function pageSkeleton(path) {
    if (path.startsWith('/valuation/')) return valuationSkeletonHtml();
    if (path === '/dashboard') {
        return `<div class="skeleton" role="status" aria-label="Loading">
            <div class="skeleton-line skeleton-line--title"></div>
            <div class="skeleton-line skeleton-line--short"></div>
            ${skeletonRows(8)}
        </div>`;
    }
    if (path.startsWith('/property/')) {
        return `<div class="skeleton" role="status" aria-label="Loading">
            <div class="skeleton-line skeleton-line--title"></div>
            <div class="skeleton-line skeleton-line--short"></div>
            <div class="skeleton-block"></div>
            ${skeletonRows(10)}
        </div>`;
    }
    return null;
}

async function navigate() {
    const hash = location.hash || '#/dashboard';
    const path = hash.slice(1); // remove #
    renderShell(path);

    for (const route of routes) {
        const match = path.match(route.regex);
        if (match) {
            const params = {};
            route.paramNames.forEach((name, i) => params[name] = match[i + 1]);
            $app().innerHTML = pageSkeleton(path) || '<div class="loading-screen"><div class="loading-spinner"></div><p>Loading...</p></div>';
            try {
                await route.handler(params);
            } catch (err) {
                console.error('Route error:', err);
                $app().innerHTML = `
                    <div class="empty-state">
                        <h3>Something went wrong</h3>
                        <p>${escapeHtmlAttr(err.message)}</p>
                        <br><a href="#/dashboard" class="btn btn-secondary">Back to Properties</a>
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
    // Outside Properties the section sub-nav already says where you are
    if (sectionForPath(location.hash.slice(1) || '/dashboard') !== 'properties') {
        items = items.filter(item => item.label !== 'Properties');
    }
    if (items.length <= 1) items = [];
    bc.innerHTML = items.map((item, i) => {
        if (i === items.length - 1) {
            return `<span class="current">${escapeHtmlAttr(item.label)}</span>`;
        }
        return `<a href="${escapeHtmlAttr(item.href)}">${escapeHtmlAttr(item.label)}</a><span class="sep">/</span>`;
    }).join('');
}


// ─── Chart.js Global Config ──────────────────────────────────

// Colors come from the theme tokens in style.css and follow theme changes (theme.js)
function applyChartTheme() {
    const css = getComputedStyle(document.documentElement);
    const token = (name) => css.getPropertyValue(name).trim();
    Chart.defaults.color = token('--chart-text');
    Chart.defaults.borderColor = token('--chart-grid');
    Chart.defaults.scale.grid.color = token('--chart-grid');
    Chart.defaults.plugins.tooltip.backgroundColor = token('--tooltip-bg');
    Chart.defaults.plugins.tooltip.borderColor = token('--tooltip-bg');
    Chart.defaults.plugins.tooltip.titleColor = token('--tooltip-text');
    Chart.defaults.plugins.tooltip.bodyColor = token('--tooltip-text');
}
applyChartTheme();
window.addEventListener('themechange', () => {
    applyChartTheme();
    // Chart.js caches axis colors per chart, so redraw the current page's charts
    if (Object.keys(Chart.instances).length) navigate();
});
Chart.defaults.font.family = "'Inter', -apple-system, sans-serif";
Chart.defaults.font.size = 11;
Chart.defaults.plugins.legend.display = false;
Chart.defaults.plugins.tooltip.borderWidth = 0;
Chart.defaults.plugins.tooltip.cornerRadius = 8;
Chart.defaults.plugins.tooltip.titleFont = { family: "'Inter', sans-serif", size: 12, weight: 600 };
Chart.defaults.plugins.tooltip.bodyFont = { family: "'Inter', sans-serif", size: 11 };
Chart.defaults.plugins.tooltip.padding = 10;


// ═══════════════════════════════════════════════════════════════
// FIELD DEFINITIONS
// ═══════════════════════════════════════════════════════════════

// Types offered for new properties. Marina is hidden for now; existing marina properties still open.
const PROPERTY_TYPES = ['office', 'retail', 'industrial', 'mixed_use', 'multifamily', 'self_storage', 'seniors_housing'];
const UNIT_BASED_PROPERTY_TYPES = new Set(['multifamily', 'self_storage', 'marina', 'seniors_housing']);

function areaUnitForPropertyType(propertyType) {
    return UNIT_BASED_PROPERTY_TYPES.has(propertyType) ? 'unit' : 'sf';
}

const PROPERTY_FIELDS = [
    { key: 'name', label: 'Property Name', type: 'text', required: true },
    { key: 'property_type', label: 'Property Type', type: 'select', options: PROPERTY_TYPES, required: true, half: true },
    {
        key: 'area_unit',
        label: 'Area Unit',
        type: 'custom',
        half: true,
        render: (container, vals, setValue) => {
            const propertyType = vals.property_type || 'office';
            const areaUnit = areaUnitForPropertyType(propertyType);
            setValue('area_unit', areaUnit);
            const areaUnitLabel = propertyType === 'marina'
                ? 'Slips'
                : propertyType === 'seniors_housing'
                ? 'Beds/Units'
                : (areaUnit === 'sf' ? 'SF' : 'Units');

            const group = document.createElement('div');
            group.className = 'form-group';

            const label = document.createElement('label');
            label.className = 'form-label';
            label.textContent = 'Area Unit';
            group.appendChild(label);

            const input = document.createElement('input');
            input.className = 'form-input';
            input.type = 'text';
            input.value = areaUnitLabel;
            input.readOnly = true;
            group.appendChild(input);

            const help = document.createElement('div');
            help.className = 'form-help';
            help.textContent = 'Auto-selected from property type.';
            group.appendChild(help);

            container.appendChild(group);
        },
    },
    { key: 'total_area', label: 'Size', type: 'number', required: true, step: '1', half: true, helpText: 'Rentable SF, or the number of units / slips / beds.' },
    { key: 'year_built', label: 'Year Built', type: 'number', step: '1', half: true },
    { type: 'section', label: 'Location' },
    { key: 'address_line1', label: 'Address', type: 'text' },
    { key: 'address_line2', label: 'Address Line 2', type: 'text' },
    { key: 'city', label: 'City', type: 'text', half: true },
    { key: 'state', label: 'State', type: 'text', half: true },
    { key: 'zip_code', label: 'Zip Code', type: 'text', half: true },
    { key: 'market', label: 'Market / submarket', type: 'text', half: true, helpText: 'Free-text label, e.g. Uptown. Profiles can match it by name.' },
    { key: 'cbsa_label', label: 'Census market (CBSA)', type: 'text', half: true, suggestions: [],
      helpText: 'Filled from the ZIP code; type to pick another. The assumptions library is keyed on it.' },
    { key: 'quality_score', label: 'Quality (1-5)', type: 'number', step: '0.5', min: 1, max: 5, half: true,
      helpText: '5 = best, 3 = typical for the market. Places this property inside library ranges.' },
    { type: 'section', label: 'Defaults for new valuations', collapsible: true, defaultCollapsed: true,
      collapsedSummary: (v) => `${v.analysis_period_months ? Math.round(v.analysis_period_months / 12) : 10}-yr hold from ${v.analysis_start_date || 'next month'}` },
    { key: 'analysis_start_date', label: 'Analysis Start', type: 'date', half: true, helpText: 'Each valuation can set its own.' },
    { key: 'analysis_period_months', label: 'Hold Period (months)', type: 'number', step: '12', min: 12, max: 360, default: 120, half: true,
      helpText: 'Whole years only (12, 24, … 360).' },
    { type: 'section', label: 'Ownership & mapping', collapsible: true, defaultCollapsed: true },
    { key: 'ownership_pct', label: 'Ownership Share %', type: 'number', step: '0.01', default: 1.0, half: true, helpText: 'Enter percent, e.g. 100 = 100%, 50 = 50% JV share' },
    { key: 'latitude', label: 'Latitude', type: 'number', step: '0.000001', half: true },
    { key: 'longitude', label: 'Longitude', type: 'number', step: '0.000001', half: true },
    { key: 'comment', label: 'Comment / Source Note', type: 'textarea' },
];

// Creating a property asks only what identifies it; everything else has defaults or comes later.
const NEW_PROPERTY_FIELDS = PROPERTY_FIELDS.filter(f =>
    ['name', 'property_type', 'area_unit', 'total_area', 'address_line1', 'city', 'state', 'zip_code'].includes(f.key)
);

// Census markets for pickers: "Dallas-Fort Worth-Arlington, TX · 19100"
let _cbsaOptions = null;
async function cbsaOptions() {
    if (!_cbsaOptions) _cbsaOptions = (await api.get('/cbsas?limit=1000')).map(c => `${c.title} · ${c.code}`);
    return _cbsaOptions;
}
function cbsaLabel(code, title) { return code ? `${title || ''} · ${code}` : ''; }
// Reads a picked label (or a bare code) back to a CBSA code; '' clears
function cbsaCodeFromLabel(text) {
    const t = String(text || '').trim();
    if (!t) return '';
    const m = t.match(/(\d{5})\s*$/);
    if (!m) throw new Error(`Pick a census market from the list (got "${t}")`);
    return m[1];
}
async function withCbsaPicker(fields) {
    const options = await cbsaOptions();
    return fields.map(f => f.key === 'cbsa_label' ? { ...f, suggestions: options } : f);
}

function buildSuiteFields(marketProfiles, areaUnit, simplifyUnitAssumptions = false) {
    const isUnit = areaUnit === 'unit';
    const areaFieldLabel = isUnit ? 'Unit Count' : 'Area (SF)';
    const mlaOptions = [
        { value: '', label: '— Same as space type —' },
        ...(marketProfiles || []).map(m => ({ value: m.space_type, label: `${fmt.typeLabel(m.space_type)} — ${fmt.perSf(m.market_rent_per_unit, areaUnit)}` }))
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
            key: 'market_space_type',
            label: 'Re-lease As',
            type: 'select',
            options: mlaOptions,
            half: true,
            helpText: 'Market space type used for renewal/new-tenant modeling in each valuation',
        });
    }
    fields.push({ key: 'comment', label: 'Comment / Source Note', type: 'textarea' });
    if (!simplifyUnitAssumptions) {
        fields.push({ type: 'section', label: 'Lease-Up (vacant space)', collapsible: true, defaultCollapsed: true, collapsedSummary: 'Blank = renewal/new-tenant blend' });
        fields.push({ key: 'absorption_start_date', label: 'Leasing Begins', type: 'date', half: true, helpText: 'Blank = when the space is vacant' });
        fields.push({ key: 'lease_up_months', label: 'Lease-Up Months', type: 'number', step: '1', min: 0, half: true, helpText: 'Months to new-tenant commencement. Blank = MLA downtime. Also used when a lease is reabsorbed.' });
    }
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
        { key: 'rent_basis', label: 'Rent Basis', type: 'select', options: [{ value: 'per_area', label: 'Per SF / unit × area' }, { value: 'total', label: 'Total $ amount (e.g. antenna, 0 SF)' }], default: 'per_area', half: true, helpText: 'Total: Base Rent is the whole lease amount per year (or month)' },
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
        { key: 'exclude_from_general_vacancy', label: 'Credit tenant: exclude from general vacancy and credit loss', type: 'checkbox', default: false },
        { key: 'vacancy_exclusion_ends_at_rollover', label: 'Exclude upon rollover: exclusion ends when this lease expires', type: 'checkbox', default: true, visibleWhen: v => v.exclude_from_general_vacancy },
        { type: 'section', label: 'Upon Expiration', collapsible: true, defaultCollapsed: true, collapsedSummary: (v) => fmt.typeLabel(v.upon_expiration || 'market') },
        {
            key: 'upon_expiration',
            label: 'Upon Expiration',
            type: 'select',
            default: 'market',
            half: true,
            options: [
                { value: 'market', label: 'Market (renewal probability blend)' },
                { value: 'renew', label: 'Renew' },
                { value: 'vacate', label: 'Vacate' },
                { value: 'option', label: 'Contract Option' },
                { value: 'reabsorb', label: 'Reabsorb (stays vacant)' },
            ],
        },
        { key: 'option_rent_per_unit', label: 'Option Rent', type: 'number', step: '0.01', half: true, helpText: 'Blank = market rent with the renewal adjustment', visibleWhen: v => v.upon_expiration === 'option' },
        { key: 'option_term_months', label: 'Option Term (months)', type: 'number', step: '1', half: true, helpText: 'Blank = MLA renewal term', visibleWhen: v => v.upon_expiration === 'option' },
        { key: 'option_ti_per_sf', label: 'Option TI ($/SF)', type: 'number', step: '0.01', default: 0, half: true, visibleWhen: v => v.upon_expiration === 'option' },
        { key: 'option_lc_pct', label: 'Option LC %', type: 'number', step: '0.005', default: 0, half: true, visibleWhen: v => v.upon_expiration === 'option' },
        { type: 'section', label: 'Committed Leasing Costs', collapsible: true, defaultCollapsed: true },
        { key: 'committed_ti_amount', label: 'Committed TI ($ total)', type: 'number', step: '1', default: 0, half: true, helpText: 'Unpaid contractual TI. Paid at lease start, or analysis start if the lease has begun.' },
        { key: 'committed_lc_amount', label: 'Committed LC ($ total)', type: 'number', step: '1', default: 0, half: true },
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
        if (f.key === 'recovery_type') {
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
            'upon_expiration', 'option_rent_per_unit', 'option_term_months', 'option_ti_per_sf', 'option_lc_pct',
        ]);
        const hideSections = new Set(['Recovery', 'Percentage Rent', 'Escalation', 'Renewal', 'Upon Expiration']);
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
        {
            key: 'amount_basis',
            label: 'Amount Entered As',
            type: 'select',
            default: 'total',
            half: true,
            options: [
                { value: 'total', label: 'Total $ per year' },
                { value: 'per_area', label: isMultifamily ? '$ per unit per year' : '$ per SF per year' },
            ],
            visibleWhen: v => !v.is_pct_of_egi,
        },
        { key: 'base_year_amount', label: 'Base Year Amount ($)', type: 'number', required: true, step: '0.01', half: true, helpText: 'Year 1 amount in the basis selected', visibleWhen: v => !v.is_pct_of_egi },
        { key: 'growth_rate_pct', label: 'Annual Growth Rate', type: 'number', step: '0.005', default: 0.03, half: true, helpText: 'Enter percent, e.g. 3.00 = 3%', visibleWhen: v => !v.is_pct_of_egi },
        { key: 'variable_pct', label: 'Variable with Occupancy %', type: 'number', step: '0.05', default: 0, half: true, helpText: '0 = use amount as entered. Above 0, the amount is at 100% occupancy and this share scales with occupancy.', visibleWhen: v => !v.is_pct_of_egi },
        { key: 'growth_schedule', label: 'Growth by Year (%)', type: 'rateList', helpText: 'Optional. Year 1, Year 2, … in percent; the last rate carries forward. Overrides the single rate.', visibleWhen: v => !v.is_pct_of_egi },
        { key: 'amount_schedule', label: 'Amount by Year', type: 'numberList', placeholder: 'e.g. 120000; 126000; 131000', helpText: 'Optional. Year 1, Year 2, … in the basis selected (e.g. a budget). Replaces the base amount and growth for those years; later years grow from the last amount at the growth rate.', visibleWhen: v => !v.is_pct_of_egi },
    ];
    if (!isMultifamily) {
        fields.push(
            { key: 'is_recoverable', label: 'Recoverable from tenants', type: 'checkbox', default: true },
            { key: 'is_gross_up_eligible', label: 'Gross-up eligible', type: 'checkbox', default: false },
            { key: 'gross_up_vacancy_pct', label: 'Gross-Up Occupancy %', type: 'number', step: '0.01', half: true, helpText: 'Enter percent', visibleWhen: v => v.is_gross_up_eligible },
        );
    }
    fields.push(
        { key: 'is_pct_of_egi', label: '% of EGI (instead of fixed amount)', type: 'checkbox', default: false },
        { key: 'pct_of_egi', label: 'Percentage of EGI', type: 'number', step: '0.005', asPercent: true, half: true, visibleWhen: v => v.is_pct_of_egi },
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
    { key: 'growth_schedule', label: 'Growth by Year (%)', type: 'rateList', helpText: 'Optional. Year 1, Year 2, … in percent; the last rate carries forward. Overrides the single rate.' },
    { key: 'amount_schedule', label: 'Amount by Year ($)', type: 'numberList', placeholder: 'e.g. 200000; 210000; 225000', helpText: 'Optional. Year 1, Year 2, … in dollars. Replaces the base amount and growth for those years; later years grow from the last amount at the growth rate.' },
];

const MARKET_FIELDS = [
    { key: 'space_type', label: 'Space Type', type: 'text', required: true, helpText: 'Must match suite space types to link' },
    { key: 'description', label: 'Description', type: 'text' },
    { key: 'comment', label: 'Comment / Source Note', type: 'textarea' },
    { key: 'market_rent_per_unit', label: 'Market Rent ($/SF/yr)', type: 'number', required: true, step: '0.01', half: true },
    { key: 'rent_basis', label: 'Rent Basis', type: 'select', options: [{ value: 'per_area', label: 'Per SF / unit × area' }, { value: 'total', label: 'Total $ amount (e.g. antenna, 0 SF)' }], default: 'per_area', half: true, helpText: 'Total: Market Rent, TI and LC $/SF are the whole space\'s $ amounts' },
    { key: 'rent_growth_rate_pct', label: 'Rent Growth Rate', type: 'number', step: '0.005', default: 0.03, half: true, helpText: 'Enter percent' },
    { key: 'rent_growth_schedule', label: 'Rent Growth by Year (%)', type: 'rateList', helpText: 'Optional. Year 1, Year 2, … in percent; the last rate carries forward. Overrides the single rate.' },
    { type: 'section', label: 'New Tenant Assumptions' },
    { key: 'new_lease_term_months', label: 'Lease Term (months)', type: 'number', step: '1', default: 60, half: true },
    { key: 'new_tenant_ti_per_sf', label: 'TI ($/SF)', type: 'number', step: '0.01', default: 0, half: true },
    { key: 'new_tenant_lc_pct', label: 'Leasing Commission %', type: 'number', step: '0.005', default: 0.06, half: true, helpText: 'Enter percent' },
    { key: 'new_tenant_lc_pct_by_lease_year', label: 'LC % by Lease Year', type: 'rateList', helpText: 'Optional. Percent of each lease year\'s rent, year 1 = the first 12 months of the lease (e.g. 6, 6, 6, 6, 6, 3 = 6% of years 1-5, 3% after); the last rate carries forward. Replaces the single %.' },
    { key: 'new_tenant_lc_per_sf', label: 'Leasing Commission ($/SF)', type: 'number', step: '0.01', default: 0, half: true, helpText: 'Added to the % of lease rent' },
    { key: 'new_tenant_free_rent_months', label: 'Free Rent (months)', type: 'number', step: '1', default: 0, half: true },
    { key: 'downtime_months', label: 'Downtime (months)', type: 'number', step: '1', default: 3, half: true },
    { key: 'new_free_rent_schedule', label: 'Free Rent by Year (months)', type: 'numberList', helpText: 'Optional. By the analysis year the new lease starts. Year 1, Year 2, … ; the last value carries forward. Overrides the single value.' },
    { key: 'downtime_schedule', label: 'Downtime by Year (months)', type: 'numberList', helpText: 'Optional. Whole months, by the analysis year the lease expires. Year 1, Year 2, … ; the last value carries forward. Overrides the single value.' },
    { type: 'section', label: 'Renewal Assumptions' },
    { key: 'renewal_probability', label: 'Renewal Probability', type: 'number', step: '0.05', default: 0.65, half: true, helpText: 'Enter percent' },
    { key: 'renewal_lease_term_months', label: 'Renewal Term (months)', type: 'number', step: '1', default: 60, half: true },
    { key: 'renewal_ti_per_sf', label: 'Renewal TI ($/SF)', type: 'number', step: '0.01', default: 0, half: true },
    { key: 'renewal_lc_pct', label: 'Renewal LC %', type: 'number', step: '0.005', default: 0.03, half: true, helpText: 'Enter percent' },
    { key: 'renewal_lc_per_sf', label: 'Renewal LC ($/SF)', type: 'number', step: '0.01', default: 0, half: true, helpText: 'Added to the % of lease rent' },
    { key: 'renewal_lc_pct_by_lease_year', label: 'Renewal LC % by Lease Year', type: 'rateList', helpText: 'Optional. Percent of each lease year\'s rent, year 1 = the first 12 months of the renewal; the last rate carries forward. Replaces the single %.' },
    { key: 'renewal_free_rent_months', label: 'Renewal Free Rent (months)', type: 'number', step: '1', default: 0, half: true },
    { key: 'renewal_rent_adjustment_pct', label: 'Renewal Rent Adjustment', type: 'number', step: '0.01', default: 0, half: true, helpText: 'e.g. 5.00 = 5% above market' },
    { key: 'renewal_rent_rule', label: 'Renewal Rent', type: 'select', default: 'market', half: true, options: [
        { value: 'market', label: 'Market' },
        { value: 'greater_of_prior', label: 'Greater of market or prior rent' },
        { value: 'lesser_of_prior', label: 'Lesser of market or prior rent' },
    ], helpText: 'Prior rent = the expiring lease\'s rent in its last month (steps and escalations included). Compared with market rent after the renewal adjustment; new tenants always pay market.' },
    { key: 'renewal_probability_schedule', label: 'Renewal Probability by Year (%)', type: 'rateList', helpText: 'Optional. By the analysis year the lease expires. Year 1, Year 2, … ; the last value carries forward. Overrides the single value.' },
    { key: 'renewal_free_rent_schedule', label: 'Renewal Free Rent by Year (months)', type: 'numberList', helpText: 'Optional. By the analysis year the renewal starts. Year 1, Year 2, … ; the last value carries forward. Overrides the single value.' },
    { key: 'leasing_cost_growth_rate', label: 'Leasing Cost Growth', type: 'number', step: '0.005', default: 0, half: true, helpText: 'Grows TI and LC $/SF each year to the year a lease starts.' },
    { key: 'leasing_cost_growth_schedule', label: 'Leasing Cost Growth by Year (%)', type: 'rateList', helpText: 'Optional. Year 1, Year 2, … in percent; the last rate carries forward. Overrides the single rate.' },
    { key: 'rollover_method', label: 'Rollover Method', type: 'select', default: 'probability_tree', half: true, options: [
        { value: 'probability_tree', label: 'Weighted branches' },
        { value: 'blended', label: 'Blended lease (published DCF software)' },
    ], helpText: 'Weighted branches: renewal and new tenant modeled separately. Blended: one lease with probability-weighted downtime (whole months), rent, free rent, TI and LC.' },
    { key: 'lease_escalation_pct', label: 'Market Lease Escalation', type: 'number', step: '0.005', half: true, helpText: 'Annual increase on renewal and new leases. Blank = market rent growth when the lease starts.' },
    { key: 'lease_escalation_per_unit', label: 'Market Lease Escalation ($/SF/yr)', type: 'number', step: '0.01', half: true, asPercent: false, helpText: 'Fixed annual increase instead of a %, e.g. 0.50 = $0.50/SF each year. Leave the % blank when set.' },
    { key: 'lc_includes_escalations', label: 'Leasing commissions include rent escalations', type: 'checkbox', default: true },
    { key: 'lease_rent_steps', label: 'Market Lease Rent Steps', type: 'stepList', helpText: 'Optional. Lease month: percent increase, on top of the annual escalation. e.g. 61: 10.00 = up 10% from month 61.' },
    { type: 'section', label: 'Vacancy & Credit' },
    { key: 'general_vacancy_pct', label: 'General Vacancy %', type: 'number', step: '0.005', default: 0.05, half: true, helpText: 'Enter percent' },
    { key: 'credit_loss_pct', label: 'Credit Loss %', type: 'number', step: '0.005', default: 0.01, half: true, helpText: 'Enter percent' },
    { key: 'general_vacancy_schedule', label: 'General Vacancy by Year (%)', type: 'rateList', helpText: 'Optional. Year 1, Year 2, … in percent; the last rate carries forward. Overrides the single rate.' },
    { key: 'credit_loss_schedule', label: 'Credit Loss by Year (%)', type: 'rateList', helpText: 'Optional. Year 1, Year 2, … in percent; the last rate carries forward. Overrides the single rate.' },
    { key: 'exclude_from_general_vacancy', label: 'Exclude leases in suites using this profile from general vacancy and credit loss', type: 'checkbox', default: false },
];

const CONCESSION_TIMING_OPTIONS = [
    { value: 'blended', label: 'Blended' },
    { value: 'timed', label: 'Timed by Year' },
];

function buildMarketFields(areaUnit, includeSpaceType = true, otherProfiles = [], recoveryStructures = []) {
    const isUnit = areaUnit === 'unit';
    if (!isUnit) {
        const recovery = [
            { type: 'section', label: 'Expense Recoveries' },
            {
                key: 'recovery_structure_id',
                label: 'Recovery Structure',
                tip: 'Recovery template for every market lease under this profile (renewals, new tenants, vacant space leasing up). Blank keeps the expiring lease\'s recovery type and pro rata share without its caps or stop; never-leased space is NNN.',
                type: 'select',
                default: '',
                options: [{ value: '', label: '— Same as expiring lease —' },
                    ...recoveryStructures.map(rs => ({ value: rs.id, label: rs.name }))],
                helpText: 'Recovery terms for renewals, new tenants and vacant space leasing up under this profile. '
                    + 'Blank: each market lease keeps the expiring lease\'s recovery type, without its caps; '
                    + 'space never leased is NNN. Templates live on the Recoveries tab.',
            },
        ];
        const base = includeSpaceType ? MARKET_FIELDS : MARKET_FIELDS.filter(f => f.key !== 'space_type');
        if (!otherProfiles.length) return [...base, ...recovery];
        return [...base, {
            key: 'next_profile_id',
            label: 'Upon Expiration Use MLA',
            type: 'select',
            default: '',
            options: [{ value: '', label: 'This profile (no chaining)' },
                ...otherProfiles.map(p => ({ value: p.id, label: p.description || fmt.typeLabel(p.space_type) }))],
            helpText: 'MLA chaining: speculative leases under this profile roll to the selected profile when they expire.',
        }, ...recovery];
    }

    const unitFields = [
        { key: 'description', label: 'Description', type: 'text' },
        { key: 'comment', label: 'Comment / Source Note', type: 'textarea' },
        { key: 'market_rent_per_unit', label: 'Market Rent ($/Unit/mo)', type: 'number', required: true, step: '0.01', half: true },
        { key: 'rent_growth_rate_pct', label: 'Rent Growth Rate', type: 'number', step: '0.005', default: 0.03, half: true, helpText: 'Enter percent' },
        { key: 'rent_growth_schedule', label: 'Rent Growth by Year (%)', type: 'rateList', helpText: 'Optional. Year 1, Year 2, … in percent; the last rate carries forward. Overrides the single rate.' },
        { key: 'general_vacancy_pct', label: 'General Vacancy %', type: 'number', step: '0.005', default: 0.05, half: true, helpText: 'Enter percent' },
        { key: 'credit_loss_pct', label: 'Credit Loss %', type: 'number', step: '0.005', default: 0.01, half: true, helpText: 'Enter percent' },
        { key: 'general_vacancy_schedule', label: 'General Vacancy by Year (%)', type: 'rateList', helpText: 'Optional. Year 1, Year 2, … in percent; the last rate carries forward. Overrides the single rate.' },
        { key: 'credit_loss_schedule', label: 'Credit Loss by Year (%)', type: 'rateList', helpText: 'Optional. Year 1, Year 2, … in percent; the last rate carries forward. Overrides the single rate.' },
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

// Market profile single value -> the by-year schedule that overrides it when set
const MARKET_SCALAR_SCHEDULES = {
    rent_growth_rate_pct: 'rent_growth_schedule',
    general_vacancy_pct: 'general_vacancy_schedule',
    credit_loss_pct: 'credit_loss_schedule',
    renewal_probability: 'renewal_probability_schedule',
    new_tenant_free_rent_months: 'new_free_rent_schedule',
    renewal_free_rent_months: 'renewal_free_rent_schedule',
    downtime_months: 'downtime_schedule',
    new_tenant_lc_pct: 'new_tenant_lc_pct_by_lease_year',
    renewal_lc_pct: 'renewal_lc_pct_by_lease_year',
};

// " (by year)" after a profile value that a by-year schedule overrides
function byYearNote(p, key) {
    return (p[MARKET_SCALAR_SCHEDULES[key]] || []).length ? ' <span style="color:var(--text-tertiary);font-size:.8em">(by year)</span>' : '';
}

// `original`: the stored record a row edits, so a cell the user blanked is sent as null (clears it)
function buildPayloadFromBulkRow(row, columns, original = null) {
    const payload = {};
    (columns || []).forEach((col) => {
        if (!col || !col.key) return;
        if (col.type === 'checkbox') {
            payload[col.key] = !!row[col.key];
            return;
        }
        const v = row[col.key];
        if (v == null || v === '') {
            if (col.sendBlank) payload[col.key] = '';  // blank clears the stored value
            else if (original && original[col.key] != null && original[col.key] !== '') payload[col.key] = null;
            return;
        }
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
        new_tenant_lc_per_sf: 0,
        new_tenant_free_rent_months: 0,
        downtime_months: areaUnit === 'unit' ? 1 : 3,
        renewal_probability: areaUnit === 'unit' ? 0.70 : 0.65,
        renewal_lease_term_months: 60,
        renewal_ti_per_sf: 0,
        renewal_lc_pct: 0.03,
        renewal_lc_per_sf: 0,
        renewal_free_rent_months: 0,
        renewal_rent_adjustment_pct: 0,
        leasing_cost_growth_rate: 0,
        rollover_method: 'probability_tree',
        lease_escalation_pct: null,
        lc_includes_escalations: true,
        lease_rent_steps: [],
        exclude_from_general_vacancy: false,
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

async function openMarketAssumptionWorkspace(valuationId, property, marketProfiles, onSaved = () => propertyView({ id: property.id })) {
    const areaUnit = property.area_unit || 'sf';
    const isUnit = areaUnit === 'unit';
    const recoveryStructures = isUnit ? [] : await api.get(`/valuations/${valuationId}/recovery-structures`);
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
        ...(isUnit ? [] : [{
            key: 'recovery_structure_id', label: 'Recovery Structure', type: 'select', default: '', sendBlank: true, tip: 'Recovery template for every market lease under this profile (renewals, new tenants, vacant space leasing up). Blank keeps the expiring lease\'s recovery type and pro rata share without its caps or stop; never-leased space is NNN.',
            options: [{ value: '', label: 'Same as expiring lease' }, ...recoveryStructures.map(rs => ({ value: rs.id, label: rs.name }))],
        }]),
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
            const deleteOps = uniqueDeletedIds.map((id) => api.del(`/valuations/${valuationId}/market-profiles/${id}`));
            const upsertOps = finalRows.map((row) => {
                const payload = buildPayloadFromBulkRow(row, columns,
                    row.id ? (marketProfiles || []).find(p => p.id === row.id) : null);
                const spaceType = String(payload.space_type || '').trim();
                delete payload.space_type;
                if (row.id) {
                    // Changing a single value replaces its by-year schedule, which would otherwise win
                    const before = (marketProfiles || []).find(p => p.id === row.id) || {};
                    Object.entries(MARKET_SCALAR_SCHEDULES).forEach(([key, sched]) => {
                        if (payload[key] != null && (before[sched] || []).length
                            && parseFloat(payload[key]) !== parseFloat(before[key])) payload[sched] = [];
                    });
                    return api.put(`/valuations/${valuationId}/market-profiles/${row.id}`, payload);
                }
                const createBody = { ...defaults, ...payload, space_type: spaceType };
                return api.post(`/valuations/${valuationId}/market-profiles`, createBody);
            });

            const results = await Promise.allSettled([...deleteOps, ...upsertOps]);
            const firstFailure = summarizeBulkFailures(results);
            if (firstFailure) throw new Error(firstFailure);

            overlay.remove();
            toast('Market assumptions updated', 'success');
            onSaved();
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
            const deleteOps = uniqueDeletedIds.map((id) => api.del(`${modelUrl(propertyId)}/expenses/${id}`));
            const upsertOps = finalRows.map((row) => {
                const payload = buildPayloadFromBulkRow(row, columns,
                    row.id ? (expenses || []).find(e => e.id === row.id) : null);
                if (row.id) return api.put(`${modelUrl(propertyId)}/expenses/${row.id}`, payload);
                return api.post(`${modelUrl(propertyId)}/expenses`, { ...defaults, ...payload, category: String(payload.category || '').trim() });
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
            const deleteOps = uniqueDeletedIds.map((id) => api.del(`${modelUrl(propertyId)}/other-income/${id}`));
            const upsertOps = finalRows.map((row) => {
                const payload = buildPayloadFromBulkRow(row, columns,
                    row.id ? (items || []).find(i => i.id === row.id) : null);
                if (row.id) return api.put(`${modelUrl(propertyId)}/other-income/${row.id}`, payload);
                return api.post(`${modelUrl(propertyId)}/other-income`, { ...defaults, ...payload, category: String(payload.category || '').trim() });
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

// Enter or paste a whole commercial rent roll at once: one row per suite, with its in-place lease
// if it has one (leave tenant blank for vacant space). Adds suites; existing ones are not changed.
function openRentRollPasteEditor(property) {
    const defaultSpace = { retail: 'retail', industrial: 'industrial' }[property.property_type] || 'office';
    const columns = [
        { key: 'suite_name', label: 'Suite', type: 'text', required: true, default: '' },
        { key: 'area', label: 'Area SF', type: 'number', step: '1', align: 'right', default: '' },
        { key: 'space_type', label: 'Space Type', type: 'text', default: defaultSpace },
        { key: 'tenant_name', label: 'Tenant (blank = vacant)', type: 'text', default: '', cloneOnAdd: false },
        { key: 'lease_start_date', label: 'Lease Start', type: 'date', default: '', cloneOnAdd: false },
        { key: 'lease_end_date', label: 'Lease End', type: 'date', default: '', cloneOnAdd: false },
        { key: 'base_rent_per_unit', label: 'Rent $/SF/yr', type: 'number', step: '0.01', align: 'right', default: '', cloneOnAdd: false },
        { key: 'escalation_pct_annual', label: 'Bumps %/yr', type: 'number', step: '0.005', asPercent: true, align: 'right', default: 0.03 },
        { key: 'recovery_type', label: 'Recoveries', type: 'select', options: RECOVERY_TYPES, default: 'nnn' },
    ];
    showBulkTableEditorModal({
        title: 'Add rent roll',
        columns,
        rows: [],
        addLabel: 'Add suite',
        intro: 'One row per suite. Paste straight from a spreadsheet (copy the cells, click the first cell, paste). Leave the tenant blank for vacant space.',
        onSave: async ({ rows }, overlay) => {
            const filled = rows.filter(r => r.suite_name && String(r.suite_name).trim());
            if (filled.length === 0) throw new Error('Add at least one suite.');
            const bad = filled.find(r => !(parseFloat(r.area) > 0));
            if (bad) throw new Error(`Suite ${bad.suite_name} needs an area.`);
            const partial = filled.find(r => r.tenant_name && !(r.lease_start_date && r.lease_end_date && parseFloat(r.base_rent_per_unit) > 0));
            if (partial) throw new Error(`${partial.tenant_name}: a lease needs start, end and rent.`);

            const tenants = await api.get(`${modelUrl(property.id)}/tenants`).catch(() => []);
            const tenantIdByName = Object.fromEntries(tenants.map(t => [t.name.trim().toLowerCase(), t.id]));
            const failures = [];
            for (const r of filled) {
                try {
                    const suite = await api.post(`${modelUrl(property.id)}/suites`, {
                        suite_name: String(r.suite_name).trim(), area: r.area, space_type: r.space_type || defaultSpace,
                    });
                    if (!r.tenant_name) continue;
                    const key = String(r.tenant_name).trim().toLowerCase();
                    if (!tenantIdByName[key]) {
                        tenantIdByName[key] = (await api.post(`${modelUrl(property.id)}/tenants`, { name: String(r.tenant_name).trim() })).id;
                    }
                    await api.post(`/suites/${suite.id}/leases`, {
                        suite_id: suite.id,
                        tenant_id: tenantIdByName[key],
                        lease_start_date: r.lease_start_date,
                        lease_end_date: r.lease_end_date,
                        base_rent_per_unit: r.base_rent_per_unit,
                        rent_payment_frequency: 'annual',
                        escalation_type: parseFloat(r.escalation_pct_annual) > 0 ? 'pct_annual' : 'flat',
                        escalation_pct_annual: parseFloat(r.escalation_pct_annual) > 0 ? r.escalation_pct_annual : null,
                        recovery_type: r.recovery_type || 'nnn',
                    });
                } catch (err) {
                    failures.push(`${r.suite_name}: ${err.message}`);
                }
            }
            overlay.remove();
            if (failures.length) toast(`Some rows were not saved — ${failures[0]}`, 'error');
            else toast(`${filled.length} suite${filled.length === 1 ? '' : 's'} added`, 'success');
            propertyView({ id: property.id });
        },
    });
}

function openUnitMarketQuickSetup(valuationId, property, marketProfiles, onSaved = () => propertyView({ id: property.id })) {
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
            key: `rent_${st}`, tip: FIELD_TIPS['market_rent_per_unit|Market Rent ($/Unit/mo)'],
            label: 'Market Rent ($/Unit/mo)',
            type: 'number',
            step: '0.01',
            half: true,
            default: mla ? parseFloat(mla.market_rent_per_unit) : '',
            visibleWhen: v => !v.apply_same_all,
        });
        fields.push({
            key: `growth_${st}`, tip: 'Annual growth applied to this unit type\'s market rent, by analysis year. Enter percent, e.g. 3.00 for 3%.',
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
            key: `vacancy_${st}`, tip: FIELD_TIPS['general_vacancy_pct|Vacancy %'],
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
            key: `credit_${st}`, tip: FIELD_TIPS['credit_loss_pct|Credit Loss %'],
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
            key: `renewal_${st}`, tip: FIELD_TIPS['renewal_probability|Renewal %'],
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
            key: `turnover_${st}`, tip: FIELD_TIPS['new_tenant_ti_per_sf|Turnover Cost ($/Unit/turn)'],
            label: 'Turnover Cost ($/Unit)',
            type: 'number',
            step: '0.01',
            half: true,
            default: mla ? parseFloat(mla.new_tenant_ti_per_sf) : 0,
            visibleWhen: v => !v.apply_same_all,
        });
        fields.push({
            key: `new_concession_${st}`, tip: FIELD_TIPS['new_tenant_free_rent_months|New Lease Concession (months)'],
            label: 'New Lease Concession (months)',
            type: 'number',
            step: '1',
            half: true,
            default: mla ? parseFloat(mla.new_tenant_free_rent_months || 0) : 0,
            visibleWhen: v => !v.apply_same_all,
        });
        fields.push({
            key: `renewal_concession_${st}`, tip: FIELD_TIPS['renewal_free_rent_months|Renewal Concession (months)'],
            label: 'Renewal Concession (months)',
            type: 'number',
            step: '1',
            half: true,
            default: mla ? parseFloat(mla.renewal_free_rent_months || 0) : 0,
            visibleWhen: v => !v.apply_same_all,
        });
        fields.push({
            key: `timing_mode_${st}`, tip: FIELD_TIPS['concession_timing_mode|Concession Timing'],
            label: 'Concession Timing',
            type: 'select',
            options: CONCESSION_TIMING_OPTIONS,
            half: true,
            default: mla ? (mla.concession_timing_mode || 'blended') : 'blended',
            visibleWhen: v => !v.apply_same_all,
        });
        fields.push({
            key: `c_y1_${st}`, tip: 'Months of free rent applied in analysis Year 1 when Concession Timing is Timed by Year.',
            label: 'Year 1 Concession (months)',
            type: 'number',
            step: '0.25',
            half: true,
            default: mla && mla.concession_year1_months != null ? parseFloat(mla.concession_year1_months) : '',
            visibleWhen: v => !v.apply_same_all && v[`timing_mode_${st}`] === 'timed',
        });
        fields.push({
            key: `c_y2_${st}`, tip: 'Months of free rent applied in analysis Year 2 when Concession Timing is Timed by Year.',
            label: 'Year 2 Concession (months)',
            type: 'number',
            step: '0.25',
            half: true,
            default: mla && mla.concession_year2_months != null ? parseFloat(mla.concession_year2_months) : '',
            visibleWhen: v => !v.apply_same_all && v[`timing_mode_${st}`] === 'timed',
        });
        fields.push({
            key: `c_y3_${st}`, tip: 'Months of free rent applied in analysis Year 3 when Concession Timing is Timed by Year.',
            label: 'Year 3 Concession (months)',
            type: 'number',
            step: '0.25',
            half: true,
            default: mla && mla.concession_year3_months != null ? parseFloat(mla.concession_year3_months) : '',
            visibleWhen: v => !v.apply_same_all && v[`timing_mode_${st}`] === 'timed',
        });
        fields.push({
            key: `c_y4_${st}`, tip: 'Months of free rent applied in analysis Year 4 when Concession Timing is Timed by Year.',
            label: 'Year 4 Concession (months)',
            type: 'number',
            step: '0.25',
            half: true,
            default: mla && mla.concession_year4_months != null ? parseFloat(mla.concession_year4_months) : '',
            visibleWhen: v => !v.apply_same_all && v[`timing_mode_${st}`] === 'timed',
        });
        fields.push({
            key: `c_y5_${st}`, tip: 'Months of free rent applied in analysis Year 5 when Concession Timing is Timed by Year.',
            label: 'Year 5 Concession (months)',
            type: 'number',
            step: '0.25',
            half: true,
            default: mla && mla.concession_year5_months != null ? parseFloat(mla.concession_year5_months) : '',
            visibleWhen: v => !v.apply_same_all && v[`timing_mode_${st}`] === 'timed',
        });
        fields.push({
            key: `c_ys_${st}`, tip: 'Months of free rent applied in Year 6 and later when Concession Timing is Timed by Year.',
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
                    await api.put(`/valuations/${valuationId}/market-profiles/${existing.id}`, body);
                } else {
                    await api.post(`/valuations/${valuationId}/market-profiles`, {
                        space_type: st,
                        ...body,
                    });
                }
            }
            overlay.remove();
            toast('Rent roll assumptions updated', 'success');
            onSaved();
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
            key: `rent_${l.id}`, tip: FIELD_TIPS['base_rent_per_unit|Rent $/Unit/mo'],
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
    const isOperatingBusiness = propertyType === 'marina' || propertyType === 'seniors_housing';
    const reservesLabel = isUnit ? 'Capital Reserves $/Unit/yr' : 'Capital Reserves $/SF/yr';
    const fields = [
        { key: 'name', label: 'Valuation Name', type: 'text', required: true, helpText: 'e.g. "Base case" or "Downside: 7% exit cap"' },
        { key: 'analysis_start_date_override', label: 'Analysis Start', type: 'date', half: true },
        { key: 'hold_years', label: 'Hold Period (years)', type: 'number', step: '1', min: 1, max: 30, required: true, half: true },
        { key: 'discount_rate', label: 'Discount Rate', type: 'number', required: true, step: '0.0025', default: 0.08, half: true },
        { key: 'exit_cap_rate', label: 'Exit Cap Rate', type: 'number', required: true, step: '0.0025', default: 0.065, half: true },
        { key: 'purchase_price', label: 'Purchase Price ($)', type: 'number', step: '1', half: true, helpText: 'Optional. Needed for a meaningful IRR and equity multiple.' },

        { type: 'section', label: 'Sale & exit', collapsible: true, defaultCollapsed: true,
          collapsedSummary: (v) => `${fmt.pct(v.exit_costs_pct ?? 0.02, 1)} costs · ${v.exit_cap_applied_to_year === -1 || v.exit_cap_applied_to_year == null ? 'forward-year NOI' : 'year ' + v.exit_cap_applied_to_year + ' NOI'}` },
        { key: 'exit_costs_pct', label: 'Exit Costs %', type: 'number', step: '0.005', default: 0.02, half: true, helpText: 'Enter percent' },
        { key: 'exit_cap_applied_to_year', label: 'Exit Cap Applied to Year', type: 'number', step: '1', default: -1, half: true, helpText: '-1 = forward year (Hold + 1 NOI)' },
        {
            key: 'transfer_tax_preset', label: 'Transfer Tax', type: 'select', default: 'none', half: true,
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
        { key: 'transfer_tax_custom_rate', label: 'Custom Transfer Tax %', type: 'number', step: '0.0025', half: true,
          visibleWhen: v => v.transfer_tax_preset === 'custom_rate' },
        {
            key: 'terminal_timing', label: 'Sale Proceeds Timing', type: 'select', default: 'end_of_period', half: true,
            options: [
                { value: 'end_of_period', label: 'End of hold (recommended)' },
                { value: 'mid_year', label: 'Mid-year (legacy parity)' },
            ],
        },
        { key: 'exit_deduct_forward_capital', label: 'Deduct Year N+1 TI/LC/capex from sale', type: 'checkbox', default: false },
    ];
    if (!isUnit && !isOperatingBusiness) {
        fields.push({ key: 'exit_noi_full_occupancy', label: 'Capitalize reversion NOI adjusted for full occupancy', type: 'checkbox', default: false });
        fields.push({ key: 'exit_stabilized_vacancy_pct', label: 'Stabilized Vacancy %', type: 'number', step: '0.005', default: 0, half: true, helpText: 'General vacancy in the full-occupancy reversion NOI.', visibleWhen: v => v.exit_noi_full_occupancy });
    }

    fields.push({ type: 'section', label: 'Acquisition', collapsible: true, defaultCollapsed: true,
        collapsedSummary: (v) => v.direct_cap_rate ? `Direct cap ${fmt.pct(v.direct_cap_rate)}` : 'Costs and direct cap' });
    fields.push({ key: 'acquisition_costs_pct', label: 'Acquisition Costs %', type: 'number', step: '0.0025', default: 0, half: true, helpText: 'Enter percent of price' });
    fields.push({ key: 'direct_cap_rate', label: 'Direct Cap Rate', type: 'number', step: '0.0025', half: true, helpText: 'Applied to Year 1 NOI for a direct cap value' });

    fields.push({ type: 'section', label: 'Financing', collapsible: true, defaultCollapsed: true,
        collapsedSummary: (v) => {
            const extra = (v.additional_loans || []).length;
            if (!v.loan_amount && !extra) return 'Unlevered';
            if (!v.loan_amount) return `${extra} loan${extra > 1 ? 's' : ''}`;
            return `${fmt.currency(v.loan_amount)} loan${extra ? ` +${extra} more` : ''}`;
        } });
    fields.push({ key: 'loan_amount', label: 'Loan Amount ($)', type: 'number', step: '1', half: true });
    fields.push({ key: 'interest_rate', label: 'Interest Rate', type: 'number', step: '0.0025', half: true, helpText: 'Enter percent' });
    fields.push({ key: 'amortization_months', label: 'Amortization (months)', type: 'number', step: '1', half: true });
    fields.push({ key: 'loan_term_months', label: 'Loan Term (months)', type: 'number', step: '1', half: true });
    fields.push({ key: 'io_period_months', label: 'Interest-Only Period (months)', type: 'number', step: '1', default: 0, half: true });
    fields.push({ key: 'loan_fees_pct', label: 'Loan Fees %', type: 'number', step: '0.0025', default: 0, half: true, helpText: 'Enter percent of loan amount' });
    if (!isOperatingBusiness) fields.push({ key: 'additional_loans', label: 'Additional Loans', type: 'loanList',
        placeholder: 'Mezz; 1,000,000; 10; ; 60; 60; 1',
        helpText: 'Optional: second mortgage, mezzanine. One per line: label; amount; rate %; amortization months; term months; interest-only months; fees %. Blank amortization = 360, blank term = through the sale. Funded at close; debt service, balance and fees add to the loan above.' });

    fields.push({ type: 'section', label: 'Reserves, inflation & conventions', collapsible: true, defaultCollapsed: true,
        collapsedSummary: (v) => `${v.use_mid_year_convention ? 'Mid-year' : 'End-of-year'} discounting · CPI ${v.cpi_rate != null && v.cpi_rate !== '' ? fmt.pct(v.cpi_rate, 1) : '2.5%'}` });
    fields.push({ key: 'capital_reserves_per_unit', label: reservesLabel, type: 'number', step: '0.05', default: 0.25, half: true });
    fields.push({ key: 'capital_reserves_growth_rate', label: 'Capital Reserves Growth', type: 'number', step: '0.005', default: 0, half: true, helpText: 'Annual growth from Year 1.' });
    fields.push({ key: 'use_mid_year_convention', label: 'Use mid-year discounting', type: 'checkbox', default: false });
    fields.push({ key: 'cpi_rate', label: 'CPI Rate', type: 'number', step: '0.0025', half: true, helpText: 'For CPI-escalated leases. Blank = 2.5%.' });
    fields.push({ key: 'cpi_schedule', label: 'CPI by Year (%)', type: 'rateList', helpText: 'Optional. Year 1, Year 2, … in percent; the last rate carries forward. Overrides the single rate.' });
    if (!isUnit && !isOperatingBusiness) {
        fields.push({ key: 'reduce_general_vacancy_by_downtime', label: 'Reduce general vacancy by absorption & turnover vacancy', type: 'checkbox', default: false });
        fields.push({ key: 'vacancy_on_gross_revenue', label: 'Apply general vacancy & credit loss to gross revenue (rent + recoveries + other income)', type: 'checkbox', default: false });
        fields.push({ key: 'calendar_year_recoveries', label: 'Bill recoveries on calendar years (expenses inflate on fiscal years)', type: 'checkbox', default: false });
        fields.push({ key: 'apply_stabilized_gross_up', label: 'Apply stabilized gross-up', type: 'checkbox', default: true });
        fields.push({ key: 'stabilized_occupancy_pct', label: 'Stabilized Occupancy %', type: 'number', step: '0.005', default: 0.95, half: true,
            helpText: 'Optional global gross-up target. Leave blank to use each expense line target.', visibleWhen: v => v.apply_stabilized_gross_up });
    }

    fields.push({ type: 'section', label: 'Basis of value & notes', collapsible: true, defaultCollapsed: true,
        collapsedSummary: (v) => fmt.typeLabel(v.basis_of_value || 'market_value') });
    fields.push({
        key: 'basis_of_value', label: 'Basis of Value', type: 'select', default: 'market_value', half: true,
        options: [
            { value: 'market_value', label: 'Market Value' },
            { value: 'investment_value', label: 'Investment Value' },
            { value: 'lending_stress', label: 'Lending / Stress Value' },
        ],
    });
    fields.push({ key: 'intended_use', label: 'Intended Use', type: 'text', half: true, helpText: 'Examples: acquisition underwriting, financial reporting, or loan underwriting.' });
    fields.push({
        key: 'risk_treatment', label: 'Risk Treatment', type: 'select', default: 'deterministic', half: true,
        options: [
            { value: 'deterministic', label: 'Deterministic' },
            { value: 'scenario_weighted', label: 'Scenario-weighted expected cash flow' },
            { value: 'stress', label: 'Stress case' },
        ],
    });
    fields.push({
        key: 'cash_flow_basis', label: 'Cash Flow Basis', type: 'select', default: 'nominal', half: true,
        options: [{ value: 'nominal', label: 'Nominal' }, { value: 'real', label: 'Real' }],
    });
    fields.push({
        key: 'discount_rate_basis', label: 'Discount Rate Basis', type: 'select', default: 'nominal', half: true,
        options: [{ value: 'nominal', label: 'Nominal' }, { value: 'real', label: 'Real' }],
        helpText: 'Must match the cash flow basis.',
    });
    fields.push({ key: 'description', label: 'Description', type: 'text' });
    fields.push({ key: 'comment', label: 'Comment / Source Note', type: 'textarea' });
    return fields;
}

// New or edit valuation. The hold period and start date belong to the valuation; the property's
// values are only defaults, so an unchanged default is stored as "inherit" (null).
async function showValuationForm({ property, valuation = null, marketProfiles = [], onSaved }) {
    const propertyYears = inheritedHoldYears(valuation, property);
    let fields = buildValuationFields(property.property_type);
    if (!valuation) {
        // New valuations start from the assumptions library's reserves when it has one
        try {
            const lib = await api.get(`/properties/${property.id}/resolved-assumptions`);
            const reserves = lib.values.capital_reserves_per_unit;
            if (reserves != null) {
                const source = (lib.sources.capital_reserves_per_unit || '').replace(/^profile:/, '');
                fields = fields.map(f => f.key === 'capital_reserves_per_unit'
                    ? { ...f, default: parseFloat(reserves), helpText: `From the assumptions library (${source}).` } : f);
            }
        } catch { /* library unavailable: keep the built-in default */ }
        const mps = marketProfiles || [];
        const avgVacancy = mps.length > 0
            ? mps.reduce((s, m) => s + parseFloat(m.general_vacancy_pct || 0.05), 0) / mps.length
            : 0.05;
        const occupancy = Math.round((1 - avgVacancy) * 10000) / 10000;
        fields = fields.map(f => f.key === 'stabilized_occupancy_pct' ? { ...f, default: occupancy } : f);
    }
    const prefill = {
        analysis_start_date_override: (valuation && valuation.analysis_start_date_override) || property.analysis_start_date,
        hold_years: effectiveHoldYears(valuation, property),
    };
    showFormModal({
        title: valuation ? 'Rates & exit' : 'New valuation',
        fields,
        wide: true,
        // Editing sends only changed fields; a new valuation is prefilled but sends everything
        ...(valuation ? { initialValues: { ...valuation, ...prefill } } : { defaults: { name: 'Base case', ...prefill } }),
        submitLabel: valuation ? 'Save' : 'Create & run',
        onSubmit: async (data, overlay) => {
            // Store the property's default hold / start as "inherit" (null) unless the valuation already pinned one
            if ('hold_years' in data) {
                const years = parseInt(data.hold_years, 10);
                const hadPeriod = valuation && valuation.analysis_period_months_override;
                data.analysis_period_months_override = (!hadPeriod && years === propertyYears) ? null : years * 12;
            }
            delete data.hold_years;
            const hadStart = valuation && valuation.analysis_start_date_override;
            if (!hadStart && data.analysis_start_date_override === property.analysis_start_date) {
                delete data.analysis_start_date_override;
            }
            const saved = valuation
                ? await api.put(`/valuations/${valuation.id}`, data)
                : await api.post(`/properties/${property.id}/valuations`, data);
            if (!valuation) {
                const submitBtn = overlay.querySelector('.btn-primary');
                if (submitBtn) submitBtn.textContent = 'Running…';
                try {
                    await api.post(`/valuations/${saved.id}/run`);
                    toast('Valuation completed', 'success');
                } catch (err) {
                    toast('Saved, but the run did not complete: ' + err.message, 'error');
                }
            } else {
                toast('Valuation saved', 'success');
            }
            overlay.remove();
            onSaved(saved);
        },
    });
}

const VALUATION_FIELDS = buildValuationFields();


const RECOVERY_STRUCTURE_FIELDS = [
    { key: 'name', label: 'Name', type: 'text', required: true },
    { key: 'description', label: 'Description', type: 'text' },
    { key: 'comment', label: 'Comment / Source Note', type: 'textarea' },
    { key: 'default_recovery_type', label: 'Default Recovery Type', type: 'select', options: RECOVERY_TYPES, default: 'nnn', half: true, helpText: 'Used for expense categories without their own override' },
    { key: 'expense_stop_per_sf', label: 'Expense Stop $/SF/yr', type: 'number', step: '0.01', half: true, visibleWhen: v => v.default_recovery_type === 'modified_gross', tip: 'Modified gross stop for every lease using this structure: tenants pay the pooled modified-gross expense $/SF above it × their SF. Annual $/SF, e.g. 11.00.', helpText: 'Tenants recover the pooled expense $/SF above this stop. Replaces a lease\'s own stop. Blank: each lease\'s own stop; market leases reset to expenses in their first year (base year).' },
];

// A list field shown as checkboxes; the value travels as a JSON array string (see recoveryPoolPayload)
function checkboxListField(key, label, options, helpText) {
    return {
        key, label, type: 'custom',
        render: (container, vals, setValue) => {
            let selected = vals[key] ?? [];
            if (typeof selected === 'string') { try { selected = JSON.parse(selected || '[]'); } catch { selected = []; } }
            // Drop ids no longer offered (a deleted suite, a renamed expense) so saving stays valid
            const chosen = new Set(selected.filter(v => options.some(o => o.value === v)));
            setValue(key, JSON.stringify([...chosen]));
            const group = document.createElement('div');
            group.className = 'form-group';
            group.innerHTML = `<label class="form-label">${escapeHtmlAttr(label)}</label>`;
            const list = document.createElement('div');
            list.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:4px 12px';
            if (!options.length) list.innerHTML = '<span class="form-help">None on this property yet.</span>';
            options.forEach(o => {
                const row = document.createElement('label');
                row.style.cssText = 'display:flex;gap:6px;align-items:center;font-size:0.87rem';
                const box = document.createElement('input');
                box.type = 'checkbox';
                box.checked = chosen.has(o.value);
                box.addEventListener('change', () => {
                    box.checked ? chosen.add(o.value) : chosen.delete(o.value);
                    setValue(key, JSON.stringify([...chosen]));
                });
                row.append(box, document.createTextNode(o.label));
                list.appendChild(row);
            });
            group.appendChild(list);
            if (helpText) group.insertAdjacentHTML('beforeend', `<div class="form-help">${escapeHtmlAttr(helpText)}</div>`);
            container.appendChild(group);
        },
    };
}

function buildRecoveryPoolFields(expenses, suites, areaUnit) {
    const categories = [...new Set(expenses.filter(e => e.is_recoverable).map(e => e.category))]
        .map(c => ({ value: c, label: fmt.typeLabel(c) }));
    const suiteOptions = suites.map(s => ({ value: s.id, label: `${s.suite_name} (${fmt.num(s.area)} ${areaUnit === 'unit' ? 'units' : 'SF'})` }));
    return [
        { key: 'name', label: 'Name', type: 'text', required: true, helpText: 'e.g. Shop CAM, Real Estate Taxes' },
        { key: 'description', label: 'Description', type: 'text' },
        checkboxListField('expense_categories', 'Expense Categories', categories,
            'Recoverable expense lines in this pool. Each line can be in one pool only; lines in no pool are shared over the whole property area.'),
        { type: 'section', label: 'Share Denominator' },
        { key: 'denominator', label: 'Denominator', type: 'select', default: 'property_area', options: [
            { value: 'property_area', label: 'Property area less excluded suites' },
            { value: 'fixed_area', label: 'Fixed area' },
            { value: 'occupied_area', label: 'Occupied area (with optional minimum)' },
        ], helpText: 'A tenant\'s share = its area ÷ this denominator. A lease\'s own Pro Rata Share still wins.' },
        { key: 'fixed_area', label: 'Fixed Denominator Area', type: 'number', step: '1', half: true,
          visibleWhen: v => v.denominator === 'fixed_area' },
        { key: 'minimum_occupancy_pct', label: 'Minimum Occupancy %', type: 'number', step: '0.5', half: true,
          visibleWhen: v => v.denominator === 'occupied_area',
          helpText: 'Enter percent. The denominator is at least this share of the included area. Occupied-area pools are not grossed up.' },
        { type: 'section', label: 'Excluded Suites (anchors, outparcels)' },
        checkboxListField('excluded_suite_ids', 'Leave out of the denominator', suiteOptions,
            'Leases in these suites recover on their own terms over the whole property area.'),
        { key: 'deduct_excluded_recoveries', label: 'Deduct what excluded suites pay from the pool before others share it', type: 'checkbox', default: true },
    ];
}

function recoveryPoolPayload(data) {
    const list = v => Array.isArray(v) ? v : (() => { try { return JSON.parse(v || '[]'); } catch { return []; } })();
    return { ...data, expense_categories: list(data.expense_categories), excluded_suite_ids: list(data.excluded_suite_ids) };
}

// Category overrides of a recovery structure, edited together in one grid
const RECOVERY_ITEM_COLUMNS = [
    { key: 'expense_category', label: 'Category', type: 'text', required: true, default: '' },
    { key: 'recovery_type', label: 'Recovery', type: 'select', options: RECOVERY_TYPES, default: 'nnn' },
    { key: 'base_year_stop_amount', label: 'Base-Year Stop $', type: 'number', step: '0.01', align: 'right' },
    { key: 'expense_stop_per_sf', label: 'Mod. Gross Stop $/SF', type: 'number', step: '0.01', align: 'right' },
    { key: 'cap_per_sf_annual', label: 'Cap $/SF', type: 'number', step: '0.01', align: 'right' },
    { key: 'cap_group', label: 'Cap Group', type: 'text' },
    { key: 'cap_growth_pct', label: 'Cap Growth %', type: 'number', step: '0.005', asPercent: true, align: 'right' },
    { key: 'floor_per_sf_annual', label: 'Floor $/SF', type: 'number', step: '0.01', align: 'right' },
    { key: 'admin_fee_pct', label: 'Admin Fee %', type: 'number', step: '0.005', asPercent: true, align: 'right' },
    { key: 'comment', label: 'Comment', type: 'text', cloneOnAdd: false },
];

// Edit a recovery structure's category overrides in one pass: add, change, remove rows
// "+ New" and "Edit overrides" beside a form's Recovery Structure select, so a template can be made
// or changed without leaving the lease or market profile being edited. Returns the wiring to run
// on the form's overlay once it is open.
function addRecoveryStructureLinks(fields, valuationId, onChanged) {
    const field = fields.find(f => f.key === 'recovery_structure_id');
    if (!field || (field.visibleWhen && !field.visibleWhen({}))) return () => {};
    field.afterLabel = '<button type="button" class="form-inline-link" data-rs-link="new">+ New</button> '
        + '<button type="button" class="form-inline-link" data-rs-link="edit">Edit overrides</button>';
    const base = `/valuations/${valuationId}/recovery-structures`;
    return (overlay) => overlay.addEventListener('click', async (e) => {
        const link = e.target.closest('[data-rs-link]');
        if (!link) return;
        e.preventDefault();
        e.stopPropagation();
        const select = overlay.querySelector('#form_recovery_structure_id');
        if (link.dataset.rsLink === 'edit') {
            if (!select?.value) { toast('Pick a recovery structure first, or click + New', 'error'); return; }
            const rs = await api.get(`${base}/${select.value}`);
            openRecoveryItemsWorkspace(`${base}/${rs.id}`, rs, onChanged);
            return;
        }
        showFormModal({
            title: 'New Recovery Structure',
            fields: RECOVERY_STRUCTURE_FIELDS,
            onSubmit: async (data, rsOverlay) => {
                const created = await api.post(base, data);
                rsOverlay.remove();
                // Kept in the field's options so the form's re-renders keep the choice
                field.options.push({ value: created.id, label: created.name });
                if (select) {
                    const o = document.createElement('option');
                    o.value = created.id;
                    o.textContent = created.name;
                    select.appendChild(o);
                    select.value = created.id;
                    select.dispatchEvent(new Event('change'));
                }
                toast('Recovery structure created and selected. Add category overrides, or close to keep the default for every expense.', 'success');
                onChanged();
                openRecoveryItemsWorkspace(`${base}/${created.id}`, created, onChanged);
            },
        });
    });
}

function openRecoveryItemsWorkspace(baseUrl, structure, onDone) {
    const blank = { expense_category: '', recovery_type: structure.default_recovery_type || 'nnn' };
    const rows = structure.items.map(item => ({ ...item }));
    if (!rows.length) rows.push({ ...blank, id: null });
    showBulkTableEditorModal({
        title: `Category overrides: ${structure.name}`,
        columns: RECOVERY_ITEM_COLUMNS,
        rows,
        addLabel: 'Add Category',
        intro: `Categories listed here replace the default (${fmt.typeLabel(structure.default_recovery_type)}) for that expense. Base-year stop applies to base year stop rows; the modified gross stop measures that category alone against it; floors do not apply to modified gross. Blank cells clear the value.`,
        onSave: async ({ rows: finalRows, deletedIds }, overlay) => {
            const kept = finalRows.filter(r => String(r.expense_category || '').trim());
            const categories = kept.map(r => String(r.expense_category).trim());
            const dup = categories.find((c, i) => categories.indexOf(c) !== i);
            if (dup) throw new Error(`${dup} is listed twice.`);
            const removed = [...new Set([...(deletedIds || []),
                ...finalRows.filter(r => r.id && !String(r.expense_category || '').trim()).map(r => r.id)])];
            const payload = (row) => Object.fromEntries(RECOVERY_ITEM_COLUMNS.map(c => {
                const v = row[c.key];
                return [c.key, v == null || v === '' ? null : (c.key === 'expense_category' ? String(v).trim() : v)];
            }));
            const results = await Promise.allSettled([
                ...removed.map(itemId => api.del(`${baseUrl}/items/${itemId}`)),
                ...kept.map(row => row.id
                    ? api.put(`${baseUrl}/items/${row.id}`, payload(row))
                    : api.post(`${baseUrl}/items`, payload(row))),
            ]);
            const failure = summarizeBulkFailures(results);
            if (failure) throw new Error(failure);
            overlay.remove();
            toast('Category overrides saved', 'success');
            onDone();
        },
    });
}

const CAPITAL_PROJECT_FIELDS = [
    { key: 'description', label: 'Description', type: 'text', required: true },
    { key: 'comment', label: 'Comment / Source Note', type: 'textarea' },
    { key: 'total_amount', label: 'Total Amount ($)', type: 'number', required: true, step: '1', half: true },
    { key: 'start_date', label: 'Start Date', type: 'date', required: true, half: true, tip: 'Month the spending starts; the total spreads evenly from here over Duration.' },
    { key: 'duration_months', label: 'Duration (months)', type: 'number', required: true, step: '1', half: true },
];

const RENT_STEP_FIELDS = [
    { key: 'effective_date', label: 'Effective Date', type: 'date', required: true, half: true },
    { key: 'rent_per_unit', label: 'Rent ($/SF/yr)', type: 'number', required: true, step: '0.01', half: true },
    { key: 'comment', label: 'Comment / Source Note', type: 'textarea' },
];

const FREE_RENT_FIELDS = [
    { key: 'start_date', label: 'Start Date', type: 'date', required: true, half: true, tip: 'First day rent is abated.' },
    { key: 'end_date', label: 'End Date', type: 'date', required: true, half: true, tip: 'Last day rent is abated. Partial months are prorated by day count.' },
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
    { key: 'expense_stop_per_sf', label: 'Expense Stop $/SF/yr', type: 'number', step: '0.01', half: true, visibleWhen: v => v.recovery_type === 'modified_gross', tip: 'This category alone is tested: the tenant pays (category expense per SF − stop) × its SF when positive. Annual $/SF, e.g. 4.50. Blank uses the lease\'s or structure\'s stop, applied to this category alone.' },
    { key: 'floor_per_sf_annual', label: 'Floor $/SF/yr', type: 'number', step: '0.01', half: true, visibleWhen: v => v.recovery_type !== 'modified_gross' },
    { key: 'admin_fee_pct', label: 'Admin Fee %', type: 'number', step: '0.005', half: true, helpText: 'Enter percent, e.g. 5.00 = 5%' },
    { key: 'cap_group', label: 'Cap Group', type: 'text', half: true, helpText: 'Categories with the same group share one cap on their combined recovery.' },
    { key: 'cap_growth_pct', label: 'Cap Growth %/yr', type: 'number', step: '0.005', half: true, helpText: 'Recovery grows at most this much a year from the lease start year (an exercised option keeps the original lease start).' },
    { key: 'comment', label: 'Comment / Source Note', type: 'textarea' },
];


// ─── Rent Schedule Builder ────────────────────────────────

// With `host`, renders into that element (a lease editor tab) instead of its own modal
async function showRentScheduleBuilder(leaseId, propertyId, areaUnit = 'sf', { host = null, onChange = () => {} } = {}) {
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
            ${host ? '' : `<div class="modal wide">
                <div class="modal-title">${tenantName} — Rent Schedule</div>`}
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

                ${host ? '' : `<div class="modal-actions">
                    <button class="btn btn-secondary" id="closeSchedule">Done</button>
                </div>
            </div>`}`;

        if (host) overlay = host;
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.className = 'modal-overlay';
            document.body.appendChild(overlay);
        }
        overlay.innerHTML = content;

        // Close
        if (!host) {
            const closeBtn = overlay.querySelector('#closeSchedule');
            closeBtn.onclick = () => { overlay.remove(); if (propertyId) propertyView({ id: propertyId }); };
            overlay.addEventListener('click', (e) => { if (e.target === overlay) { overlay.remove(); if (propertyId) propertyView({ id: propertyId }); } }, { once: true });
        }

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
                onChange();
                render();
            } catch (err) {
                toast('Error: ' + err.message, 'error');
            }
        };

        // Delete steps
        overlay.querySelectorAll('[data-del-step]').forEach(btn => {
            btn.onclick = async () => {
                try {
                    await api.del(`/leases/${leaseId}/rent-steps/${btn.dataset.delStep}`);
                } catch (err) { toast('Error: ' + err.message, 'error'); return; }
                toast('Rent step removed', 'success');
                onChange();
                render();
            };
        });
    }

    render();
}


// ─── Lease Detail Modal (sub-resources) ──────────────────

// With `host`, renders one `section` ('free-rent' or 'recoveries') into that element (a lease editor tab)
async function showLeaseDetailModal(leaseId, propertyId, marketProfiles, propertyType = '', areaUnit = 'sf', { host = null, section = null, onChange = () => {} } = {}) {
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
    const show = (name) => !section || section === name;

    async function render() {
        const fresh = await api.get(`/leases/${leaseId}`);
        const content = `
            ${host ? '' : `<div class="modal wide" style="width:700px">
                <div class="modal-title">${tenantName} — Lease Details</div>
                <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:20px">
                    <div><div class="info-item-label">Lease Type</div><div class="info-item-value">${fmt.typeLabel(fresh.lease_type)}</div></div>
                    <div><div class="info-item-label">Term</div><div class="info-item-value">${fmt.date(fresh.lease_start_date)} – ${fmt.date(fresh.lease_end_date)}</div></div>
                    <div><div class="info-item-label">Base Rent</div><div class="info-item-value" style="color:var(--accent)">${fmt.perSf(fresh.base_rent_per_unit)}</div></div>
                    ${isMultifamilyLease ? '' : `<div><div class="info-item-label">Escalation</div><div class="info-item-value">${fmt.typeLabel(fresh.escalation_type)}${fresh.escalation_pct_annual ? ' (' + fmt.pct(fresh.escalation_pct_annual) + ')' : ''}</div></div>`}
                    ${isMultifamilyLease ? '' : `<div><div class="info-item-label">Recovery</div><div class="info-item-value">${fmt.typeLabel(fresh.recovery_type)}</div></div>`}
                </div>`}

                <!-- Effective Assumptions (resolved values the engine will use) -->
                ${matchedMarket && show('recoveries') ? `
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
                ${show('schedule') ? `<div class="form-section" style="display:flex;justify-content:space-between;align-items:center">
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
                </div>` : ''}

                <!-- Free Rent Periods -->
                ${show('free-rent') ? `<div class="form-section" style="display:flex;justify-content:space-between;align-items:center">
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
                </div>` : ''}

                <!-- Expense Recovery Overrides -->
                ${isMultifamilyLease || !show('recoveries') ? '' : `<div class="form-section" style="display:flex;justify-content:space-between;align-items:center">
                    <span>Expense Recovery Overrides (${fresh.expense_recovery_overrides.length})</span>
                    <button class="btn btn-secondary btn-sm" id="addRecoveryOverride">${icons.plus} Add</button>
                </div>
                <div class="data-table-wrap" style="margin-bottom:8px" id="recoveryTable">
                    ${fresh.expense_recovery_overrides.length === 0
                        ? '<div style="color:var(--text-tertiary);font-size:0.87rem;padding:12px 0">No per-category overrides. Using lease-level recovery type for all expenses.</div>'
                        : `<table class="data-table" style="margin-bottom:0">
                            <thead><tr><th>Category</th><th>Recovery</th><th class="right">Cap/SF</th><th class="right">Floor/SF</th><th class="right">Stop/SF</th><th class="right">Admin %</th><th></th></tr></thead>
                            <tbody>${fresh.expense_recovery_overrides.map(ero => `<tr>
                                <td class="tenant-name">${fmt.typeLabel(ero.expense_category)}</td>
                                <td>${fmt.typeLabel(ero.recovery_type)}</td>
                                <td class="mono right">${ero.cap_per_sf_annual ? fmt.perSf(ero.cap_per_sf_annual) : '—'}</td>
                                <td class="mono right">${ero.floor_per_sf_annual && ero.recovery_type !== 'modified_gross' ? fmt.perSf(ero.floor_per_sf_annual) : '—'}</td>
                                <td class="mono right">${(ero.expense_stop_per_sf ?? ero.floor_per_sf_annual) != null && ero.recovery_type === 'modified_gross' ? fmt.perSf(ero.expense_stop_per_sf ?? ero.floor_per_sf_annual) : '—'}</td>
                                <td class="mono right">${ero.admin_fee_pct ? fmt.pct(ero.admin_fee_pct) : '—'}</td>
                                <td style="white-space:nowrap"><button class="btn-icon" data-edit-ero="${ero.id}" title="Edit">${icons.edit}</button><button class="btn-icon danger" data-del-ero="${ero.id}" title="Remove">${icons.trash}</button></td>
                            </tr>`).join('')}</tbody>
                        </table>`
                    }
                </div>`}

                ${host ? '' : `<div class="modal-actions">
                    <button class="btn btn-secondary" id="closeDetail">Close</button>
                </div>
            </div>`}`;

        if (host) overlay = host;
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.className = 'modal-overlay';
            document.body.appendChild(overlay);
        }
        overlay.innerHTML = content;

        // Close handlers
        if (!host) {
            overlay.querySelector('#closeDetail').onclick = () => { overlay.remove(); if (propertyId) propertyView({ id: propertyId }); };
            overlay.addEventListener('click', (e) => { if (e.target === overlay) { overlay.remove(); if (propertyId) propertyView({ id: propertyId }); } }, { once: true });
        }

        // Open Rent Schedule Builder
        const openScheduleBtn = overlay.querySelector('#openRentSchedule');
        if (openScheduleBtn) openScheduleBtn.onclick = () => {
            overlay.remove();
            overlay = null;
            showRentScheduleBuilder(leaseId, propertyId, areaUnit);
        };

        // Add Free Rent Period
        const addFreeRentBtn = overlay.querySelector('#addFreeRent');
        if (addFreeRentBtn) addFreeRentBtn.onclick = () => {
            showFormModal({
                title: 'Add Free Rent Period',
                fields: FREE_RENT_FIELDS,
                onSubmit: async (data, formOverlay) => {
                    await api.post(`/leases/${leaseId}/free-rent-periods`, data);
                    formOverlay.remove();
                    toast('Free rent period added', 'success');
                    onChange();
                    render();
                }
            });
        };

        // Delete Free Rent Period
        overlay.querySelectorAll('[data-del-frp]').forEach(btn => {
            btn.onclick = async (e) => {
                e.stopPropagation();
                const frpId = btn.dataset.delFrp;
                try {
                    await api.del(`/leases/${leaseId}/free-rent-periods/${frpId}`);
                } catch (err) { toast('Error: ' + err.message, 'error'); return; }
                toast('Free rent period removed', 'success');
                onChange();
                render();
            };
        });

        // Add Expense Recovery Override
        const addOverrideBtn = overlay.querySelector('#addRecoveryOverride');
        if (addOverrideBtn) addOverrideBtn.onclick = () => {
            showFormModal({
                title: 'Add Expense Recovery Override',
                fields: EXPENSE_RECOVERY_OVERRIDE_FIELDS,
                onSubmit: async (data, formOverlay) => {
                    await api.post(`/leases/${leaseId}/expense-recoveries`, data);
                    formOverlay.remove();
                    toast('Recovery override added', 'success');
                    onChange();
                    render();
                }
            });
        };

        // Edit Expense Recovery Override: the form holds the whole override, so save it as a
        // replacement (add the edited one, then remove the old) so cleared values clear too
        overlay.querySelectorAll('[data-edit-ero]').forEach(btn => {
            btn.onclick = (e) => {
                e.stopPropagation();
                const ero = fresh.expense_recovery_overrides.find(o => o.id === btn.dataset.editEro);
                showFormModal({
                    title: 'Edit Expense Recovery Override',
                    fields: EXPENSE_RECOVERY_OVERRIDE_FIELDS,
                    initialValues: ero,
                    onSubmit: async (data, formOverlay) => {
                        const merged = { ...ero, ...data };
                        const body = Object.fromEntries(EXPENSE_RECOVERY_OVERRIDE_FIELDS.map(f => [f.key,
                            f.visibleWhen && !f.visibleWhen(merged) ? null : (merged[f.key] ?? null)]));
                        const added = await api.post(`/leases/${leaseId}/expense-recoveries`, body);
                        try {
                            await api.del(`/leases/${leaseId}/expense-recoveries/${ero.id}`);
                        } catch (err) {
                            // Old one still there: drop the new one so the category is not recovered twice
                            await api.del(`/leases/${leaseId}/expense-recoveries/${added.id}`).catch(() => {});
                            throw err;
                        }
                        formOverlay.remove();
                        toast('Recovery override updated', 'success');
                        onChange();
                        render();
                    }
                });
            };
        });

        // Delete Expense Recovery Override
        overlay.querySelectorAll('[data-del-ero]').forEach(btn => {
            btn.onclick = async (e) => {
                e.stopPropagation();
                const eroId = btn.dataset.delEro;
                try {
                    await api.del(`/leases/${leaseId}/expense-recoveries/${eroId}`);
                } catch (err) { toast('Error: ' + err.message, 'error'); return; }
                toast('Recovery override removed', 'success');
                onChange();
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
    setBreadcrumb([]);

    let rows;
    try {
        rows = await api.get('/properties/summary');
    } catch {
        $app().innerHTML = `
            <div class="empty-state">
                <h3>Cannot connect to API</h3>
                <p>Make sure the server is running: <code style="color:var(--accent)">uvicorn src.main:app --reload</code></p>
            </div>`;
        return;
    }

    const valued = rows.filter(r => r.primary_valuation && r.primary_valuation.value != null);
    const totalValue = valued.reduce((s, r) => s + parseFloat(r.primary_valuation.value), 0);
    const staleCount = rows.filter(r => r.primary_valuation && r.primary_valuation.is_stale).length;
    const notValued = rows.length - valued.length;

    const statusPill = (r) => {
        const v = r.primary_valuation;
        if (!v) return '<span class="pill pill-muted">Not valued</span>';
        if (v.is_stale && v.stale_reason === 'engine') return '<span class="pill pill-warn" title="Calculated with an earlier version of the valuation engine">Needs re-run (engine updated)</span>';
        if (v.is_stale) return '<span class="pill pill-warn" title="Inputs changed after this valuation ran">Needs re-run</span>';
        return '<span class="pill pill-ok">Current</span>';
    };

    const tableRows = rows.map(r => {
        const v = r.primary_valuation;
        const place = [r.city, r.state].filter(Boolean).join(', ');
        return `
            <tr class="row-link" tabindex="0" data-href="#/property/${r.id}" data-search="${escapeHtmlAttr((r.name + ' ' + place + ' ' + fmt.typeLabel(r.property_type)).toLowerCase())}">
                <td>
                    <div class="cell-title">${escapeHtmlAttr(r.name)}</div>
                    <div class="cell-sub">${escapeHtmlAttr(place || 'No location')}</div>
                </td>
                <td><span class="property-type-badge badge-${r.property_type}">${fmt.typeLabel(r.property_type)}</span></td>
                <td class="mono right">${fmt.sf(r.total_area, r.area_unit, r.property_type)}</td>
                <td>
                    ${statusPill(r)}
                    ${v ? `<div class="cell-sub"><a href="#/valuation/${v.id}" class="valuation-link" title="Open this valuation's results">${escapeHtmlAttr(v.name)}</a></div>` : ''}
                </td>
                <td class="mono right strong">${v ? fmt.currency(v.value) : '—'}</td>
                <td class="mono right">${v && v.going_in_cap_rate != null ? fmt.pct(v.going_in_cap_rate) : '—'}</td>
                <td class="mono right" title="${v && !v.irr ? 'Shown when the valuation has a purchase price' : ''}">${v && v.irr != null ? fmt.pct(v.irr) : '—'}</td>
            </tr>`;
    }).join('');

    $app().innerHTML = `
        <div class="page-header page-header--row">
            <div>
                <h1 class="page-title">Properties</h1>
                <p class="page-subtitle">${rows.length} propert${rows.length === 1 ? 'y' : 'ies'}${valued.length ? ` · ${fmt.currency(totalValue)} total value from each property's latest valuation` : ''}</p>
            </div>
            <div class="page-actions">
                ${menuHtml('Import', [
                    menuItem('aiImportAppraisalBtn', 'From documents', { hint: 'Rent roll, leases, T-12 or appraisal, read by AI' }),
                    menuItem('importWorkbookBtn', 'From Excel workbook', { hint: 'Many properties at once, using the import template' }),
                    menuItem('importPackageBtn', 'From OpenDCF package', { hint: 'A .odcf.zip or .odcf.json file exported from OpenDCF' }),
                ])}
                <button class="btn btn-primary" id="newPropertyBtn">${icons.plus} New property</button>
            </div>
        </div>

        <div id="unfinishedImports"></div>
        ${rows.length === 0 ? `
            <div class="onboarding">
                <h2>Value your first property</h2>
                <p>Start from scratch, or let OpenDCF read an appraisal, rent roll and leases and build the model for you to review.</p>
                <div class="onboarding-choices">
                    <button class="choice-card" id="onboardNewBtn">
                        <span class="choice-card-title">Enter it yourself</span>
                        <span class="choice-card-text">Name, type and size first. A checklist then walks you through rent roll, expenses and market leasing.</span>
                    </button>
                    <button class="choice-card" id="onboardImportBtn">
                        <span class="choice-card-title">Import documents</span>
                        <span class="choice-card-text">Drop in a rent roll, leases, operating statement or appraisal. You check what was read before anything is valued.</span>
                    </button>
                </div>
            </div>` : `
            <div class="summary-strip">
                <div><span class="summary-strip-value">${valued.length}</span> valued</div>
                ${staleCount ? `<div class="summary-strip-warn"><span class="summary-strip-value">${staleCount}</span> need a re-run</div>` : ''}
                ${notValued ? `<div><span class="summary-strip-value">${notValued}</span> not yet valued</div>` : ''}
                <div id="duplicateNotice"></div>
                <input class="form-input summary-strip-search" id="propertySearch" type="search" placeholder="Search properties">
            </div>
            <div class="data-table-wrap">
                <table class="data-table property-table dt-dense">
                    <thead><tr>
                        <th>Property</th><th>Type</th><th class="right">Size</th><th>Latest valuation</th>
                        <th class="right">Value</th><th class="right">Going-in cap</th><th class="right">IRR</th>
                    </tr></thead>
                    <tbody id="propertyRows">${tableRows}</tbody>
                </table>
            </div>`}`;

    const startImport = async (button) => {
        const original = button.innerHTML;
        button.disabled = true;
        button.textContent = 'Opening import…';
        try {
            const workspace = await api.post('/appraisal-import-workspaces', {});
            location.assign(`?intake=1#/valuation/${workspace.valuation_id}`);
        } catch (err) {
            button.disabled = false;
            button.innerHTML = original;
            toast('Could not start the import: ' + err.message, 'error');
        }
    };
    document.getElementById('aiImportAppraisalBtn').addEventListener('click', (e) => startImport(e.currentTarget));
    document.getElementById('importWorkbookBtn').addEventListener('click', () => { location.hash = '#/import'; });
    renderUnfinishedImports();
    renderDuplicateNotice();
    document.getElementById('importPackageBtn').addEventListener('click', () => showPackageImport());
    document.getElementById('newPropertyBtn').addEventListener('click', showNewPropertyModal);
    document.getElementById('onboardNewBtn')?.addEventListener('click', showNewPropertyModal);
    document.getElementById('onboardImportBtn')?.addEventListener('click', (e) => startImport(e.currentTarget));

    document.querySelectorAll('#propertyRows tr[data-href]').forEach(tr => {
        tr.addEventListener('click', () => { location.hash = tr.dataset.href; });
        tr.addEventListener('keydown', (e) => { if (e.key === 'Enter') location.hash = tr.dataset.href; });
        // The latest valuation's name opens its results, not the property
        tr.querySelector('.valuation-link')?.addEventListener('click', (e) => e.stopPropagation());
        tr.querySelector('.valuation-link')?.addEventListener('keydown', (e) => e.stopPropagation());
    });
    document.getElementById('propertySearch')?.addEventListener('input', (e) => {
        const q = e.target.value.trim().toLowerCase();
        document.querySelectorAll('#propertyRows tr').forEach(tr => {
            tr.hidden = q && !tr.dataset.search.includes(q);
        });
    });
}

function showNewPropertyModal() {
    showFormModal({
        title: 'New property',
        fields: NEW_PROPERTY_FIELDS,
        // Remember type and location habits, never the last property's identity (invites duplicates)
        defaults: { name: '', address_line1: '', total_area: '', zip_code: '' },
        onSubmit: async (data, overlay) => {
            const prop = await api.post('/properties', data);
            overlay.remove();
            toast('Property created. Next: add its rent roll and expenses.', 'success');
            location.hash = `#/property/${prop.id}`;
        },
    });
}


// ─── Property Detail ──────────────────────────────────────────

// Tab and Recoveries pane last open per property, so a re-render after a save stays there
const propertyTabMemory = {};

async function propertyView({ id }) {
    const { property, valuations } = await api.get(`/properties/${id}/workspace`);
    // Each valuation owns its whole model; this page shows and edits the one picked
    const modelValuation = pickModelValuation(id, valuations);
    if (!modelValuation) return renderPropertyWithoutValuations(property);
    const mvId = modelValuationIds[id] = modelValuation.id;
    const [{
        suites, expenses, other_income: otherIncomeItems,
        recovery_structures: recoveryStructures, recovery_pools: recoveryPools = [], capital_projects: capitalProjects, leases: propertyLeases, readiness,
    }, marketProfiles] = await Promise.all([
        api.get(`/valuations/${mvId}/workspace`), api.get(`/valuations/${mvId}/market-profiles`),
    ]);
    property.suites = suites;
    const marketValuation = modelValuation;
    const modelFrozen = (modelValuation.review_status || 'draft') !== 'draft';
    const withMarket = (fn) => {
        if (modelFrozen) {
            toast(`'${modelValuation.name}' is frozen for review; duplicate or roll it forward to change its model`, 'error'); return;
        }
        fn();
    };

    const leasesBySuite = {};
    property.suites.forEach(s => { leasesBySuite[s.id] = []; });
    propertyLeases.forEach(l => { (leasesBySuite[l.suite_id] ||= []).push(l); });

    const addressText = [property.address_line1, property.city, property.state, property.zip_code].filter(Boolean).join(', ');
    const simplifyUnitAssumptions = property.property_type === 'multifamily' || property.property_type === 'self_storage';
    const isMarina = property.property_type === 'marina';
    const isSeniorsHousing = property.property_type === 'seniors_housing';
    // Self storage is valued from its unit mix unless it still has a rent roll and no unit mix
    const storageModel = property.property_type === 'self_storage' ? storageModelOf(modelValuation) : null;
    const isStorageModel = property.property_type === 'self_storage' && (!!storageModel || property.suites.length === 0);
    const totalArea = parseFloat(property.total_area);
    const occupiedArea = property.suites.reduce((sum, s) => {
        const hasLease = (leasesBySuite[s.id] || []).some(l => l.lease_type !== 'market');
        return sum + (hasLease ? parseFloat(s.area) : 0);
    }, 0);
    const occupancyPct = totalArea > 0 ? occupiedArea / totalArea : 0;

    setBreadcrumb([
        { label: 'Properties', href: '#/dashboard' },
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

    // Marina, seniors and storage pages show the model valuation's own results
    let modelCashFlows = [];
    let modelKeyMetrics = null;
    if ((isMarina || isSeniorsHousing || (isStorageModel && storageModel)) && modelValuation.status === 'completed') {
        try {
            const fullReport = await api.get(`/valuations/${mvId}/reports/full?include_recovery_audit=false`);
            modelCashFlows = fullReport.annual_cash_flows || [];
            modelKeyMetrics = fullReport.key_metrics || null;
        } catch { /* valuation may not have been run yet */ }
    }
    const marinaCashFlows = modelCashFlows, marinaKeyMetrics = modelKeyMetrics;
    const shCashFlows = modelCashFlows, shKeyMetrics = modelKeyMetrics;
    const storageCashFlows = modelCashFlows, storageKeyMetrics = modelKeyMetrics;
    // Render functions read the operating model from these holders
    const marinaModel = modelValuation;
    const shModel = modelValuation;

    // Save an edited operating model on the model valuation, then re-run it if it had results
    async function saveOperatingModel(column, updated) {
        await api.put(`/valuations/${mvId}`, { [column]: JSON.stringify(updated) });
        toast('Operating model saved', 'success');
        if (modelValuation.status === 'completed') {
            try {
                await api.post(`/valuations/${mvId}/run`);
                toast(`Re-ran "${modelValuation.name}"`, 'success');
            } catch (err) {
                toast('Re-run failed: ' + err.message, 'error');
            }
        }
        propertyView({ id });
    }

    $app().innerHTML = `
        <div class="property-header">
            <div class="property-header-left">
                <h1 class="property-header-title">${escapeHtmlAttr(property.name)}</h1>
                <div class="property-header-address">${escapeHtmlAttr(addressText || 'No address specified')}</div>
                <div class="property-header-badges">
                    <span class="property-type-badge badge-${property.property_type}">${fmt.typeLabel(property.property_type)}</span>
                    <span class="status-badge" style="background:var(--bg-secondary);color:var(--text-secondary)">${fmt.sf(property.total_area, property.area_unit, property.property_type)}</span>
                    ${property.year_built ? `<span class="status-badge" style="background:var(--bg-secondary);color:var(--text-secondary)">Built ${property.year_built}</span>` : ''}
                    ${property.cbsa_title ? `<span class="status-badge" style="background:var(--bg-secondary);color:var(--text-secondary)" title="Census market (CBSA ${property.cbsa_code})">${escapeHtmlAttr(property.cbsa_title)}</span>` : ''}
                    ${property.quality_score != null ? `<span class="status-badge" style="background:var(--bg-secondary);color:var(--text-secondary)" title="Quality score: 5 = best, 3 = market typical">Quality ${parseFloat(property.quality_score)}</span>` : ''}
                    ${(isMarina || isSeniorsHousing || isStorageModel) ? (() => {
                        const specY1 = isMarina ? marinaCashFlows[0] : isStorageModel ? storageCashFlows[0] : shCashFlows[0];
                        const specMetrics = isMarina ? marinaKeyMetrics : isStorageModel ? storageKeyMetrics : shKeyMetrics;
                        return `
                    <span class="status-badge" style="background:var(--bg-secondary);color:var(--text-secondary)" title="Year 1 NOI of '${escapeHtmlAttr(modelValuation.name)}'">Y1 NOI ${specY1 ? fmt.currencyExact(parseFloat(specY1.net_operating_income)) : '—'}</span>
                    <span class="status-badge" style="background:var(--bg-secondary);color:var(--text-secondary)" title="NPV of '${escapeHtmlAttr(modelValuation.name)}'">NPV ${specMetrics ? fmt.currencyExact(parseFloat(specMetrics.npv)) : '—'}</span>`;
                    })() : `
                    <span class="status-badge" style="background:var(--bg-secondary);color:var(--text-secondary)">${property.suites.length} suite${property.suites.length === 1 ? '' : 's'}</span>
                    <span class="status-badge" style="background:var(--bg-secondary);color:var(--text-secondary)" title="Leased area ÷ total area">${fmt.pct(occupancyPct, 1)} occupied</span>`}
                </div>
            </div>
            <div class="property-header-actions">
                <button class="btn btn-secondary btn-sm" id="editPropertyBtn">${icons.edit} Edit details</button>
                ${menuHtml('More', [
                    `<a class="menu-item" href="#/tenants/${id}">Tenant list</a>`,
                    menuItem('valEvidenceBtn', 'New valuation from documents'),
                    menuItem('mergePropertiesBtn', 'Merge duplicates…'),
                    menuItem('deletePropertyBtn', 'Delete property…', { danger: true }),
                ])}
                <button class="btn btn-primary btn-sm" id="newValuationBtn">${icons.plus} New valuation</button>
            </div>
        </div>

        ${renderModelPicker(valuations, modelValuation, property)}

        ${renderReadinessCard(readiness)}

        <div class="tab-bar" id="tabBar">
            <button class="tab-item active" data-tab="rent-roll">${isMarina ? 'Slip Inventory' : isSeniorsHousing || isStorageModel ? 'Unit Mix' : 'Rent Roll'}</button>
            <button class="tab-item" data-tab="operating-budget">${isMarina || isSeniorsHousing ? 'Operations' : 'Operating Budget'}</button>
            ${simplifyUnitAssumptions || isMarina || isSeniorsHousing ? '' : '<button class="tab-item" data-tab="market">Market Leasing</button>'}
            ${simplifyUnitAssumptions || isMarina || isSeniorsHousing ? '' : '<button class="tab-item" data-tab="recovery">Recoveries</button>'}
            <div class="menu tab-more">
                <button type="button" class="tab-item tab-more-trigger menu-trigger" id="tabMoreTrigger">More <span class="menu-caret">▾</span></button>
                <div class="menu-list">
                    ${isMarina || isSeniorsHousing ? '' : '<button class="tab-item menu-item" data-tab="capital">Capital Projects</button>'}
                    <button class="tab-item menu-item" data-tab="comparables">Sales Comparables</button>
                    <button class="tab-item menu-item" data-tab="loans">Loans</button>
                </div>
            </div>
        </div>

        <div class="tab-content active" id="tab-rent-roll">
            ${isMarina ? renderMarinaSlipTab(property, marinaCashFlows, marinaModel)
              : isSeniorsHousing ? renderSeniorsHousingUnitTab(property, shCashFlows, shModel)
              : isStorageModel ? renderStorageUnitMixTab(property, storageModel, storageCashFlows)
              : (property.property_type === 'self_storage' ? storageConvertNotice() : '')
                + renderRentRollTab(property, allLeases, marketProfiles, recoveryStructures)}
        </div>
        <div class="tab-content" id="tab-operating-budget">
            ${isMarina ? renderMarinaOperatingTab(property, marinaCashFlows, marinaModel)
              : isSeniorsHousing ? renderSeniorsHousingOperatingTab(property, shCashFlows, shModel)
              : renderOperatingBudgetTab(expenses, otherIncomeItems, totalArea, property.area_unit, property.property_type, recoveryPools)}
        </div>
        ${simplifyUnitAssumptions ? '' : `<div class="tab-content" id="tab-market">
            ${renderMarketTab(marketProfiles, property, marketValuation, recoveryStructures)}
        </div>`}
        <div class="tab-content" id="tab-capital">
            ${renderCapitalProjectsTab(capitalProjects, id)}
        </div>
        ${simplifyUnitAssumptions ? '' : `<div class="tab-content" id="tab-recovery">
            <div class="btn-group" id="recoveryPaneNav" style="margin-bottom:16px">
                <button type="button" class="btn btn-primary btn-sm" data-recovery-pane="structures">Structures (${recoveryStructures.length})</button>
                <button type="button" class="btn btn-secondary btn-sm" data-recovery-pane="pools">Pools (${recoveryPools.length})</button>
                <button type="button" class="btn btn-secondary btn-sm" data-recovery-pane="audit">Tenant Recovery Audit</button>
            </div>
            <div class="recovery-pane" data-pane="structures">${renderRecoveryStructuresTab(recoveryStructures, allLeases, marketProfiles)}</div>
            <div class="recovery-pane" data-pane="pools" style="display:none">${renderRecoveryPoolsSection(recoveryPools, property)}</div>
            <div class="recovery-pane" data-pane="audit" style="display:none">${renderRecoveryAuditTab(completedValuations)}</div>
        </div>`}
        <div class="tab-content" id="tab-comparables">
            <div id="comparableSalesSection">${skeletonRows(6)}</div>
        </div>
        <div class="tab-content" id="tab-loans"></div>`;

    // Tab switching
    document.getElementById('tabBar').addEventListener('click', (e) => {
        const tab = e.target.closest('.tab-item');
        if (!tab || !tab.dataset.tab) return;
        document.querySelectorAll('.tab-item').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        const moreTrigger = document.getElementById('tabMoreTrigger');
        if (moreTrigger) {
            const inMore = !!tab.closest('.tab-more');
            moreTrigger.classList.toggle('active', inMore);
            moreTrigger.innerHTML = `${inMore ? escapeHtmlAttr(tab.textContent) : 'More'} <span class="menu-caret">▾</span>`;
        }
        const content = document.getElementById('tab-' + tab.dataset.tab);
        if (content) content.classList.add('active');
        if (tab.dataset.tab === 'loans') loadPropertyLoans(property);
        if (tab.dataset.tab === 'comparables') loadComparableSalesTab(property);
        if (tab.dataset.tab === 'recovery' && recoveryPane === 'audit' && !auditLoaded) loadRecoveryAudit();
        propertyTabMemory[id] = { ...propertyTabMemory[id], tab: tab.dataset.tab };
    });

    // Recoveries tab: structures, pools and the tenant audit, one pane at a time
    let recoveryPane = 'structures';
    const showRecoveryPane = (name) => {
        recoveryPane = name;
        propertyTabMemory[id] = { ...propertyTabMemory[id], pane: name };
        document.querySelectorAll('#recoveryPaneNav [data-recovery-pane]').forEach(b => {
            b.classList.toggle('btn-primary', b.dataset.recoveryPane === name);
            b.classList.toggle('btn-secondary', b.dataset.recoveryPane !== name);
        });
        document.querySelectorAll('#tab-recovery .recovery-pane').forEach(p => { p.style.display = p.dataset.pane === name ? '' : 'none'; });
        if (name === 'audit' && !auditLoaded) loadRecoveryAudit();
    };
    document.getElementById('recoveryPaneNav')?.addEventListener('click', (e) => {
        const b = e.target.closest('[data-recovery-pane]');
        if (b) showRecoveryPane(b.dataset.recoveryPane);
    });

    // Recovery Audit tab interactions
    const auditValuationSel = document.getElementById('recoveryAuditValuationSelect');
    const auditTenantSel = document.getElementById('recoveryAuditTenantSelect');
    const auditSummaryEl = document.getElementById('recoveryAuditSummary');
    const auditTableEl = document.getElementById('recoveryAuditTable');
    const openAuditValuationBtn = document.getElementById('openAuditValuationBtn');
    let auditRows = [];
    let auditLoaded = false;  // the audit can run to ~100k rows, so it loads when its tab first opens
    const AUDIT_ROW_LIMIT = 500;

    function renderAuditRows(rows, tenantFilter, limit = AUDIT_ROW_LIMIT) {
        const all = Array.isArray(rows) ? rows : [];
        const filtered = (tenantFilter && tenantFilter !== '__all__')
            ? all.filter(r => (r.tenant_name || 'Vacant/Spec') === tenantFilter)
            : all;
        // The area each row's share is taken over: its recovery pool's denominator, else the property area
        const rowArea = (r) => parseFloat(r.share_denominator_area ?? property.total_area);
        const perSf = (r, amount) => { const a = rowArea(r); return Number.isFinite(a) && a > 0 ? amount / a : null; };
        const mgPoolPerSfByKey = {};
        filtered.forEach((r) => {
            if (r.recovery_type !== 'modified_gross') return;
            const key = `${r.year}|${r.period_start}|${r.suite_id}|${r.lease_id}`;
            mgPoolPerSfByKey[key] = (mgPoolPerSfByKey[key] || 0) + (perSf(r, parseFloat(r.annual_expense_after_gross_up || 0)) || 0);
        });
        // The $/SF the stop is tested against: the engine's pooled $/SF; a line with its own stop is
        // measured alone. Runs saved before the engine reported it fall back to summing the MG rows.
        const mgPoolPerSf = (r) => {
            if (r.modified_gross_pool_per_sf === undefined) {
                return mgPoolPerSfByKey[`${r.year}|${r.period_start}|${r.suite_id}|${r.lease_id}`] || 0;
            }
            if (r.modified_gross_pool_per_sf === null) {
                return perSf(r, parseFloat(r.annual_expense_after_gross_up || 0)) || 0;
            }
            return parseFloat(r.modified_gross_pool_per_sf);
        };
        const totalWeighted = filtered.reduce((sum, r) => sum + parseFloat(r.weighted_monthly_recovery || 0), 0);
        if (auditSummaryEl) {
            auditSummaryEl.textContent = `${filtered.length} row${filtered.length === 1 ? '' : 's'} • Weighted recovery total ${fmt.currencyExact(totalWeighted)}`
                + (filtered.length > limit ? ` • Showing the first ${fmt.num(limit)}` : '');
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

        const body = filtered.slice(0, limit).map((r) => `<tr>
            <td>${r.year}</td>
            <td>${fmt.date(r.period_start)}</td>
            <td>${escapeHtmlAttr(r.suite_name || r.suite_id)}</td>
            <td>${escapeHtmlAttr(r.tenant_name || 'Vacant/Spec')}</td>
            <td class="mono right">${fmt.num(suiteAreaById[r.suite_id])}</td>
            <td>${fmt.typeLabel(r.expense_category)}</td>
            <td>${fmt.typeLabel(r.recovery_type)}</td>
            <td>${impl(r)}</td>
            <td>${escapeHtmlAttr(r.recovery_pool || '—')}</td>
            <td class="mono right">${fmt.num(rowArea(r))}</td>
            <td class="mono right">${parseFloat(r.pool_deduction || 0) ? fmt.currencyExact(r.pool_deduction) : '—'}</td>
            <td class="mono right">${(() => {
                const v = perSf(r, parseFloat(r.annual_expense_before_gross_up || 0));
                return v == null ? '—' : fmt.perSf(v, property.area_unit);
            })()}</td>
            <td class="mono right">${(() => {
                const v = perSf(r, parseFloat(r.annual_expense_after_gross_up || 0));
                return v == null ? '—' : fmt.perSf(v, property.area_unit);
            })()}</td>
            <td class="mono right">${(() => {
                if (r.recovery_type !== 'modified_gross') return '—';
                return fmt.perSf(mgPoolPerSf(r), property.area_unit);
            })()}</td>
            <td class="mono right">${(() => {
                if (r.recovery_type !== 'modified_gross') return '—';
                const stop = parseFloat(r.expense_stop_per_sf || 0);
                return fmt.perSf(Math.max(0, mgPoolPerSf(r) - stop), property.area_unit);
            })()}</td>
            <td class="mono right">${(() => {
                if (r.recovery_type !== 'modified_gross') return '—';
                const poolPerSf = mgPoolPerSf(r);
                const catPerSf = perSf(r, parseFloat(r.annual_expense_after_gross_up || 0));
                if (!(poolPerSf > 0) || catPerSf == null) return '—';
                return fmt.pct(catPerSf / poolPerSf);
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
                            <th>Recovery Pool</th>
                            <th class="right">Share Denominator</th>
                            <th class="right">Pool Deduction</th>
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
            </div>
            ${filtered.length > limit ? `<button type="button" class="btn btn-secondary btn-sm" id="auditShowMore">Show ${fmt.num(Math.min(AUDIT_ROW_LIMIT, filtered.length - limit))} more of ${fmt.num(filtered.length - limit)} remaining</button>` : ''}`;
        document.getElementById('auditShowMore')?.addEventListener('click', () => renderAuditRows(rows, tenantFilter, limit + AUDIT_ROW_LIMIT));
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
        auditTableEl.innerHTML = `<div class="skeleton" role="status" aria-label="Loading audit">${skeletonRows(10)}</div>`;
        auditLoaded = true;
        try {
            auditRows = await api.get(`/valuations/${vid}/reports/recovery-audit`);
        } catch (err) {
            auditLoaded = false;  // retry when the tab is opened again
            auditRows = [];
            auditTableEl.innerHTML = `<div class="empty-state"><h3>Could not load recovery audit</h3><p>${escapeHtmlAttr(err.message)}</p></div>`;
            return;
        }
        const tenantNames = [...new Set(auditRows.map(r => r.tenant_name || 'Vacant/Spec'))].sort((a, b) => a.localeCompare(b));
        auditTenantSel.innerHTML = [
            '<option value="__all__">All Tenants</option>',
            ...tenantNames.map(name => `<option value="${escapeHtmlAttr(name)}">${escapeHtmlAttr(name)}</option>`),
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
        sessionStorage.removeItem('opendcf_recovery_audit_valuation_id');
    }

    const pendingTab = sessionStorage.getItem('opendcf_property_tab');
    if (pendingTab) {
        const tabBtn = document.querySelector(`#tabBar .tab-item[data-tab="${pendingTab === 'recovery-audit' ? 'recovery' : pendingTab}"]`);
        if (tabBtn) tabBtn.click();
        if (tabBtn && pendingTab === 'recovery-audit') showRecoveryPane('audit');
        sessionStorage.removeItem('opendcf_property_tab');
    } else if (propertyTabMemory[id]) {
        const { tab, pane } = propertyTabMemory[id];
        document.querySelector(`#tabBar .tab-item[data-tab="${tab}"]`)?.click();
        if (pane && document.getElementById('recoveryPaneNav')) showRecoveryPane(pane);
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

    // Duplicate a valuation as a new scenario
    document.querySelectorAll('[data-duplicate-valuation]').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            try {
                const copy = await api.post(`/valuations/${btn.dataset.duplicateValuation}/duplicate`, {});
                saveModelValuation(id, copy.id);
                const val = await api.get(`/valuations/${copy.id}`);
                showValuationForm({ property, valuation: val, onSaved: () => propertyView({ id }) });
                propertyView({ id });
            } catch (err) {
                toast('Could not duplicate: ' + err.message, 'error');
            }
        });
    });

    // Readiness checklist: each button opens the editor that fixes the item
    const showTab = (tab) => {
        const tabBtn = document.querySelector(`#tabBar .tab-item[data-tab="${tab}"]`);
        if (tabBtn) {
            tabBtn.click();
            document.getElementById('tabBar').scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    };
    const readinessActions = {
        space: () => (property.area_unit === 'unit'
            ? document.getElementById('newUnitTypeBtn')?.click()
            : openRentRollPasteEditor(property)),
        leases: () => showTab('rent-roll'),
        market: () => withMarket(() => openMarketAssumptionWorkspace(mvId, property, marketProfiles)),
        expenses: () => openExpenseWorkspace(id, expenses, property.property_type),
        operating_model: () => (isSeniorsHousing
            ? document.getElementById('editShUnitsBtn')?.click()
            : document.getElementById('addSlipClassBtn')?.click()),
    };
    document.querySelectorAll('[data-readiness-action]').forEach(btn => {
        btn.addEventListener('click', () => readinessActions[btn.dataset.readinessAction]?.());
    });

    document.getElementById('pasteRentRollBtn')?.addEventListener('click', () => openRentRollPasteEditor(property));

    // New valuation button
    const newValBtn = document.getElementById('newValuationBtn');
    if (newValBtn) {
        newValBtn.addEventListener('click', () => showNewValuationModal(property, marketProfiles));
    }
    wireEvidenceWorkspace(mvId);

    // Edit Property
    document.getElementById('editPropertyBtn').addEventListener('click', async () => {
        showFormModal({
            title: 'Edit Property',
            fields: await withCbsaPicker(PROPERTY_FIELDS),
            initialValues: { ...property, cbsa_label: cbsaLabel(property.cbsa_code, property.cbsa_title) },
            onSubmit: async (data, overlay) => {
                if ('cbsa_label' in data) data.cbsa_code = cbsaCodeFromLabel(data.cbsa_label);
                delete data.cbsa_label;
                await api.put(`/properties/${id}`, data);
                overlay.remove();
                toast('Property updated', 'success');
                propertyView({ id });
            }
        });
    });

    document.getElementById('mergePropertiesBtn').addEventListener('click', () =>
        openMergeProperties(property).catch(err => toast(err.message, 'error')));

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
        btn.addEventListener('click', () => withMarket(() => openMarketAssumptionWorkspace(mvId, property, marketProfiles)));
    });

    const editRentUnitBtn = document.getElementById('editRentUnitBtn');
    if (editRentUnitBtn) {
        editRentUnitBtn.addEventListener('click', () => openUnitInPlaceRentEditor(id, allLeases));
    }

    const bulkMarketBtn = document.getElementById('bulkMarketBtn');
    if (bulkMarketBtn) {
        bulkMarketBtn.addEventListener('click', () => withMarket(() => openMarketAssumptionWorkspace(mvId, property, marketProfiles)));
    }

    // Quick market setup in Market tab for unit-type properties
    const quickUnitMarketBtn = document.getElementById('quickUnitMarketBtn');
    if (quickUnitMarketBtn) {
        quickUnitMarketBtn.addEventListener('click', () => withMarket(() => openUnitMarketQuickSetup(mvId, property, marketProfiles)));
    }
    document.getElementById('modelValuationSelect')?.addEventListener('change', (e) => {
        saveModelValuation(id, e.target.value);
        propertyView({ id });
    });
    document.querySelectorAll('[data-roll-forward]').forEach(btn => btn.addEventListener('click', (e) => {
        e.stopPropagation();
        openRollForward(btn.dataset.rollForward, () => propertyView({ id }));
    }));

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
                    const suite = await api.post(`/valuations/${mvId}/suites`, suiteData);
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
                            const tenant = await api.post(`/valuations/${mvId}/tenants`, { name: data.resident_name.trim() });
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
                    await api.put(`/valuations/${mvId}/suites/${sid}`, {
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
                                const tenant = await api.post(`/valuations/${mvId}/tenants`, { name: data.resident_name.trim() });
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
                            const tenant = await api.post(`/valuations/${mvId}/tenants`, { name: data.resident_name.trim() });
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
                    if (!data.market_space_type) delete data.market_space_type;
                    await api.post(`/valuations/${mvId}/suites`, data);
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
                    await api.put(`/valuations/${mvId}/suites/${sid}`, data);
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
                await api.del(`/valuations/${mvId}/suites/${sid}`);
                toast('Suite deleted', 'success');
                propertyView({ id });
            });
        });
    });

    // New Lease
    // Helper: open lease form with inline tenant creation
    function openLeaseForm(title, initialValues, onSubmit, opts = {}) {
        return (async () => {
            let tenants = [];
            try { tenants = await api.get(`/valuations/${mvId}/tenants`); } catch {}
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
            const wireRsLinks = addRecoveryStructureLinks(leaseFields, mvId, () => propertyView({ id }));
            const formOverlay = showFormModal({
                title,
                fields: leaseFields,
                wide: true,
                initialValues,
                onSubmit
            });
            wireRsLinks(formOverlay);
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
                                const newTenant = await api.post(`/valuations/${mvId}/tenants`, data);
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
            return formOverlay;
        })();
    }

    // One editor per lease: the Terms form's modal gains tabs for the rent schedule, free rent and
    // recovery overrides, each rendered by its existing builder into a pane of the same modal
    async function openLeaseEditor(lid, initialTab = 'terms') {
        const lease = allLeases.find(l => l.id === lid);
        const formOverlay = await openLeaseForm(
            `${lease.tenant ? lease.tenant.name : 'Lease'}, suite ${lease.suite?.suite_name || ''}`, lease,
            async (data, overlay) => {
                if (data.tenant_id === '') data.tenant_id = null;
                await api.put(`/leases/${lid}`, data);
                overlay.remove();
                toast('Lease updated', 'success');
                propertyView({ id });
            }, { includeSuite: false });
        const modal = formOverlay.querySelector('.modal');
        modal.classList.add('lease-editor');
        const actions = modal.querySelector('.modal-actions');
        const cancelBtn = actions.querySelector('.btn-secondary'), saveBtn = actions.querySelector('.btn-primary');
        const termsEls = [...modal.children].filter(el => el !== actions && !el.classList.contains('modal-title'));
        const tabs = [['terms', 'Terms'], ['schedule', 'Rent schedule'], ['free-rent', 'Free rent'],
            ...(simplifyUnitAssumptions ? [] : [['recoveries', 'Recoveries']])];
        const strip = document.createElement('div');
        strip.className = 'tab-bar lease-editor-tabs';
        strip.innerHTML = tabs.map(([key, label]) => `<button type="button" class="tab-item" data-lease-tab="${key}">${label}</button>`).join('');
        modal.querySelector('.modal-title').after(strip);
        let pane = document.createElement('div');
        actions.before(pane);
        // Sub-tabs save as they go; the rent roll refreshes when the editor closes
        let changed = false;
        const onChange = () => { changed = true; };
        const close = () => { formOverlay.remove(); if (changed) propertyView({ id }); };
        cancelBtn.onclick = close;
        formOverlay.addEventListener('click', (e) => { if (e.target === formOverlay && changed) propertyView({ id }); });
        const showTab = (key) => {
            strip.querySelectorAll('[data-lease-tab]').forEach(b => b.classList.toggle('active', b.dataset.leaseTab === key));
            termsEls.forEach(el => { el.style.display = key === 'terms' ? '' : 'none'; });
            // A fresh pane per tab, so a slow render from the last tab lands in a detached node
            const fresh = document.createElement('div');
            pane.replaceWith(fresh);
            pane = fresh;
            pane.style.display = key === 'terms' ? 'none' : '';
            // Other tabs save as they go; Save Changes is for the Terms form
            saveBtn.style.display = key === 'terms' ? '' : 'none';
            cancelBtn.textContent = key === 'terms' ? 'Cancel' : 'Close';
            if (key === 'schedule') showRentScheduleBuilder(lid, id, property.area_unit, { host: pane, onChange });
            else if (key !== 'terms') {
                showLeaseDetailModal(lid, id, marketProfiles, property.property_type, property.area_unit, { host: pane, section: key, onChange });
            }
        };
        strip.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-lease-tab]');
            if (btn) showTab(btn.dataset.leaseTab);
        });
        showTab(tabs.some(([key]) => key === initialTab) ? initialTab : 'terms');
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

    // Lease editor: each older entry point opens it on its matching tab
    [['data-detail-lease', 'detailLease', 'recoveries'], ['data-edit-lease', 'editLease', 'terms']].forEach(([attr, key, tab]) => {
        document.querySelectorAll(`[${attr}]`).forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                openLeaseEditor(btn.dataset[key], tab);
            });
        });
    });
    // Clicking a lease row opens it too, except on inline-edit cells and controls, and except the
    // click that commits an open inline edit (its blur closes the editor before the click lands)
    const rentRollTable = document.getElementById('rentRollTable');
    let inlineEditAtPress = false;
    rentRollTable?.addEventListener('pointerdown', () => { inlineEditAtPress = !!rentRollTable.querySelector('.ie-editing'); }, true);
    rentRollTable?.addEventListener('click', (e) => {
        const row = e.target.closest('tr[data-open-lease]');
        if (!row || inlineEditAtPress || e.target.closest('.ie-cell, button, a, input, select, .row-menu')) return;
        openLeaseEditor(row.dataset.openLease);
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

    wireRentRollInlineEdit(allLeases, id);

    // New Expense. With recovery pools, the form also picks the expense category's pool.
    const poolOfCategory = (category) => recoveryPools.find(p => (p.expense_categories || []).includes(category));
    const expenseFields = [...buildExpenseFields(property.property_type), ...(simplifyUnitAssumptions ? [] : [{
        key: 'recovery_pool_id', label: 'Recovery Pool', type: 'select', default: '',
        visibleWhen: v => v.is_recoverable !== false,
        options: [{ value: '', label: '— Whole property area —' }, ...recoveryPools.map(p => ({ value: p.id, label: p.name }))],
        helpText: recoveryPools.length
            ? 'Shares this expense category over the pool\'s area. Every expense in the same category uses the same pool. Pools are set up on Recoveries ▸ Pools.'
            : 'No recovery pools yet: every recoverable expense is shared over the whole property area. Set up pools (e.g. shop CAM without anchors) on Recoveries ▸ Pools.',
    }])];
    const withPool = (exp) => ({ ...exp, recovery_pool_id: poolOfCategory(exp.category)?.id || '' });
    // Pools hold categories. `picked` is the pool chosen (undefined when the picker was not changed):
    // the category moves to it, removals first since a category can be in one pool only. A renamed
    // category keeps its pool; the old name leaves the pool when no other expense still has it.
    async function saveExpensePool(expenseId, oldCategory, category, picked) {
        const renamed = oldCategory != null && oldCategory !== category;
        const target = picked !== undefined ? picked : (renamed ? poolOfCategory(oldCategory)?.id : undefined);
        if (target === undefined || (picked === undefined && !target)) return;
        const others = new Set(expenses.filter(e => e.id !== expenseId).map(e => e.category));
        const wanted = (p) => {
            let cats = (p.expense_categories || []).filter(c => c !== category && !(renamed && c === oldCategory && !others.has(c)));
            if (p.id === target) cats = [...cats, category];
            return cats;
        };
        const changed = recoveryPools.map(p => ({ p, cats: wanted(p) }))
            .filter(({ p, cats }) => cats.length !== p.expense_categories.length || cats.some(c => !p.expense_categories.includes(c)));
        const put = ({ p, cats }) => {
            const { id: poolId, property_id: _p, valuation_id: _v, created_at: _c, updated_at: _u, ...rest } = p;
            return api.put(`/valuations/${mvId}/recovery-pools/${poolId}`, { ...rest, expense_categories: cats });
        };
        for (const c of changed.filter(c => c.p.id !== target)) await put(c);
        for (const c of changed.filter(c => c.p.id === target)) await put(c);
    }
    const expenseBody = ({ recovery_pool_id: _pool, ...body }) => body;
    const newExpenseBtn = document.getElementById('newExpenseBtn');
    if (newExpenseBtn) {
        newExpenseBtn.addEventListener('click', () => {
            showFormModal({
                title: 'New Expense',
                fields: expenseFields,
                defaults: { recovery_pool_id: '' },  // never prefilled from the last entry
                onSubmit: async (data, overlay) => {
                    await api.post(`/valuations/${mvId}/expenses`, expenseBody(data));
                    // Left on "Whole property area", a category another expense already pools stays pooled
                    if (data.is_recoverable !== false) await saveExpensePool(null, null, data.category, data.recovery_pool_id || undefined);
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
                initialValues: withPool(exp),
                onSubmit: async (data, overlay) => {
                    await api.put(`/valuations/${mvId}/expenses/${eid}`, expenseBody(data));
                    // The form sends only changed fields
                    if ((data.is_recoverable ?? exp.is_recoverable) !== false) {
                        await saveExpensePool(eid, exp.category, data.category ?? exp.category,
                            'recovery_pool_id' in data ? data.recovery_pool_id : undefined);
                    }
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
                await api.del(`/valuations/${mvId}/expenses/${eid}`);
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
                    await api.post(`/valuations/${mvId}/other-income`, data);
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
                    await api.put(`/valuations/${mvId}/other-income/${itemId}`, data);
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
                await api.del(`/valuations/${mvId}/other-income/${itemId}`);
                toast('Other income item deleted', 'success');
                propertyView({ id });
            });
        });
    });

    // New Market Profile
    const newMarketBtn = document.getElementById('newMarketBtn');
    if (newMarketBtn) {
        newMarketBtn.addEventListener('click', () => withMarket(() => {
            const fields = buildMarketFields(property.area_unit, true, marketProfiles, recoveryStructures);
            const wireRsLinks = addRecoveryStructureLinks(fields, mvId, () => propertyView({ id }));
            wireRsLinks(showFormModal({
                title: 'New Market Profile',
                fields,
                wide: true,
                onSubmit: async (data, overlay) => {
                    await api.post(`/valuations/${mvId}/market-profiles`, data);
                    overlay.remove();
                    toast('Market profile created', 'success');
                    propertyView({ id });
                }
            }));
        }));
    }

    // Edit Market Profile
    document.querySelectorAll('[data-edit-market]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const mid = btn.dataset.editMarket;
            const mp = marketProfiles.find(x => x.id === mid);
            withMarket(() => {
                const fields = buildMarketFields(property.area_unit, false, marketProfiles.filter(x => x.id !== mid), recoveryStructures);
                const wireRsLinks = addRecoveryStructureLinks(fields, mvId, () => propertyView({ id }));
                wireRsLinks(showFormModal({
                    title: 'Edit Market Profile',
                    fields,
                    wide: true,
                    initialValues: mp,
                    onSubmit: async (data, overlay) => {
                        await api.put(`/valuations/${mvId}/market-profiles/${mid}`, data);
                        overlay.remove();
                        toast('Market profile updated', 'success');
                        propertyView({ id });
                    }
                }));
            });
        });
    });

    // Delete Market Profile
    document.querySelectorAll('[data-delete-market]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const mid = btn.dataset.deleteMarket;
            const mp = marketProfiles.find(x => x.id === mid);
            withMarket(() => showDeleteConfirm(mp.space_type + ' market profile', async () => {
                await api.del(`/valuations/${mvId}/market-profiles/${mid}`);
                toast('Market profile deleted', 'success');
                propertyView({ id });
            }));
        });
    });

    // Edit Valuation
    document.querySelectorAll('[data-edit-valuation]').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const vid = btn.dataset.editValuation;
            const val = valuations.find(v => v.id === vid);
            showValuationForm({ property, valuation: val, onSaved: () => propertyView({ id }) });
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
                    await api.post(`/valuations/${mvId}/capital-projects`, data);
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
                    await api.put(`/valuations/${mvId}/capital-projects/${cpId}`, data);
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
                await api.del(`/valuations/${mvId}/capital-projects/${cpId}`);
                toast('Capital project deleted', 'success');
                propertyView({ id });
            });
        });
    });

    // --- Recovery Pool CRUD ---
    const poolFields = () => buildRecoveryPoolFields(expenses, property.suites || [], property.area_unit);
    document.getElementById('newRecoveryPoolBtn')?.addEventListener('click', () => {
        showFormModal({
            title: 'New Recovery Pool',
            fields: poolFields(),
            wide: true,
            onSubmit: async (data, overlay) => {
                await api.post(`/valuations/${mvId}/recovery-pools`, recoveryPoolPayload(data));
                overlay.remove();
                toast('Recovery pool created', 'success');
                propertyView({ id });
            }
        });
    });
    document.querySelectorAll('[data-edit-pool]').forEach(btn => {
        btn.addEventListener('click', () => {
            const pool = recoveryPools.find(p => p.id === btn.dataset.editPool);
            const fields = poolFields();
            showFormModal({
                title: 'Edit Recovery Pool',
                fields,
                wide: true,
                initialValues: pool,
                onSubmit: async (data, overlay) => {
                    // The pool PUT replaces every field
                    await api.put(`/valuations/${mvId}/recovery-pools/${pool.id}`,
                        recoveryPoolPayload(withUnchanged(fields, pool, data)));
                    overlay.remove();
                    toast('Recovery pool updated', 'success');
                    propertyView({ id });
                }
            });
        });
    });
    document.querySelectorAll('[data-delete-pool]').forEach(btn => {
        btn.addEventListener('click', () => {
            const pool = recoveryPools.find(p => p.id === btn.dataset.deletePool);
            showDeleteConfirm(pool.name, async () => {
                await api.del(`/valuations/${mvId}/recovery-pools/${pool.id}`);
                toast('Recovery pool deleted', 'success');
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
                    const created = await api.post(`/valuations/${mvId}/recovery-structures`, data);
                    overlay.remove();
                    toast('Recovery structure created. Add category overrides, or close to keep the default for every expense.', 'success');
                    openRecoveryItemsWorkspace(`/valuations/${mvId}/recovery-structures/${created.id}`, created, () => propertyView({ id }));
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
                    await api.put(`/valuations/${mvId}/recovery-structures/${rsId}`, data);
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
                await api.del(`/valuations/${mvId}/recovery-structures/${rsId}`);
                toast('Recovery structure deleted', 'success');
                propertyView({ id });
            });
        });
    });

    document.querySelectorAll('[data-add-rs-item]').forEach(btn => {
        btn.addEventListener('click', () => {
            const rsId = btn.dataset.addRsItem;
            const rs = recoveryStructures.find(r => r.id === rsId);
            openRecoveryItemsWorkspace(`/valuations/${mvId}/recovery-structures/${rsId}`, rs, () => propertyView({ id }));
        });
    });

    document.querySelectorAll('[data-del-rs-item]').forEach(btn => {
        btn.addEventListener('click', async () => {
            const itemId = btn.dataset.delRsItem;
            const rsId = btn.dataset.rsId;
            await api.del(`/valuations/${mvId}/recovery-structures/${rsId}/items/${itemId}`);
            toast('Category override removed', 'success');
            propertyView({ id });
        });
    });

    // --- Self Storage Unit Mix Editing ---
    if (property.property_type === 'self_storage') {
        wireStorageEditors(property, storageModel, updated => saveOperatingModel('self_storage_assumptions_json', updated));
    }

    // --- Seniors Housing Operating Model Editing ---
    if (isSeniorsHousing) {
        let shModelData = null;
        try { shModelData = JSON.parse(shModel.seniors_housing_assumptions_json || 'null'); } catch {}
        shModelData = shModelData || { unit_types: [], expenses: [], capex: [], ancillary_revenue: [], snf_payer_mix: [] };
        const opt = (values) => values.map(v => ({ value: v, label: fmt.typeLabel(v) }));
        const saveRows = (key, rows) => {
            const clean = rows.map(({ id: _id, ...rest }) => rest);
            return saveOperatingModel('seniors_housing_assumptions_json', { ...shModelData, [key]: clean });
        };
        document.getElementById('editShUnitsBtn')?.addEventListener('click', () => {
            const columns = [
                { key: 'name', label: 'Name', type: 'text', required: true, default: '' },
                { key: 'acuity', label: 'Acuity', type: 'select', options: opt(['independent_living', 'assisted_living', 'memory_care', 'skilled_nursing']), default: 'assisted_living' },
                { key: 'unit_type', label: 'Unit Type', type: 'select', options: opt(['studio', 'one_br', 'two_br', 'semi_private', 'private', 'cottage']), default: 'studio' },
                { key: 'count', label: 'Units', type: 'number', step: '1', align: 'right', default: 0 },
                { key: 'avg_sf', label: 'Avg SF', type: 'number', step: '1', align: 'right', default: 0 },
                { key: 'monthly_base_fee', label: 'Base Fee $/mo', type: 'number', step: '1', align: 'right', default: 0 },
                { key: 'community_fee', label: 'Community Fee $', type: 'number', step: '1', align: 'right', default: 0 },
                { key: 'stabilized_occupancy', label: 'Stab. Occ.', type: 'number', step: '0.005', asPercent: true, align: 'right', default: 0.9 },
                { key: 'annual_turnover_rate', label: 'Turnover/yr', type: 'number', step: '0.01', asPercent: true, align: 'right', default: 0.4 },
                { key: 'second_person_pct', label: '2nd Person %', type: 'number', step: '0.01', asPercent: true, align: 'right', default: 0 },
                { key: 'second_person_fee_monthly', label: '2nd Person $/mo', type: 'number', step: '1', align: 'right', default: 0 },
            ];
            showBulkTableEditorModal({
                title: 'Unit mix',
                columns,
                rows: shModelData.unit_types,
                addLabel: 'Add unit type',
                intro: 'One row per unit type. Paste from a spreadsheet to fill several rows at once. Care-level tiers on existing rows are kept.',
                onSave: async ({ rows }, overlay) => {
                    if (rows.some(r => !r.name || !String(r.name).trim())) throw new Error('Each unit type needs a name.');
                    overlay.remove();
                    await saveRows('unit_types', rows);
                },
            });
        });
        document.getElementById('editShExpensesBtn')?.addEventListener('click', () => {
            const columns = [
                { key: 'name', label: 'Name', type: 'text', required: true, default: '' },
                { key: 'category', label: 'Category', type: 'select', tip: 'Expense group used for reporting, e.g. Labor, Food, Management Fee. Does not change how the amount is calculated.', options: opt(['labor', 'food', 'utilities', 'marketing', 'insurance', 'property_tax', 'management_fee', 'repairs_maintenance', 'general_admin', 'other']), default: 'other' },
                { key: 'annual_fixed', label: 'Fixed $/yr', type: 'number', step: '1', align: 'right', default: 0 },
                { key: 'per_occupied_unit_month', label: '$/Occ. Unit/mo', type: 'number', step: '0.01', align: 'right', default: 0 },
                { key: 'pct_of_revenue', label: '% of Revenue', type: 'number', step: '0.005', asPercent: true, align: 'right', default: 0 },
                { key: 'growth_pct', label: 'Growth %', type: 'number', step: '0.005', asPercent: true, align: 'right' },
            ];
            showBulkTableEditorModal({
                title: 'Operating expenses',
                columns,
                rows: shModelData.expenses,
                addLabel: 'Add expense',
                onSave: async ({ rows }, overlay) => {
                    if (rows.some(r => !r.name || !String(r.name).trim())) throw new Error('Each expense needs a name.');
                    overlay.remove();
                    await saveRows('expenses', rows);
                },
            });
        });
    }

    // --- Marina Assumptions Editing ---
    if (isMarina) {
        let marinaAssumptions = null;
        try { marinaAssumptions = JSON.parse(marinaModel.marina_assumptions_json || 'null'); } catch {}
        marinaAssumptions = marinaAssumptions || {
            slip_classes: [],
            demand: { monthly_seasonality: Array(12).fill('1.00'), monthly_weather_shock_pct: Array(12).fill('0') },
            additional_revenue_lines: [],
            operating_cost_lines: [],
            cyclical_costs: [],
            capex_lifecycle: [],
        };

        const saveMarinaAssumptions = (updated) => saveOperatingModel('marina_assumptions_json', updated);

        const SLIP_CLASS_FIELDS = [
            { type: 'section', label: 'Slip Class' },
            { key: 'name', label: 'Class Name', type: 'text', required: true, half: true },
            { key: 'kind', label: 'Kind', type: 'select', options: [
                { value: 'wet_slip', label: 'Wet Slip' },
                { value: 'dry_stack', label: 'Dry Stack' },
                { value: 'mooring', label: 'Mooring' },
            ], half: true },
            { key: 'count', label: 'Slip Count', type: 'number', required: true, step: '1', half: true },
            { key: 'length_class', label: 'Length Class', type: 'text', half: true },
            { key: 'utility_service_level', label: 'Utility Service', type: 'select', options: [
                { value: 'fifty_amp', label: '50-Amp' },
                { value: 'thirty_amp', label: '30-Amp' },
                { value: 'water_only', label: 'Water Only' },
                { value: 'none', label: 'None' },
            ], half: true },
            { type: 'section', label: 'Contract Mix (must sum to 1.0)' },
            { key: 'annual_contract_share', label: 'Annual Share', type: 'number', step: '0.01', half: true, asPercent: true },
            { key: 'seasonal_contract_share', label: 'Seasonal Share', type: 'number', step: '0.01', half: true, asPercent: true },
            { key: 'transient_share', label: 'Transient Share', type: 'number', step: '0.01', half: true, asPercent: true },
            { type: 'section', label: 'Rates' },
            { key: 'annual_contract_rate', label: 'Annual Rate ($/yr)', type: 'number', step: '1', half: true, asPercent: false },
            { key: 'seasonal_contract_rate', label: 'Seasonal Rate ($/season)', type: 'number', step: '1', half: true, asPercent: false },
            { key: 'transient_daily_rate', label: 'Transient ($/day)', type: 'number', step: '1', half: true, asPercent: false },
            { type: 'section', label: 'Occupancy' },
            { key: 'base_annual_occupancy', label: 'Annual Occupancy', type: 'number', step: '0.01', half: true, asPercent: true },
            { key: 'base_seasonal_occupancy', label: 'Seasonal Occupancy', type: 'number', step: '0.01', half: true, asPercent: true },
            { key: 'base_transient_capture', label: 'Transient Capture', type: 'number', step: '0.01', half: true, asPercent: true },
            { type: 'section', label: 'Ancillary Revenue Per Slip' },
            { key: 'utility_fee_monthly', label: 'Utility Fee ($/mo)', type: 'number', step: '0.01', half: true },
            { key: 'utility_fee_transient_daily', label: 'Utility Fee Transient ($/day)', type: 'number', step: '0.01', half: true },
            { key: 'repair_service_revenue_per_occupied_day', label: 'Repair Rev ($/occ day)', type: 'number', step: '0.01', half: true },
            { key: 'retail_fnb_revenue_per_occupied_day', label: 'Retail/F&B Rev ($/occ day)', type: 'number', step: '0.01', half: true },
            { key: 'storage_fee_per_month', label: 'Storage Fee ($/mo)', type: 'number', step: '0.01', half: true },
            { key: 'launch_fee_per_transient_arrival', label: 'Launch Fee ($/arrival)', type: 'number', step: '0.01', half: true },
        ];

        const DEMAND_FIELDS = [
            { key: 'annual_churn_pct', label: 'Annual Churn %', type: 'number', step: '0.01', half: true },
            { key: 'seasonal_churn_pct', label: 'Seasonal Churn %', type: 'number', step: '0.01', half: true },
            { key: 'seasonal_replacement_pct', label: 'Seasonal Replacement %', type: 'number', step: '0.01', half: true },
            { key: 'waitlist_start_count', label: 'Waitlist Start Count', type: 'number', step: '1', half: true },
            { key: 'waitlist_conversion_pct', label: 'Waitlist Conversion %', type: 'number', step: '0.01', half: true },
            { key: 'waitlist_new_demand_per_year', label: 'New Waitlist/Year', type: 'number', step: '1', half: true },
            { key: 'annual_reprice_growth_pct', label: 'Annual Rent Growth %', type: 'number', step: '0.001', half: true },
            { key: 'seasonal_reprice_growth_pct', label: 'Seasonal Rent Growth %', type: 'number', step: '0.001', half: true },
            { key: 'transient_reprice_growth_pct', label: 'Transient Rent Growth %', type: 'number', step: '0.001', half: true },
            { key: 'ancillary_growth_pct', label: 'Ancillary Growth %', type: 'number', step: '0.001', half: true },
            { key: 'vacancy_collection_loss_pct', label: 'V&C Loss %', type: 'number', step: '0.001', half: true },
            { key: 'management_fee_pct', label: 'Management Fee %', type: 'number', step: '0.001', half: true },
        ];

        const MARINA_REVENUE_SUGGESTIONS = [
            'Boat Club Memberships', 'Parking & Trailer Storage', 'Ship Store & Chandlery',
            'Boat Brokerage Commissions', 'Ice & Pumpout Services', 'Wi-Fi & Cable Subscriptions',
            'Liveaboard Premiums', 'Event & Venue Rental', 'Boat Wash & Detailing',
            'Canvas & Upholstery Shop', 'Boat Yard / Haul-Out Fees', 'Winter Shrink-Wrap',
            'Dinghy & Kayak Rental', 'Sailing School / Lessons', 'Charter Revenue Share',
            'Vending & Laundry', 'Fishing License Sales', 'Ship-to-Shore / VHF',
        ];

        const REVENUE_LINE_FIELDS = [
            { key: 'name', label: 'Revenue Source', type: 'text', required: true, suggestions: MARINA_REVENUE_SUGGESTIONS, helpText: 'Pick a standard source or type a custom name.' },
            { key: 'annual_fixed', label: 'Annual Fixed ($)', type: 'number', step: '1', half: true },
            { key: 'per_occupied_day', label: 'Per Occupied Day ($)', type: 'number', step: '0.01', half: true },
            { key: 'growth_pct', label: 'Annual Growth %', type: 'number', step: '0.001', half: true },
        ];

        const MARINA_OPEX_SUGGESTIONS = [
            'Dock Labor', 'Utilities', 'Insurance & Environmental', 'Maintenance & Repairs',
            'Security', 'Waste Management', 'Landscaping & Grounds', 'Office & Admin',
            'Marketing & Advertising', 'IT & Software', 'Property Tax', 'Dock Supplies',
            'Water Quality / Environmental Testing', 'Winter Storage Operations',
        ];

        const OPEX_LINE_FIELDS = [
            { key: 'name', label: 'Expense Name', type: 'text', required: true, suggestions: MARINA_OPEX_SUGGESTIONS, helpText: 'Pick a standard category or type a custom name.' },
            { key: 'annual_fixed', label: 'Annual Fixed ($)', type: 'number', step: '1', half: true },
            { key: 'per_occupied_day', label: 'Per Occupied Day ($)', type: 'number', step: '0.01', half: true },
            { key: 'growth_pct', label: 'Annual Growth %', type: 'number', step: '0.001', half: true },
        ];

        const MARINA_CYCLICAL_SUGGESTIONS = [
            'Dredging', 'Seawall Repair', 'Storm Damage Reserve', 'Dock Resurfacing',
            'Piling Replacement', 'Bulkhead Repair', 'Channel Marking', 'Environmental Remediation',
        ];

        const CYCLICAL_COST_FIELDS = [
            { key: 'name', label: 'Cost Name', type: 'text', required: true, suggestions: MARINA_CYCLICAL_SUGGESTIONS, helpText: 'Pick a standard item or type a custom name.' },
            { key: 'base_amount', label: 'Base Amount ($)', type: 'number', step: '1', required: true, half: true },
            { key: 'first_year', label: 'First Year', type: 'number', step: '1', required: true, half: true, helpText: 'Analysis year when cost first occurs.' },
            { key: 'every_n_years', label: 'Every N Years', type: 'number', step: '1', required: true, half: true },
            { key: 'growth_pct', label: 'Annual Growth %', type: 'number', step: '0.001', half: true },
            { key: 'treat_as_capex', label: 'Treat as CapEx (below the line)', type: 'checkbox', default: false },
        ];

        const MARINA_CAPEX_SUGGESTIONS = [
            'Floating Docks', 'Fixed Docks', 'Fuel System', 'Electrical Infrastructure',
            'Pump-Out Station', 'Travel Lift / Hoist', 'Breakwater / Wave Attenuator',
            'Parking Lot / Ramp', 'Clubhouse / Office', 'Boat Ramp',
        ];

        const CAPEX_LIFECYCLE_FIELDS = [
            { key: 'name', label: 'Item Name', type: 'text', required: true, suggestions: MARINA_CAPEX_SUGGESTIONS, helpText: 'Pick a standard item or type a custom name.' },
            { key: 'asset_type', label: 'Asset Type', type: 'text', required: true, half: true, helpText: 'e.g. floating_docks, fuel_system' },
            { key: 'base_amount', label: 'Base Amount ($)', type: 'number', step: '1', required: true, half: true },
            { key: 'first_year', label: 'First Year', type: 'number', step: '1', required: true, half: true },
            { key: 'every_n_years', label: 'Every N Years', type: 'number', step: '1', required: true, half: true },
            { key: 'growth_pct', label: 'Annual Growth %', type: 'number', step: '0.001', half: true },
        ];

        const LEGAL_TENURE_FIELDS = [
            { key: 'tenure_type', label: 'Tenure Type', type: 'select', options: [
                { value: 'fee_simple', label: 'Fee Simple' },
                { value: 'leasehold', label: 'Leasehold' },
            ], half: true },
            { key: 'annual_submerged_land_lease', label: 'Submerged Land Lease ($/yr)', type: 'number', step: '1', half: true, asPercent: false },
            { key: 'annual_permit_concession_fees', label: 'Permit / Concession Fees ($/yr)', type: 'number', step: '1', half: true, asPercent: false },
            { key: 'annual_ground_lease', label: 'Ground Lease ($/yr)', type: 'number', step: '1', half: true, asPercent: false },
        ];

        const FUEL_DOCK_FIELDS = [
            { key: 'enabled', label: 'Fuel Dock Active', type: 'checkbox', default: true },
            { key: 'fuel_sales_per_occupied_day', label: 'Fuel Sales ($/occ day)', type: 'number', step: '0.01', half: true, asPercent: false },
            { key: 'fuel_margin_pct', label: 'Fuel Margin %', type: 'number', step: '0.001', half: true },
            { key: 'annual_growth_pct', label: 'Annual Growth %', type: 'number', step: '0.001', half: true },
        ];

        // Edit slip class
        document.querySelectorAll('[data-edit-slip-class]').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.editSlipClass);
                const sc = marinaAssumptions.slip_classes[idx];
                // Convert string values to numbers for the form
                const iv = {};
                Object.entries(sc).forEach(([k, v]) => { iv[k] = v; });
                showFormModal({
                    title: `Edit ${sc.name}`,
                    fields: SLIP_CLASS_FIELDS,
                    initialValues: iv,
                    wide: true,
                    onSubmit: async (data, overlay) => {
                        // Convert numeric fields back to strings for the JSON blob
                        const updated = { ...marinaAssumptions };
                        const numKeys = ['annual_contract_share','seasonal_contract_share','transient_share',
                            'annual_contract_rate','seasonal_contract_rate','transient_daily_rate',
                            'base_annual_occupancy','base_seasonal_occupancy','base_transient_capture',
                            'utility_fee_monthly','utility_fee_transient_daily',
                            'repair_service_revenue_per_occupied_day','retail_fnb_revenue_per_occupied_day',
                            'storage_fee_per_month','launch_fee_per_transient_arrival'];
                        const newSc = { ...sc };  // the form sends only changed fields
                        Object.entries(data).forEach(([k, v]) => {
                            newSc[k] = numKeys.includes(k) ? String(v) : v;
                        });
                        newSc.count = parseInt(newSc.count);
                        updated.slip_classes[idx] = newSc;
                        overlay.remove();
                        await saveMarinaAssumptions(updated);
                    }
                });
            });
        });

        // Add slip class
        const addSlipBtn = document.getElementById('addSlipClassBtn');
        if (addSlipBtn) {
            addSlipBtn.addEventListener('click', () => {
                showFormModal({
                    title: 'Add Slip Class',
                    fields: SLIP_CLASS_FIELDS,
                    wide: true,
                    onSubmit: async (data, overlay) => {
                        const updated = { ...marinaAssumptions };
                        const numKeys = ['annual_contract_share','seasonal_contract_share','transient_share',
                            'annual_contract_rate','seasonal_contract_rate','transient_daily_rate',
                            'base_annual_occupancy','base_seasonal_occupancy','base_transient_capture',
                            'utility_fee_monthly','utility_fee_transient_daily',
                            'repair_service_revenue_per_occupied_day','retail_fnb_revenue_per_occupied_day',
                            'storage_fee_per_month','launch_fee_per_transient_arrival'];
                        const newSc = {};
                        Object.entries(data).forEach(([k, v]) => {
                            newSc[k] = numKeys.includes(k) ? String(v) : v;
                        });
                        newSc.count = parseInt(newSc.count);
                        updated.slip_classes.push(newSc);
                        overlay.remove();
                        await saveMarinaAssumptions(updated);
                    }
                });
            });
        }

        // Edit demand assumptions
        const editDemandBtn = document.getElementById('editMarinaDemandBtn');
        if (editDemandBtn) {
            editDemandBtn.addEventListener('click', () => {
                showFormModal({
                    title: 'Edit Demand & Growth Assumptions',
                    fields: DEMAND_FIELDS,
                    initialValues: marinaAssumptions.demand || {},
                    onSubmit: async (data, overlay) => {
                        const updated = { ...marinaAssumptions };
                        const newDemand = { ...(marinaAssumptions.demand || {}) };
                        Object.entries(data).forEach(([k, v]) => { newDemand[k] = String(v); });
                        updated.demand = newDemand;
                        overlay.remove();
                        await saveMarinaAssumptions(updated);
                    }
                });
            });
        }

        // Edit opex lines
        // --- Additional Revenue CRUD ---
        document.querySelectorAll('[data-edit-revenue-line]').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.editRevenueLine);
                const line = marinaAssumptions.additional_revenue_lines[idx];
                showFormModal({
                    title: `Edit ${line.name}`,
                    fields: REVENUE_LINE_FIELDS,
                    initialValues: line,
                    onSubmit: async (data, overlay) => {
                        const updated = { ...marinaAssumptions };
                        const newLine = { ...line };
                        Object.entries(data).forEach(([k, v]) => { newLine[k] = typeof v === 'number' ? String(v) : v; });
                        updated.additional_revenue_lines[idx] = newLine;
                        overlay.remove();
                        await saveMarinaAssumptions(updated);
                    }
                });
            });
        });

        document.querySelectorAll('[data-delete-revenue-line]').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.deleteRevenueLine);
                const line = marinaAssumptions.additional_revenue_lines[idx];
                showDeleteConfirm(line.name, async () => {
                    const updated = { ...marinaAssumptions };
                    updated.additional_revenue_lines.splice(idx, 1);
                    await saveMarinaAssumptions(updated);
                });
            });
        });

        const addRevenueBtn = document.getElementById('addRevenueLineBtn');
        if (addRevenueBtn) {
            addRevenueBtn.addEventListener('click', () => {
                showFormModal({
                    title: 'Add Revenue Source',
                    fields: REVENUE_LINE_FIELDS,
                    onSubmit: async (data, overlay) => {
                        const updated = { ...marinaAssumptions };
                        const newLine = {};
                        Object.entries(data).forEach(([k, v]) => { newLine[k] = typeof v === 'number' ? String(v) : v; });
                        if (!updated.additional_revenue_lines) updated.additional_revenue_lines = [];
                        updated.additional_revenue_lines.push(newLine);
                        overlay.remove();
                        await saveMarinaAssumptions(updated);
                    }
                });
            });
        }

        // --- OpEx CRUD ---
        document.querySelectorAll('[data-edit-opex-line]').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.editOpexLine);
                const line = marinaAssumptions.operating_cost_lines[idx];
                showFormModal({
                    title: `Edit ${line.name}`,
                    fields: OPEX_LINE_FIELDS,
                    initialValues: line,
                    onSubmit: async (data, overlay) => {
                        const updated = { ...marinaAssumptions };
                        const newLine = { ...line };
                        Object.entries(data).forEach(([k, v]) => { newLine[k] = typeof v === 'number' ? String(v) : v; });
                        updated.operating_cost_lines[idx] = newLine;
                        overlay.remove();
                        await saveMarinaAssumptions(updated);
                    }
                });
            });
        });

        // Delete opex lines
        document.querySelectorAll('[data-delete-opex-line]').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.deleteOpexLine);
                const line = marinaAssumptions.operating_cost_lines[idx];
                showDeleteConfirm(line.name, async () => {
                    const updated = { ...marinaAssumptions };
                    updated.operating_cost_lines.splice(idx, 1);
                    await saveMarinaAssumptions(updated);
                });
            });
        });

        // Add opex line
        const addOpexBtn = document.getElementById('addOpexLineBtn');
        if (addOpexBtn) {
            addOpexBtn.addEventListener('click', () => {
                showFormModal({
                    title: 'Add Operating Cost Line',
                    fields: OPEX_LINE_FIELDS,
                    onSubmit: async (data, overlay) => {
                        const updated = { ...marinaAssumptions };
                        const newLine = {};
                        Object.entries(data).forEach(([k, v]) => { newLine[k] = typeof v === 'number' ? String(v) : v; });
                        if (!updated.operating_cost_lines) updated.operating_cost_lines = [];
                        updated.operating_cost_lines.push(newLine);
                        overlay.remove();
                        await saveMarinaAssumptions(updated);
                    }
                });
            });
        }

        // --- Cyclical Costs CRUD ---
        document.querySelectorAll('[data-edit-cyclical]').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.editCyclical);
                const cost = marinaAssumptions.cyclical_costs[idx];
                showFormModal({
                    title: `Edit ${cost.name}`,
                    fields: CYCLICAL_COST_FIELDS,
                    initialValues: cost,
                    onSubmit: async (data, overlay) => {
                        const updated = { ...marinaAssumptions };
                        const entry = { ...cost };
                        Object.entries(data).forEach(([k, v]) => {
                            if (k === 'treat_as_capex') entry[k] = !!v;
                            else entry[k] = typeof v === 'number' ? String(v) : v;
                        });
                        updated.cyclical_costs[idx] = entry;
                        overlay.remove();
                        await saveMarinaAssumptions(updated);
                    }
                });
            });
        });

        document.querySelectorAll('[data-delete-cyclical]').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.deleteCyclical);
                const cost = marinaAssumptions.cyclical_costs[idx];
                showDeleteConfirm(cost.name, async () => {
                    const updated = { ...marinaAssumptions };
                    updated.cyclical_costs.splice(idx, 1);
                    await saveMarinaAssumptions(updated);
                });
            });
        });

        const addCyclicalBtn = document.getElementById('addCyclicalBtn');
        if (addCyclicalBtn) {
            addCyclicalBtn.addEventListener('click', () => {
                showFormModal({
                    title: 'Add Cyclical Cost',
                    fields: CYCLICAL_COST_FIELDS,
                    onSubmit: async (data, overlay) => {
                        const updated = { ...marinaAssumptions };
                        const entry = {};
                        Object.entries(data).forEach(([k, v]) => {
                            if (k === 'treat_as_capex') entry[k] = !!v;
                            else entry[k] = typeof v === 'number' ? String(v) : v;
                        });
                        if (!updated.cyclical_costs) updated.cyclical_costs = [];
                        updated.cyclical_costs.push(entry);
                        overlay.remove();
                        await saveMarinaAssumptions(updated);
                    }
                });
            });
        }

        // --- CapEx Lifecycle CRUD ---
        document.querySelectorAll('[data-edit-capex-lifecycle]').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.editCapexLifecycle);
                const item = marinaAssumptions.capex_lifecycle[idx];
                showFormModal({
                    title: `Edit ${item.name}`,
                    fields: CAPEX_LIFECYCLE_FIELDS,
                    initialValues: item,
                    onSubmit: async (data, overlay) => {
                        const updated = { ...marinaAssumptions };
                        const entry = { ...item };
                        Object.entries(data).forEach(([k, v]) => { entry[k] = typeof v === 'number' ? String(v) : v; });
                        updated.capex_lifecycle[idx] = entry;
                        overlay.remove();
                        await saveMarinaAssumptions(updated);
                    }
                });
            });
        });

        document.querySelectorAll('[data-delete-capex-lifecycle]').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = parseInt(btn.dataset.deleteCapexLifecycle);
                const item = marinaAssumptions.capex_lifecycle[idx];
                showDeleteConfirm(item.name, async () => {
                    const updated = { ...marinaAssumptions };
                    updated.capex_lifecycle.splice(idx, 1);
                    await saveMarinaAssumptions(updated);
                });
            });
        });

        const addCapexBtn = document.getElementById('addCapexLifecycleBtn');
        if (addCapexBtn) {
            addCapexBtn.addEventListener('click', () => {
                showFormModal({
                    title: 'Add CapEx Lifecycle Item',
                    fields: CAPEX_LIFECYCLE_FIELDS,
                    onSubmit: async (data, overlay) => {
                        const updated = { ...marinaAssumptions };
                        const entry = {};
                        Object.entries(data).forEach(([k, v]) => { entry[k] = typeof v === 'number' ? String(v) : v; });
                        if (!updated.capex_lifecycle) updated.capex_lifecycle = [];
                        updated.capex_lifecycle.push(entry);
                        overlay.remove();
                        await saveMarinaAssumptions(updated);
                    }
                });
            });
        }

        // --- Legal Tenure Edit ---
        const editLegalBtn = document.getElementById('editLegalTenureBtn');
        if (editLegalBtn) {
            editLegalBtn.addEventListener('click', () => {
                showFormModal({
                    title: 'Edit Legal Tenure',
                    fields: LEGAL_TENURE_FIELDS,
                    initialValues: marinaAssumptions.legal_tenure || {},
                    onSubmit: async (data, overlay) => {
                        const updated = { ...marinaAssumptions };
                        const entry = { ...(marinaAssumptions.legal_tenure || {}) };
                        Object.entries(data).forEach(([k, v]) => {
                            entry[k] = typeof v === 'number' ? String(v) : v;
                        });
                        updated.legal_tenure = entry;
                        overlay.remove();
                        await saveMarinaAssumptions(updated);
                    }
                });
            });
        }

        // --- Fuel Dock Edit ---
        const editFuelBtn = document.getElementById('editFuelDockBtn');
        if (editFuelBtn) {
            editFuelBtn.addEventListener('click', () => {
                showFormModal({
                    title: 'Edit Fuel Dock',
                    fields: FUEL_DOCK_FIELDS,
                    initialValues: marinaAssumptions.fuel_dock || {},
                    onSubmit: async (data, overlay) => {
                        const updated = { ...marinaAssumptions };
                        const entry = { ...(marinaAssumptions.fuel_dock || {}) };
                        Object.entries(data).forEach(([k, v]) => {
                            if (k === 'enabled') entry[k] = !!v;
                            else entry[k] = typeof v === 'number' ? String(v) : v;
                        });
                        updated.fuel_dock = entry;
                        overlay.remove();
                        await saveMarinaAssumptions(updated);
                    }
                });
            });
        }
    }

    // Marina CF table expandable rows (top-level)
    document.querySelectorAll('#marinaCfTable tr.expandable').forEach(row => {
        row.querySelector('td').addEventListener('click', () => {
            const groupId = row.dataset.toggle;
            const isExpanded = row.classList.toggle('expanded');
            document.querySelectorAll(`#marinaCfTable tr.sub-row[data-group="${groupId}"]`).forEach(sub => {
                sub.classList.toggle('visible', isExpanded);
                // Collapse nested sub-sub-rows when parent collapses
                if (!isExpanded && sub.dataset.toggle) {
                    sub.classList.remove('expanded');
                    document.querySelectorAll(`#marinaCfTable tr.sub-sub-row[data-group="${sub.dataset.toggle}"]`).forEach(ss => {
                        ss.classList.remove('visible');
                    });
                }
            });
        });
    });
    // Marina CF table expandable sub-rows (second level)
    document.querySelectorAll('#marinaCfTable tr.expandable-sub').forEach(row => {
        row.querySelector('td').addEventListener('click', (e) => {
            e.stopPropagation();
            const subGroupId = row.dataset.toggle;
            const isExpanded = row.classList.toggle('expanded');
            document.querySelectorAll(`#marinaCfTable tr.sub-sub-row[data-group="${subGroupId}"]`).forEach(ss => {
                ss.classList.toggle('visible', isExpanded);
            });
        });
    });

    // Seniors housing CF table expandable rows
    wireSeniorsHousingCfToggle();
}


function renderMarinaSlipTab(property, cfRows, valuation) {
    const totalSlips = parseFloat(property.total_area);

    // Parse actual assumptions from valuation JSON, or fall back to defaults
    let assumptions = null;
    if (valuation && valuation.marina_assumptions_json) {
        try { assumptions = JSON.parse(valuation.marina_assumptions_json); } catch {}
    }

    const slipClasses = assumptions ? assumptions.slip_classes : [];
    const demand = assumptions ? assumptions.demand : {};

    const utilityLabels = { fifty_amp: '50-Amp', thirty_amp: '30-Amp', water_only: 'Water Only', none: 'None' };

    const slipRows = slipClasses.map((s, i) => `<tr>
        <td><button class="btn-icon" data-edit-slip-class="${i}" title="Edit slip class">${icons.edit}</button></td>
        <td class="tenant-name">${escapeHtmlAttr(s.name)}</td>
        <td>${s.kind ? fmt.typeLabel(s.kind) : '—'}</td>
        <td>${s.length_class || '—'}</td>
        <td>${utilityLabels[s.utility_service_level] || s.utility_service_level || '—'}</td>
        <td class="mono right">${s.count}</td>
        <td class="mono right">${fmt.pct(s.base_annual_occupancy)}</td>
        <td class="mono right">${fmt.currencyExact(s.annual_contract_rate)}</td>
        <td class="mono right">${fmt.currencyExact(s.seasonal_contract_rate)}</td>
        <td class="mono right">${fmt.currencyExact(s.transient_daily_rate)}/day</td>
        <td class="mono right">${fmt.pct(s.annual_contract_share)}</td>
        <td class="mono right">${fmt.pct(s.seasonal_contract_share)}</td>
        <td class="mono right">${fmt.pct(s.transient_share)}</td>
    </tr>`).join('');

    const computedSlipTotal = slipClasses.reduce((s, c) => s + (parseInt(c.count) || 0), 0);

    // Demand assumptions card
    const demandHtml = assumptions ? `
        <div class="section-header" style="margin-top:32px">
            <h3 class="section-title">Demand & Growth Assumptions</h3>
            <button class="btn btn-secondary btn-sm" id="editMarinaDemandBtn">${icons.edit} Edit</button>
        </div>
        <div class="kpi-row" style="margin-bottom:12px">
            <div class="kpi-card"><div class="kpi-label">Annual Churn</div><div class="kpi-value">${fmt.pct(demand.annual_churn_pct)}</div></div>
            <div class="kpi-card"><div class="kpi-label">Seasonal Churn</div><div class="kpi-value">${fmt.pct(demand.seasonal_churn_pct)}</div></div>
            <div class="kpi-card"><div class="kpi-label">Seasonal Replacement</div><div class="kpi-value">${fmt.pct(demand.seasonal_replacement_pct)}</div></div>
            <div class="kpi-card"><div class="kpi-label">Rent Growth (Annual)</div><div class="kpi-value">${fmt.pct(demand.annual_reprice_growth_pct)}</div></div>
            <div class="kpi-card"><div class="kpi-label">V&C Loss</div><div class="kpi-value">${fmt.pct(demand.vacancy_collection_loss_pct)}</div></div>
            <div class="kpi-card"><div class="kpi-label">Mgmt Fee</div><div class="kpi-value">${fmt.pct(demand.management_fee_pct)}</div></div>
            <div class="kpi-card"><div class="kpi-label">Ancillary Growth</div><div class="kpi-value">${fmt.pct(demand.ancillary_growth_pct)}</div></div>
        </div>` : '';

    // Revenue breakdown from Y1 cash flow
    const y1 = cfRows[0];
    let revenueHtml = '';
    if (y1) {
        const gpi = parseFloat(y1.gross_potential_income || 0);
        const otherIncome = parseFloat(y1.other_income || 0);
        const otherDetail = y1.other_income_detail || {};
        const perSlipAncillary = parseFloat(otherDetail.per_slip_ancillary || 0);
        const additionalRev = parseFloat(otherDetail.additional_revenue || 0);
        const dockageRev = gpi - otherIncome;
        revenueHtml = `
        <div class="section-header" style="margin-top:32px">
            <h3 class="section-title">Year 1 Revenue Summary</h3>
        </div>
        <div class="data-table-wrap" style="max-width:500px">
            <table class="data-table">
                <thead><tr><th>Line Item</th><th class="right">Amount</th></tr></thead>
                <tbody>
                    <tr><td class="tenant-name">Dockage Revenue</td><td class="mono right">${fmt.currencyExact(dockageRev)}</td></tr>
                    <tr><td class="tenant-name">Per-Slip Ancillary</td><td class="mono right">${fmt.currencyExact(perSlipAncillary)}</td></tr>
                    ${additionalRev > 0 ? `<tr><td class="tenant-name">Additional Revenue</td><td class="mono right">${fmt.currencyExact(additionalRev)}</td></tr>` : ''}
                    <tr style="border-top:2px solid var(--border);font-weight:600"><td>Potential Gross Revenue</td><td class="mono right">${fmt.currencyExact(gpi)}</td></tr>
                    <tr><td>Vacancy & Collection Loss</td><td class="mono right" style="color:var(--text-secondary)">${fmt.currencyExact(parseFloat(y1.general_vacancy_loss || 0))}</td></tr>
                    <tr style="border-top:2px solid var(--border);font-weight:600"><td>Effective Gross Income</td><td class="mono right" style="color:var(--accent)">${fmt.currencyExact(parseFloat(y1.effective_gross_income || 0))}</td></tr>
                </tbody>
            </table>
        </div>`;
    }

    const noAssumptionsMsg = !assumptions
        ? '<div class="page-subtitle" style="margin-top:16px;color:var(--text-tertiary)">No slip classes yet. Valuations use generic marina defaults sized to the slip count until you add them.</div>'
        : '';

    return `
        <div class="section-header">
            <h3 class="section-title">Slip Inventory</h3>
            <button class="btn btn-primary btn-sm" id="addSlipClassBtn">${icons.plus} Add Slip Class</button>
        </div>
        <div class="page-subtitle" style="margin-bottom:12px">Total: <strong>${fmt.num(computedSlipTotal || totalSlips)} slips</strong> across ${slipClasses.length} classes.</div>
        ${noAssumptionsMsg}
        ${slipClasses.length > 0 ? `
        <div class="data-table-wrap" style="overflow-x:auto">
            <table class="data-table">
                <thead><tr>
                    <th></th>
                    <th>Class Name</th><th>Kind</th><th>Length</th><th>Utility</th>
                    <th class="right">Count</th><th class="right">Occupancy</th>
                    <th class="right">Annual Rate</th><th class="right">Seasonal Rate</th><th class="right">Transient Rate</th>
                    <th class="right">Annual %</th><th class="right">Seasonal %</th><th class="right">Transient %</th>
                </tr></thead>
                <tbody>${slipRows}</tbody>
                <tfoot><tr>
                    <td colspan="5" style="text-align:right;font-weight:600">Total Slips</td>
                    <td class="mono right" style="font-weight:600">${fmt.num(computedSlipTotal)}</td>
                    <td colspan="7"></td>
                </tr></tfoot>
            </table>
        </div>` : ''}
        ${demandHtml}
        ${revenueHtml}
        ${!y1 && assumptions ? '<div class="page-subtitle" style="margin-top:24px;color:var(--text-tertiary)">Run a valuation to see revenue projections.</div>' : ''}
    `;
}

function renderMarinaOperatingTab(property, cfRows, valuation) {
    let assumptions = null;
    if (valuation && valuation.marina_assumptions_json) {
        try { assumptions = JSON.parse(valuation.marina_assumptions_json); } catch {}
    }

    // OpEx assumptions table (even without completed valuation)
    const revenueLines = assumptions ? (assumptions.additional_revenue_lines || []) : [];
    const opexLines = assumptions ? (assumptions.operating_cost_lines || []) : [];
    const cyclicalCosts = assumptions ? (assumptions.cyclical_costs || []) : [];
    const legalTenure = assumptions ? (assumptions.legal_tenure || {}) : {};
    const capex = assumptions ? (assumptions.capex_lifecycle || []) : [];
    const fuelDock = assumptions ? (assumptions.fuel_dock || {}) : {};

    let assumptionsHtml = '';
    if (assumptions) {
        const revenueRows = revenueLines.map((line, i) => `<tr>
            <td><button class="btn-icon" data-edit-revenue-line="${i}" title="Edit">${icons.edit}</button>
                <button class="btn-icon danger" data-delete-revenue-line="${i}" title="Delete">${icons.trash}</button></td>
            <td class="tenant-name">${escapeHtmlAttr(line.name)}</td>
            <td class="mono right">${fmt.currencyExact(line.annual_fixed)}</td>
            <td class="mono right">${line.per_occupied_day ? '$' + parseFloat(line.per_occupied_day).toFixed(2) + '/day' : '—'}</td>
            <td class="mono right">${fmt.pct(line.growth_pct)}</td>
        </tr>`).join('');

        const opexRows = opexLines.map((line, i) => `<tr>
            <td><button class="btn-icon" data-edit-opex-line="${i}" title="Edit">${icons.edit}</button>
                <button class="btn-icon danger" data-delete-opex-line="${i}" title="Delete">${icons.trash}</button></td>
            <td class="tenant-name">${escapeHtmlAttr(line.name)}</td>
            <td class="mono right">${fmt.currencyExact(line.annual_fixed)}</td>
            <td class="mono right">${line.per_occupied_day ? '$' + parseFloat(line.per_occupied_day).toFixed(2) + '/day' : '—'}</td>
            <td class="mono right">${fmt.pct(line.growth_pct)}</td>
        </tr>`).join('');

        const cyclicalRows = cyclicalCosts.map((c, i) => `<tr>
            <td><button class="btn-icon" data-edit-cyclical="${i}" title="Edit">${icons.edit}</button>
                <button class="btn-icon danger" data-delete-cyclical="${i}" title="Delete">${icons.trash}</button></td>
            <td class="tenant-name">${escapeHtmlAttr(c.name)}</td>
            <td class="mono right">${fmt.currencyExact(c.base_amount)}</td>
            <td class="mono right">Year ${c.first_year}</td>
            <td class="mono right">Every ${c.every_n_years} yrs</td>
            <td class="mono right">${fmt.pct(c.growth_pct)}</td>
            <td>${c.treat_as_capex ? 'CapEx' : 'OpEx'}</td>
        </tr>`).join('');

        const capexRows = capex.map((c, i) => `<tr>
            <td><button class="btn-icon" data-edit-capex-lifecycle="${i}" title="Edit">${icons.edit}</button>
                <button class="btn-icon danger" data-delete-capex-lifecycle="${i}" title="Delete">${icons.trash}</button></td>
            <td class="tenant-name">${escapeHtmlAttr(c.name)}</td>
            <td class="mono right">${fmt.currencyExact(c.base_amount)}</td>
            <td class="mono right">Year ${c.first_year}</td>
            <td class="mono right">Every ${c.every_n_years} yrs</td>
            <td class="mono right">${fmt.pct(c.growth_pct)}</td>
        </tr>`).join('');

        assumptionsHtml = `
        <div class="section-header" style="margin-top:32px">
            <h3 class="section-title">Additional Revenue Sources</h3>
            <button class="btn btn-primary btn-sm" id="addRevenueLineBtn">${icons.plus} Add Revenue</button>
        </div>
        ${revenueLines.length > 0 ? `
        <div class="data-table-wrap">
            <table class="data-table">
                <thead><tr><th></th><th>Revenue Source</th><th class="right">Annual Fixed</th><th class="right">Per Occ. Day</th><th class="right">Growth</th></tr></thead>
                <tbody>${revenueRows}</tbody>
            </table>
        </div>` : '<div class="page-subtitle" style="color:var(--text-tertiary)">No additional revenue lines. Per-slip revenue (utility, repair, retail/F&B, storage, launch) is configured on the Slip Inventory tab. Add sources like boat club memberships, parking, ship store, etc.</div>'}

        <div class="section-header" style="margin-top:32px">
            <h3 class="section-title">Operating Cost Assumptions</h3>
            <button class="btn btn-primary btn-sm" id="addOpexLineBtn">${icons.plus} Add Line</button>
        </div>
        ${opexLines.length > 0 ? `
        <div class="data-table-wrap">
            <table class="data-table">
                <thead><tr><th></th><th>Expense Line</th><th class="right">Annual Fixed</th><th class="right">Per Occ. Day</th><th class="right">Growth</th></tr></thead>
                <tbody>${opexRows}</tbody>
            </table>
        </div>` : '<div class="page-subtitle" style="color:var(--text-tertiary)">No operating cost lines. Click Add Line to create one.</div>'}

        <div class="section-header" style="margin-top:28px">
            <h3 class="section-title">Legal Tenure</h3>
        </div>
        <div class="data-table-wrap">
            <table class="data-table">
                <thead><tr><th></th><th>Tenure Type</th><th class="right">Ground Lease</th><th class="right">Submerged Land</th><th class="right">Permits / Concessions</th><th class="right">Remaining Years</th><th class="right">Extension Prob.</th></tr></thead>
                <tbody>
                    <tr>
                        <td><button class="btn-icon" id="editLegalTenureBtn" title="Edit">${icons.edit}</button></td>
                        <td class="tenant-name">${fmt.typeLabel(legalTenure.tenure_type || 'fee_simple')}</td>
                        <td class="mono right">${parseFloat(legalTenure.annual_ground_lease || 0) > 0 ? fmt.currencyExact(legalTenure.annual_ground_lease) + '/yr' : '—'}</td>
                        <td class="mono right">${parseFloat(legalTenure.annual_submerged_land_lease || 0) > 0 ? fmt.currencyExact(legalTenure.annual_submerged_land_lease) + '/yr' : '—'}</td>
                        <td class="mono right">${parseFloat(legalTenure.annual_permit_concession_fees || 0) > 0 ? fmt.currencyExact(legalTenure.annual_permit_concession_fees) + '/yr' : '—'}</td>
                        <td class="mono right">${legalTenure.remaining_lease_years ? legalTenure.remaining_lease_years + ' yrs' : '—'}</td>
                        <td class="mono right">${legalTenure.lease_extension_probability ? fmt.pct(legalTenure.lease_extension_probability) : '—'}</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <div class="section-header" style="margin-top:28px">
            <h3 class="section-title">Fuel Dock</h3>
        </div>
        <div class="data-table-wrap">
            <table class="data-table">
                <thead><tr><th></th><th>Status</th><th class="right">Sales / Occ. Day</th><th class="right">Margin</th><th class="right">Growth</th></tr></thead>
                <tbody>
                    <tr>
                        <td><button class="btn-icon" id="editFuelDockBtn" title="Edit">${icons.edit}</button></td>
                        <td class="tenant-name">${fuelDock.enabled ? 'Active' : 'Disabled'}</td>
                        <td class="mono right">${fuelDock.enabled ? '$' + parseFloat(fuelDock.fuel_sales_per_occupied_day || 0).toFixed(2) : '—'}</td>
                        <td class="mono right">${fuelDock.enabled ? fmt.pct(fuelDock.fuel_margin_pct) : '—'}</td>
                        <td class="mono right">${fuelDock.enabled ? fmt.pct(fuelDock.annual_growth_pct) : '—'}</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <div class="section-header" style="margin-top:28px">
            <h3 class="section-title">Cyclical Costs</h3>
            <button class="btn btn-primary btn-sm" id="addCyclicalBtn">${icons.plus} Add Cyclical Cost</button>
        </div>
        ${cyclicalCosts.length > 0 ? `
        <div class="data-table-wrap">
            <table class="data-table">
                <thead><tr><th></th><th>Item</th><th class="right">Base Amount</th><th class="right">First Year</th><th class="right">Cycle</th><th class="right">Growth</th><th>Type</th></tr></thead>
                <tbody>${cyclicalRows}</tbody>
            </table>
        </div>` : '<div class="page-subtitle" style="color:var(--text-tertiary)">No cyclical costs. Click Add to create one (e.g. dredging, seawall repair).</div>'}

        <div class="section-header" style="margin-top:28px">
            <h3 class="section-title">CapEx Lifecycle</h3>
            <button class="btn btn-primary btn-sm" id="addCapexLifecycleBtn">${icons.plus} Add CapEx Item</button>
        </div>
        ${capex.length > 0 ? `
        <div class="data-table-wrap">
            <table class="data-table">
                <thead><tr><th></th><th>Item</th><th class="right">Base Amount</th><th class="right">First Year</th><th class="right">Cycle</th><th class="right">Growth</th></tr></thead>
                <tbody>${capexRows}</tbody>
            </table>
        </div>` : '<div class="page-subtitle" style="color:var(--text-tertiary)">No CapEx lifecycle items. Click Add to create one (e.g. dock replacement, fuel system).</div>'}
        `;
    }

    if (cfRows.length === 0) {
        return `
            <div class="section-header"><h3 class="section-title">Operating Budget</h3></div>
            <div class="page-subtitle" style="color:var(--text-tertiary)">Run a valuation to see marina operating projections.</div>
            ${assumptionsHtml}
        `;
    }

    const y1 = cfRows[0];
    const opex = Math.abs(parseFloat(y1.operating_expenses || 0));
    const noi = parseFloat(y1.net_operating_income || 0);
    const egi = parseFloat(y1.effective_gross_income || 0);
    const opexRatio = egi > 0 ? (opex / egi * 100).toFixed(1) : '—';

    // Build year-by-year summary table
    const yearHeaders = cfRows.map(cf => `<th class="right">Year ${cf.year}</th>`).join('');
    const makeRow = (label, accessor, negative, cls = '') => {
        const cells = cfRows.map(cf => {
            const v = parseFloat(accessor(cf) || 0);
            const display = negative ? -v : v;
            return `<td class="mono right">${fmt.currencyExact(display)}</td>`;
        }).join('');
        return `<tr class="${cls}"><td class="tenant-name">${label}</td>${cells}</tr>`;
    };

    const slipClasses = (cfRows[0] || {}).slip_class_detail || [];
    const hasSlipDetail = slipClasses.length > 0;

    const hasBalloon = cfRows.some(cf => parseFloat(cf.balloon_payment || 0) !== 0);

    return `
        <div class="section-header"><h3 class="section-title">Operating Budget</h3></div>
        <div class="page-subtitle" style="margin-bottom:12px">
            Operating expenses are generated by the marina valuation engine. Year 1 operating expense ratio: <strong>${opexRatio}%</strong> of EGI.
        </div>
        <div class="kpi-row" style="margin-bottom:24px">
            <div class="kpi-card">
                <div class="kpi-label">Y1 Gross Revenue</div>
                <div class="kpi-value">${fmt.currencyExact(parseFloat(y1.gross_potential_income || 0))}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Y1 Operating Expenses</div>
                <div class="kpi-value">${fmt.currencyExact(opex)}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Y1 NOI</div>
                <div class="kpi-value green">${fmt.currencyExact(noi)}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">OpEx Ratio</div>
                <div class="kpi-value">${opexRatio}%</div>
            </div>
        </div>
        <div class="data-table-wrap" style="overflow-x:auto">
            <table class="data-table marina-cf-table" id="marinaCfTable">
                <thead><tr><th>Line Item</th>${yearHeaders}</tr></thead>
                <tbody>
                    <tr class="section-divider"><td colspan="${cfRows.length + 1}" style="font-weight:600;padding-top:12px;color:var(--text-secondary)">Revenue</td></tr>
                    ${(() => {
                        if (!hasSlipDetail) return makeRow('Dockage Revenue', cf => cf.gross_potential_rent, false);
                        const groupId = 'marina_dockage';
                        let html = `<tr class="expandable" data-toggle="${groupId}">
                            <td class="tenant-name"><span class="expand-chevron">&#9654;</span>Dockage Revenue</td>
                            ${cfRows.map(cf => `<td class="mono right">${fmt.currencyExact(parseFloat(cf.gross_potential_rent || 0))}</td>`).join('')}
                        </tr>`;
                        const dockageTypes = [
                            { label: 'Annual Contracts', field: 'annual_contract_revenue' },
                            { label: 'Seasonal Contracts', field: 'seasonal_contract_revenue' },
                            { label: 'Transient', field: 'transient_revenue' },
                        ];
                        dockageTypes.forEach(dt => {
                            const total = cfRows.map(cf => {
                                return (cf.slip_class_detail || []).reduce((s, sc) => s + parseFloat(sc[dt.field] || 0), 0);
                            });
                            if (total.every(v => v === 0)) return;
                            // Check which slip classes have non-zero values for this type
                            const activeSlips = slipClasses.filter(sc => {
                                return cfRows.some(cf => {
                                    const d = (cf.slip_class_detail || []).find(x => x.slip_class_name === sc.slip_class_name);
                                    return d && parseFloat(d[dt.field] || 0) !== 0;
                                });
                            });
                            const subGroupId = `marina_dock_${dt.field}`;
                            if (activeSlips.length > 1) {
                                html += `<tr class="sub-row expandable-sub" data-group="${groupId}" data-toggle="${subGroupId}">
                                    <td style="padding-left:40px;font-style:italic"><span class="expand-chevron">&#9654;</span>${dt.label}</td>
                                    ${total.map(v => `<td class="mono right">${fmt.currencyExact(v)}</td>`).join('')}
                                </tr>`;
                                activeSlips.forEach(sc => {
                                    const vals = cfRows.map(cf => {
                                        const d = (cf.slip_class_detail || []).find(x => x.slip_class_name === sc.slip_class_name);
                                        return d ? parseFloat(d[dt.field] || 0) : 0;
                                    });
                                    html += `<tr class="sub-sub-row" data-group="${subGroupId}">
                                        <td style="padding-left:60px;font-style:italic">${escapeHtmlAttr(sc.slip_class_name)} <span style="font-size:0.67rem;opacity:0.6">${fmt.typeLabel(sc.kind)}</span></td>
                                        ${vals.map(v => `<td class="mono right">${fmt.currencyExact(v)}</td>`).join('')}
                                    </tr>`;
                                });
                            } else {
                                html += `<tr class="sub-row" data-group="${groupId}">
                                    <td style="padding-left:40px;font-style:italic">${dt.label}</td>
                                    ${total.map(v => `<td class="mono right">${fmt.currencyExact(v)}</td>`).join('')}
                                </tr>`;
                            }
                        });
                        return html;
                    })()}
                    ${(() => {
                        if (!hasSlipDetail) return makeRow('Ancillary Income', cf => cf.other_income, false);
                        const groupId = 'marina_ancillary';
                        let html = `<tr class="expandable" data-toggle="${groupId}">
                            <td class="tenant-name"><span class="expand-chevron">&#9654;</span>Ancillary Income</td>
                            ${cfRows.map(cf => `<td class="mono right">${fmt.currencyExact(parseFloat(cf.other_income || 0))}</td>`).join('')}
                        </tr>`;
                        const ancTypes = [
                            { label: 'Utility Charges', field: 'utility_revenue' },
                            { label: 'Repair & Service', field: 'repair_service_revenue' },
                            { label: 'Retail / F&B', field: 'retail_fnb_revenue' },
                            { label: 'Storage Fees', field: 'storage_revenue' },
                            { label: 'Launch Fees', field: 'launch_fee_revenue' },
                        ];
                        ancTypes.forEach(at => {
                            const total = cfRows.map(cf => {
                                return (cf.slip_class_detail || []).reduce((s, sc) => s + parseFloat(sc[at.field] || 0), 0);
                            });
                            if (total.every(v => v === 0)) return;
                            const activeSlips = slipClasses.filter(sc => {
                                return cfRows.some(cf => {
                                    const d = (cf.slip_class_detail || []).find(x => x.slip_class_name === sc.slip_class_name);
                                    return d && parseFloat(d[at.field] || 0) !== 0;
                                });
                            });
                            const subGroupId = `marina_anc_${at.field}`;
                            if (activeSlips.length > 1) {
                                html += `<tr class="sub-row expandable-sub" data-group="${groupId}" data-toggle="${subGroupId}">
                                    <td style="padding-left:40px;font-style:italic"><span class="expand-chevron">&#9654;</span>${at.label}</td>
                                    ${total.map(v => `<td class="mono right">${fmt.currencyExact(v)}</td>`).join('')}
                                </tr>`;
                                activeSlips.forEach(sc => {
                                    const vals = cfRows.map(cf => {
                                        const d = (cf.slip_class_detail || []).find(x => x.slip_class_name === sc.slip_class_name);
                                        return d ? parseFloat(d[at.field] || 0) : 0;
                                    });
                                    html += `<tr class="sub-sub-row" data-group="${subGroupId}">
                                        <td style="padding-left:60px;font-style:italic">${escapeHtmlAttr(sc.slip_class_name)} <span style="font-size:0.67rem;opacity:0.6">${fmt.typeLabel(sc.kind)}</span></td>
                                        ${vals.map(v => `<td class="mono right">${fmt.currencyExact(v)}</td>`).join('')}
                                    </tr>`;
                                });
                            } else {
                                html += `<tr class="sub-row" data-group="${groupId}">
                                    <td style="padding-left:40px;font-style:italic">${at.label}</td>
                                    ${total.map(v => `<td class="mono right">${fmt.currencyExact(v)}</td>`).join('')}
                                </tr>`;
                            }
                        });
                        // Additional revenue lines (not per-slip)
                        const addlRev = cfRows.map(cf => {
                            const oid = cf.other_income_detail || {};
                            return parseFloat(oid.additional_revenue || 0);
                        });
                        if (!addlRev.every(v => v === 0)) {
                            html += `<tr class="sub-row" data-group="${groupId}">
                                <td style="padding-left:40px;font-style:italic">Additional Revenue</td>
                                ${addlRev.map(v => `<td class="mono right">${fmt.currencyExact(v)}</td>`).join('')}
                            </tr>`;
                        }
                        // Fuel margin (not per-slip)
                        const fuelRev = cfRows.map(cf => {
                            const gpi = parseFloat(cf.gross_potential_income || 0);
                            const dock = parseFloat(cf.gross_potential_rent || 0);
                            const anc = parseFloat(cf.other_income || 0);
                            return gpi - dock - anc;
                        });
                        if (!fuelRev.every(v => Math.abs(v) < 1)) {
                            html += `<tr class="sub-row" data-group="${groupId}">
                                <td style="padding-left:40px;font-style:italic">Fuel Dock Margin</td>
                                ${fuelRev.map(v => `<td class="mono right">${fmt.currencyExact(v)}</td>`).join('')}
                            </tr>`;
                        }
                        return html;
                    })()}
                    ${makeRow('Gross Potential Revenue', cf => cf.gross_potential_income, false)}
                    ${makeRow('Vacancy & Collection Loss', cf => cf.general_vacancy_loss, false)}
                    ${makeRow('Effective Gross Income', cf => cf.effective_gross_income, false, 'row-highlight')}

                    <tr class="section-divider"><td colspan="${cfRows.length + 1}" style="font-weight:600;padding-top:12px;color:var(--text-secondary)">Expenses & NOI</td></tr>
                    ${makeRow('Operating Expenses', cf => cf.operating_expenses, true)}
                    ${makeRow('Net Operating Income', cf => cf.net_operating_income, false, 'row-highlight')}

                    <tr class="section-divider"><td colspan="${cfRows.length + 1}" style="font-weight:600;padding-top:12px;color:var(--text-secondary)">Below the Line</td></tr>
                    ${makeRow('Capital Reserves', cf => cf.capital_reserves, true)}
                    ${makeRow('Capital Improvements', cf => cf.building_improvements, true)}
                    ${makeRow('Cash Flow Before Debt', cf => cf.cash_flow_before_debt, false, 'row-highlight')}
                    ${makeRow('Debt Service', cf => cf.debt_service, true)}
                    ${hasBalloon ? makeRow('Balloon Payment', cf => cf.balloon_payment, true) : ''}
                    ${makeRow('Levered Cash Flow', cf => cf.levered_cash_flow, false, 'row-highlight')}
                </tbody>
            </table>
        </div>
        ${assumptionsHtml}
    `;
}

// ─── Seniors Housing Tabs ──────────────────────────────────────

function renderSeniorsHousingUnitTab(property, cfRows, valuation) {
    let assumptions = null;
    if (valuation && valuation.seniors_housing_assumptions_json) {
        try { assumptions = JSON.parse(valuation.seniors_housing_assumptions_json); } catch {}
    }

    const unitTypes = assumptions ? (assumptions.unit_types || []) : [];
    const snfPayerMix = assumptions ? (assumptions.snf_payer_mix || []) : [];
    const totalUnits = unitTypes.reduce((s, u) => s + (parseInt(u.count) || 0), 0);

    const acuityLabels = {
        independent_living: 'Independent Living',
        assisted_living: 'Assisted Living',
        memory_care: 'Memory Care',
        skilled_nursing: 'Skilled Nursing',
    };
    const unitTypeLabels = {
        studio: 'Studio', one_br: '1BR', two_br: '2BR',
        semi_private: 'Semi-Private', private: 'Private', cottage: 'Cottage',
    };

    // Group by acuity
    const byAcuity = {};
    unitTypes.forEach(u => {
        const a = u.acuity || 'unknown';
        if (!byAcuity[a]) byAcuity[a] = [];
        byAcuity[a].push(u);
    });

    let unitTableHtml = '';
    for (const [acuity, units] of Object.entries(byAcuity)) {
        const acuityCount = units.reduce((s, u) => s + (parseInt(u.count) || 0), 0);
        unitTableHtml += `<tr class="section-divider"><td colspan="8" style="font-weight:600;padding-top:12px;color:var(--text-secondary)">${acuityLabels[acuity] || acuity} (${acuityCount} units)</td></tr>`;
        units.forEach(u => {
            const careTiers = u.care_level_tiers || [];
            const tierInfo = careTiers.length > 0
                ? careTiers.map(t => `${escapeHtmlAttr(t.name)}: ${fmt.currencyExact(parseFloat(t.monthly_surcharge))}/mo (${fmt.pct(parseFloat(t.pct_of_residents))})`).join(', ')
                : '—';
            unitTableHtml += `<tr>
                <td class="tenant-name">${escapeHtmlAttr(u.name)}</td>
                <td>${unitTypeLabels[u.unit_type] || u.unit_type || '—'}</td>
                <td class="mono right">${u.count}</td>
                <td class="mono right">${fmt.num(parseFloat(u.avg_sf || 0))} SF</td>
                <td class="mono right">${parseFloat(u.monthly_base_fee || 0) > 0 ? fmt.currencyExact(parseFloat(u.monthly_base_fee)) + '/mo' : '—'}</td>
                <td class="mono right">${fmt.pct(parseFloat(u.stabilized_occupancy || 0.9))}</td>
                <td class="mono right">${fmt.pct(parseFloat(u.annual_turnover_rate || 0))}</td>
                <td style="font-size:0.75rem;color:var(--text-tertiary)">${tierInfo}</td>
            </tr>`;
        });
    }

    // SNF payer mix
    const payerLabels = { private_pay: 'Private Pay', medicare: 'Medicare', medicaid: 'Medicaid', medicare_advantage: 'Medicare Advantage', insurance: 'Insurance' };
    let payerHtml = '';
    if (snfPayerMix.length > 0) {
        const payerRows = snfPayerMix.map(p => `<tr>
            <td class="tenant-name">${payerLabels[p.payer] || p.payer}</td>
            <td class="mono right">${fmt.pct(parseFloat(p.pct_of_days))}</td>
            <td class="mono right">${fmt.currencyExact(parseFloat(p.daily_rate))}/day</td>
            <td class="mono right">${fmt.pct(parseFloat(p.annual_rate_growth || 0))}</td>
        </tr>`).join('');
        payerHtml = `
        <div class="section-header" style="margin-top:32px">
            <h3 class="section-title">SNF Payer Mix</h3>
        </div>
        <div class="data-table-wrap" style="max-width:600px">
            <table class="data-table">
                <thead><tr><th>Payer</th><th class="right">% of Days</th><th class="right">Daily Rate</th><th class="right">Annual Growth</th></tr></thead>
                <tbody>${payerRows}</tbody>
            </table>
        </div>`;
    }

    // Y1 revenue summary from cash flows
    let revenueHtml = '';
    const y1 = cfRows[0];
    if (y1) {
        const otherDetail = y1.other_income_detail || {};
        revenueHtml = `
        <div class="section-header" style="margin-top:32px">
            <h3 class="section-title">Year 1 Revenue Summary</h3>
        </div>
        <div class="data-table-wrap" style="max-width:500px">
            <table class="data-table">
                <thead><tr><th>Line Item</th><th class="right">Amount</th></tr></thead>
                <tbody>
                    <tr><td class="tenant-name">Base Service Fees</td><td class="mono right">${fmt.currencyExact(parseFloat(y1.gross_potential_rent || 0))}</td></tr>
                    <tr><td class="tenant-name">Care Level Surcharges</td><td class="mono right">${fmt.currencyExact(parseFloat(otherDetail.care_level_revenue || 0))}</td></tr>
                    <tr><td class="tenant-name">Second Person Fees</td><td class="mono right">${fmt.currencyExact(parseFloat(otherDetail.second_person_revenue || 0))}</td></tr>
                    <tr><td class="tenant-name">Community Fees</td><td class="mono right">${fmt.currencyExact(parseFloat(otherDetail.community_fee_revenue || 0))}</td></tr>
                    <tr><td class="tenant-name">SNF Payer Revenue</td><td class="mono right">${fmt.currencyExact(parseFloat(otherDetail.snf_payer_revenue || 0))}</td></tr>
                    <tr><td class="tenant-name">Ancillary Revenue</td><td class="mono right">${fmt.currencyExact(parseFloat(otherDetail.ancillary_revenue || 0))}</td></tr>
                    <tr style="border-top:2px solid var(--border);font-weight:600"><td>Effective Gross Income</td><td class="mono right" style="color:var(--accent)">${fmt.currencyExact(parseFloat(y1.effective_gross_income || 0))}</td></tr>
                </tbody>
            </table>
        </div>`;
    }

    const noAssumptionsMsg = !assumptions
        ? '<div class="page-subtitle" style="margin-top:16px;color:var(--text-tertiary)">No unit mix yet. Add the community\'s unit types to value it.</div>'
        : '';

    return `
        <div class="section-header">
            <h3 class="section-title">Unit Mix</h3>
            <div style="display:flex;gap:8px">
                <button class="btn btn-secondary btn-sm" id="editShExpensesBtn">Edit expenses</button>
                <button class="btn btn-primary btn-sm" id="editShUnitsBtn">${icons.edit} Edit unit mix</button>
            </div>
        </div>
        <div class="page-subtitle" style="margin-bottom:12px">Total: <strong>${fmt.num(totalUnits)} beds/units</strong> across ${unitTypes.length} unit types and ${Object.keys(byAcuity).length} acuity levels.</div>
        ${noAssumptionsMsg}
        ${unitTypes.length > 0 ? `
        <div class="data-table-wrap" style="overflow-x:auto">
            <table class="data-table">
                <thead><tr>
                    <th>Unit Name</th><th>Type</th><th class="right">Count</th><th class="right">Avg SF</th>
                    <th class="right">Monthly Fee</th><th class="right">Stab. Occ.</th><th class="right">Turnover</th>
                    <th>Care Tiers</th>
                </tr></thead>
                <tbody>${unitTableHtml}</tbody>
                <tfoot><tr>
                    <td colspan="2" style="text-align:right;font-weight:600">Total Units</td>
                    <td class="mono right" style="font-weight:600">${fmt.num(totalUnits)}</td>
                    <td colspan="5"></td>
                </tr></tfoot>
            </table>
        </div>` : ''}
        ${payerHtml}
        ${revenueHtml}
        ${!y1 && assumptions ? '<div class="page-subtitle" style="margin-top:24px;color:var(--text-tertiary)">Run a valuation to see revenue projections.</div>' : ''}
    `;
}


function renderSeniorsHousingOperatingTab(property, cfRows, valuation) {
    let assumptions = null;
    if (valuation && valuation.seniors_housing_assumptions_json) {
        try { assumptions = JSON.parse(valuation.seniors_housing_assumptions_json); } catch {}
    }

    const expenseLines = assumptions ? (assumptions.expenses || []) : [];
    const ancillaryLines = assumptions ? (assumptions.ancillary_revenue || []) : [];
    const capexItems = assumptions ? (assumptions.capex || []) : [];
    const valuationParams = assumptions ? (assumptions.valuation || {}) : {};

    const acuityLabels = {
        independent_living: 'IL', assisted_living: 'AL',
        memory_care: 'MC', skilled_nursing: 'SNF',
    };

    let assumptionsHtml = '';
    if (assumptions) {
        // Growth & valuation assumptions
        assumptionsHtml += `
        <div class="section-header" style="margin-top:32px">
            <h3 class="section-title">Valuation Assumptions</h3>
        </div>
        <div class="kpi-row" style="margin-bottom:12px">
            <div class="kpi-card"><div class="kpi-label">Fee Growth</div><div class="kpi-value">${fmt.pct(parseFloat(valuationParams.fee_growth_rate || 0))}</div></div>
            <div class="kpi-card"><div class="kpi-label">Expense Growth</div><div class="kpi-value">${fmt.pct(parseFloat(valuationParams.expense_growth_rate || 0))}</div></div>
            <div class="kpi-card"><div class="kpi-label">Discount Rate</div><div class="kpi-value">${fmt.pct(parseFloat(valuationParams.discount_rate || 0))}</div></div>
            <div class="kpi-card"><div class="kpi-label">Exit Cap Rate</div><div class="kpi-value">${fmt.pct(parseFloat(valuationParams.exit_cap_rate || 0))}</div></div>
            <div class="kpi-card"><div class="kpi-label">Hold Period</div><div class="kpi-value">${valuationParams.hold_years || '—'} yrs</div></div>
        </div>`;

        // Expense assumptions table (grouped by category)
        const categoryLabels = {
            labor: 'Labor', food: 'Food & Dietary', insurance: 'Insurance',
            marketing: 'Marketing', utilities: 'Utilities', property_tax: 'Property Tax',
            medical_supplies: 'Medical Supplies', management_fee: 'Management Fee', other: 'Other',
        };
        const expByCategory = {};
        expenseLines.forEach(e => {
            const cat = e.category || 'other';
            if (!expByCategory[cat]) expByCategory[cat] = [];
            expByCategory[cat].push(e);
        });

        let expRows = '';
        for (const [cat, lines] of Object.entries(expByCategory)) {
            expRows += `<tr class="section-divider"><td colspan="5" style="font-weight:600;padding-top:8px;color:var(--text-secondary)">${categoryLabels[cat] || cat}</td></tr>`;
            lines.forEach(e => {
                const acuityScope = (e.applies_to_acuity && e.applies_to_acuity.length > 0)
                    ? e.applies_to_acuity.map(a => acuityLabels[a] || a).join(', ')
                    : 'All';
                expRows += `<tr>
                    <td class="tenant-name">${escapeHtmlAttr(e.name)}</td>
                    <td class="mono right">${parseFloat(e.annual_fixed || 0) > 0 ? fmt.currencyExact(parseFloat(e.annual_fixed)) : '—'}</td>
                    <td class="mono right">${parseFloat(e.per_occupied_unit_month || 0) > 0 ? fmt.currencyExact(parseFloat(e.per_occupied_unit_month)) + '/unit/mo' : parseFloat(e.pct_of_revenue || 0) > 0 ? fmt.pct(parseFloat(e.pct_of_revenue)) + ' of rev' : '—'}</td>
                    <td class="mono right">${fmt.pct(parseFloat(e.growth_pct || 0))}</td>
                    <td style="font-size:0.75rem;color:var(--text-tertiary)">${acuityScope}</td>
                </tr>`;
            });
        }

        assumptionsHtml += `
        <div class="section-header" style="margin-top:32px">
            <h3 class="section-title">Expense Assumptions</h3>
        </div>
        ${expenseLines.length > 0 ? `
        <div class="data-table-wrap" style="overflow-x:auto">
            <table class="data-table">
                <thead><tr><th>Expense</th><th class="right">Annual Fixed</th><th class="right">Variable</th><th class="right">Growth</th><th>Acuity</th></tr></thead>
                <tbody>${expRows}</tbody>
            </table>
        </div>` : '<div class="page-subtitle" style="color:var(--text-tertiary)">No expense lines configured.</div>'}`;

        // Ancillary revenue
        if (ancillaryLines.length > 0) {
            const ancRows = ancillaryLines.map(a => {
                const acuityScope = (a.applies_to_acuity && a.applies_to_acuity.length > 0)
                    ? a.applies_to_acuity.map(ac => acuityLabels[ac] || ac).join(', ')
                    : 'All';
                return `<tr>
                    <td class="tenant-name">${escapeHtmlAttr(a.name)}</td>
                    <td class="mono right">${parseFloat(a.annual_fixed || 0) > 0 ? fmt.currencyExact(parseFloat(a.annual_fixed)) : '—'}</td>
                    <td class="mono right">${parseFloat(a.per_occupied_unit_month || 0) > 0 ? fmt.currencyExact(parseFloat(a.per_occupied_unit_month)) + '/unit/mo' : '—'}</td>
                    <td class="mono right">${fmt.pct(parseFloat(a.growth_pct || 0))}</td>
                    <td style="font-size:0.75rem;color:var(--text-tertiary)">${acuityScope}</td>
                </tr>`;
            }).join('');
            assumptionsHtml += `
            <div class="section-header" style="margin-top:32px">
                <h3 class="section-title">Ancillary Revenue</h3>
            </div>
            <div class="data-table-wrap" style="overflow-x:auto">
                <table class="data-table">
                    <thead><tr><th>Source</th><th class="right">Annual Fixed</th><th class="right">Per Unit/Mo</th><th class="right">Growth</th><th>Acuity</th></tr></thead>
                    <tbody>${ancRows}</tbody>
                </table>
            </div>`;
        }

        // CapEx
        if (capexItems.length > 0) {
            const capRows = capexItems.map(c => `<tr>
                <td class="tenant-name">${escapeHtmlAttr(c.name)}</td>
                <td class="mono right">${parseFloat(c.annual_per_unit || 0) > 0 ? fmt.currencyExact(parseFloat(c.annual_per_unit)) + '/unit' : '—'}</td>
                <td class="mono right">${parseFloat(c.annual_fixed || 0) > 0 ? fmt.currencyExact(parseFloat(c.annual_fixed)) : '—'}</td>
                <td class="mono right">${fmt.pct(parseFloat(c.growth_pct || 0))}</td>
            </tr>`).join('');
            assumptionsHtml += `
            <div class="section-header" style="margin-top:32px">
                <h3 class="section-title">Capital Expenditures</h3>
            </div>
            <div class="data-table-wrap" style="max-width:700px">
                <table class="data-table">
                    <thead><tr><th>Item</th><th class="right">Per Unit/Yr</th><th class="right">Annual Fixed</th><th class="right">Growth</th></tr></thead>
                    <tbody>${capRows}</tbody>
                </table>
            </div>`;
        }
    }

    if (cfRows.length === 0) {
        return `
            <div class="section-header"><h3 class="section-title">Operating Budget</h3></div>
            <div class="page-subtitle" style="color:var(--text-tertiary)">Run a valuation to see seniors housing operating projections.</div>
            ${assumptionsHtml}
        `;
    }

    const y1 = cfRows[0];
    const opex = Math.abs(parseFloat(y1.operating_expenses || 0));
    const noi = parseFloat(y1.net_operating_income || 0);
    const egi = parseFloat(y1.effective_gross_income || 0);
    const opexRatio = egi > 0 ? (opex / egi * 100).toFixed(1) : '—';

    // Year-by-year cash flow table
    const yearHeaders = cfRows.map(cf => `<th class="right">Year ${cf.year}</th>`).join('');
    const makeRow = (label, accessor, negative, cls = '') => {
        const cells = cfRows.map(cf => {
            const v = parseFloat(accessor(cf) || 0);
            const display = negative ? -v : v;
            return `<td class="mono right">${fmt.currencyExact(display)}</td>`;
        }).join('');
        return `<tr class="${cls}"><td class="tenant-name">${label}</td>${cells}</tr>`;
    };

    const expenseDetail = y1.expense_detail || {};
    const otherIncomeDetail = y1.other_income_detail || {};
    const hasDebt = cfRows.some(cf => parseFloat(cf.debt_service || 0) !== 0);

    // Build expandable revenue rows
    let revenueRows = makeRow('Base Service Fees', cf => cf.gross_potential_rent, false);
    // Expandable other income
    const otherIncomeKeys = [
        { key: 'care_level_revenue', label: 'Care Level Surcharges' },
        { key: 'second_person_revenue', label: 'Second Person Fees' },
        { key: 'community_fee_revenue', label: 'Community Fees' },
        { key: 'snf_payer_revenue', label: 'SNF Payer Revenue' },
        { key: 'ancillary_revenue', label: 'Ancillary Revenue' },
    ];
    const otherGroupId = 'sh_other_income';
    revenueRows += `<tr class="expandable" data-toggle="${otherGroupId}">
        <td class="tenant-name"><span class="expand-chevron">&#9654;</span>Other Income</td>
        ${cfRows.map(cf => `<td class="mono right">${fmt.currencyExact(parseFloat(cf.other_income || 0))}</td>`).join('')}
    </tr>`;
    otherIncomeKeys.forEach(({ key, label }) => {
        revenueRows += `<tr class="sub-row" data-group="${otherGroupId}">
            <td style="padding-left:40px;font-style:italic">${label}</td>
            ${cfRows.map(cf => {
                const detail = cf.other_income_detail || {};
                return `<td class="mono right">${fmt.currencyExact(parseFloat(detail[key] || 0))}</td>`;
            }).join('')}
        </tr>`;
    });

    // Build expandable expense rows
    const expenseCategories = [
        { key: 'labor', label: 'Labor' },
        { key: 'food_dietary', label: 'Food & Dietary' },
        { key: 'insurance', label: 'Insurance' },
        { key: 'marketing', label: 'Marketing' },
        { key: 'utilities', label: 'Utilities' },
        { key: 'property_tax', label: 'Property Tax' },
        { key: 'medical_supplies', label: 'Medical Supplies' },
        { key: 'management_fee', label: 'Management Fee' },
        { key: 'other', label: 'Other' },
    ];
    const expGroupId = 'sh_expenses';
    let expenseRows = `<tr class="expandable" data-toggle="${expGroupId}">
        <td class="tenant-name"><span class="expand-chevron">&#9654;</span>Operating Expenses</td>
        ${cfRows.map(cf => `<td class="mono right">${fmt.currencyExact(Math.abs(parseFloat(cf.operating_expenses || 0)))}</td>`).join('')}
    </tr>`;
    expenseCategories.forEach(({ key, label }) => {
        const hasValues = cfRows.some(cf => {
            const d = cf.expense_detail || {};
            return parseFloat(d[key] || 0) !== 0;
        });
        if (!hasValues) return;
        expenseRows += `<tr class="sub-row" data-group="${expGroupId}">
            <td style="padding-left:40px;font-style:italic">${label}</td>
            ${cfRows.map(cf => {
                const d = cf.expense_detail || {};
                return `<td class="mono right">${fmt.currencyExact(Math.abs(parseFloat(d[key] || 0)))}</td>`;
            }).join('')}
        </tr>`;
    });

    return `
        <div class="section-header"><h3 class="section-title">Operating Budget</h3></div>
        <div class="page-subtitle" style="margin-bottom:12px">
            Operating projections from the seniors housing valuation engine. Year 1 operating expense ratio: <strong>${opexRatio}%</strong> of EGI.
        </div>
        <div class="kpi-row" style="margin-bottom:24px">
            <div class="kpi-card">
                <div class="kpi-label">Y1 Gross Revenue</div>
                <div class="kpi-value">${fmt.currencyExact(parseFloat(y1.gross_potential_income || 0))}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Y1 Operating Expenses</div>
                <div class="kpi-value">${fmt.currencyExact(opex)}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Y1 NOI</div>
                <div class="kpi-value green">${fmt.currencyExact(noi)}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">OpEx Ratio</div>
                <div class="kpi-value">${opexRatio}%</div>
            </div>
        </div>
        <div class="data-table-wrap" style="overflow-x:auto">
            <table class="data-table" id="shCfTable">
                <thead><tr><th>Line Item</th>${yearHeaders}</tr></thead>
                <tbody>
                    <tr class="section-divider"><td colspan="${cfRows.length + 1}" style="font-weight:600;padding-top:12px;color:var(--text-secondary)">Revenue</td></tr>
                    ${revenueRows}
                    <tr style="border-top:2px solid var(--border);font-weight:600"><td>Effective Gross Income</td>${cfRows.map(cf => `<td class="mono right">${fmt.currencyExact(parseFloat(cf.effective_gross_income || 0))}</td>`).join('')}</tr>

                    <tr class="section-divider"><td colspan="${cfRows.length + 1}" style="font-weight:600;padding-top:12px;color:var(--text-secondary)">Expenses</td></tr>
                    ${expenseRows}

                    <tr class="section-divider"><td colspan="${cfRows.length + 1}" style="font-weight:600;padding-top:12px;color:var(--text-secondary)">Profitability</td></tr>
                    <tr style="font-weight:600;color:var(--accent)"><td class="tenant-name">Net Operating Income</td>${cfRows.map(cf => `<td class="mono right">${fmt.currencyExact(parseFloat(cf.net_operating_income || 0))}</td>`).join('')}</tr>
                    ${makeRow('Capital Reserves', cf => cf.capital_reserves, true)}
                    ${makeRow('Cash Flow Before Debt', cf => cf.cash_flow_before_debt, false, 'font-weight:600')}
                    ${hasDebt ? makeRow('Debt Service', cf => cf.debt_service, true) : ''}
                    ${hasDebt ? makeRow('Levered Cash Flow', cf => cf.levered_cash_flow, false, 'font-weight:600') : ''}
                </tbody>
            </table>
        </div>
        ${assumptionsHtml}
    `;
}

function wireSeniorsHousingCfToggle() {
    const table = document.getElementById('shCfTable');
    if (!table) return;
    table.querySelectorAll('.expandable').forEach(row => {
        row.addEventListener('click', () => {
            const groupId = row.dataset.toggle;
            const isExpanded = row.classList.toggle('expanded');
            row.querySelector('.expand-chevron').innerHTML = isExpanded ? '&#9660;' : '&#9654;';
            table.querySelectorAll(`tr.sub-row[data-group="${groupId}"]`).forEach(sr => {
                sr.classList.toggle('visible', isExpanded);
            });
        });
    });
}


// ─── Property tables: row menus, rates, inline edit ───────────

// Bare rate for statement tables; the unit lives in the column header
function fmtRate(val, decimals = 2) {
    const n = parseFloat(val);
    if (isNaN(n)) return '—';
    return n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

// One "⋯" per row. Items keep their data-* attributes so existing querySelectorAll wiring still binds.
function rowMenuHtml(items, label = 'Row actions') {
    return `<div class="menu row-menu">
        <button type="button" class="btn-icon menu-trigger row-menu-trigger" aria-haspopup="true" aria-label="${escapeHtmlAttr(label)}" title="Actions">⋯</button>
        <div class="menu-list menu-list--right">${items.filter(Boolean).join('')}</div>
    </div>`;
}

function rowMenuItem(attrs, label, { danger = false } = {}) {
    return `<button type="button" class="menu-item${danger ? ' menu-item--danger' : ''}" ${attrs}>${label}</button>`;
}

// Row menus live in scrolling table wraps, so place the open list fixed to escape the clip
document.addEventListener('click', (e) => {
    const trigger = e.target.closest('.row-menu-trigger');
    if (!trigger) return;
    const menu = trigger.closest('.row-menu');
    if (!menu.classList.contains('open')) return;
    const list = menu.querySelector('.menu-list');
    const r = trigger.getBoundingClientRect();
    list.style.top = `${r.bottom + 4}px`;
    list.style.left = 'auto';
    list.style.right = `${document.documentElement.clientWidth - r.right}px`;
    const below = window.innerHeight - r.bottom;
    if (list.offsetHeight > below - 8 && r.top > below) list.style.top = `${r.top - list.offsetHeight - 4}px`;
    if (e.detail === 0) list.querySelector('.menu-item')?.focus(); // opened from the keyboard
});
// Item handlers often stopPropagation, so close row menus in the capture phase
document.addEventListener('click', (e) => {
    const item = e.target.closest('.row-menu .menu-item');
    if (item) item.closest('.row-menu').classList.remove('open');
}, true);
document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    // The shared Escape handler has already closed it; return focus to its trigger
    const menu = e.target.closest?.('.row-menu');
    if (menu && e.target.classList.contains('menu-item')) menu.querySelector('.row-menu-trigger').focus();
});
window.addEventListener('scroll', () => {
    document.querySelectorAll('.row-menu.open').forEach(m => m.classList.remove('open'));
}, true);

// Imports closed before a valuation was created, with Resume / Discard
async function renderUnfinishedImports() {
    const el = document.getElementById('unfinishedImports');
    if (!el) return;
    const items = await api.get('/appraisal-import-workspaces').catch(() => []);
    if (!document.body.contains(el) || !items.length) return;
    el.innerHTML = `<div class="unfinished-imports"><strong>Unfinished imports</strong>${items.map(w => `
        <div class="unfinished-import"><span>${escapeHtmlAttr(w.documents.slice(0, 3).join(', '))}${w.documents.length > 3 ? ` +${w.documents.length - 3} more` : ''}
            <small>${typeof intakeBuilds !== 'undefined' && intakeBuilds.has(w.valuation_id) ? 'Building model…' : w.model_ready ? 'Model ready to create' : 'Needs checking'} · started ${new Date(w.created_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</small></span>
            <a class="btn btn-primary btn-sm" href="?intake=1#/valuation/${w.valuation_id}">Resume</a>
            <button class="btn btn-secondary btn-sm" data-discard-import="${w.valuation_id}">Discard</button></div>`).join('')}</div>`;
    el.querySelectorAll('[data-discard-import]').forEach(btn => btn.onclick = async () => {
        try { await api.del(`/appraisal-import-workspaces/${btn.dataset.discardImport}`); el.innerHTML = ''; toast('Import discarded', 'success'); renderUnfinishedImports(); }
        catch (err) { toast(apiErrorDetail(err), 'error'); }
    });
}

// "PUT /x → 422: {"detail":...}" → the human part
function apiErrorDetail(err) {
    const m = String(err && err.message || '').match(/→ \d+: ([\s\S]*)$/);
    if (!m) return String(err && err.message || 'Request failed');
    try {
        const detail = JSON.parse(m[1]).detail;
        if (Array.isArray(detail)) return detail.map(d => d.msg).join('; ');
        if (detail && typeof detail === 'object') return detail.message || JSON.stringify(detail);
        return String(detail || m[1]);
    } catch { return m[1] || 'Request failed'; }
}

// Validate an inline rent roll edit; returns { value } or { error }
function parseRentRollEdit(field, text, lease) {
    const v = String(text).trim();
    if (field === 'rent') {
        const n = Number(v);
        if (v === '' || !isFinite(n) || n <= 0) return { error: 'Rent must be a number above zero' };
        return { value: n };
    }
    if (field === 'start' || field === 'end') {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(v)) return { error: 'Enter a full date' };
        const start = field === 'start' ? v : lease.lease_start_date;
        const end = field === 'end' ? v : lease.lease_end_date;
        if (end <= start) return { error: 'Lease end must be after lease start' };
        return { value: v };
    }
    if (field === 'tenant') {
        if (!v) return { error: 'Tenant name cannot be blank' };
        if (v.length > 255) return { error: 'Tenant name is too long' };
        return { value: v };
    }
    return { error: 'Unknown field' };
}

const RENT_ROLL_EDIT = {
    rent: { key: 'base_rent_per_unit', input: 'number', raw: l => String(parseFloat(l.base_rent_per_unit)), show: l => fmtRate(l.base_rent_per_unit) },
    start: { key: 'lease_start_date', input: 'date', raw: l => l.lease_start_date, show: l => fmt.date(l.lease_start_date) },
    end: { key: 'lease_end_date', input: 'date', raw: l => l.lease_end_date, show: l => fmt.date(l.lease_end_date) },
    tenant: { key: 'name', input: 'text', raw: l => l.tenant.name, show: l => escapeHtmlAttr(l.tenant.name) },
};

// Inline edit for the commercial rent roll: click or Enter on a cell, Enter/blur saves, Esc cancels.
// Cells update in place; the page re-renders once no editor is open so valuations show "Needs re-run".
function wireRentRollInlineEdit(allLeases, propertyId) {
    const table = document.getElementById('rentRollTable');
    if (!table) return;
    let saving = 0;
    let dirty = false;
    let refreshing = false;
    let refreshTimer = null;

    const refreshWhenIdle = () => {
        clearTimeout(refreshTimer);
        refreshTimer = setTimeout(async () => {
            if (!dirty || !document.body.contains(table)) return;
            if (saving || table.querySelector('.ie-editing')) return; // the open editor reschedules on settle
            const focusKey = document.activeElement?.closest?.('[data-ie-key]')?.dataset.ieKey;
            const activeTab = document.querySelector('#tabBar .tab-item.active')?.dataset.tab;
            const wrap = table.closest('.data-table-wrap');
            const y = window.scrollY, wrapY = wrap ? wrap.scrollTop : 0, wrapX = wrap ? wrap.scrollLeft : 0;
            refreshing = true;
            await propertyView({ id: propertyId });
            if (activeTab && activeTab !== 'rent-roll') document.querySelector(`#tabBar .tab-item[data-tab="${activeTab}"]`)?.click();
            window.scrollTo(0, y);
            const newTable = document.getElementById('rentRollTable');
            const newWrap = newTable?.closest('.data-table-wrap');
            if (newWrap) { newWrap.scrollTop = wrapY; newWrap.scrollLeft = wrapX; }
            if (focusKey) newTable?.querySelector(`[data-ie-key="${focusKey}"]`)?.focus({ preventScroll: true });
        }, 400);
    };

    const flash = (td, cls) => {
        td.classList.add(cls);
        setTimeout(() => td.classList.remove(cls), 1200);
    };

    const updateTotals = () => {
        allLeases.forEach(l => {
            const cell = table.querySelector(`[data-annual-for="${l.id}"]`);
            if (cell) cell.textContent = fmt.currencyExact(parseFloat(l.base_rent_per_unit) * rentUnits(l.rent_basis, l.suite.area));
        });
        const total = document.getElementById('rentRollTotal');
        if (total) total.textContent = fmt.currencyExact(allLeases.reduce((s, l) =>
            s + parseFloat(l.base_rent_per_unit) * rentUnits(l.rent_basis, l.suite.area), 0));
    };

    const save = async (field, lease, value) => {
        if (field === 'tenant') {
            const tenant = await api.put(`/valuations/${lease.tenant.valuation_id}/tenants/${lease.tenant.id}`, { name: value });
            allLeases.forEach(l => { if (l.tenant && l.tenant.id === tenant.id) l.tenant = { ...l.tenant, name: tenant.name }; });
            table.querySelectorAll(`[data-ie="tenant"][data-tenant-id="${tenant.id}"]`).forEach(td => {
                if (!td.classList.contains('ie-editing')) td.innerHTML = escapeHtmlAttr(tenant.name);
            });
            return;
        }
        const key = RENT_ROLL_EDIT[field].key;
        const updated = await api.put(`/leases/${lease.id}`, { [key]: value });
        lease[key] = updated[key];
        if (field === 'rent') updateTotals();
    };

    const startEdit = (td) => {
        if (refreshing || td.classList.contains('ie-editing') || td.classList.contains('ie-saving')) return;
        const field = td.dataset.ie;
        const spec = RENT_ROLL_EDIT[field];
        const lease = allLeases.find(l => l.id === td.dataset.leaseId);
        if (!spec || !lease || (field === 'tenant' && !lease.tenant)) return;

        const original = td.innerHTML;
        const raw = spec.raw(lease);
        const input = document.createElement('input');
        input.type = spec.input;
        input.className = 'ie-input';
        input.value = raw;
        if (spec.input === 'number') { input.step = '0.01'; input.min = '0.01'; }
        if (field === 'tenant') input.maxLength = 255;
        input.setAttribute('aria-label', td.dataset.ieLabel || 'Edit value');
        td.textContent = '';
        td.appendChild(input);
        td.classList.add('ie-editing');
        input.focus();
        if (spec.input !== 'date') input.select();

        let settled = false;
        const finish = async (commit, refocus) => {
            if (settled) return;
            settled = true;
            const text = input.value;
            td.classList.remove('ie-editing');
            td.innerHTML = original;
            if (refocus) td.focus();
            const unchanged = field === 'rent' ? Number(text) === Number(raw) : text.trim() === raw;
            if (!commit || unchanged) { refreshWhenIdle(); return; }

            const parsed = parseRentRollEdit(field, text, lease);
            if (parsed.error) { flash(td, 'ie-error'); toast(parsed.error, 'error'); refreshWhenIdle(); return; }

            saving++;
            td.classList.add('ie-saving');
            td.setAttribute('aria-busy', 'true');
            td.innerHTML = field === 'tenant' ? escapeHtmlAttr(parsed.value)
                : field === 'rent' ? fmtRate(parsed.value) : fmt.date(parsed.value);
            try {
                await save(field, lease, parsed.value);
                dirty = true;
                td.innerHTML = spec.show(lease);
                flash(td, 'ie-saved');
            } catch (err) {
                td.innerHTML = original;
                flash(td, 'ie-error');
                toast('Could not save: ' + apiErrorDetail(err), 'error');
            } finally {
                saving--;
                td.classList.remove('ie-saving');
                td.removeAttribute('aria-busy');
                refreshWhenIdle();
            }
        };
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); finish(true, true); }
            else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); finish(false, true); }
        });
        // A re-render that detaches the input must not commit a half-typed value
        input.addEventListener('blur', () => finish(td.isConnected, false));
    };

    table.addEventListener('click', (e) => {
        const td = e.target.closest('td[data-ie]');
        if (td) startEdit(td);
    });
    table.addEventListener('keydown', (e) => {
        const td = e.target.closest('td[data-ie]');
        if (!td || e.target !== td) return;
        if (e.key === 'Enter' || e.key === 'F2') { e.preventDefault(); startEdit(td); }
    });
}


function renderRentRollTab(property, allLeases, marketProfiles, recoveryStructures = []) {
    const mlaMap = {};
    (marketProfiles || []).forEach(m => { mlaMap[m.id] = m; });
    const mlaByType = {};
    (marketProfiles || []).forEach(m => { mlaByType[m.space_type] = m; });
    const au = property.area_unit;
    const isUnit = au === 'unit';
    const simplifyUnitAssumptions = property.property_type === 'multifamily' || property.property_type === 'self_storage';
    const areaLabel = isUnit ? 'Units' : 'Area (SF)';
    const rentLabel = isUnit ? 'Rent $/Unit/mo' : 'Rent $/SF/yr';
    const mktLabel = isUnit ? 'Mkt Rent $/Unit/mo' : 'Mkt Rent $/SF/yr';

    // ── Multifamily: unified one-row-per-unit-type layout ──
    if (simplifyUnitAssumptions) {
        const rows = property.suites.map(suite => {
            const leases = allLeases.filter(l => l.suite.id === suite.id);
            const mla = mlaByType[suite.market_space_type || suite.space_type];
            const lease = leases[0]; // one lease per unit type
            const isVacant = !lease;
            const displayName = lease && lease.tenant ? lease.tenant.name : '';
            // Unit rents are $/unit/mo (monthly frequency); the column is annual
            const annualRent = lease ? parseFloat(lease.base_rent_per_unit) * rentUnits(lease.rent_basis, suite.area) * (lease.rent_payment_frequency === 'monthly' ? 12 : 1) : 0;

            const actions = rowMenuHtml([
                rowMenuItem(`data-edit-unit-type="${suite.id}"`, 'Edit unit type'),
                rowMenuItem(`data-delete-suite="${suite.id}"`, 'Delete unit type', { danger: true }),
            ], `Actions for ${suite.suite_name}`);

            return `<tr>
                <td class="tenant-name">${escapeHtmlAttr(suite.suite_name)}</td>
                <td>${escapeHtmlAttr(suite.space_type)}</td>
                <td class="mono right">${fmt.num(suite.area)}</td>
                <td class="${isVacant ? 'vacant' : 'tenant-name'}">${isVacant ? 'Vacant' : escapeHtmlAttr(displayName || 'Occupied')}</td>
                <td>${lease ? fmt.date(lease.lease_start_date) : '—'}</td>
                <td>${lease ? fmt.date(lease.lease_end_date) : '—'}</td>
                <td class="mono right">${mla ? fmtRate(mla.market_rent_per_unit, isUnit ? 0 : 2) : '—'}</td>
                <td class="mono right">${lease ? fmtRate(lease.base_rent_per_unit, isUnit ? 0 : 2) : '—'}</td>
                <td class="mono right">${mla ? fmt.pct(mla.rent_growth_rate_pct) : '—'}</td>
                <td class="mono right">${annualRent > 0 ? fmt.currencyExact(annualRent) : '—'}</td>
                <td class="col-actions">${actions}</td>
            </tr>`;
        }).join('');

        const totalRent = allLeases.reduce((s, l) => s + parseFloat(l.base_rent_per_unit) * rentUnits(l.rent_basis, l.suite.area) * (l.rent_payment_frequency === 'monthly' ? 12 : 1), 0);
        const colCount = 11;

        return `
            <div class="section-header">
                <h3 class="section-title">Rent Roll</h3>
                <div class="btn-group">
                    <button class="btn btn-primary btn-sm" id="newUnitTypeBtn">${icons.plus} Add Unit Type</button>
                </div>
            </div>
            <div class="page-subtitle" style="margin-bottom:10px">Each row is a unit type. Market assumptions are managed inline via the <button class="btn-icon" id="editMktRentsBtn" title="Assumption workspace" style="vertical-align:middle">${icons.edit}</button> buttons below.</div>
            <div class="data-table-wrap dt-scroll">
                <table class="data-table dt-dense">
                    <thead>
                        <tr>
                            <th>Unit Type</th>
                            <th>Key</th>
                            <th class="right">${areaLabel}</th>
                            <th>Resident</th>
                            <th>Start</th>
                            <th>End</th>
                            <th class="right">${mktLabel} <button class="btn-icon" id="editMktRentsHdrBtn" title="Edit market rents" aria-label="Edit market rents" style="vertical-align:middle">${icons.edit}</button></th>
                            <th class="right">${rentLabel} <button class="btn-icon" id="editRentUnitBtn" title="Edit in-place rents" aria-label="Edit in-place rents" style="vertical-align:middle">${icons.edit}</button></th>
                            <th class="right">Growth</th>
                            <th class="right">Annual Rent</th>
                            <th class="col-actions"><span class="sr-only">Actions</span></th>
                        </tr>
                    </thead>
                    <tbody>${rows || `<tr><td colspan="${colCount}" style="text-align:center;color:var(--text-tertiary);padding:32px">No unit types yet. Click "Add Unit Type" to get started.</td></tr>`}</tbody>
                    ${totalRent > 0 ? `<tfoot>
                        <tr>
                            <td colspan="${colCount - 2}" style="text-align:right">Total Annual Rent</td>
                            <td style="text-align:right">${fmt.currencyExact(totalRent)}</td>
                            <td class="col-actions"></td>
                        </tr>
                    </tfoot>` : ''}
                </table>
            </div>`;
    }

    // ── Commercial: original multi-row layout ──
    const rsName = Object.fromEntries(recoveryStructures.map(rs => [rs.id, rs.name]));
    // A lease's template wins over its own recovery type; overrides add to either
    const leaseRecovery = (l) => {
        const n = (l.expense_recovery_overrides || []).length;
        const base = l.recovery_structure_id ? escapeHtmlAttr(rsName[l.recovery_structure_id] || 'Template') : fmt.typeLabel(l.recovery_type);
        return `<button type="button" class="form-inline-link" data-detail-lease="${l.id}" title="Recovery overrides">${base}${n ? ` + ${n} override${n === 1 ? '' : 's'}` : ''}</button>`;
    };
    // Vacant space leases up under its market profile's recovery structure
    const vacantRecovery = (suite) => {
        const mla = mlaByType[suite.market_space_type || suite.space_type];
        if (!mla) return '<span class="form-help" title="No market profile matches this space type, so it never leases">No market profile</span>';
        const terms = mla.recovery_structure_id ? escapeHtmlAttr(rsName[mla.recovery_structure_id] || 'Template') : 'NNN';
        return `<button type="button" class="form-inline-link" data-edit-market="${mla.id}" title="Leases up under the ${escapeHtmlAttr(mla.space_type)} market profile">via ${escapeHtmlAttr(mla.space_type)}: ${terms}</button>`;
    };
    const rows = property.suites.map(suite => {
        const leases = allLeases.filter(l => l.suite.id === suite.id);
        const suiteItems = [
            rowMenuItem(`data-edit-suite="${suite.id}"`, 'Edit suite'),
            rowMenuItem(`data-delete-suite="${suite.id}"`, 'Delete suite', { danger: true }),
        ];

        if (leases.length === 0) {
            return `<tr>
                <td class="tenant-name">${escapeHtmlAttr(suite.suite_name)}</td>
                <td>${escapeHtmlAttr(suite.space_type)}</td>
                <td class="mono right">${fmt.num(suite.area)}</td>
                <td class="vacant">Vacant</td>
                <td>—</td>
                <td>—</td>
                <td>—</td>
                <td class="mono right">—</td>
                <td class="mono right">—</td>
                <td>${vacantRecovery(suite)}</td>
                <td class="col-actions">${rowMenuHtml(suiteItems, `Actions for suite ${suite.suite_name}`)}</td>
            </tr>`;
        }
        return leases.map((l, i) => {
            const displayName = l.tenant ? l.tenant.name : (l.tenant_id ? 'Leased' : 'Vacant');
            const leaseActions = rowMenuHtml([
                rowMenuItem(`data-edit-lease="${l.id}"`, 'Open lease'),
                rowMenuItem(`data-delete-lease="${l.id}"`, 'Delete lease', { danger: true }),
                ...(i === 0 ? ['<div class="menu-sep" role="separator"></div>', ...suiteItems] : []),
            ], `Actions for ${displayName} in suite ${suite.suite_name}`);
            const who = escapeHtmlAttr(`${displayName}, suite ${suite.suite_name}`);
            const ie = (field, label) => `data-ie="${field}" data-lease-id="${l.id}" data-ie-key="${field}:${l.id}" data-ie-label="${label} for ${who}" tabindex="0" title="Click or press Enter to edit"`;
            return `<tr class="lease-row" data-open-lease="${l.id}">
                <td class="tenant-name">${i === 0 ? escapeHtmlAttr(suite.suite_name) : ''}</td>
                <td>${i === 0 ? escapeHtmlAttr(suite.space_type) : ''}</td>
                <td class="mono right">${i === 0 ? fmt.num(suite.area) : ''}</td>
                ${l.tenant
                    ? `<td class="tenant-name ie-cell" ${ie('tenant', 'Tenant name')} data-tenant-id="${l.tenant.id}">${escapeHtmlAttr(displayName)}</td>`
                    : `<td class="tenant-name">${escapeHtmlAttr(displayName)}</td>`}
                <td>${fmt.typeLabel(l.lease_type)}</td>
                <td class="ie-cell" ${ie('start', 'Lease start')}>${fmt.date(l.lease_start_date)}</td>
                <td class="ie-cell" ${ie('end', 'Lease end')}>${fmt.date(l.lease_end_date)}</td>
                <td class="mono right ie-cell" ${ie('rent', 'Base rent')}>${l.rent_basis === 'total' ? `${fmt.currencyExact(l.base_rent_per_unit)} total` : fmtRate(l.base_rent_per_unit)}</td>
                <td class="mono right" data-annual-for="${l.id}">${fmt.currencyExact(parseFloat(l.base_rent_per_unit) * rentUnits(l.rent_basis, suite.area))}</td>
                <td>${leaseRecovery(l)}</td>
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
                ${property.area_unit === 'unit' ? '' : '<button class="btn btn-secondary btn-sm" id="pasteRentRollBtn">Add / paste rent roll</button>'}
                <button class="btn btn-secondary btn-sm" id="newSuiteBtn">${icons.plus} New Suite</button>
                <button class="btn btn-primary btn-sm" id="newLeaseBtn">${icons.plus} New Lease</button>
            </div>
        </div>
        <div class="data-table-wrap dt-scroll">
            <table class="data-table dt-dense" id="rentRollTable">
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
                        <th class="col-actions"><span class="sr-only">Actions</span></th>
                    </tr>
                </thead>
                <tbody>${rows || `<tr><td colspan="${colCount}" style="text-align:center;color:var(--text-tertiary);padding:32px">No suites or leases yet</td></tr>`}</tbody>
                ${totalRent > 0 ? `<tfoot>
                    <tr>
                        <td colspan="${colCount - 3}" style="text-align:right">Total Annual Rent</td>
                        <td style="text-align:right" id="rentRollTotal">${fmt.currencyExact(totalRent)}</td>
                        <td></td>
                        <td class="col-actions"></td>
                    </tr>
                </tfoot>` : ''}
            </table>
        </div>`;
}


function renderOperatingBudgetTab(expenses, otherIncomeItems, totalArea, areaUnit, propertyType, recoveryPools = []) {
    return `
        ${renderExpensesTab(expenses, totalArea, areaUnit, propertyType, recoveryPools)}
        <div style="margin-top:32px">
            ${renderOtherIncomeTab(otherIncomeItems)}
        </div>`;
}

function renderExpensesTab(expenses, totalArea, areaUnit, propertyType, recoveryPools = []) {
    const poolOf = (category) => recoveryPools.find(p => (p.expense_categories || []).includes(category));
    const isMultifamily = propertyType === 'multifamily' || propertyType === 'self_storage';
    const perUnitLabel = areaUnit === 'unit' ? '$/Unit' : '$/SF';
    const annualAmount = e => parseFloat(e.base_year_amount) * (e.amount_basis === 'per_area' ? parseFloat(totalArea) : 1);
    const totalExp = expenses.reduce((s, e) => s + (e.is_pct_of_egi ? 0 : annualAmount(e)), 0);
    const colCount = isMultifamily ? 6 : 7;
    const rows = expenses.map(e => `
        <tr>
            <td class="tenant-name">${escapeHtmlAttr(fmt.typeLabel(e.category))}</td>
            <td>${escapeHtmlAttr(e.description || '—')}</td>
            <td class="mono right">${e.is_pct_of_egi ? fmt.pct(e.pct_of_egi) + ' of EGI' : fmt.currencyExact(annualAmount(e))}</td>
            <td class="mono right">${e.is_pct_of_egi ? '—' : fmtRate(annualAmount(e) / totalArea, areaUnit === 'unit' ? 0 : 2)}</td>
            <td class="mono right">${e.is_pct_of_egi ? '—' : fmt.pct(e.growth_rate_pct)}</td>
            ${isMultifamily ? '' : `<td>${e.is_recoverable ? 'Yes' : 'No'}${e.is_recoverable && poolOf(e.category) ? ` <span class="status-badge" title="Shared over this recovery pool's area">${escapeHtmlAttr(poolOf(e.category).name)}</span>` : ''}</td>`}
            <td class="col-actions">${rowMenuHtml([
                rowMenuItem(`data-edit-expense="${e.id}"`, 'Edit expense'),
                rowMenuItem(`data-delete-expense="${e.id}"`, 'Delete expense', { danger: true }),
            ], `Actions for ${fmt.typeLabel(e.category)}`)}</td>
        </tr>`).join('');

    return `
        <div class="section-header">
            <h3 class="section-title">Operating Expenses</h3>
            <div class="btn-group">
                <button class="btn btn-secondary btn-sm" id="bulkExpenseBtn">Bulk Edit</button>
                <button class="btn btn-primary btn-sm" id="newExpenseBtn">${icons.plus} New Expense</button>
            </div>
        </div>
        <div class="data-table-wrap dt-scroll">
            <table class="data-table dt-dense">
                <thead>
                    <tr>
                        <th>Category</th>
                        <th>Description</th>
                        <th class="right">Base Amount $/yr</th>
                        <th class="right">${perUnitLabel}/yr</th>
                        <th class="right">Growth</th>
                        ${isMultifamily ? '' : '<th>Recoverable</th>'}
                        <th class="col-actions"><span class="sr-only">Actions</span></th>
                    </tr>
                </thead>
                <tbody>${rows || `<tr><td colspan="${colCount}" style="text-align:center;color:var(--text-tertiary);padding:32px">No expenses defined</td></tr>`}</tbody>
                ${totalExp > 0 ? `<tfoot>
                    <tr>
                        <td colspan="2">Total (excl. % of EGI items)</td>
                        <td style="text-align:right">${fmt.currencyExact(totalExp)}</td>
                        <td style="text-align:right">${fmtRate(totalExp / totalArea, areaUnit === 'unit' ? 0 : 2)}</td>
                        <td colspan="${colCount - 5}"></td>
                        <td class="col-actions"></td>
                    </tr>
                </tfoot>` : ''}
            </table>
        </div>`;
}

function renderOtherIncomeTab(items) {
    const total = items.reduce((s, i) => s + parseFloat(i.base_year_amount), 0);
    const rows = items.map(i => `
        <tr>
            <td class="tenant-name">${escapeHtmlAttr(fmt.typeLabel(i.category))}</td>
            <td>${escapeHtmlAttr(i.description || '—')}</td>
            <td class="mono right">${fmt.currencyExact(i.base_year_amount)}</td>
            <td class="mono right">${fmt.pct(i.growth_rate_pct)}</td>
            <td class="col-actions">${rowMenuHtml([
                rowMenuItem(`data-edit-other-income="${i.id}"`, 'Edit revenue item'),
                rowMenuItem(`data-delete-other-income="${i.id}"`, 'Delete revenue item', { danger: true }),
            ], `Actions for ${fmt.typeLabel(i.category)}`)}</td>
        </tr>`).join('');

    return `
        <div class="section-header">
            <h3 class="section-title">Custom Revenue Line Items</h3>
            <div class="btn-group">
                <button class="btn btn-secondary btn-sm" id="bulkOtherIncomeBtn">Bulk Edit</button>
                <button class="btn btn-primary btn-sm" id="newOtherIncomeBtn">${icons.plus} New Revenue Item</button>
            </div>
        </div>
        <div class="data-table-wrap dt-scroll">
            <table class="data-table dt-dense">
                <thead>
                    <tr>
                        <th>Category</th>
                        <th>Description</th>
                        <th class="right">Base Amount $/yr</th>
                        <th class="right">Growth</th>
                        <th class="col-actions"><span class="sr-only">Actions</span></th>
                    </tr>
                </thead>
                <tbody>${rows || '<tr><td colspan="5" style="text-align:center;color:var(--text-tertiary);padding:32px">No custom revenue items defined</td></tr>'}</tbody>
                ${total > 0 ? `<tfoot>
                    <tr>
                        <td colspan="2">Total</td>
                        <td style="text-align:right">${fmt.currencyExact(total)}</td>
                        <td></td>
                        <td class="col-actions"></td>
                    </tr>
                </tfoot>` : ''}
            </table>
        </div>`;
}


// Each valuation owns its whole model. The property page edits the one picked here (remembered per
// property), else the newest draft, else the newest valuation.
const modelValuationIds = {};  // property id -> the valuation its page is editing

function modelUrl(propertyId) {
    if (!modelValuationIds[propertyId]) throw new Error('Add a valuation first: the model belongs to each valuation');
    return `/valuations/${modelValuationIds[propertyId]}`;
}

function savedModelValuation(propertyId) {
    try { return localStorage.getItem(`opendcf_market_val_${propertyId}`); } catch { return null; }
}

function saveModelValuation(propertyId, valuationId) {
    try { localStorage.setItem(`opendcf_market_val_${propertyId}`, valuationId); } catch { /* storage unavailable */ }
}

function pickModelValuation(propertyId, valuations) {
    if (!valuations?.length) return null;
    const saved = savedModelValuation(propertyId);
    const byNewest = [...valuations].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
    return valuations.find(v => v.id === saved)
        || byNewest.find(v => (v.review_status || 'draft') === 'draft')
        || byNewest[0];
}

function valuationStatusPill(v, property) {
    if (v.review_status === 'approved') return '<span class="pill pill-ok" title="Frozen and approved">Approved</span>';
    if (v.review_status === 'in_review') return '<span class="pill pill-muted" title="Frozen for review">In review</span>';
    if (isValuationStale(v, property)) return valuationStaleReason(v) === 'engine'
        ? '<span class="pill pill-warn" title="Calculated with an earlier version of the valuation engine">Needs re-run (engine updated)</span>'
        : '<span class="pill pill-warn" title="Its inputs changed after it ran">Needs re-run</span>';
    if (v.status === 'completed') return '<span class="pill pill-ok">Current</span>';
    if (v.status === 'failed') return '<span class="pill pill-bad">Not run</span>';
    return '<span class="pill pill-muted">Draft</span>';
}

// The one valuation bar: pick a valuation, see its result, act on it. The tabs below edit its model.
function renderModelPicker(valuations, v, property) {
    const frozen = (v.review_status || 'draft') !== 'draft';
    const completed = v.status === 'completed';
    const stale = isValuationStale(v, property);
    return `
        <section class="scenarios" id="modelPicker">
            <div class="scenario">
                <div class="scenario-main">
                    <select class="form-input" id="modelValuationSelect" style="max-width:340px" aria-label="Valuation">
                        ${valuations.map(o => `<option value="${o.id}" ${o.id === v.id ? 'selected' : ''}>${escapeHtmlAttr(o.name)}${(o.review_status || 'draft') !== 'draft' ? ' (frozen)' : ''}</option>`).join('')}
                    </select>
                    <div class="scenario-meta" style="margin-top:6px">${valuationStatusPill(v, property)} ${effectiveHoldYears(v, property)}-yr hold · ${fmt.pct(v.discount_rate)} discount · ${fmt.pct(v.exit_cap_rate)} exit cap${v.purchase_price ? ` · ${fmt.currency(v.purchase_price)} price` : ''}${v.loan_amount ? ' · Levered' : ''}</div>
                    ${v.status === 'failed' && v.error_message ? `<div class="scenario-error">${escapeHtmlAttr(v.error_message)}</div>` : ''}
                </div>
                ${completed ? `
                    <div class="scenario-metric"><div class="scenario-metric-label">Value</div><div class="scenario-metric-value">${fmt.currency(v.result_npv)}</div></div>
                    <div class="scenario-metric"><div class="scenario-metric-label">Going-in cap</div><div class="scenario-metric-value">${fmt.pct(v.result_going_in_cap_rate)}</div></div>
                    <div class="scenario-metric"><div class="scenario-metric-label">IRR</div><div class="scenario-metric-value" title="${v.purchase_price ? '' : 'Add a purchase price to measure IRR'}">${v.purchase_price && v.result_irr != null ? fmt.pct(v.result_irr) : '—'}</div></div>
                ` : ''}
                <div class="scenario-actions">
                    ${!frozen && (!completed || stale) ? `<button class="btn btn-primary btn-sm" data-run-valuation="${v.id}">${completed ? 'Re-run' : 'Run'}</button>` : ''}
                    ${completed ? `<a class="btn btn-secondary btn-sm" href="#/valuation/${v.id}">Results</a>` : ''}
                    <button class="btn btn-secondary btn-sm" data-duplicate-valuation="${v.id}" title="Copy this valuation and its whole model">Copy</button>
                    <button class="btn btn-secondary btn-sm" data-roll-forward="${v.id}" title="Copy with the analysis start moved forward">Roll forward</button>
                    ${frozen ? '' : `<button class="btn-icon" data-edit-valuation="${v.id}" title="Rates &amp; exit">${icons.edit}</button>
                    <button class="btn-icon danger" data-delete-valuation="${v.id}" title="Delete">${icons.trash}</button>`}
                </div>
            </div>
            <div class="form-help">${frozen
                ? 'Frozen for review: read only. Copy or roll it forward to make changes.'
                : 'The tabs below edit this valuation\'s own model. Copies and roll-forwards take their own copy.'}</div>
        </section>`;
}

function openRollForward(valuationId, onDone) {
    showFormModal({
        title: 'Roll forward',
        fields: [
            { key: 'period', label: 'Move the analysis start forward by', type: 'select',
              options: [{ value: 'quarter', label: 'One quarter' }, { value: 'month', label: 'One month' }, { value: 'year', label: 'One year' }] },
            { key: 'name', label: 'Name (optional)', type: 'text' },
        ],
        defaults: { period: 'quarter' },
        submitLabel: 'Roll forward',
        onSubmit: async (data, overlay) => {
            const r = await api.post(`/valuations/${valuationId}/roll-forward`, { period: data.period, name: data.name || null });
            const listed = (rows) => rows.map(l => `${l.suite_name}${l.tenant_name ? ` (${l.tenant_name})` : ''}`).join(', ');
            const notes = [
                r.expired_leases.length ? `Expired since the prior start: ${listed(r.expired_leases)}` : '',
                r.started_leases.length ? `Started since the prior start: ${listed(r.started_leases)}` : '',
            ].filter(Boolean);
            toast(notes.length ? `Rolled forward. ${notes.join('. ')}. Update them in the new model.` : 'Rolled forward. No leases expired or started in between.', 'success');
            overlay.remove();
            saveModelValuation(r.valuation.property_id, r.valuation.id);
            onDone?.(r.valuation);
        },
    });
}

function renderPropertyWithoutValuations(property) {
    setBreadcrumb([{ label: 'Properties', href: '#/dashboard' }, { label: property.name }]);
    $app().innerHTML = `
        <div class="property-header">
            <div class="property-header-left">
                <h1 class="property-header-title">${escapeHtmlAttr(property.name)}</h1>
                <div class="property-header-badges"><span class="property-type-badge badge-${property.property_type}">${fmt.typeLabel(property.property_type)}</span></div>
            </div>
        </div>
        <div class="empty-state">
            <h3>No valuation yet</h3>
            <p>The rent roll, expenses and market leasing belong to each valuation. Start one to build the model.</p>
            <button class="btn btn-primary" id="firstValuationBtn">${icons.plus} New valuation</button>
        </div>`;
    document.getElementById('firstValuationBtn').addEventListener('click', () => showNewValuationModal(property, []));
}

function renderMarketTab(profiles, property, marketValuation, recoveryStructures = []) {
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
                            <div class="property-card-name">${escapeHtmlAttr(fmt.typeLabel(p.space_type))}</div>
                            <div class="property-card-location">${escapeHtmlAttr(p.description || 'Market assumptions')}</div>
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
                                <div class="info-item-value" style="color:var(--accent)">${p.rent_basis === 'total' ? `${fmt.currencyExact(p.market_rent_per_unit)} total` : fmt.perSf(p.market_rent_per_unit, au)}</div>
                            </div>
                            <div>
                                <div class="info-item-label">Rent Growth</div>
                                <div class="info-item-value">${fmt.pct(p.rent_growth_rate_pct)}${byYearNote(p, 'rent_growth_rate_pct')}</div>
                            </div>
                            <div>
                                <div class="info-item-label">Renewal Prob.</div>
                                <div class="info-item-value">${fmt.pct(p.renewal_probability)}${byYearNote(p, 'renewal_probability')}</div>
                            </div>
                            ${isUnit ? '' : `<div>
                                <div class="info-item-label">Recoveries</div>
                                <div class="info-item-value">${escapeHtmlAttr(recoveryStructures.find(rs => rs.id === p.recovery_structure_id)?.name || 'Same as expiring lease')}</div>
                            </div>`}
                            <div>
                                <div class="info-item-label">Concession Timing</div>
                                <div class="info-item-value">${fmt.typeLabel(p.concession_timing_mode || 'blended')}</div>
                            </div>
                            <div>
                                <div class="info-item-label">New Concession</div>
                                <div class="info-item-value">${p.new_tenant_free_rent_months || 0} mo${byYearNote(p, 'new_tenant_free_rent_months')}</div>
                            </div>
                            <div>
                                <div class="info-item-label">Renewal Concession</div>
                                <div class="info-item-value">${p.renewal_free_rent_months || 0} mo${byYearNote(p, 'renewal_free_rent_months')}</div>
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
                                <div class="info-item-value">${p.downtime_months} mo${(p.downtime_schedule || []).length ? ' <span style="color:var(--text-tertiary);font-size:.8em">(by year)</span>' : ''}</div>
                            </div>
                            <div>
                                <div class="info-item-label">Vacancy</div>
                                <div class="info-item-value">${fmt.pct(p.general_vacancy_pct)}${byYearNote(p, 'general_vacancy_pct')}</div>
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
            <td class="tenant-name">${escapeHtmlAttr(cp.description)}</td>
            <td class="mono right">${fmt.currencyExact(cp.total_amount)}</td>
            <td>${fmt.dateFull(cp.start_date)}</td>
            <td class="mono right">${cp.duration_months}</td>
            <td class="mono right">${fmt.currencyExact(monthly)}</td>
            <td class="col-actions">${rowMenuHtml([
                rowMenuItem(`data-edit-capex="${cp.id}"`, 'Edit project'),
                rowMenuItem(`data-delete-capex="${cp.id}"`, 'Delete project', { danger: true }),
            ], `Actions for ${cp.description}`)}</td>
        </tr>`;
    }).join('');

    return `
        <div class="section-header">
            <h3 class="section-title">Building Improvements</h3>
            <button class="btn btn-primary btn-sm" id="newCapexBtn">${icons.plus} New Project</button>
        </div>
        <div class="data-table-wrap dt-scroll">
            <table class="data-table dt-dense">
                <thead><tr>
                    <th>Description</th><th class="right">Total Cost $</th><th>Start Date</th><th class="right">Duration (mo)</th><th class="right">Monthly Spend $</th><th class="col-actions"><span class="sr-only">Actions</span></th>
                </tr></thead>
                <tbody>${rows || '<tr><td colspan="6" style="text-align:center;color:var(--text-tertiary);padding:32px">No capital projects scheduled</td></tr>'}</tbody>
            </table>
        </div>`;
}


function renderRecoveryPoolsSection(pools, property) {
    const suiteName = Object.fromEntries((property.suites || []).map(s => [s.id, s.suite_name]));
    const denominatorText = p => p.denominator === 'fixed_area' ? `Fixed ${fmt.num(p.fixed_area)} ${property.area_unit === 'unit' ? 'units' : 'SF'}`
        : p.denominator === 'occupied_area' ? `Occupied area${p.minimum_occupancy_pct != null ? `, at least ${fmt.pct(p.minimum_occupancy_pct)}` : ''}`
        : 'Property area less excluded suites';
    const cards = pools.map(p => {
        const excluded = (p.excluded_suite_ids || []).map(id => suiteName[id]).filter(Boolean);
        return `
            <div class="property-card" style="cursor:default;margin-bottom:16px">
                <div class="property-card-header">
                    <div>
                        <div class="property-card-name">${escapeHtmlAttr(p.name)}</div>
                        <div class="property-card-location">${escapeHtmlAttr(p.description || denominatorText(p))}</div>
                    </div>
                    <div class="card-actions">
                        <button class="btn-icon" data-edit-pool="${p.id}" title="Edit">${icons.edit}</button>
                        <button class="btn-icon danger" data-delete-pool="${p.id}" title="Delete">${icons.trash}</button>
                    </div>
                </div>
                <div class="info-grid" style="grid-template-columns:1fr 1fr; gap:10px; margin:16px 0 0">
                    <div><div class="info-item-label">Expenses</div><div class="info-item-value">${p.expense_categories.length ? p.expense_categories.map(c => escapeHtmlAttr(fmt.typeLabel(c))).join(', ') : '—'}</div></div>
                    <div><div class="info-item-label">Denominator</div><div class="info-item-value">${escapeHtmlAttr(denominatorText(p))}</div></div>
                    <div><div class="info-item-label">Excluded Suites</div><div class="info-item-value">${excluded.length ? excluded.map(escapeHtmlAttr).join(', ') : 'None'}</div></div>
                    <div><div class="info-item-label">Excluded Tenants' Recoveries</div><div class="info-item-value">${excluded.length ? (p.deduct_excluded_recoveries ? 'Deducted from pool' : 'Not deducted') : '—'}</div></div>
                </div>
            </div>`;
    }).join('');
    return `
        <div class="section-header" style="margin-top:24px">
            <h3 class="section-title">Recovery Pools</h3>
            <button class="btn btn-primary btn-sm" id="newRecoveryPoolBtn">${icons.plus} New Recovery Pool</button>
        </div>
        ${cards || '<div class="empty-state"><h3>No recovery pools</h3><p>Every recoverable expense is shared over the whole property area. Add a pool to share some expenses over a different area, such as excluding anchors from shop CAM.</p></div>'}`;
}

function renderRecoveryStructuresTab(structures, leases = [], marketProfiles = []) {
    const usedBy = (rs) => {
        const link = (attr, id, name) => `<button type="button" class="form-inline-link" ${attr}="${id}">${escapeHtmlAttr(name)}</button>`;
        const leaseNames = leases.filter(l => l.recovery_structure_id === rs.id)
            .map(l => link('data-edit-lease', l.id, `${l.suite?.suite_name || 'Suite'}${l.tenant ? ' (' + l.tenant.name + ')' : ''}`));
        const profileNames = marketProfiles.filter(m => m.recovery_structure_id === rs.id).map(m => link('data-edit-market', m.id, m.space_type));
        if (!leaseNames.length && !profileNames.length) return 'Not used by any lease or market profile';
        const list = (label, names) => names.length ? `${label}: ${names.slice(0, 6).join(', ')}${names.length > 6 ? ` +${names.length - 6} more` : ''}` : '';
        return [list(`${leaseNames.length} lease${leaseNames.length === 1 ? '' : 's'}`, leaseNames),
            list(`${profileNames.length} market profile${profileNames.length === 1 ? '' : 's'}`, profileNames)].filter(Boolean).join(' · ');
    };
    const cards = structures.map(rs => {
        const itemRows = rs.items.map(item => `
            <tr>
                <td class="tenant-name">${fmt.typeLabel(item.expense_category)}</td>
                <td>${fmt.typeLabel(item.recovery_type)}</td>
                <td class="mono right">${item.recovery_type === 'base_year_stop' && item.base_year_stop_amount != null ? fmt.currency(item.base_year_stop_amount)
                    : item.recovery_type === 'modified_gross' && item.expense_stop_per_sf != null ? fmtRate(item.expense_stop_per_sf) + '/SF' : '—'}</td>
                <td class="mono right">${item.cap_per_sf_annual ? fmtRate(item.cap_per_sf_annual) : '—'}${item.cap_group ? ` <span class="form-help">(${escapeHtmlAttr(item.cap_group)})</span>` : ''}</td>
                <td class="mono right">${item.cap_growth_pct ? fmt.pct(item.cap_growth_pct) : '—'}</td>
                <td class="mono right">${item.floor_per_sf_annual && item.recovery_type !== 'modified_gross' ? fmtRate(item.floor_per_sf_annual) : '—'}</td>
                <td class="mono right">${item.admin_fee_pct ? fmt.pct(item.admin_fee_pct) : '—'}</td>
                <td class="col-actions">
                    <button class="btn-icon danger" data-del-rs-item="${item.id}" data-rs-id="${rs.id}" title="Remove override" aria-label="Remove ${escapeHtmlAttr(fmt.typeLabel(item.expense_category))} override">${icons.trash}</button>
                </td>
            </tr>`).join('');

        return `
            <div class="property-card" style="cursor:default;margin-bottom:16px">
                <div class="property-card-header">
                    <div>
                        <div class="property-card-name">${escapeHtmlAttr(rs.name)}</div>
                        <div class="property-card-location">Default: ${fmt.typeLabel(rs.default_recovery_type)}${rs.default_recovery_type === 'modified_gross' ? (rs.expense_stop_per_sf != null ? `, stop ${fmtRate(rs.expense_stop_per_sf)}/SF` : ', stop resets to base year') : ''}${rs.description ? ' — ' + escapeHtmlAttr(rs.description) : ''}</div>
                    </div>
                    <div class="card-actions">
                        <button class="btn-icon" data-edit-rs="${rs.id}" title="Edit">${icons.edit}</button>
                        <button class="btn-icon danger" data-delete-rs="${rs.id}" title="Delete">${icons.trash}</button>
                    </div>
                </div>
                <div class="form-help" style="margin-top:8px">Used by ${usedBy(rs)}</div>
                ${rs.items.length > 0 ? `
                <div class="data-table-wrap" style="margin-top:16px">
                    <table class="data-table dt-dense" style="margin-bottom:0">
                        <thead><tr><th>Category</th><th>Recovery</th><th class="right">Stop</th><th class="right">Cap $/SF/yr</th><th class="right">Cap Growth</th><th class="right">Floor $/SF/yr</th><th class="right">Admin %</th><th class="col-actions"><span class="sr-only">Actions</span></th></tr></thead>
                        <tbody>${itemRows}</tbody>
                    </table>
                </div>` : '<div style="margin-top:12px;color:var(--text-tertiary);font-size:0.87rem">No per-category overrides — all expenses use the default recovery type.</div>'}
                <div style="margin-top:12px">
                    <button class="btn btn-secondary btn-sm" data-add-rs-item="${rs.id}">${rs.items.length ? `${icons.edit} Edit Category Overrides` : `${icons.plus} Add Category Overrides`}</button>
                </div>
            </div>`;
    }).join('');

    return `
        <div class="section-header">
            <h3 class="section-title">Recovery Structures</h3>
            <button class="btn btn-primary btn-sm" id="newRecoveryStructureBtn">${icons.plus} New Recovery Structure</button>
        </div>
        ${cards || '<div class="empty-state"><h3>No recovery structures</h3><p>Create a reusable recovery template to assign to leases and market leasing profiles.</p></div>'}`;
}


// Hold the engine will use when the valuation sets none: a marina / seniors operating model's own
// hold_years, else the property's default. Mirrors ValuationService._hold_years.
function inheritedHoldYears(valuation, property) {
    const column = { marina: 'marina_assumptions_json', seniors_housing: 'seniors_housing_assumptions_json' }[property?.property_type];
    if (column) {
        try {
            const model = JSON.parse((valuation && valuation[column]) || 'null');
            if (model && model.valuation && model.valuation.hold_years) return parseInt(model.valuation.hold_years, 10);
        } catch { /* fall through */ }
    }
    return Math.round(((property && property.analysis_period_months) || 120) / 12);
}

function effectiveHoldYears(valuation, property) {
    if (valuation && valuation.analysis_period_months_override) return valuation.analysis_period_months_override / 12;
    return inheritedHoldYears(valuation, property);
}

// ─── Review lifecycle: submit, approve, reopen, verify, history ───────────────
// Review timestamps are full datetimes, unlike the model's month dates
function reviewDate(ts) {
    const d = ts ? new Date(ts) : null;
    return d && !isNaN(d) ? d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '—';
}

function reviewActionModal(title, submitLabel, noteLabel, noteRequired, onSubmit) {
    let last = '';
    try { last = localStorage.getItem('opendcf_reviewer_name') || ''; } catch { /* storage unavailable */ }
    showFormModal({
        title,
        submitLabel,
        fields: [
            { key: 'name', label: 'Your name', type: 'text', required: true },
            { key: 'note', label: noteLabel, type: 'textarea', required: noteRequired },
        ],
        defaults: { name: last },
        onSubmit: async (data, overlay) => {
            const name = (data.name || '').trim();
            if (!name) throw new Error('Enter your name');
            if (noteRequired && !(data.note || '').trim()) throw new Error(`${noteLabel} is required`);
            try { localStorage.setItem('opendcf_reviewer_name', name); } catch { /* storage unavailable */ }
            await onSubmit({ name, note: (data.note || '').trim() || null });
            overlay.remove();
        },
    });
}

function wireReviewActions(id, valuation) {
    const post = (path, toastText) => async (body) => {
        await api.post(`/valuations/${id}/${path}`, body);
        toast(toastText, 'success');
        valuationView({ id });
    };
    const on = (btnId, fn) => { const b = document.getElementById(btnId); if (b) b.onclick = fn; };
    on('valSubmitBtn', () => reviewActionModal('Submit for review',
        'Run, freeze & submit', 'Note for the reviewer', false,
        post('submit', 'Submitted. Inputs and results are frozen.')));
    on('valApproveBtn', () => reviewActionModal('Approve valuation', 'Approve', 'Approval note', false,
        post('approve', 'Approved.')));
    on('valReopenBtn', () => reviewActionModal('Reopen valuation', 'Reopen',
        'Reason for reopening', true, post('reopen', 'Reopened as a draft. The frozen version stays in its history.')));
    on('valVerifyBtn', async () => {
        try {
            const r = await api.post(`/valuations/${id}/verify`);
            if (r.error) toast(`Could not re-run the frozen inputs: ${r.error}`, 'error');
            else if (r.matches) toast(`Verified: the frozen inputs still value at ${fmt.currency(r.rerun_npv)}.`, 'success');
            else toast(`Today’s engine values the frozen inputs at ${fmt.currency(r.rerun_npv)}, not ${fmt.currency(r.stored_npv)} (frozen with ${r.engine_version_frozen}, now ${r.engine_version_now}).`, 'error');
        } catch (err) { toast('Verify failed: ' + err.message, 'error'); }
    });
    on('valHistoryBtn', async () => {
        const rows = await api.get(`/valuations/${id}/snapshots`);
        const line = (label, who, when, note) => who
            ? `<div>${label} ${reviewDate(when)} by ${escapeHtmlAttr(who)}${note ? `: “${escapeHtmlAttr(note)}”` : ''}</div>` : '';
        const body = rows.map(s => `
            <div class="review-history-item">
                <div><strong>${fmt.currency(s.result_npv)}</strong> · ${s.status.replace('_', ' ')} · engine ${escapeHtmlAttr(s.engine_version)}</div>
                ${line('Submitted', s.submitted_by, s.submitted_at, s.submit_note)}
                ${line('Approved', s.approved_by, s.approved_at, s.approve_note)}
                ${line('Reopened', s.reopened_by, s.reopened_at, s.reopen_reason)}
            </div>`).join('');
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.innerHTML = `<div class="modal"><h2 class="modal-title">Review history</h2>
            <div class="review-history">${body || '<p>Never frozen.</p>'}</div>
            <div class="modal-actions"><button class="btn btn-secondary" data-close>Close</button></div></div>`;
        overlay.addEventListener('click', (e) => { if (e.target === overlay || e.target.closest('[data-close]')) overlay.remove(); });
        document.body.appendChild(overlay);
    });
}

// Inputs changed after this valuation ran (both timestamps are UTC from the API), or its results
// came from an earlier engine version
function isValuationStale(valuation, property) {
    return valuationStaleReason(valuation) !== null;
}

function valuationStaleReason(valuation) {
    if (valuation.review_status && valuation.review_status !== 'draft') return null;
    if (valuation.status !== 'completed') return null;
    const ran = valuation.last_run_at || valuation.updated_at;
    if (ran && valuation.inputs_updated_at && new Date(ran) < new Date(valuation.inputs_updated_at)) return 'inputs';
    return valuation.engine_outdated ? 'engine' : null;
}


function renderReadinessCard(readiness) {
    if (!readiness) return '';
    const open = readiness.items.filter(i => i.status !== 'done');
    if (open.length === 0) return '';
    const icon = { done: '✓', warning: '!', missing: '○' };
    return `
        <div class="readiness ${readiness.ready ? '' : 'readiness--blocked'}">
            <div class="readiness-head">
                <h2 class="readiness-title">${readiness.ready ? 'Ready to value, with gaps' : 'Set up this property'}</h2>
                <p class="readiness-sub">${readiness.ready
                    ? 'Valuations will run, but these inputs are missing or look incomplete.'
                    : 'Valuations can run once the required items are in.'}</p>
            </div>
            <ol class="readiness-list">
                ${readiness.items.map(i => `
                    <li class="readiness-item readiness-item--${i.status}">
                        <span class="readiness-icon" aria-hidden="true">${icon[i.status] || ''}</span>
                        <span class="readiness-label">${escapeHtmlAttr(i.label)}</span>
                        <span class="readiness-detail">${escapeHtmlAttr(i.detail)}</span>
                        ${i.status !== 'done'
                            ? `<button class="btn ${i.status === 'missing' ? 'btn-primary' : 'btn-secondary'} btn-sm" data-readiness-action="${i.key}">${i.status === 'missing' ? 'Add' : 'Review'}</button>`
                            : ''}
                    </li>`).join('')}
            </ol>
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
        `<option value="${v.id}">${escapeHtmlAttr(v.name)} (${fmt.dateFull(String(v.last_run_at || v.updated_at || v.created_at).slice(0, 10))})</option>`
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
        { label: 'Properties', href: '#/dashboard' },
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
                <div class="help-row"><strong>What it changes</strong><span>Only the expense pool tenants are billed against (recoveries). The landlord's operating expenses in NOI stay as entered.</span></div>
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
                <div class="help-row"><strong>Recovery Pool / Share Denominator</strong><span>The pool the expense is recovered through and the area its pro rata share is taken over (the whole property area when the expense is in no pool). Exp/SF columns use this area.</span></div>
                <div class="help-row"><strong>Pool Deduction</strong><span>Annual recoveries paid by the pool's excluded suites (anchors), taken off the expense before this tenant's share. Post GU Exp/SF is net of it.</span></div>
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
        { label: 'Properties', href: '#/dashboard' },
        { label: 'Tenants' }
    ]);

    let properties;
    try {
        properties = await api.get('/properties');
    } catch (err) {
        $app().innerHTML = `<div class="empty-state"><h3>Cannot load properties</h3><p>${escapeHtmlAttr(err.message)}</p></div>`;
        return;
    }

    if (!properties || properties.length === 0) {
        $app().innerHTML = `
            <div class="empty-state">
                <h3>No properties found</h3>
                <p>Create a property first. Tenants are scoped to each property.</p>
                <br><a href="#/dashboard" class="btn btn-secondary">Back to Properties</a>
            </div>`;
        return;
    }

    const selectedPropertyId = propertyId || properties[0].id;
    const selectedProperty = properties.find(p => p.id === selectedPropertyId) || properties[0];

    // Tenants belong to each valuation: list the one the property page is editing
    let tenants;
    try {
        const model = pickModelValuation(selectedProperty.id, await api.get(`/properties/${selectedProperty.id}/valuations`));
        modelValuationIds[selectedProperty.id] = model?.id;
        tenants = model ? await api.get(`/valuations/${model.id}/tenants`) : [];
    } catch (err) {
        $app().innerHTML = `<div class="empty-state"><h3>Cannot load tenants</h3><p>${escapeHtmlAttr(err.message)}</p></div>`;
        return;
    }

    const propertyOptions = properties.map(p => (
        `<option value="${p.id}" ${p.id === selectedProperty.id ? 'selected' : ''}>${escapeHtmlAttr(p.name)}</option>`
    )).join('');

    const isUnitTenants = selectedProperty.property_type === 'multifamily' || selectedProperty.property_type === 'self_storage';
    const rows = tenants.map(t => `
        <tr>
            <td class="tenant-name">${escapeHtmlAttr(t.name)}</td>
            ${isUnitTenants ? '' : `<td>${t.credit_rating || '—'}</td>`}
            ${isUnitTenants ? '' : `<td>${escapeHtmlAttr(t.industry || '—')}</td>`}
            <td>${escapeHtmlAttr(t.contact_name || '—')}</td>
            <td>${escapeHtmlAttr(t.contact_email || '—')}</td>
            <td class="col-actions">${rowMenuHtml([
                rowMenuItem(`data-edit-tenant="${t.id}"`, 'Edit tenant'),
                rowMenuItem(`data-delete-tenant="${t.id}"`, 'Delete tenant', { danger: true }),
            ], `Actions for ${t.name}`)}</td>
        </tr>`).join('');

    $app().innerHTML = `
        <div class="page-header">
            <h1 class="page-title">Tenants</h1>
            <p class="page-subtitle">${tenants.length} tenant${tenants.length !== 1 ? 's' : ''} for ${escapeHtmlAttr(selectedProperty.name)}</p>
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

        <div class="data-table-wrap dt-scroll">
            <table class="data-table dt-dense">
                <thead>
                    <tr>
                        <th>Name</th>
                        ${isUnitTenants ? '' : '<th>Credit Rating</th>'}
                        ${isUnitTenants ? '' : '<th>Industry</th>'}
                        <th>Contact</th>
                        <th>Email</th>
                        <th class="col-actions"><span class="sr-only">Actions</span></th>
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
                await api.post(`${modelUrl(selectedProperty.id)}/tenants`, data);
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
                    await api.put(`${modelUrl(selectedProperty.id)}/tenants/${tid}`, data);
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
                await api.del(`${modelUrl(selectedProperty.id)}/tenants/${tid}`);
                toast('Tenant deleted', 'success');
                tenantsView({ propertyId: selectedProperty.id });
            });
        });
    });
}


// ─── New Valuation Modal ──────────────────────────────────────

function showNewValuationModal(property, marketProfiles) {
    showValuationForm({
        property,
        marketProfiles,
        onSaved: (val) => { saveModelValuation(property.id, val.id); location.hash = `#/valuation/${val.id}`; },
    });
}


// ─── Valuation Detail ─────────────────────────────────────────

// Shown by WS5's pageSkeleton(path) in navigate() for '/valuation/' routes
function valuationSkeletonHtml() {
    return `
        <div class="ws3-skeleton" aria-busy="true" aria-label="Loading valuation">
            <div class="skeleton skeleton-line skeleton-line--title"></div>
            <div class="skeleton skeleton-line skeleton-line--short"></div>
            <div class="skeleton skeleton-block ws3-skeleton-headline"></div>
            <div class="skeleton skeleton-block ws3-skeleton-chart"></div>
            <div class="skeleton skeleton-block ws3-skeleton-table"></div>
        </div>`;
}

async function valuationView({ id }) {
    const [valuation, fullReport, snapshots] = await Promise.all([
        api.get(`/valuations/${id}`),
        api.get(`/valuations/${id}/reports/full?include_recovery_audit=false`).catch(() => null),
        api.get(`/valuations/${id}/snapshots`).catch(() => []),
    ]);
    const frozen = valuation.review_status && valuation.review_status !== 'draft';
    const currentSnapshot = frozen ? snapshots.find(s => s.id === valuation.snapshot_id) : null;

    // Get property + market profiles + expenses (for reversion gross-up disclosure)
    let property, marketProfiles = [], expenses = [], suites = [];
    try {
        [property, marketProfiles, expenses, suites] = await Promise.all([
            api.get(`/properties/${valuation.property_id}`),
            api.get(`/valuations/${id}/market-profiles`),
            api.get(`/valuations/${id}/expenses`),
            api.get(`/valuations/${id}/suites`),
        ]);
        property.suites = suites;
        if (frozen) {
            // Show the inputs as frozen
            const f = await api.get(`/valuations/${id}/frozen-inputs`);
            property = { ...property, ...f.property };
            marketProfiles = f.market_profiles;
            expenses = f.expenses;
        }
    } catch { property = null; }

    const crumbs = [{ label: 'Properties', href: '#/dashboard' }];
    if (property) crumbs.push({ label: property.name, href: `#/property/${valuation.property_id}` });
    crumbs.push({ label: valuation.name });
    setBreadcrumb(crumbs);
    const effectiveStartDate = valuation.analysis_start_date_override || (property ? property.analysis_start_date : null);
    const startDateLabel = effectiveStartDate ? fmt.date(effectiveStartDate) : '—';
    const startDateSuffix = '';

    // Shared action button wiring (used for both draft and completed states)
    function wireValuationActions() {
        wireValuationCopilot(id, valuation);
        wireWhatIfChat(id);
        // "New valuation from documents" now sits on the property page; the import flow opens it directly
        const openIntake = wireEvidenceWorkspace(id, { isImport: !!property?.external_id?.startsWith('__appraisal_intake__:') });
        if (new URLSearchParams(location.search).get('intake') === '1') {
            requestAnimationFrame(() => openIntake());
        }
        // Edit
        document.getElementById('valMarketBtn')?.addEventListener('click', () => {
            if (!property) { toast('The property for this valuation could not be loaded', 'error'); return; }
            openMarketAssumptionWorkspace(id, property, marketProfiles, () => valuationView({ id }));
        });
        const editBtn = document.getElementById('valEditBtn');
        if (editBtn) {
            editBtn.onclick = () => {
                if (!property) { toast('The property for this valuation could not be loaded', 'error'); return; }
                showValuationForm({ property, valuation, onSaved: () => valuationView({ id }) });
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
        // The model lives with the valuation; the property page edits the valuation picked there
        document.getElementById('valModelBtn')?.addEventListener('click', () => {
            saveModelValuation(valuation.property_id, id);
            location.hash = `#/property/${valuation.property_id}`;
        });
        document.getElementById('valRollForwardBtn')?.addEventListener('click', () =>
            openRollForward(id, (rolled) => { location.hash = `#/valuation/${rolled.id}`; }));
        // Duplicate as a new scenario
        const dupBtn = document.getElementById('valDuplicateBtn');
        if (dupBtn) {
            dupBtn.onclick = async () => {
                try {
                    const copy = await api.post(`/valuations/${id}/duplicate`, {});
                    toast('Valuation copied with its own model. Change it, then run it.', 'success');
                    location.hash = `#/valuation/${copy.id}`;
                } catch (err) {
                    toast('Could not duplicate: ' + err.message, 'error');
                }
            };
        }
        document.querySelector('[data-banner-run]')?.addEventListener('click', () => document.getElementById('valRunBtn')?.click());
        wireReviewActions(id, valuation);
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
                    runBtn.textContent = fullReport ? 'Re-run' : 'Run valuation';
                    runBtn.disabled = false;
                }
            };
        }
        const packageBtn = document.getElementById('valExportPackageBtn');
        if (packageBtn) packageBtn.onclick = () => { location.href = `${API}/valuations/${id}/package?format=zip`; };
        const packageJsonBtn = document.getElementById('valExportPackageJsonBtn');
        if (packageJsonBtn) packageJsonBtn.onclick = () => { location.href = `${API}/valuations/${id}/package`; };
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
        // Full Excel export
        const fullExportBtn = document.getElementById('valExportFullBtn');
        if (fullExportBtn) {
            fullExportBtn.onclick = async () => {
                const original = fullExportBtn.textContent;
                fullExportBtn.textContent = 'Exporting...';
                fullExportBtn.disabled = true;
                try {
                    const res = await fetch(`${API}/valuations/${id}/reports/full-export.xlsx`);
                    if (!res.ok) {
                        const text = await res.text().catch(() => '');
                        throw new Error(`Export failed (${res.status}) ${text}`);
                    }
                    const blob = await res.blob();
                    const cd = res.headers.get('Content-Disposition') || '';
                    const match = cd.match(/filename=\"?([^"]+)\"?/i);
                    const filename = match ? match[1] : `full-export-${id}.xlsx`;
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    URL.revokeObjectURL(url);
                    toast('Full export downloaded', 'success');
                } catch (err) {
                    toast('Error: ' + err.message, 'error');
                } finally {
                    fullExportBtn.textContent = original;
                    fullExportBtn.disabled = false;
                }
            };
        }
        // Investment Memo PDF
        const pdfExportBtn = document.getElementById('valExportPdfBtn');
        if (pdfExportBtn) {
            pdfExportBtn.onclick = async () => {
                const original = pdfExportBtn.textContent;
                pdfExportBtn.textContent = 'Generating...';
                pdfExportBtn.disabled = true;
                try {
                    const res = await fetch(`${API}/valuations/${id}/reports/investment-memo.pdf`);
                    if (!res.ok) {
                        const text = await res.text().catch(() => '');
                        throw new Error(`PDF generation failed (${res.status}) ${text}`);
                    }
                    const blob = await res.blob();
                    const cd = res.headers.get('Content-Disposition') || '';
                    const match = cd.match(/filename=\"?([^"]+)\"?/i);
                    const filename = match ? match[1] : `investment-memo-${id}.pdf`;
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    URL.revokeObjectURL(url);
                    toast('Investment memo downloaded', 'success');
                } catch (err) {
                    toast('Error: ' + err.message, 'error');
                } finally {
                    pdfExportBtn.textContent = original;
                    pdfExportBtn.disabled = false;
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
    const hasResults = fullReport && fullReport.key_metrics;
    const stale = hasResults && isValuationStale(valuation, property);
    const actionButtons = `
        <div class="property-header-actions">
            ${frozen && isMultifamilyVal ? '' : menuHtml('Analyze', [
                frozen ? '' : menuItem('valWhatIfChatBtn', 'What if…', { hint: 'Test a change without saving it' }),
                frozen ? '' : menuItem('valCopilotBtn', 'AI copilot', { hint: 'Ask about or adjust this valuation' }),
                isMultifamilyVal ? '' : menuItem('valAuditBtn', 'Tenant recovery audit', { hint: 'Opens on the property page, Recoveries tab' }),
            ])}
            ${menuHtml('Valuation', [
                frozen ? menuItem('valVerifyBtn', 'Verify frozen result', { hint: 'Re-run the frozen inputs on today’s engine' }) : '',
                snapshots.length ? menuItem('valHistoryBtn', 'Review history') : '',
                menuItem('valDuplicateBtn', 'Copy valuation and model'),
                menuItem('valRollForwardBtn', 'Roll forward…', { hint: 'Copy with the analysis start moved forward' }),
                frozen ? '' : menuItem('valDeleteBtn', 'Delete valuation…', { danger: true }),
            ])}
            ${menuHtml('Export', [
                hasResults ? menuItem('valExportFullBtn', 'Full model (Excel)') : '',
                hasResults ? menuItem('valExportPdfBtn', 'Investment memo (PDF)') : '',
                menuItem('valExportRentRollBtn', 'Rent roll (Excel)'),
                menuItem('valExportPackageBtn', 'Deal package (.odcf.zip)', { hint: 'Model, documents and evidence, to send to someone' }),
                menuItem('valExportPackageJsonBtn', 'Model and facts only (.odcf.json)'),
            ])}
            ${frozen ? `
            <button class="btn btn-secondary btn-sm" id="valReopenBtn">Reopen…</button>
            ${valuation.review_status === 'in_review' ? '<button class="btn btn-primary btn-sm" id="valApproveBtn">Approve…</button>' : ''}` : `
            <button class="btn btn-secondary btn-sm" id="valEditBtn" title="Hold, discount and cap rates, exit, financing and other valuation settings">${icons.edit} Rates &amp; exit</button>
            <button class="btn btn-secondary btn-sm" id="valModelBtn" title="This valuation's own rent roll, expenses, market leasing and recoveries">Rent roll &amp; expenses</button>
            <button class="btn btn-secondary btn-sm" id="valMarketBtn" title="This valuation's own market leasing assumptions">Market leasing (${marketProfiles.length})</button>
            ${hasResults ? '<button class="btn btn-secondary btn-sm" id="valSubmitBtn">Submit for review…</button>' : ''}
            <button class="btn btn-primary btn-sm" id="valRunBtn">${hasResults ? 'Re-run' : 'Run valuation'}</button>`}
        </div>`;
    const reviewBanner = currentSnapshot ? `
        <div class="banner ${valuation.review_status === 'approved' ? 'banner-ok' : 'banner-info'}">
            <strong>${valuation.review_status === 'approved' ? 'Approved' : 'In review'}.</strong>
            Frozen ${reviewDate(currentSnapshot.submitted_at)} by ${escapeHtmlAttr(currentSnapshot.submitted_by)}${currentSnapshot.submit_note ? ` (“${escapeHtmlAttr(currentSnapshot.submit_note)}”)` : ''}${currentSnapshot.approved_by ? `; approved ${reviewDate(currentSnapshot.approved_at)} by ${escapeHtmlAttr(currentSnapshot.approved_by)}${currentSnapshot.approve_note ? ` (“${escapeHtmlAttr(currentSnapshot.approve_note)}”)` : ''}` : ''}.
            Results and reports show the inputs as frozen; later property edits do not change them.
            ${valuation.engine_outdated ? 'These results were calculated with an earlier engine version; Valuation › Verify frozen result compares them with today’s engine.' : ''}
        </div>` : '';
    const staleBanner = stale ? `
        <div class="banner banner-warn">
            <strong>${valuationStaleReason(valuation) === 'engine' ? 'The valuation engine was updated after this ran.' : 'Property inputs changed after this ran.'}</strong> These results may be out of date.
            <button class="btn btn-primary btn-sm" data-banner-run>Re-run now</button>
        </div>` : '';
    const holdYears = effectiveHoldYears(valuation, property);

    if (!fullReport || !fullReport.key_metrics) {
        $app().innerHTML = `
            <div class="property-header">
                <div class="property-header-left">
                    <h1 class="property-header-title">${escapeHtmlAttr(valuation.name)}</h1>
                    <div class="property-header-address">${property ? escapeHtmlAttr(property.name) + ' &middot; ' : ''}${holdYears}-yr hold from ${startDateLabel} &middot; ${fmt.pct(valuation.discount_rate)} discount &middot; ${fmt.pct(valuation.exit_cap_rate)} exit cap</div>
                </div>
                ${actionButtons}
            </div>
            <div class="empty-state">
                <h3>${valuation.status === 'failed' ? 'This valuation could not run' : 'Not run yet'}</h3>
                ${valuation.error_message
                    ? `<p style="color:var(--red);margin-top:12px">${escapeHtmlAttr(valuation.error_message)}</p>
                       ${property ? `<p><a class="btn btn-secondary btn-sm" href="#/property/${property.id}">Open property inputs</a></p>` : ''}`
                    : '<p>Run it to project the cash flows and value.</p>'}
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
    // What-if reprices the stored run on the generic grid; marina and seniors housing don't use it
    const showWhatIf = km.terminal_noi_basis != null
        && !(property && ['marina', 'seniors_housing'].includes(property.property_type));

    $app().innerHTML = `
        <div class="property-header">
            <div class="property-header-left">
                <h1 class="property-header-title">${escapeHtmlAttr(valuation.name)}</h1>
                <div class="property-header-address">${property ? escapeHtmlAttr(property.name) + ' &middot; ' : ''}${holdYears}-yr hold from ${startDateLabel}${startDateSuffix} &middot; ${fmt.pct(valuation.discount_rate)} discount &middot; ${fmt.pct(valuation.exit_cap_rate)} exit cap${valuation.loan_amount ? ' &middot; Levered' : ''}</div>
            </div>
            ${actionButtons}
        </div>
        ${staleBanner}
        ${reviewBanner}

        ${renderValuationHeadline(valuation, km, property, holdYears, startDateLabel)}

        <div class="chart-container ws3-cf-chart">
            <div class="ws3-chart-head">
                <div class="chart-title" id="cfChartTitle">Net Operating Income</div>
                <div class="ws3-seg" role="group" aria-label="Chart series">
                    <button type="button" class="ws3-seg-btn" data-series="noi" aria-pressed="true">NOI</button>
                    <button type="button" class="ws3-seg-btn" data-series="cfbd" aria-pressed="false">Cash flow before debt</button>
                </div>
            </div>
            <div class="chart-wrap"><canvas id="cfChart"></canvas></div>
        </div>

        <div class="ws3-whatif-row${showWhatIf ? '' : ' ws3-whatif-row--single'}">
            ${showWhatIf ? '<div id="whatIfSection"></div>' : ''}
            <div id="sensitivitySection"></div>
        </div>

        ${showLeaseExpirations && expirations.length > 0 ? `
        <div class="chart-container">
            <div class="chart-title">Lease Expiration Schedule</div>
            <div class="chart-wrap"><canvas id="expChart"></canvas></div>
        </div>` : ''}

        <!-- Annual Cash Flow Table -->
        <div class="section-header">
            <h3 class="section-title" id="cfTableTitle">Annual Cash Flow Summary</h3>
            ${km.terminal_noi_basis != null ? `
            <select class="form-input" id="cfPeriodSelect" style="width:auto">
                <option value="annual">Annual</option>
                <option value="monthly">Monthly</option>
            </select>` : ''}
        </div>
        <div class="cf-table-wrap ws3-cf-wrap" id="cfTableWrap">
            ${renderCashFlowTable(
                cf,
                tenants,
                marketProfiles,
                property ? property.area_unit : 'sf',
                property ? property.property_type : ''
            )}
        </div>
        ${renderReversionValueSection(valuation, km, cf, expenses)}
        ${renderReturnsSection(km)}
        <div id="monteCarloSection"></div>
    `;
    if (km.terminal_noi_basis != null) loadSensitivitySection(id);
    if (showWhatIf) renderWhatIfPanel(document.getElementById('whatIfSection'), { valuation, km, property, stale });
    const storageModelled = property?.property_type === 'self_storage' && !!valuation.self_storage_assumptions_json;
    if (!property || (!['marina', 'seniors_housing'].includes(property.property_type) && !storageModelled)) loadMonteCarloSection(id);

    // Render charts
    renderValuationCashFlowChart(cf);
    if (showLeaseExpirations && expirations.length > 0) {
        renderExpirationChart(expirations, property ? property.area_unit : 'sf', property ? property.property_type : '');
    }

    wireValuationActions();

    // Expandable cash flow rows
    const wireCfTable = () => {
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
    };
    wireCfTable();

    // Annual / monthly cash flow toggle (monthly re-runs the model on request)
    const periodSelect = document.getElementById('cfPeriodSelect');
    if (periodSelect) {
        const areaUnit = property ? property.area_unit : 'sf';
        const propertyType = property ? property.property_type : '';
        periodSelect.onchange = async () => {
            const monthly = periodSelect.value === 'monthly';
            const wrap = document.getElementById('cfTableWrap');
            document.getElementById('cfTableTitle').textContent = monthly ? 'Monthly Cash Flow' : 'Annual Cash Flow Summary';
            if (!monthly) {
                wrap.innerHTML = renderCashFlowTable(cf, tenants, marketProfiles, areaUnit, propertyType);
            } else {
                wrap.innerHTML = '<div class="loading-spinner"></div>';
                try {
                    const months = await api.get(`/valuations/${id}/reports/monthly-cash-flows`);
                    wrap.innerHTML = renderCashFlowTable(months, [], marketProfiles, areaUnit, propertyType);
                } catch (err) {
                    wrap.innerHTML = `<div class="empty-state"><p>${escapeHtmlAttr(err.message)}</p></div>`;
                }
            }
            wireCfTable();
        };
    }
}

function wireValuationCopilot(valuationId, valuation) {
    const button = document.getElementById('valCopilotBtn');
    if (!button) return;
    button.onclick = () => {
        document.getElementById('valuationCopilot')?.remove();
        const panel = document.createElement('aside');
        panel.id = 'valuationCopilot';
        panel.className = 'copilot-panel';
        panel.innerHTML = `
            <div class="copilot-head"><div><strong>OpenDCF Copilot</strong><small>Ask or change the active model</small></div><button class="btn btn-sm" id="copilotClose">×</button></div>
            <div class="copilot-permission"><label><input type="checkbox" id="copilotAlways" ${valuation.ai_permission_mode === 'always_allow' ? 'checked' : ''}> Always allow changes</label><span>Dangerous: skips confirmation</span></div>
            <div class="copilot-messages" id="copilotMessages"><div class="copilot-msg ai">Try “What is the renewal probability for ABC tenant?” or “Change market rent for the anchor to $12/SF.”</div></div>
            <form class="copilot-form" id="copilotForm"><textarea id="copilotInput" rows="3" placeholder="Ask about or change this valuation…" required></textarea><button class="btn btn-primary" type="submit">Send</button></form>`;
        document.body.appendChild(panel);
        panel.querySelector('#copilotClose').onclick = () => panel.remove();
        panel.querySelector('#copilotAlways').onchange = async (event) => {
            const enabled = event.target.checked;
            if (enabled && !confirm('Always allow lets AI-supported changes apply without review. Enable it for this valuation?')) {
                event.target.checked = false; return;
            }
            try {
                await api.put(`/valuations/${valuationId}/copilot-permission`, {mode: enabled ? 'always_allow' : 'confirm'});
                valuation.ai_permission_mode = enabled ? 'always_allow' : 'confirm';
                toast(enabled ? 'AI changes will auto-apply' : 'Confirmation restored', enabled ? 'warning' : 'success');
            } catch (err) { event.target.checked = !enabled; toast(err.message, 'error'); }
        };
        panel.querySelector('#copilotForm').onsubmit = async (event) => {
            event.preventDefault();
            const input = panel.querySelector('#copilotInput');
            const message = input.value.trim();
            if (!message) return;
            const messages = panel.querySelector('#copilotMessages');
            messages.insertAdjacentHTML('beforeend', `<div class="copilot-msg user">${escapeHtmlAttr(message)}</div><div class="copilot-msg ai pending">Thinking…</div>`);
            input.value = '';
            try {
                const result = await api.post(`/valuations/${valuationId}/copilot`, {message});
                messages.querySelector('.pending')?.remove();
                const changes = (result.changes || []).map(c => `<li><code>${escapeHtmlAttr(c.entity_type)}.${escapeHtmlAttr(c.field)}</code>: ${escapeHtmlAttr(String(c.old_value ?? '—'))} → <strong>${escapeHtmlAttr(String(c.new_value))}</strong></li>`).join('');
                const card = document.createElement('div');
                card.className = 'copilot-msg ai';
                card.innerHTML = `<div>${escapeHtmlAttr(result.message)}</div>${changes ? `<ul>${changes}</ul>` : ''}${result.status === 'pending_confirmation' ? '<div class="copilot-actions"><button class="btn btn-primary btn-sm" data-apply>Apply changes</button><button class="btn btn-secondary btn-sm" data-reject>Reject</button></div>' : result.status === 'applied' ? '<small>Applied automatically and audit-logged.</small>' : ''}`;
                messages.appendChild(card);
                card.querySelector('[data-apply]')?.addEventListener('click', async () => {
                    await api.post(`/valuations/${valuationId}/copilot/${result.action_id}/confirm`);
                    toast('AI changes applied', 'success'); valuationView({id: valuationId});
                });
                card.querySelector('[data-reject]')?.addEventListener('click', async () => {
                    await api.post(`/valuations/${valuationId}/copilot/${result.action_id}/reject`);
                    card.querySelector('.copilot-actions').innerHTML = '<small>Rejected.</small>';
                });
            } catch (err) {
                const pending = messages.querySelector('.pending');
                if (pending) pending.textContent = err.message;
            }
            messages.scrollTop = messages.scrollHeight;
        };
    };
}

function wireEvidenceWorkspace(valuationId) {
    const button = document.getElementById('valEvidenceBtn');
    if (!button) return;
    button.onclick = async () => {
        document.getElementById('evidenceWorkspace')?.remove();
        const panel = document.createElement('aside');
        panel.id = 'evidenceWorkspace';
        panel.className = 'copilot-panel evidence-panel';
        panel.innerHTML = `<div class="copilot-head"><div><strong>Appraisal Evidence</strong><small>Source-linked facts for valuation creation</small></div><button class="btn btn-sm" data-close>×</button></div><div class="evidence-upload"><input type="file" multiple id="evidenceFiles"><button class="btn btn-primary btn-sm" data-upload>Upload</button><a class="btn btn-secondary btn-sm" href="${API}/valuations/${valuationId}/package?format=zip">Export deal package (.odcf.zip)</a></div><div class="copilot-messages" data-content><div class="loading-spinner"></div></div>`;
        document.body.appendChild(panel);
        panel.querySelector('[data-close]').onclick = () => panel.remove();
        const load = async () => {
            const content = panel.querySelector('[data-content]');
            try {
                const [docs, reconstructions, review] = await Promise.all([
                    api.get(`/valuations/${valuationId}/documents`),
                    api.get(`/valuations/${valuationId}/appraisal-reconstructions`),
                    api.get(`/valuations/${valuationId}/document-review`),
                ]);
                const issues = (review.issues || []).map(i => `<div class="evidence-issue ${i.severity}">${escapeHtmlAttr(i.message)}</div>`).join('');
                const docRows = docs.map(d => `<div class="evidence-card"><div><strong>${escapeHtmlAttr(d.original_filename)}</strong><small>${escapeHtmlAttr(d.document_type || 'Unclassified')} · ${escapeHtmlAttr(d.status)} · SHA ${d.sha256.slice(0, 10)}</small></div><div>${d.status !== 'processed' ? `<button class="btn btn-primary btn-sm" data-process="${d.id}">Process</button>` : ''}${d.status === 'processed' && d.document_type === 'appraisal' ? `<button class="btn btn-secondary btn-sm" data-rebuild="${d.id}">Prepare valuation</button>` : ''}</div></div>`).join('') || '<div class="empty-state"><p>No evidence uploaded.</p></div>';
                const rebuildRows = reconstructions.map(r => `<details class="evidence-card reconstruction"><summary><strong>Valuation setup</strong><small>${escapeHtmlAttr(r.status)} · ${r.unresolved.length} items requiring review</small></summary><textarea data-plan="${r.id}" rows="12">${escapeHtmlAttr(JSON.stringify(r.plan, null, 2))}</textarea><div class="copilot-actions">${r.status === 'staged' ? `<button class="btn btn-secondary btn-sm" data-save-plan="${r.id}">Save setup</button><button class="btn btn-primary btn-sm" data-materialize="${r.id}">Create valuation</button>` : `<a class="btn btn-primary btn-sm" href="#/valuation/${r.rebuilt_valuation_id}">Open valuation</a>`}<button class="btn btn-secondary btn-sm" data-comparison="${r.id}">Comparison</button></div></details>`).join('');
                content.innerHTML = `${issues}<h4>Documents</h4>${docRows}<h4>Valuation setup</h4>${rebuildRows || '<p class="muted">No valuation setup prepared.</p>'}`;
                content.querySelectorAll('[data-process]').forEach(el => el.onclick = async () => { el.disabled = true; el.textContent = 'Processing…'; try { await api.post(`/valuations/${valuationId}/documents/${el.dataset.process}/process`); await load(); } catch (err) { toast(err.message, 'error'); el.disabled = false; } });
                content.querySelectorAll('[data-rebuild]').forEach(el => el.onclick = async () => { await api.post(`/valuations/${valuationId}/appraisal-reconstructions`, {document_id: el.dataset.rebuild}); toast('Valuation setup prepared', 'success'); await load(); });
                content.querySelectorAll('[data-save-plan]').forEach(el => el.onclick = async () => { try { const plan = JSON.parse(content.querySelector(`[data-plan="${el.dataset.savePlan}"]`).value); await api.put(`/appraisal-reconstructions/${el.dataset.savePlan}`, {plan}); toast('Staged model saved', 'success'); } catch (err) { toast(err.message, 'error'); } });
                content.querySelectorAll('[data-materialize]').forEach(el => el.onclick = async () => { if (!confirm('Create this property and valuation in OpenDCF?')) return; try { const result = await api.post(`/appraisal-reconstructions/${el.dataset.materialize}/materialize`); toast('OpenDCF valuation created', 'success'); location.hash = `#/valuation/${result.rebuilt_valuation_id}`; } catch (err) { toast(err.message, 'error'); } });
                content.querySelectorAll('[data-comparison]').forEach(el => el.onclick = async () => { const result = await api.get(`/appraisal-reconstructions/${el.dataset.comparison}/comparison`); alert(Object.entries(result.metrics).map(([key, v]) => `${key}: source ${v.source ?? '—'} | rebuilt ${v.rebuilt ?? '—'} | variance ${v.variance ?? '—'}`).join('\n')); });
            } catch (err) { content.innerHTML = `<div class="evidence-issue critical">${escapeHtmlAttr(err.message)}</div>`; }
        };
        panel.querySelector('[data-upload]').onclick = async () => {
            const files = panel.querySelector('#evidenceFiles').files;
            if (!files.length) return;
            const form = new FormData(); [...files].forEach(file => form.append('files', file));
            try { const response = await fetch(`${API}/valuations/${valuationId}/documents`, {method:'POST', body:form}); if (!response.ok) throw new Error(await response.text()); toast('Evidence uploaded', 'success'); await load(); } catch (err) { toast(err.message, 'error'); }
        };
        await load();
    };
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
            const nyc = gross <= 500000 ? 0.01425 : 0.02625;
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
    // Next year's capital, deducted from the sale when the valuation is set to
    const capitalDeduction = asNum(keyMetrics.terminal_capital_deduction_amount);
    const netReversion = grossReversion - exitCostsAmount - transferTaxAmount - capitalDeduction;
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
                        <td>Gross up eligible expenses in tenant recovery pools</td>
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
                        <td>Gross up eligible expenses in tenant recovery pools</td>
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
                    ${capitalDeduction ? `
                    <tr>
                        <td>Less: Forward-Year Capital</td>
                        <td>Capital in the year after the hold</td>
                        <td class="mono right negative">-${fmt.currencyExact(capitalDeduction)}</td>
                    </tr>` : ''}
                    <tr>
                        <td><strong>Net Reversion (Terminal Value)</strong></td>
                        <td>Gross Reversion − Exit Costs − Transfer Tax${capitalDeduction ? ' − Capital' : ''}</td>
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


function mlaTooltipHtml(m, area, areaUnit, propertyType = '') {
    const au = areaUnit;
    return `<strong>${escapeHtmlAttr(fmt.typeLabel(m.space_type))} Market Profile</strong>
${area ? `<span>Suite: ${fmt.sf(area, au, propertyType)}</span>` : ''}
<span>Market Rent: ${fmt.perSf(m.market_rent_per_unit, au)}</span>
<span>Rent Growth: ${fmt.pct(m.rent_growth_rate_pct)}/yr</span>
<span>Renewal Prob: ${fmt.pct(m.renewal_probability)}</span>
<span>Downtime: ${m.downtime_months} mo</span>
<span>New TI: ${fmt.perSf(m.new_tenant_ti_per_sf, au)} | LC: ${fmt.pct(m.new_tenant_lc_pct)}${byYearNote(m, 'new_tenant_lc_pct')}${parseFloat(m.new_tenant_lc_per_sf) ? ` + ${fmt.perSf(m.new_tenant_lc_per_sf, au)}` : ''}</span>
<span>Renewal TI: ${fmt.perSf(m.renewal_ti_per_sf, au)} | LC: ${fmt.pct(m.renewal_lc_pct)}${byYearNote(m, 'renewal_lc_pct')}${parseFloat(m.renewal_lc_per_sf) ? ` + ${fmt.perSf(m.renewal_lc_per_sf, au)}` : ''}</span>
<span>Vacancy: ${fmt.pct(m.general_vacancy_pct)} | Credit Loss: ${fmt.pct(m.credit_loss_pct)}</span>`;
}

// Contract rent today for a tenant row (set when the results are read; absent when vacant today)
function currentRentTooltipHtml(t, areaUnit) {
    if (t.current_rent_annual == null) return '';
    const monthly = t.current_rent_frequency === 'monthly';
    const rate = t.current_rent_basis === 'total'
        ? ''
        : ` (${monthly ? `${fmt.currencyExact(t.current_rent_rate)}/unit/mo` : fmt.perSf(t.current_rent_rate, areaUnit)})`;
    return `<strong>Current Rent Today</strong>
<span style="margin-bottom:8px">${fmt.currencyExact(t.current_rent_annual)}/yr${rate}</span>
`;
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

// Statement figures: whole dollars, negatives in parentheses; the $ unit lives in the header
function fmtStatement(val) {
    const n = parseFloat(val);
    if (isNaN(n)) return '—';
    const r = Math.round(n);
    const s = Math.abs(r).toLocaleString('en-US');
    return r < 0 ? `(${s})` : s;
}

function renderCashFlowTable(cashFlows, tenants, mktProfiles, areaUnit, propertyType = '') {
    if (!cashFlows || cashFlows.length === 0) return '<div class="empty-state"><p>No cash flow data</p></div>';
    const numYears = cashFlows.length;
    const hasTenants = tenants && tenants.length > 0;
    // Self storage valued from a unit mix: rents are against street rate, nothing is recovered
    const storage = cashFlows.some(cf => cf.storage_detail);

    // Build market profile lookup by space_type for tooltips
    const mlaByType = {};
    (mktProfiles || []).forEach(m => { mlaByType[m.space_type] = m; });

    const header = `<tr>
        <th>Line item <span class="ws3-unit">($)</span></th>
        ${cashFlows.map(cf => `<th class="right" title="${fiscalYearRangeLabel(cf)}">${fiscalYearLabel(cf)}</th>`).join('')}
    </tr>`;

    const row = (label, field, cls = '') => `<tr class="${cls}">
        <td>${label}</td>
        ${cashFlows.map(cf => {
            const v = parseFloat(cf[field]);
            const neg = v < 0 ? 'negative' : '';
            return `<td class="${neg}">${fmtStatement(v)}</td>`;
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
                return `<td class="${neg}">${fmtStatement(v)}</td>`;
            }).join('')}
        </tr>`;
        // Sub-rows per tenant
        tenants.forEach((t, ti) => {
            const vals = t[tenantField] || [];
            // Skip if all zeros
            if (vals.every(v => parseFloat(v) === 0)) return;
            const tenantLabel = escapeHtmlAttr(`${t.suite_name}${t.tenant_name ? ' — ' + t.tenant_name : ''}`);
            const scenarioTag = t.scenario !== 'in_place' ? ` <span style="font-size:0.67rem;opacity:0.7">${fmt.typeLabel(t.scenario)}</span>` : '';
            const mla = mlaByType[t.space_type];
            const tipHtml = currentRentTooltipHtml(t, areaUnit) + (mla ? mlaTooltipHtml(mla, t.area, areaUnit, propertyType) : '');
            const mlaAttr = tipHtml ? ` data-mla="${encodeURIComponent(tipHtml)}"` : '';
            html += `<tr class="sub-row" data-group="${groupId}">
                <td><span class="mla-hover"${mlaAttr}>${tenantLabel}${scenarioTag}</span></td>
                ${vals.slice(0, numYears).map(v => {
                    const n = parseFloat(v);
                    const neg = n < 0 ? 'negative' : '';
                    return `<td class="${neg}">${fmtStatement(n)}</td>`;
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
                return `<td class="${neg}">${fmtStatement(v)}</td>`;
            }).join('')}
        </tr>`;
        [...categories].sort().forEach(cat => {
            html += `<tr class="sub-row" data-group="${groupId}">
                <td>${escapeHtmlAttr(fmt.typeLabel(cat))}</td>
                ${cashFlows.map(cf => {
                    const v = cf.expense_detail ? parseFloat(cf.expense_detail[cat] || 0) : 0;
                    const neg = v < 0 ? 'negative' : '';
                    return `<td class="${neg}">${fmtStatement(v)}</td>`;
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
                return `<td class="${neg}">${fmtStatement(v)}</td>`;
            }).join('')}
        </tr>`;
        [...categories].sort().forEach(cat => {
            html += `<tr class="sub-row" data-group="${groupId}">
                <td>${escapeHtmlAttr(fmt.typeLabel(cat))}</td>
                ${cashFlows.map(cf => {
                    const v = cf.other_income_detail ? parseFloat(cf.other_income_detail[cat] || 0) : 0;
                    const neg = v < 0 ? 'negative' : '';
                    return `<td class="${neg}">${fmtStatement(v)}</td>`;
                }).join('')}
            </tr>`;
        });
        return html;
    };

    // (TI/LC now shown as separate expandable rows below)

    return `<table class="cf-table cf-table--statement" id="cfTable">
        <thead>${header}</thead>
        <tbody>
            <tr class="subtotal">
                <td>${storage ? 'Street Rent Potential' : 'Market Rent Potential'}</td>
                ${cashFlows.map(cf => {
                    const v = parseFloat(cf.gross_potential_rent) - parseFloat(cf.absorption_vacancy) - parseFloat(cf.loss_to_lease);
                    return `<td>${fmtStatement(v)}</td>`;
                }).join('')}
            </tr>
            ${expandableRow(storage ? 'Vacancy at Street Rate' : 'Turnover Vacancy', 'absorption_vacancy', 'annual_turnover_vacancy')}
            ${expandableRow(storage ? 'Loss (Gain) to Lease' : 'Loss to Lease', 'loss_to_lease', 'annual_loss_to_lease')}
            ${expandableRow(storage ? 'In-Place Rent' : 'Scheduled Base Rent', 'gross_potential_rent', 'annual_base_rent')}
            ${expandableRow(storage ? 'Move-in Concessions' : 'Free Rent', 'free_rent', 'annual_free_rent')}
            ${storage ? '' : expandableRow('Expense Recoveries', 'expense_recoveries', 'annual_recoveries')}
            ${storage ? '' : row('Percentage Rent', 'percentage_rent')}
            ${expandableOtherIncomeRow()}
            ${row('Gross Potential Income', 'gross_potential_income', 'subtotal')}
            ${row('General Vacancy', 'general_vacancy_loss')}
            ${row('Credit Loss', 'credit_loss')}
            ${row('Effective Gross Income', 'effective_gross_income', 'subtotal rule-above')}
            ${expandableExpenseRow()}
            ${row('Net Operating Income', 'net_operating_income', 'total rule-above')}
            ${expandableRow('Tenant Improvements', 'tenant_improvements', 'annual_ti')}
            ${expandableRow('Leasing Commissions', 'leasing_commissions', 'annual_lc')}
            ${row('Capital Reserves', 'capital_reserves')}
            ${row('Building Improvements', 'building_improvements')}
            ${row('Cash Flow Before Debt', 'cash_flow_before_debt', 'total rule-above')}
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
            <td class="tenant-name">${escapeHtmlAttr(t.suite_name)}</td>
            <td>${t.tenant_name ? escapeHtmlAttr(t.tenant_name) : '<span class="vacant">Vacant</span>'}</td>
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

// Value per SF / unit / slip label used by the valuation headline and what-if panel
function valuePerAreaLabel(value, property) {
    const area = property ? parseFloat(property.total_area) : 0;
    const v = parseFloat(value);
    if (!(area > 0) || isNaN(v)) return '';
    if (property.area_unit === 'unit') {
        return fmt.currencyExact(v / area) + (property.property_type === 'marina' ? '/slip' : '/unit');
    }
    return '$' + Math.round(v / area).toLocaleString('en-US') + '/SF';
}

function renderValuationHeadline(valuation, km, property, holdYears, startDateLabel) {
    const perArea = valuePerAreaLabel(km.npv, property);
    const sentence = `${fmt.currency(km.npv)}${perArea ? ` (${perArea})` : ''} at a ${fmt.pct(valuation.discount_rate)} discount rate`
        + ` and ${fmt.pct(valuation.exit_cap_rate)} exit cap, ${holdYears}-year hold from ${startDateLabel}`;
    const metric = (label, value, sub = '') => `
        <div class="ws3-metric">
            <dt>${label}</dt>
            <dd>${value}${sub ? `<span class="ws3-metric-sub">${sub}</span>` : ''}</dd>
        </div>`;
    const hasPrice = valuation.purchase_price && km.irr != null;
    return `
        <section class="ws3-headline" aria-label="Valuation result">
            <div class="ws3-headline-label">Value (NPV)</div>
            <div class="ws3-headline-value">${fmt.currencyExact(km.npv)}</div>
            <p class="ws3-headline-sentence">${sentence}${valuation.loan_amount ? ' &middot; levered' : ''}.</p>
            <dl class="ws3-metrics">
                ${metric('Going-in cap', fmt.pct(km.going_in_cap_rate))}
                ${metric('Terminal value', fmt.currency(km.terminal_value))}
                ${metric('Avg occupancy', fmt.pct(km.avg_occupancy_pct, 1))}
                ${metric('WALT', km.weighted_avg_lease_term_years != null ? fmt.years(km.weighted_avg_lease_term_years) : '—')}
                ${hasPrice ? metric('IRR', fmt.pct(km.irr), 'at ' + fmt.currency(valuation.purchase_price)) : ''}
            </dl>
        </section>`;
}

// Chart colors come from CSS tokens so they follow the active theme
function chartToken(name, fallbackName = '') {
    const css = getComputedStyle(document.documentElement);
    return css.getPropertyValue(name).trim() || (fallbackName ? css.getPropertyValue(fallbackName).trim() : '');
}

// One cash-flow chart with an NOI / cash-flow-before-debt toggle
function renderValuationCashFlowChart(cf) {
    const canvas = document.getElementById('cfChart');
    if (!canvas) return;
    const series = {
        noi: { title: 'Net Operating Income', short: 'NOI', field: 'net_operating_income', token: '--chart-1' },
        cfbd: { title: 'Cash Flow Before Debt', short: 'CFBD', field: 'cash_flow_before_debt', token: '--chart-2' },
    };
    let current = 'noi';
    const values = () => cf.map(c => parseFloat(c[series[current].field]));
    const colors = () => {
        const pos = chartToken(series[current].token);
        const neg = chartToken('--red');
        return values().map(v => (v < 0 ? neg : pos));
    };
    const chart = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: cf.map(c => fiscalYearLabel(c)),
            datasets: [{ data: values(), backgroundColor: colors(), borderRadius: 3, maxBarThickness: 48 }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: { callback: v => fmt.currency(v), color: chartToken('--chart-text') },
                    grid: { color: chartToken('--chart-grid') },
                    border: { display: false },
                },
                x: { grid: { display: false }, ticks: { color: chartToken('--chart-text') } },
            },
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: ctx => `${series[current].short}: ${fmt.currencyExact(ctx.raw)}` } },
            },
        },
    });

    const applyTheme = () => {
        const text = chartToken('--chart-text');
        chart.data.datasets[0].backgroundColor = colors();
        chart.options.scales.y.grid.color = chartToken('--chart-grid');
        chart.options.scales.y.ticks.color = text;
        chart.options.scales.x.ticks.color = text;
        chart.update('none');
    };
    document.querySelectorAll('.ws3-cf-chart .ws3-seg-btn').forEach(btn => {
        btn.onclick = () => {
            current = btn.dataset.series;
            document.querySelectorAll('.ws3-cf-chart .ws3-seg-btn').forEach(b => b.setAttribute('aria-pressed', String(b === btn)));
            document.getElementById('cfChartTitle').textContent = series[current].title;
            chart.data.datasets[0].data = values();
            applyTheme();
        };
    });

    // Recolor when the theme changes; stop listening once the page is replaced
    const media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
    const observer = new MutationObserver(() => onThemeChange());
    function onThemeChange() {
        if (!document.body.contains(canvas)) {
            observer.disconnect();
            media?.removeEventListener?.('change', onThemeChange);
            return;
        }
        applyTheme();
    }
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class'] });
    media?.addEventListener?.('change', onThemeChange);
}


function renderExpirationChart(expirations, areaUnit = 'sf', propertyType = '') {
    const ctx = document.getElementById('expChart');
    if (!ctx) return;
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: expirations.map(e => `Year ${e.year}`),
            datasets: [{
                label: `Expiring Area (${areaUnit === 'unit' ? (propertyType === 'marina' ? 'Slips' : 'Units') : 'SF'})`,
                data: expirations.map(e => parseFloat(e.expiring_area)),
                backgroundColor: chartToken('--chart-3'),
                borderRadius: 3,
                maxBarThickness: 48,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: v => fmt.num(v) + (areaUnit === 'unit' ? (propertyType === 'marina' ? ' Slips' : ' Units') : ' SF'),
                        color: chartToken('--chart-text'),
                    },
                    grid: { color: chartToken('--chart-grid') },
                    border: { display: false },
                },
                x: { grid: { display: false }, ticks: { color: chartToken('--chart-text') } }
            },
            plugins: {
                legend: { labels: { color: chartToken('--chart-text') } },
                tooltip: {
                    callbacks: {
                        label: ctx => {
                            const e = expirations[ctx.dataIndex];
                            return [
                                `Area: ${fmt.sf(e.expiring_area, areaUnit, propertyType)}`,
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
// ─── Portfolio Cash Flows ─────────────────────────────────────

async function portfolioView() {
    setBreadcrumb([
        { label: 'Properties', href: '#/dashboard' },
        { label: 'Portfolio Cash Flows' }
    ]);

    // Load all properties
    let properties;
    try {
        properties = await api.get('/properties');
    } catch (err) {
        $app().innerHTML = `<div class="empty-state"><h3>Cannot load properties</h3><p>${escapeHtmlAttr(err.message)}</p></div>`;
        return;
    }

    if (!properties || properties.length === 0) {
        $app().innerHTML = `
            <div class="empty-state">
                <h3>No properties found</h3>
                <p>Create properties and run valuations first.</p>
                <br><a href="#/dashboard" class="btn btn-secondary">Back to Properties</a>
            </div>`;
        return;
    }

    // Load latest completed valuation + full report for each property in parallel
    const propData = await Promise.all(properties.map(async (p) => {
        try {
            const valuations = await api.get(`/properties/${p.id}/valuations`);
            const completed = valuations.filter(v => v.status === 'completed');
            if (completed.length === 0) return { property: p, report: null, valuation: null };
            // Use the most recently updated completed valuation
            completed.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
            const val = completed[0];
            const report = await api.get(`/valuations/${val.id}/reports/full?include_recovery_audit=false`).catch(() => null);
            return { property: p, report, valuation: val };
        } catch {
            return { property: p, report: null, valuation: null };
        }
    }));

    // Filter to only properties with completed reports
    const withReports = propData.filter(d => d.report && d.report.annual_cash_flows && d.report.annual_cash_flows.length > 0);

    // Unique property types for filter
    const allTypes = [...new Set(properties.map(p => p.property_type))].sort();

    // Render controls
    $app().innerHTML = `
        <div class="page-header">
            <h1 class="page-title">Portfolio Cash Flows</h1>
            <p class="page-subtitle">${properties.length} properties, ${withReports.length} with completed valuations</p>
        </div>

        <div style="display:flex;gap:16px;align-items:center;margin-bottom:24px;flex-wrap:wrap">
            <div style="display:flex;align-items:center;gap:8px">
                <label class="form-label" style="margin:0;white-space:nowrap">Property Type</label>
                <select class="form-input" id="portfolioTypeFilter" style="width:auto;min-width:160px">
                    <option value="all">All Types</option>
                    ${allTypes.map(t => `<option value="${t}">${fmt.typeLabel(t)}</option>`).join('')}
                </select>
            </div>
            <div style="display:flex;align-items:center;gap:8px">
                <label class="form-label" style="margin:0;white-space:nowrap">
                    <input type="checkbox" id="portfolioProRata" style="margin-right:6px">
                    Apply ownership share (pro rata)
                </label>
            </div>
        </div>

        <div id="portfolioContent"></div>
    `;

    function renderPortfolio() {
        const typeFilter = document.getElementById('portfolioTypeFilter').value;
        const proRata = document.getElementById('portfolioProRata').checked;

        const filtered = withReports.filter(d =>
            typeFilter === 'all' || d.property.property_type === typeFilter
        );

        if (filtered.length === 0) {
            document.getElementById('portfolioContent').innerHTML = `
                <div class="empty-state" style="padding:40px 0">
                    <h3>No completed valuations</h3>
                    <p>No properties match this filter with completed valuations.</p>
                </div>`;
            return;
        }

        // Determine max year count across all filtered properties
        const maxYears = Math.max(...filtered.map(d => d.report.annual_cash_flows.length));

        // Aggregation fields — full waterfall
        const fields = [
            { key: 'gross_potential_rent', label: 'Scheduled Base Rent' },
            { key: 'absorption_vacancy', label: 'Turnover Vacancy' },
            { key: 'loss_to_lease', label: 'Loss to Lease' },
            { key: 'free_rent', label: 'Free Rent' },
            { key: 'expense_recoveries', label: 'Expense Recoveries' },
            { key: 'percentage_rent', label: 'Percentage Rent' },
            { key: 'other_income', label: 'Other Income' },
            { key: 'gross_potential_income', label: 'Gross Potential Income', cls: 'subtotal' },
            { key: 'general_vacancy_loss', label: 'General Vacancy' },
            { key: 'credit_loss', label: 'Credit Loss' },
            { key: 'effective_gross_income', label: 'Effective Gross Income', cls: 'subtotal' },
            { key: 'operating_expenses', label: 'Operating Expenses' },
            { key: 'net_operating_income', label: 'Net Operating Income', cls: 'total' },
            { key: 'tenant_improvements', label: 'Tenant Improvements' },
            { key: 'leasing_commissions', label: 'Leasing Commissions' },
            { key: 'capital_reserves', label: 'Capital Reserves' },
            { key: 'building_improvements', label: 'Building Improvements' },
            { key: 'cash_flow_before_debt', label: 'Cash Flow Before Debt', cls: 'total' },
            { key: 'debt_service', label: 'Debt Service' },
            { key: 'levered_cash_flow', label: 'Levered Cash Flow', cls: 'total' },
        ];

        // Aggregate: sum each field across properties for each year
        const aggregated = Array.from({ length: maxYears }, (_, yi) => {
            const yearData = {};
            fields.forEach(f => { yearData[f.key] = 0; });
            yearData.year = yi + 1;
            filtered.forEach(d => {
                const cf = d.report.annual_cash_flows[yi];
                if (!cf) return;
                const share = proRata ? parseFloat(d.property.ownership_pct || 1) : 1;
                fields.forEach(f => {
                    yearData[f.key] += parseFloat(cf[f.key] || 0) * share;
                });
            });
            return yearData;
        });

        // Filter out line items that are zero across all years (unless subtotal/total)
        const alwaysShow = new Set(['gross_potential_income', 'effective_gross_income', 'net_operating_income', 'cash_flow_before_debt']);
        const displayFields = fields.filter(f =>
            alwaysShow.has(f.key) || aggregated.some(y => Math.abs(y[f.key]) > 0.01)
        );

        // Year headers
        const yearHeaders = aggregated.map(y => `<th class="right">Yr ${y.year}</th>`).join('');

        // Build expandable rows with per-property sub-rows
        const tableRows = displayFields.map(f => {
            const groupId = 'pcf_' + f.key;
            const cls = f.cls || '';

            // Totals row (expandable)
            const cells = aggregated.map(y => {
                const v = y[f.key];
                const neg = v < 0 ? 'negative' : '';
                return `<td class="${neg}">${fmt.currencyExact(v)}</td>`;
            }).join('');
            let html = `<tr class="${cls} expandable" data-toggle="${groupId}">
                <td><span class="expand-chevron">&#9654;</span>${f.label}</td>${cells}
            </tr>`;

            // Sub-rows per property
            filtered.forEach(d => {
                const share = proRata ? parseFloat(d.property.ownership_pct || 1) : 1;
                const ownershipTag = proRata && share < 1 ? ` <span style="font-size:0.67rem;opacity:0.6">${(share * 100).toFixed(0)}%</span>` : '';
                const subCells = aggregated.map((_, yi) => {
                    const cf = d.report.annual_cash_flows[yi];
                    const v = cf ? parseFloat(cf[f.key] || 0) * share : 0;
                    const neg = v < 0 ? 'negative' : '';
                    return `<td class="${neg}">${fmt.currencyExact(v)}</td>`;
                }).join('');
                html += `<tr class="sub-row" data-group="${groupId}">
                    <td>${escapeHtmlAttr(d.property.name)}${ownershipTag}</td>${subCells}
                </tr>`;
            });

            return html;
        }).join('');

        // Property breakdown table
        const breakdownRows = filtered.map(d => {
            const share = proRata ? parseFloat(d.property.ownership_pct || 1) : 1;
            const ownershipLabel = proRata && share < 1 ? ` (${(share * 100).toFixed(1)}%)` : '';
            const val = d.valuation;
            const noi = d.report.annual_cash_flows[0] ? parseFloat(d.report.annual_cash_flows[0].net_operating_income) * share : 0;
            const cfbd = d.report.annual_cash_flows[0] ? parseFloat(d.report.annual_cash_flows[0].cash_flow_before_debt) * share : 0;
            const npv = val.result_npv ? parseFloat(val.result_npv) * share : 0;
            return `<tr>
                <td class="tenant-name"><a href="#/property/${d.property.id}" style="color:var(--accent);text-decoration:none">${escapeHtmlAttr(d.property.name)}</a>${ownershipLabel}</td>
                <td>${fmt.typeLabel(d.property.property_type)}</td>
                <td class="mono right">${fmt.num(d.property.total_area)}</td>
                <td class="mono right">${fmt.currencyExact(noi)}</td>
                <td class="mono right">${fmt.currencyExact(cfbd)}</td>
                <td class="mono right">${fmt.currencyExact(npv)}</td>
                <td class="mono right">${val.purchase_price && val.result_irr ? fmt.pct(val.result_irr) : '—'}</td>
                <td class="mono right">${val.exit_cap_rate ? fmt.pct(val.exit_cap_rate) : '—'}</td>
            </tr>`;
        }).join('');

        // Portfolio totals
        const totalNOI = filtered.reduce((s, d) => {
            const share = proRata ? parseFloat(d.property.ownership_pct || 1) : 1;
            return s + (d.report.annual_cash_flows[0] ? parseFloat(d.report.annual_cash_flows[0].net_operating_income) * share : 0);
        }, 0);
        const totalCFBD = filtered.reduce((s, d) => {
            const share = proRata ? parseFloat(d.property.ownership_pct || 1) : 1;
            return s + (d.report.annual_cash_flows[0] ? parseFloat(d.report.annual_cash_flows[0].cash_flow_before_debt) * share : 0);
        }, 0);
        const totalNPV = filtered.reduce((s, d) => {
            const share = proRata ? parseFloat(d.property.ownership_pct || 1) : 1;
            return s + (d.valuation.result_npv ? parseFloat(d.valuation.result_npv) * share : 0);
        }, 0);

        // NOI chart data
        const noiData = aggregated.map(y => y.net_operating_income);
        const cfbdData = aggregated.map(y => y.cash_flow_before_debt);

        document.getElementById('portfolioContent').innerHTML = `
            <div class="kpi-row" style="margin-bottom:24px">
                <div class="kpi-card">
                    <div class="kpi-label">Properties</div>
                    <div class="kpi-value">${filtered.length}</div>
                    <div class="kpi-subtext">${proRata ? 'Pro rata basis' : '100% basis'}</div>
                </div>
                <div class="kpi-card">
                    <div class="kpi-label">Year 1 NOI</div>
                    <div class="kpi-value">${fmt.currencyExact(totalNOI)}</div>
                </div>
                <div class="kpi-card">
                    <div class="kpi-label">Year 1 CFBD</div>
                    <div class="kpi-value">${fmt.currencyExact(totalCFBD)}</div>
                </div>
                <div class="kpi-card">
                    <div class="kpi-label">Total NPV</div>
                    <div class="kpi-value">${fmt.currencyExact(totalNPV)}</div>
                </div>
            </div>

            <h3 class="section-title" style="margin-bottom:12px">Property Summary</h3>
            <div class="data-table-wrap" style="margin-bottom:32px">
                <table class="data-table">
                    <thead><tr>
                        <th>Property</th>
                        <th>Type</th>
                        <th class="right">Area</th>
                        <th class="right">Yr 1 NOI</th>
                        <th class="right">Yr 1 CFBD</th>
                        <th class="right">NPV</th>
                        <th class="right">IRR</th>
                        <th class="right">Exit Cap</th>
                    </tr></thead>
                    <tbody>${breakdownRows}</tbody>
                    <tfoot><tr>
                        <td><strong>Portfolio Total</strong></td>
                        <td></td>
                        <td></td>
                        <td class="mono right"><strong>${fmt.currencyExact(totalNOI)}</strong></td>
                        <td class="mono right"><strong>${fmt.currencyExact(totalCFBD)}</strong></td>
                        <td class="mono right"><strong>${fmt.currencyExact(totalNPV)}</strong></td>
                        <td></td>
                        <td></td>
                    </tr></tfoot>
                </table>
            </div>

            <h3 class="section-title" style="margin-bottom:12px">Portfolio NOI & Cash Flow</h3>
            <div style="max-width:800px;margin-bottom:32px">
                <canvas id="portfolioChart" height="280"></canvas>
            </div>

            <h3 class="section-title" style="margin-bottom:12px">Aggregated Cash Flows</h3>
            <div class="cf-table-wrap">
                <table class="cf-table" id="portfolioCfTable">
                    <thead><tr><th></th>${yearHeaders}</tr></thead>
                    <tbody>${tableRows}</tbody>
                </table>
            </div>
        `;

        // Render chart
        const ctx = document.getElementById('portfolioChart');
        if (ctx) {
            new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: aggregated.map(y => 'Yr ' + y.year),
                    datasets: [
                        {
                            label: 'NOI',
                            data: noiData,
                            backgroundColor: 'rgba(0, 113, 227, 0.7)',
                            borderRadius: 4,
                        },
                        {
                            label: 'Cash Flow Before Debt',
                            data: cfbdData,
                            backgroundColor: 'rgba(52, 199, 89, 0.7)',
                            borderRadius: 4,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { position: 'top' },
                        tooltip: {
                            callbacks: {
                                label: ctx => ctx.dataset.label + ': ' + fmt.currencyExact(ctx.parsed.y),
                            }
                        },
                    },
                    scales: {
                        y: {
                            ticks: { callback: v => fmt.currencyExact(v) },
                        },
                    },
                },
            });
        }

        // Wire expand/collapse on cash flow rows
        document.querySelectorAll('#portfolioCfTable tr.expandable').forEach(row => {
            row.querySelector('td').addEventListener('click', () => {
                const groupId = row.dataset.toggle;
                const isExpanded = row.classList.toggle('expanded');
                document.querySelectorAll(`#portfolioCfTable tr.sub-row[data-group="${groupId}"]`).forEach(sub => {
                    sub.classList.toggle('visible', isExpanded);
                });
            });
        });
    }

    // Wire up filter controls
    document.getElementById('portfolioTypeFilter').addEventListener('change', renderPortfolio);
    document.getElementById('portfolioProRata').addEventListener('change', renderPortfolio);

    // Initial render
    renderPortfolio();
}


// REGISTER ROUTES & INIT
// ═══════════════════════════════════════════════════════════════

addRoute('/dashboard', dashboardView);
addRoute('/portfolio', portfolioView);
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
