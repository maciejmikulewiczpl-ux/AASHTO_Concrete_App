"""
AASHTO LRFD Reinforced Concrete Section Design - Standalone Application
Wraps the HTML/JS UI in a native desktop window.
Calculations run in Python via the pywebview JS↔Python bridge.
"""
import webview
import os
import sys
from api import Api


def get_html():
    """Load HTML from file next to the exe/script, or from embedded fallback."""
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))

    html_path = os.path.join(base, 'index.html')
    if os.path.exists(html_path):
        with open(html_path, 'r', encoding='utf-8') as f:
            return f.read()
    raise FileNotFoundError(f"index.html not found at {html_path}")


if __name__ == '__main__':
    html_content = get_html()
    api = Api()
    window = webview.create_window(
        'AASHTO LRFD - Concrete Section Design',
        html=html_content,
        width=1400,
        height=900,
        min_size=(900, 600),
        resizable=True,
        text_select=True,
        js_api=api,
    )
    api.window = window

    def on_started():
        window.maximize()

    webview.start(on_started, debug=False)
