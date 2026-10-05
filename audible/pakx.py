"""Index the game's .pak files (seeking to the FILE chunk only) and grep/cat files out of them."""
import glob, json, os, re, struct, sys, zlib

GAME = r"C:\Program Files (x86)\Steam\steamapps\common\Arma Reforger\addons"
IDX = os.path.join(os.path.dirname(__file__), "pakindex.json")


def tree(data):
    out, stack, pos = [], [("", None)], 0
    while pos < len(data):
        kind, n = data[pos], data[pos + 1]
        name = data[pos + 2:pos + 2 + n].decode("utf8", "replace")
        pos += 2 + n
        folder = stack[-1][0]
        if stack[-1][1] is not None:
            stack[-1] = (folder, stack[-1][1] - 1)
        if kind == 0:
            count = struct.unpack("<I", data[pos:pos + 4])[0]
            pos += 4
            stack.append((f"{folder}{name}/" if name else folder, count))
        else:
            off, stored, size, _, _, comp, _, _ = struct.unpack("<IIIIHBBI", data[pos:pos + 24])
            pos += 24
            out.append((folder + name, off, stored, size, comp))
        while len(stack) > 1 and stack[-1][1] == 0:
            stack.pop()
    return out


def index():
    if os.path.exists(IDX):
        return json.load(open(IDX))
    res = {}
    for pak in sorted(glob.glob(os.path.join(GAME, "*", "*.pak"))):
        with open(pak, "rb") as f:
            head = f.read(12)
            if head[:4] != b"FORM":
                continue
            while True:
                h = f.read(8)
                if len(h) < 8:
                    break
                cid, size = h[:4], struct.unpack(">I", h[4:])[0]
                if cid == b"FILE":
                    res[pak] = tree(f.read(size))
                    break
                f.seek(size, 1)
    json.dump(res, open(IDX, "w"))
    return res


def read(pak, off, stored, size, comp):
    with open(pak, "rb") as f:
        f.seek(off)
        raw = f.read(stored)
    return zlib.decompress(raw) if comp else raw


if __name__ == "__main__":
    cmd, arg = sys.argv[1], sys.argv[2]
    ix = index()
    for pak, files in ix.items():
        for p, *rest in files:
            if cmd == "list" and re.search(arg, p, re.I):
                print(p, rest[2])
            elif cmd == "cat" and p == arg:
                sys.stdout.buffer.write(read(pak, *rest))
                sys.exit(0)
            elif cmd == "grep":  # grep <pathregex>::<textregex>
                pr, tr = arg.split("::")
                if re.search(pr, p, re.I):
                    t = read(pak, *rest).decode("utf8", "replace")
                    for i, line in enumerate(t.splitlines()):
                        if re.search(tr, line, re.I):
                            print(f"{p}:{i+1}: {line.strip()[:200]}")
