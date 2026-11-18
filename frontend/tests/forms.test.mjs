// Form behavior that has caused data loss: edit forms pass onSubmit only the changed fields, and
// number fields are shown and parsed as percents by key name.
import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { loadApp, source, SCRIPTS, submitModal, setField } from './harness.mjs';

const w = loadApp();
const api = w.eval('api');
after(() => w.close());

function captureApi(method) {
    const calls = [];
    const original = api[method];
    api[method] = async (url, body) => { calls.push({ url, body }); return { id: 'saved' }; };
    return { calls, restore: () => { api[method] = original; } };
}

test('an edit form passes only changed fields; withUnchanged fills in the rest', async () => {
    const fields = [
        { key: 'name', label: 'Name', type: 'text' },
        { key: 'amount', label: 'Amount', type: 'number' },
    ];
    const record = { id: 'r1', name: 'Roof', amount: '5000' };
    let received;
    w.showFormModal({ title: 'T', fields, initialValues: record, onSubmit: async (data, ov) => { received = data; ov.remove(); } });
    setField(w, 'amount', '6000');
    await submitModal(w);
    assert.deepEqual({ ...received }, { amount: 6000 });
    assert.deepEqual({ ...w.withUnchanged(fields, record, received) }, { name: 'Roof', amount: 6000 });
});

test('a percent field shows the stored fraction as a percent and saves a fraction', async () => {
    let received;
    w.showFormModal({
        title: 'T', fields: [{ key: 'ownership_pct', label: 'Ownership (%)', type: 'number' }],
        initialValues: { ownership_pct: '0.500000' }, onSubmit: async (data, ov) => { received = data; ov.remove(); },
    });
    assert.equal(w.document.getElementById('form_ownership_pct').value, '50.00');
    setField(w, 'ownership_pct', '40');
    await submitModal(w);
    assert.equal(received.ownership_pct, 0.4);
});

test('editing a loan keeps the fields the user did not touch', async () => {
    const get = api.get;
    api.get = async (url) => (url.startsWith('/properties') ? [{ id: 'p1', name: 'Tower' }] : []);
    const put = captureApi('put');
    try {
        const loan = {
            id: 'l1', property_id: 'p1', name: 'Senior loan', lien_position: 2, recourse: true,
            origination_date: '2022-01-01', maturity_date: '2032-01-01', original_balance: '10000000.00',
            rate_type: 'fixed', coupon: '0.065000', spread: null, amortization_months: 360, io_months: 24,
            extension_count: 1, extension_months: 12, delinquency_status: '60', comment: null,
        };
        await w.openLoanForm(loan, { onSaved: () => {} });
        setField(w, 'name', 'Senior loan A');
        await submitModal(w);
        const body = put.calls[0].body;
        assert.equal(body.name, 'Senior loan A');
        assert.equal(body.coupon, '0.065000');
        assert.equal(body.recourse, true);
        assert.equal(body.io_months, 24);
        assert.equal(body.lien_position, 2);
        assert.equal(body.extension_count, 1);
        assert.equal(body.delinquency_status, '60');
    } finally {
        api.get = get;
        put.restore();
    }
});

test('editing a comparable selection keeps its adjustments', async () => {
    const put = captureApi('put');
    const load = w.loadComparableSalesTab;
    w.loadComparableSalesTab = () => {};
    try {
        w.showComparableSelectionModal({ id: 'p1' }, { id: 's1', property_name: 'Comp A' },
            { weight: 2, included: true, adjustments: { condition: -0.05 }, rationale: 'old' });
        setField(w, 'rationale', 'new');
        await submitModal(w);
        assert.deepEqual({ ...put.calls[0].body.adjustments }, { condition: -0.05 });
        assert.equal(put.calls[0].body.weight, 2);
    } finally {
        w.loadComparableSalesTab = load;
        put.restore();
    }
});

test('no dollar-labelled number field is treated as a percent', () => {
    // Field literals in the scripts: { key: 'x', label: '...', ... type: 'number' ... }
    const literal = /\{\s*key:\s*'([a-z0-9_]+)',\s*label:\s*'([^']*)'([^}]*)\}/g;
    const wrong = [];
    for (const name of SCRIPTS) {
        for (const [, key, label, rest] of source(name).matchAll(literal)) {
            if (!/type:\s*'number'/.test(rest) || !label.includes('$')) continue;
            const asPercent = /asPercent:\s*true/.test(rest) ? true : /asPercent:\s*false/.test(rest) ? false : undefined;
            if (w.isPercentNumberField({ key, label, type: 'number', asPercent })) wrong.push(`${name}: ${key} '${label}'`);
        }
    }
    assert.deepEqual(wrong, []);
});

test('a field with a tip gets an underlined label carrying the tip', () => {
    w.showFormModal({
        title: 'T', fields: [{ key: 'discount_rate', label: 'Discount Rate', type: 'number' }],
        onSubmit: async () => {},
    });
    const tip = w.document.querySelector('.modal .form-label .has-tip');
    assert.ok(tip, 'label has a tip');
    assert.equal(tip.getAttribute('data-tip'), w.fieldTip({ key: 'discount_rate', label: 'Discount Rate' }));
    w.document.querySelector('.modal-overlay').remove();
});

test('a grid cell the user blanked is sent as null; cells blank all along are left out', () => {
    const columns = [
        { key: 'comment', label: 'Comment', type: 'text' },
        { key: 'description', label: 'Description', type: 'text' },
        { key: 'recovery_structure_id', label: 'Recovery', type: 'select', sendBlank: true },
    ];
    const row = { id: 'e1', comment: '', description: '', recovery_structure_id: '' };
    const stored = { id: 'e1', comment: 'source note', description: null, recovery_structure_id: 'rs1' };
    assert.deepEqual({ ...w.buildPayloadFromBulkRow(row, columns, stored) }, { comment: null, recovery_structure_id: '' });
    assert.deepEqual({ ...w.buildPayloadFromBulkRow({ ...row, id: null }, columns) }, { recovery_structure_id: '' });
});
