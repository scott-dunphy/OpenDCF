/* ============================================================
   OpenDCF — Acquisition returns and sensitivity matrix
   Rendered inside the valuation view (see valuationView in app.js)
   ============================================================ */

function renderReturnsSection(km) {
    const r = km.returns;
    if (!r && km.direct_cap_value == null) return '';
    const card = (label, value) => `
        <div class="metric-card">
            <div class="metric-label">${label}</div>
            <div class="metric-value">${value}</div>
        </div>`;
    const pctOrDash = v => (v != null ? fmt.pct(v) : '—');
    const multOrDash = v => (v != null ? fmt.multiple(v) : '—');
    const ratioOrDash = v => (v != null ? parseFloat(v).toFixed(2) + 'x' : '—');
    const irrCard = (prefix, values) => {
        const xirr = values[`${prefix}_xirr`];
        const periodic = values[`${prefix}_irr`];
        const mirr = values[`${prefix}_mirr`];
        let html = card(`${prefix === 'unlevered' ? 'Unlevered' : 'Levered'} XIRR`, pctOrDash(xirr));
        html += card(`${prefix === 'unlevered' ? 'Unlevered' : 'Levered'} Periodic IRR`, pctOrDash(periodic));
        if (mirr != null) html += card(`${prefix === 'unlevered' ? 'Unlevered' : 'Levered'} MIRR`, pctOrDash(mirr));
        return html;
    };
    const irrWarning = (prefix, values) => {
        const label = prefix === 'unlevered' ? 'Unlevered' : 'Levered';
        const status = values[`${prefix}_irr_status`];
        const roots = values[`${prefix}_irr_roots`] || [];
        const xStatus = values[`${prefix}_xirr_status`];
        const xRoots = values[`${prefix}_xirr_roots`] || [];
        if (!['multiple', 'no_root', 'no_sign_change'].includes(status)
            && !['multiple', 'no_root', 'no_sign_change'].includes(xStatus)) return '';
        const rootText = roots.length ? roots.map(pctOrDash).join(', ') : 'none';
        const xRootText = xRoots.length ? xRoots.map(pctOrDash).join(', ') : 'none';
        return `<div class="alert alert-warning" style="margin-top:12px">
            <strong>${label} return warning:</strong>
            Periodic IRR status is ${escapeHtmlAttr(status || 'unknown')} (roots: ${escapeHtmlAttr(rootText)});
            XIRR status is ${escapeHtmlAttr(xStatus || 'unknown')} (roots: ${escapeHtmlAttr(xRootText)}).
            MIRR is shown as the single reinvestment-rate-based alternative.
        </div>`;
    };

    let cards = '';
    if (km.direct_cap_value != null) cards += card('Direct Cap Value', fmt.currency(km.direct_cap_value));
    if (r) {
        cards += card('Purchase Price', fmt.currency(r.purchase_price));
        cards += card('NPV at Price', fmt.currency(r.npv_at_price));
        cards += irrCard('unlevered', r);
        cards += card('Unlevered Multiple', multOrDash(r.unlevered_equity_multiple));
        if (parseFloat(r.loan_amount) > 0) {
            cards += irrCard('levered', r);
            cards += card('Levered Multiple', multOrDash(r.levered_equity_multiple));
            cards += card('Equity Invested', fmt.currency(r.equity_invested));
            cards += card('LTV', pctOrDash(r.loan_to_value));
            cards += card('Yr 1 DSCR', ratioOrDash(r.year1_dscr));
            cards += card('Min DSCR', ratioOrDash(r.min_dscr));
            cards += card('Yr 1 Debt Yield', pctOrDash(r.year1_debt_yield));
            cards += card('Yr 1 Cash-on-Cash', pctOrDash(r.year1_cash_on_cash));
            cards += card('Loan Payoff at Sale', fmt.currency(r.loan_payoff_at_sale));
        }
    }
    return `
        <div class="section-header">
            <h3 class="section-title">Acquisition Returns</h3>
        </div>
        <div class="metrics-grid">${cards}</div>
        ${r ? irrWarning('unlevered', r) : ''}
        ${r && parseFloat(r.loan_amount) > 0 ? irrWarning('levered', r) : ''}`;
}

async function loadSensitivitySection(valuationId, discountStep = 0.0025, capStep = 0.0025, steps = 2) {
    const el = document.getElementById('sensitivitySection');
    if (!el) return;
    let m;
    try {
        m = await api.get(`/valuations/${valuationId}/reports/sensitivity?discount_step=${discountStep}&exit_cap_step=${capStep}&steps=${steps}`);
    } catch (err) {
        // Stale results: say why the grid is missing; unsupported types just omit it
        el.innerHTML = /re-run/.test(err.message || '')
            ? `<p class="muted" style="margin:16px 0">Sensitivity: ${escapeHtmlAttr(err.message)}.</p>` : '';
        return;
    }
    const centerRow = Math.floor(m.discount_rates.length / 2);
    const centerCol = Math.floor(m.exit_cap_rates.length / 2);
    const hasIrr = m.irr_by_exit_cap.some(v => v != null);
    el.innerHTML = `
        <div class="section-header">
            <h3 class="section-title">Value Sensitivity: Discount Rate × Exit Cap</h3>
            <div style="display:flex;gap:8px;align-items:center">
                <label class="form-label" style="margin:0">Step (bp)</label>
                <select class="form-input" id="sensStep" style="width:auto">
                    ${[10, 25, 50].map(bp => `<option value="${bp / 10000}" ${Math.abs(bp / 10000 - capStep) < 1e-9 ? 'selected' : ''}>${bp}</option>`).join('')}
                </select>
            </div>
        </div>
        <div class="data-table-wrap">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Discount \\ Exit Cap</th>
                        ${m.exit_cap_rates.map(c => `<th style="text-align:right">${fmt.pct(c)}</th>`).join('')}
                    </tr>
                </thead>
                <tbody>
                    ${m.values.map((row, i) => `
                        <tr>
                            <td><strong>${fmt.pct(m.discount_rates[i])}</strong></td>
                            ${row.map((v, j) => `<td style="text-align:right;${i === centerRow && j === centerCol ? 'font-weight:700;color:var(--accent)' : ''}">${fmt.currency(v)}</td>`).join('')}
                        </tr>`).join('')}
                    ${hasIrr ? `
                        <tr>
                            <td><em>Unlevered IRR at price</em></td>
                            ${m.irr_by_exit_cap.map(v => `<td style="text-align:right"><em>${v != null ? fmt.pct(v) : '—'}</em></td>`).join('')}
                        </tr>` : ''}
                </tbody>
            </table>
        </div>`;
    document.getElementById('sensStep').onchange = e => {
        const step = parseFloat(e.target.value);
        loadSensitivitySection(valuationId, step, step, steps);
    };
}

async function loadComparableSalesTab(property) {
    const el = document.getElementById('comparableSalesSection');
    if (!el) return;
    el.innerHTML = '<div class="loading-spinner"></div>';
    try {
        const [sales, selected, manual] = await Promise.all([
            api.get(`/comparable-sales?property_type=${encodeURIComponent(property.property_type)}&limit=250`),
            api.get(`/properties/${property.id}/comparable-sales`),
            api.get(`/properties/${property.id}/comparable-analysis/manual`),
        ]);
        const selectedBySale = Object.fromEntries(selected.map(s => [s.sale_id, s]));
        const manualWarnings = (manual.warnings || []).map(w => `<div class="alert alert-warning">${escapeHtmlAttr(w)}</div>`).join('');
        el.innerHTML = `
            <div class="section-header">
                <div><h3 class="section-title">Sales Comparison & Statistical Calibration</h3>
                <p class="page-subtitle">Verified transactions, explicit adjustments, amenity-aware price modeling, and reconciliation.</p></div>
                <div style="display:flex;gap:8px">
                    <button class="btn btn-secondary btn-sm" id="editAmenitiesBtn">Edit Subject Amenities</button>
                    <button class="btn btn-primary btn-sm" id="newComparableBtn">Add Comparable Sale</button>
                </div>
            </div>
            <div class="kpi-row" style="margin-bottom:20px">
                <div class="kpi-card"><div class="kpi-label">Selected Comps</div><div class="kpi-value">${selected.filter(s => s.included).length}</div></div>
                <div class="kpi-card"><div class="kpi-label">Weighted Price / ${escapeHtmlAttr(property.area_unit)}</div><div class="kpi-value">${manual.weighted_price_per_area != null ? fmt.currency(manual.weighted_price_per_area) : '—'}</div></div>
                <div class="kpi-card"><div class="kpi-label">Sales Comparison Value</div><div class="kpi-value green">${manual.indicated_value != null ? fmt.currency(manual.indicated_value) : '—'}</div></div>
            </div>
            ${manualWarnings}
            <div style="display:flex;gap:8px;margin-bottom:16px">
                <button class="btn btn-primary btn-sm" id="runStatModelBtn">Run Statistical Model</button>
                <label class="form-label" style="margin:6px 0 0 8px">Occupancy</label>
                <input class="form-input" id="statOccupancy" type="number" step="0.01" value="0.90" style="width:90px">
                <label class="form-label" style="margin:6px 0 0 8px">Normalized NOI</label>
                <input class="form-input" id="statNoi" type="number" step="1000" style="width:150px">
            </div>
            <div id="statModelResult"></div>
            <div class="data-table-wrap"><table class="data-table">
                <thead><tr><th>Property</th><th>Sale Date</th><th>Market</th><th class="right">Price</th><th class="right">Price/${escapeHtmlAttr(property.area_unit)}</th><th class="right">Cap Rate</th><th>Verification</th><th></th></tr></thead>
                <tbody>${sales.map(s => {
                    const selection = selectedBySale[s.id];
                    return `<tr><td><strong>${escapeHtmlAttr(s.property_name)}</strong><div class="table-subtext">${escapeHtmlAttr(JSON.stringify(s.amenities || {}))}</div></td>
                    <td>${fmt.date(s.sale_date)}</td><td>${escapeHtmlAttr(s.market || s.city || '—')}</td>
                    <td class="right">${fmt.currency(s.sale_price)}</td><td class="right">${fmt.currency(s.price_per_area)}</td>
                    <td class="right">${s.going_in_cap_rate != null ? fmt.pct(s.going_in_cap_rate) : '—'}</td>
                    <td>${escapeHtmlAttr(s.verification_status.replaceAll('_', ' '))}</td>
                    <td><button class="btn btn-secondary btn-sm" data-select-comp="${s.id}">${selection ? 'Edit Selection' : 'Select'}</button></td></tr>`;
                }).join('') || '<tr><td colspan="8" class="empty-state">No comparable sales yet.</td></tr>'}</tbody>
            </table></div>`;

        document.getElementById('editAmenitiesBtn').onclick = () => showFormModal({
            title: 'Subject Amenities',
            fields: [{ key: 'amenities_json', label: 'Amenities JSON', type: 'textarea', required: true }],
            initialValues: { amenities_json: JSON.stringify(property.amenities || {}, null, 2) },
            onSubmit: async (values, overlay) => {
                let amenities;
                // Left unchanged, the edit form passes no amenities_json
                const text = values.amenities_json ?? JSON.stringify(property.amenities || {});
                try { amenities = JSON.parse(text || '{}'); } catch { throw new Error('Amenities must be valid JSON'); }
                await api.put(`/properties/${property.id}`, { amenities });
                property.amenities = amenities;
                overlay.remove();
                loadComparableSalesTab(property);
            },
        });
        document.getElementById('newComparableBtn').onclick = () => showComparableSaleModal(property);
        document.querySelectorAll('[data-select-comp]').forEach(btn => btn.onclick = () => {
            const sale = sales.find(s => s.id === btn.dataset.selectComp);
            showComparableSelectionModal(property, sale, selectedBySale[sale.id]);
        });
        document.getElementById('runStatModelBtn').onclick = async () => {
            const target = document.getElementById('statModelResult');
            target.innerHTML = '<div class="loading-spinner"></div>';
            const occupancy = document.getElementById('statOccupancy').value;
            const noi = document.getElementById('statNoi').value;
            const result = await api.post(`/properties/${property.id}/comparable-analysis/statistical`, {
                occupancy_pct: occupancy || null, normalized_noi: noi || null,
            });
            target.innerHTML = renderStatisticalComparableResult(result, property.area_unit);
        };
    } catch (err) {
        el.innerHTML = `<div class="alert alert-error">Unable to load comparable sales: ${escapeHtmlAttr(err.message)}</div>`;
    }
}

function showComparableSaleModal(property) {
    showFormModal({
        title: 'Add Comparable Sale',
        fields: [
            { key: 'property_name', label: 'Property Name', type: 'text', required: true },
            { key: 'sale_date', label: 'Sale Date', type: 'date', required: true, half: true },
            { key: 'sale_price', label: 'Sale Price', type: 'number', required: true, half: true },
            { key: 'area', label: `Area (${property.area_unit})`, type: 'number', required: true, half: true },
            { key: 'market', label: 'Market', type: 'text', half: true },
            { key: 'submarket', label: 'Submarket', type: 'text', half: true },
            { key: 'year_built', label: 'Year Built', type: 'number', half: true },
            { key: 'occupancy_pct', label: 'Occupancy', type: 'number', step: '0.01', half: true },
            { key: 'normalized_noi', label: 'Normalized NOI', type: 'number', half: true },
            { key: 'source', label: 'Source', type: 'text', required: true },
            { key: 'verification_status', label: 'Verification', type: 'select', default: 'unverified', options: [
                { value: 'unverified', label: 'Unverified' }, { value: 'partially_verified', label: 'Partially Verified' }, { value: 'verified', label: 'Verified' },
            ]},
            { key: 'amenities_json', label: 'Amenities JSON', type: 'textarea' },
        ],
        onSubmit: async (values, overlay) => {
            let amenities = {};
            try { amenities = JSON.parse(values.amenities_json || '{}'); } catch { throw new Error('Amenities must be valid JSON'); }
            delete values.amenities_json;
            await api.post('/comparable-sales', { ...values, property_type: property.property_type, area_unit: property.area_unit, amenities });
            overlay.remove();
            loadComparableSalesTab(property);
        },
    });
}

function showComparableSelectionModal(property, sale, selection) {
    const initial = {
        weight: selection?.weight || 1, included: selection?.included ?? true,
        adjustments_json: JSON.stringify(selection?.adjustments || {}, null, 2), rationale: selection?.rationale || '',
    };
    showFormModal({
        title: `Adjust ${sale.property_name}`,
        fields: [
            { key: 'weight', label: 'Weight', type: 'number', default: 1, half: true },
            { key: 'included', label: 'Include', type: 'checkbox', default: true, half: true },
            { key: 'adjustments_json', label: 'Percentage Adjustments JSON', type: 'textarea', helpText: 'Example: {"market_time": 0.03, "condition": -0.05}' },
            { key: 'rationale', label: 'Adjustment Rationale', type: 'textarea' },
        ],
        initialValues: initial,
        onSubmit: async (changed, overlay) => {
            // Edit mode passes only changed fields; the PUT needs the whole selection
            const values = { ...initial, ...changed };
            let adjustments;
            try { adjustments = JSON.parse(values.adjustments_json || '{}'); } catch { throw new Error('Adjustments must be valid JSON'); }
            delete values.adjustments_json;
            await api.put(`/properties/${property.id}/comparable-sales/${sale.id}`, { ...values, adjustments });
            overlay.remove();
            loadComparableSalesTab(property);
        },
    });
}

function renderStatisticalComparableResult(result, areaUnit) {
    if (result.status !== 'ok') return `<div class="alert alert-warning">${escapeHtmlAttr((result.warnings || []).join(' '))}</div>`;
    return `<div class="card" style="margin-bottom:20px"><div class="kpi-row">
        <div class="kpi-card"><div class="kpi-label">Estimated Price / ${escapeHtmlAttr(areaUnit)}</div><div class="kpi-value">${fmt.currency(result.estimated_price_per_area)}</div></div>
        <div class="kpi-card"><div class="kpi-label">Statistical Value</div><div class="kpi-value green">${fmt.currency(result.indicated_value)}</div></div>
        <div class="kpi-card"><div class="kpi-label">95% Prediction Range</div><div class="kpi-value" style="font-size:18px">${fmt.currency(result.prediction_low)} – ${fmt.currency(result.prediction_high)}</div></div>
        <div class="kpi-card"><div class="kpi-label">Confidence / Sample</div><div class="kpi-value" style="font-size:18px">${escapeHtmlAttr(result.confidence)} · ${result.observation_count}</div><div class="kpi-subtext">MAPE ${fmt.pct(result.model_mape)}</div></div>
    </div>${(result.warnings || []).map(w => `<div class="alert alert-warning">${escapeHtmlAttr(w)}</div>`).join('')}
    <details><summary>Model coefficients and diagnostics</summary><pre>${escapeHtmlAttr(JSON.stringify(result.coefficients, null, 2))}</pre></details></div>`;
}
