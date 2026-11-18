// ─── Self storage: unit mix and revenue assumptions ──────────
// The operating model lives on each valuation (self_storage_assumptions_json) and is valued by
// src/engine/self_storage.py. Rates are $ per unit per month; percentages are fractions.

const STORAGE_ACCESS = { interior: 'Interior', drive_up: 'Drive-up', parking: 'Parking' };
const STORAGE_BASIS = {
    per_occupied_unit_month: '$ per occupied unit / month',
    per_move_in: '$ per move-in',
    pct_of_rental: '% of rental income',
    annual_fixed: '$ per year',
};

function storageModelOf(valuation) {
    try { return JSON.parse(valuation?.self_storage_assumptions_json || 'null'); } catch { return null; }
}

function storageStarterModel() {
    return {
        unit_types: [],
        street_rate_growth_pct: 0.03,
        churn: { monthly_move_out_pct: 0.04 },
        ecri: { enabled: true, first_after_months: 6, interval_months: 12, increase_pct: 0.08, extra_move_out_pct: 0.04 },
        concessions: { first_month_discount_pct: 0.5 },
        lease_up: { monthly_net_absorption_units: null },
        credit_loss_pct: 0.01,
        ancillary_lines: [
            { name: 'Tenant protection', basis: 'per_occupied_unit_month', amount: 12, participation_pct: 0.6, growth_pct: 0 },
        ],
    };
}

// Shown above the rent roll of a storage property that has no unit mix yet
function storageConvertNotice() {
    return `<div class="storage-notice">This property is still valued from its rent roll.
        <button class="btn btn-secondary btn-sm" id="convertStorageBtn">Convert rent roll to a unit mix</button></div>`;
}

function renderStorageUnitMixTab(property, model, cashFlows) {
    if (!model || !model.unit_types?.length) {
        return `<div class="empty-state">
            <h3>No unit mix yet</h3>
            <p>Enter each unit type with its count, occupied units, in-place rent and street rate. Churn, rate increases and ancillary income are set next.</p>
            <button class="btn btn-primary" id="editStorageUnitsBtn">Set up unit mix</button></div>`;
    }
    const n = v => parseFloat(v) || 0;
    const units = model.unit_types.reduce((s, u) => s + n(u.count), 0);
    const occupied = model.unit_types.reduce((s, u) => s + n(u.occupied_units), 0);
    const sf = model.unit_types.reduce((s, u) => s + n(u.sf_per_unit) * n(u.count), 0);
    const occSf = model.unit_types.reduce((s, u) => s + n(u.sf_per_unit) * n(u.occupied_units), 0);
    const inPlace = model.unit_types.reduce((s, u) => s + n(u.in_place_rate) * n(u.occupied_units), 0);
    const streetOcc = model.unit_types.reduce((s, u) => s + n(u.street_rate) * n(u.occupied_units), 0);
    const gap = streetOcc ? inPlace / streetOcc - 1 : 0;
    const sfMismatch = n(property.total_area) && Math.abs(sf - n(property.total_area)) > n(property.total_area) * 0.01;

    const rows = model.unit_types.map(u => {
        const occ = n(u.count) ? n(u.occupied_units) / n(u.count) : 0;
        const g = n(u.street_rate) ? n(u.in_place_rate) / n(u.street_rate) - 1 : 0;
        return `<tr>
            <td><strong>${escapeHtmlAttr(u.name)}</strong><small class="storage-sub">${u.climate_controlled ? 'Climate controlled · ' : ''}${STORAGE_ACCESS[u.access] || 'Interior'}</small></td>
            <td class="num">${fmt.num(u.sf_per_unit)}</td>
            <td class="num">${fmt.num(u.count)}</td>
            <td class="num">${fmt.num(u.occupied_units, 0)}</td>
            <td class="num">${fmt.pct(occ, 1)}</td>
            <td class="num">${fmt.currency(u.in_place_rate, 0)}</td>
            <td class="num">${fmt.currency(u.street_rate, 0)}</td>
            <td class="num ${g >= 0 ? 'green' : 'red'}">${g >= 0 ? '+' : ''}${fmt.pct(g, 1)}</td>
            <td class="num">${u.stabilized_occupancy != null ? fmt.pct(u.stabilized_occupancy, 0) : 'Today'}</td></tr>`;
    }).join('');

    const churn = n(model.churn?.monthly_move_out_pct);
    const ecri = model.ecri || {};
    const leaseUp = model.lease_up?.monthly_net_absorption_units;
    const assumption = (label, value, note = '') => `<div class="storage-assumption"><span>${label}</span><strong>${value}</strong>${note ? `<small>${note}</small>` : ''}</div>`;
    const ancillary = (model.ancillary_lines || []).map(l => `<tr><td>${escapeHtmlAttr(l.name)}</td>
        <td>${STORAGE_BASIS[l.basis] || l.basis}</td>
        <td class="num">${l.basis === 'pct_of_rental' ? fmt.pct(l.amount, 2) : fmt.currency(l.amount, 2)}</td>
        <td class="num">${fmt.pct(l.participation_pct ?? 1, 0)}</td>
        <td class="num">${fmt.pct(l.growth_pct || 0, 1)}</td></tr>`).join('');

    return `
        <div class="kpi-row storage-kpis">
            <div class="kpi-card"><div class="kpi-label">Units</div><div class="kpi-value">${fmt.num(units)}</div><div class="kpi-subtext">${fmt.num(sf)} rentable SF</div></div>
            <div class="kpi-card"><div class="kpi-label">Occupancy</div><div class="kpi-value">${fmt.pct(units ? occupied / units : 0, 1)}</div><div class="kpi-subtext">${fmt.pct(sf ? occSf / sf : 0, 1)} by SF</div></div>
            <div class="kpi-card"><div class="kpi-label">In-place vs street</div><div class="kpi-value ${gap >= 0 ? 'green' : ''}">${gap >= 0 ? '+' : ''}${fmt.pct(gap, 1)}</div><div class="kpi-subtext">${fmt.currency(sf ? inPlace * 12 / occSf : 0, 2)}/SF/yr in place</div></div>
        </div>
        ${sfMismatch ? `<div class="storage-notice warning">Unit types add up to ${fmt.num(sf)} SF but the property is ${fmt.num(property.total_area)} SF. Capital reserves use the property's SF.</div>` : ''}
        <div class="section-header"><h3 class="section-title">Unit mix</h3><button class="btn btn-secondary btn-sm" id="editStorageUnitsBtn">${icons.edit} Edit unit mix</button></div>
        <div class="table-wrap"><table class="data-table storage-table"><thead><tr>
            <th>Unit type</th><th class="num">SF</th><th class="num">Units</th><th class="num">Occupied</th><th class="num">Occupancy</th>
            <th class="num">In-place $/mo</th><th class="num">Street $/mo</th><th class="num">Gap</th><th class="num">Stabilized</th></tr></thead>
            <tbody>${rows}</tbody></table></div>

        <div class="section-header"><h3 class="section-title">Revenue assumptions</h3><button class="btn btn-secondary btn-sm" id="editStorageAssumptionsBtn">${icons.edit} Edit</button></div>
        <div class="storage-assumptions">
            ${assumption('Street rate growth', fmt.pct(model.street_rate_growth_pct || 0, 1) + ' / yr',
                model.street_rate_growth_schedule?.length ? `Schedule: ${formatRateList(model.street_rate_growth_schedule)}%` : '')}
            ${assumption('Move-outs', fmt.pct(churn, 1) + ' / month', churn ? `Average stay ${fmt.num(1 / churn, 0)} months` : 'No churn')}
            ${assumption('Rate increases (ECRI)', ecri.enabled ? `${fmt.pct(ecri.increase_pct, 1)} every ${ecri.interval_months} mo` : 'Off',
                ecri.enabled ? `First after ${ecri.first_after_months} months; ${fmt.pct(ecri.extra_move_out_pct, 1)} extra move-outs` : '')}
            ${assumption('Move-in concession', fmt.pct(model.concessions?.first_month_discount_pct || 0, 0) + ' off first month')}
            ${assumption('Lease-up', leaseUp ? `${fmt.num(leaseUp, 1)} units / month` : 'At stabilized occupancy', leaseUp ? 'Net absorption cap, facility-wide' : '')}
            ${assumption('Credit loss', fmt.pct(model.credit_loss_pct || 0, 1) + ' of rental')}
        </div>

        <div class="section-header"><h3 class="section-title">Ancillary income</h3><button class="btn btn-secondary btn-sm" id="editStorageAncillaryBtn">${icons.edit} Edit</button></div>
        ${ancillary ? `<div class="table-wrap"><table class="data-table storage-section-table"><thead><tr><th>Line</th><th>Basis</th><th class="num">Amount</th><th class="num">Participation</th><th class="num">Growth</th></tr></thead><tbody>${ancillary}</tbody></table></div>`
            : '<p class="muted">No ancillary income. Tenant protection, admin fees and retail sales go here.</p>'}
        ${renderStorageResults(cashFlows)}`;
}

function renderStorageResults(cashFlows) {
    const years = (cashFlows || []).filter(cf => cf.storage_detail);
    if (!years.length) return '<p class="muted storage-run-note">Run a valuation to see the rental build and yearly occupancy.</p>';
    const y1 = years[0];
    const v = k => parseFloat(y1[k]) || 0;
    const streetAll = v('gross_potential_rent') - v('absorption_vacancy') - v('loss_to_lease');
    const line = (label, amount, cls = '') => `<tr class="${cls}"><td>${label}</td><td class="num">${fmt.currencyExact(amount)}</td></tr>`;
    const build = `<table class="data-table storage-build"><tbody>
        ${line('Street rent, all units', streetAll)}
        ${line('Vacancy at street', v('absorption_vacancy'))}
        ${line(v('loss_to_lease') >= 0 ? 'Gain to lease (in place above street)' : 'Loss to lease', v('loss_to_lease'))}
        ${line('In-place rent', v('gross_potential_rent'), 'subtotal')}
        ${line('Move-in concessions', v('free_rent'))}
        ${line('Credit loss', v('credit_loss'))}
        ${line('Ancillary and other income', v('other_income'))}
        ${line('Effective gross income', v('effective_gross_income'), 'subtotal')}
        ${line('Operating expenses', v('operating_expenses'))}
        ${line('Net operating income', v('net_operating_income'), 'total')}
    </tbody></table>`;
    const metric = (label, f) => `<tr><td>${label}</td>${years.map(cf => `<td class="num">${f(cf.storage_detail)}</td>`).join('')}</tr>`;
    const yearly = `<div class="table-wrap"><table class="data-table storage-yearly"><thead><tr><th></th>${years.map(cf => `<th class="num">Yr ${cf.year}</th>`).join('')}</tr></thead><tbody>
        ${metric('Occupancy (units)', d => fmt.pct(d.physical_occupancy_units, 1))}
        ${metric('Occupancy (SF)', d => fmt.pct(d.physical_occupancy_sf, 1))}
        ${metric('Economic occupancy', d => fmt.pct(d.economic_occupancy, 1))}
        ${metric('In-place $/SF/yr', d => fmt.currency(d.in_place_rent_per_occupied_sf, 2))}
        ${metric('Street $/SF/yr', d => fmt.currency(d.street_rent_per_occupied_sf, 2))}
        ${metric('In-place vs street', d => fmt.pct(d.rate_gap_pct, 1))}
        ${metric('Move-ins', d => fmt.num(d.move_ins, 0))}
        ${metric('Move-outs', d => fmt.num(d.move_outs, 0))}
        ${metric('  of which after a rate increase', d => fmt.num(d.ecri_move_outs, 0))}
        ${metric('Revenue / available SF', d => fmt.currency(d.revenue_per_available_sf, 2))}
        ${metric('NOI margin', d => fmt.pct(d.noi_margin, 1))}
    </tbody></table></div>`;
    return `<div class="section-header"><h3 class="section-title">Year 1 rental build</h3><small class="muted">From the latest run</small></div>
        ${build}
        <div class="section-header"><h3 class="section-title">By year</h3></div>${yearly}`;
}

function wireStorageEditors(property, model, saveModel) {
    const working = model || storageStarterModel();
    const save = patch => saveModel({ ...working, ...patch });

    document.getElementById('editStorageUnitsBtn')?.addEventListener('click', () => {
        showBulkTableEditorModal({
            title: 'Unit mix',
            addLabel: 'Add unit type',
            intro: 'One row per unit type. Rents are $ per unit per month. Paste from a spreadsheet to fill several rows. Stabilized occupancy left blank keeps today\'s occupancy.',
            columns: [
                { key: 'name', label: 'Unit type', type: 'text', required: true, default: '' },
                { key: 'sf_per_unit', label: 'SF each', type: 'number', step: '1', align: 'right', default: 100 },
                { key: 'climate_controlled', label: 'Climate', type: 'checkbox', default: false },
                { key: 'access', label: 'Access', type: 'select', options: Object.entries(STORAGE_ACCESS).map(([value, label]) => ({ value, label })), default: 'interior' },
                { key: 'count', label: 'Units', type: 'number', step: '1', align: 'right', default: 0 },
                { key: 'occupied_units', label: 'Occupied', type: 'number', step: '1', align: 'right', default: 0 },
                { key: 'in_place_rate', label: 'In-place $/mo', type: 'number', step: '0.01', align: 'right', default: 0, asPercent: false },
                { key: 'street_rate', label: 'Street $/mo', type: 'number', step: '0.01', align: 'right', default: 0, asPercent: false },
                { key: 'stabilized_occupancy', label: 'Stabilized', type: 'number', step: '0.005', asPercent: true, align: 'right' },
            ],
            rows: working.unit_types,
            onSave: async ({ rows }, overlay) => {
                const clean = rows.map(({ id: _id, ...r }) => ({
                    ...r,
                    name: String(r.name || '').trim(),
                    stabilized_occupancy: r.stabilized_occupancy === '' || r.stabilized_occupancy == null ? null : r.stabilized_occupancy,
                }));
                if (!clean.length) throw new Error('Add at least one unit type.');
                if (clean.some(r => !r.name)) throw new Error('Each unit type needs a name.');
                const over = clean.find(r => Number(r.occupied_units) > Number(r.count));
                if (over) throw new Error(`${over.name}: occupied units exceed the unit count.`);
                overlay.remove();
                await save({ unit_types: clean });
            },
        });
    });

    document.getElementById('editStorageAssumptionsBtn')?.addEventListener('click', () => {
        const e = working.ecri || {};
        const initial = {
                street_rate_growth_pct: working.street_rate_growth_pct,
                street_rate_growth_schedule: working.street_rate_growth_schedule || [],
                monthly_move_out_pct: working.churn?.monthly_move_out_pct,
                ecri_enabled: !!e.enabled,
                first_after_months: e.first_after_months ?? 6,
                interval_months: e.interval_months ?? 12,
                increase_pct: e.increase_pct ?? 0,
                extra_move_out_pct: e.extra_move_out_pct ?? 0,
                first_month_discount_pct: working.concessions?.first_month_discount_pct,
                monthly_net_absorption_units: working.lease_up?.monthly_net_absorption_units,
                credit_loss_pct: working.credit_loss_pct,
        };
        showFormModal({
            title: 'Revenue assumptions',
            submitLabel: 'Save and re-run',
            initialValues: initial,
            fields: [
                { type: 'section', label: 'Street rates and move-outs' },
                { key: 'street_rate_growth_pct', label: 'Street rate growth / yr', type: 'number', step: '0.005', asPercent: true, half: true },
                { key: 'monthly_move_out_pct', label: 'Move-outs / month', type: 'number', step: '0.001', asPercent: true, half: true },
                { key: 'street_rate_growth_schedule', label: 'Growth by year (optional)', type: 'rateList', helpText: 'Year 1, Year 2, … in percent; the last rate carries forward. Overrides the single rate.' },
                { type: 'section', label: 'Existing-customer rate increases (ECRI)' },
                { key: 'ecri_enabled', label: 'Raise rates on existing customers', type: 'checkbox' },
                { key: 'first_after_months', label: 'First increase after (months)', type: 'number', step: '1', half: true, visibleWhen: v => v.ecri_enabled },
                { key: 'interval_months', label: 'Then every (months)', type: 'number', step: '1', half: true, visibleWhen: v => v.ecri_enabled },
                { key: 'increase_pct', label: 'Increase', type: 'number', step: '0.005', asPercent: true, half: true, visibleWhen: v => v.ecri_enabled },
                { key: 'extra_move_out_pct', label: 'Extra move-outs on increase', type: 'number', step: '0.005', asPercent: true, half: true, visibleWhen: v => v.ecri_enabled },
                { type: 'section', label: 'Move-ins and collections' },
                { key: 'first_month_discount_pct', label: 'Discount off first month', type: 'number', step: '0.05', asPercent: true, half: true },
                { key: 'credit_loss_pct', label: 'Credit loss', type: 'number', step: '0.005', asPercent: true, half: true },
                { key: 'monthly_net_absorption_units', label: 'Lease-up: most units gained per month (blank = already stabilized)', type: 'number', step: '0.5' },
            ],
            onSubmit: async (changed, overlay) => {
                // The form sends only changed fields when editing
                const v = { ...initial, ...changed };
                overlay.remove();
                await save({
                    street_rate_growth_pct: v.street_rate_growth_pct ?? 0,
                    street_rate_growth_schedule: v.street_rate_growth_schedule || [],
                    churn: { monthly_move_out_pct: v.monthly_move_out_pct ?? 0 },
                    ecri: {
                        enabled: !!v.ecri_enabled, first_after_months: v.first_after_months || 1,
                        interval_months: v.interval_months || 12, increase_pct: v.increase_pct ?? 0,
                        extra_move_out_pct: v.extra_move_out_pct ?? 0,
                    },
                    concessions: { first_month_discount_pct: v.first_month_discount_pct ?? 0 },
                    lease_up: { monthly_net_absorption_units: v.monthly_net_absorption_units || null },
                    credit_loss_pct: v.credit_loss_pct ?? 0,
                });
            },
        });
    });

    document.getElementById('editStorageAncillaryBtn')?.addEventListener('click', () => {
        showBulkTableEditorModal({
            title: 'Ancillary income',
            addLabel: 'Add income line',
            intro: 'Amount is $ (or a % for "% of rental income"). Participation is the share of customers, or the owner\'s share for tenant protection.',
            columns: [
                { key: 'name', label: 'Line', type: 'text', required: true, default: '' },
                { key: 'basis', label: 'Basis', type: 'select', options: Object.entries(STORAGE_BASIS).map(([value, label]) => ({ value, label })), default: 'per_occupied_unit_month' },
                { key: 'amount', label: 'Amount', type: 'number', step: '0.01', align: 'right', default: 0 },
                { key: 'participation_pct', label: 'Participation', type: 'number', step: '0.01', asPercent: true, align: 'right', default: 1 },
                { key: 'growth_pct', label: 'Growth / yr', type: 'number', step: '0.005', asPercent: true, align: 'right', default: 0 },
            ],
            rows: working.ancillary_lines,
            onSave: async ({ rows }, overlay) => {
                const clean = rows.map(({ id: _id, ...r }) => ({ ...r, name: String(r.name || '').trim() })).filter(r => r.name);
                const pct = clean.find(r => r.basis === 'pct_of_rental' && Number(r.amount) > 1);
                if (pct) throw new Error(`${pct.name}: enter the percent of rental as a fraction, e.g. 0.02 for 2%.`);
                overlay.remove();
                await save({ ancillary_lines: clean });
            },
        });
    });

    document.getElementById('convertStorageBtn')?.addEventListener('click', async () => {
        try {
            await api.post(`${modelUrl(property.id)}/self-storage/convert-rent-roll`, {});
            toast('Unit mix created from the rent roll. Check SF per unit before running.', 'success');
            propertyView({ id: property.id });
        } catch (err) { toast(apiErrorDetail(err), 'error'); }
    });
}
