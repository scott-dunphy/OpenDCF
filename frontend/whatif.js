// ─── Valuation what-if panel ─────────────────────────────────
// Reprices the last completed run at another discount rate / exit cap via
// GET /valuations/{id}/reports/what-if. Nothing is saved unless the user
// saves the rates as a new scenario (duplicate, update rates, run).

function renderWhatIfPanel(host, { valuation, km, property, stale = false }) {
    if (!host) return;
    const savedRate = parseFloat(valuation.discount_rate) * 100;
    const savedCap = parseFloat(valuation.exit_cap_rate) * 100;
    const savedValue = parseFloat(km.npv);
    const round2 = n => Math.round(n * 100) / 100;
    const rateText = n => String(parseFloat(n.toFixed(4))); // keeps e.g. 6.875 exact
    const bounds = (saved, span) => ({ min: Math.max(0.25, round2(saved - span)), max: round2(saved + span) });

    const control = (key, label, saved, { min, max }) => `
        <div class="ws3-whatif-control">
            <div class="ws3-whatif-control-head">
                <label for="wi${key}Num">${label}</label>
                <span class="ws3-whatif-saved">Saved ${saved.toFixed(2)}%</span>
            </div>
            <div class="ws3-whatif-inputs">
                <input type="range" id="wi${key}" min="${min}" max="${max}" step="0.05" value="${saved}" aria-label="${label}">
                <span class="ws3-whatif-num">
                    <input type="number" id="wi${key}Num" class="form-input" min="0.01" max="99.99" step="any" value="${rateText(saved)}">
                    <span aria-hidden="true">%</span>
                </span>
            </div>
        </div>`;

    host.innerHTML = `
        <section class="ws3-whatif" aria-labelledby="wiTitle">
            <div class="ws3-whatif-head">
                <h3 class="section-title" id="wiTitle">What-if</h3>
                <span class="ws3-badge-unsaved">Not saved</span>
            </div>
            <p class="ws3-whatif-note">Reprices this run's cash flows at other rates.${stale ? ' Results are out of date: re-run the valuation to use what-if.' : ''}</p>
            ${control('Rate', 'Discount rate', savedRate, bounds(savedRate, 5))}
            ${control('Cap', 'Exit cap rate', savedCap, bounds(savedCap, 3))}
            <div class="ws3-whatif-result" aria-live="polite">
                <div class="ws3-whatif-value" data-wi-value>${fmt.currencyExact(savedValue)}</div>
                <div class="ws3-whatif-sub" data-wi-sub></div>
                <div class="ws3-whatif-delta" data-wi-delta>Same as saved</div>
                <dl class="ws3-whatif-meta" data-wi-meta></dl>
            </div>
            <div class="ws3-whatif-actions">
                <button type="button" class="btn btn-secondary btn-sm" data-wi-reset>Reset to saved</button>
                <button type="button" class="btn btn-primary btn-sm" data-wi-save disabled>Save as scenario</button>
            </div>
        </section>`;

    const $ = sel => host.querySelector(sel);
    const rateRange = $('#wiRate'), rateNum = $('#wiRateNum');
    const capRange = $('#wiCap'), capNum = $('#wiCapNum');
    const saveBtn = $('[data-wi-save]');
    let timer = null;
    let seq = 0;

    const current = () => ({ rate: parseFloat(rateNum.value), cap: parseFloat(capNum.value) });
    const valid = ({ rate, cap }) => rate > 0 && rate < 100 && cap > 0 && cap < 100;
    const isSaved = ({ rate, cap }) => Math.abs(rate - savedRate) < 1e-6 && Math.abs(cap - savedCap) < 1e-6;

    function showResult(r) {
        const value = parseFloat(r.value);
        const delta = parseFloat(r.change_vs_saved);
        const perArea = valuePerAreaLabel(value, property);
        $('[data-wi-value]').textContent = fmt.currencyExact(value);
        $('[data-wi-sub]').textContent = perArea;
        const deltaEl = $('[data-wi-delta]');
        deltaEl.classList.remove('ws3-up', 'ws3-down');
        if (Math.abs(delta) < 0.5) {
            deltaEl.textContent = 'Same as saved';
        } else {
            const pct = savedValue ? ` (${delta > 0 ? '+' : ''}${(delta / savedValue * 100).toFixed(1)}%)` : '';
            deltaEl.textContent = `${delta > 0 ? '+' : '−'}${fmt.currencyExact(Math.abs(delta))}${pct} vs saved`;
            deltaEl.classList.add(delta > 0 ? 'ws3-up' : 'ws3-down');
        }
        $('[data-wi-meta]').innerHTML = `
            <div><dt>Terminal value</dt><dd>${fmt.currency(r.terminal_value)}</dd></div>
            ${r.irr != null ? `<div><dt>IRR at price</dt><dd>${fmt.pct(r.irr)}</dd></div>` : ''}`;
    }

    async function refresh() {
        const rates = current();
        saveBtn.disabled = !valid(rates) || isSaved(rates);
        if (!valid(rates)) {
            $('[data-wi-delta]').textContent = 'Enter rates between 0% and 100%';
            return;
        }
        const mine = ++seq;
        host.querySelector('.ws3-whatif-result').classList.add('is-pending');
        try {
            const r = await api.get(`/valuations/${valuation.id}/reports/what-if`
                + `?discount_rate=${(rates.rate / 100).toFixed(6)}&exit_cap_rate=${(rates.cap / 100).toFixed(6)}`);
            if (mine !== seq) return; // a newer request superseded this one
            showResult(r);
        } catch (err) {
            if (mine !== seq) return;
            $('[data-wi-delta]').textContent = 'Could not reprice: ' + err.message;
        } finally {
            if (mine === seq) host.querySelector('.ws3-whatif-result')?.classList.remove('is-pending');
        }
    }
    const schedule = () => { clearTimeout(timer); timer = setTimeout(refresh, 150); };

    const link = (range, num) => {
        range.addEventListener('input', () => { num.value = parseFloat(range.value).toFixed(2); schedule(); });
        num.addEventListener('input', () => {
            const v = parseFloat(num.value);
            if (!isNaN(v)) range.value = v;
            schedule();
        });
    };
    link(rateRange, rateNum);
    link(capRange, capNum);

    $('[data-wi-reset]').onclick = () => {
        rateRange.value = savedRate; rateNum.value = rateText(savedRate);
        capRange.value = savedCap; capNum.value = rateText(savedCap);
        schedule();
    };

    saveBtn.onclick = async () => {
        const { rate, cap } = current();
        if (!valid({ rate, cap })) return;
        saveBtn.disabled = true;
        saveBtn.textContent = 'Saving…';
        let copy;
        try {
            copy = await api.post(`/valuations/${valuation.id}/duplicate`, {});
            await api.put(`/valuations/${copy.id}`, {
                name: `${valuation.name} (${rate.toFixed(2)}% / ${cap.toFixed(2)}%)`.slice(0, 255),
                discount_rate: (rate / 100).toFixed(6),
                exit_cap_rate: (cap / 100).toFixed(6),
            });
        } catch (err) {
            if (copy) await api.del(`/valuations/${copy.id}`).catch(() => {});
            toast('Could not save scenario: ' + err.message, 'error');
            saveBtn.textContent = 'Save as scenario';
            saveBtn.disabled = false;
            return;
        }
        try {
            await api.post(`/valuations/${copy.id}/run`);
            toast('Scenario saved and run', 'success');
        } catch (err) {
            toast('Scenario saved, but the run failed: ' + err.message, 'error');
        }
        window.location.hash = `#/valuation/${copy.id}`;
    };

    refresh();
}

// ─── What-if chat ────────────────────────────────────────────
// POST /valuations/{id}/what-if-chat: the AI turns a question into temporary model changes
// and the engine prices them against the saved model. Nothing is saved.

const WHAT_IF_FIELD_LABELS = {
    market_rent_per_unit: 'Market rent', rent_growth_rate_pct: 'Rent growth', renewal_probability: 'Renewal probability',
    downtime_months: 'Downtime (months)', new_lease_term_months: 'New lease term (months)',
    renewal_lease_term_months: 'Renewal term (months)', general_vacancy_pct: 'General vacancy', credit_loss_pct: 'Credit loss',
    discount_rate: 'Discount rate', exit_cap_rate: 'Exit cap rate', exit_costs_pct: 'Exit costs', cpi_rate: 'CPI',
    capital_reserves_per_unit: 'Capital reserves', purchase_price: 'Purchase price', direct_cap_rate: 'Direct cap rate',
    base_rent_per_unit: 'Rent', escalation_pct_annual: 'Escalation', renewal_rent_spread_pct: 'Renewal rent spread',
    lease_start_date: 'Lease start', lease_end_date: 'Lease end', upon_expiration: 'At expiry', recovery_type: 'Recovery',
};
const WHAT_IF_PCT_FIELDS = new Set(['rent_growth_rate_pct', 'renewal_probability', 'general_vacancy_pct', 'credit_loss_pct',
    'discount_rate', 'exit_cap_rate', 'exit_costs_pct', 'cpi_rate', 'direct_cap_rate', 'escalation_pct_annual', 'renewal_rent_spread_pct']);

function whatIfValueText(field, value) {
    if (value == null || value === '') return '—';
    if (WHAT_IF_PCT_FIELDS.has(field)) return fmt.pct(value, 2);
    if (/rent_per_unit|price|reserves/.test(field)) return fmt.currency(value, 2);
    return String(value);
}

function whatIfResultHtml(result) {
    const base = result.base, next = result.result;
    const changes = result.changes.map(c => `<li>${escapeHtmlAttr(c.label)}: ${escapeHtmlAttr(WHAT_IF_FIELD_LABELS[c.field] || c.field)}
        ${escapeHtmlAttr(whatIfValueText(c.field, c.old_value))} → <strong>${escapeHtmlAttr(whatIfValueText(c.field, c.new_value))}</strong></li>`);
    const shown = changes.length > 6 ? [...changes.slice(0, 5), `<li>and ${changes.length - 5} more</li>`] : changes;
    let impact = '';
    if (base && next) {
        const delta = parseFloat(next.value) - parseFloat(base.value);
        const pct = parseFloat(base.value) ? delta / Math.abs(parseFloat(base.value)) : 0;
        const sign = delta > 0 ? '+' : '';
        const row = (label, a, b, f) => `<tr><td>${label}</td><td>${f(a)}</td><td>${f(b)}</td></tr>`;
        impact = `<div class="whatif-chat-headline ${delta < 0 ? 'down' : delta > 0 ? 'up' : ''}">
                Value ${sign}${fmt.currencyExact(delta)} (${sign}${(pct * 100).toFixed(1)}%)</div>
            <table class="whatif-chat-table"><thead><tr><th></th><th>Saved model</th><th>What if</th></tr></thead><tbody>
            ${row('Value', base.value, next.value, v => fmt.currencyExact(v))}
            ${base.irr != null || next.irr != null ? row('IRR', base.irr, next.irr, v => fmt.pct(v)) : ''}
            ${row('Year 1 NOI', base.year1_noi, next.year1_noi, v => fmt.currencyExact(v))}
            ${row('NOI over hold', base.total_noi, next.total_noi, v => fmt.currency(v))}
            ${row('Avg occupancy', base.avg_occupancy_pct, next.avg_occupancy_pct, v => fmt.pct(v, 1))}
            </tbody></table>`;
        if (Math.abs(delta) < 0.5) impact += '<small>No change in value. Leases with their own terms may override this assumption.</small>';
    }
    return `<div>${escapeHtmlAttr(result.scenario)}</div>${shown.length ? `<ul>${shown.join('')}</ul>` : ''}${impact}
        ${base ? '<small>Not saved. The valuation is unchanged.</small>' : ''}`;
}

function wireWhatIfChat(valuationId) {
    const button = document.getElementById('valWhatIfChatBtn');
    if (!button) return;
    button.onclick = () => {
        document.getElementById('whatIfChat')?.remove();
        const history = [];
        const panel = document.createElement('aside');
        panel.id = 'whatIfChat';
        panel.className = 'copilot-panel';
        panel.innerHTML = `
            <div class="copilot-head"><div><strong>What if…</strong><small>Test a change on the engine. The valuation is never changed.</small></div><button class="btn btn-sm" data-close aria-label="Close">×</button></div>
            <div class="copilot-messages"><div class="copilot-msg ai">Try “What if market rent is 10% lower?”, “What if renewal probability drops to 50%?” or “What if the exit cap is 25 bps higher?”</div></div>
            <form class="copilot-form"><textarea rows="2" placeholder="What if…" required></textarea><button class="btn btn-primary" type="submit">Ask</button></form>`;
        document.body.appendChild(panel);
        const messages = panel.querySelector('.copilot-messages');
        const input = panel.querySelector('textarea');
        panel.querySelector('[data-close]').onclick = () => panel.remove();
        input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); panel.querySelector('form').requestSubmit(); } });
        input.focus();
        panel.querySelector('form').onsubmit = async event => {
            event.preventDefault();
            const message = input.value.trim();
            if (!message) return;
            input.value = '';
            messages.insertAdjacentHTML('beforeend', `<div class="copilot-msg user">${escapeHtmlAttr(message)}</div>`);
            const card = document.createElement('div');
            card.className = 'copilot-msg ai';
            card.innerHTML = '<span class="intake-spinner"></span> Running the scenario…';
            messages.appendChild(card);
            messages.scrollTop = messages.scrollHeight;
            try {
                const result = await api.post(`/valuations/${valuationId}/what-if-chat`, { message, history: history.slice(-6) });
                card.innerHTML = whatIfResultHtml(result);
                history.push(`${message} => ${result.scenario}`);
            } catch (err) {
                card.textContent = apiErrorDetail(err);
            }
            messages.scrollTop = messages.scrollHeight;
        };
    };
}
