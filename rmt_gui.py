"""Reforger Map Tools: the desktop app.

  Double-click "Reforger Map Tools.bat" (sets everything up the first time), or:
  python rmt_gui.py          (needs PySide6, numpy, Pillow and SciPy: pip install -r requirements.txt)

The packaged app (PyInstaller, ReforgerMapTools.spec) is this same file twice: "Reforger Map Tools.exe" (the window)
and rmt.exe (a console exe: the command line, and the child process the window starts to do the work, so the window
stays responsive and Cancel can stop everything). See docs/gui.md and docs/packaging.md.
  --worker <rmt.py arguments>                       rmt.py's commands
  [--stderr-info] --script <file.py> <arguments>    one of the Labs scripts (firetest.py, audible/audible.py, ...), run
                                                    as __main__ in its own folder, its output as rmt.py --events lines
  [--stderr-info] --module <name> <arguments>       the same for a module (rmtlib.pak, unittest)
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))


def run_script(args):
    """The Labs runner: run a script or module as __main__, with every line it prints sent as an event."""
    import runpy
    from rmtlib import events, paths
    stderr_info = args[:1] == ["--stderr-info"]
    if stderr_info:
        args = args[1:]
    kind, target, rest = args[0], args[1], args[2:]
    events.enable()
    if stderr_info:  # unittest reports on stderr; that's not an error
        sys.stderr = events._Lines("info")
    code = 0
    try:
        if kind == "--module":
            sys.argv = [target, *rest]
            runpy.run_module(target, run_name="__main__", alter_sys=True)
        else:
            path = target if os.path.isabs(target) else os.path.join(paths.bundle(), *target.split("/"))
            folder = os.path.dirname(path)
            os.chdir(folder)              # the audible scripts read and write their files in the current folder
            sys.path.insert(0, folder)
            sys.argv = [path, *rest]
            runpy.run_path(path, run_name="__main__")
    except SystemExit as e:
        if isinstance(e.code, str):
            events.emit("error", message=e.code)
            code = 1
        else:
            code = e.code or 0
    except KeyboardInterrupt:
        code = 1
    except Exception as e:  # noqa: BLE001 - every failure must reach the window
        traceback.print_exc()
        events.emit("error", message=f"{type(e).__name__}: {e}")
        code = 1
    events.emit("done", ok=code == 0)
    return code


def _message_box(text):
    """A plain Windows message box: under pythonw (the launcher) there is no console to print to."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "Reforger Map Tools", 0x10)
    except Exception:  # noqa: BLE001
        print(text, file=sys.stderr)


def _crash_log(text):
    try:
        from rmtlib import paths
        folder = paths.app_data()
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "gui-error.log")
        with open(path, "a", encoding="utf8") as f:
            f.write(text + "\n")
        return path
    except OSError:
        return None


def _is_cli_exe():
    return getattr(sys, "frozen", False) and os.path.basename(sys.executable).lower() == "rmt.exe"


def main():
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    if sys.stdout is None:  # pythonw
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        import rmt
        return rmt.main(sys.argv[2:])
    if _is_cli_exe() and not (len(sys.argv) > 2 and sys.argv[1] in ("--script", "--module", "--stderr-info")):
        import rmt  # the packaged rmt.exe is the command line: rmt.exe detect, rmt.exe run Arland ...
        return rmt.main(sys.argv[1:])
    if len(sys.argv) > 2 and sys.argv[1] in ("--script", "--module", "--stderr-info"):
        return run_script(sys.argv[1:])
    try:
        from rmtgui.app import main as gui
    except ImportError as e:
        if "PySide6" in str(e) or "shiboken" in str(e).lower():
            _message_box("The desktop app needs PySide6.\n\nDouble-click \"Reforger Map Tools.bat\" (it installs "
                         "what's missing), or run:\n\npip install -r requirements.txt")
            return 1
        raise
    try:
        return gui()
    except Exception:  # noqa: BLE001
        text = traceback.format_exc()
        log = _crash_log(text)
        _message_box("The app stopped with an error:\n\n" + text[-1500:] + (f"\n\nSaved to {log}" if log else ""))
        return 1


if __name__ == "__main__":
    sys.exit(main())
