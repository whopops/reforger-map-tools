"""Reforger Map Tools: the desktop app.

  python rmt_gui.py          (needs PySide6, numpy and Pillow: pip install -r requirements.txt)

The packaged app (PyInstaller) is this same file. It re-launches itself with --worker to run rmt.py's commands in a
child process, so the window stays responsive and Cancel can stop everything. See docs/gui.md.
"""

import sys


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        import rmt
        return rmt.main(sys.argv[2:])
    try:
        from rmtgui.app import main as gui
    except ImportError as e:
        if "PySide6" in str(e):
            print("The desktop app needs PySide6: pip install -r requirements.txt", file=sys.stderr)
            return 1
        raise
    return gui()


if __name__ == "__main__":
    sys.exit(main())
