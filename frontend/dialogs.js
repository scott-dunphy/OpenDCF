// Keyboard behavior for every overlay dialog (showFormModal, bulk editors, confirms, intake overlays):
// Tab stays inside the top dialog, Esc closes a .modal-overlay through its own Cancel/Close control, and focus returns
// to the control that opened it. Dialogs are found by watching <body>, so no dialog code needs changes.
(function () {
    const DIALOG = '.modal-overlay, .intake-overlay, .intake-workbench-overlay';
    const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), '
        + 'select:not([disabled]), textarea:not([disabled]), summary, iframe, [tabindex]:not([tabindex="-1"])';
    const CLOSERS = '[data-cancel], [data-close], [id$="Cancel"], [id^="close"]';

    const stack = [];   // open dialogs, oldest first: { el, opener }
    const recent = [];  // last controls the user focused or pressed
    let menuWasOpen = false;
    let titleSeq = 0;

    function remember(e) {
        if (!(e.target instanceof Element)) return;
        recent.push(e.target.closest(FOCUSABLE) || e.target);
        if (recent.length > 8) recent.shift();
    }
    document.addEventListener('focusin', remember, true);
    document.addEventListener('pointerdown', remember, true);

    const top = () => stack[stack.length - 1] || null;
    const visible = (el) => el.getClientRects().length > 0;
    const focusables = (root) => [...root.querySelectorAll(FOCUSABLE)].filter(visible);

    function opened(el) {
        // The opener is the last control used outside the new dialog (it may already have focused itself)
        const opener = [...recent].reverse().find(t => t.isConnected && !el.contains(t)) || null;
        stack.push({ el, opener });
        el.setAttribute('role', 'dialog');
        el.setAttribute('aria-modal', 'true');
        const title = el.querySelector('.modal-title, h1, h2');
        if (title && !el.hasAttribute('aria-labelledby')) {
            if (!title.id) title.id = `dialog-title-${++titleSeq}`;
            el.setAttribute('aria-labelledby', title.id);
        }
        if (!el.contains(document.activeElement)) {
            const first = focusables(el)[0];
            if (first) first.focus();
            else {
                const box = el.firstElementChild || el;
                box.tabIndex = -1;
                box.focus();
            }
        }
    }

    function closed(el) {
        const i = stack.findIndex(d => d.el === el);
        if (i < 0) return;
        const [entry] = stack.splice(i, 1);
        const active = document.activeElement;
        if (active && active !== document.body && active.isConnected) return; // someone already moved focus
        let opener = entry.opener && entry.opener.isConnected ? entry.opener : null;
        // A menu item is hidden once its menu closes: return to the menu's button instead
        if (opener && !visible(opener)) opener = opener.closest('.menu')?.querySelector('.menu-trigger') || null;
        if (opener) opener.focus();
        else if (top()) (focusables(top().el)[0] || top().el).focus();
    }

    new MutationObserver((records) => {
        records.forEach((r) => {
            r.removedNodes.forEach((n) => { if (n instanceof Element && n.matches(DIALOG)) closed(n); });
            r.addedNodes.forEach((n) => { if (n instanceof Element && n.matches(DIALOG)) opened(n); });
        });
    }).observe(document.body, { childList: true });

    function closeDialog(el) {
        const closer = el.querySelector(CLOSERS)
            || [...el.querySelectorAll('button')].find(b => /^(cancel|close|done)$/i.test(b.textContent.trim()));
        if (closer && !closer.disabled) { closer.click(); return; }
        // Fall back to the backdrop-click handler most overlays have
        el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    }

    // Capture phase: note whether a dropdown menu is open before app.js's Esc handler closes it
    document.addEventListener('keydown', () => { menuWasOpen = !!document.querySelector('.menu.open'); }, true);

    // Bubble phase on window: runs after field-level handlers, which can claim Esc with preventDefault()
    window.addEventListener('keydown', (e) => {
        const dialog = top();
        if (!dialog) return;
        if (e.defaultPrevented) return;
        if (e.key === 'Escape') {
            // The full-screen intake workspaces hold unsaved work: Esc closes only ordinary dialogs
            if (e.isComposing || menuWasOpen || !dialog.el.matches('.modal-overlay')) return;
            e.preventDefault();
            closeDialog(dialog.el);
        } else if (e.key === 'Tab') {
            const items = focusables(dialog.el);
            if (!items.length) { e.preventDefault(); return; }
            const first = items[0];
            const last = items[items.length - 1];
            const active = document.activeElement;
            if (!dialog.el.contains(active)) {
                e.preventDefault();
                (e.shiftKey ? last : first).focus();
            } else if (e.shiftKey && active === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && active === last) {
                e.preventDefault();
                first.focus();
            }
        }
    });
})();
