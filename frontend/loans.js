/* ============================================================
   OpenDCF — Mortgage loan book, Monte Carlo risk runs, risk admin
   Uses helpers from app.js: api, fmt, toast, setBreadcrumb, showFormModal,
   showDeleteConfirm, addRoute, escapeHtmlAttr, icons, $app
   ============================================================ */

const DELINQUENCY_LABELS = {
    current: 'Current', '30': '30 days', '60': '60 days', '90_plus': '90+ days', foreclosure: 'Foreclosure', reo: 'REO',
};
const RATING_ORDER = ['Aaa', 'Aa1', 'Aa2', 'Aa3', 'A1', 'A2', 'A3', 'Baa1', 'Baa2', 'Baa3',
    'Ba1', 'Ba2', 'Ba3', 'B1', 'B2', 'B3', 'Caa1', 'Caa2', 'Caa3', 'Ca'];

const bps = v => (v == null || isNaN(parseFloat(v))) ? '—' : (parseFloat(v) * 10000).toFixed(0) + ' bp';
const ratio = v => (v == null || isNaN(parseFloat(v))) ? '—' : parseFloat(v).toFixed(2) + 'x';
const pctOrDash = (v, d = 1) => v == null ? '—' : fmt.pct(v, d);
const num = (v, d = 0) => fmt.num(v, d);
const today = () => new Date().toISOString().slice(0, 10);
const td = (v, right = true) => `<td${right ? ' style="text-align:right"' : ''}>${v}</td>`;

function ratingBadge(r) {
    if (!r) return '—';
    const i = RATING_ORDER.indexOf(r);
    const cls = i < 10 ? 'status-completed' : i < 16 ? 'status-running' : 'status-failed';
    return `<span class="status-badge ${cls}">${r}</span>`;
}

function cmBadge(cm) {
    if (!cm) return '—';
    const n = parseInt(cm.slice(2), 10);
    const cls = n <= 2 ? 'status-completed' : n <= 4 ? 'status-running' : 'status-failed';
    return `<span class="status-badge ${cls}">${cm}</span>`;
}

async function latestCompletedRun() {
    const runs = await api.get('/loan-risk-runs');
    const done = runs.find(r => r.status === 'completed');
    return done ? api.get(`/loan-risk-runs/${done.id}`) : null;
}

function destroyCharts(ids) {
    ids.forEach(id => {
        const c = Chart.getChart(id);
        if (c) c.destroy();
    });
}


function auditValue(v) {
    if (v == null) return '<span style="color:var(--text-tertiary)">—</span>';
    const s = typeof v === 'object' ? JSON.stringify(v) : String(v);
    return escapeHtmlAttr(s.length > 80 ? s.slice(0, 77) + '…' : s);
}

// Audit log entries as a table; showEntity adds the record type and id column
function renderAuditTable(entries, { showEntity = false } = {}) {
    if (!entries.length) return '<p class="form-help">No recorded changes.</p>';
    return `<div class="data-table-wrap" style="max-height:420px;overflow:auto"><table class="data-table" style="font-size:12px">
        <thead><tr><th>When</th>${showEntity ? '<th>Record</th>' : ''}<th>Action</th><th>Changes</th><th>Source</th></tr></thead>
        <tbody>${entries.map(e => {
            const fields = Object.entries(e.changes);
            const shown = e.action === 'update' ? fields : fields.slice(0, 6);
            return `<tr>
                <td style="white-space:nowrap">${new Date(e.created_at + (e.created_at.endsWith('Z') || e.created_at.includes('+') ? '' : 'Z')).toLocaleString()}</td>
                ${showEntity ? `<td>${fmt.typeLabel(e.entity_type)}<br><span style="color:var(--text-tertiary)">${e.entity_id.slice(0, 8)}</span></td>` : ''}
                <td><span class="status-badge status-${e.action === 'delete' ? 'failed' : e.action === 'create' ? 'completed' : 'draft'}">${e.action}</span></td>
                <td>${shown.map(([k, [before, after]]) => e.action === 'update'
                    ? `<div><strong>${escapeHtmlAttr(k)}</strong>: ${auditValue(before)} → ${auditValue(after)}</div>`
                    : `<div><strong>${escapeHtmlAttr(k)}</strong>: ${auditValue(e.action === 'create' ? after : before)}</div>`).join('')}
                    ${shown.length < fields.length ? `<div style="color:var(--text-tertiary)">+${fields.length - shown.length} more fields</div>` : ''}</td>
                <td style="color:var(--text-secondary)">${escapeHtmlAttr(e.source || '')}</td></tr>`;
        }).join('')}</tbody></table></div>`;
}


// ═══════════════════════════════════════════════════════════════
// LOAN FORM
// ═══════════════════════════════════════════════════════════════

function loanFields(properties, funds) {
    return [
        { type: 'section', label: 'Loan' },
        { key: 'property_id', label: 'Collateral Property', type: 'select', required: true,
          options: properties.map(p => ({ value: p.id, label: p.name })) },
        { key: 'external_id', label: 'Loan ID', type: 'text', half: true },
        { key: 'name', label: 'Name', type: 'text', half: true },
        { key: 'portfolio_id', label: 'Fund', type: 'select', half: true,
          options: [{ value: '', label: 'None' }, ...funds.map(f => ({ value: f.id, label: f.name }))] },
        { key: 'lien_position', label: 'Lien Position (1 = senior)', type: 'number', half: true, step: '1' },
        { key: 'sponsor', label: 'Sponsor / Borrower', type: 'text', half: true },
        { key: 'recourse', label: 'Recourse', type: 'checkbox', half: true },
        { type: 'section', label: 'Terms (at origination)' },
        { key: 'origination_date', label: 'Origination Date', type: 'date', required: true, half: true },
        { key: 'maturity_date', label: 'Maturity Date', type: 'date', required: true, half: true },
        { key: 'original_balance', label: 'Original Balance ($)', type: 'number', required: true, half: true },
        { key: 'rate_type', label: 'Rate Type', type: 'select', half: true,
          options: [{ value: 'fixed', label: 'Fixed' }, { value: 'floating', label: 'Floating' }] },
        { key: 'coupon', label: 'Coupon (fixed)', type: 'number', half: true, step: '0.0005', asPercent: true },
        { key: 'spread', label: 'Spread (floating)', type: 'number', half: true, step: '0.0005', asPercent: true },
        { key: 'index_floor', label: 'Index Floor', type: 'number', half: true, step: '0.0025', asPercent: true },
        { key: 'index_cap', label: 'Index Cap', type: 'number', half: true, step: '0.0025', asPercent: true },
        { key: 'amortization_months', label: 'Amortization (months, blank = IO)', type: 'number', half: true, step: '12' },
        { key: 'io_months', label: 'Interest-Only Months', type: 'number', half: true, step: '1' },
        { key: 'extension_count', label: 'Extension Options', type: 'number', half: true, step: '1' },
        { key: 'extension_months', label: 'Months per Extension', type: 'number', half: true, step: '1' },
        { type: 'section', label: 'Loan Tape', collapsible: true },
        { key: 'reported_balance', label: 'Reported Balance ($)', type: 'number', half: true },
        { key: 'balance_as_of_date', label: 'Balance As Of', type: 'date', half: true },
        { key: 'delinquency_status', label: 'Delinquency', type: 'select', half: true,
          options: Object.entries(DELINQUENCY_LABELS).map(([value, label]) => ({ value, label })) },
        { key: 'origination_value', label: 'Value at Origination ($)', type: 'number', half: true },
        { type: 'section', label: 'Tape Collateral (used when the property has no full model)', collapsible: true,
          defaultCollapsed: true },
        { key: 'tape_noi', label: 'Current Annual NOI ($)', type: 'number', half: true },
        { key: 'tape_value', label: 'Current Value ($)', type: 'number', half: true },
        { key: 'tape_value_date', label: 'Value Date', type: 'date', half: true },
        { key: 'tape_noi_growth', label: 'NOI Growth', type: 'number', half: true, step: '0.0025', asPercent: true },
        { key: 'tape_exit_cap_rate', label: 'Exit Cap Rate', type: 'number', half: true, step: '0.0025', asPercent: true,
          helpText: 'Base cap rate for values after today (refinance, extension, liquidation). Blank uses NOI ÷ value.' },
        { key: 'comment', label: 'Comment', type: 'text' },
    ];
}

function loanBody(data) {
    const body = { ...data };
    const ints = ['lien_position', 'amortization_months', 'io_months', 'extension_count', 'extension_months'];
    Object.keys(body).forEach(k => {
        if (body[k] === '' || body[k] == null) body[k] = null;
        else if (ints.includes(k)) body[k] = parseInt(body[k], 10);
    });
    body.recourse = !!data.recourse;
    ['io_months', 'extension_count', 'extension_months'].forEach(k => { if (body[k] == null) body[k] = 0; });
    if (body.lien_position == null) body.lien_position = 1;
    if (!body.delinquency_status) body.delinquency_status = 'current';
    if (body.rate_type === 'fixed') body.spread = null;
    else body.coupon = null;
    return body;
}

async function openLoanForm(loan, { propertyId, onSaved } = {}) {
    const [properties, funds] = await Promise.all([api.get('/properties?limit=1000'), api.get('/portfolios')]);
    if (!properties.length) { toast('Create or import a collateral property first', 'error'); return; }
    const fields = loanFields(properties, funds);
    showFormModal({
        title: loan ? 'Edit Loan' : 'New Loan',
        wide: true,
        memoryKey: 'loan-form',
        fields,
        initialValues: loan || null,
        defaults: propertyId ? { property_id: propertyId } : null,
        onSubmit: async (data, overlay) => {
            // loanBody fills defaults for missing fields, so an edit needs the unchanged ones too
            const body = loanBody(loan ? withUnchanged(fields, loan, data) : data);
            const saved = loan ? await api.put(`/loans/${loan.id}`, body) : await api.post('/loans', body);
            overlay.remove();
            toast(loan ? 'Loan updated' : 'Loan created', 'success');
            if (onSaved) onSaved(saved);
            else location.hash = `#/loan/${saved.id}`;
        },
    });
}


// ═══════════════════════════════════════════════════════════════
// LOAN BOOK
// ═══════════════════════════════════════════════════════════════

async function loansView() {
    setBreadcrumb([{ label: 'Properties', href: '#/dashboard' }, { label: 'Loan Book' }]);
    const [loans, properties, funds, run] = await Promise.all([
        api.get('/loans'), api.get('/properties?limit=1000'), api.get('/portfolios'), latestCompletedRun(),
    ]);
    const propById = Object.fromEntries(properties.map(p => [p.id, p]));
    const fundById = Object.fromEntries(funds.map(f => [f.id, f]));
    const riskById = Object.fromEntries((run?.results?.loans || []).map(r => [r.loan_id, r]));
    const pf = run?.results?.portfolio;

    $app().innerHTML = `
        <div class="page-header">
            <h1 class="page-title">Loan Book</h1>
            <p class="page-subtitle">Commercial mortgage loans held, with LTV, DSCR, ratings and expected loss from the latest risk run</p>
        </div>
        <div class="kpi-row">
            <div class="kpi-card"><div class="kpi-label">Loans</div><div class="kpi-value">${loans.length}</div></div>
            <div class="kpi-card"><div class="kpi-label">Balance Today</div><div class="kpi-value">${pf ? fmt.currency(pf.total_balance) : fmt.currency(loans.reduce((s, l) => s + parseFloat(l.reported_balance || l.original_balance), 0))}</div>
                <div class="kpi-subtext">${pf ? 'Rolled forward to ' + fmt.dateFull(run.as_of_date) : 'Tape / original balance'}</div></div>
            <div class="kpi-card"><div class="kpi-label">Fair Value</div><div class="kpi-value">${pf ? fmt.currency(pf.fair_value) : '—'}</div>
                <div class="kpi-subtext">${pf ? 'Price ' + (pf.fair_value / pf.total_balance * 100).toFixed(2) : 'Run risk to value loans'}</div></div>
            <div class="kpi-card"><div class="kpi-label">Weighted LTV / DSCR</div><div class="kpi-value">${pf ? pctOrDash(pf.weighted_ltv) + ' · ' + ratio(pf.weighted_dscr) : '—'}</div></div>
            <div class="kpi-card"><div class="kpi-label">Expected Loss</div><div class="kpi-value accent">${pf ? fmt.currency(pf.expected_loss_amount) : '—'}</div>
                <div class="kpi-subtext">${pf ? pctOrDash(pf.expected_loss, 2) + ' of balance, lifetime' : ''}</div></div>
        </div>

        <div class="section-header">
            <h2 class="section-title">Loans</h2>
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                <select class="form-input" id="loanFundFilter" style="width:auto">
                    <option value="">All funds</option>
                    ${funds.map(f => `<option value="${f.id}">${escapeHtmlAttr(f.name)}</option>`).join('')}
                </select>
                <a class="btn btn-secondary btn-sm" href="#/import">Import Tape</a>
                <a class="btn btn-secondary btn-sm" href="#/risk-runs">Risk Runs</a>
                <button class="btn btn-primary btn-sm" id="newLoanBtn" style="white-space:nowrap">${icons.plus} New Loan</button>
            </div>
        </div>
        ${!run && loans.length ? '<p class="form-help">No completed risk run yet. <a href="#/risk-runs" style="color:var(--accent)">Run one</a> to see LTV, DSCR, ratings and expected loss.</p>' : ''}
        <div id="loanTable"></div>

        ${run?.results?.maturity_wall?.length ? `
        <div class="chart-container">
            <div class="chart-title">Maturity Wall (balance at scheduled maturity)</div>
            <div class="chart-wrap" style="height:240px"><canvas id="maturityWall"></canvas></div>
        </div>` : ''}
    `;

    const renderTable = () => {
        const fund = document.getElementById('loanFundFilter').value;
        const rows = loans.filter(l => !fund || l.portfolio_id === fund);
        document.getElementById('loanTable').innerHTML = rows.length === 0 ? `
            <div class="empty-state"><h3>No loans</h3><p>Add a loan or import a loan tape (Excel) from the Import page.</p></div>` : `
            <div class="data-table-wrap"><table class="data-table">
                <thead><tr><th>Loan</th><th>Collateral</th><th>Fund</th><th style="text-align:right">Lien</th>
                    <th style="text-align:right">Balance</th><th style="text-align:right">Rate</th><th>Maturity</th>
                    <th style="text-align:right">LTV</th><th style="text-align:right">DSCR</th><th style="text-align:right">Debt Yield</th>
                    <th>Moody's</th><th>NAIC</th><th style="text-align:right">PD</th><th style="text-align:right">EL</th>
                    <th style="text-align:right">Price</th><th>Status</th></tr></thead>
                <tbody>${rows.map(l => {
                    const r = riskById[l.id] || {};
                    const p = propById[l.property_id];
                    const rate = l.rate_type === 'fixed' ? fmt.pct(l.coupon) : `S+${bps(l.spread)}`;
                    return `<tr style="cursor:pointer" onclick="location.hash='#/loan/${l.id}'">
                        <td class="tenant-name"><strong>${escapeHtmlAttr(l.external_id || l.name || l.id.slice(0, 8))}</strong>${r.error ? ' <span title="' + escapeHtmlAttr(r.error) + '" style="color:var(--red)">!</span>' : ''}</td>
                        <td>${escapeHtmlAttr(p?.name || '—')} <span style="color:var(--text-secondary);font-size:12px">${fmt.typeLabel(p?.property_type)}</span></td>
                        <td>${escapeHtmlAttr(fundById[l.portfolio_id]?.name || '—')}</td>
                        ${td(l.lien_position)}
                        ${td(fmt.currency(r.balance ?? l.reported_balance ?? l.original_balance))}
                        ${td(r.rate != null ? fmt.pct(r.rate) : rate)}
                        <td>${fmt.date(l.maturity_date)}</td>
                        ${td(pctOrDash(r.ltv))}${td(ratio(r.dscr))}${td(pctOrDash(r.debt_yield))}
                        <td>${ratingBadge(r.moodys_rating)}</td><td>${cmBadge(r.naic_cm)}</td>
                        ${td(pctOrDash(r.pd_cumulative))}${td(r.expected_loss != null ? fmt.pct(r.expected_loss) : '—')}
                        ${td(r.fair_value_price != null ? (r.fair_value_price * 100).toFixed(2) : '—')}
                        <td>${DELINQUENCY_LABELS[l.delinquency_status] || l.delinquency_status}</td>
                    </tr>`;
                }).join('')}</tbody>
            </table></div>`;
    };
    document.getElementById('loanFundFilter').onchange = renderTable;
    renderTable();
    document.getElementById('newLoanBtn').onclick = () => openLoanForm(null);

    if (run?.results?.maturity_wall?.length) {
        const wall = run.results.maturity_wall;
        new Chart(document.getElementById('maturityWall'), {
            type: 'bar',
            data: { labels: wall.map(w => w.year), datasets: [{ data: wall.map(w => w.balance), backgroundColor: '#0071e3', borderRadius: 4 }] },
            options: { maintainAspectRatio: false, scales: { y: { ticks: { callback: v => fmt.currency(v) } } },
                plugins: { tooltip: { callbacks: { label: c => fmt.currency(c.raw) } } } },
        });
    }
}


// ═══════════════════════════════════════════════════════════════
// LOAN DETAIL
// ═══════════════════════════════════════════════════════════════

async function loanView({ id }) {
    const loan = await api.get(`/loans/${id}`);
    const [property, run] = await Promise.all([api.get(`/properties/${loan.property_id}`), latestCompletedRun()]);
    // Show the schedule at the latest run's as-of date so it lines up with the risk figures
    const schedule = await api.get(`/loans/${id}/schedule?as_of_date=${run?.as_of_date || today()}`);
    const r = (run?.results?.loans || []).find(x => x.loan_id === id);
    const label = loan.external_id || loan.name || 'Loan';
    setBreadcrumb([{ label: 'Properties', href: '#/dashboard' }, { label: 'Loan Book', href: '#/loans' }, { label }]);

    const term = (label, value) => `<div><div class="kpi-label">${label}</div><div>${value}</div></div>`;
    const rateText = loan.rate_type === 'fixed' ? `${fmt.pct(loan.coupon, 3)} fixed`
        : `${escapeHtmlAttr(loan.index_name || 'Index')} + ${bps(loan.spread)}${loan.index_floor != null ? ', floor ' + fmt.pct(loan.index_floor) : ''}${loan.index_cap != null ? ', cap ' + fmt.pct(loan.index_cap) : ''}`;

    $app().innerHTML = `
        <div class="page-header" style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap">
            <div>
                <h1 class="page-title">${escapeHtmlAttr(label)} ${ratingBadge(r?.moodys_rating)} ${cmBadge(r?.naic_cm)}</h1>
                <p class="page-subtitle">Secured by <a href="#/property/${property.id}" style="color:var(--accent)">${escapeHtmlAttr(property.name)}</a>
                    · ${fmt.typeLabel(property.property_type)}${property.market ? ' · ' + escapeHtmlAttr(property.market) : ''}
                    · Lien ${loan.lien_position} · ${DELINQUENCY_LABELS[loan.delinquency_status]}</p>
            </div>
            <div style="display:flex;gap:8px">
                <button class="btn btn-secondary btn-sm" id="editLoanBtn">${icons.edit} Edit</button>
                <button class="btn btn-danger btn-sm" id="deleteLoanBtn">${icons.trash} Delete</button>
            </div>
        </div>

        <div class="kpi-row">
            <div class="kpi-card"><div class="kpi-label">Balance Today</div><div class="kpi-value">${fmt.currency(schedule.balance)}</div>
                <div class="kpi-subtext">${schedule.payments_made} payments made · ${fmt.currency(loan.original_balance)} original</div></div>
            <div class="kpi-card"><div class="kpi-label">Fair Value</div><div class="kpi-value">${r ? fmt.currency(r.fair_value) : '—'}</div>
                <div class="kpi-subtext">${r ? 'Price ' + (r.fair_value_price * 100).toFixed(2) + ' (expected cash flows)' : 'No risk run yet'}</div></div>
            <div class="kpi-card"><div class="kpi-label">LTV / DSCR</div><div class="kpi-value">${r ? pctOrDash(r.ltv) + ' · ' + ratio(r.dscr) : '—'}</div>
                <div class="kpi-subtext">${r ? `Collateral ${fmt.currency(r.collateral_value)} (${r.collateral_source === 'model' ? 'DCF' : 'tape, rolled forward'}) at ${fmt.dateFull(run.as_of_date)} · NOI ${fmt.currency(r.noi_year1)}` + (r.lien_position > 1 ? ' · cumulative through lien' : '') : ''}</div></div>
            <div class="kpi-card"><div class="kpi-label">PD (lifetime)</div><div class="kpi-value">${r ? pctOrDash(r.pd_cumulative) : '—'}</div>
                <div class="kpi-subtext">${r ? `Term ${pctOrDash(r.pd_term)} · maturity ${pctOrDash(r.pd_maturity)} · 1-yr ${pctOrDash(r.pd_one_year)}` : ''}</div></div>
            <div class="kpi-card"><div class="kpi-label">LGD / EL</div><div class="kpi-value accent">${r ? pctOrDash(r.lgd) + ' · ' + pctOrDash(r.expected_loss, 2) : '—'}</div>
                <div class="kpi-subtext">${r ? fmt.currency(r.expected_loss_amount) + ' expected loss · 99th ' + pctOrDash(r.loss_percentiles?.p99) : ''}</div></div>
        </div>
        ${r?.error ? `<div class="modal-warning" style="margin-bottom:16px">${escapeHtmlAttr(r.error)}</div>` : ''}
        ${[...schedule.warnings, ...(r?.warnings || [])].length ? `<div class="form-help" style="margin-bottom:16px">${[...new Set([...schedule.warnings, ...(r?.warnings || [])])].map(escapeHtmlAttr).join('<br>')}</div>` : ''}

        <div class="chart-container">
            <div class="chart-title">Terms</div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px">
                ${term('Originated', fmt.dateFull(loan.origination_date))}
                ${term('Maturity', fmt.dateFull(loan.maturity_date))}
                ${term('Rate', rateText)}
                ${term('Current Rate', fmt.pct(schedule.rate, 3))}
                ${term('Amortization', loan.amortization_months ? loan.amortization_months + ' mo' : 'Interest only')}
                ${term('IO Period', loan.io_months + ' mo')}
                ${term('Extensions', loan.extension_count ? `${loan.extension_count} × ${loan.extension_months} mo` : 'None')}
                ${term('Remaining Term', schedule.remaining_term_months + ' mo')}
                ${term('WAL', fmt.years(schedule.wal_years))}
                ${term('Sponsor', escapeHtmlAttr(loan.sponsor || '—') + (loan.recourse ? ' (recourse)' : ''))}
                ${term('Tape Balance', loan.reported_balance ? fmt.currency(loan.reported_balance) + ' at ' + fmt.dateFull(loan.balance_as_of_date) : '—')}
                ${term('Origination LTV', loan.origination_value ? fmt.pct(loan.original_balance / loan.origination_value, 1) : '—')}
            </div>
        </div>

        ${r?.value_fan ? `
        <div class="two-col">
            <div class="chart-container" style="margin-bottom:0">
                <div class="chart-title">Collateral Value vs Debt (5th–95th percentile)</div>
                <div class="chart-wrap"><canvas id="valueFan"></canvas></div>
            </div>
            <div class="chart-container" style="margin-bottom:0">
                <div class="chart-title">Cumulative Default Probability</div>
                <div class="chart-wrap"><canvas id="pdByYear"></canvas></div>
            </div>
        </div>` : ''}

        <div class="section-header"><h2 class="section-title">Remaining Schedule from ${fmt.dateFull(schedule.as_of_date)}</h2></div>
        <div class="data-table-wrap" style="max-height:420px;overflow:auto"><table class="data-table">
            <thead><tr><th>#</th><th>Payment Date</th><th style="text-align:right">Beginning</th><th style="text-align:right">Interest</th>
                <th style="text-align:right">Principal</th><th style="text-align:right">Balloon</th><th style="text-align:right">Ending</th></tr></thead>
            <tbody>${schedule.rows.length === 0 ? '<tr><td colspan="7">Past scheduled maturity at this date; no contractual payments remain.</td></tr>' : ''}${schedule.rows.map(row => `<tr>
                <td>${row.period}</td><td>${fmt.dateFull(row.payment_date)}</td>
                ${td(fmt.currencyExact(row.beginning_balance))}${td(fmt.currencyExact(row.interest))}
                ${td(fmt.currencyExact(row.principal))}${td(parseFloat(row.balloon) ? fmt.currencyExact(row.balloon) : '—')}
                ${td(fmt.currencyExact(row.ending_balance))}</tr>`).join('')}</tbody>
        </table></div>
        <p class="form-help">Floating-rate interest uses today's index from the default parameter set's forward curve.</p>

        <div class="section-header"><h2 class="section-title">Risk History</h2></div>
        <div id="loanRiskHistory"><p class="form-help">Loading…</p></div>

        <div class="section-header"><h2 class="section-title">Change History</h2></div>
        <div id="loanHistory"><p class="form-help">Loading…</p></div>
    `;
    api.get(`/loans/${id}/history`).then(h => renderLoanRiskHistory(h));
    api.get(`/audit-log?entity_type=mortgage_loans&entity_id=${id}`).then(entries => {
        const el = document.getElementById('loanHistory');
        if (el) el.innerHTML = renderAuditTable(entries);
    });

    document.getElementById('editLoanBtn').onclick = () => openLoanForm(loan, { onSaved: () => loanView({ id }) });
    document.getElementById('deleteLoanBtn').onclick = () => showDeleteConfirm('loan ' + label, async () => {
        await api.del(`/loans/${id}`);
        toast('Loan deleted', 'success');
        location.hash = '#/loans';
    });

    if (r?.value_fan) {
        const fan = r.value_fan;
        const labels = fan.month.map(m => `Yr ${m / 12}`);
        // Debt is cumulative through this lien; scale this loan's balance path by its share of that debt
        const debtScale = r.own_ltv ? r.ltv / r.own_ltv : 1;
        const debt = labels.map((_, i) => r.balance_by_year[i] != null ? r.balance_by_year[i] * debtScale : null);
        new Chart(document.getElementById('valueFan'), {
            type: 'line',
            data: {
                labels,
                datasets: [
                    { label: '95th', data: fan.p95, borderColor: 'transparent', backgroundColor: 'rgba(0,113,227,0.10)', fill: '+4', pointRadius: 0 },
                    { label: '75th', data: fan.p75, borderColor: 'transparent', backgroundColor: 'rgba(0,113,227,0.18)', fill: '+2', pointRadius: 0 },
                    { label: 'Median', data: fan.p50, borderColor: '#0071e3', borderWidth: 2, pointRadius: 0, fill: false },
                    { label: '25th', data: fan.p25, borderColor: 'transparent', pointRadius: 0, fill: false },
                    { label: '5th', data: fan.p5, borderColor: 'transparent', pointRadius: 0, fill: false },
                    { label: r.lien_position > 1 ? 'Debt through lien' : 'Loan balance', data: debt, borderColor: '#ff3b30', borderWidth: 2, borderDash: [6, 4], pointRadius: 0, fill: false },
                ],
            },
            options: { maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
                plugins: { legend: { display: true, labels: { filter: i => ['Median', 'Loan balance', 'Debt through lien'].includes(i.text) } },
                    tooltip: { callbacks: { label: c => `${c.dataset.label}: ${fmt.currency(c.raw)}` } } },
                scales: { y: { ticks: { callback: v => fmt.currency(v) } } } },
        });
        new Chart(document.getElementById('pdByYear'), {
            type: 'bar',
            data: { labels: r.pd_by_year.map((_, i) => `Yr ${i + 1}`), datasets: [{ data: r.pd_by_year, backgroundColor: '#ff9500', borderRadius: 4 }] },
            options: { maintainAspectRatio: false, scales: { y: { ticks: { callback: v => fmt.pct(v, 1) } } },
                plugins: { tooltip: { callbacks: { label: c => fmt.pct(c.raw, 1) } } } },
        });
    }
}


function renderLoanRiskHistory(h) {
    const el = document.getElementById('loanRiskHistory');
    if (!el) return;
    const runs = h.runs.filter(r => !r.error);
    el.innerHTML = `
        ${runs.length >= 2 ? `
        <div class="two-col">
            <div class="chart-container" style="margin-bottom:0">
                <div class="chart-title">Collateral Value and Balance by Run</div>
                <div class="chart-wrap" style="height:240px"><canvas id="histValue"></canvas></div>
            </div>
            <div class="chart-container" style="margin-bottom:0">
                <div class="chart-title">LTV, PD and EL by Run</div>
                <div class="chart-wrap" style="height:240px"><canvas id="histRisk"></canvas></div>
            </div>
        </div>` : ''}
        ${h.runs.length === 0 ? '<p class="form-help">Not in any completed risk run yet.</p>' : `
        <div class="data-table-wrap"><table class="data-table">
            <thead><tr><th>As of</th><th>Run</th><th style="text-align:right">Balance</th><th style="text-align:right">Collateral Value</th>
                <th>Value Source</th><th style="text-align:right">NOI</th><th style="text-align:right">LTV</th><th style="text-align:right">DSCR</th>
                <th>Moody's</th><th>NAIC</th><th style="text-align:right">PD</th><th style="text-align:right">LGD</th>
                <th style="text-align:right">EL</th><th style="text-align:right">Price</th><th>Params</th></tr></thead>
            <tbody>${[...h.runs].reverse().map(r => `<tr style="cursor:pointer" onclick="location.hash='#/risk-run/${r.run_id}'">
                <td>${fmt.dateFull(r.as_of_date)}</td><td>${escapeHtmlAttr(r.run_name || 'Run')}</td>
                ${r.error ? `<td colspan="13" style="color:var(--red)">${escapeHtmlAttr(r.error)}</td>` : `
                ${td(fmt.currency(r.balance))}${td(fmt.currency(r.collateral_value))}
                <td>${r.collateral_source === 'model' ? 'Model' + (r.valuation_name ? ': ' + escapeHtmlAttr(r.valuation_name) : '') : 'Tape'}</td>
                ${td(fmt.currency(r.noi_year1))}${td(pctOrDash(r.ltv))}${td(ratio(r.dscr))}
                <td>${ratingBadge(r.moodys_rating)}</td><td>${cmBadge(r.naic_cm)}</td>
                ${td(pctOrDash(r.pd_cumulative))}${td(pctOrDash(r.lgd))}${td(fmt.pct(r.expected_loss, 2))}
                ${td((r.fair_value_price * 100).toFixed(2))}<td>v${r.parameter_set_version ?? '?'}</td>`}</tr>`).join('')}</tbody>
        </table></div>`}

        <div class="section-header"><h3 class="section-title">Collateral Valuation History</h3></div>
        ${h.collateral_values.length === 0 ? '<p class="form-help">No valuation changes recorded for this property yet (recording started with the audit log).</p>' : `
        <div class="data-table-wrap"><table class="data-table">
            <thead><tr><th>Changed</th><th>Source</th><th style="text-align:right">Previous</th><th style="text-align:right">New Value</th><th style="text-align:right">Change</th></tr></thead>
            <tbody>${[...h.collateral_values].reverse().map(v => `<tr>
                <td>${new Date(v.changed_at + (v.changed_at.endsWith('Z') || v.changed_at.includes('+') ? '' : 'Z')).toLocaleString()}</td>
                <td>${v.source === 'model' ? 'Valuation: ' + escapeHtmlAttr(v.valuation_name || '—') : 'Loan tape value'}</td>
                ${td(v.previous_value != null ? fmt.currency(v.previous_value) : '—')}${td(fmt.currency(v.value))}
                ${td(v.previous_value ? fmt.pct(v.value / v.previous_value - 1, 1) : '—')}</tr>`).join('')}</tbody>
        </table></div>`}`;

    if (runs.length >= 2) {
        const labels = runs.map(r => fmt.date(r.as_of_date));
        new Chart(document.getElementById('histValue'), {
            type: 'line',
            data: { labels, datasets: [
                { label: 'Collateral value', data: runs.map(r => r.collateral_value), borderColor: '#0071e3', borderWidth: 2, tension: 0.2 },
                { label: 'Loan balance', data: runs.map(r => r.balance), borderColor: '#ff3b30', borderWidth: 2, borderDash: [6, 4], tension: 0.2 },
            ] },
            options: { maintainAspectRatio: false, plugins: { legend: { display: true },
                tooltip: { callbacks: { label: c => `${c.dataset.label}: ${fmt.currency(c.raw)}` } } },
                scales: { y: { ticks: { callback: v => fmt.currency(v) } } } },
        });
        new Chart(document.getElementById('histRisk'), {
            type: 'line',
            data: { labels, datasets: [
                { label: 'LTV', data: runs.map(r => r.ltv), borderColor: '#0071e3', borderWidth: 2, yAxisID: 'y' },
                { label: 'PD (lifetime)', data: runs.map(r => r.pd_cumulative), borderColor: '#ff9500', borderWidth: 2, yAxisID: 'y1' },
                { label: 'EL', data: runs.map(r => r.expected_loss), borderColor: '#ff3b30', borderWidth: 2, yAxisID: 'y1' },
            ] },
            options: { maintainAspectRatio: false, plugins: { legend: { display: true },
                tooltip: { callbacks: { label: c => `${c.dataset.label}: ${fmt.pct(c.raw, 2)}` } } },
                scales: { y: { position: 'left', ticks: { callback: v => fmt.pct(v, 0) } },
                    y1: { position: 'right', grid: { drawOnChartArea: false }, ticks: { callback: v => fmt.pct(v, 1) } } } },
        });
    }
}


// ═══════════════════════════════════════════════════════════════
// PROPERTY PAGE: LOANS TAB (called from propertyView in app.js)
// ═══════════════════════════════════════════════════════════════

async function loadPropertyLoans(property) {
    const el = document.getElementById('tab-loans');
    if (!el) return;
    const loans = await api.get(`/loans?property_id=${property.id}`);
    el.innerHTML = `
        <div class="section-header">
            <h2 class="section-title">Mortgage Loans Secured by This Property</h2>
            <button class="btn btn-primary btn-sm" id="propNewLoanBtn">${icons.plus} New Loan</button>
        </div>
        ${loans.length === 0 ? '<div class="empty-state"><h3>No loans</h3><p>Loans the lender holds on this property appear here.</p></div>' : `
        <div class="data-table-wrap"><table class="data-table">
            <thead><tr><th>Loan</th><th style="text-align:right">Lien</th><th style="text-align:right">Original</th><th style="text-align:right">Tape Balance</th>
                <th>Rate</th><th>Originated</th><th>Maturity</th><th>Status</th></tr></thead>
            <tbody>${loans.map(l => `<tr style="cursor:pointer" onclick="location.hash='#/loan/${l.id}'">
                <td class="tenant-name"><strong>${escapeHtmlAttr(l.external_id || l.name || l.id.slice(0, 8))}</strong></td>
                ${td(l.lien_position)}${td(fmt.currency(l.original_balance))}${td(l.reported_balance ? fmt.currency(l.reported_balance) : '—')}
                <td>${l.rate_type === 'fixed' ? fmt.pct(l.coupon, 3) : `${escapeHtmlAttr(l.index_name || 'Index')} + ${bps(l.spread)}`}</td>
                <td>${fmt.date(l.origination_date)}</td><td>${fmt.date(l.maturity_date)}</td>
                <td>${DELINQUENCY_LABELS[l.delinquency_status] || l.delinquency_status}</td></tr>`).join('')}</tbody>
        </table></div>`}`;
    document.getElementById('propNewLoanBtn').onclick = () =>
        openLoanForm(null, { propertyId: property.id, onSaved: () => loadPropertyLoans(property) });
}


// ═══════════════════════════════════════════════════════════════
// RISK RUNS
// ═══════════════════════════════════════════════════════════════

async function riskRunsView() {
    setBreadcrumb([{ label: 'Properties', href: '#/dashboard' }, { label: 'Loan Book', href: '#/loans' }, { label: 'Risk Runs' }]);
    const [runs, funds, sets] = await Promise.all([api.get('/loan-risk-runs'), api.get('/portfolios'), api.get('/risk-parameter-sets')]);
    const setById = Object.fromEntries(sets.map(s => [s.id, s]));
    const fundById = Object.fromEntries(funds.map(f => [f.id, f]));

    $app().innerHTML = `
        <div class="page-header">
            <h1 class="page-title">Loan Risk Runs</h1>
            <p class="page-subtitle">Monte Carlo PD, LGD and expected loss, Moody's and NAIC ratings and fair value at an as-of date</p>
        </div>
        <div class="chart-container">
            <div class="chart-title">New Run</div>
            <div class="form-row">
                <div class="form-group"><label class="form-label">Name</label><input class="form-input" id="runName" placeholder="e.g. Q3 2025"></div>
                <div class="form-group"><label class="form-label">As-of Date</label><input class="form-input" type="date" id="runAsOf" value="${today()}"></div>
                <div class="form-group"><label class="form-label">Loans</label>
                    <select class="form-input" id="runFund"><option value="">Whole loan book</option>
                        ${funds.map(f => `<option value="${f.id}">${escapeHtmlAttr(f.name)}</option>`).join('')}</select></div>
                <div class="form-group"><label class="form-label">Parameters</label>
                    <select class="form-input" id="runSet">${sets.map(s => `<option value="${s.id}" ${s.is_default ? 'selected' : ''}>${escapeHtmlAttr(s.name)} (v${s.version}, ${num(s.params.num_paths)} paths)</option>`).join('')}</select></div>
            </div>
            <button class="btn btn-primary" id="runBtn">Run Simulation</button>
            <a href="#/admin" style="color:var(--accent);margin-left:12px">Edit parameters</a>
        </div>

        <div class="section-header"><h2 class="section-title">History</h2></div>
        ${runs.length === 0 ? '<div class="empty-state"><h3>No runs yet</h3></div>' : `
        <div class="data-table-wrap"><table class="data-table">
            <thead><tr><th>Run</th><th>As of</th><th>Loans</th><th>Parameters</th><th style="text-align:right">Count</th>
                <th style="text-align:right">Balance</th><th style="text-align:right">EL</th><th>Status</th><th>Created</th><th></th></tr></thead>
            <tbody>${runs.map(r => `<tr style="cursor:pointer" data-run="${r.id}">
                <td class="tenant-name"><strong>${escapeHtmlAttr(r.name || 'Run')}</strong></td>
                <td>${fmt.dateFull(r.as_of_date)}</td>
                <td>${escapeHtmlAttr(r.portfolio_id ? (fundById[r.portfolio_id]?.name || 'Fund') : 'All')}</td>
                <td>${escapeHtmlAttr(setById[r.parameter_set_id]?.name || '—')} v${r.parameter_set_version ?? '?'}</td>
                ${td(r.loan_count ?? '—')}${td(r.total_balance != null ? fmt.currency(r.total_balance) : '—')}
                ${td(r.expected_loss != null ? fmt.pct(r.expected_loss) : '—')}
                <td><span class="status-badge status-${r.status === 'completed' ? 'completed' : r.status === 'failed' ? 'failed' : 'running'}">${r.status}${r.status === 'running' ? ' ' + Math.round(r.progress * 100) + '%' : ''}</span></td>
                <td>${new Date(r.created_at).toLocaleString()}</td>
                <td><button class="btn-icon" data-del="${r.id}" title="Delete">${icons.trash}</button></td>
            </tr>`).join('')}</tbody>
        </table></div>`}
    `;

    document.querySelectorAll('tr[data-run]').forEach(tr => tr.onclick = (e) => {
        if (e.target.closest('[data-del]')) return;
        location.hash = `#/risk-run/${tr.dataset.run}`;
    });
    document.querySelectorAll('[data-del]').forEach(b => b.onclick = () => showDeleteConfirm('run', async () => {
        await api.del(`/loan-risk-runs/${b.dataset.del}`);
        riskRunsView();
    }));
    document.getElementById('runBtn').onclick = async () => {
        const btn = document.getElementById('runBtn');
        btn.disabled = true;
        try {
            const run = await api.post('/loan-risk-runs', {
                name: document.getElementById('runName').value || null,
                as_of_date: document.getElementById('runAsOf').value,
                portfolio_id: document.getElementById('runFund').value || null,
                parameter_set_id: document.getElementById('runSet').value || null,
            });
            location.hash = `#/risk-run/${run.id}`;
        } catch (err) {
            toast('Error: ' + err.message, 'error');
            btn.disabled = false;
        }
    };
}

let riskRunPoll = null;

async function riskRunView({ id }) {
    clearTimeout(riskRunPoll);
    const run = await api.get(`/loan-risk-runs/${id}`);
    setBreadcrumb([{ label: 'Properties', href: '#/dashboard' }, { label: 'Risk Runs', href: '#/risk-runs' }, { label: run.name || 'Run' }]);

    if (run.status === 'queued' || run.status === 'running') {
        $app().innerHTML = `
            <div class="page-header"><h1 class="page-title">${escapeHtmlAttr(run.name || 'Risk Run')}</h1>
                <p class="page-subtitle">As of ${fmt.dateFull(run.as_of_date)} · ${num(run.params.num_paths)} paths</p></div>
            <div class="chart-container">
                <div class="chart-title">${run.status === 'queued' ? 'Queued' : 'Simulating'}… ${Math.round(run.progress * 100)}%</div>
                <div style="height:8px;background:var(--bg-secondary);border-radius:4px;overflow:hidden">
                    <div style="height:100%;width:${Math.max(2, run.progress * 100)}%;background:var(--accent);transition:width .4s"></div></div>
                <p class="form-help" style="margin-top:12px">Projecting collateral, rolling loans forward from origination, then simulating paths.</p>
            </div>`;
        riskRunPoll = setTimeout(() => {
            if (location.hash === `#/risk-run/${id}`) riskRunView({ id });
        }, 1500);
        return;
    }
    if (run.status === 'failed') {
        $app().innerHTML = `<div class="empty-state"><h3>Run failed</h3><p>${escapeHtmlAttr(run.error_message || '')}</p>
            <br><a href="#/risk-runs" class="btn btn-secondary">Back to runs</a></div>`;
        return;
    }

    const res = run.results;
    const pf = res.portfolio;
    const ok = res.loans.filter(l => !l.error);
    const failed = res.loans.filter(l => l.error);
    const top = [...ok].sort((a, b) => b.expected_loss_amount - a.expected_loss_amount).slice(0, 10);
    const migrated = ok.filter(l => l.previous_moodys_rating);

    const bucketTable = (buckets, title, extra) => `
        <div class="chart-container">
            <div class="chart-title">${title}</div>
            <div class="data-table-wrap" style="box-shadow:none"><table class="data-table">
                <thead><tr><th>Bucket</th><th style="text-align:right">Loans</th><th style="text-align:right">Balance</th><th style="text-align:right">Share</th>
                    <th style="text-align:right">LTV</th><th style="text-align:right">DSCR</th><th style="text-align:right">PD</th><th style="text-align:right">LGD</th>
                    <th style="text-align:right">EL %</th><th style="text-align:right">EL $</th>${extra ? '<th style="text-align:right">RBC Factor</th><th style="text-align:right">RBC Charge</th>' : ''}</tr></thead>
                <tbody>${buckets.filter(b => b.loan_count).map(b => `<tr>
                    <td>${extra ? cmBadge(b.bucket) : ratingBadge(b.bucket)}</td>${td(b.loan_count)}${td(fmt.currency(b.balance))}${td(fmt.pct(b.share_of_balance, 1))}
                    ${td(pctOrDash(b.ltv))}${td(ratio(b.dscr))}${td(pctOrDash(b.pd))}${td(pctOrDash(b.lgd))}
                    ${td(fmt.pct(b.expected_loss, 2))}${td(fmt.currency(b.expected_loss_amount))}
                    ${extra ? td(pctOrDash(b.rbc_factor, 2)) + td(fmt.currency(b.balance * (b.rbc_factor || 0))) : ''}</tr>`).join('')}
                    <tr style="font-weight:600"><td>Total</td>${td(ok.length)}${td(fmt.currency(pf.total_balance))}${td('100%')}
                        ${td(pctOrDash(pf.weighted_ltv))}${td(ratio(pf.weighted_dscr))}${td(pctOrDash(pf.weighted_pd))}${td(pctOrDash(pf.weighted_lgd))}
                        ${td(fmt.pct(pf.expected_loss, 2))}${td(fmt.currency(pf.expected_loss_amount))}
                        ${extra ? td('') + td(fmt.currency(buckets.reduce((s, b) => s + b.balance * (b.rbc_factor || 0), 0))) : ''}</tr>
                </tbody></table></div>
        </div>`;

    // Migration matrix: previous rating rows x current rating columns (rating letters only, to keep it compact)
    const grade = r => r ? r.replace(/[123]$/, '') : null;
    const grades = ['Aaa', 'Aa', 'A', 'Baa', 'Ba', 'B', 'Caa', 'Ca'];
    const matrix = {};
    migrated.forEach(l => {
        const k = grade(l.previous_moodys_rating) + '|' + grade(l.moodys_rating);
        matrix[k] = (matrix[k] || 0) + 1;
    });
    const upgrades = migrated.filter(l => RATING_ORDER.indexOf(l.moodys_rating) < RATING_ORDER.indexOf(l.previous_moodys_rating)).length;
    const downgrades = migrated.filter(l => RATING_ORDER.indexOf(l.moodys_rating) > RATING_ORDER.indexOf(l.previous_moodys_rating)).length;

    $app().innerHTML = `
        <div class="page-header" style="display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap">
            <div><h1 class="page-title">${escapeHtmlAttr(run.name || 'Risk Run')}</h1>
            <p class="page-subtitle">As of ${fmt.dateFull(run.as_of_date)} · ${res.loan_count} loans · ${num(run.params.num_paths)} paths · seed ${run.params.seed}
                · parameter set v${run.parameter_set_version}</p></div>
            <div style="display:flex;gap:8px">
                <button class="btn btn-secondary btn-sm" id="exportInputsBtn" title="Loan terms, collateral NOI paths and values as used by this run">Download Inputs</button>
                <button class="btn btn-secondary btn-sm" id="exportRunBtn">Export CSV</button>
            </div>
        </div>
        <div class="kpi-row">
            <div class="kpi-card"><div class="kpi-label">Balance</div><div class="kpi-value">${fmt.currency(pf.total_balance)}</div></div>
            <div class="kpi-card"><div class="kpi-label">Fair Value</div><div class="kpi-value">${fmt.currency(pf.fair_value)}</div>
                <div class="kpi-subtext">Price ${(pf.fair_value / pf.total_balance * 100).toFixed(2)}</div></div>
            <div class="kpi-card"><div class="kpi-label">Expected Loss</div><div class="kpi-value accent">${fmt.currency(pf.expected_loss_amount)}</div>
                <div class="kpi-subtext">${fmt.pct(pf.expected_loss, 2)} of balance, lifetime</div></div>
            <div class="kpi-card"><div class="kpi-label">Loss VaR 99% / 99.9%</div><div class="kpi-value">${fmt.currency(pf.var.p99)}</div>
                <div class="kpi-subtext">99.9%: ${fmt.currency(pf.var.p999)} · ES99 ${fmt.currency(pf.expected_shortfall_99)}</div></div>
            <div class="kpi-card"><div class="kpi-label">Weighted PD / LGD</div><div class="kpi-value">${pctOrDash(pf.weighted_pd)} · ${pctOrDash(pf.weighted_lgd)}</div></div>
        </div>
        ${failed.length ? `<div class="modal-warning" style="margin-bottom:16px">${failed.length} loan(s) not simulated: ${failed.map(l => escapeHtmlAttr((l.external_id || l.loan_id.slice(0, 8)) + ' — ' + l.error)).join('<br>')}</div>` : ''}

        ${bucketTable(res.moodys_buckets, "Expected Loss by Moody's Rating (EL vs idealized EL at the loan's WAL)", false)}
        ${bucketTable(res.naic_buckets, 'NAIC CM Categories (DSC × LTV matrix)', true)}

        <div class="two-col">
            <div class="chart-container" style="margin-bottom:0">
                <div class="chart-title">Portfolio Loss Distribution</div>
                <div class="chart-wrap"><canvas id="lossHist"></canvas></div>
            </div>
            <div class="chart-container" style="margin-bottom:0">
                <div class="chart-title">Rating Migration vs Previous Run</div>
                ${migrated.length === 0 ? '<p class="form-help">No earlier completed run with these loans.</p>' : `
                <p class="form-help">${upgrades} upgraded · ${downgrades} downgraded · ${migrated.length - upgrades - downgrades} unchanged (notch level)</p>
                <div class="data-table-wrap" style="box-shadow:none"><table class="data-table">
                    <thead><tr><th>From \\ To</th>${grades.map(g => `<th style="text-align:right">${g}</th>`).join('')}</tr></thead>
                    <tbody>${grades.map(f => `<tr><td><strong>${f}</strong></td>${grades.map(t => {
                        const n = matrix[f + '|' + t] || 0;
                        const style = n ? (f === t ? 'font-weight:600' : grades.indexOf(t) > grades.indexOf(f) ? 'color:var(--red);font-weight:600' : 'color:var(--green);font-weight:600') : 'color:var(--text-tertiary)';
                        return `<td style="text-align:right;${style}">${n || '·'}</td>`;
                    }).join('')}</tr>`).join('')}</tbody>
                </table></div>`}
            </div>
        </div>

        <div class="section-header"><h2 class="section-title">Top 10 Loans by Expected Loss</h2></div>
        ${runLoanTable(top)}
        <div class="section-header"><h2 class="section-title">All Loans</h2></div>
        ${runLoanTable([...ok].sort((a, b) => (a.external_id || '').localeCompare(b.external_id || '')))}
        <details style="margin-top:16px"><summary class="form-help" style="cursor:pointer">Parameters used</summary>
            <pre style="font-size:12px;background:var(--bg-secondary);padding:12px;border-radius:8px;overflow:auto">${escapeHtmlAttr(JSON.stringify(run.params, null, 2))}</pre></details>
    `;

    const h = pf.histogram;
    if (h.counts.length) {
        const mids = h.counts.map((_, i) => (h.edges[i] + h.edges[i + 1]) / 2);
        new Chart(document.getElementById('lossHist'), {
            type: 'bar',
            data: { labels: mids.map(m => fmt.currency(m)), datasets: [{ data: h.counts.map(c => c / run.params.num_paths), backgroundColor: mids.map(m => m >= pf.var.p99 ? '#ff3b30' : '#0071e3'), borderRadius: 2 }] },
            options: { maintainAspectRatio: false, scales: { y: { ticks: { callback: v => fmt.pct(v, 0) } } },
                plugins: { tooltip: { callbacks: { label: c => fmt.pct(c.raw, 1) + ' of paths' } } } },
        });
    }

    document.getElementById('exportInputsBtn').onclick = async () => {
        try {
            const inputs = await api.get(`/loan-risk-runs/${id}/inputs`);
            const a = document.createElement('a');
            a.href = URL.createObjectURL(new Blob([JSON.stringify(inputs, null, 2)], { type: 'application/json' }));
            a.download = `loan-risk-inputs-${run.as_of_date}.json`;
            a.click();
            URL.revokeObjectURL(a.href);
        } catch (err) {
            toast('No recorded inputs for this run (runs before input logging was added)', 'error');
        }
    };
    document.getElementById('exportRunBtn').onclick = () => {
        const cols = ['external_id', 'property_name', 'property_type', 'lien_position', 'balance', 'rate', 'maturity_date', 'collateral_value',
            'noi_year1', 'ltv', 'dscr', 'debt_yield', 'naic_dsc', 'naic_ltv', 'naic_cm', 'moodys_rating', 'previous_moodys_rating', 'wal_years',
            'pd_cumulative', 'pd_one_year', 'pd_term', 'pd_maturity', 'lgd', 'expected_loss', 'expected_loss_amount', 'fair_value',
            'fair_value_price', 'collateral_source', 'error'];
        const esc = v => v == null ? '' : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v);
        const csv = [cols.join(','), ...res.loans.map(l => cols.map(c => esc(l[c])).join(','))].join('\n');
        const a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
        a.download = `loan-risk-${run.as_of_date}.csv`;
        a.click();
        URL.revokeObjectURL(a.href);
    };
}

function runLoanTable(rows) {
    return `<div class="data-table-wrap"><table class="data-table">
        <thead><tr><th>Loan</th><th>Collateral</th><th style="text-align:right">Lien</th><th style="text-align:right">Balance</th>
            <th style="text-align:right">LTV</th><th style="text-align:right">DSCR</th><th style="text-align:right">WAL</th>
            <th>Moody's</th><th>Prev</th><th>NAIC</th><th style="text-align:right">PD</th><th style="text-align:right">LGD</th>
            <th style="text-align:right">EL %</th><th style="text-align:right">EL $</th><th style="text-align:right">Price</th><th>Source</th></tr></thead>
        <tbody>${rows.map(l => `<tr style="cursor:pointer" onclick="location.hash='#/loan/${l.loan_id}'">
            <td class="tenant-name"><strong>${escapeHtmlAttr(l.external_id || l.loan_id.slice(0, 8))}</strong></td>
            <td>${escapeHtmlAttr(l.property_name)}</td>${td(l.lien_position)}${td(fmt.currency(l.balance))}
            ${td(pctOrDash(l.ltv))}${td(ratio(l.dscr))}${td(l.wal_years.toFixed(1))}
            <td>${ratingBadge(l.moodys_rating)}</td><td>${l.previous_moodys_rating || '—'}</td><td>${cmBadge(l.naic_cm)}</td>
            ${td(pctOrDash(l.pd_cumulative))}${td(pctOrDash(l.lgd))}${td(fmt.pct(l.expected_loss, 2))}${td(fmt.currency(l.expected_loss_amount))}
            ${td((l.fair_value_price * 100).toFixed(2))}<td>${l.collateral_source === 'model' ? 'Model' : 'Tape'}</td></tr>`).join('')}</tbody>
    </table></div>`;
}


// ═══════════════════════════════════════════════════════════════
// ADMIN: RISK PARAMETER SETS AND RATING TABLES
// ═══════════════════════════════════════════════════════════════

// [key, label, kind]; kind: pct (fraction shown as %), int, num, bool, select:<a|b>
const RISK_PARAM_GROUPS = [
    { label: 'Simulation', fields: [['num_paths', 'Paths (loan runs)', 'int'], ['seed', 'Random Seed', 'int']] },
    { label: 'Shared Shocks', help: 'Inflation, SOFR and the 10-year Treasury are economy-wide. Leasing drivers are a market shock (property type + market) plus a property-specific shock; cap rates are a property-type shock plus a property-specific one. The national share applies to each market / property-type shock.',
      fields: [['global_share', 'National Share of Market Shock', 'pct'], ['market_share', 'Market Share of Leasing Shock', 'pct'],
          ['cap_rate_type_share', 'Property-Type Share of Cap Rate Shock', 'pct'], ['credit_loss_vacancy_sensitivity', 'Credit Loss per Point of Vacancy', 'num'],
          ['cap_rate_floor', 'Cap Rate Floor', 'pct']] },
    { label: 'Recessions', help: 'An economy-wide downturn regime. Each year a recession starts with the start probability; an ongoing one continues with the continue probability. In a recession year each driver gets severity × its recession shock (see the driver table). The shock is centred on the long-run share of recession years, so the average path stays the base case and only the downside gets fatter. Rent level reversion is the share of the accumulated market rent shortfall (or excess) that closes each year, so rents recover after a downturn.',
      fields: [['recession_probability', 'Start Probability (per year)', 'pct'], ['recession_persistence', 'Continue Probability', 'pct'],
          ['recession_severity', 'Severity Multiplier', 'num'], ['rent_level_reversion', 'Rent Level Reversion (per year)', 'pct']] },
    { label: 'Tape-Only Collateral', help: 'Properties without a full model: leases are assumed staggered over the average lease term, so market rent and vacancy reach revenue as leases roll; expenses move with inflation.',
      fields: [['tape_expense_ratio', 'Expense Ratio', 'pct'], ['tape_base_vacancy', 'Base Vacancy', 'pct'],
          ['tape_avg_lease_years', 'Average Lease Term (years)', 'num']] },
    { label: 'Rates', help: 'With live rates on, each run replaces the curves below with today\'s SOFR forward and 10-year Treasury curves from FRED and saves them with the run. Turn it off to run with the saved curves, e.g. a rate scenario.',
      fields: [['use_live_rates', 'Use Live FRED Rates at Run Time', 'bool'], ['index_curve_as_of', 'Curves As Of', 'date']] },
    { label: 'Term Default', help: 'Each quarter a path defaults with the quarterly share of annual PD = 1 ÷ (1 + e^−(intercept + DSCR coef × ln DSCR + LTV coef × LTV)), using that path\'s trailing-12-month DSCR and current LTV (Moody\'s CMM approach). DSCR coefficient should be negative, LTV coefficient positive.',
      fields: [['default_intercept', 'Intercept', 'num'], ['default_dscr_coef', 'ln(DSCR) Coefficient', 'num'],
          ['default_ltv_coef', 'LTV Coefficient', 'num']] },
    { label: 'Maturity / Refinance', help: 'At maturity the loan refinances if the largest new loan (LTV, DSCR at the refinance rate, debt yield) covers it; the sponsor can pay down a shortfall up to the paydown limit; otherwise it extends (if an option remains and its tests pass), the borrower sells if the sale net of costs repays all the debt, or it defaults. Fixed-rate loans refinance at the 10-year Treasury + spread, floating-rate loans at SOFR + spread.',
      fields: [['refi_max_ltv', 'Refi Max LTV', 'pct'], ['refi_min_dscr', 'Refi Min DSCR', 'num'], ['refi_min_debt_yield', 'Refi Min Debt Yield', 'pct'],
          ['refi_spread_fixed', 'Fixed Refi Spread over 10-Yr', 'pct'], ['refi_spread', 'Floating Refi Spread over SOFR', 'pct'],
          ['refi_amortization_months', 'Refi Amortization (months)', 'int'], ['max_equity_paydown_pct', 'Max Equity Paydown (% of value)', 'pct'],
          ['sale_cost_pct', 'Sale Costs if Borrower Sells', 'pct'],
          ['extension_min_dscr', 'Extension Min DSCR', 'num'], ['extension_max_ltv', 'Extension Max LTV', 'pct']] },
    { label: 'Loss Given Default', fields: [['liquidation_lag_months', 'Liquidation Lag (months)', 'int'], ['liquidation_cost_pct', 'Liquidation Costs', 'pct'],
          ['workout_cost_pct', 'Workout Costs (% of balance)', 'pct'], ['workout_carry_pct', 'Carrying Costs (% of value per year of lag)', 'pct'],
          ['workout_noi_to_lender_pct', 'Workout NOI to Lender', 'pct'], ['advance_interest', 'Lender Advances Interest', 'bool']] },
    { label: 'Fair Value', fields: [['fair_value_spread', 'Discount Spread over Index', 'pct']] },
];

// Monte Carlo drivers (order matches the engine's DRIVERS): [key, label, how the deviation applies]
const MC_DRIVERS = [
    ['rent_growth', 'Market Rent Growth', '± points of growth'],
    ['vacancy', 'General Vacancy', '± points'],
    ['renewal', 'Renewal Probability', '± points'],
    ['downtime', 'Downtime', '% change'],
    ['concessions', 'TI & Free Rent', '% change'],
    ['inflation', 'Expense / CPI Inflation', '± points'],
    ['cap_rate', 'Cap Rates', '± points'],
    ['sofr', 'SOFR', '± points'],
    ['treasury_10y', '10-Year Treasury', '± points'],
];
const mcDriverLabel = k => (MC_DRIVERS.find(d => d[0] === k) || [k, k])[1];

function curveText(curve) {
    return curve.map(([y, r]) => `${y}, ${+(r * 100).toFixed(4)}`).join('\n');
}

function parseCurve(id, name) {
    const curve = document.getElementById(id).value.split('\n').map(l => l.trim()).filter(Boolean).map(l => {
        const [y, r] = l.split(/[,\s\t]+/).map(parseFloat);
        if (isNaN(y) || isNaN(r)) throw new Error(`Bad ${name} line: "${l}"`);
        return [y, +(r / 100).toFixed(8)];
    }).sort((a, b) => a[0] - b[0]);
    if (!curve.length) throw new Error(`The ${name} needs at least one point`);
    return curve;
}

function renderDriverEditor(p) {
    const head = MC_DRIVERS.map(([, l]) => `<th style="text-align:right;font-size:11px;white-space:normal;min-width:64px">${l}</th>`).join('');
    return `
        <h3 class="section-title" style="font-size:1rem;margin:20px 0 4px">Scenario Drivers</h3>
        <p class="form-help" style="margin-bottom:8px">Each driver moves year by year around the property's own assumption: deviation = persistence × last year's deviation + volatility × shock. Volatility is the yearly shock size; persistence (0–1) is how much of last year's deviation carries over. Every path is a full property valuation with that path's assumptions.</p>
        <div class="data-table-wrap" style="box-shadow:none"><table class="data-table" style="font-size:12px">
            <thead><tr><th>Driver</th><th>Applied as</th><th style="text-align:right">Volatility (%)</th><th style="text-align:right">Persistence</th><th style="text-align:right">Recession Shock (%)</th></tr></thead>
            <tbody>${MC_DRIVERS.map(([k, l, unit]) => `<tr><td><strong>${l}</strong></td><td style="color:var(--text-secondary)">${unit}</td>
                <td style="text-align:right"><input class="form-input" type="number" step="any" id="rp_vol_${k}" value="${+((p.driver_volatility[k] ?? 0) * 100).toFixed(4)}" style="width:90px;text-align:right"></td>
                <td style="text-align:right"><input class="form-input" type="number" step="0.05" min="0" max="1" id="rp_phi_${k}" value="${p.driver_persistence[k] ?? 0}" style="width:80px;text-align:right"></td>
                <td style="text-align:right"><input class="form-input" type="number" step="any" id="rp_rec_${k}" value="${+((p.recession_shock[k] ?? 0) * 100).toFixed(4)}" style="width:90px;text-align:right"></td></tr>`).join('')}</tbody>
        </table></div>
        <h3 class="section-title" style="font-size:1rem;margin:20px 0 4px">Driver Correlation</h3>
        <p class="form-help" style="margin-bottom:8px">Correlation of the yearly shocks. Editing a cell updates its mirror. The matrix must be internally consistent (positive definite); saving rejects contradictory values.</p>
        <div class="data-table-wrap" style="box-shadow:none;overflow-x:auto"><table class="data-table" style="font-size:12px" id="rpCorr">
            <thead><tr><th></th>${head}</tr></thead>
            <tbody>${MC_DRIVERS.map(([, l], i) => `<tr><td style="white-space:nowrap"><strong>${l}</strong></td>${MC_DRIVERS.map((_, j) => `<td style="text-align:right;padding:2px">
                <input class="form-input" type="number" step="0.05" min="-1" max="1" data-corr="${i},${j}" value="${p.driver_correlation[i][j]}" ${i === j ? 'disabled' : ''}
                    style="width:64px;text-align:right;padding:4px">`).join('')}</td></tr>`).join('')}</tbody>
        </table></div>`;
}

function paramInput(key, label, kind, value) {
    const id = `rp_${key}`;
    let input;
    if (kind === 'bool') {
        input = `<label class="form-checkbox-row"><input type="checkbox" id="${id}" ${value ? 'checked' : ''}> ${label}</label>`;
        return `<div class="form-group">${input}</div>`;
    }
    if (kind.startsWith('select:')) {
        input = `<select class="form-input" id="${id}">${kind.slice(7).split('|').map(o => `<option value="${o}" ${o === value ? 'selected' : ''}>${fmt.typeLabel(o)}</option>`).join('')}</select>`;
    } else if (kind === 'date') {
        input = `<input class="form-input" type="date" id="${id}" value="${value || ''}">`;
    } else {
        const shown = kind === 'pct' ? +(value * 100).toFixed(4) : value;
        input = `<input class="form-input" type="number" step="any" id="${id}" value="${shown ?? ''}">`;
    }
    return `<div class="form-group"><label class="form-label">${label}${kind === 'pct' ? ' (%)' : ''}</label>${input}</div>`;
}

function readParamInput(kind, el) {
    if (kind === 'bool') return el.checked;
    if (kind.startsWith('select:')) return el.value;
    if (kind === 'date') return el.value || null;
    const n = parseFloat(el.value);
    if (isNaN(n)) return undefined;
    return kind === 'pct' ? +(n / 100).toFixed(8) : kind === 'int' ? Math.round(n) : n;
}

async function adminView({ setId } = {}) {
    setBreadcrumb([{ label: 'Properties', href: '#/dashboard' }, { label: 'Risk Admin' }]);
    const [sets, ref, recent] = await Promise.all([
        api.get('/risk-parameter-sets'), api.get('/risk-parameter-sets/reference'), api.get('/audit-log?limit=100'),
    ]);
    const current = sets.find(s => s.id === setId) || sets.find(s => s.is_default) || sets[0];
    const versions = await api.get(`/risk-parameter-sets/${current.id}/versions`);
    // Keys that differ from the previous version, for the version table
    const changedKeys = (v, i) => {
        const prev = versions[i + 1];
        if (!prev) return 'Initial version';
        const keys = Object.keys(v.params).filter(k => JSON.stringify(v.params[k]) !== JSON.stringify(prev.params[k]));
        return keys.length ? keys.map(k => `${k}: ${auditValue(prev.params[k])} → ${auditValue(v.params[k])}`).join('<br>') : 'No parameter changes';
    };
    // Sets saved before a setting existed use the engine default for it
    const p = { ...ref.defaults, ...current.params };
    const curveStale = !p.index_curve_as_of;

    $app().innerHTML = `
        <div class="page-header">
            <h1 class="page-title">Risk Admin</h1>
            <p class="page-subtitle">Default Monte Carlo parameters for loan risk runs, and the rating tables used</p>
        </div>

        <div class="section-header">
            <h2 class="section-title">Parameter Sets</h2>
            <button class="btn btn-secondary btn-sm" id="newSetBtn" style="white-space:nowrap" title="Copies the selected set">${icons.plus} Copy Set</button>
        </div>
        <div class="data-table-wrap"><table class="data-table">
            <thead><tr><th>Name</th><th style="text-align:right">Version</th><th>Default</th><th>Index Curve As Of</th><th>Updated</th><th></th></tr></thead>
            <tbody>${sets.map(s => `<tr style="cursor:pointer${s.id === current.id ? ';background:var(--blue-bg)' : ''}" data-set="${s.id}">
                <td class="tenant-name"><strong>${escapeHtmlAttr(s.name)}</strong>${s.comment ? ` <span style="color:var(--text-secondary);font-size:12px">${escapeHtmlAttr(s.comment)}</span>` : ''}</td>
                ${td('v' + s.version)}<td>${s.is_default ? '<span class="status-badge status-completed">Default</span>' : ''}</td>
                <td>${s.params.index_curve_as_of ? fmt.dateFull(s.params.index_curve_as_of) : '<span style="color:var(--red)">Placeholder</span>'}</td>
                <td>${new Date(s.updated_at).toLocaleString()}</td>
                <td style="white-space:nowrap">${s.is_default ? '' : `<button class="btn btn-secondary btn-sm" data-default="${s.id}">Make Default</button>
                    <button class="btn-icon" data-delset="${s.id}" title="Delete">${icons.trash}</button>`}</td></tr>`).join('')}</tbody>
        </table></div>

        <div class="chart-container">
            <div class="chart-title">Edit "${escapeHtmlAttr(current.name)}" (v${current.version}) — saving creates v${current.version + 1}; past runs keep their snapshot</div>
            <p class="form-help">Used by loan risk runs and by valuation Monte Carlo (which sets its own path count).</p>
            <div class="form-row">
                <div class="form-group"><label class="form-label">Name</label><input class="form-input" id="rpName" value="${escapeHtmlAttr(current.name)}"></div>
                <div class="form-group"><label class="form-label">Comment</label><input class="form-input" id="rpComment" value="${escapeHtmlAttr(current.comment || '')}"></div>
            </div>
            ${RISK_PARAM_GROUPS.map(g => `
                <h3 class="section-title" style="font-size:1rem;margin:20px 0 4px">${g.label}</h3>
                ${g.help ? `<p class="form-help" style="margin-bottom:8px">${g.help}</p>` : ''}
                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:0 16px">
                    ${g.fields.map(([k, l, kind]) => paramInput(k, l, kind, p[k])).join('')}
                </div>
                ${g.label === 'Simulation' ? renderDriverEditor(p) : ''}
                ${g.label === 'Rates' ? `
                    ${curveStale ? '<div class="modal-warning" style="margin:8px 0" id="rpCurveWarn">The rate curves are flat placeholders. Load live rates or paste current curves and set the as-of date before relying on refinancing, floating-rate results and fair values.</div>' : ''}
                    <button class="btn btn-secondary btn-sm" id="loadRatesBtn" style="margin-bottom:8px">Load Live Rates (FRED)</button>
                    <span class="form-help" id="loadRatesNote" style="margin-left:8px"></span>
                    <div class="form-row">
                        <div class="form-group"><label class="form-label">SOFR Forward Curve — "years, rate %" per line</label>
                            <textarea class="form-input" id="rpCurve" rows="8" style="font-family:'JetBrains Mono',monospace">${curveText(p.index_curve)}</textarea></div>
                        <div class="form-group"><label class="form-label">10-Year Treasury Forward Curve — "years, rate %" per line</label>
                            <textarea class="form-input" id="rpTreasury" rows="8" style="font-family:'JetBrains Mono',monospace">${curveText(p.treasury_curve)}</textarea></div>
                    </div>` : ''}
                ${g.label === 'Loss Given Default' ? `<div class="form-group"><label class="form-label">Liquidation Lag by Type (months) — "type: months" per line</label>
                    <textarea class="form-input" id="rpLagByType" rows="3">${Object.entries(p.liquidation_lag_by_type).map(([t, m]) => `${t}: ${m}`).join('\n')}</textarea></div>` : ''}
            `).join('')}
            <div style="display:flex;gap:8px;margin-top:16px">
                <button class="btn btn-primary" id="saveSetBtn">Save Parameters</button>
                <button class="btn btn-secondary" id="resetSetBtn">Reset Form to Engine Defaults</button>
            </div>
        </div>

        <div class="chart-container">
            <div class="chart-title">Version History — "${escapeHtmlAttr(current.name)}"</div>
            <p class="form-help">Every saved version is kept. Runs record the version they used and a full copy of its parameters.</p>
            <div class="data-table-wrap" style="box-shadow:none;max-height:320px;overflow:auto"><table class="data-table" style="font-size:12px">
                <thead><tr><th>Version</th><th>Saved</th><th>Name</th><th>Changes from Previous</th><th></th></tr></thead>
                <tbody>${versions.map((v, i) => `<tr>
                    <td>v${v.version}</td><td style="white-space:nowrap">${new Date(v.created_at + (v.created_at.endsWith('Z') ? '' : 'Z')).toLocaleString()}</td>
                    <td>${escapeHtmlAttr(v.name)}</td><td>${changedKeys(v, i)}</td>
                    <td>${i > 0 ? `<button class="btn btn-secondary btn-sm" data-restore="${v.version}">Load into Form</button>` : ''}</td></tr>`).join('')}</tbody>
            </table></div>
        </div>

        <div class="two-col">
            <div class="chart-container" style="margin-bottom:0">
                <div class="chart-title">Moody's Idealized Expected Loss (%)</div>
                <p class="form-help">Moody's (2003) idealized cumulative EL by rating and horizon. A loan is rated at the best rating whose idealized EL at the loan's WAL is at least its simulated EL; beyond 10 years the 10-year column is used.</p>
                <div class="data-table-wrap" style="box-shadow:none;max-height:420px;overflow:auto"><table class="data-table" style="font-size:12px">
                    <thead><tr><th>Rating</th>${[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(y => `<th style="text-align:right">${y}y</th>`).join('')}</tr></thead>
                    <tbody>${Object.entries(ref.moodys_idealized_el_pct).map(([r, row]) => `<tr><td><strong>${r}</strong></td>${row.map(v => td(v.toFixed(4).replace(/0+$/, '').replace(/\.$/, ''))).join('')}</tr>`).join('')}</tbody>
                </table></div>
            </div>
            <div class="chart-container" style="margin-bottom:0">
                <div class="chart-title">NAIC Commercial Mortgage (CM) Categories</div>
                <p class="form-help">LR004 office/industrial/retail/multifamily matrix. DSC = Year-1 NOI ÷ (12 payments of a 300-month amortization of total debt at the loan rate), rounded down to 0.01; LTV = total debt ÷ current DCF value, rounded to the nearest percent. Junior loans move one category riskier (cap CM5). 90+ days delinquent = CM6; foreclosure/REO = CM7.</p>
                <div class="data-table-wrap" style="box-shadow:none"><table class="data-table">
                    <thead><tr><th>Category</th><th style="text-align:right">RBC Factor</th></tr></thead>
                    <tbody>${Object.entries(ref.naic_cm_factors).map(([c, f]) => `<tr><td>${cmBadge(c)}</td>${td(fmt.pct(f, 2))}</tr>`).join('')}</tbody>
                </table></div>
            </div>
        </div>

        <div class="section-header"><h2 class="section-title">Recent Changes (all inputs)</h2></div>
        <p class="form-help">Every create, update and delete of properties, leases, expenses, valuations, funds, loans and parameter sets is logged automatically with before/after values and the request that made it. Valuation result changes (NPV, IRR, cap rates) are logged when a rerun changes them.</p>
        ${renderAuditTable(recent, { showEntity: true })}
    `;

    document.querySelectorAll('tr[data-set]').forEach(tr => tr.onclick = (e) => {
        if (e.target.closest('button')) return;
        adminView({ setId: tr.dataset.set });
    });
    document.querySelectorAll('[data-default]').forEach(b => b.onclick = async () => {
        await api.post(`/risk-parameter-sets/${b.dataset.default}/make-default`);
        toast('Default parameter set changed', 'success');
        adminView({ setId: b.dataset.default });
    });
    document.querySelectorAll('[data-delset]').forEach(b => b.onclick = () => showDeleteConfirm('parameter set', async () => {
        await api.del(`/risk-parameter-sets/${b.dataset.delset}`);
        adminView();
    }));

    const collect = () => {
        const params = {};
        RISK_PARAM_GROUPS.forEach(g => g.fields.forEach(([k, , kind]) => {
            const v = readParamInput(kind, document.getElementById(`rp_${k}`));
            if (v !== undefined) params[k] = v;
        }));
        params.driver_volatility = {};
        params.driver_persistence = {};
        params.recession_shock = {};
        MC_DRIVERS.forEach(([k]) => {
            const shock = readParamInput('pct', document.getElementById(`rp_rec_${k}`));
            if (shock !== undefined) params.recession_shock[k] = shock;
            const v = readParamInput('pct', document.getElementById(`rp_vol_${k}`));
            const phi = readParamInput('num', document.getElementById(`rp_phi_${k}`));
            if (v !== undefined) params.driver_volatility[k] = v;
            if (phi !== undefined) params.driver_persistence[k] = phi;
        });
        params.driver_correlation = MC_DRIVERS.map((_, i) => MC_DRIVERS.map((_, j) => {
            if (i === j) return 1;
            const v = parseFloat(document.querySelector(`[data-corr="${i},${j}"]`).value);
            if (isNaN(v)) throw new Error(`Correlation ${mcDriverLabel(MC_DRIVERS[i][0])} / ${mcDriverLabel(MC_DRIVERS[j][0])} is blank`);
            return v;
        }));
        params.index_curve = parseCurve('rpCurve', 'SOFR curve');
        params.treasury_curve = parseCurve('rpTreasury', 'Treasury curve');
        params.liquidation_lag_by_type = Object.fromEntries(document.getElementById('rpLagByType').value.split('\n')
            .map(l => l.split(':').map(s => s.trim())).filter(([t, m]) => t && !isNaN(parseInt(m, 10)))
            .map(([t, m]) => [t, parseInt(m, 10)]));
        return params;
    };

    document.getElementById('saveSetBtn').onclick = async () => {
        try {
            await api.put(`/risk-parameter-sets/${current.id}`, {
                name: document.getElementById('rpName').value || current.name,
                comment: document.getElementById('rpComment').value,
                params: collect(),
            });
            toast('Parameters saved', 'success');
            adminView({ setId: current.id });
        } catch (err) {
            toast('Error: ' + err.message, 'error');
        }
    };
    const fillForm = (saved) => {
        // Versions saved before a setting existed use the engine default for it
        const d = { ...ref.defaults, ...saved };
        RISK_PARAM_GROUPS.forEach(g => g.fields.forEach(([k, l, kind]) => {
            const el = document.getElementById(`rp_${k}`);
            if (kind === 'bool') el.checked = !!d[k];
            else if (kind === 'pct') el.value = +(d[k] * 100).toFixed(4);
            else el.value = d[k] ?? '';
        }));
        MC_DRIVERS.forEach(([k], i) => {
            document.getElementById(`rp_vol_${k}`).value = +((d.driver_volatility[k] ?? 0) * 100).toFixed(4);
            document.getElementById(`rp_phi_${k}`).value = d.driver_persistence[k] ?? 0;
            document.getElementById(`rp_rec_${k}`).value = +((d.recession_shock[k] ?? 0) * 100).toFixed(4);
            MC_DRIVERS.forEach((_, j) => { document.querySelector(`[data-corr="${i},${j}"]`).value = d.driver_correlation[i][j]; });
        });
        document.getElementById('rpCurve').value = curveText(d.index_curve);
        document.getElementById('rpTreasury').value = curveText(d.treasury_curve);
        document.getElementById('rpLagByType').value = Object.entries(d.liquidation_lag_by_type).map(([t, m]) => `${t}: ${m}`).join('\n');
    };
    document.querySelectorAll('[data-corr]').forEach(el => el.oninput = () => {
        const [i, j] = el.dataset.corr.split(',');
        document.querySelector(`[data-corr="${j},${i}"]`).value = el.value;
    });
    document.getElementById('loadRatesBtn').onclick = async (e) => {
        const btn = e.currentTarget;
        btn.disabled = true;
        btn.textContent = 'Loading...';
        try {
            const r = await api.get('/risk-parameter-sets/live-rates');
            document.getElementById('rpCurve').value = curveText(r.index_curve);
            document.getElementById('rpTreasury').value = curveText(r.treasury_curve);
            document.getElementById('rp_index_curve_as_of').value = r.as_of;
            document.getElementById('rpCurveWarn')?.remove();
            document.getElementById('loadRatesNote').textContent =
                `SOFR ${fmt.pct(r.sofr, 2)} as of ${fmt.dateFull(r.as_of)}; forwards implied from the Treasury curve. Save to apply.`;
            toast('Live rates loaded into the form; save to apply', 'info');
        } catch (err) {
            toast('Error: ' + err.message, 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Load Live Rates (FRED)';
        }
    };
    document.querySelectorAll('[data-restore]').forEach(b => b.onclick = () => {
        fillForm(versions.find(v => v.version === +b.dataset.restore).params);
        window.scrollTo({ top: document.getElementById('rpName').getBoundingClientRect().top + window.scrollY - 120, behavior: 'smooth' });
        toast(`Form loaded from v${b.dataset.restore}; save to make it the new version`, 'info');
    });
    document.getElementById('resetSetBtn').onclick = () => {
        fillForm(ref.defaults);
        toast('Form reset to engine defaults; save to apply', 'info');
    };
    document.getElementById('newSetBtn').onclick = () => showFormModal({
        title: 'New Parameter Set',
        fields: [{ key: 'name', label: 'Name', type: 'text', required: true }, { key: 'comment', label: 'Comment', type: 'text' }],
        onSubmit: async (data, overlay) => {
            const created = await api.post('/risk-parameter-sets', { name: data.name, comment: data.comment || null, params: p });
            overlay.remove();
            adminView({ setId: created.id });
        },
    });
}


// ═══════════════════════════════════════════════════════════════
// VALUATION MONTE CARLO (section on the valuation page)
// ═══════════════════════════════════════════════════════════════

async function loadMonteCarloSection(valuationId) {
    const el = document.getElementById('monteCarloSection');
    if (!el) return;
    const sims = await api.get(`/valuations/${valuationId}/monte-carlo`).catch(() => []);
    const latest = sims.find(x => x.status === 'completed' || x.status === 'running' || x.status === 'queued') || sims[0];
    el.innerHTML = `
        <div class="section-header" style="margin-top:20px">
            <h3 class="section-title">Monte Carlo</h3>
            <div style="display:flex;gap:8px;align-items:center">
                <label class="form-label" style="margin:0">Paths</label>
                <input class="form-input" type="number" id="mcPaths" min="10" max="20000" step="500" value="${latest?.num_paths || 5000}" style="width:100px">
                <button class="btn btn-primary btn-sm" id="mcRunBtn">Run Monte Carlo</button>
            </div>
        </div>
        <p class="form-help">Values the property with the full cash flow engine on every path, each with its own year-by-year rent growth, vacancy, renewals, downtime, TI and free rent, expense inflation and exit cap rate. Driver settings come from the default parameter set (Risk Admin). A finished run is reused until the property's inputs or the settings change.</p>
        ${sims.length ? `<p class="form-help"><a href="#/simulations/${sims[0].property_id}" style="color:var(--accent)">All simulations for this property</a>${latest ? ` · <a href="#/simulation/${latest.id}" style="color:var(--accent)">Open this run</a>` : ''}</p>` : ''}
        <div id="mcBody">${latest ? '' : '<div class="empty-state"><p>No Monte Carlo run yet.</p></div>'}</div>`;
    document.getElementById('mcRunBtn').onclick = async (e) => {
        e.currentTarget.disabled = true;
        try {
            const sim = await api.post(`/valuations/${valuationId}/monte-carlo`, { num_paths: parseInt(document.getElementById('mcPaths').value, 10) || 5000 });
            if (sim.reused) toast('Inputs unchanged — showing the existing run', 'info');
            showMonteCarlo(sim.id);
        } catch (err) {
            toast('Error: ' + err.message, 'error');
        } finally {
            const btn = document.getElementById('mcRunBtn');
            if (btn) btn.disabled = false;
        }
    };
    if (latest) showMonteCarlo(latest.id);
}

async function showMonteCarlo(simId, polling = false) {
    // The panel shows one simulation; a poll stops once the page (or its simulation) changes
    const current = () => {
        const el = document.getElementById('mcBody');
        return el && el.dataset.simId === simId ? el : null;
    };
    if (!polling) {
        const el = document.getElementById('mcBody');
        if (el) el.dataset.simId = simId;
    }
    if (!current()) return;
    const sim = await api.get(`/collateral-simulations/${simId}`);
    const body = current();
    if (!body) return;
    if (sim.status === 'queued' || sim.status === 'running') {
        const pct = Math.round(sim.progress * 100);
        body.innerHTML = `<div class="chart-container"><div class="chart-title">Running ${sim.num_paths.toLocaleString()} paths… ${pct}%</div>
            <div style="height:8px;background:var(--border);border-radius:4px;overflow:hidden"><div style="width:${pct}%;height:100%;background:var(--blue, #0071e3)"></div></div></div>`;
        setTimeout(() => showMonteCarlo(simId, true), 1500);
        return;
    }
    if (sim.status === 'failed') {
        body.innerHTML = `<div class="modal-warning">Monte Carlo failed: ${escapeHtmlAttr(sim.error_message || 'unknown error')}</div>`;
        return;
    }
    const s = sim.summary;
    const v = s.value;
    const card = (label, value, sub = '') => `<div class="metric-card"><div class="metric-label">${label}</div><div class="metric-value">${value}</div>${sub ? `<div class="metric-sub" style="font-size:12px;color:var(--text-secondary)">${sub}</div>` : ''}</div>`;
    const maxSens = Math.max(...s.sensitivity.map(x => Math.abs(x.value_per_std)), 1);
    body.innerHTML = `
        <p class="form-help">${s.paths.toLocaleString()} paths · run ${new Date(sim.created_at + (sim.created_at.endsWith('Z') ? '' : 'Z')).toLocaleString()} · parameter set v${sim.parameter_set_version ?? '—'} · seed ${sim.seed}</p>
        <div class="metrics-grid">
            ${card('Deterministic Value', fmt.currency(s.base_value))}
            ${card('Mean Value', fmt.currency(v.mean), `σ ${fmt.currency(v.std)}`)}
            ${card('5th – 95th Percentile', `${fmt.currency(v.p5)} – ${fmt.currency(v.p95)}`, `median ${fmt.currency(v.p50)}`)}
            ${card('Chance Below Deterministic', fmt.pct(s.prob_below_base, 1), `${fmt.pct(s.prob_below_90pct_base, 1)} more than 10% below`)}
            ${s.irr ? card('IRR 5th / 50th / 95th', `${fmt.pct(s.irr.p5, 1)} / ${fmt.pct(s.irr.p50, 1)} / ${fmt.pct(s.irr.p95, 1)}`) : ''}
            ${card('Exit Cap 5th – 95th', `${fmt.pct(s.exit_cap.p5, 2)} – ${fmt.pct(s.exit_cap.p95, 2)}`)}
        </div>
        <div class="two-col">
            <div class="chart-container"><div class="chart-title">Value Distribution</div><div class="chart-wrap"><canvas id="mcHist"></canvas></div></div>
            <div class="chart-container"><div class="chart-title">NOI by Year (5th–95th percentile band)</div><div class="chart-wrap"><canvas id="mcNoi"></canvas></div></div>
        </div>
        <div class="chart-container">
            <div class="chart-title">What Drives Value</div>
            <p class="form-help">Correlation of each driver's average deviation over the hold with value across paths, and the value change that goes with a one standard deviation move in that driver.</p>
            <div class="data-table-wrap" style="box-shadow:none"><table class="data-table">
                <thead><tr><th>Driver</th><th style="text-align:right">Correlation with Value</th><th style="text-align:right">Value per 1σ</th><th style="width:40%"></th></tr></thead>
                <tbody>${s.sensitivity.map(x => {
                    const w = Math.abs(x.value_per_std) / maxSens * 50;
                    const neg = x.value_per_std < 0;
                    return `<tr><td>${mcDriverLabel(x.driver)}</td>${td(x.correlation.toFixed(2))}${td(fmt.currency(x.value_per_std))}
                        <td><div style="position:relative;height:14px"><div style="position:absolute;left:50%;top:0;bottom:0;border-left:1px solid var(--border)"></div>
                        <div style="position:absolute;top:2px;height:10px;border-radius:2px;${neg ? `right:50%;background:#ff3b30` : `left:50%;background:#34c759`};width:${w}%"></div></div></td></tr>`;
                }).join('')}</tbody>
            </table></div>
        </div>`;

    const edges = s.histogram.edges;
    const mids = s.histogram.counts.map((_, i) => (edges[i] + edges[i + 1]) / 2);
    new Chart(document.getElementById('mcHist'), {
        type: 'bar',
        data: { labels: mids.map(m => fmt.currency(m)), datasets: [{
            data: s.histogram.counts,
            backgroundColor: mids.map(m => m < s.base_value ? 'rgba(255,59,48,0.55)' : 'rgba(0,113,227,0.6)'),
            borderRadius: 2, barPercentage: 1, categoryPercentage: 1,
        }] },
        options: { maintainAspectRatio: false,
            plugins: { tooltip: { callbacks: { title: c => `${fmt.currency(edges[c[0].dataIndex])} – ${fmt.currency(edges[c[0].dataIndex + 1])}`, label: c => `${c.raw} paths` } } },
            scales: { x: { ticks: { maxTicksLimit: 6 }, grid: { display: false } }, y: { title: { display: true, text: 'Paths' } } } },
    });
    const n = s.noi_by_year;
    new Chart(document.getElementById('mcNoi'), {
        type: 'line',
        data: { labels: n.map(r => `Yr ${r.year}`), datasets: [
            { label: '95th', data: n.map(r => r.p95), borderColor: 'transparent', backgroundColor: 'rgba(0,113,227,0.10)', fill: '+4', pointRadius: 0 },
            { label: '75th', data: n.map(r => r.p75), borderColor: 'transparent', backgroundColor: 'rgba(0,113,227,0.18)', fill: '+2', pointRadius: 0 },
            { label: 'Median', data: n.map(r => r.p50), borderColor: '#0071e3', borderWidth: 2, pointRadius: 0, fill: false },
            { label: '25th', data: n.map(r => r.p25), borderColor: 'transparent', pointRadius: 0, fill: false },
            { label: '5th', data: n.map(r => r.p5), borderColor: 'transparent', pointRadius: 0, fill: false },
        ] },
        options: { maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
            plugins: { tooltip: { callbacks: { label: c => `${c.dataset.label}: ${fmt.currency(c.raw)}` } } },
            scales: { y: { ticks: { callback: x => fmt.currency(x) } } } },
    });
}


// ═══════════════════════════════════════════════════════════════
// COLLATERAL SIMULATIONS (list and detail)
// ═══════════════════════════════════════════════════════════════

const simPurposeLabel = p => ({ valuation: 'Valuation', loan_risk: 'Loan risk' }[p] || p);
const simStatusBadge = sim => `<span class="status-badge status-${sim.status === 'completed' ? 'completed' : sim.status === 'failed' ? 'failed' : 'running'}">${sim.status}${sim.status === 'running' ? ' ' + Math.round(sim.progress * 100) + '%' : ''}</span>`;
const simTime = (t, short = false) => new Date(t + (t.endsWith('Z') ? '' : 'Z'))
    .toLocaleString(undefined, short ? { dateStyle: 'short', timeStyle: 'short' } : undefined);

async function simulationsView(params = {}) {
    const propertyId = params.propertyId || '';
    setBreadcrumb([{ label: 'Properties', href: '#/dashboard' }, { label: 'Simulations' }]);
    const [all, sets] = await Promise.all([api.get('/collateral-simulations'), api.get('/risk-parameter-sets')]);
    const setById = Object.fromEntries(sets.map(x => [x.id, x]));
    const properties = [...new Map(all.map(x => [x.property_id, x.property_name])).entries()]
        .sort((a, b) => (a[1] || '').localeCompare(b[1] || ''));
    const purpose = sessionStorage.getItem('simPurpose') || '';
    const sims = all.filter(x => (!propertyId || x.property_id === propertyId) && (!purpose || x.purpose === purpose));

    $app().innerHTML = `
        <div class="page-header">
            <h1 class="page-title">Collateral Simulations</h1>
            <p class="page-subtitle">Monte Carlo valuations: the full cash flow engine on every simulated path. Run them from a valuation page; loan risk runs add their own.</p>
        </div>
        <div class="form-row" style="max-width:640px">
            <div class="form-group"><label class="form-label">Property</label>
                <select class="form-input" id="simProperty"><option value="">All properties</option>
                    ${properties.map(([id, name]) => `<option value="${id}" ${id === propertyId ? 'selected' : ''}>${escapeHtmlAttr(name || id)}</option>`).join('')}</select></div>
            <div class="form-group"><label class="form-label">Purpose</label>
                <select class="form-input" id="simPurpose"><option value="">All</option>
                    ${['valuation', 'loan_risk'].map(p => `<option value="${p}" ${p === purpose ? 'selected' : ''}>${simPurposeLabel(p)}</option>`).join('')}</select></div>
        </div>
        ${sims.length === 0 ? '<div class="empty-state"><h3>No simulations</h3><p>Open a valuation and click Run Monte Carlo.</p></div>' : `
        <div class="data-table-wrap"><table class="data-table">
            <thead><tr><th>Run</th><th>Property / Valuation</th><th>Purpose</th><th>Parameters</th>
                <th style="text-align:right">Deterministic</th><th style="text-align:right">Mean</th><th style="text-align:right">5th – 95th</th>
                <th style="text-align:right">Below Det.</th><th></th></tr></thead>
            <tbody>${sims.map(x => `<tr style="cursor:pointer" data-sim="${x.id}">
                <td style="white-space:nowrap">${simTime(x.created_at, true)}${x.status === 'completed' ? '' : `<div>${simStatusBadge(x)}</div>`}</td>
                <td class="tenant-name"><strong>${escapeHtmlAttr(x.property_name || '—')}</strong>
                    <div style="font-size:12px;color:var(--text-secondary)">${escapeHtmlAttr(x.valuation_name || '—')}</div></td>
                <td>${simPurposeLabel(x.purpose)}<div style="font-size:12px;color:var(--text-secondary)">${num(x.num_paths)} paths</div></td>
                <td>${escapeHtmlAttr(setById[x.parameter_set_id]?.name || '—')}${x.parameter_set_version != null ? ' v' + x.parameter_set_version : ''}</td>
                ${td(x.base_value != null ? fmt.currency(x.base_value) : '—')}
                ${td(x.mean_value != null ? fmt.currency(x.mean_value) : '—')}
                ${td(x.p5_value != null ? `${fmt.currency(x.p5_value)} – ${fmt.currency(x.p95_value)}` : '—')}
                ${td(x.prob_below_base != null ? fmt.pct(x.prob_below_base, 1) : '—')}
                <td><button class="btn-icon" data-del="${x.id}" title="Delete">${icons.trash}</button></td>
            </tr>`).join('')}</tbody>
        </table></div>`}`;

    document.getElementById('simProperty').onchange = e => {
        location.hash = e.target.value ? `#/simulations/${e.target.value}` : '#/simulations';
    };
    document.getElementById('simPurpose').onchange = e => {
        try { sessionStorage.setItem('simPurpose', e.target.value); } catch (_) { /* storage blocked */ }
        simulationsView(params);
    };
    document.querySelectorAll('tr[data-sim]').forEach(tr => tr.onclick = (e) => {
        if (e.target.closest('[data-del]')) return;
        location.hash = `#/simulation/${tr.dataset.sim}`;
    });
    document.querySelectorAll('[data-del]').forEach(b => b.onclick = () => showDeleteConfirm('simulation', async () => {
        await api.del(`/collateral-simulations/${b.dataset.del}`);
        simulationsView(params);
    }));
    const here = location.hash;
    if (sims.some(x => x.status === 'queued' || x.status === 'running')) {
        setTimeout(() => { if (location.hash === here) simulationsView(params); }, 2000);
    }
}

async function simulationView({ id }) {
    let sim;
    try {
        sim = await api.get(`/collateral-simulations/${id}`);
    } catch (err) {
        $app().innerHTML = `<div class="empty-state"><h3>Simulation not found</h3><br><a href="#/simulations" class="btn btn-secondary">Back to simulations</a></div>`;
        return;
    }
    setBreadcrumb([{ label: 'Properties', href: '#/dashboard' }, { label: 'Simulations', href: '#/simulations' },
        { label: sim.property_name || 'Simulation' }]);
    const p = sim.params;
    const pctCell = (v, d = 2) => td(v != null ? fmt.pct(v, d) : '—');
    const scalar = [
        ['Recession start probability (per year)', fmt.pct(p.recession_probability, 0)],
        ['Recession continue probability', fmt.pct(p.recession_persistence, 0)],
        ['Recession severity', num(p.recession_severity, 2)],
        ['Rent level reversion (per year)', fmt.pct(p.rent_level_reversion, 0)],
        ['National share of market / type shocks', fmt.pct(p.global_share, 0)],
        ['Market share of leasing shocks', fmt.pct(p.market_share, 0)],
        ['Property-type share of cap rate shocks', fmt.pct(p.cap_rate_type_share, 0)],
        ['Cap rate floor', fmt.pct(p.cap_rate_floor, 2)],
        ['Seed', p.seed],
    ];
    const logDriver = k => k === 'downtime' || k === 'concessions';

    $app().innerHTML = `
        <div class="page-header" style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px">
            <div>
                <h1 class="page-title">${escapeHtmlAttr(sim.property_name || 'Simulation')}</h1>
                <p class="page-subtitle">${simPurposeLabel(sim.purpose)} simulation${sim.valuation_name ? ` · ${escapeHtmlAttr(sim.valuation_name)}` : ''} · ${num(sim.num_paths)} paths · ${sim.horizon_months / 12} years from ${fmt.dateFull(sim.analysis_start)} · ${simStatusBadge(sim)}</p>
            </div>
            <div style="display:flex;gap:8px">
                <a class="btn btn-secondary btn-sm" href="#/property/${sim.property_id}">Property</a>
                ${sim.valuation_id ? `<a class="btn btn-secondary btn-sm" href="#/valuation/${sim.valuation_id}">Valuation</a>` : ''}
                <button class="btn btn-secondary btn-sm" id="simDelete">Delete</button>
            </div>
        </div>
        <div id="mcBody"></div>
        <div id="simPaths"></div>
        <div class="chart-container">
            <div class="chart-title">Settings Used</div>
            <p class="form-help">Snapshot from ${escapeHtmlAttr(sim.parameter_set_name || 'a parameter set')}${sim.parameter_set_version != null ? ` v${sim.parameter_set_version}` : ''} when the simulation ran; later edits to the set do not change it. Each path moves every driver around its base case: volatility and recession shocks are added to rates (± points) and scale downtime and TI / free rent (% change).
                ${sim.base_assumptions_source === 'current' ? '<br><strong>Base case shows the valuation\'s current inputs</strong>; this simulation ran before base assumptions were saved with it.' : ''}</p>
            <div class="data-table-wrap" style="box-shadow:none;margin-bottom:16px"><table class="data-table">
                <thead><tr><th>Driver</th><th>Base Case</th><th style="text-align:right">Volatility</th><th style="text-align:right">Persistence</th><th style="text-align:right">Recession Shock</th></tr></thead>
                <tbody>${MC_DRIVERS.map(([k, label]) => `<tr><td>${label}</td>
                    <td>${escapeHtmlAttr(sim.base_assumptions?.[k] ?? '—')}</td>
                    ${pctCell(p.driver_volatility[k], logDriver(k) ? 0 : 2)}${td(num(p.driver_persistence[k], 2))}${pctCell(p.recession_shock?.[k], logDriver(k) ? 0 : 2)}</tr>`).join('')}</tbody>
            </table></div>
            <div class="two-col">${[scalar.slice(0, 5), scalar.slice(5)].map(half => `
                <div class="data-table-wrap" style="box-shadow:none"><table class="data-table">
                    <tbody>${half.map(([label, v]) => `<tr><td>${label}</td>${td(v)}</tr>`).join('')}</tbody>
                </table></div>`).join('')}
            </div>
        </div>`;

    document.getElementById('simDelete').onclick = () => showDeleteConfirm('simulation', async () => {
        await api.del(`/collateral-simulations/${id}`);
        location.hash = '#/simulations';
    });
    showMonteCarlo(id);
    if (sim.status === 'completed') loadSimPaths(sim);
}

async function loadSimPaths(sim) {
    const el = document.getElementById('simPaths');
    if (!el) return;
    const paths = await api.get(`/collateral-simulations/${sim.id}/paths`).catch(() => []);
    if (!paths.length) return;
    const base = sim.summary.base_value;
    const ord = p => `${p}${p === 1 ? 'st' : 'th'}`;
    el.innerHTML = `
        <div class="chart-container">
            <div class="chart-title">Paths</div>
            <p class="form-help">The path at each value percentile. Open one to see its cash flows and the assumptions it drew, year by year. Paths are rebuilt from the simulation's seed and settings when opened.</p>
            <div class="data-table-wrap" style="box-shadow:none"><table class="data-table">
                <thead><tr><th>Percentile</th><th style="text-align:right">Value</th><th style="text-align:right">vs Deterministic</th>
                    <th style="text-align:right">IRR</th><th style="text-align:right">Exit Cap</th><th style="text-align:right">Path #</th><th></th></tr></thead>
                <tbody>${paths.map(p => `<tr style="cursor:pointer" data-path="${p.index}">
                    <td><strong>${ord(p.percentile)}</strong>${p.percentile === 50 ? ' (median)' : ''}</td>
                    ${td(fmt.currency(p.npv))}${td(fmt.pct(p.npv / base - 1, 1))}
                    ${td(p.irr != null ? fmt.pct(p.irr, 2) : '—')}${td(fmt.pct(p.exit_cap, 2))}${td(p.index + 1)}
                    <td style="text-align:right;color:var(--accent)">Cash flows ›</td></tr>`).join('')}</tbody>
            </table></div>
        </div>`;
    el.querySelectorAll('tr[data-path]').forEach(tr => tr.onclick = () => {
        location.hash = `#/simulation/${sim.id}/path/${tr.dataset.path}`;
    });
}

async function simulationPathView({ id, index }) {
    $app().innerHTML = '<div class="empty-state"><p>Running this path through the cash flow engine…</p></div>';
    const [sim, path, listed] = await Promise.all([api.get(`/collateral-simulations/${id}`),
        api.get(`/collateral-simulations/${id}/paths/${index}`), api.get(`/collateral-simulations/${id}/paths`)]);
    const pct = listed.find(p => p.index === +index)?.percentile;
    setBreadcrumb([{ label: 'Properties', href: '#/dashboard' }, { label: 'Simulations', href: '#/simulations' },
        { label: sim.property_name || 'Simulation', href: `#/simulation/${id}` }, { label: `Path ${+index + 1}` }]);
    const a = path.assumptions;
    const rev = path.reversion;
    const years = a.years;
    const spaces = Object.keys(years[0].space_types);
    const multi = spaces.length > 1;
    // Path value, with the base case underneath when the path differs from it
    const cell = (v, b, f) => {
        const differs = b != null && Math.abs(v - b) > 1e-9;
        return `<td style="text-align:right">${f(v)}${differs ? `<div style="font-size:11px;color:var(--text-secondary)">base ${f(b)}</div>` : ''}</td>`;
    };
    const p2 = v => fmt.pct(v, 2);
    const p0 = v => fmt.pct(v, 0);
    const rows = [];
    rows.push(`<tr><td>Recession</td>${years.map(y => `<td style="text-align:right">${y.recession ? '<span class="status-badge status-failed">Recession</span>' : ''}</td>`).join('')}</tr>`);
    spaces.forEach(k => {
        const tag = multi ? ` <span style="font-size:11px;color:var(--text-secondary)">${escapeHtmlAttr(k)}</span>` : '';
        const s = y => y.space_types[k];
        rows.push(`<tr><td>Market Rent Growth${tag}</td>${years.map(y => cell(s(y).rent_growth, s(y).base_rent_growth, p2)).join('')}</tr>`);
        rows.push(`<tr><td>General Vacancy${tag}</td>${years.map(y => cell(s(y).vacancy, s(y).base_vacancy, p2)).join('')}</tr>`);
        rows.push(`<tr><td>Credit Loss${tag}</td>${years.map(y => cell(s(y).credit_loss, null, p2)).join('')}</tr>`);
        rows.push(`<tr><td>Renewal Probability${tag}</td>${years.map(y => cell(s(y).renewal, s(y).base_renewal, p0)).join('')}</tr>`);
        rows.push(`<tr><td>Downtime (months)${tag}</td>${years.map(y => cell(s(y).downtime, s(y).base_downtime, v => v)).join('')}</tr>`);
    });
    rows.push(`<tr><td>Expense Growth (weighted)</td>${years.map(y => y.expense_growth == null ? td('—') : cell(y.expense_growth, y.base_expense_growth, p2)).join('')}</tr>`);
    rows.push(`<tr><td>CPI</td>${years.map(y => cell(y.cpi, y.base_cpi, p2)).join('')}</tr>`);
    rows.push(`<tr><td>SOFR (start of year)</td>${years.map(y => cell(y.sofr, y.base_sofr, p2)).join('')}</tr>`);
    rows.push(`<tr><td>10-Year Treasury (start of year)</td>${years.map(y => cell(y.treasury_10y, y.base_treasury_10y, p2)).join('')}</tr>`);
    const conc = Object.entries(a.concessions).map(([k, c]) => `<tr><td>${escapeHtmlAttr(k)}</td>
        ${td(`${fmt.currency(c.new_ti_per_sf)} / ${c.new_free_rent_months} mo`)}${td(`${fmt.currency(c.base_new_ti_per_sf)} / ${c.base_new_free_rent_months} mo`)}
        ${td(`${fmt.currency(c.renewal_ti_per_sf)} / ${c.renewal_free_rent_months} mo`)}</tr>`).join('');
    const ord = p => `${p}${+p === 1 ? 'st' : 'th'} percentile`;

    $app().innerHTML = `
        <div class="page-header" style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px">
            <div>
                <h1 class="page-title">${escapeHtmlAttr(sim.property_name || 'Simulation')} — Path ${+index + 1}</h1>
                <p class="page-subtitle">${pct ? ord(pct) + ' · ' : ''}${fmt.currency(path.npv)} vs ${fmt.currency(sim.summary.base_value)} deterministic (${fmt.pct(path.npv / sim.summary.base_value - 1, 1)})${path.irr != null ? ` · IRR ${fmt.pct(path.irr, 2)}` : ''} · exit cap ${fmt.pct(a.exit_cap_rate, 2)} (base ${fmt.pct(a.base_exit_cap_rate, 2)})</p>
            </div>
            <a class="btn btn-secondary btn-sm" href="#/simulation/${id}">Back to simulation</a>
        </div>
        ${path.matches_simulation ? '' : `<div class="modal-warning">The property's inputs changed after this simulation ran, so this path now values at ${fmt.currency(path.npv)} instead of the ${fmt.currency(path.stored_npv)} recorded. Rerun the Monte Carlo for current results.</div>`}
        <div class="section-header"><h3 class="section-title">Assumptions on This Path</h3></div>
        <p class="form-help">What this path drew each year; the base case is shown underneath wherever the path differs from it.</p>
        <div class="cf-table-wrap"><table class="data-table">
            <thead><tr><th>Driver</th>${years.map(y => `<th style="text-align:right">Yr ${y.year}</th>`).join('')}</tr></thead>
            <tbody>${rows.join('')}</tbody>
        </table></div>
        <div class="two-col" style="margin-top:16px">
            <div class="data-table-wrap" style="box-shadow:none"><table class="data-table">
                <thead><tr><th>TI / Free Rent</th><th style="text-align:right">New Leases (path)</th><th style="text-align:right">New Leases (base)</th><th style="text-align:right">Renewals (path)</th></tr></thead>
                <tbody>${conc}</tbody></table></div>
            <div class="data-table-wrap" style="box-shadow:none"><table class="data-table">
                <thead><tr><th>Reversion (Sale)</th><th></th></tr></thead><tbody>
                <tr><td>Reversion NOI <span style="font-size:11px;color:var(--text-secondary)">${rev.exit_cap_year === -1 ? `Year ${years.length + 1} (forward year)` : `Year ${rev.exit_cap_year}`}</span></td>${td(fmt.currency(rev.noi_basis))}</tr>
                <tr><td>÷ Exit Cap Rate <span style="font-size:11px;color:var(--text-secondary)">base ${fmt.pct(a.base_exit_cap_rate, 2)}</span></td>${td(fmt.pct(rev.exit_cap_rate, 2))}</tr>
                <tr><td><strong>Gross Sale Price</strong></td>${td(`<strong>${fmt.currency(rev.gross_value)}</strong>`)}</tr>
                <tr><td>− Exit Costs</td>${td(fmt.currency(-rev.exit_costs))}</tr>
                ${rev.transfer_tax ? `<tr><td>− Transfer Tax</td>${td(fmt.currency(-rev.transfer_tax))}</tr>` : ''}
                ${rev.capital_deduction ? `<tr><td>− Forward-Year Capital</td>${td(fmt.currency(-rev.capital_deduction))}</tr>` : ''}
                <tr><td><strong>Net Reversion</strong></td>${td(`<strong>${fmt.currency(rev.net_value)}</strong>`)}</tr>
                <tr><td>Present Value of Reversion</td>${td(fmt.currency(rev.pv))}</tr>
                <tr><td>Value Today <span style="font-size:11px;color:var(--text-secondary)">PV of cash flows + reversion</span></td>${td(fmt.currency(path.npv))}</tr>
            </tbody></table></div>
        </div>
        <div class="section-header"><h3 class="section-title">Annual Cash Flow on This Path</h3></div>
        ${path.forward_cash_flow ? `<p class="form-help">Year ${years.length + 1} (shaded) is the year after the hold: it is not part of the hold's cash flows${rev.exit_cap_year === -1 ? ', but its NOI is the reversion NOI' : ''}.</p>` : ''}
        <div class="cf-table-wrap" id="pathCfWrap">${renderCashFlowTable(path.forward_cash_flow ? [...path.annual_cash_flows, path.forward_cash_flow] : path.annual_cash_flows, [], [], 'sf', '')}</div>`;
    if (path.forward_cash_flow) {
        // Shade the forward-year column
        const col = path.annual_cash_flows.length + 2;
        document.querySelectorAll(`#pathCfWrap tr > :nth-child(${col})`).forEach(c => { c.style.background = 'var(--bg-secondary, rgba(0,0,0,0.04))'; });
    }

    document.querySelectorAll('#cfTable tr.expandable').forEach(row => {
        row.querySelector('td').addEventListener('click', () => {
            const isExpanded = row.classList.toggle('expanded');
            document.querySelectorAll(`#cfTable tr.sub-row[data-group="${row.dataset.toggle}"]`).forEach(r => r.classList.toggle('visible', isExpanded));
        });
    });
}

addRoute('/simulations', simulationsView);
addRoute('/simulations/:propertyId', simulationsView);
addRoute('/simulation/:id', simulationView);
addRoute('/simulation/:id/path/:index', simulationPathView);
addRoute('/loans', loansView);
addRoute('/loan/:id', loanView);
addRoute('/risk-runs', riskRunsView);
addRoute('/risk-run/:id', riskRunView);
addRoute('/admin', adminView);
