"""Decode single-channel Enfusion .edds textures (a tree crown's opacity map) into every mip level.

An .edds is a DDS header (with a DX10 block here) whose fourcc slot says "ENF1", then a directory of <4-char tag>
<u32 stored size> per mip, smallest first, then the mips' bytes in that order: "COPY" stored as is, "LZ4 " as
<u32 size> and 64 KiB LZ4 chunks (the same framing as .xob LODs; rmtlib/sights.py reads the same files for optics).
Every vegetation opacity map in the base game is BC4 (DXGI 80); R8 (61) is read too.

The stored mips are the game's own: vegetation opacity is imported with a mip filter that keeps it denser in the small
mips (mean opacity rises 67 -> 106 from mip 0 to mip 7 on the spruce's map, where a box filter keeps it flat), so a
measurement that samples the mip the game would sample gets the thickening at distance for free.
"""

import struct

import numpy as np

from .sights import lz4_block

BC4, R8 = 80, 61


def bc4(data, w, h):
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    b = np.frombuffer(data, np.uint8, bw * bh * 8).reshape(bh * bw, 8)
    r0, r1 = b[:, 0].astype(np.int32), b[:, 1].astype(np.int32)
    pal = np.zeros((len(b), 8), np.int32)
    pal[:, 0], pal[:, 1] = r0, r1
    gt = r0 > r1
    for i in range(1, 7):
        pal[:, i + 1] = np.where(gt, ((7 - i) * r0 + i * r1) // 7, 0)
    for i in range(1, 5):
        pal[:, i + 1] = np.where(gt, pal[:, i + 1], ((5 - i) * r0 + i * r1) // 5)
    pal[:, 6] = np.where(gt, pal[:, 6], 0)
    pal[:, 7] = np.where(gt, pal[:, 7], 255)
    bits = np.zeros(len(b), np.uint64)
    for i in range(6):
        bits |= b[:, 2 + i].astype(np.uint64) << np.uint64(8 * i)
    sel = np.stack([(bits >> np.uint64(3 * j)) & np.uint64(7) for j in range(16)], 1).astype(np.int64)
    px = np.take_along_axis(pal, sel, 1).reshape(bh, bw, 4, 4).transpose(0, 2, 1, 3).reshape(bh * 4, bw * 4)
    return px[:h, :w].astype(np.uint8)


def mips(data):
    """[mip 0 (largest), mip 1, ...] as uint8 (h, w) arrays."""
    if data[:4] != b"DDS " or data[36:40] != b"ENF1":
        raise ValueError("not an Enfusion .edds")
    h, w = struct.unpack_from("<II", data, 12)
    count = struct.unpack_from("<I", data, 28)[0] or 1
    dx10 = data[84:88] == b"DX10"
    fmt = struct.unpack_from("<I", data, 128)[0] if dx10 else None
    if fmt not in (BC4, R8):
        raise ValueError(f"texture format {fmt} is not a single-channel one this reads (BC4 or R8)")
    header = 148 if dx10 else 128
    cursor, payloads = header + count * 8, []
    for k in range(count):
        tag = data[header + k * 8:header + k * 8 + 4]
        stored = struct.unpack_from("<I", data, header + k * 8 + 4)[0]
        payloads.append((tag, data[cursor:cursor + stored]))
        cursor += stored
    out = []
    for level in range(count):
        tag, payload = payloads[count - 1 - level]
        if tag == b"LZ4 ":
            size = struct.unpack_from("<I", payload)[0]
            raw, p = bytearray(), 4
            while p < len(payload):
                n = struct.unpack_from("<I", payload, p)[0] & 0x7FFFFFFF
                p += 4
                lz4_block(payload[p:p + n], raw, size)
                p += n
            raw = bytes(raw)
        elif tag == b"COPY":
            raw = payload
        else:
            raise ValueError(f"unknown mip storage {tag!r}")
        lw, lh = max(1, w >> level), max(1, h >> level)
        out.append(bc4(raw, lw, lh) if fmt == BC4 else np.frombuffer(raw, np.uint8, lw * lh).reshape(lh, lw).copy())
    return out
