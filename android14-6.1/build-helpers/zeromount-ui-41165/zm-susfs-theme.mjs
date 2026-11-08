// Read the same appearance preferences as ZeroMount without booting its SPA.
export function applyAppearance(scope = globalThis, root = scope.document?.documentElement) {
  if (!root) return;
  try {
    const theme = scope.localStorage?.getItem('zeromount-theme');
    root.dataset.zmTheme = theme === 'light' ? 'light' : 'dark';
    const accent = scope.localStorage?.getItem('zeromount-accent');
    if (/^#[0-9a-f]{6}$/i.test(accent ?? '')) root.style.setProperty('--zm-accent', accent);
  } catch { /* Appearance storage is optional in a restricted WebView. */ }
}
if (typeof document !== 'undefined') applyAppearance();
