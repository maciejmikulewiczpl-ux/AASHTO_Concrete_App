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


def hide_own_console() -> None:
    """Hide the console window if this process is its only user (double-click launch, not a terminal)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        hwnd = k32.GetConsoleWindow()
        procs = (ctypes.c_uint * 4)()
        # The venv launcher and its interpreter child share the console: <= 2 processes = ours alone.
        if hwnd and k32.GetConsoleProcessList(procs, 4) <= 2:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="app.py")
    ap.add_argument("--fake", metavar="FIXTURE", help="use a JSON fixture instead of CSiBridge (demo)")
    ap.add_argument("--pid", type=int, help="process id of the CSiBridge window to use (when several are open)")
    args = ap.parse_args(argv)
    hide_own_console()

    import webview  # lazy: only the window needs it
    from csibridge_extractor.api import Api

    api = Api(fake=args.fake, pid=args.pid)
    title = "CSiBridge Results Extractor" + (" [FAKE DATA]" if args.fake else "")
    window = webview.create_window(title, html=get_html(), width=1100, height=900,
                                   min_size=(800, 600), resizable=True, text_select=True, js_api=api)
    api.window = window
    webview.start(debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
