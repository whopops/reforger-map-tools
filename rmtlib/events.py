"""Machine-readable progress for the GUI: `rmt.py --events ...` prints one JSON object per line on stdout.

Off by default, so the CLI prints exactly what it always has. With events on, everything else that would have been
printed (the tools' own `print` and `log` lines, and tracebacks) arrives as {"t": "log"} events, so stdout only ever
carries JSON.

Event kinds (every one has "t" and "ts", seconds since 1970):
  {"t":"plan","world":..., "steps":[{"id","label","game"}...]}   what a run will do, in order
  {"t":"step","id":"export:terrain","state":"start"|"done"|"failed"|"skipped","detail"?}
  {"t":"progress","id":"export:terrain","done":120,"total":324,"unit":"chunks"}
  {"t":"log","level":"info"|"error","text":...}
  {"t":"error","message":...,"hint"?}                           the run stopped
  {"t":"result", ...}                                            a command's answer (worlds, detect, check)
  {"t":"done","ok":true|false, ...}                              the last line of a run

Progress comes from the engine's own heartbeat (the RMT| lines in its console.log, see rmtlib/workbench.py), so
nothing here changes what the engine is asked to do.
"""

import io
import json
import sys
import threading
import time

_out = None
_lock = threading.Lock()
_totals = {}
_started = set()


def enabled():
    return _out is not None


def enable():
    """Route stdout to JSON events from now on (plain prints become log events)."""
    global _out
    if _out is not None:
        return
    _out = sys.stdout
    sys.stdout = _Lines("info")
    sys.stderr = _Lines("error")


def emit(kind, **fields):
    if _out is None:
        return
    line = json.dumps({"t": kind, "ts": round(time.time(), 3), **fields})
    with _lock:
        _out.write(line + "\n")
        _out.flush()


class _Lines(io.TextIOBase):
    """A text stream that turns each written line into a log event."""

    def __init__(self, level):
        self.level = level
        self.buf = ""

    def writable(self):
        return True

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                emit("log", level=self.level, text=line.rstrip())
        return len(s)

    def flush(self):
        pass


def step(step_id, state, **fields):
    if state == "start":
        if step_id in _started:
            return
        _started.add(step_id)
    emit("step", id=step_id, state=state, **fields)


def progress(step_id, done, total, unit):
    emit("progress", id=step_id, done=max(0, done), total=max(total, 0), unit=unit)


def _kv(parts):
    out = {}
    for p in parts:
        k, sep, v = p.partition("=")
        if sep:
            out[k] = v
    return out


def _int(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def heartbeat(label, msg):
    """One RMT| line from the engine (label: the launch, e.g. 'workbench', 'satellite', 'foliage')."""
    if _out is None:
        return
    p = msg.split("|")
    k = p[0]
    kv = _kv(p[1:])
    if k == "begin" and len(p) > 1:
        step("export:" + p[1], "start")
    elif k == "job" and len(p) > 1:
        # job|<name>|chunks=N|done_before=M
        total = _int(kv.get("chunks"))
        _totals[p[1]] = total
        progress("export:" + p[1], _int(kv.get("done_before")), total, "chunks")
    elif k == "chunk" and len(p) > 1 and p[1] in _totals:
        total = _totals[p[1]]
        progress("export:" + p[1], total - _int(kv.get("left")), total, "chunks")
    elif k == "progress" and len(p) > 3:
        progress("export:" + p[1], _int(p[2]), _int(p[3]), "items")
    elif k == "sat" and len(p) > 1:
        step("export:satellite", "start")
        if p[1] == "setup":
            _totals["satellite"] = _int(kv.get("shots"))
            progress("export:satellite", 0, _totals["satellite"], "shots")
        elif p[1] == "shot" and "satellite" in _totals:
            total = _totals["satellite"]
            progress("export:satellite", total - _int(kv.get("left")), total, "shots")
    elif k == "foliage" and len(p) > 1:
        step("export:foliage", "start")
        if p[1] == "setup":
            _totals["foliage"] = _int(kv.get("plants"))
            progress("export:foliage", 0, _totals["foliage"], "plants")
        elif p[1] == "plant" and "foliage" in _totals:
            total = _totals["foliage"]
            progress("export:foliage", total - _int(kv.get("left")), total, "plants")
    elif k in ("fire", "blast") and len(p) > 1:
        # the Labs tests (firetest.py, rockettest.py, blasttest.py): fire|setup|aims=N, fire|aim|id|left=K,
        # blast|setup|trials=N, blast|trial|id|left=K. Each game run starts its own count.
        unit = "aims" if k == "fire" else "trials"
        if p[1] == "setup":
            _totals[k] = _int(kv.get(unit))
            progress("lab", 0, _totals[k], unit)
        elif p[1] in ("aim", "trial") and k in _totals:
            progress("lab", _totals[k] - _int(kv.get("left")), _totals[k], unit)
    elif k in ("gun", "launcher") and len(p) > 1:
        # gun|setup|aims=N, then gun|landed|id|round and gun|lost|id|round (launcher|fired / launcher|lost for
        # launchertest.py): rounds per aim vary, so only a count
        if p[1] == "setup":
            _totals[k] = 0
            progress("lab", 0, 0, "rounds")
        elif p[1] in ("landed", "fired", "lost"):
            _totals[k] = _totals.get(k, 0) + 1
            progress("lab", _totals[k], 0, "rounds")
