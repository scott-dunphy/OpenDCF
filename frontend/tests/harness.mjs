// Loads the real frontend scripts into a jsdom window, as the browser does (classic scripts sharing
// one global scope), with Chart.js and the network stubbed. Tests call the app's own functions.
import { readFileSync } from 'node:fs';
import { JSDOM } from 'jsdom';

const ROOT = new URL('../', import.meta.url);
export const SCRIPTS = ['tips.js', 'app.js', 'dialogs.js', 'returns.js', 'storage.js', 'portfolios.js', 'loans.js'];

export function source(name) {
    return readFileSync(new URL(name, ROOT), 'utf8');
}

// Any property read or call on the stub returns the stub, so Chart.defaults.x.y = ... works
function chartStub() {
    const stub = new Proxy(function () {}, {
        get: (target, prop) => (prop in target ? target[prop] : stub),
        set: () => true,
        apply: () => stub,
        construct: () => stub,
    });
    return stub;
}

export function loadApp() {
    // The real page shell, without its external scripts and stylesheets
    const shell = source('index.html').replace(/<script[\s\S]*?<\/script>/g, '').replace(/<link[^>]*>/g, '');
    const dom = new JSDOM(shell, {
        url: 'http://localhost/',
        runScripts: 'dangerously',
        pretendToBeVisual: true,
    });
    const { window } = dom;
    window.Chart = chartStub();
    window.fetch = async () => ({ ok: true, status: 200, json: async () => [], headers: new Map() });
    window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
    const errors = [];
    window.addEventListener('error', (e) => errors.push(e.error || e.message));
    for (const name of SCRIPTS) {
        const el = window.document.createElement('script');
        el.textContent = source(name);
        window.document.body.appendChild(el);
    }
    if (errors.length) throw errors[0];
    return window;
}

// Submit the open form modal and resolve once its onSubmit has run
export async function submitModal(window) {
    const btn = [...window.document.querySelectorAll('.modal button')].find(b => /Save|Create|Update/.test(b.textContent));
    btn.click();
    await new Promise(r => setTimeout(r, 20));
}

export function setField(window, key, value) {
    const el = window.document.getElementById(`form_${key}`);
    el.value = value;
    el.dispatchEvent(new window.Event('input', { bubbles: true }));
}
