/* OpenDCF document import: upload documents, check what was read, create the valuation. */

const intakeState = new Map();
// Model builds in progress, by valuation id. A build keeps running if the import screen is closed.
const intakeBuilds = new Map();

const INTAKE_ACCEPT = '.pdf,.xlsx,.xlsm,.csv,.txt,.png,.jpg,.jpeg,.gif,.webp';
const INTAKE_AUTO_APPROVE = 0.95;

const INTAKE_DOC_TYPES = {
    lease: 'Lease', lease_amendment: 'Lease amendment', rent_roll: 'Rent roll',
    operating_statement: 'Operating statement', budget: 'Budget', appraisal: 'Appraisal',
    property_tax: 'Property tax bill', insurance: 'Insurance', title: 'Title', environmental: 'Environmental',
    survey: 'Survey', capital_plan: 'Capital plan', offering_memorandum: 'Offering memorandum',
    sale_comparable: 'Sale comparable', other: 'Other',
};

// Order matters: the first matching pattern wins.
const INTAKE_TOPICS = [
    ['Tenants & leases', /^(leases?|lease_amendment|rent_roll|tenants?|suites?|rollover|rent_steps|free_rent)/],
    ['Income & expenses', /^(expenses?|operating|income|other_income|budget|revenue|noi|recover|property_tax|insurance|capital)/],
    ['Valuation assumptions', /^(dcf|valuation|market|cap_rate|sales?_comp|reconciliation|discount|exit)/],
    ['Property', /^(property|appraisal|site|building)/],
];

function intakeValue(value) {
    if (value == null) return '—';
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
}

function intakeLabel(path) {
    return path.split('.').map(part => {
        const text = part.replace('[]', '').replaceAll('_', ' ').trim();
        return text.charAt(0).toUpperCase() + text.slice(1);
    }).join(' › ');
}

function intakeTopic(path) {
    const key = path.toLowerCase();
    return (INTAKE_TOPICS.find(([, pattern]) => pattern.test(key)) || ['Other'])[0];
}

function intakeFileSummary(pkg) {
    const model = (pkg.valuation || {}).model || {};
    return [
        ['Property', pkg.property?.name || 'Unnamed'],
        ['Schema', pkg.schema_version || 'Unknown'],
        ['Suites', (model.suites || []).length],
        ['Tenants', (model.tenants || []).length],
        ['Leases', (model.leases || []).length],
        ['Expenses', (model.expenses || []).length],
        ['Evidence files', ((pkg.evidence || {}).documents || []).length],
    ];
}

function showPackageImport() {
    const input = document.createElement('input');
    input.type = 'file'; input.accept = '.zip,.odcf.zip,.json,.odcf.json,application/json,application/zip';
    input.onchange = async () => {
        const file = input.files[0]; if (!file) return;
        try {
            // A .odcf.zip deal package is read by the server; a .odcf.json is checked here first
            const isZip = /\.zip$/i.test(file.name);
            const pkg = isZip ? null : JSON.parse(await file.text());
            if (pkg && pkg.format !== 'OpenDCF Valuation Package') throw new Error('This is not an OpenDCF valuation package.');
            const summary = pkg ? intakeFileSummary(pkg) : [
                ['File', file.name], ['Size', `${(file.size / 1048576).toFixed(1)} MB`],
                ['Contents', 'Model, documents and evidence'],
            ];
            const overlay = document.createElement('div'); overlay.className = 'modal-overlay';
            overlay.innerHTML = `<div class="modal intake-import-modal"><div class="modal-title">Import valuation package</div>
                <p class="form-help">The package will create a separate property and valuation. Existing data will not be overwritten.</p>
                <div class="intake-summary-grid">${summary.map(([k,v]) => `<div><span>${escapeHtmlAttr(k)}</span><strong>${escapeHtmlAttr(String(v))}</strong></div>`).join('')}</div>
                <div class="modal-actions"><button class="btn btn-secondary" data-cancel>Cancel</button><button class="btn btn-primary" data-import>Import as new valuation</button></div></div>`;
            document.body.appendChild(overlay);
            overlay.querySelector('[data-cancel]').onclick = () => overlay.remove();
            overlay.querySelector('[data-import]').onclick = async e => {
                e.target.disabled = true; e.target.textContent = 'Importing…';
                try {
                    let result;
                    if (pkg) result = await api.post('/valuation-packages/import', pkg);
                    else {
                        const form = new FormData(); form.append('file', file);
                        const response = await fetch(`${API}/valuation-packages/import`, { method: 'POST', body: form });
                        if (!response.ok) throw new Error(`Import → ${response.status}: ${await response.text()}`);
                        result = await response.json();
                    }
                    overlay.remove(); toast('Valuation package imported', 'success');
                    location.hash = `#/valuation/${result.valuation_id}`;
                } catch (err) { toast(apiErrorDetail(err), 'error'); e.target.disabled = false; e.target.textContent = 'Import as new valuation'; }
            };
        } catch (err) { toast(`Package validation failed: ${apiErrorDetail(err)}`, 'error'); }
    };
    input.click();
}

// Columns shown for each staged collection in "Edit details": [label, row => display value].
function reconstructionColumns(name, plan) {
    const byId = (rows, id, key) => (rows || []).find(r => r.source_id === id)?.[key] ?? id;
    const suite = id => byId(plan.suites, id, 'suite_name');
    const tenant = id => byId(plan.tenants, id, 'name');
    const lease = id => tenant(byId(plan.leases, id, 'source_tenant_id'));
    const col = (label, key) => [label, r => r[key]];
    return ({
        suites: [col('Suite', 'suite_name'), col('Space type', 'space_type'), col('Area', 'area')],
        tenants: [col('Name', 'name'), col('Credit rating', 'credit_rating'), col('Industry', 'industry')],
        leases: [['Tenant', r => tenant(r.source_tenant_id)], ['Suite', r => suite(r.source_suite_id)], col('Start', 'lease_start_date'), col('End', 'lease_end_date'), col('Rent / SF', 'base_rent_per_unit'), col('Escalation', 'escalation_type'), col('Recovery', 'recovery_type'), col('Pro-rata', 'pro_rata_share_pct'), col('Base year', 'base_year'), col('At expiry', 'upon_expiration')],
        market_leasing_profiles: [col('Space type', 'space_type'), col('Market rent', 'market_rent_per_unit'), col('Renewal %', 'renewal_probability'), col('Downtime (mo)', 'downtime_months')],
        expenses: [col('Category', 'category'), col('Amount', 'base_year_amount'), col('Growth', 'growth_rate_pct'), col('Recoverable', 'is_recoverable')],
        other_income: [col('Category', 'category'), col('Amount', 'base_year_amount'), col('Growth', 'growth_rate_pct')],
        capital_projects: [col('Description', 'description'), col('Amount', 'total_amount'), col('Start', 'start_date'), col('Months', 'duration_months')],
        rent_steps: [['Lease', r => lease(r.source_lease_id)], col('Effective', 'effective_date'), col('Rent / SF', 'rent_per_unit')],
        free_rent_periods: [['Lease', r => lease(r.source_lease_id)], col('Start', 'start_date'), col('End', 'end_date')],
        lease_expense_recoveries: [['Lease', r => lease(r.source_lease_id)], col('Expense', 'expense_category'), col('Recovery', 'recovery_type'), col('Stop $', 'base_year_stop_amount'), col('Cap / SF', 'cap_per_sf_annual'), col('Cap growth', 'cap_growth_pct'), col('Admin fee', 'admin_fee_pct'), col('Cap group', 'cap_group'), col('MG stop / SF', 'expense_stop_per_sf')],
        recovery_structures: [col('Name', 'name'), col('Default recovery', 'default_recovery_type')],
        recovery_structure_items: [['Setup', r => byId(plan.recovery_structures, r.source_recovery_structure_id, 'name')], col('Expense', 'expense_category'), col('Recovery', 'recovery_type'), col('Cap / SF', 'cap_per_sf_annual'), col('Cap growth', 'cap_growth_pct'), col('Admin fee', 'admin_fee_pct')],
    })[name] || [];
}

// Readable form of an extracted value, chosen from its field name: $, %, SF and dates.
function intakeDisplay(path, value) {
    if (value == null || value === '') return '';
    if (typeof value === 'object') {
        return Array.isArray(value)
            ? value.map(v => intakeDisplay(path, v)).join(', ')
            : Object.entries(value).map(([k, v]) => `${k.replaceAll('_', ' ')}: ${intakeDisplay(`${path}.${k}`, v)}`).join(' · ');
    }
    const text = String(value);
    if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
        const d = new Date(`${text}T00:00:00`);
        return isNaN(d) ? text : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    }
    const n = typeof value === 'number' ? value : Number(text.replace(/[$,\s]/g, ''));
    if (typeof value === 'boolean' || text.trim() === '' || !Number.isFinite(n)) return text;
    const field = path.toLowerCase().split('.').pop().replace('[]', '');
    const words = new Set(field.split('_'));
    const has = list => list.some(w => words.has(w));
    const money = digits => `$${n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
    if (has(['rate', 'pct', 'percent', 'cap', 'yield', 'growth', 'probability', 'vacancy', 'occupancy'])) {
        return Math.abs(n) <= 1 ? `${+(n * 100).toFixed(2)}%` : `${n}%`;
    }
    if (/per_sf|psf|per_unit|per_square/.test(field)) return `${money(2)}/SF`;
    if (has(['area', 'sf', 'rsf', 'nra', 'gla', 'footage', 'size'])) return `${n.toLocaleString('en-US')} SF`;
    if (has(['year', 'years', 'month', 'months', 'term', 'count', 'number', 'units', 'floor', 'suite'])) return String(n);
    if (has(['rent', 'amount', 'tax', 'taxes', 'insurance', 'expense', 'expenses', 'income', 'price', 'value', 'noi',
        'revenue', 'cost', 'costs', 'fee', 'fees', 'budget', 'total', 'utilities', 'repairs', 'management', 'payroll',
        'parking', 'reserves'])) return money(0);
    return n.toLocaleString('en-US');
}

function intakeRaw(value) {
    return value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value);
}

// Inputs show the readable value and switch to the raw value while being edited.
function intakeValueInput(f, cls, disabled) {
    const display = escapeHtmlAttr(intakeDisplay(f.field_path, f.value));
    return `<input class="${cls}" data-value="${f.id}" data-raw="${escapeHtmlAttr(intakeRaw(f.value))}" data-display="${display}" value="${display}" ${disabled ? 'disabled' : ''}>`;
}

function coerceIntakeInput(raw, original) {
    if (typeof original === 'boolean') return raw === 'true';
    if (typeof original === 'number') {
        if (raw.trim() === '') return null;
        const n = Number(raw.replace(/[$,\s]/g, ''));
        if (!Number.isFinite(n)) throw new Error('Enter a number.');
        return n;
    }
    if (original != null && typeof original === 'object') {
        try { return JSON.parse(raw); } catch { throw new Error('Enter valid JSON.'); }
    }
    return raw === '' && original == null ? null : raw;
}

function objectEditor(title, object, onSave) {
    const overlay = document.createElement('div'); overlay.className = 'modal-overlay';
    const fields = Object.entries(object).filter(([key]) => !['id','created_at','updated_at'].includes(key));
    overlay.innerHTML = `<div class="modal wide intake-object-modal"><div class="modal-title">${escapeHtmlAttr(title)}</div><div class="intake-object-grid">
        ${fields.map(([key,value]) => `<label><span>${escapeHtmlAttr(key.replaceAll('_',' '))}</span>${typeof value === 'boolean' ? `<select data-key="${escapeHtmlAttr(key)}"><option value="true" ${value ? 'selected':''}>Yes</option><option value="false" ${!value ? 'selected':''}>No</option></select>` : `<textarea data-key="${escapeHtmlAttr(key)}" rows="${value && typeof value === 'object' ? 3 : 1}">${escapeHtmlAttr(value == null ? '' : (typeof value === 'object' ? JSON.stringify(value) : String(value)))}</textarea>`}</label>`).join('')}
        </div><div class="modal-actions"><button class="btn btn-secondary" data-cancel>Cancel</button><button class="btn btn-primary" data-save>Save</button></div></div>`;
    document.body.appendChild(overlay);
    overlay.querySelector('[data-cancel]').onclick = () => overlay.remove();
    overlay.querySelector('[data-save]').onclick = () => {
        try {
            const updated = {...object};
            fields.forEach(([key, original]) => { updated[key] = coerceIntakeInput(overlay.querySelector(`[data-key="${CSS.escape(key)}"]`).value, original); });
            onSave(updated); overlay.remove();
        } catch (err) { toast(apiErrorDetail(err), 'error'); }
    };
}

// Full-screen table editor for the staged rows. Edits change `plan` in place; Done hands control back.
function showSetupDetails(plan, onDone) {
    const overlay = document.createElement('div'); overlay.className = 'intake-workbench-overlay';
    overlay.innerHTML = `<div class="intake-workbench"><header><div><h2>Edit details</h2><p>Correct tenants, leases, expenses and other rows before creating the valuation.</p></div><button class="btn btn-primary" data-close>Done</button></header><div data-body></div></div>`;
    document.body.appendChild(overlay);
    overlay.querySelector('[data-close]').onclick = () => { overlay.remove(); onDone(); };
    const collections = ['suites','tenants','leases','rent_steps','free_rent_periods','lease_expense_recoveries','recovery_structures','recovery_structure_items','market_leasing_profiles','expenses','other_income','capital_projects'];
    const title = name => { const t = name.replaceAll('_', ' '); return t.charAt(0).toUpperCase() + t.slice(1); };
    const render = () => {
        overlay.querySelector('[data-body]').innerHTML = collections.map(name => {
            const rows = plan[name] || [], cols = reconstructionColumns(name, plan);
            return `<section class="intake-collection"><div class="section-header"><h3>${escapeHtmlAttr(title(name))} <small>${rows.length}</small></h3><button class="btn btn-secondary btn-sm" data-add="${name}">Add</button></div>
                <div class="table-wrap"><table class="data-table"><thead><tr>${cols.map(([label]) => `<th>${escapeHtmlAttr(label)}</th>`).join('')}<th></th></tr></thead>
                <tbody>${rows.map((row, i) => `<tr data-edit-row="${name}:${i}">${cols.map(([, get]) => `<td>${escapeHtmlAttr(intakeValue(get(row)))}</td>`).join('')}<td class="right"><button class="intake-icon-btn" data-delete-row="${name}:${i}" title="Remove row" aria-label="Remove row">✕</button></td></tr>`).join('') || `<tr><td colspan="${cols.length + 1}" class="muted">None</td></tr>`}</tbody></table></div></section>`;
        }).join('');
        overlay.querySelectorAll('[data-add]').forEach(el => el.onclick = () => objectEditor(`Add ${title(el.dataset.add).toLowerCase()}`, {}, row => { (plan[el.dataset.add] ||= []).push(row); render(); }));
        overlay.querySelectorAll('[data-edit-row]').forEach(el => el.onclick = e => {
            if (e.target.closest('[data-delete-row]')) return;
            const [name, index] = el.dataset.editRow.split(':');
            objectEditor(`Edit ${title(name).toLowerCase()}`, plan[name][Number(index)], row => { plan[name][Number(index)] = row; render(); });
        });
        overlay.querySelectorAll('[data-delete-row]').forEach(el => el.onclick = () => { const [name, index] = el.dataset.deleteRow.split(':'); plan[name].splice(Number(index), 1); render(); });
    };
    render();
}

function showReconstructionComparison(result) {
    const overlay=document.createElement('div'); overlay.className='modal-overlay';
    const rows=Object.entries(result.metrics||{});
    overlay.innerHTML=`<div class="modal wide"><div class="modal-title">Source-to-valuation comparison</div><div class="table-wrap"><table class="data-table"><thead><tr><th>Metric</th><th class="num">Source appraisal</th><th class="num">Created valuation</th><th class="num">Variance</th></tr></thead><tbody>${rows.map(([key,v])=>`<tr><td>${escapeHtmlAttr(key.replaceAll('_',' '))}</td><td class="num">${escapeHtmlAttr(intakeValue(v.source))}</td><td class="num">${escapeHtmlAttr(intakeValue(v.rebuilt))}</td><td class="num">${escapeHtmlAttr(intakeValue(v.variance))}</td></tr>`).join('')}</tbody></table></div><div class="modal-actions"><button class="btn btn-secondary" data-close>Close</button></div></div>`;
    document.body.appendChild(overlay); overlay.querySelector('[data-close]').onclick=()=>overlay.remove();
}

const INTAKE_GUIDE = `<aside class="intake-guide">
    <h3>What to upload</h3>
    <dl>
        <dt>Rent roll or leases</dt><dd>Tenants, suites, rents and dates. Signed leases and amendments win over the rent roll.</dd>
        <dt>Operating statement (T-12) or budget</dt><dd>Operating expenses and other income.</dd>
        <dt>Appraisal or offering memorandum</dt><dd>Discount rate, exit cap rate and market rents. Without one you set these yourself in step 3.</dd>
    </dl>
    <p>Any one of these is enough to start; each extra document fills more of the model.</p>
</aside>`;

// Opens the import workspace. isImport: the valuation is the hidden workspace behind
// "Import from documents"; otherwise documents are attached to an existing valuation.
function wireEvidenceWorkspace(valuationId, { isImport = false } = {}) {
    const button = document.getElementById('valEvidenceBtn');
    const open = async () => {
        document.getElementById('valuationIntake')?.remove();
        const workspace = document.createElement('div'); workspace.id = 'valuationIntake'; workspace.className = 'intake-overlay';
        workspace.innerHTML = `<div class="intake-shell">
            <header class="intake-header"><div><h1>${isImport ? 'Import from documents' : 'Build a valuation from documents'}</h1>
                <p>${isImport ? 'Upload documents, check what was read, then create the valuation.' : 'Creates a new valuation from these documents. This valuation is not changed.'}</p></div>
                <button class="btn btn-secondary" data-close>Close</button></header>
            <nav class="intake-steps" data-steps></nav>
            <div data-configuration></div>
            <div class="intake-body" data-body></div>
        </div>`;
        document.body.appendChild(workspace);
        const state = { docs: [], review: null, reconstructions: [], configuration: null, step: null, busy: '', plan: null, planId: null };
        intakeState.set(valuationId, state);
        const body = workspace.querySelector('[data-body]');
        workspace.dataset.valuationId = valuationId;
        // The build may finish after this screen was closed and reopened; the open screen refreshes itself.
        workspace.addEventListener('intake-built', e => { if (e.detail.ok) state.step = 'create'; load(); });
        workspace.querySelector('[data-close]').onclick = async () => {
            workspace.remove();
            if (intakeBuilds.has(valuationId)) toast('The model is still building. Carry on working; you will be told when it is ready.', 'info');
            if (!isImport) return;
            // An import with no documents has nothing to resume
            if (!state.docs.length) await api.del(`/appraisal-import-workspaces/${valuationId}`).catch(() => {});
            // Drop ?intake=1 without reloading, so a model build in progress keeps running
            history.replaceState(null, '', `${location.pathname}#/dashboard`);
            window.dispatchEvent(new HashChangeEvent('hashchange'));
        };

        const facts = () => state.review?.facts || [];
        const issues = () => state.review?.issues || [];
        const docName = id => state.docs.find(d => d.id === id)?.original_filename || 'Document';
        const processed = () => state.docs.filter(d => d.status === 'processed');
        const created = () => state.reconstructions.find(r => r.status === 'materialized');
        const staged = () => state.reconstructions.find(r => r.status === 'staged');
        const sourceUrl = (docId, page) => `${API}/valuations/${valuationId}/documents/${docId}/content${page ? `#page=${page}` : ''}`;

        async function load() {
            const [docs, reconstructions, review, configuration] = await Promise.all([
                api.get(`/valuations/${valuationId}/documents`),
                api.get(`/valuations/${valuationId}/appraisal-reconstructions`),
                api.get(`/valuations/${valuationId}/document-review`),
                api.get('/document-intelligence/status'),
            ]);
            Object.assign(state, { docs, reconstructions, review, configuration });
            if (!state.step) state.step = created() || staged() ? 'create' : processed().length ? 'check' : 'upload';
            render();
        }

        // ---- Step 1: upload and read ----
        async function processPending() {
            const pending = state.docs.filter(d => d.status !== 'processed' && d.status !== 'failed');
            for (const doc of pending) await processDoc(doc);
        }
        async function processDoc(doc) {
            if (!state.configuration?.configured) return;
            state.busy = doc.id; render();
            try { await api.post(`/valuations/${valuationId}/documents/${doc.id}/process`); }
            catch (err) { toast(`${doc.original_filename}: ${apiErrorDetail(err)}`, 'error'); }
            state.busy = '';
            await load();
        }
        async function upload(fileList) {
            const allowed = INTAKE_ACCEPT.split(',');
            const files = [...fileList].filter(f => allowed.some(ext => f.name.toLowerCase().endsWith(ext)));
            const skipped = fileList.length - files.length;
            if (skipped) toast(`${skipped} file${skipped > 1 ? 's' : ''} skipped. Word files are not supported yet; save them as PDF.`, 'error');
            if (!files.length) return;
            const form = new FormData(); files.forEach(f => form.append('files', f));
            state.busy = 'upload'; render();
            try {
                const response = await fetch(`${API}/valuations/${valuationId}/documents`, { method: 'POST', body: form });
                if (!response.ok) throw new Error(`POST → ${response.status}: ${await response.text()}`);
            } catch (err) { toast(apiErrorDetail(err), 'error'); }
            state.busy = '';
            await load();
            await processPending();
        }
        function docStatus(d) {
            if (state.busy === d.id) return `<span class="intake-doc-state"><span class="intake-spinner"></span> Reading…</span>`;
            if (d.status === 'failed') return `<span class="intake-doc-state error" title="${escapeHtmlAttr(d.error_message || '')}">Couldn't read this file</span><button class="btn btn-secondary btn-sm" data-retry="${d.id}">Try again</button>`;
            if (d.status !== 'processed') return `<span class="intake-doc-state">${state.configuration?.configured ? 'Waiting' : 'Waiting for set-up'}</span>`;
            if (d.relevant === false) return `<span class="intake-doc-state muted">Not used</span>`;
            const count = facts().filter(f => f.document_id === d.id).length;
            return `<span class="intake-doc-state ok">✓ ${count} item${count === 1 ? '' : 's'} found</span>`;
        }
        function docTypePicker(d) {
            if (d.status !== 'processed') return '<span></span>';
            const current = d.relevant === false ? 'unused' : d.document_type || 'other';
            return `<select class="intake-doc-type" data-doc-type="${d.id}" title="Detected document type. Change it if it's wrong.">
                ${Object.entries(INTAKE_DOC_TYPES).map(([v, label]) => `<option value="${v}" ${v === current ? 'selected' : ''}>${label}</option>`).join('')}
                <option value="unused" ${current === 'unused' ? 'selected' : ''}>Don't use this file</option></select>`;
        }
        function renderUpload() {
            const reading = state.busy !== '';
            const ready = processed().length > 0;
            const notes = issues();
            body.innerHTML = `<div class="intake-upload">
                    <label class="intake-drop"><input type="file" multiple accept="${INTAKE_ACCEPT}" data-files>
                        <strong>${state.busy === 'upload' ? 'Uploading…' : 'Drop files here or click to choose'}</strong>
                        <span>PDF, Excel, CSV, text or images. Files are read automatically.</span></label>
                    ${INTAKE_GUIDE}
                </div>
                ${state.docs.length ? `<section class="intake-section"><h3>Your documents</h3>
                    ${state.docs.map(d => `<div class="intake-doc-row"><a href="${sourceUrl(d.id)}" target="_blank" rel="noopener">${escapeHtmlAttr(d.original_filename)}</a>
                        ${docTypePicker(d)}${docStatus(d)}
                        <button class="intake-icon-btn" data-remove-doc="${d.id}" title="Remove this file" aria-label="Remove this file" ${state.busy ? 'disabled' : ''}>✕</button></div>`).join('')}
                </section>` : ''}
                ${notes.length ? `<section class="intake-section"><h3>Gaps</h3>${notes.map(i => `<div class="intake-issue ${i.severity}">${escapeHtmlAttr(i.message)}</div>`).join('')}</section>` : ''}
                <footer class="intake-footer"><span>${reading ? 'Reading documents…' : ''}</span>
                    <button class="btn btn-primary" data-next ${!ready || reading ? 'disabled' : ''}>Continue</button></footer>`;
            const input = body.querySelector('[data-files]');
            const drop = body.querySelector('.intake-drop');
            input.onchange = () => upload(input.files);
            ['dragenter', 'dragover'].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.add('active'); }));
            ['dragleave', 'drop'].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.remove('active'); }));
            drop.addEventListener('drop', e => upload(e.dataTransfer.files));
            body.querySelectorAll('[data-retry]').forEach(el => el.onclick = () => processDoc(state.docs.find(d => d.id === el.dataset.retry)));
            body.querySelectorAll('[data-doc-type]').forEach(el => el.onchange = async () => {
                const change = el.value === 'unused' ? { relevant: false } : { document_type: el.value, relevant: true };
                try { await api.patch(`/valuations/${valuationId}/documents/${el.dataset.docType}`, change); await load(); }
                catch (err) { toast(apiErrorDetail(err), 'error'); }
            });
            body.querySelectorAll('[data-remove-doc]').forEach(el => el.onclick = async () => {
                try { await api.del(`/valuations/${valuationId}/documents/${el.dataset.removeDoc}`); await load(); }
                catch (err) { toast(apiErrorDetail(err), 'error'); }
            });
            body.querySelector('[data-next]').onclick = () => { state.step = 'check'; render(); };
        }

        // ---- Step 2: check what was read ----
        function factRow(f) {
            const low = f.confidence != null && f.confidence < INTAKE_AUTO_APPROVE;
            const where = `${docName(f.document_id)}${f.page_number ? ` · page ${f.page_number}` : ''}`;
            const action = f.status === 'rejected'
                ? `<button class="btn btn-secondary btn-sm" data-restore="${f.id}">Use</button>`
                : `<button class="intake-icon-btn" data-exclude="${f.id}" title="Don't use this item" aria-label="Don't use this item">✕</button>`;
            return `<div class="intake-fact-row ${f.status === 'rejected' ? 'excluded' : ''}">
                <div class="intake-fact-label"><strong title="${escapeHtmlAttr(f.field_path)}">${escapeHtmlAttr(intakeLabel(f.field_path))}</strong>
                    <small><a href="${sourceUrl(f.document_id, f.page_number)}" target="_blank" rel="noopener">${escapeHtmlAttr(where)}</a>${low ? ` · <span class="intake-low">${Math.round(f.confidence * 100)}% sure</span>` : ''}</small>
                    ${low && f.source_quote ? `<q>${escapeHtmlAttr(f.source_quote)}</q>` : ''}</div>
                ${intakeValueInput(f, 'form-input', f.status === 'rejected')}
                ${action}</div>`;
        }
        function factGroups(list) {
            const order = [...INTAKE_TOPICS.map(([t]) => t), 'Other'];
            const groups = new Map(order.map(t => [t, []]));
            list.forEach(f => groups.get(intakeTopic(f.field_path)).push(f));
            return [...groups].filter(([, rows]) => rows.length)
                .map(([topic, rows]) => `<h4 class="intake-topic">${topic}</h4>${rows.map(factRow).join('')}`).join('');
        }
        const isLow = f => f.status === 'proposed' && (f.confidence == null || f.confidence < INTAKE_AUTO_APPROVE);
        // Lease facts tagged with a record key render as one table row per tenant.
        const isLeaseRow = f => !!f.record_key && /^leases?(\[\])?\./.test(f.field_path);
        function leaseTable(list) {
            const rows = new Map(), cols = [];
            list.forEach(f => {
                const key = `${f.document_id}|${f.record_key}`;
                const col = f.field_path.split('.').slice(1).join('.') || f.field_path;
                if (!rows.has(key)) rows.set(key, { doc: f.document_id, cells: {} });
                if (!cols.includes(col)) cols.push(col);
                rows.get(key).cells[col] = f;
            });
            const toCheck = list.filter(isLow).length;
            const rowsHtml = [...rows.values()].map(row => {
                const cells = Object.values(row.cells);
                const ids = cells.map(f => f.id).join(',');
                const out = cells.every(f => f.status === 'rejected');
                const page = cells.find(f => f.page_number)?.page_number;
                return `<tr class="${out ? 'excluded' : ''}"><td><a href="${sourceUrl(row.doc, page)}" target="_blank" rel="noopener">${escapeHtmlAttr(docName(row.doc))}${page ? ` · p.${page}` : ''}</a></td>
                    ${cols.map(col => {
                        const f = row.cells[col];
                        if (!f) return '<td></td>';
                        return `<td class="${f.status === 'rejected' ? 'intake-out-cell' : isLow(f) ? 'intake-low-cell' : ''}" title="${escapeHtmlAttr(f.status === 'rejected' ? 'Left out' : f.source_quote || '')}">${intakeValueInput(f, 'intake-cell', out || f.status === 'rejected')}</td>`;
                    }).join('')}
                    <td>${out ? `<button class="btn btn-secondary btn-sm" data-row-status="proposed" data-row="${ids}">Use</button>`
                        : `<button class="intake-icon-btn" data-row-status="rejected" data-row="${ids}" title="Leave this row out" aria-label="Leave this row out">✕</button>`}</td></tr>`;
            }).join('');
            return `<section class="intake-section"><h3>Rent roll <small>${rows.size} row${rows.size === 1 ? '' : 's'}${toCheck ? ` · ${toCheck} to check` : ''}</small></h3>
                <p class="muted">Highlighted cells were read with low confidence. Hover a cell for the source text.</p>
                <div class="table-wrap"><table class="data-table intake-lease-table"><thead><tr><th>Source</th>${cols.map(c => `<th>${escapeHtmlAttr(intakeLabel(c))}</th>`).join('')}<th></th></tr></thead><tbody>${rowsHtml}</tbody></table></div></section>`;
        }
        // Same item read from two or more documents with different values.
        const normValue = v => {
            const text = typeof v === 'object' ? JSON.stringify(v) : String(v ?? '');
            const number = Number(text.replace(/[$,%\s]/g, ''));
            return text.trim() !== '' && Number.isFinite(number) ? String(number) : text.trim().toLowerCase();
        };
        const normKey = k => String(k).toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
        function findConflicts(list) {
            const groups = new Map();
            list.forEach(f => {
                if (f.status === 'rejected') return;
                if (f.field_path.includes('[]') && !f.record_key) return; // rows can't be matched across files
                const key = f.record_key ? `${f.field_path}|${normKey(f.record_key)}` : f.field_path;
                if (!groups.has(key)) groups.set(key, []);
                groups.get(key).push(f);
            });
            return [...groups.values()].filter(g =>
                new Set(g.map(f => f.document_id)).size > 1 && new Set(g.map(f => normValue(f.value))).size > 1);
        }
        function conflictSection(conflicts) {
            return `<section class="intake-section intake-conflicts"><h3>Documents disagree <small>${conflicts.length}</small></h3>
                <p class="muted">Pick the right value. If you skip one, signed leases win over the rent roll, the operating statement over the budget, and the appraisal over the offering memorandum.</p>
                ${conflicts.map((group, n) => {
                    const options = new Map();
                    group.forEach(f => {
                        const key = normValue(f.value);
                        if (!options.has(key)) options.set(key, { value: f.value, facts: [] });
                        options.get(key).facts.push(f);
                    });
                    const first = group[0];
                    return `<div class="intake-conflict"><strong>${escapeHtmlAttr(intakeLabel(first.field_path))}${first.record_key ? ` <small>${escapeHtmlAttr(first.record_key)}</small>` : ''}</strong>
                        ${[...options.values()].map(o => `<label><input type="radio" name="conflict-${n}" data-pick="${o.facts.map(f => f.id).join(',')}" data-others="${group.filter(f => !o.facts.includes(f)).map(f => f.id).join(',')}">
                            <b>${escapeHtmlAttr(intakeDisplay(first.field_path, o.value))}</b>
                            <small>${o.facts.map(f => `${escapeHtmlAttr(INTAKE_DOC_TYPES[state.docs.find(d => d.id === f.document_id)?.document_type] || 'Document')}: ${escapeHtmlAttr(docName(f.document_id))}${f.page_number ? ` p.${f.page_number}` : ''}`).join(' · ')}</small></label>`).join('')}
                    </div>`;
                }).join('')}</section>`;
        }
        function startBuild() {
            const ids = facts().filter(f => f.status === 'proposed').map(f => f.id);
            const job = (async () => {
                if (ids.length) await api.post(`/valuations/${valuationId}/facts/bulk-review`, { status: 'accepted', fact_ids: ids });
                await api.post(`/valuations/${valuationId}/appraisal-reconstructions`, {});
            })();
            intakeBuilds.set(valuationId, job);
            render();
            job.then(() => true, err => { toast(apiErrorDetail(err), 'error'); return false; }).then(ok => {
                intakeBuilds.delete(valuationId);
                const open = document.querySelector(`#valuationIntake[data-valuation-id="${valuationId}"]`);
                if (open) { open.dispatchEvent(new CustomEvent('intake-built', { detail: { ok } })); return; }
                if (!ok) return;
                toast(isImport ? 'Model ready. Resume it from Unfinished imports on the Properties page.'
                    : 'Model ready. Open Tools, then New valuation from documents, to finish.', 'success');
                if (typeof renderUnfinishedImports === 'function') renderUnfinishedImports();
            });
        }
        function renderCheck() {
            const all = facts().filter(f => state.docs.find(d => d.id === f.document_id)?.relevant !== false);
            const leaseFacts = all.filter(isLeaseRow);
            const flat = all.filter(f => !isLeaseRow(f));
            const needsLook = flat.filter(isLow);
            const looksRight = flat.filter(f => f.status !== 'rejected' && !needsLook.includes(f));
            const excluded = flat.filter(f => f.status === 'rejected');
            const conflicts = findConflicts(all);
            const allClear = all.length && !needsLook.length && !leaseFacts.some(isLow) && !conflicts.length;
            body.innerHTML = `${all.length ? `<p class="intake-lead">${all.length} items were read from your documents. Correct any value by typing over it, or press ✕ to leave it out.
                    Everything not left out is used when you build the model.</p>`
                : '<p class="intake-lead">Nothing was read from your documents. Go back and press Try again on a document, or add another one.</p>'}
                ${allClear ? '<div class="intake-empty-ok">Everything was read with high confidence.</div>' : ''}
                ${conflicts.length ? conflictSection(conflicts) : ''}
                ${leaseFacts.length ? leaseTable(leaseFacts) : ''}
                ${needsLook.length ? `<section class="intake-section"><h3>Please check <small>${needsLook.length}</small></h3><p class="muted">Read with low confidence.</p>${factGroups(needsLook)}</section>` : ''}
                ${looksRight.length ? `<details class="intake-section" ${allClear && !leaseFacts.length ? 'open' : ''}><summary><h3>Read with high confidence <small>${looksRight.length}</small></h3></summary>${factGroups(looksRight)}</details>` : ''}
                ${excluded.length ? `<details class="intake-section"><summary><h3>Left out <small>${excluded.length}</small></h3></summary>${factGroups(excluded)}</details>` : ''}
                <footer class="intake-footer"><button class="btn btn-secondary" data-back>Back</button>
                    ${intakeBuilds.has(valuationId)
                        ? '<span class="intake-building"><span class="intake-spinner"></span> Building model, up to a minute. You can close this screen meanwhile.</span>'
                        : `${staged() ? '<small class="intake-footer-note">Builds a fresh model from your documents. It replaces the earlier one, including changes made in step 3.</small>' : ''}
                           <button class="btn btn-primary" data-build ${all.length ? '' : 'disabled'}>Build model</button>`}</footer>`;
            body.querySelectorAll('[data-value]').forEach(el => {
                el.addEventListener('focus', () => { el.value = el.dataset.raw; el.select(); });
                el.addEventListener('blur', () => { if (el.value === el.dataset.raw) el.value = el.dataset.display; });
                el.onchange = async () => {
                    const fact = facts().find(f => f.id === el.dataset.value);
                    try {
                        const value = coerceIntakeInput(el.value, fact.value);
                        await api.patch(`/valuations/${valuationId}/facts/${fact.id}`, { status: 'accepted', value });
                        Object.assign(fact, { status: 'accepted', value });
                        el.dataset.raw = intakeRaw(value);
                        el.dataset.display = intakeDisplay(fact.field_path, value);
                        el.value = el.dataset.display;
                    } catch (err) { toast(apiErrorDetail(err), 'error'); }
                };
            });
            const setStatus = async (id, status) => { await api.patch(`/valuations/${valuationId}/facts/${id}`, { status }); await load(); };
            body.querySelectorAll('[data-exclude]').forEach(el => el.onclick = () => setStatus(el.dataset.exclude, 'rejected'));
            body.querySelectorAll('[data-restore]').forEach(el => el.onclick = () => setStatus(el.dataset.restore, 'proposed'));
            body.querySelectorAll('[data-pick]').forEach(el => el.onchange = async () => {
                try {
                    await api.post(`/valuations/${valuationId}/facts/bulk-review`, { status: 'accepted', fact_ids: el.dataset.pick.split(',') });
                    await api.post(`/valuations/${valuationId}/facts/bulk-review`, { status: 'rejected', fact_ids: el.dataset.others.split(',') });
                    await load();
                } catch (err) { toast(apiErrorDetail(err), 'error'); }
            });
            body.querySelectorAll('[data-row]').forEach(el => el.onclick = async () => {
                await api.post(`/valuations/${valuationId}/facts/bulk-review`, { status: el.dataset.rowStatus, fact_ids: el.dataset.row.split(',') });
                await load();
            });
            body.querySelector('[data-back]').onclick = () => { state.step = 'upload'; render(); };
            body.querySelector('[data-build]')?.addEventListener('click', startBuild);
        }

        // ---- Step 3: confirm and create ----
        const SETUP_FIELDS = [
            ['property', 'name', 'Property name', 'text'],
            ['property', 'property_type', 'Property type', 'select'],
            ['property', 'total_area', 'Total area (SF)', 'number'],
            ['property', 'analysis_start_date', 'Analysis start', 'date'],
            ['property', 'analysis_period_months', 'Hold period (months)', 'number'],
            ['valuation', 'discount_rate', 'Discount rate (%)', 'pct'],
            ['valuation', 'exit_cap_rate', 'Exit cap rate (%)', 'pct'],
            ['valuation', 'purchase_price', 'Purchase price', 'number'],
        ];
        // Market leasing: what happens when each lease expires. Space types without a profile are never re-leased.
        const MARKET_FIELDS = [
            ['market_rent_per_unit', 'Market rent ($/SF/yr)', 'number'],
            ['rent_growth_rate_pct', 'Rent growth (%)', 'pct'],
            ['renewal_probability', 'Renewal chance (%)', 'pct'],
            ['downtime_months', 'Downtime (months)', 'number'],
        ];
        const pctShown = v => v == null || v === '' ? '' : String(+(Number(v) * 100).toFixed(4));
        function uncoveredSpaceTypes(plan) {
            const covered = new Set((plan.market_leasing_profiles || []).map(p => p.space_type));
            return [...new Set(plan.suites.map(s => s.space_type || 'office'))].filter(t => !covered.has(t));
        }
        // Lease terms: one row per lease, with the recovery terms for each expense.
        const RECOVERY_LABELS = { nnn: 'NNN', full_service_gross: 'Full service gross', modified_gross: 'Modified gross', base_year_stop: 'Base year stop', none: 'None' };
        const EXPIRY_LABELS = { market: 'Market', renew: 'Renews', vacate: 'Vacates', option: 'Option', reabsorb: 'Not re-leased' };
        const pctText = v => v == null || v === '' ? '' : `${+(Number(v) * 100).toFixed(2)}%`;
        function escalationText(lease, plan) {
            const steps = (plan.rent_steps || []).filter(r => r.source_lease_id === lease.source_id).length;
            if (lease.escalation_type === 'pct_annual') return `${pctText(lease.escalation_pct_annual)} / yr`;
            if (lease.escalation_type === 'cpi') return `CPI${lease.cpi_floor != null || lease.cpi_cap != null ? ` (${pctText(lease.cpi_floor) || '–'} to ${pctText(lease.cpi_cap) || '–'})` : ''}`;
            if (steps) return `${steps} rent step${steps === 1 ? '' : 's'}`;
            return lease.escalation_type === 'flat' ? 'Flat' : '—';
        }
        function expiryText(lease) {
            const label = EXPIRY_LABELS[lease.upon_expiration] || 'Market';
            if (lease.upon_expiration !== 'option') return label;
            const term = lease.option_term_months ? `${lease.option_term_months / 12} yr` : '';
            const rent = lease.option_rent_per_unit ? ` at $${Number(lease.option_rent_per_unit).toFixed(2)}/SF` : ' at market';
            return `${label} ${term}${rent}`.trim();
        }
        function expenseTermsText(lease, plan) {
            const rows = (plan.lease_expense_recoveries || []).filter(r => r.source_lease_id === lease.source_id);
            const shared = (plan.recovery_structure_items || []).filter(r => lease.source_recovery_structure_id && r.source_recovery_structure_id === lease.source_recovery_structure_id);
            const setup = (plan.recovery_structures || []).find(r => r.source_id === lease.source_recovery_structure_id);
            const parts = [...rows, ...shared].map(r => {
                const bits = [RECOVERY_LABELS[r.recovery_type] || r.recovery_type];
                if (r.base_year_stop_amount) bits.push(`stop $${Number(r.base_year_stop_amount).toLocaleString('en-US')}`);
                if (r.cap_per_sf_annual) bits.push(`cap $${Number(r.cap_per_sf_annual).toFixed(2)}/SF`);
                if (r.cap_growth_pct) bits.push(`cap +${pctText(r.cap_growth_pct)}/yr`);
                if (r.cap_group) bits.push(`shared cap: ${r.cap_group}`);
                if (r.admin_fee_pct) bits.push(`${pctText(r.admin_fee_pct)} fee`);
                return `${fmt.typeLabel(r.expense_category)}: ${bits.join(', ')}`;
            });
            return (setup ? `${setup.name}. ` : '') + (parts.join(' · ') || 'Same for all expenses');
        }
        function leaseTermsSection(plan) {
            if (!plan.leases.length) return '';
            const tenants = new Map(plan.tenants.map(t => [t.source_id, t.name]));
            const suites = new Map(plan.suites.map(r => [r.source_id, r.suite_name]));
            const notes = plan.review_notes || [];
            return `<section class="intake-section"><h3>Lease terms <small>${plan.leases.length}</small></h3>
                <p class="muted">Rent changes, expense recoveries and what happens at expiry, as read from the leases. Edit details shows every field.</p>
                ${notes.map(n => `<div class="intake-issue warning">${escapeHtmlAttr(n)}</div>`).join('')}
                <div class="table-wrap"><table class="data-table intake-lease-terms"><thead><tr>
                    <th>Tenant</th><th>Escalation</th><th>Recovery</th><th>Pro-rata share</th><th>Base year</th><th>Terms by expense</th><th>At expiry</th></tr></thead><tbody>
                ${plan.leases.map((l, i) => `<tr>
                    <td><strong>${escapeHtmlAttr(tenants.get(l.source_tenant_id) || 'Vacant')}</strong><small>Suite ${escapeHtmlAttr(suites.get(l.source_suite_id) || '')}</small></td>
                    <td>${escapeHtmlAttr(escalationText(l, plan))}</td>
                    <td><select class="intake-cell" data-lease="${i}" data-key="recovery_type">${Object.entries(RECOVERY_LABELS).map(([v, label]) => `<option value="${v}" ${v === l.recovery_type ? 'selected' : ''}>${label}</option>`).join('')}</select></td>
                    <td><input class="intake-cell" type="number" step="any" placeholder="Auto" data-lease="${i}" data-key="pro_rata_share_pct" data-kind="pct" value="${escapeHtmlAttr(pctShown(l.pro_rata_share_pct))}"></td>
                    <td><input class="intake-cell" type="number" step="1" placeholder="—" data-lease="${i}" data-key="base_year" data-kind="int" value="${escapeHtmlAttr(l.base_year ?? '')}"></td>
                    <td class="intake-terms-text">${escapeHtmlAttr(expenseTermsText(l, plan))}</td>
                    <td>${escapeHtmlAttr(expiryText(l))}</td></tr>`).join('')}
                </tbody></table></div></section>`;
        }
        function marketSection(plan) {
            const profiles = plan.market_leasing_profiles || [];
            const missing = uncoveredSpaceTypes(plan);
            return `<section class="intake-section"><h3>When leases expire</h3>
                <p class="muted">Market leasing assumptions decide how expiring space is re-leased.</p>
                ${profiles.map((p, i) => `<div class="intake-market-row"><strong>${escapeHtmlAttr(fmt.typeLabel(p.space_type))}</strong>
                    ${MARKET_FIELDS.map(([key, label, kind]) => `<label><span>${tipLabelHtml(key, label)}</span><input class="form-input" type="number" step="any" data-profile="${i}" data-key="${key}" data-kind="${kind}" value="${escapeHtmlAttr(kind === 'pct' ? pctShown(p[key]) : p[key] ?? '')}"></label>`).join('')}</div>`).join('')}
                ${missing.map(type => `<div class="intake-issue warning">No market assumptions for ${escapeHtmlAttr(type)} space: it is never re-leased after its leases expire.
                    <button class="btn btn-secondary btn-sm" data-add-market="${escapeHtmlAttr(type)}">Add assumptions</button></div>`).join('')}
            </section>`;
        }
        // Starting point for a new profile: the area-weighted in-place rent for that space type.
        function newMarketProfile(plan, type) {
            const suites = new Map(plan.suites.map(s => [s.source_id, s]));
            let rent = 0, area = 0;
            plan.leases.forEach(l => {
                const suite = suites.get(l.source_suite_id);
                if (!suite || (suite.space_type || 'office') !== type) return;
                const a = Number(suite.area) || 0;
                rent += (Number(l.base_rent_per_unit) || 0) * a; area += a;
            });
            return {
                source_id: `market-${type}`, space_type: type, description: `${type} market leasing`,
                market_rent_per_unit: area ? Math.round((rent / area) * 100) / 100 : 0,
                rent_growth_rate_pct: '0.03', renewal_probability: '0.65', downtime_months: 3,
            };
        }
        function renderCreate() {
            const done = created();
            if (done) {
                body.innerHTML = `<section class="intake-done"><h2>✓ Valuation created</h2><p>${escapeHtmlAttr(done.plan?.property?.name || '')}</p>
                    <div><a class="btn btn-primary" href="#/valuation/${done.rebuilt_valuation_id}" data-open>Open valuation</a>
                    ${isImport ? '' : `<button class="btn btn-secondary" data-compare="${done.id}">Compare with this valuation</button>`}</div></section>`;
                body.querySelector('[data-open]').onclick = () => workspace.remove();
                body.querySelector('[data-compare]')?.addEventListener('click', async () => showReconstructionComparison(await api.get(`/appraisal-reconstructions/${done.id}/comparison`)));
                return;
            }
            const setup = staged();
            if (!setup) { state.step = 'check'; render(); return; }
            if (state.planId !== setup.id) { state.plan = structuredClone(setup.plan); state.planId = setup.id; }
            const plan = state.plan;
            const shown = (root, key, kind) => {
                const v = plan[root]?.[key];
                if (v == null || v === '') return '';
                return kind === 'pct' ? String(+(Number(v) * 100).toFixed(4)) : String(v);
            };
            const area = plan.suites.reduce((sum, s) => sum + (Number(s.area) || 0), 0);
            const total = Number(plan.property.total_area) || 0;
            const coverage = total ? Math.round((area / total) * 100) : null;
            const counts = [['suites', 'suite'], ['tenants', 'tenant'], ['leases', 'lease'], ['expenses', 'expense'], ['other_income', 'other income line']]
                .map(([k, word]) => { const n = (plan[k] || []).length; return `<div><strong>${n}</strong><span>${word}${n === 1 || k === 'other_income' ? '' : 's'}</span></div>`; }).join('');
            const notes = issues().filter(i => i.code?.startsWith('missing_') && i.code.endsWith('_source'));
            body.innerHTML = `<p class="intake-lead">Check the key inputs, then create the valuation. You can change anything later.</p>
                <section class="intake-section"><h3>Key inputs</h3><div class="intake-setup-grid">
                    ${SETUP_FIELDS.map(([root, key, label, kind]) => `<label><span>${tipLabelHtml(key, label)}</span>${kind === 'select'
                        ? `<select class="form-input" data-root="${root}" data-key="${key}" data-kind="text">${propertyTypeOptions(false).map(o => `<option value="${o.value}" ${o.value === plan[root][key] ? 'selected' : ''}>${escapeHtmlAttr(o.label)}</option>`).join('')}</select>`
                        : `<input class="form-input" type="${kind === 'pct' ? 'number' : kind}" ${kind === 'pct' ? 'step="0.01"' : ''} data-root="${root}" data-key="${key}" data-kind="${kind}" value="${escapeHtmlAttr(shown(root, key, kind))}">`}</label>`).join('')}
                </div></section>
                <section class="intake-section"><h3>Model contents</h3><div class="intake-counts">${counts}</div>
                    ${coverage != null && plan.leases.length ? (coverage < 90
                        ? `<div class="intake-issue warning">Suites cover only ${coverage}% of the property's ${total.toLocaleString()} SF; ${Math.round(total - area).toLocaleString()} SF has no suite. Add the missing suites in Edit details, or check the total area.</div>`
                        : `<p class="muted">Suites cover ${coverage}% of the property's ${total.toLocaleString()} SF.</p>`) : ''}
                    ${notes.map(i => `<div class="intake-issue ${i.severity}">${escapeHtmlAttr(i.message)}</div>`).join('')}
                </section>
                ${leaseTermsSection(plan)}
                ${marketSection(plan)}
                <footer class="intake-footer"><button class="btn btn-secondary" data-back>Back</button><span class="intake-footer-spacer"></span>
                    <button class="btn btn-secondary" data-details>Edit details</button><button class="btn btn-primary" data-create>Create valuation</button></footer>`;
            body.querySelectorAll('[data-root]').forEach(el => el.onchange = () => {
                const { root, key, kind } = el.dataset;
                const raw = el.value.trim();
                plan[root][key] = raw === '' ? null : kind === 'pct' ? String(Number(raw) / 100) : kind === 'number' ? Number(raw) : raw;
            });
            body.querySelectorAll('[data-lease]').forEach(el => el.onchange = () => {
                const lease = plan.leases[Number(el.dataset.lease)];
                const raw = el.value.trim();
                const kind = el.dataset.kind;
                lease[el.dataset.key] = raw === '' ? null : kind === 'pct' ? String(Number(raw) / 100) : kind === 'int' ? parseInt(raw, 10) : raw;
            });
            body.querySelectorAll('[data-profile]').forEach(el => el.onchange = () => {
                const { profile, key, kind } = el.dataset;
                const raw = el.value.trim();
                plan.market_leasing_profiles[Number(profile)][key] = raw === '' ? null : kind === 'pct' ? String(Number(raw) / 100) : Number(raw);
            });
            body.querySelectorAll('[data-add-market]').forEach(el => el.onclick = () => {
                (plan.market_leasing_profiles ||= []).push(newMarketProfile(plan, el.dataset.addMarket));
                render();
            });
            body.querySelector('[data-back]').onclick = () => { state.step = 'check'; render(); };
            body.querySelector('[data-details]').onclick = () => showSetupDetails(plan, render);
            body.querySelector('[data-create]').onclick = async e => {
                const btn = e.currentTarget;
                btn.disabled = true; btn.textContent = 'Creating…';
                try {
                    await api.put(`/appraisal-reconstructions/${setup.id}`, { plan });
                    const result = await api.post(`/appraisal-reconstructions/${setup.id}/materialize`);
                    btn.textContent = 'Running valuation…';
                    try {
                        await api.post(`/valuations/${result.rebuilt_valuation_id}/run`);
                        toast('Valuation created and run', 'success');
                    } catch (err) {
                        toast(`Valuation created. It could not run yet: ${apiErrorDetail(err)}`, 'error');
                    }
                    if (isImport) { workspace.remove(); location.assign(`${location.pathname}#/valuation/${result.rebuilt_valuation_id}`); }
                    else await load();
                } catch (err) { toast(apiErrorDetail(err), 'error'); btn.disabled = false; btn.textContent = 'Create valuation'; }
            };
        }

        function render() {
            const configuration = workspace.querySelector('[data-configuration]');
            configuration.innerHTML = state.configuration && !state.configuration.configured && state.step !== 'create'
                ? `<div class="intake-configuration-error"><strong>Documents can't be read yet</strong>
                    <span>Reading documents needs an Anthropic API key. Ask whoever runs OpenDCF to add it and restart.
                    You can still upload files now; they are read once it is set up.</span>
                    <small title="Add to the .env file">Setting: ANTHROPIC_API_KEY</small></div>` : '';
            const reachable = { upload: true, check: processed().length > 0, create: !!(staged() || created()) };
            const order = ['upload', 'check', 'create'];
            const labels = { upload: 'Upload', check: 'Check', create: 'Create' };
            workspace.querySelector('[data-steps]').innerHTML = order.map((step, i) => {
                const cls = step === state.step ? 'active' : order.indexOf(state.step) > i ? 'done' : '';
                return `<button type="button" class="${cls}" data-step="${step}" ${reachable[step] && !state.busy && !intakeBuilds.has(valuationId) ? '' : 'disabled'}><b>${i + 1}</b> ${labels[step]}</button>`;
            }).join('');
            workspace.querySelectorAll('[data-step]').forEach(el => el.onclick = () => { state.step = el.dataset.step; render(); });
            ({ upload: renderUpload, check: renderCheck, create: renderCreate })[state.step]();
        }

        await load();
        await processPending();
    };
    if (button) button.onclick = open;
    return open;
}
