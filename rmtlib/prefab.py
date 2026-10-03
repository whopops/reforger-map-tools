"""Read values out of the game's prefabs, following their inheritance (`Type : "{GUID}parent.et" {`).

A prefab only lists what it changes; anything it doesn't set comes from its parent, and so on up. `value(path, name)`
finds the first `name <value>` line going up that chain. Good enough for the flat numeric settings the tools need
(InitSpeed, AirDrag, BulletInitSpeedCoef, MagazineTemplate...), not for telling apart two components with the same
setting.
"""
import functools, re

from rmtlib import pak

_PARENT = re.compile(r'^\s*\w+\s*:\s*"\{[0-9A-F]+\}([^"]+)"')


@functools.lru_cache(maxsize=None)
def _index():
    """Every file in the game paks: path -> (pak, offset, stored, size, compressed). Built once (a few seconds)."""
    out = {}
    for pk in pak.game_paks():
        for p, off, stored, size, comp in pak.entries(pk):
            out.setdefault(p, (pk, off, stored, size, comp))
    return out


@functools.lru_cache(maxsize=None)
def text(path):
    e = _index().get(path)
    if not e:
        raise FileNotFoundError(path)
    return pak.read(*e).decode('utf8', 'replace')


def chain(path):
    """The prefab and its ancestors, nearest first."""
    out = []
    while path and path not in out:
        out.append(path)
        try:
            m = _PARENT.match(text(path).splitlines()[0])
        except FileNotFoundError:
            break
        path = m.group(1) if m else None
    return out


def value(path, name, pattern=r'(\S.*)'):
    """The first `name <value>` in the prefab or its ancestors (the value as a string), or None."""
    rx = re.compile(r'^\s*' + re.escape(name) + r'\s+' + pattern + r'\s*$', re.M)
    for p in chain(path):
        try:
            m = rx.search(text(p))
        except FileNotFoundError:
            continue
        if m:
            return m.group(1).strip()
    return None


def number(path, name):
    v = value(path, name, r'([-0-9.eE]+)')
    return float(v) if v is not None else None


def resource(path, name):
    """A `name "{GUID}path"` setting, as the path."""
    v = value(path, name, r'"\{[0-9A-F]+\}([^"]+)"')
    return v
