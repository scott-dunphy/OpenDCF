// ─── Modeling help chat ──────────────────────────────────────
// A side panel, reachable from every page, that answers "how do I model X in OpenDCF?"
// via POST /help/chat. It knows the app guide only: no user data is sent or read.

(function () {
    const SCREENS = {
        dashboard: 'Properties', property: 'Property', valuation: 'Valuation', tenants: 'Tenants',
        portfolio: 'Portfolio', funds: 'Funds', fund: 'Fund', assumptions: 'Assumptions library',
        loans: 'Loan book', loan: 'Loan', import: 'Import', help: 'Help & Glossary',
    };
    const EXAMPLES = [
        'How do I model free rent at the start of a lease?',
        'How do I set up a base year expense stop?',
        'What happens to a suite when its lease expires?',
    ];
    const history = [];
    let panel = null, busy = false, returnFocus = null;

    const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

    // Escape first, then a small markdown subset: bold, inline code, bullet and numbered lists
    function renderMarkdown(text) {
        const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>');
        const out = [];
        let list = null;
        for (const raw of text.split('\n')) {
            const line = raw.trim();
            const item = line.match(/^(?:[-*]|(\d+)\.)\s+(.*)$/);
            const kind = item ? (item[1] ? 'ol' : 'ul') : null;
            if (list && kind !== list) { out.push(`</${list}>`); list = null; }
            if (kind) {
                if (!list) { out.push(`<${kind}>`); list = kind; }
                // Keep the model's numbering: bullets under a step close the list and restart it
                out.push(`<li${item[1] ? ` value="${item[1]}"` : ''}>${inline(item[2])}</li>`);
            } else if (line) {
                out.push(`<p>${inline(line.replace(/^#+\s*/, ''))}</p>`);
            }
        }
        if (list) out.push(`</${list}>`);
        return out.join('');
    }

    function currentScreen() {
        const first = (location.hash.slice(2) || 'dashboard').split('/')[0];
        return SCREENS[first] || null;
    }

    function addMessage(role, text, isError = false) {
        const log = panel.querySelector('[data-help-log]');
        panel.querySelector('[data-help-empty]')?.remove();
        const div = document.createElement('div');
        div.className = `help-chat-msg help-chat-msg--${role}${isError ? ' help-chat-msg--error' : ''}`;
        if (role === 'assistant' && !isError) div.innerHTML = renderMarkdown(text);
        else div.textContent = text;
        log.appendChild(div);
        log.scrollTop = log.scrollHeight;
        return div;
    }

    async function send(message) {
        message = message.trim();
        if (!message || busy) return;
        busy = true;
        const input = panel.querySelector('[data-help-input]');
        const button = panel.querySelector('[data-help-send]');
        input.value = '';
        button.disabled = true;
        addMessage('user', message);
        const pending = addMessage('assistant', 'Thinking…');
        pending.classList.add('help-chat-msg--pending');
        try {
            const res = await fetch(API + '/help/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message, history, screen: currentScreen() }),
            });
            const data = await res.json().catch(() => ({}));
            pending.remove();
            if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'The help assistant could not answer.');
            history.push({ role: 'user', content: message }, { role: 'assistant', content: data.message });
            addMessage('assistant', data.message);
        } catch (err) {
            pending.remove();
            addMessage('assistant', err.message || 'The help assistant could not answer.', true);
        } finally {
            busy = false;
            button.disabled = false;
            input.focus();
        }
    }

    function open() {
        if (!panel) build();
        returnFocus = document.activeElement;
        panel.hidden = false;
        document.getElementById('helpChatToggle')?.setAttribute('aria-expanded', 'true');
        panel.querySelector('[data-help-input]').focus();
    }

    function close() {
        if (!panel || panel.hidden) return;
        panel.hidden = true;
        document.getElementById('helpChatToggle')?.setAttribute('aria-expanded', 'false');
        returnFocus?.focus?.();
    }

    function build() {
        panel = document.createElement('aside');
        panel.className = 'help-chat';
        panel.hidden = true;
        panel.setAttribute('role', 'dialog');
        panel.setAttribute('aria-labelledby', 'helpChatTitle');
        panel.innerHTML = `
            <div class="help-chat-head">
                <div>
                    <h2 id="helpChatTitle">Modeling help</h2>
                    <p>Ask how to model something in OpenDCF. It can't see or change your data.</p>
                </div>
                <button type="button" class="topnav-icon-btn" data-help-close aria-label="Close help">
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>
                </button>
            </div>
            <div class="help-chat-log" data-help-log aria-live="polite">
                <div class="help-chat-empty" data-help-empty>
                    <p>Try one of these:</p>
                    ${EXAMPLES.map(q => `<button type="button" class="help-chat-example">${esc(q)}</button>`).join('')}
                </div>
            </div>
            <form class="help-chat-form" data-help-form>
                <textarea class="form-input" data-help-input rows="2" maxlength="2000" placeholder="How do I model…" aria-label="Your question"></textarea>
                <button type="submit" class="btn btn-primary btn-sm" data-help-send>Ask</button>
            </form>`;
        document.body.appendChild(panel);
        const input = panel.querySelector('[data-help-input]');
        panel.querySelector('[data-help-close]').addEventListener('click', close);
        panel.querySelector('[data-help-form]').addEventListener('submit', e => { e.preventDefault(); send(input.value); });
        input.addEventListener('keydown', e => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input.value); }
        });
        panel.querySelectorAll('.help-chat-example').forEach(b => b.addEventListener('click', () => send(b.textContent)));
        panel.addEventListener('keydown', e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } });
    }

    const toggle = document.getElementById('helpChatToggle');
    toggle?.addEventListener('click', () => (panel && !panel.hidden ? close() : open()));
    window.openHelpChat = open;
})();
