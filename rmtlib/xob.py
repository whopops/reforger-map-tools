"""Read Enfusion .xob meshes (the game's models) out of the paks: every LOD, its parts, positions, UVs, triangles.

Layout (worked out and checked against the game on build 24903726, 2026-10-05: the decoded triangles, drawn by the
engine as debug shapes from the same camera, cover the game's own render of the plant to IoU 0.995):

  "FORM" <u32 BE size> "XOB9", then chunks <4-char id> <u32 BE size> <data>, packed with no padding:
    HEAD  the global box, the material list ("name\\0{GUID}path.emat\\0" pairs), part names, collision materials,
          then one record per LOD
    COLL, VOLM  collision data (not used here)
    LODS  every LOD's geometry, LZ4-compressed (64 KiB chunks <u32 size | 0x80000000 on a LOD's last chunk>, sharing
          a dictionary, as in .edds); smallest LOD first
  LOD record:  "LZO4" <u32 parts> <u32 0> <f32 screen-size threshold> <u32 0> <u32 file offset> <u32 stored> <u32 size>,
               then per part 64 + 20 * (uv sets) bytes:
                 <u8 ?> <u8 0> <u8 0> <u8 vertex format> <f32 x6 box> <16 bytes 0> <u16 triangles> <u16 vertices>
                 <u16 vertices + extra> <u32 0> <u16 0xffff> <u16 material> <u16 uv sets> <u16 0>
                 per uv set: <f32 u min> <f32 u max> <f32 v min> <f32 v max> <f32 texel density>
  LOD data, per part in record order:
    two triangle lists of `triangles` x 3 u16 (the first is the one drawn with the UVs; the second, over
    `vertices + extra` positions, is a depth/shadow list)
    positions  f32 x3 per vertex
    then 4-byte streams, one value per vertex each: normal, [colour if format & 0x20], uv0, [uv1 if format & 0x80],
    then a 12-byte record per vertex (an index and two per-card words: wind data, not needed here)
    then the extra vertices: 12 bytes each, 20 with two uv sets
  Vertex formats: 0x0f (32 bytes a vertex), 0x2f (+ colour, 36), 0x8f (+ uv1, 44), 0xaf (both, 48).
  UVs are signed 16-bit: uv = centre + half-range * s / 32767, centre and half-range from the part's uv-set floats.
  (Reading them as unsigned 0..1 over min..max puts many texels in the wrong place on the atlas; checked per pixel
  against the game.)
"""

import re
import struct

import numpy as np

from .sights import lz4_block

STRIDE = {0x0F: 32, 0x2F: 36, 0x8F: 44, 0xAF: 48}
UV_STREAM = {0x0F: 1, 0x2F: 2, 0x8F: 1, 0xAF: 2}   # which 4-byte stream after the positions holds uv0
_MAT = re.compile(rb"(\{[0-9A-F]{16}\})([^\x00]+?\.emat)")


class Part:
    def __init__(self, material, fmt, positions, uv, triangles):
        self.material = material          # .emat path (no GUID), or None
        self.format = fmt
        self.positions = positions        # float64 (n, 3), metres, the model's own axes (y up)
        self.uv = uv                      # float64 (n, 2)
        self.triangles = triangles        # int64 (m, 3)


class Lod:
    def __init__(self, threshold, parts):
        self.threshold = threshold        # the screen-size threshold the .xob stores for it
        self.parts = parts

    @property
    def triangles(self):
        return sum(len(p.triangles) for p in self.parts)


def chunks(data):
    if data[:4] != b"FORM" or data[8:12] != b"XOB9":
        raise ValueError("not an XOB9 mesh")
    pos, out = 12, {}
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4].decode("latin1")
        size = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        out[cid] = (pos + 8, size)
        pos += 8 + size
    return out


def _decompress(data, off, stored, size):
    p, end, out = off, off + stored, bytearray()
    while p < end:
        n = struct.unpack_from("<I", data, p)[0]
        p += 4
        last, n = n >> 31, n & 0x7FFFFFFF
        lz4_block(data[p:p + n], out, size)
        p += n
        if last:
            break
    if len(out) != size:
        raise ValueError(f"LOD data is {len(out)} bytes, the record says {size}")
    return bytes(out)


def records(head):
    """The LOD records in a HEAD chunk: [(threshold, offset, stored, size, [part dicts])], largest LOD first."""
    out, i = [], 0
    while True:
        i = head.find(b"LZO4", i)
        if i < 0:
            return out
        nparts, _, thr, _, off, stored, size = struct.unpack_from("<IIfIIII", head, i + 4)
        p, parts = i + 32, []
        for _ in range(nparts):
            nuv = struct.unpack_from("<H", head, p + 58)[0]
            parts.append(dict(
                fmt=head[p + 3], ntri=struct.unpack_from("<H", head, p + 44)[0],
                nv=struct.unpack_from("<H", head, p + 46)[0], nv2=struct.unpack_from("<H", head, p + 48)[0],
                mat=struct.unpack_from("<H", head, p + 56)[0], nuv=nuv,
                uvs=[struct.unpack_from("<5f", head, p + 64 + 20 * k) for k in range(nuv)]))
            p += 64 + 20 * nuv
        out.append((thr, off, stored, size, parts))
        i = p


def parse(data):
    """(lods, materials): the LODs, largest first, and the material paths in the mesh's own order."""
    ch = chunks(data)
    hs, hn = ch["HEAD"]
    head = data[hs:hs + hn]
    materials = [m.group(2).decode("utf8", "replace") for m in _MAT.finditer(head)]
    lods = []
    for thr, off, stored, size, parts in records(head):
        blob = _decompress(data, off, stored, size)
        p, out = 0, []
        for s in parts:
            fmt, nt, nv, nv2 = s["fmt"], s["ntri"], s["nv"], s["nv2"]
            if fmt not in STRIDE:
                raise ValueError(f"unknown vertex format {fmt:#x}")
            tris = np.frombuffer(blob, "<u2", nt * 3, p).reshape(-1, 3).astype(np.int64)
            pos = np.frombuffer(blob, "<f4", nv * 3, p + nt * 12).reshape(-1, 3).astype(np.float64)
            q = np.frombuffer(blob, "<i2", nv * 2, p + nt * 12 + nv * 12 + UV_STREAM[fmt] * nv * 4)
            q = q.reshape(-1, 2) / 32767.0
            u0, u1, v0, v1, _ = s["uvs"][0]
            uv = np.stack([(u0 + u1) / 2 + q[:, 0] * (u1 - u0) / 2, (v0 + v1) / 2 + q[:, 1] * (v1 - v0) / 2], 1)
            p += nt * 12 + nv * STRIDE[fmt] + (nv2 - nv) * (12 + 8 * (s["nuv"] - 1))
            mat = materials[s["mat"]] if s["mat"] < len(materials) else None
            out.append(Part(mat, fmt, pos, uv, tris))
        if p != len(blob):
            raise ValueError(f"LOD data left {len(blob) - p} bytes unread")
        lods.append(Lod(thr, out))
    return lods, materials
