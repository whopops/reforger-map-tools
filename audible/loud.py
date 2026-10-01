"""Loudness (BS.1770 K-weighted, LUFS) and peak of game wavs pulled straight from the paks."""
import io, re, sys, wave, struct
import numpy as np
from scipy import signal
sys.path.insert(0, '.')
import pakx

IX = pakx.index()
FILES = {}
for pak, files in IX.items():
    for p, *rest in files:
        if p.endswith('.wav'):
            FILES[p] = (pak, rest)


def load(path):
    pak, rest = FILES[path]
    raw = pakx.read(pak, *rest)
    w = wave.open(io.BytesIO(raw))
    n, ch, sw, fs = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
    b = w.readframes(n)
    if sw == 2:
        x = np.frombuffer(b, '<i2').astype(float) / 32768
    elif sw == 3:
        a = np.frombuffer(b, np.uint8).reshape(-1, 3)
        x = ((a[:, 0].astype(np.int32) | a[:, 1].astype(np.int32) << 8 | a[:, 2].astype(np.int32) << 16) << 8 >> 8) / 8388608.0
    else:
        x = np.frombuffer(b, '<i4').astype(float) / 2147483648
    return x.reshape(-1, ch), fs


def kweight(x, fs):
    # BS.1770 pre-filter + RLB, designed for any fs via bilinear transform of the analog prototypes
    f0, Q, G = 1681.974450955533, 0.7071752369554196, 3.999843853973347
    K = np.tan(np.pi * f0 / fs); Vh = 10 ** (G / 20); Vb = Vh ** 0.4996667741545416
    a0 = 1 + K / Q + K * K
    b = [(Vh + Vb * K / Q + K * K) / a0, 2 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0]
    a = [1, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0]
    f0, Q = 38.13547087602444, 0.5003270373238773
    K = np.tan(np.pi * f0 / fs)
    a2 = [1, 2 * (K * K - 1) / (1 + K / Q + K * K), (1 - K / Q + K * K) / (1 + K / Q + K * K)]
    b2 = [1, -2, 1]
    return signal.lfilter(b2, a2, signal.lfilter(b, a, x, axis=0), axis=0)


def lufs(x, fs):
    y = kweight(x, fs)
    z = (y ** 2).sum(axis=1) if y.ndim > 1 else y ** 2
    blk, hop = int(0.4 * fs), int(0.1 * fs)
    if len(z) < blk:
        return -0.691 + 10 * np.log10(z.mean() + 1e-20)
    l = np.array([z[i:i + blk].mean() for i in range(0, len(z) - blk + 1, hop)])
    L = -0.691 + 10 * np.log10(l + 1e-20)
    keep = l[L > -70]
    g = -0.691 + 10 * np.log10(keep.mean() + 1e-20)
    keep = l[L > g - 10]
    return -0.691 + 10 * np.log10(keep.mean() + 1e-20)


def stats(path):
    x, fs = load(path)
    pk = 20 * np.log10(np.abs(x).max() + 1e-12)
    rms = 20 * np.log10(np.sqrt((x ** 2).sum(axis=1).mean()) + 1e-12)
    return dict(fs=fs, ch=x.shape[1], sec=len(x) / fs, lufs=lufs(x, fs), peak=pk, rms=rms)


if __name__ == '__main__':
    for pat in sys.argv[1:]:
        for p in sorted(FILES):
            if re.search(pat, p):
                try:
                    s = stats(p)
                    print(f"{s['lufs']:7.1f} LUFS  pk {s['peak']:6.1f}  rms {s['rms']:6.1f}  {s['sec']:5.1f}s  {p.split('/')[-1]}")
                except Exception as e:
                    print('ERR', p, e)
