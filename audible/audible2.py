import numpy as np, sys
sys.path.insert(0, '.')
from audible import BANDS, db, absorption_db_per_km

S = db(np.load('S.npy')); N = db(np.load('N.npy'))
ok = [i for i, b in enumerate(BANDS) if b >= 60]
alpha = absorption_db_per_km(np.array(BANDS))


def reach(class_lufs, noise_lufs, thresh=0.0, sample_lufs=-31.7, inner=2.0, rh=70):
    """distance where the shot's best band drops to the noise in that band."""
    gain = class_lufs - sample_lufs                 # put the shot at the loudness its amplitude class names, at the inner range
    noise = N + (noise_lufs - (-30.0))              # samples are mastered to -30 LUFS
    al = absorption_db_per_km(np.array(BANDS), rh=rh)
    for r in np.arange(inner, 20000, 5):
        snr = (S + gain - 20 * np.log10(r / inner) - al * (r - inner) / 1000) - noise
        if max(snr[i] for i in ok) < thresh:
            return r
    return 20000


if __name__ == '__main__':
    cls = {'rifle -15.5': -15.5, 'mg -13.5': -13.5, 'heavy -9': -9.0, 'supp (-5.2 dB)': -15.5 - 5.2}
    for nl in (-40, -45, -50, -55):
        print(f'noise {nl} LUFS:', {k: int(reach(v, nl)) for k, v in cls.items()})
    print('thresh -6 dB, noise -40:', {k: int(reach(v, -40, -6)) for k, v in cls.items()})
    print('thresh +6 dB, noise -40:', {k: int(reach(v, -40, 6)) for k, v in cls.items()})
