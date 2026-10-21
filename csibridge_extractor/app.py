"""CSiBridge Results Extractor window.  Usage: python app.py [--fake FIXTURE.json]"""
from __future__ import annotations

import argparse
import os
import sys

# Allow `python app.py` from inside this folder: the package is imported as csibridge_extractor.
_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)


def resource_path(rel: str) -> str:
    """Path of a bundled resource, from source or under PyInstaller (sys._MEIPASS)."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, rel)


def get_html() -> str:
    with open(resource_path(os.path.join("ui", "index.html")), "r", encoding="utf-8") as fh:
        return fh.read()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="app.py")
    ap.add_argument("--fake", metavar="FIXTURE", help="use a JSON fixture instead of CSiBridge (demo)")
    args = ap.parse_args(argv)

    import webview  # lazy: only the window needs it
    from csibridge_extractor.api import Api

    api = Api(fake=args.fake)
    title = "CSiBridge Results Extractor" + (" [FAKE DATA]" if args.fake else "")
    window = webview.create_window(title, html=get_html(), width=1100, height=900,
                                   min_size=(800, 600), resizable=True, text_select=True, js_api=api)
    api.window = window
    webview.start(debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
