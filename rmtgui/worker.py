"""Runs `rmt.py --events ...` as a child process and turns its JSON lines into Qt signals.

The GUI never runs an export in its own process: a hung Workbench or a crashing baker can't freeze the window, and
Cancel kills the whole process tree (the worker, and Workbench or the game under it).
"""

import json
import os
import subprocess
import sys

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from rmtlib import paths


def _python():
    """python.exe beside the running interpreter (the launcher starts the window with pythonw.exe, but the worker
    should be a console program so its output pipes behave; Qt starts it without a console window)."""
    exe = sys.executable
    if os.path.basename(exe).lower() == "pythonw.exe":
        console = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.isfile(console):
            return console
    return exe


def _frozen_worker():
    """The packaged app's console exe, rmt.exe beside the window's exe: a windowless exe may have no output pipe, so
    the worker is the console one (Qt starts it without a console window)."""
    exe = os.path.join(os.path.dirname(sys.executable), "rmt.exe")
    return exe if os.path.isfile(exe) else sys.executable


def worker_command(args):
    """The command that runs rmt.py with these arguments: the packaged app runs rmt.exe --worker."""
    if paths.FROZEN:
        return [_frozen_worker(), "--worker", *args]
    return [_python(), "-u", os.path.join(paths.REPO, "rmt.py"), *args]


def script_command(args):
    """The command that runs a Labs script: rmt_gui.py --script/--module ... (see rmt_gui.run_script)."""
    if paths.FROZEN:
        return [_frozen_worker(), *args]
    return [_python(), "-u", os.path.join(paths.REPO, "rmt_gui.py"), *args]


class Worker(QObject):
    event = Signal(dict)       # one JSON event from rmt.py (rmtlib/events.py)
    output = Signal(str, str)  # (level, text) for anything that wasn't JSON
    finished = Signal(int)     # exit code; -1 when cancelled

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc = None
        self.cancelled = False
        self._buf = {QProcess.ProcessChannel.StandardOutput: b"", QProcess.ProcessChannel.StandardError: b""}

    def running(self):
        return self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning

    def start(self, args, workspace, workbench=None):
        """rmt.py with these arguments."""
        glob_args = ["--events", "--workspace", workspace]
        if workbench:
            glob_args += ["--workbench", workbench]
        self._start(worker_command(glob_args + list(args)))

    def start_script(self, args):
        """A Labs script: args as rmtgui.labs.build gives them."""
        self._start(script_command(list(args)))

    def _start(self, cmd):
        if self.running():
            raise RuntimeError("a run is already going")
        self.cancelled = False
        self.proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        self.proc.setProcessEnvironment(env)
        self.proc.setWorkingDirectory(paths.bundle())
        self.proc.setProgram(cmd[0])
        self.proc.setArguments(cmd[1:])
        self.proc.readyReadStandardOutput.connect(lambda: self._read(QProcess.ProcessChannel.StandardOutput))
        self.proc.readyReadStandardError.connect(lambda: self._read(QProcess.ProcessChannel.StandardError))
        self.proc.finished.connect(self._done)
        self.proc.errorOccurred.connect(self._error)
        self.output.emit("info", "$ " + subprocess.list2cmdline(cmd))
        self.proc.start()

    def cancel(self):
        """Kill the worker and everything it started (Workbench, the game)."""
        if not self.running():
            return
        self.cancelled = True
        pid = self.proc.processId()
        if pid:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.proc.kill()

    def _read(self, channel):
        data = self.proc.readAllStandardOutput() if channel == QProcess.ProcessChannel.StandardOutput \
            else self.proc.readAllStandardError()
        buf = self._buf[channel] + bytes(data)
        *lines, self._buf[channel] = buf.split(b"\n")
        for raw in lines:
            text = raw.decode("utf8", errors="replace").rstrip("\r")
            if not text.strip():
                continue
            if channel == QProcess.ProcessChannel.StandardOutput and text.startswith("{"):
                try:
                    self.event.emit(json.loads(text))
                    continue
                except json.JSONDecodeError:
                    pass
            self.output.emit("error" if channel == QProcess.ProcessChannel.StandardError else "info", text)

    def _done(self, code, _status):
        for channel in list(self._buf):
            if self._buf[channel].strip():
                self.output.emit("info", self._buf[channel].decode("utf8", errors="replace"))
            self._buf[channel] = b""
        self.finished.emit(-1 if self.cancelled else code)

    def _error(self, err):
        if err == QProcess.ProcessError.FailedToStart:
            self.output.emit("error", f"could not start {self.proc.program()}")
            self.finished.emit(1)
