// Theme: <html data-theme="light|dark">. Load in <head> so the theme is set before first paint.
// Light by default; dark is opt-in. window.setTheme('light' | 'dark' | 'system') saves the choice;
// 'system' follows prefers-color-scheme.
// window.getTheme() returns the theme in effect ('light' | 'dark'); window.getThemeMode() the saved choice.
// A 'themechange' event fires on window when the theme in effect changes.
(function () {
    const KEY = 'opendcf-theme';
    const MODES = ['light', 'dark', 'system'];
    const media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

    let mode = 'light';
    try {
        const saved = localStorage.getItem(KEY);
        if (MODES.includes(saved)) mode = saved;
    } catch (e) { /* storage blocked: stay light */ }

    const resolved = () => (mode === 'system' ? (media && media.matches ? 'dark' : 'light') : mode);

    function apply() {
        const theme = resolved();
        const root = document.documentElement;
        if (root.dataset.theme === theme) return;
        root.dataset.theme = theme;
        window.dispatchEvent(new CustomEvent('themechange', { detail: { theme, mode } }));
    }

    window.getTheme = resolved;
    window.getThemeMode = () => mode;
    window.setTheme = function (next) {
        if (!MODES.includes(next)) return;
        mode = next;
        try { localStorage.setItem(KEY, mode); } catch (e) { /* not remembered */ }
        apply();
        updateToggle();
    };

    if (media) {
        const onSystemChange = () => { if (mode === 'system') apply(); };
        if (media.addEventListener) media.addEventListener('change', onSystemChange);
        else if (media.addListener) media.addListener(onSystemChange);
    }

    apply();

    // Sun/moon button in the top nav switches between light and dark
    function updateToggle() {
        const button = document.getElementById('themeToggle');
        if (!button) return;
        const dark = resolved() === 'dark';
        button.setAttribute('aria-pressed', String(dark));
        button.title = dark ? 'Switch to light mode' : 'Switch to dark mode';
        button.setAttribute('aria-label', button.title);
    }
    function wireToggle() {
        const button = document.getElementById('themeToggle');
        if (!button) return;
        button.addEventListener('click', () => window.setTheme(resolved() === 'dark' ? 'light' : 'dark'));
        window.addEventListener('themechange', updateToggle);
        updateToggle();
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wireToggle);
    else wireToggle();
})();
