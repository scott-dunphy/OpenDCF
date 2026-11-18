/* ============================================================
   OpenDCF — Funds (portfolios), scenarios, assumption profiles, bulk import
   Uses helpers from app.js: api, fmt, toast, setBreadcrumb, showFormModal,
   showDeleteConfirm, addRoute, PROPERTY_TYPES, $app
   ============================================================ */

// Assumption fields shared by profiles and scenario overrides.
// kind: pct (fraction, entered as percent), money ($), months, pctShift (percentage-point shift)
const ASSUMPTION_FIELD_GROUPS = [
    {
        label: 'Valuation',
        fields: [
            ['discount_rate', 'Discount Rate', 'pct'],
            ['exit_cap_rate', 'Exit Cap Rate', 'pct'],
            ['exit_costs_pct', 'Exit Costs', 'pct'],
            ['direct_cap_rate', 'Direct Cap Rate', 'pct'],
            ['acquisition_costs_pct', 'Acquisition Costs', 'pct'],
            ['capital_reserves_per_unit', 'Capital Reserves (property basis)', 'money'],
            ['capital_reserves_per_sf', 'Capital Reserves $/SF (SF properties)', 'money'],
            ['capital_reserves_per_unit_count', 'Capital Reserves $/Unit (unit properties)', 'money'],
            ['management_fee_pct', 'Management Fee (% of EGI)', 'pct'],
            ['stabilized_occupancy_pct', 'Stabilized Occupancy', 'pct'],
        ],
    },
    {
        label: 'Market Leasing',
        fields: [
            ['market_rent_change_pct', 'Market Rent Change', 'pct'],
            ['market_rent_growth', 'Market Rent Growth', 'pct'],
            ['general_vacancy_pct', 'General Vacancy', 'pct'],
            ['credit_loss_pct', 'Credit Loss', 'pct'],
            ['renewal_probability', 'Renewal Probability', 'pct'],
            ['downtime_months', 'Downtime (months)', 'months'],
            ['new_lease_term_months', 'New Lease Term (months)', 'months'],
            ['renewal_lease_term_months', 'Renewal Term (months)', 'months'],
            ['new_ti_per_sf', 'New TI $/SF', 'money'],
            ['renewal_ti_per_sf', 'Renewal TI $/SF', 'money'],
            ['new_lc_pct', 'New LC', 'pct'],
            ['renewal_lc_pct', 'Renewal LC', 'pct'],
            ['new_free_rent_months', 'New Free Rent (months)', 'months'],
            ['renewal_free_rent_months', 'Renewal Free Rent (months)', 'months'],
        ],
    },
    {
        label: 'Growth',
        fields: [
            ['expense_growth', 'Expense Growth', 'pct'],
            ['other_income_growth', 'Other Income Growth', 'pct'],
            ['cpi_rate', 'CPI', 'pct'],
        ],
    },
];
const ASSUMPTION_FIELDS = ASSUMPTION_FIELD_GROUPS.flatMap(g => g.fields);
const ASSUMPTION_LABELS = Object.fromEntries(ASSUMPTION_FIELDS.map(([k, l]) => [k, l]));
const ASSUMPTION_KINDS = Object.fromEntries(ASSUMPTION_FIELDS.map(([k, , kind]) => [k, kind]));

function formatAssumption(key, value, shift = false) {
    const kind = ASSUMPTION_KINDS[key.replace(/^shift:/, '')];
    const n = parseFloat(value);
    if (isNaN(n)) return '—';
    const sign = shift && n > 0 ? '+' : '';
    // Rate shifts read naturally in bp (caps, discount); other percent shifts as signed %
    if (kind === 'pct' && shift && key.endsWith('_rate')) return `${sign}${(n * 10000).toFixed(0)} bp`;
    if (kind === 'pct') return sign + fmt.pct(n);
    if (kind === 'money') return `${sign}$${n.toFixed(2)}`;
    return `${sign}${n.toFixed(0)}`;
}

function assumptionValueFields(withRanges = false) {
    const out = [];
    ASSUMPTION_FIELD_GROUPS.forEach(g => {
        out.push({ type: 'section', label: g.label, collapsible: true, defaultCollapsed: g.label !== 'Valuation' });
        g.fields.forEach(([key, label, kind]) => {
            const num = {
                type: 'number', step: kind === 'pct' ? '0.0025' : (kind === 'money' ? '0.25' : '1'),
                asPercent: kind === 'pct',
            };
            if (!withRanges) {
                out.push({ key: `v_${key}`, label, half: true, ...num });
                return;
            }
            // Base, then the low/high spread across properties in the market (optional)
            out.push({ key: `v_${key}`, label, third: true, ...num });
            out.push({ key: `lo_${key}`, label: 'Low', third: true, ...num });
            out.push({ key: `hi_${key}`, label: 'High', third: true, ...num });
        });
    });
    return out;
}

function rangesFromForm(data) {
    const ranges = {};
    ASSUMPTION_FIELDS.forEach(([key]) => {
        const lo = data[`lo_${key}`], hi = data[`hi_${key}`];
        const set = v => v != null && v !== '' && !Number.isNaN(v);
        if (set(lo) || set(hi)) {
            if (!set(lo) || !set(hi)) throw new Error(`${ASSUMPTION_LABELS[key] || key}: enter both low and high, or neither`);
            ranges[key] = { low: lo, high: hi };
        }
    });
    return ranges;
}

function rangesToForm(ranges) {
    const out = {};
    Object.entries(ranges || {}).forEach(([k, r]) => {
        out[`lo_${k}`] = parseFloat(r.low);
        out[`hi_${k}`] = parseFloat(r.high);
    });
    return out;
}

function valuesFromForm(data) {
    const values = {};
    ASSUMPTION_FIELDS.forEach(([key]) => {
        const v = data[`v_${key}`];
        if (v != null && v !== '' && !Number.isNaN(v)) values[key] = v;
    });
    return values;
}

function valuesToForm(values) {
    const out = {};
    Object.entries(values || {}).forEach(([k, v]) => { if (v != null) out[`v_${k}`] = parseFloat(v); });
    return out;
}

function summarizeValues(values, shift = false, ranges = {}) {
    const entries = Object.entries(values || {}).filter(([, v]) => v != null);
    if (!entries.length) return '<span style="color:var(--text-secondary)">—</span>';
    return entries.map(([k, v]) => {
        const r = ranges[k];
        const span = r ? ` <span style="color:var(--text-secondary)">(${formatAssumption(k, r.low)}–${formatAssumption(k, r.high)})</span>` : '';
        return `${ASSUMPTION_LABELS[k] || k}: <strong>${formatAssumption(k, v, shift)}</strong>${span}`;
    }).join(' · ');
}

function propertyTypeOptions(includeAny = true) {
    const opts = PROPERTY_TYPES.map(t => ({ value: t, label: fmt.typeLabel(t) }));
    return includeAny ? [{ value: '', label: 'Any property type' }, ...opts] : opts;
}

async function downloadBlob(url, fallbackName) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Download failed (${res.status})`);
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') || '';
    const match = cd.match(/filename="?([^"]+)"?/i);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = match ? match[1] : fallbackName;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
}


// ═══════════════════════════════════════════════════════════════
// FUNDS LIST
// ═══════════════════════════════════════════════════════════════

async function fundsView() {
    setBreadcrumb([{ label: 'Properties', href: '#/dashboard' }, { label: 'Funds' }]);
    const [funds, properties] = await Promise.all([api.get('/portfolios'), api.get('/properties?limit=1000')]);

    $app().innerHTML = `
        <div class="page-header">
            <h1 class="page-title">Funds</h1>
            <p class="page-subtitle">Group properties, apply assumptions by property type and market, and run portfolio scenarios</p>
        </div>
        <div class="section-header">
            <h2 class="section-title">Portfolios</h2>
            <button class="btn btn-primary btn-sm" id="newFundBtn" style="white-space:nowrap">${icons.plus} New Fund</button>
        </div>
        ${funds.length === 0 ? `
            <div class="empty-state"><h3>No funds yet</h3><p>Create a fund, or bulk-import a workbook with a PortfolioName column.</p></div>
        ` : `
        <div class="data-table-wrap">
            <table class="data-table">
                <thead><tr><th>Name</th><th>Description</th><th style="text-align:right">Properties</th><th>Types</th><th>Markets</th></tr></thead>
                <tbody>
                    ${funds.map(f => `
                        <tr style="cursor:pointer" onclick="location.hash='#/fund/${f.id}'">
                            <td class="tenant-name"><strong>${escapeHtmlAttr(f.name)}</strong></td>
                            <td>${escapeHtmlAttr(f.description || '')}</td>
                            <td style="text-align:right">${f.properties.length}</td>
                            <td>${[...new Set(f.properties.map(p => fmt.typeLabel(p.property_type)))].join(', ') || '—'}</td>
                            <td>${[...new Set(f.properties.map(p => p.market).filter(Boolean))].join(', ') || '—'}</td>
                        </tr>`).join('')}
                </tbody>
            </table>
        </div>`}
    `;

    document.getElementById('newFundBtn').onclick = () => showFormModal({
        title: 'New Fund',
        fields: [
            { key: 'name', label: 'Name', type: 'text', required: true },
            { key: 'description', label: 'Description', type: 'text' },
            {
                key: 'property_ids', label: 'Properties', type: 'custom',
                render: (container, vals, setValue) => renderPropertyPicker(container, properties, [], setValue),
            },
        ],
        onSubmit: async (data, overlay) => {
            const ids = data.property_ids ? JSON.parse(data.property_ids) : [];
            const fund = await api.post('/portfolios', { name: data.name, description: data.description, property_ids: ids });
            overlay.remove();
            toast('Fund created', 'success');
            location.hash = `#/fund/${fund.id}`;
        },
    });
}

function renderPropertyPicker(container, properties, selectedIds, setValue) {
    const selected = new Set(selectedIds);
    const group = document.createElement('div');
    group.className = 'form-group';
    group.innerHTML = `<label class="form-label">Properties</label>
        <div style="max-height:240px;overflow:auto;border:1px solid var(--border);border-radius:8px;padding:8px">
            ${properties.length === 0 ? '<em>No properties</em>' : properties.map(p => `
                <label class="form-checkbox-row" style="display:flex;gap:8px;align-items:center;padding:2px 0">
                    <input type="checkbox" value="${p.id}" ${selected.has(p.id) ? 'checked' : ''}>
                    <span>${escapeHtmlAttr(p.name)} <span style="color:var(--text-secondary)">· ${fmt.typeLabel(p.property_type)}${p.market ? ' · ' + escapeHtmlAttr(p.market) : ''}</span></span>
                </label>`).join('')}
        </div>`;
    const sync = () => setValue('property_ids', JSON.stringify(
        [...group.querySelectorAll('input[type=checkbox]:checked')].map(i => i.value)
    ));
    group.querySelectorAll('input[type=checkbox]').forEach(i => i.addEventListener('change', sync));
    container.appendChild(group);
    sync();
}


// ═══════════════════════════════════════════════════════════════
// FUND DETAIL: properties, scenarios, runs
// ═══════════════════════════════════════════════════════════════

async function fundView({ id }) {
    const [fund, scenarios, runs, properties, approvedDates] = await Promise.all([
        api.get(`/portfolios/${id}`),
        api.get(`/portfolios/${id}/scenarios`),
        api.get(`/portfolios/${id}/runs`),
        api.get('/properties?limit=1000'),
        api.get(`/portfolios/${id}/approved-dates`).catch(() => []),
    ]);
    const asOfLabel = d => new Date(d + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    setBreadcrumb([{ label: 'Properties', href: '#/dashboard' }, { label: 'Funds', href: '#/funds' }, { label: fund.name }]);
    const selectedRunId = sessionStorage.getItem(`opendcf_fund_run_${id}`) || (runs[0] && runs[0].id);

    $app().innerHTML = `
        <div class="property-header">
            <div class="property-header-left">
                <h1 class="property-header-title">${escapeHtmlAttr(fund.name)}</h1>
                <div class="property-header-address">${[escapeHtmlAttr(fund.description || ''), `${fund.properties.length} properties`].filter(Boolean).join(' · ')}</div>
            </div>
            <div class="property-header-actions">
                <button class="btn btn-secondary btn-sm" id="editFundBtn">Edit</button>
                <button class="btn btn-danger btn-sm" id="deleteFundBtn">Delete</button>
            </div>
        </div>

        <div class="section-header"><h2 class="section-title">Portfolio Map</h2><span class="page-subtitle">Marker size reflects effective ownership</span></div>
        <div id="portfolioMap" class="portfolio-map"></div>
        <div id="portfolioMapUnmapped" class="field-hint"></div>

        <div class="section-header">
            <h2 class="section-title">Properties</h2>
            <button class="btn btn-secondary btn-sm" id="addFundPropsBtn" style="white-space:nowrap">${icons.plus} Add Properties</button>
        </div>
        <div class="data-table-wrap">
            <table class="data-table">
                <thead><tr><th>Property</th><th>Type</th><th>Market</th><th style="text-align:right">Ownership</th><th>Resolved Assumptions</th><th></th></tr></thead>
                <tbody>
                    ${fund.properties.length === 0 ? '<tr><td colspan="6"><em>No properties in this fund</em></td></tr>' : fund.properties.map(p => `
                        <tr>
                            <td class="tenant-name"><a href="#/property/${p.id}" style="color:var(--accent);text-decoration:none">${escapeHtmlAttr(p.name)}</a></td>
                            <td>${fmt.typeLabel(p.property_type)}</td>
                            <td>${escapeHtmlAttr(p.market || '—')}</td>
                            <td style="text-align:right">${fmt.pct(p.ownership_pct, 0)}</td>
                            <td><button class="btn btn-secondary btn-sm" data-resolved="${p.id}">View</button></td>
                            <td style="text-align:right;white-space:nowrap"><button class="btn btn-secondary btn-sm" data-interest="${p.id}">Ownership</button> <button class="btn btn-secondary btn-sm" data-remove="${p.id}">Remove</button></td>
                        </tr>`).join('')}
                </tbody>
            </table>
        </div>

        <div class="section-header">
            <h2 class="section-title">Scenarios</h2>
            <button class="btn btn-secondary btn-sm" id="newScenarioBtn" style="white-space:nowrap">${icons.plus} New Scenario</button>
        </div>
        <div class="data-table-wrap">
            <table class="data-table">
                <thead><tr><th style="width:36px">Run</th><th>Scenario</th><th>Overrides</th><th></th></tr></thead>
                <tbody>
                    <tr>
                        <td><input type="checkbox" id="runBase" checked></td>
                        <td><strong>Base</strong></td>
                        <td>Property models + assumption profiles</td>
                        <td></td>
                    </tr>
                    ${scenarios.map(s => `
                        <tr>
                            <td><input type="checkbox" class="run-scenario" value="${s.id}" checked></td>
                            <td><strong>${escapeHtmlAttr(s.name)}</strong>${s.description ? `<div style="color:var(--text-secondary);font-size:12px">${escapeHtmlAttr(s.description)}</div>` : ''}</td>
                            <td style="font-size:12px">${s.overrides.map(o => `
                                <div>${o.mode === 'shift' ? 'Shift' : 'Set'} · ${o.property_type ? fmt.typeLabel(o.property_type) : 'All types'}${o.market ? ' · ' + escapeHtmlAttr(o.market) : ''}: ${summarizeValues(o.values, o.mode === 'shift')}</div>`).join('') || '—'}</td>
                            <td style="text-align:right;white-space:nowrap">
                                <button class="btn btn-secondary btn-sm" data-edit-scenario="${s.id}">Edit</button>
                                <button class="btn btn-secondary btn-sm" data-delete-scenario="${s.id}">Delete</button>
                            </td>
                        </tr>`).join('')}
                </tbody>
            </table>
        </div>
        <div style="display:flex;gap:8px;align-items:center;margin:12px 0 24px">
            <input class="form-input" id="runName" placeholder="Run name (optional)" style="max-width:260px">
            <select class="form-input" id="runAsOf" style="width:auto" title="Which values to use">
                <option value="">Live: latest valuations, current inputs</option>
                ${approvedDates.map(d => `<option value="${d.value_date}">Approved as of ${asOfLabel(d.value_date)} (${d.properties} of ${d.of} properties)</option>`).join('')}
                <option value="other">Approved as of another date…</option>
            </select>
            <input class="form-input" type="date" id="runAsOfDate" style="width:auto;display:none">
            <button class="btn btn-primary" id="runFundBtn">Run Portfolio</button>
        </div>

        <div class="section-header">
            <h2 class="section-title">Results</h2>
            <div style="display:flex;gap:8px">${runs.length ? `<button class="btn btn-secondary btn-sm" id="allocationSensitivityBtn">Disposition Sensitivity</button><select class="form-input" id="runSelect" style="width:auto">
                ${runs.map(r => `<option value="${r.id}" ${r.id === selectedRunId ? 'selected' : ''}>${escapeHtmlAttr(r.name || 'Run')}${r.as_of ? ` · approved as of ${asOfLabel(r.as_of)}` : ' · live'} · ${new Date(r.created_at).toLocaleString()} · ${r.scenario_names.join(', ')}</option>`).join('')}
            </select>` : ''}</div>
        </div>
        <div id="fundRunResults">${runs.length ? '<div class="loading-spinner"></div>' : '<div class="empty-state"><p>No runs yet. Pick scenarios above and click Run Portfolio.</p></div>'}</div>
    `;
    renderPortfolioMap(fund.properties);

    // Fund edit / delete
    document.getElementById('editFundBtn').onclick = () => showFormModal({
        title: 'Edit Fund',
        fields: [
            { key: 'name', label: 'Name', type: 'text', required: true },
            { key: 'description', label: 'Description', type: 'text' },
        ],
        initialValues: { name: fund.name, description: fund.description },
        onSubmit: async (data, overlay) => {
            await api.put(`/portfolios/${id}`, data);
            overlay.remove();
            fundView({ id });
        },
    });
    document.getElementById('deleteFundBtn').onclick = () => showDeleteConfirm(fund.name, async () => {
        await api.del(`/portfolios/${id}`);
        location.hash = '#/funds';
    });

    // Membership
    document.getElementById('addFundPropsBtn').onclick = () => {
        const inFund = new Set(fund.properties.map(p => p.id));
        const candidates = properties.filter(p => !inFund.has(p.id));
        showFormModal({
            title: 'Add Properties',
            fields: [{
                key: 'property_ids', label: 'Properties', type: 'custom',
                render: (container, vals, setValue) => renderPropertyPicker(container, candidates, [], setValue),
            }],
            onSubmit: async (data, overlay) => {
                await api.post(`/portfolios/${id}/properties`, { property_ids: JSON.parse(data.property_ids || '[]') });
                overlay.remove();
                fundView({ id });
            },
        });
    };
    document.querySelectorAll('[data-remove]').forEach(btn => btn.onclick = async () => {
        await api.del(`/portfolios/${id}/properties/${btn.dataset.remove}`).catch(() => null);
        // DELETE returns the portfolio body; api.del ignores it
        fundView({ id });
    });
    document.querySelectorAll('[data-resolved]').forEach(btn => btn.onclick = () => showResolvedAssumptions(btn.dataset.resolved, id));
    document.querySelectorAll('[data-interest]').forEach(btn => btn.onclick = () => {
        const p = fund.properties.find(item => item.id === btn.dataset.interest);
        showFormModal({
            title: `Portfolio Interest · ${p.name}`,
            fields: [
                {key:'ownership_pct', label:'Effective Ownership (%)', type:'number', required:true, half:true},
                {key:'currency', label:'Currency', type:'text', required:true, half:true},
                {key:'effective_from', label:'Effective From', type:'date', half:true},
                {key:'effective_to', label:'Effective To', type:'date', half:true},
                {key:'acquisition_cost', label:'Acquisition Cost (share)', type:'number', half:true},
                {key:'commitment', label:'Total Commitment', type:'number', half:true},
            ],
            // ownership_pct is stored as a fraction; the form shows and parses it as a percent
            initialValues: p,
            onSubmit: async (changed, overlay) => {
                // Edit mode passes only changed fields; the PUT needs the whole interest
                const data = { ...p, ...changed };
                await api.put(`/portfolios/${id}/properties/${p.id}/interest`, {
                    ownership_pct: Number(data.ownership_pct),
                    currency: (data.currency || 'USD').toUpperCase(),
                    effective_from: data.effective_from || null, effective_to: data.effective_to || null,
                    acquisition_cost: data.acquisition_cost ? Number(data.acquisition_cost) : null,
                    commitment: data.commitment ? Number(data.commitment) : null,
                });
                overlay.remove(); toast('Portfolio ownership updated', 'success'); fundView({id});
            },
        });
    });

    // Scenarios
    document.getElementById('newScenarioBtn').onclick = () => showScenarioEditor(id, null);
    document.querySelectorAll('[data-edit-scenario]').forEach(btn => btn.onclick = () =>
        showScenarioEditor(id, scenarios.find(s => s.id === btn.dataset.editScenario)));
    document.querySelectorAll('[data-delete-scenario]').forEach(btn => btn.onclick = () => {
        const s = scenarios.find(x => x.id === btn.dataset.deleteScenario);
        showDeleteConfirm(s.name, async () => {
            await api.del(`/portfolios/${id}/scenarios/${s.id}`);
            fundView({ id });
        });
    });

    // Run
    document.getElementById('runAsOf').onchange = (e) => {
        document.getElementById('runAsOfDate').style.display = e.target.value === 'other' ? '' : 'none';
    };
    document.getElementById('runFundBtn').onclick = async () => {
        const btn = document.getElementById('runFundBtn');
        const scenarioIds = [...document.querySelectorAll('.run-scenario:checked')].map(i => i.value);
        const includeBase = document.getElementById('runBase').checked;
        if (!includeBase && !scenarioIds.length) { toast('Select the base case or a scenario', 'error'); return; }
        const choice = document.getElementById('runAsOf').value;
        const asOf = choice === 'other' ? document.getElementById('runAsOfDate').value : choice;
        if (choice === 'other' && !asOf) { toast('Pick the as-of date', 'error'); return; }
        btn.disabled = true;
        btn.textContent = 'Running...';
        try {
            const run = await api.post(`/portfolios/${id}/runs`, {
                name: document.getElementById('runName').value || null,
                scenario_ids: scenarioIds,
                include_base: includeBase,
                as_of: asOf || null,
            });
            sessionStorage.setItem(`opendcf_fund_run_${id}`, run.id);
            toast('Portfolio run complete', 'success');
            fundView({ id });
        } catch (err) {
            toast('Error: ' + err.message, 'error');
            btn.disabled = false;
            btn.textContent = 'Run Portfolio';
        }
    };

    const runSelect = document.getElementById('runSelect');
    if (runSelect) {
        runSelect.onchange = () => {
            sessionStorage.setItem(`opendcf_fund_run_${id}`, runSelect.value);
            loadFundRun(id, runSelect.value);
        };
        loadFundRun(id, runSelect.value);
    }
    const sensitivityBtn = document.getElementById('allocationSensitivityBtn');
    if (sensitivityBtn) sensitivityBtn.onclick = () => showAllocationSensitivity(id, runSelect.value, fund.properties);
}

function renderPortfolioMap(properties, selectedIds = new Set(), hostId = 'portfolioMap', noteId = 'portfolioMapUnmapped', onMarkerClick = null) {
    const host = document.getElementById(hostId);
    if (!host || typeof L === 'undefined') {
        if (host) host.innerHTML = '<div class="empty-state"><p>Map library unavailable.</p></div>';
        return;
    }
    const mapped = properties.filter(p => p.latitude != null && p.longitude != null);
    const unmapped = properties.filter(p => p.latitude == null || p.longitude == null);
    if (host._portfolioMap) host._portfolioMap.remove();
    const map = L.map(host).setView([39.5, -98.35], 4);
    host._portfolioMap = map;
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);
    const colors = {office:'#0071e3', industrial:'#ff9500', retail:'#af52de', multifamily:'#34c759', hotel:'#ff3b30'};
    const bounds = [];
    mapped.forEach(p => {
        const size = 14 + Math.round(Math.sqrt(Math.max(0, Number(p.ownership_pct))) * 12);
        const color = selectedIds.has(p.id) ? '#ff3b30' : (colors[p.property_type] || '#5e5ce6');
        const icon = L.divIcon({className:'portfolio-map-marker', html:`<span style="width:${size}px;height:${size}px;background:${color}"></span>`, iconSize:[size,size]});
        const marker = L.marker([Number(p.latitude), Number(p.longitude)], {icon}).addTo(map);
        marker.bindPopup(`<strong>${escapeHtmlAttr(p.name)}</strong><br>${fmt.typeLabel(p.property_type)} · ${fmt.pct(p.ownership_pct, 1)} owned`);
        if (onMarkerClick) marker.on('click', () => onMarkerClick(p));
        bounds.push([Number(p.latitude), Number(p.longitude)]);
    });
    if (bounds.length) map.fitBounds(bounds, {padding:[30,30], maxZoom:12});
    const note = document.getElementById(noteId);
    if (note) note.textContent = unmapped.length ? `${unmapped.length} unmapped: ${unmapped.map(p => p.name).join(', ')}. Add latitude and longitude in the property editor.` : '';
}

function showAllocationSensitivity(portfolioId, runId, properties) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `<div class="modal wide"><div class="modal-title">Disposition Allocation Sensitivity</div><p class="form-help">Select assets and expected sale dates. Leave sale price blank to use the nearest forecast quarter-end market value.</p><div id="dispositionMap" class="portfolio-map"></div><div id="dispositionMapNote" class="field-hint"></div><div class="data-table-wrap"><table class="data-table"><thead><tr><th>Sell</th><th>Property</th><th>Ownership</th><th>Sale Date</th><th>100% Sale Price</th><th>Costs %</th></tr></thead><tbody>${properties.map(p => `<tr><td><input type="checkbox" data-dispose="${p.id}"></td><td>${escapeHtmlAttr(p.name)}</td><td>${fmt.pct(p.ownership_pct,1)}</td><td><input class="form-input" type="date" data-sale-date="${p.id}"></td><td><input class="form-input" type="number" step="any" placeholder="Forecast" data-sale-price="${p.id}"></td><td><input class="form-input" type="number" step="0.1" value="2" data-sale-cost="${p.id}"></td></tr>`).join('')}</tbody></table></div><div id="dispositionResult"></div><div class="modal-actions"><button class="btn btn-secondary" data-close>Close</button><button class="btn btn-primary" data-run>Analyze Sales</button></div></div>`;
    document.body.appendChild(overlay);
    const selected = () => new Set([...overlay.querySelectorAll('[data-dispose]:checked')].map(el => el.dataset.dispose));
    const redraw = () => renderPortfolioMap(properties, selected(), 'dispositionMap', 'dispositionMapNote', p => {
        const checkbox = overlay.querySelector(`[data-dispose="${p.id}"]`);
        checkbox.checked = !checkbox.checked;
        redraw();
    });
    redraw();
    overlay.querySelectorAll('[data-dispose]').forEach(el => el.onchange = redraw);
    overlay.querySelector('[data-close]').onclick = () => overlay.remove();
    overlay.querySelector('[data-run]').onclick = async () => {
        const ids = [...selected()];
        if (!ids.length) { toast('Select at least one asset', 'error'); return; }
        try {
            const dispositions = ids.map(id => {
                const dateValue = overlay.querySelector(`[data-sale-date="${id}"]`).value;
                if (!dateValue) throw new Error('Enter a sale date for every selected asset');
                const price = overlay.querySelector(`[data-sale-price="${id}"]`).value;
                return {property_id:id, sale_date:dateValue, sale_price:price ? Number(price) : null, sale_cost_pct:Number(overlay.querySelector(`[data-sale-cost="${id}"]`).value || 0) / 100};
            });
            const result = await api.post(`/portfolios/${portfolioId}/runs/${runId}/allocation-sensitivity`, {scenario_id:null, dispositions});
            const buckets = (title, rows) => `<div><h4>${title}</h4><table class="data-table"><tbody>${rows.map(row => `<tr><td>${escapeHtmlAttr(row.key)}</td><td class="num">${fmt.currency(row.share_value)}</td><td class="num">${fmt.pct(row.allocation_pct)}</td></tr>`).join('')}</tbody></table></div>`;
            overlay.querySelector('#dispositionResult').innerHTML = `<div class="metrics-grid"><div class="metric-card"><div class="metric-label">Net Sale Proceeds</div><div class="metric-value">${fmt.currency(result.net_sale_proceeds)}</div></div><div class="metric-card"><div class="metric-label">Remaining Value</div><div class="metric-value">${fmt.currency(result.remaining_share_value)}</div></div><div class="metric-card"><div class="metric-label">XIRR After</div><div class="metric-value">${result.portfolio_xirr_after == null ? '—' : fmt.pct(result.portfolio_xirr_after)}</div></div><div class="metric-card"><div class="metric-label">Required Liquidity After</div><div class="metric-value">${fmt.currency(result.required_liquidity_after)}</div></div><div class="metric-card"><div class="metric-label">HHI After</div><div class="metric-value">${result.concentration_hhi_after == null ? '—' : Number(result.concentration_hhi_after).toFixed(3)}</div></div></div><div class="two-col">${buckets('Allocation by Type', result.by_property_type)}${buckets('Allocation by Market', result.by_market)}</div><div class="field-hint">${result.warnings.map(escapeHtmlAttr).join(' · ')}</div>`;
        } catch (err) { toast(err.message, 'error'); }
    };
}

async function showResolvedAssumptions(propertyId, portfolioId) {
    const r = await api.get(`/properties/${propertyId}/resolved-assumptions?portfolio_id=${portfolioId}`);
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    const rows = Object.entries(r.values).filter(([k]) => !k.startsWith('shift:'));
    overlay.innerHTML = `
        <div class="modal wide">
            <div class="modal-title">Resolved assumptions · ${fmt.typeLabel(r.property_type)}${r.market ? ' · ' + escapeHtmlAttr(r.market) : ''}</div>
            ${rows.length === 0 ? '<p>No assumption profile matches this property; its own model is used as-is.</p>' : `
            <table class="data-table">
                <thead><tr><th>Assumption</th><th style="text-align:right">Value</th><th>From</th></tr></thead>
                <tbody>${rows.map(([k, v]) => `
                    <tr><td>${ASSUMPTION_LABELS[k] || k}</td><td style="text-align:right">${formatAssumption(k, v)}</td><td>${escapeHtmlAttr((r.sources[k] || '').replace(/^profile:/, ''))}</td></tr>`).join('')}
                </tbody>
            </table>`}
            <p class="form-help" style="margin-top:12px">Fields not listed come from the property's own valuation and market leasing profiles.</p>
            <div class="modal-actions"><button class="btn btn-secondary" id="closeResolved">Close</button></div>
        </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector('#closeResolved').onclick = () => overlay.remove();
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
}

function showScenarioEditor(portfolioId, scenario) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    // Read schemas return every assumption key; keep only the ones that are set
    let overrides = scenario
        ? scenario.overrides.map(o => ({ ...o, values: Object.fromEntries(Object.entries(o.values).filter(([, v]) => v != null)) }))
        : [{ mode: 'shift', values: {} }];

    const fieldOptions = ASSUMPTION_FIELDS.map(([k, l]) => `<option value="${k}">${l}</option>`).join('');

    function render() {
        overlay.innerHTML = `
            <div class="modal wide">
                <div class="modal-title">${scenario ? 'Edit' : 'New'} Scenario</div>
                <div class="form-row">
                    <div class="form-group"><label class="form-label">Name</label><input class="form-input" id="scName" value="${escapeHtmlAttr(scenario ? scenario.name : '')}"></div>
                    <div class="form-group"><label class="form-label">Description</label><input class="form-input" id="scDesc" value="${escapeHtmlAttr(scenario ? (scenario.description || '') : '')}"></div>
                    <div class="form-group"><label class="form-label">Probability (%)</label><input class="form-input" id="scProbability" type="number" min="0" max="100" step="0.1" value="${scenario && scenario.probability_pct != null ? Number(scenario.probability_pct) * 100 : ''}"></div>
                </div>
                <p class="form-help">Each rule applies to properties matching its type and market. <strong>Shift</strong> adds to the base value (percent fields in percentage points, e.g. 0.50 = +50 bp); <strong>Set</strong> replaces it.</p>
                ${overrides.map((o, i) => `
                    <div class="form-section" style="border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:12px">
                        <div class="form-row">
                            <div class="form-group"><label class="form-label">Mode</label>
                                <select class="form-input" data-i="${i}" data-f="mode">
                                    <option value="shift" ${o.mode === 'shift' ? 'selected' : ''}>Shift</option>
                                    <option value="set" ${o.mode === 'set' ? 'selected' : ''}>Set</option>
                                </select></div>
                            <div class="form-group"><label class="form-label">Property Type</label>
                                <select class="form-input" data-i="${i}" data-f="property_type">
                                    ${propertyTypeOptions().map(t => `<option value="${t.value}" ${(o.property_type || '') === t.value ? 'selected' : ''}>${t.label}</option>`).join('')}
                                </select></div>
                            <div class="form-group"><label class="form-label">Market</label>
                                <input class="form-input" data-i="${i}" data-f="market" value="${escapeHtmlAttr(o.market || '')}" placeholder="Any market"></div>
                        </div>
                        <table class="data-table" style="margin-bottom:8px">
                            <tbody>
                                ${Object.entries(o.values).map(([k, v]) => {
                                    const kind = ASSUMPTION_KINDS[k];
                                    const shown = kind === 'pct' ? (parseFloat(v) * 100).toFixed(2) : parseFloat(v);
                                    return `<tr>
                                        <td>${ASSUMPTION_LABELS[k] || k}${kind === 'pct' ? ' (%)' : ''}</td>
                                        <td style="width:160px"><input class="form-input" type="number" step="any" data-i="${i}" data-v="${k}" value="${shown}"></td>
                                        <td style="width:40px"><button class="btn btn-secondary btn-sm" data-i="${i}" data-rm="${k}">×</button></td>
                                    </tr>`;
                                }).join('')}
                            </tbody>
                        </table>
                        <div style="display:flex;gap:8px">
                            <select class="form-input" data-add-field="${i}" style="max-width:260px"><option value="">Add assumption…</option>${fieldOptions}</select>
                            <button class="btn btn-secondary btn-sm" data-rm-rule="${i}">Remove rule</button>
                        </div>
                    </div>`).join('')}
                <button class="btn btn-secondary btn-sm" id="scAddRule">${icons.plus} Add rule</button>
                <div class="modal-actions">
                    <button class="btn btn-secondary" id="scCancel">Cancel</button>
                    <button class="btn btn-primary" id="scSave">${scenario ? 'Save Changes' : 'Create'}</button>
                </div>
            </div>`;
        wire();
    }

    function collect() {
        overlay.querySelectorAll('[data-f]').forEach(el => {
            const o = overrides[+el.dataset.i];
            const val = el.value.trim();
            o[el.dataset.f] = val || (el.dataset.f === 'mode' ? 'shift' : null);
        });
        overlay.querySelectorAll('[data-v]').forEach(el => {
            const o = overrides[+el.dataset.i];
            const k = el.dataset.v;
            const n = parseFloat(el.value);
            if (isNaN(n)) delete o.values[k];
            else o.values[k] = ASSUMPTION_KINDS[k] === 'pct' ? n / 100 : n;
        });
    }

    function wire() {
        overlay.querySelector('#scCancel').onclick = () => overlay.remove();
        overlay.querySelector('#scAddRule').onclick = () => { collect(); overrides.push({ mode: 'shift', values: {} }); render(); };
        overlay.querySelectorAll('[data-rm-rule]').forEach(b => b.onclick = () => { collect(); overrides.splice(+b.dataset.rmRule, 1); render(); });
        overlay.querySelectorAll('[data-rm]').forEach(b => b.onclick = () => { collect(); delete overrides[+b.dataset.i].values[b.dataset.rm]; render(); });
        overlay.querySelectorAll('[data-add-field]').forEach(sel => sel.onchange = () => {
            if (!sel.value) return;
            collect();
            overrides[+sel.dataset.addField].values[sel.value] = 0;
            render();
        });
        overlay.querySelector('#scSave').onclick = async () => {
            collect();
            const name = overlay.querySelector('#scName').value.trim();
            if (!name) { toast('Scenario name is required', 'error'); return; }
            const body = {
                name,
                description: overlay.querySelector('#scDesc').value.trim() || null,
                probability_pct: overlay.querySelector('#scProbability').value === '' ? null : Number(overlay.querySelector('#scProbability').value) / 100,
                overrides: overrides.filter(o => Object.keys(o.values).length).map(o => ({
                    mode: o.mode, property_type: o.property_type || null, market: o.market || null, values: o.values,
                })),
            };
            try {
                if (scenario) await api.put(`/portfolios/${portfolioId}/scenarios/${scenario.id}`, body);
                else await api.post(`/portfolios/${portfolioId}/scenarios`, body);
                overlay.remove();
                fundView({ id: portfolioId });
            } catch (err) {
                toast('Error: ' + err.message, 'error');
            }
        };
    }

    render();
    document.body.appendChild(overlay);
}

async function loadFundRun(portfolioId, runId) {
    const el = document.getElementById('fundRunResults');
    let run;
    try {
        run = await api.get(`/portfolios/${portfolioId}/runs/${runId}`);
    } catch (err) {
        el.innerHTML = `<div class="empty-state"><p>${escapeHtmlAttr(err.message)}</p></div>`;
        return;
    }
    const sc = run.scenarios;
    const base = sc.find(s => s.scenario_id == null) || sc[0];
    const years = [...new Set(sc.flatMap(s => Object.keys(s.share_annual_noi)))].sort();
    const colors = ['rgba(0,113,227,0.75)', 'rgba(255,149,0,0.75)', 'rgba(52,199,89,0.75)', 'rgba(175,82,222,0.75)', 'rgba(255,59,48,0.75)'];

    const groupTable = (title, key) => {
        const keys = [...new Set(sc.flatMap(s => s[key].map(g => g.key)))];
        if (!keys.length) return '';
        return `
            <div class="section-header"><h3 class="section-title">${title}</h3></div>
            <div class="data-table-wrap"><table class="data-table">
                <thead><tr><th>${title.replace('By ', '')}</th>${sc.map(s => `<th style="text-align:right">${escapeHtmlAttr(s.scenario_name)} Value</th><th style="text-align:right">Cap</th>`).join('')}</tr></thead>
                <tbody>${keys.map(k => `<tr><td>${escapeHtmlAttr(key === 'by_property_type' ? fmt.typeLabel(k) : k)}</td>${sc.map(s => {
                    const g = s[key].find(x => x.key === k);
                    return g ? `<td style="text-align:right">${fmt.currency(g.share_value)}</td><td style="text-align:right">${g.implied_cap_rate != null ? fmt.pct(g.implied_cap_rate) : '—'}</td>` : '<td>—</td><td>—</td>';
                }).join('')}</tr>`).join('')}</tbody>
            </table></div>`;
    };

    const propIds = base.properties.map(p => p.property_id);
    const asOfText = run.as_of ? new Date(run.as_of + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : null;
    el.innerHTML = `
        ${asOfText ? `<div class="banner banner-info"><strong>Approved values as of ${asOfText}.</strong>
            Each property uses its latest valuation approved with a date of value on or before then; scenarios change those frozen inputs.
            ${base.excluded_count ? `${base.excluded_count} of ${base.properties.length} properties have no value and are left out of the totals.` : ''}</div>` : ''}
        ${run.probability_weighted_value != null ? `<div class="metrics-grid"><div class="metric-card highlight"><div class="metric-label">Probability-Weighted Value</div><div class="metric-value accent">${fmt.currency(run.probability_weighted_value)}</div></div><div class="metric-card"><div class="metric-label">Probability-Weighted Year 1 NOI</div><div class="metric-value">${fmt.currency(run.probability_weighted_year1_noi)}</div></div></div>` : ''}
        <div class="data-table-wrap">
            <table class="data-table">
                <thead><tr><th>Scenario</th><th style="text-align:right">Value (share)</th><th style="text-align:right">vs Base</th><th style="text-align:right">Yr 1 NOI (share)</th><th style="text-align:right">Implied Cap</th><th style="text-align:right">Portfolio XIRR</th></tr></thead>
                <tbody>${sc.map(s => `
                    <tr>
                        <td><strong>${escapeHtmlAttr(s.scenario_name)}</strong></td>
                        <td style="text-align:right">${fmt.currency(s.total_share_value)}</td>
                        <td style="text-align:right;color:${parseFloat(s.change_vs_base_pct) < 0 ? 'var(--red)' : 'inherit'}">${s.change_vs_base_pct != null ? fmt.pct(s.change_vs_base_pct) : '—'}</td>
                        <td style="text-align:right">${fmt.currency(s.total_share_year1_noi)}</td>
                        <td style="text-align:right">${s.implied_cap_rate != null ? fmt.pct(s.implied_cap_rate) : '—'}</td>
                        <td style="text-align:right">${s.portfolio_xirr != null ? fmt.pct(s.portfolio_xirr) : '—'}</td>
                    </tr>`).join('')}
                </tbody>
            </table>
        </div>
        <div class="metrics-grid">
            <div class="metric-card"><div class="metric-label">Forecast TWR</div><div class="metric-value">${base.portfolio_time_weighted_return == null ? '—' : fmt.pct(base.portfolio_time_weighted_return)}</div></div>
            <div class="metric-card"><div class="metric-label">Required Liquidity</div><div class="metric-value">${fmt.currency(base.required_liquidity)}</div></div>
            <div class="metric-card"><div class="metric-label">Largest Property</div><div class="metric-value">${base.largest_property_pct == null ? '—' : fmt.pct(base.largest_property_pct)}</div></div>
            <div class="metric-card"><div class="metric-label">Concentration HHI</div><div class="metric-value">${base.concentration_hhi == null ? '—' : Number(base.concentration_hhi).toFixed(3)}</div></div>
        </div>
        ${base.risk_alerts.length ? `<div class="evidence-issue critical"><strong>Concentration alerts</strong><ul>${base.risk_alerts.map(item => `<li>${escapeHtmlAttr(item)}</li>`).join('')}</ul></div>` : ''}
        <div class="chart-container">
            <div class="chart-title">Ownership-Share NOI by Year</div>
            <div class="chart-wrap"><canvas id="fundNoiChart"></canvas></div>
        </div>
        ${groupTable('By Property Type', 'by_property_type')}
        ${groupTable('By Market', 'by_market')}
        <div class="section-header"><h3 class="section-title">By Property</h3></div>
        <div class="data-table-wrap"><table class="data-table">
            <thead><tr><th>Property</th><th>Type</th><th>Market</th>${sc.map(s => `<th style="text-align:right">${escapeHtmlAttr(s.scenario_name)}</th>`).join('')}<th style="text-align:right">Base IRR</th><th>Notes</th></tr></thead>
            <tbody>${propIds.map(pid => {
                const b = base.properties.find(p => p.property_id === pid);
                // Overrides a property's model can't use (e.g. lease fields on a storage unit mix), per scenario
                const skipped = sc.flatMap(s => (s.properties.find(x => x.property_id === pid)?.warnings || [])
                    .map(w => sc.length > 1 ? `${s.scenario_name}: ${w}` : w));
                const basis = b.valuation_name ? `Approved “${b.valuation_name}”, value as of ${new Date(b.value_date + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}` : null;
                const notes = [basis, b.rerun ? null : 'Stored result (scenarios not applied)', ...new Set(skipped)].filter(Boolean).join(' · ');
                return `<tr>
                    <td class="tenant-name"><a href="#/property/${pid}" style="color:var(--accent);text-decoration:none">${escapeHtmlAttr(b.property_name)}</a></td>
                    <td>${fmt.typeLabel(b.property_type)}</td>
                    <td>${escapeHtmlAttr(b.market || '—')}</td>
                    ${sc.map(s => { const p = s.properties.find(x => x.property_id === pid); return `<td style="text-align:right">${p && p.share_value != null ? fmt.currency(p.share_value) : '—'}</td>`; }).join('')}
                    <td style="text-align:right">${b.irr != null ? fmt.pct(b.irr) : '—'}</td>
                    <td style="font-size:12px">${b.error ? `<span style="color:var(--red)">${escapeHtmlAttr(b.error)}</span>${notes ? ' · ' : ''}` : ''}<span style="color:var(--text-secondary)">${escapeHtmlAttr(notes)}</span></td>
                </tr>`;
            }).join('')}</tbody>
        </table></div>
    `;

    const ctx = document.getElementById('fundNoiChart');
    if (ctx && years.length) {
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: years,
                datasets: sc.map((s, i) => ({
                    label: s.scenario_name,
                    data: years.map(y => parseFloat(s.share_annual_noi[y] || 0)),
                    borderColor: colors[i % colors.length],
                    backgroundColor: colors[i % colors.length],
                    tension: 0.2,
                })),
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: sc.length > 1, position: 'top' },
                    tooltip: { callbacks: { label: c => c.dataset.label + ': ' + fmt.currencyExact(c.parsed.y) } },
                },
                scales: { y: { ticks: { callback: v => fmt.currency(v) } } },
            },
        });
    }
}


// ═══════════════════════════════════════════════════════════════
// ASSUMPTION PROFILES
// ═══════════════════════════════════════════════════════════════

async function assumptionsView() {
    setBreadcrumb([{ label: 'Properties', href: '#/dashboard' }, { label: 'Assumptions' }]);
    const [profiles, funds, cbsaList] = await Promise.all([api.get('/assumption-profiles'), api.get('/portfolios'), cbsaOptions()]);
    const fundName = Object.fromEntries(funds.map(f => [f.id, f.name]));

    // Same order as the resolver: type, then geography (CBSA > market name > state), quality, fund
    const geo = p => p.cbsa_code ? 3 : p.market ? 2 : p.state ? 1 : 0;
    const rank = p => [p.property_type ? 1 : 0, geo(p), p.quality_score ? 1 : 0, p.portfolio_id ? 1 : 0];
    const cmp = (a, b) => rank(a).reduce((d, x, i) => d || x - rank(b)[i], 0) || a.name.localeCompare(b.name);
    const sorted = [...profiles].sort(cmp);
    const marketText = p => p.cbsa_title || p.market || (p.state ? `${p.state} (statewide)` : 'Any');
    // The house-wide profile with no scope at all holds the house defaults
    const house = profiles.find(p => !p.portfolio_id && !p.property_type && !p.cbsa_code && !p.market && !p.state && !p.quality_score);

    $app().innerHTML = `
        <div class="page-header">
            <h1 class="page-title">Assumptions Library</h1>
            <p class="page-subtitle">Underwriting assumptions by property type and census market (CBSA), each with an optional low–high range. A property's 1–5 quality score places it in the range: 5 = the favourable end, 3 = base. The most specific profile wins field by field: CBSA + type + quality &gt; CBSA + type &gt; state + type &gt; type &gt; default; a fund-specific profile beats a house-wide one at the same level.</p>
        </div>
        <div class="section-header">
            <h2 class="section-title">House defaults</h2>
            <button class="btn btn-secondary btn-sm" id="houseDefaultsBtn">${icons.edit} Edit</button>
        </div>
        <div class="storage-assumptions" style="margin-bottom:24px">
            ${[['management_fee_pct', 'Management fee', 'Copied into new properties as a % of EGI expense line'],
               ['capital_reserves_per_sf', 'Capital reserves, SF properties', 'Per SF per year; copied into new valuations'],
               ['capital_reserves_per_unit_count', 'Capital reserves, unit properties', 'Per unit per year; copied into new valuations'],
            ].map(([k, label, note]) => `<div class="storage-assumption"><span>${label}</span><strong>${house && house.values[k] != null ? formatAssumption(k, house.values[k]) : 'Not set'}</strong><small>${note}</small></div>`).join('')}
        </div>
        <div class="section-header">
            <h2 class="section-title">Profiles</h2>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
                <button class="btn btn-secondary btn-sm" id="directionsBtn">Quality directions</button>
                <button class="btn btn-secondary btn-sm" id="profileTemplateBtn">Download template</button>
                <button class="btn btn-secondary btn-sm" id="profileExportBtn">Export library</button>
                <a class="btn btn-secondary btn-sm" href="#/import">Import</a>
                <button class="btn btn-primary btn-sm" id="newProfileBtn" style="white-space:nowrap">${icons.plus} New Profile</button>
            </div>
        </div>
        <div class="data-table-wrap">
            <table class="data-table">
                <thead><tr><th>Name</th><th>Scope</th><th>Property Type</th><th>Market</th><th>Quality</th><th>As of</th><th>Values (low–high)</th><th></th></tr></thead>
                <tbody>
                    ${sorted.length === 0 ? '<tr><td colspan="8"><em>No profiles yet. Create one, or download the template, fill it in and import it.</em></td></tr>' : sorted.map(p => `
                        <tr>
                            <td class="tenant-name"><strong>${escapeHtmlAttr(p.name)}</strong></td>
                            <td>${p.portfolio_id ? escapeHtmlAttr(fundName[p.portfolio_id] || 'Fund') : 'House-wide'}</td>
                            <td>${p.property_type ? fmt.typeLabel(p.property_type) : 'Any'}</td>
                            <td>${escapeHtmlAttr(marketText(p))}</td>
                            <td>${p.quality_score || 'All'}</td>
                            <td style="white-space:nowrap" title="${escapeHtmlAttr(p.source || '')}">${p.as_of ? fmt.date(p.as_of) : '—'}</td>
                            <td style="font-size:12px">${summarizeValues(p.values, false, p.ranges)}</td>
                            <td style="text-align:right;white-space:nowrap">
                                <button class="btn btn-secondary btn-sm" data-edit="${p.id}">Edit</button>
                                <button class="btn btn-secondary btn-sm" data-delete="${p.id}">Delete</button>
                            </td>
                        </tr>`).join('')}
                </tbody>
            </table>
        </div>
    `;

    const scopeFields = () => [
        { key: 'name', label: 'Name', type: 'text', required: true },
        {
            key: 'portfolio_id', label: 'Scope', type: 'select', half: true,
            options: [{ value: '', label: 'House-wide (all funds)' }, ...funds.map(f => ({ value: f.id, label: f.name }))],
        },
        { key: 'property_type', label: 'Property Type', type: 'select', half: true, options: propertyTypeOptions(), tip: 'The profile applies only to properties of this type. Blank = any type.' },
        { key: 'cbsa_label', label: 'Census market (CBSA)', type: 'text', half: true, suggestions: cbsaList, tip: 'The profile applies only to properties in this Census market. The most specific matching geography wins.',
          helpText: 'Blank = any market. Type a city or code and pick.' },
        { key: 'quality_score', label: 'Quality', type: 'select', half: true,
          options: [{ value: '', label: 'All qualities (ranges apply)' }, ...[1, 2, 3, 4, 5].map(q => ({ value: String(q), label: `Only quality ${q}` }))] },
        { key: 'state', label: 'State', type: 'text', half: true, tip: 'Two-letter state; matches properties in that state. Ranks below a CBSA match.', helpText: 'For properties outside a CBSA, e.g. TX.' },
        { key: 'market', label: 'Market name', type: 'text', half: true, helpText: 'Optional free-text market or submarket; matching ignores case.' },
        { key: 'as_of', label: 'As of', type: 'date', half: true },
        { key: 'source', label: 'Source', type: 'text', half: true },
        { key: 'comment', label: 'Comment', type: 'text' },
        ...assumptionValueFields(true),
    ];

    const toBody = data => ({
        name: data.name,
        portfolio_id: data.portfolio_id || null,
        property_type: data.property_type || null,
        cbsa_code: cbsaCodeFromLabel(data.cbsa_label) || null,
        quality_score: data.quality_score ? Number(data.quality_score) : null,
        state: data.state || null,
        market: data.market || null,
        as_of: data.as_of || null,
        source: data.source || null,
        comment: data.comment || null,
        values: valuesFromForm(data),
        ranges: rangesFromForm(data),
    });
    document.getElementById('houseDefaultsBtn').onclick = () => {
        const keys = ['management_fee_pct', 'capital_reserves_per_sf', 'capital_reserves_per_unit_count'];
        const initial = valuesToForm(Object.fromEntries(keys.map(k => [k, house?.values[k]]).filter(([, v]) => v != null)));
        showFormModal({
            title: 'House defaults',
            fields: [
                { key: 'v_management_fee_pct', label: 'Management fee (% of EGI)', type: 'number', step: '0.0025', asPercent: true,
                  helpText: 'New office, retail, industrial, multifamily, mixed-use and storage properties start with this fee line.' },
                { key: 'v_capital_reserves_per_sf', label: 'Capital reserves $/SF/yr', type: 'number', step: '0.05', half: true,
                  helpText: 'New valuations of SF-measured properties.' },
                { key: 'v_capital_reserves_per_unit_count', label: 'Capital reserves $/unit/yr', type: 'number', step: '5', half: true,
                  helpText: 'New valuations of unit-measured properties.' },
            ],
            initialValues: initial,
            onSubmit: async (diff, overlay) => {
                const form = { ...initial, ...diff };
                const values = { ...(house?.values || {}) };
                keys.forEach(k => {
                    const v = form[`v_${k}`];
                    if (v == null || v === '' || Number.isNaN(v)) delete values[k]; else values[k] = v;
                });
                if (house) await api.put(`/assumption-profiles/${house.id}`, { values, ranges: Object.fromEntries(Object.entries(house.ranges || {}).filter(([k]) => k in values)) });
                else await api.post('/assumption-profiles', { name: 'House defaults', values });
                overlay.remove();
                toast('House defaults saved. Saved valuations are unchanged; portfolio runs use the new values.', 'success');
                assumptionsView();
            },
        });
    };
    document.getElementById('directionsBtn').onclick = async () => {
        const { directions } = await api.get('/assumption-settings');
        const opts = [{ value: 'lower', label: 'Lower is better' }, { value: 'higher', label: 'Higher is better' }, { value: 'none', label: 'No direction (always base)' }];
        const fields = [];
        ASSUMPTION_FIELD_GROUPS.forEach(g => {
            fields.push({ type: 'section', label: g.label });
            // Per-SF / per-unit reserves follow the property-basis reserves row
            g.fields.filter(([key]) => key in directions)
                .forEach(([key, label]) => fields.push({ key, label, type: 'select', options: opts, half: true,
                    tip: 'Which end of this assumption\'s Low–High range a quality 5 property takes; quality 1 takes the other end and 3 the base. No direction = always base.' }));
        });
        showFormModal({
            title: 'Quality directions',
            wide: true,
            fields: [{ type: 'section', label: 'Which end of each range a quality 5 property takes; quality 1 takes the other end, 3 the base.' }, ...fields],
            initialValues: directions,
            onSubmit: async (diff, overlay) => {
                if (Object.keys(diff).length) await api.put('/assumption-settings', { directions: diff });
                overlay.remove();
                toast('Directions saved. They apply to every profile.', 'success');
            },
        });
    };
    document.getElementById('profileTemplateBtn').onclick = () =>
        downloadBlob('/api/v1/assumption-profiles/template.xlsx', 'assumptions-library-template.xlsx').catch(e => toast(e.message, 'error'));
    document.getElementById('profileExportBtn').onclick = () =>
        downloadBlob('/api/v1/assumption-profiles/template.xlsx?include_existing=true', 'assumptions-library.xlsx').catch(e => toast(e.message, 'error'));

    document.getElementById('newProfileBtn').onclick = () => showFormModal({
        title: 'New Assumption Profile',
        fields: scopeFields(),
        wide: true,
        onSubmit: async (data, overlay) => {
            await api.post('/assumption-profiles', toBody(data));
            overlay.remove();
            toast('Profile created', 'success');
            assumptionsView();
        },
    });
    document.querySelectorAll('[data-edit]').forEach(btn => btn.onclick = () => {
        const p = profiles.find(x => x.id === btn.dataset.edit);
        const initial = {
            name: p.name, portfolio_id: p.portfolio_id || '', property_type: p.property_type || '',
            market: p.market || '', comment: p.comment || '', ...valuesToForm(p.values),
            cbsa_label: cbsaLabel(p.cbsa_code, p.cbsa_title), quality_score: p.quality_score ? String(p.quality_score) : '',
            state: p.state || '', as_of: p.as_of || '', source: p.source || '', ...rangesToForm(p.ranges),
        };
        showFormModal({
            title: 'Edit Assumption Profile',
            fields: scopeFields(),
            wide: true,
            initialValues: initial,
            onSubmit: async (diff, overlay) => {
                // The form sends only changed fields; merge onto the original to send a full profile
                await api.put(`/assumption-profiles/${p.id}`, toBody({ ...initial, ...diff }));
                overlay.remove();
                assumptionsView();
            },
        });
    });
    document.querySelectorAll('[data-delete]').forEach(btn => btn.onclick = () => {
        const p = profiles.find(x => x.id === btn.dataset.delete);
        showDeleteConfirm(p.name, async () => {
            await api.del(`/assumption-profiles/${p.id}`);
            assumptionsView();
        });
    });
}


// ═══════════════════════════════════════════════════════════════
// BULK IMPORT
// ═══════════════════════════════════════════════════════════════

async function importView({ jobId } = {}) {
    setBreadcrumb([{ label: 'Properties', href: '#/dashboard' }, { label: 'Import from Excel' }]);
    const [jobs, funds] = await Promise.all([api.get('/imports'), api.get('/portfolios')]);
    const job = jobId ? await api.get(`/imports/${jobId}`) : null;

    $app().innerHTML = `
        <div class="page-header">
            <h1 class="page-title">Import from Excel</h1>
            <p class="page-subtitle">Bring in many properties at once from one workbook, one sheet per kind of data: properties, leases, market leasing, expenses and loans. Start from the template, or use input sheets exported from published DCF software. Lender loan tapes go on a sheet named Loan Tape. You see a preview before anything is saved.</p>
        </div>

        <div class="chart-container">
            <div class="form-group"><label class="form-label" for="importFile">Workbook (.xlsx)</label><input class="form-input" type="file" id="importFile" accept=".xlsx,.xlsm"></div>
            <details class="import-defaults">
                <summary>Defaults for anything the workbook leaves out</summary>
                <div class="form-row">
                    <div class="form-group"><label class="form-label">Property type</label>
                        <select class="form-input" id="importType">${propertyTypeOptions(false).map(t => `<option value="${t.value}">${t.label}</option>`).join('')}</select></div>
                    <div class="form-group"><label class="form-label">Analysis start</label><input class="form-input" type="date" id="importStart"></div>
                    <div class="form-group"><label class="form-label">Analysis period (months)</label><input class="form-input" type="number" id="importMonths" value="120" min="12" max="360" step="12"></div>
                </div>
            </details>
            <div style="display:flex;gap:8px;margin-top:12px">
                <button class="btn btn-primary" id="importPreviewBtn">Preview import</button>
                <button class="btn btn-secondary" id="importTemplateBtn">Download template</button>
            </div>
        </div>

        <div id="importPreview">${job ? '' : ''}</div>

        <div class="section-header"><h2 class="section-title">Recent Imports</h2></div>
        <div class="data-table-wrap"><table class="data-table">
            <thead><tr><th>File</th><th>Status</th><th style="text-align:right">Properties</th><th>Created</th></tr></thead>
            <tbody>${jobs.length === 0 ? '<tr><td colspan="4"><em>No imports yet</em></td></tr>' : jobs.map(j => `
                <tr style="cursor:pointer" onclick="location.hash='#/import/${j.id}'">
                    <td class="tenant-name">${escapeHtmlAttr(j.filename)}</td>
                    <td><span class="status-badge status-${j.status === 'committed' ? 'completed' : j.status === 'failed' ? 'failed' : 'draft'}">${j.status}</span></td>
                    <td style="text-align:right">${j.properties.length}</td>
                    <td>${new Date(j.created_at).toLocaleString()}</td>
                </tr>`).join('')}
            </tbody>
        </table></div>
    `;

    document.getElementById('importTemplateBtn').onclick = () =>
        downloadBlob(`${API}/imports/template.xlsx`, 'ares_import_template.xlsx').catch(err => toast(err.message, 'error'));

    document.getElementById('importPreviewBtn').onclick = async () => {
        const file = document.getElementById('importFile').files[0];
        if (!file) { toast('Choose a workbook first', 'error'); return; }
        const options = {
            default_property_type: document.getElementById('importType').value,
            analysis_period_months: parseInt(document.getElementById('importMonths').value, 10) || 120,
        };
        const start = document.getElementById('importStart').value;
        if (start) options.analysis_start_date = start;
        const btn = document.getElementById('importPreviewBtn');
        btn.disabled = true;
        btn.textContent = 'Reading...';
        try {
            const res = await fetch(`${API}/imports/preview?filename=${encodeURIComponent(file.name)}&options=${encodeURIComponent(JSON.stringify(options))}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/octet-stream' },
                body: file,
            });
            if (!res.ok) throw new Error(`POST → ${res.status}: ${await res.text()}`);
            const created = await res.json();
            location.hash = `#/import/${created.id}`;
        } catch (err) {
            toast(apiErrorDetail(err), 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Preview import';
        }
    };

    if (job) renderImportJob(job, funds);
}

function renderImportJob(job, funds) {
    const el = document.getElementById('importPreview');
    const committed = job.status === 'committed';
    el.innerHTML = `
        <div class="section-header">
            <h2 class="section-title">${escapeHtmlAttr(job.filename)} <span class="status-badge status-${committed ? 'completed' : job.status === 'failed' ? 'failed' : 'draft'}">${job.status}</span></h2>
        </div>
        ${job.errors.length ? `<div class="modal-warning" style="margin-bottom:12px">${job.errors.map(escapeHtmlAttr).join('<br>')}</div>` : ''}
        ${job.warnings.length ? `<div class="form-help" style="margin-bottom:12px">${job.warnings.map(escapeHtmlAttr).join('<br>')}</div>` : ''}

        <div class="data-table-wrap"><table class="data-table">
            <thead><tr><th>Property</th><th>Type</th><th>Market</th><th style="text-align:right">Area</th><th style="text-align:right">Suites</th><th style="text-align:right">Leases</th><th style="text-align:right">MLAs</th><th style="text-align:right">Expenses</th><th>Valuation</th><th>Warnings</th></tr></thead>
            <tbody>${job.properties.map(p => `
                <tr>
                    <td class="tenant-name">${escapeHtmlAttr(p.name)} <span style="color:var(--text-secondary);font-size:12px">${escapeHtmlAttr(p.external_id)}</span></td>
                    <td>${fmt.typeLabel(p.property_type)}</td>
                    <td>${escapeHtmlAttr(p.market || '—')}</td>
                    <td style="text-align:right">${fmt.num(p.total_area)}</td>
                    <td style="text-align:right">${p.suites}</td>
                    <td style="text-align:right">${p.leases}</td>
                    <td style="text-align:right">${p.market_profiles}</td>
                    <td style="text-align:right">${p.expenses}</td>
                    <td>${p.has_valuation ? 'Yes' : 'Defaults'}</td>
                    <td style="font-size:12px">${p.warnings.map(escapeHtmlAttr).join('<br>')}</td>
                </tr>`).join('')}
            </tbody>
        </table></div>
        ${job.assumption_profiles ? `<p class="form-help">${job.assumption_profiles} assumption profile(s) will also be created.</p>` : ''}
        ${job.loans.length ? `
        <div class="section-header"><h3 class="section-title">Loan Tape</h3></div>
        <div class="data-table-wrap"><table class="data-table">
            <thead><tr><th>Loan</th><th>Collateral</th><th>Link</th><th style="text-align:right">Lien</th><th style="text-align:right">Original</th><th style="text-align:right">Current</th><th>Originated</th><th>Maturity</th><th>Rate</th><th>Status</th><th>Warnings</th></tr></thead>
            <tbody>${job.loans.map(l => `
                <tr>
                    <td class="tenant-name">${escapeHtmlAttr(l.external_id)}</td>
                    <td>${escapeHtmlAttr(l.property_name || l.property_ref || '—')}</td>
                    <td>${{ workbook: 'Property in this file', existing: 'Existing property', new: 'New tape-only property' }[l.property_link]}</td>
                    <td style="text-align:right">${l.lien_position}</td>
                    <td style="text-align:right">${fmt.currency(l.original_balance)}</td>
                    <td style="text-align:right">${l.reported_balance ? fmt.currency(l.reported_balance) : '—'}</td>
                    <td>${fmt.date(l.origination_date)}</td>
                    <td>${fmt.date(l.maturity_date)}</td>
                    <td>${l.rate == null ? '—' : l.rate_type === 'fixed' ? fmt.pct(l.rate, 3) : 'Index + ' + (l.rate * 10000).toFixed(0) + ' bp'}</td>
                    <td>${escapeHtmlAttr(l.delinquency_status)}</td>
                    <td style="font-size:12px">${l.warnings.map(escapeHtmlAttr).join('<br>')}</td>
                </tr>`).join('')}
            </tbody>
        </table></div>` : ''}

        <div class="section-header"><h3 class="section-title">Column Mapping</h3></div>
        <div class="data-table-wrap"><table class="data-table">
            <thead><tr><th>Sheet</th><th>Format</th><th>Recognized As</th><th style="text-align:right">Rows</th><th>Mapped</th><th>Not Mapped</th></tr></thead>
            <tbody>${job.sheets.map(s => `
                <tr>
                    <td>${escapeHtmlAttr(s.sheet)}</td>
                    <td>${s.format === 'xl4adw' ? 'XL4ADW' : 'Plain'}</td>
                    <td>${s.recognized_as ? fmt.typeLabel(s.recognized_as) : '<span style="color:var(--red)">Ignored</span>'}</td>
                    <td style="text-align:right">${s.rows}</td>
                    <td style="font-size:12px">${Object.entries(s.mapped_columns).map(([h, f]) => `${escapeHtmlAttr(h)} → ${f}`).join('<br>')}</td>
                    <td style="font-size:12px;color:var(--text-secondary)">${s.unmapped_columns.map(escapeHtmlAttr).join(', ')}</td>
                </tr>`).join('')}
            </tbody>
        </table></div>

        ${committed ? `
            <p>Created ${job.created_property_ids.length} propert${job.created_property_ids.length === 1 ? 'y' : 'ies'}${job.created_loan_count ? ` and ${job.created_loan_count} loan${job.created_loan_count === 1 ? '' : 's'} (<a href="#/loans" style="color:var(--accent)">loan book</a>)` : ''}.
            ${job.portfolio_id ? `<a href="#/fund/${job.portfolio_id}" style="color:var(--accent)">Open fund</a>` : '<a href="#/dashboard" style="color:var(--accent)">Open dashboard</a>'}</p>
        ` : job.status === 'previewed' ? `
            <div class="chart-container">
                <div class="form-row">
                    <div class="form-group"><label class="form-label">Add to Fund</label>
                        <select class="form-input" id="commitFund">
                            <option value="">Use PortfolioName from file / none</option>
                            ${funds.map(f => `<option value="${f.id}">${escapeHtmlAttr(f.name)}</option>`).join('')}
                            <option value="__new">New fund…</option>
                        </select></div>
                    <div class="form-group" id="commitNewFundWrap" style="display:none"><label class="form-label">New Fund Name</label><input class="form-input" id="commitNewFund"></div>
                </div>
                <label class="form-checkbox-row"><input type="checkbox" id="commitReplace"> Replace properties and loans previously imported with the same external ID</label>
                <div style="margin-top:12px"><button class="btn btn-primary" id="commitBtn">Import ${[
                    job.properties.length ? `${job.properties.length} Propert${job.properties.length === 1 ? 'y' : 'ies'}` : '',
                    job.loans.length ? `${job.loans.length} Loan${job.loans.length === 1 ? '' : 's'}` : '',
                ].filter(Boolean).join(' and ') || 'Assumption Profiles'}</button></div>
            </div>` : ''}
    `;

    const fundSel = document.getElementById('commitFund');
    if (fundSel) {
        fundSel.onchange = () => {
            document.getElementById('commitNewFundWrap').style.display = fundSel.value === '__new' ? '' : 'none';
        };
        document.getElementById('commitBtn').onclick = async () => {
            const body = { replace_existing: document.getElementById('commitReplace').checked };
            if (fundSel.value === '__new') {
                const name = document.getElementById('commitNewFund').value.trim();
                if (!name) { toast('Enter a fund name', 'error'); return; }
                body.portfolio_name = name;
            } else if (fundSel.value) {
                body.portfolio_id = fundSel.value;
            }
            const btn = document.getElementById('commitBtn');
            btn.disabled = true;
            btn.textContent = 'Importing...';
            try {
                await api.post(`/imports/${job.id}/commit`, body);
                toast('Import complete', 'success');
                importView({ jobId: job.id });
            } catch (err) {
                toast('Error: ' + err.message, 'error');
                btn.disabled = false;
            }
        };
    }
}


addRoute('/funds', fundsView);
addRoute('/fund/:id', fundView);
addRoute('/assumptions', assumptionsView);
addRoute('/import', importView);
addRoute('/import/:jobId', importView);
