from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
main_path = ROOT / 'web' / 'app' / 'main.py'
layout_path = ROOT / 'web' / 'app' / 'templates' / 'layout.html'
css_path = ROOT / 'web' / 'app' / 'static' / 'css' / 'app.css'

main_text = main_path.read_text(encoding='utf-8')
if 'admin_payouts_grouped' in main_text and 'dispatch_state' not in main_text:
    main_text = main_text.rstrip() + '\n\nfrom web.app.routers import dispatch_state\napp.include_router(dispatch_state.router)\n'
elif 'dispatch_state' not in main_text:
    main_text = main_text.rstrip() + '\n\nfrom web.app.routers import dispatch_state\napp.include_router(dispatch_state.router)\n'
main_path.write_text(main_text, encoding='utf-8')

layout_text = layout_path.read_text(encoding='utf-8')
layout_text = re.sub(r'<script[^\n]*dispatch_alerts\.js[^\n]*', '', layout_text)
script = '<script src="/static/js/dispatch_alerts.js?v=10"></script>'
if '</body>' in layout_text:
    layout_text = layout_text.replace('</body>', script + '\n</body>', 1)
else:
    layout_text = layout_text.rstrip() + '\n' + script + '\n'
layout_path.write_text(layout_text, encoding='utf-8')

css_text = css_path.read_text(encoding='utf-8') if css_path.exists() else ''
if 'dispatch-alert-toggle' not in css_text:
    css_path.write_text(css_text + '''

/* Dispatch auto-refresh and new-order sound toggle */
.dispatch-alert-toggle {
    position: fixed;
    right: 18px;
    bottom: 18px;
    z-index: 9999;
    border: 1px solid rgba(148, 163, 184, 0.35);
    border-radius: 999px;
    padding: 10px 14px;
    color: #f8fafc;
    background: linear-gradient(135deg, #4f46e5, #2563eb);
    box-shadow: 0 12px 32px rgba(15, 23, 42, 0.35);
    font-weight: 700;
    cursor: pointer;
}

.dispatch-alert-toggle:hover {
    transform: translateY(-1px);
    filter: brightness(1.08);
}
''', encoding='utf-8')

print('installed dispatch state API and alert script')
