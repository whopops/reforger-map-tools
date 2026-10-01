"""Where a gunshot drops below the game's background noise, from the game's own sound files.

Shot: the muzzle-blast layers ('Far' and 'Mid' calibre samples, not the supersonic crack), scaled so the shot has the
loudness its amplitude class names at the inner range; falls 6 dB per doubling of distance plus air absorption.
Noise: the ambient bed / wind samples (all mastered to -30 LUFS), played through the wind bus (-10 dB).
Audible = any third-octave band of the shot's loudest 50 ms is above that band's noise over the same time."""
import sys, re
import numpy as np
sys.path.insert(0, '.')
import loud

FS = 48000
BANDS = [50 * 2 ** (i / 3) for i in range(0, 22)]  # 50 Hz .. ~6.3 kHz, third-octave centres
BANDS = [b for b in BANDS if b < 12000]


def mono(path):
    x, fs = loud.load(path)
    x = x.mean(axis=1)
    if fs != FS:
        from scipy.signal import resample_poly
        from math import gcd
        g = gcd(fs, FS)
        x = resample_poly(x, FS // g, fs // g)
    return x


def band_energy(seg):
    """Energy per third-octave band of a segment (Parseval on the FFT)."""
    n = len(seg)
    sp = np.abs(np.fft.rfft(seg * np.hanning(n))) ** 2 / n
    f = np.fft.rfftfreq(n, 1 / FS)
    out = []
    for c in BANDS:
        m = (f >= c / 2 ** (1 / 6)) & (f < c * 2 ** (1 / 6))
        out.append(sp[m].sum() * 2 / n if m.any() else 1e-20)
    return np.array(out)


def kw_lufs(x):
    return loud.lufs(x.reshape(-1, 1), FS)


def shot_bands(paths, win=0.05):
    """Band energies of the loudest 50 ms window of each sample (averaged), plus the mean crest relative to LUFS."""
    es, lufs = [], []
    for p in paths:
        x = mono(p)
        w = int(win * FS)
        hop = w // 4
        best = max(range(0, max(1, len(x) - w), hop), key=lambda i: np.sum(x[i:i + w] ** 2))
        es.append(band_energy(x[best:best + w]))
        lufs.append(kw_lufs(np.pad(x, (0, max(0, int(0.4 * FS) - len(x))))))
    return np.mean(es, axis=0), float(np.mean(lufs))


def noise_bands(paths, win=0.05):
    es = []
    for p in paths:
        x = mono(p)
        w = int(win * FS)
        e = [band_energy(x[i:i + w]) for i in range(0, len(x) - w, w * 4)]
        es.append(np.mean(e, axis=0))
    return np.mean(es, axis=0)


def absorption_db_per_km(f, t=15.0, rh=70.0, pa=101.325):
    """ISO 9613-1 pure-tone air absorption."""
    T = t + 273.15; T0 = 293.15; T01 = 273.16
    psat = 101.325 * 10 ** (-6.8346 * (T01 / T) ** 1.261 + 4.6151)
    h = rh * psat / pa
    frO = pa / 101.325 * (24 + 4.04e4 * h * (0.02 + h) / (0.391 + h))
    frN = pa / 101.325 * (T / T0) ** -0.5 * (9 + 280 * h * np.exp(-4.170 * ((T / T0) ** (-1 / 3) - 1)))
    a = 8.686 * f ** 2 * (1.84e-11 * (101.325 / pa) * (T / T0) ** 0.5
                          + (T / T0) ** -2.5 * (0.01275 * np.exp(-2239.1 / T) / (frO + f ** 2 / frO)
                                                + 0.1068 * np.exp(-3352 / T) / (frN + f ** 2 / frN)))
    return a * 1000


def db(x):
    return 10 * np.log10(np.maximum(x, 1e-30))


if __name__ == '__main__':
    files = sorted(loud.FILES)
    far = [p for p in files if re.search(r'Calibre/545/Weapons_545_556_(Far|Mid)_0[1-5]\.wav', p)]
    beds = [p for p in files if re.search(r'Ambients2D/Samples/(Bed/Environment_Bed_(Meadow|Forest|Hills)_LP|Wind/Environment_Wind_(Meadow|Forest|Hills)_Mid_LP)\.wav', p)]
    print(len(far), 'shot samples;', len(beds), 'noise samples')
    S, s_l = shot_bands(far)
    N = noise_bands(beds)
    print('shot sample loudness', round(s_l, 1), 'LUFS')
    np.save('S.npy', S); np.save('N.npy', N)
    print('band Hz   shot dB  noise dB')
    for c, s, n in zip(BANDS, db(S), db(N)):
        print(f'{c:7.0f}  {s:7.1f}  {n:7.1f}')
