/* ============================================================
   Command palette (Cmd/Ctrl+K) and keyboard shortcuts registry.
   Loaded after app.js; uses its globals: api, API, toast, navigate,
   escapeHtmlAttr, showNewPropertyModal, showNewValuationModal.
   ============================================================ */
(() => {
    const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
    const MOD = IS_MAC ? '⌘' : 'Ctrl';
    const GROUPS = ['Actions', 'Properties', 'Valuations', 'Tenants'];
    const KIND_GROUP = { property: 'Properties', valuation: 'Valuations', tenant: 'Tenants' };

    // ─── Shortcuts registry ─────────────────────────────────────
    // key is a single key ("n", "?") or a two-key sequence ("g p").
    const shortcuts = new Map();
    window.registerShortcut = (key, label, handler) => shortcuts.set(key, { label, handler });

    function currentRoute() {
        const path = (window.location.hash || '#/dashboard').slice(1);
        const prop = path.match(/^\/property\/([^/]+)/);
        const val = path.match(/^\/valuation\/([^/]+)/);
        return { path, propertyId: prop && prop[1], valuationId: val && val[1] };
    }

    function isTyping(el) {
        return !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
    }

    // ─── Actions ────────────────────────────────────────────────
    function actions() {
        const r = currentRoute();
        const list = [
            { title: 'New property', hint: r.path === '/dashboard' ? 'N' : '', run: () => showNewPropertyModal() },
        ];
        if (r.propertyId) {
            list.push({ title: 'New valuation', subtitle: 'For this property', run: async () => {
                try {
                    const [property, valuations] = await Promise.all([
                        api.get(`/properties/${r.propertyId}`),
                        api.get(`/properties/${r.propertyId}/valuations`),
                    ]);
                    // A new valuation copies the latest valuation's market leasing
                    const latest = [...valuations].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))[0];
                    const profiles = latest ? await api.get(`/valuations/${latest.id}/market-profiles`) : [];
                    showNewValuationModal(property, profiles);
                } catch (err) {
                    toast('Error: ' + err.message, 'error');
                }
            } });
        }
        if (r.valuationId) {
            list.push({ title: 'Re-run valuation', subtitle: 'This valuation', run: async () => {
                toast('Running valuation...');
                try {
                    await api.post(`/valuations/${r.valuationId}/run`);
                    toast('Valuation completed!', 'success');
                    navigate();
                } catch (err) {
                    toast('Error: ' + err.message, 'error');
                }
            } });
            list.push({ title: 'Export full model', subtitle: 'Excel workbook', run: () => {
                // Prefer the page's own button (it names the file and reports errors)
                const btn = document.getElementById('valExportFullBtn');
                if (btn) btn.click();
                else window.open(`${API}/valuations/${r.valuationId}/reports/full-export.xlsx`, '_blank');
            } });
        }
        if (typeof window.setTheme === 'function') {
            list.push({ title: 'Toggle theme', subtitle: 'Light / dark', run: () => {
                const dark = typeof window.getTheme === 'function'
                    ? window.getTheme() === 'dark'
                    : document.documentElement.dataset.theme === 'dark';
                window.setTheme(dark ? 'light' : 'dark');
            } });
        }
        list.push(
            { title: 'Go to Properties', hint: 'G P', run: () => go('#/dashboard') },
            { title: 'Go to Portfolio', hint: 'G F', run: () => go('#/funds') },
            { title: 'Go to Lending', hint: 'G L', run: () => go('#/loans') },
            { title: 'Go to Help', run: () => go('#/help') },
            { title: 'Ask modeling help', run: () => window.openHelpChat?.() },
            { title: 'Keyboard shortcuts', hint: '?', run: () => showShortcuts() },
        );
        return list.map(a => ({ ...a, group: 'Actions' }));
    }

    function go(hash) {
        if (window.location.hash === hash) navigate();
        else window.location.hash = hash;
    }

    // Subsequence match; lower score is better. Returns null when it doesn't match.
    function fuzzyScore(text, q) {
        const t = text.toLowerCase();
        if (!q) return 0;
        const idx = t.indexOf(q);
        if (idx === 0) return 0;
        if (idx > 0) return t[idx - 1] === ' ' ? 1 : 2;
        let pos = -1, gaps = 0;
        for (const ch of q) {
            const next = t.indexOf(ch, pos + 1);
            if (next < 0) return null;
            gaps += next - pos - 1;
            pos = next;
        }
        return 3 + gaps;
    }

    // ─── Palette ────────────────────────────────────────────────
    let overlay = null, input = null, listEl = null;
    let items = [], active = 0, searchResults = [], searchTimer = null, searchSeq = 0, returnFocus = null;

    function openPalette() {
        if (overlay) { input.focus(); return; }
        closeShortcuts();
        returnFocus = document.activeElement;
        overlay = document.createElement('div');
        overlay.className = 'palette-overlay';
        overlay.innerHTML = `
            <div class="palette" role="dialog" aria-modal="true" aria-label="Command palette">
                <div class="palette-search">
                    <input class="palette-input" type="text" placeholder="Search properties, valuations, tenants, or type a command"
                        role="combobox" aria-expanded="true" aria-controls="paletteList" aria-autocomplete="list" autocomplete="off" spellcheck="false">
                    <kbd class="palette-kbd">Esc</kbd>
                </div>
                <ul class="palette-list" id="paletteList" role="listbox" aria-label="Results"></ul>
                <div class="palette-footer">
                    <span><kbd class="palette-kbd">↑</kbd><kbd class="palette-kbd">↓</kbd> navigate</span>
                    <span><kbd class="palette-kbd">↵</kbd> open</span>
                    <span><kbd class="palette-kbd">${MOD}</kbd><kbd class="palette-kbd">K</kbd> toggle</span>
                    <span><kbd class="palette-kbd">?</kbd> shortcuts</span>
                </div>
            </div>`;
        document.body.appendChild(overlay);
        input = overlay.querySelector('.palette-input');
        listEl = overlay.querySelector('.palette-list');
        searchResults = [];

        overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) closePalette(); });
        input.addEventListener('input', onInput);
        input.addEventListener('keydown', onKeydown);
        listEl.addEventListener('mousemove', (e) => {
            const li = e.target.closest('[role="option"]');
            if (li && Number(li.dataset.index) !== active) setActive(Number(li.dataset.index), false);
        });
        listEl.addEventListener('click', (e) => {
            const li = e.target.closest('[role="option"]');
            if (li) runItem(Number(li.dataset.index));
        });
        render();
        input.focus();
    }

    function closePalette() {
        if (!overlay) return;
        clearTimeout(searchTimer);
        searchSeq++;
        overlay.remove();
        overlay = input = listEl = null;
        if (returnFocus && document.contains(returnFocus)) returnFocus.focus();
        returnFocus = null;
    }

    function onInput() {
        render();
        clearTimeout(searchTimer);
        const q = input.value.trim();
        if (!q) { searchResults = []; render(); return; }
        const seq = ++searchSeq;
        searchTimer = setTimeout(async () => {
            try {
                const results = await api.get(`/search?q=${encodeURIComponent(q)}&limit=20`);
                if (seq !== searchSeq || !overlay) return;
                searchResults = results;
                render();
            } catch (err) {
                console.error('Search failed:', err);
            }
        }, 120);
    }

    function render() {
        const q = input.value.trim().toLowerCase();
        const matched = actions()
            .map(a => ({ a, s: fuzzyScore(a.title, q) }))
            .filter(x => x.s !== null)
            .sort((x, y) => x.s - y.s)
            .map(x => x.a);
        const found = searchResults.map(r => ({
            group: KIND_GROUP[r.kind], title: r.title, subtitle: r.subtitle,
            run: () => go(r.href),
        }));
        items = [];
        for (const g of GROUPS) items.push(...[...matched, ...found].filter(i => i.group === g));
        active = Math.min(active, Math.max(items.length - 1, 0));
        if (q !== listEl.dataset.q) active = 0;
        listEl.dataset.q = q;

        if (!items.length) {
            listEl.innerHTML = `<li class="palette-empty" role="presentation">${q ? 'No matches' : 'Type to search'}</li>`;
            input.removeAttribute('aria-activedescendant');
            return;
        }
        let html = '', lastGroup = '';
        items.forEach((it, i) => {
            if (it.group !== lastGroup) {
                html += `<li class="palette-group" role="presentation">${it.group}</li>`;
                lastGroup = it.group;
            }
            html += `<li class="palette-item" role="option" id="paletteOpt${i}" data-index="${i}" aria-selected="false">
                <span class="palette-item-text">
                    <span class="palette-item-title">${escapeHtmlAttr(it.title)}</span>
                    ${it.subtitle ? `<span class="palette-item-sub">${escapeHtmlAttr(it.subtitle)}</span>` : ''}
                </span>
                ${it.hint ? `<span class="palette-item-hint">${it.hint.split(' ').map(k => `<kbd class="palette-kbd">${escapeHtmlAttr(k)}</kbd>`).join('')}</span>` : ''}
            </li>`;
        });
        listEl.innerHTML = html;
        setActive(active, true);
    }

    function setActive(i, scroll) {
        const prev = listEl.querySelector('[aria-selected="true"]');
        if (prev) prev.setAttribute('aria-selected', 'false');
        active = i;
        const el = document.getElementById(`paletteOpt${i}`);
        if (!el) return;
        el.setAttribute('aria-selected', 'true');
        input.setAttribute('aria-activedescendant', el.id);
        if (scroll) el.scrollIntoView({ block: 'nearest' });
    }

    function runItem(i) {
        const it = items[i];
        if (!it) return;
        closePalette();
        it.run();
    }

    function onKeydown(e) {
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            if (!items.length) return;
            const step = e.key === 'ArrowDown' ? 1 : -1;
            setActive((active + step + items.length) % items.length, true);
        } else if (e.key === 'Enter') {
            e.preventDefault();
            runItem(active);
        } else if (e.key === 'Escape') {
            e.preventDefault();
            e.stopPropagation();
            closePalette();
        } else if (e.key === 'Tab') {
            e.preventDefault(); // keep focus inside the dialog
        }
    }

    // ─── Shortcuts overlay ──────────────────────────────────────
    let helpOverlay = null, helpReturnFocus = null;

    function showShortcuts() {
        if (helpOverlay) return;
        helpReturnFocus = document.activeElement;
        const rows = [[`${MOD} K`, 'Command palette'], ['/', 'Command palette'], ['?', 'Keyboard shortcuts'],
            ...[...shortcuts].map(([k, s]) => [k, s.label])];
        helpOverlay = document.createElement('div');
        helpOverlay.className = 'palette-overlay';
        helpOverlay.innerHTML = `
            <div class="palette palette--help" role="dialog" aria-modal="true" aria-labelledby="shortcutsTitle" tabindex="-1">
                <div class="palette-help-head">
                    <h2 id="shortcutsTitle">Keyboard shortcuts</h2>
                    <button type="button" class="palette-close" aria-label="Close">×</button>
                </div>
                <dl class="palette-help-list">${rows.map(([k, label]) => `
                    <div class="palette-help-row"><dt>${escapeHtmlAttr(label)}</dt>
                    <dd>${k.split(' ').map(x => `<kbd class="palette-kbd">${escapeHtmlAttr(x.toUpperCase())}</kbd>`).join('')}</dd></div>`).join('')}
                </dl>
            </div>`;
        document.body.appendChild(helpOverlay);
        helpOverlay.addEventListener('mousedown', (e) => { if (e.target === helpOverlay) closeShortcuts(); });
        helpOverlay.querySelector('.palette-close').addEventListener('click', closeShortcuts);
        helpOverlay.querySelector('.palette--help').focus();
    }

    function closeShortcuts() {
        if (!helpOverlay) return;
        helpOverlay.remove();
        helpOverlay = null;
        if (helpReturnFocus && document.contains(helpReturnFocus)) helpReturnFocus.focus();
        helpReturnFocus = null;
    }

    // ─── Global key handling ────────────────────────────────────
    let pendingPrefix = null, pendingTimer = null;

    document.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 'k') {
            e.preventDefault();
            if (overlay) closePalette(); else openPalette();
            return;
        }
        if (helpOverlay) {
            if (e.key === 'Escape' || e.key === '?') { e.preventDefault(); closeShortcuts(); }
            else if (e.key === 'Tab') e.preventDefault();
            return;
        }
        if (overlay || e.metaKey || e.ctrlKey || e.altKey || e.defaultPrevented) return;
        if (isTyping(e.target) || document.querySelector('.modal-overlay')) return;

        if (e.key === '/') { e.preventDefault(); openPalette(); return; }
        if (e.key === '?') { e.preventDefault(); showShortcuts(); return; }

        const key = e.key.toLowerCase();
        if (pendingPrefix) {
            const combo = `${pendingPrefix} ${key}`;
            pendingPrefix = null;
            clearTimeout(pendingTimer);
            if (shortcuts.has(combo)) { e.preventDefault(); shortcuts.get(combo).handler(e); }
            return;
        }
        if ([...shortcuts.keys()].some(k => k.startsWith(key + ' '))) {
            pendingPrefix = key;
            pendingTimer = setTimeout(() => { pendingPrefix = null; }, 1000);
            return;
        }
        if (shortcuts.has(key)) { e.preventDefault(); shortcuts.get(key).handler(e); }
    });

    window.openCommandPalette = openPalette;
    const searchButton = document.getElementById('topnavSearch');
    if (searchButton) {
        searchButton.addEventListener('click', openPalette);
        document.getElementById('topnavSearchKey').textContent = `${MOD}K`;
        searchButton.title = `Search properties, valuations and tenants (${MOD}K)`;
    }

    registerShortcut('g p', 'Go to Properties', () => go('#/dashboard'));
    registerShortcut('g f', 'Go to Portfolio', () => go('#/funds'));
    registerShortcut('g l', 'Go to Lending', () => go('#/loans'));
    registerShortcut('n', 'New property (on Properties)', () => {
        if (currentRoute().path === '/dashboard') showNewPropertyModal();
    });
})();
