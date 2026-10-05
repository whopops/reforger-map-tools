"""Read files out of Enfusion .pak archives (the game's packed data), e.g. BI's own scripts for reference.

Layout: "FORM" <u32 BE size> "PAC1", then chunks <4-char id> <u32 BE size> <data>: HEAD, DATA (file bytes),
FILE (the directory tree). A tree entry is <u8 kind: 0 dir, 1 file> <u8 name length> <name>, then for a
directory <u32 LE child count> and its children, for a file <u32 offset> <u32 stored size> <u32 size> <u32> <u16>
<u8 compressed> <u8 level> <u32 time> (little endian; offsets are from the start of the .pak).

  python -m rmtlib.pak list  <pattern>         paths matching a regex, across the game's paks
  python -m rmtlib.pak cat   <exact path>      print one file
"""

import glob
import os
import re
import struct
import sys
import zlib

from .steam import GAME_APP, app


def entries(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"FORM" or data[8:12] != b"PAC1":
        return
    pos = 12
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        body = pos + 8
        if cid == b"FILE":
            yield from _tree(data, body, body + size, "")
            return
        pos = body + size


def _tree(data, pos, end, prefix):
    """Walk the FILE chunk. Returns (path, offset, stored, size, compressed) for every file."""
    stack = [(prefix, None)]  # (folder prefix, children left)
    # the root is a directory entry itself
    while pos < end:
        kind = data[pos]
        n = data[pos + 1]
        name = data[pos + 2:pos + 2 + n].decode("utf8", errors="replace")
        pos += 2 + n
        folder = stack[-1][0]
        if kind == 0:
            count = struct.unpack("<I", data[pos:pos + 4])[0]
            pos += 4
            _consume(stack)
            stack.append((f"{folder}{name}/" if name else folder, count))
            _pop_done(stack)
        else:
            off, stored, size, _, _, comp, _, _ = struct.unpack("<IIIIHBBI", data[pos:pos + 24])
            pos += 24
            _consume(stack)
            yield folder + name, off, stored, size, comp
            _pop_done(stack)


def _consume(stack):
    folder, left = stack[-1]
    if left is not None:
        stack[-1] = (folder, left - 1)


def _pop_done(stack):
    while len(stack) > 1 and stack[-1][1] == 0:
        stack.pop()


def read(pak, off, stored, size, comp):
    with open(pak, "rb") as f:
        f.seek(off)
        raw = f.read(stored)
    return zlib.decompress(raw) if comp else raw


def game_paks():
    game, _ = app(GAME_APP)
    return sorted(glob.glob(os.path.join(game, "addons", "*", "*.pak")))


def read_file(path):
    """One file's bytes by its exact path, from whichever game pak has it."""
    for pak in game_paks():
        for p, off, stored, size, comp in entries(pak):
            if p == path:
                return read(pak, off, stored, size, comp)
    raise FileNotFoundError(path)


def main(argv):
    cmd, arg = argv[0], argv[1]
    for pak in game_paks():
        for path, off, stored, size, comp in entries(pak):
            if cmd == "list" and re.search(arg, path):
                print(f"{path}  ({size} bytes, {os.path.basename(pak)})")
            elif cmd == "cat" and path == arg:
                sys.stdout.write(read(pak, off, stored, size, comp).decode("utf8", errors="replace"))
                return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
