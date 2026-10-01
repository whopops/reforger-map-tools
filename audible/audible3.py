import json, math, sys
sys.path.insert(0, '.')
from audible2 import reach

RIFLE = -15.5
db = lambda s: 20 * math.log10(s / 76)
G = {  # level at 2 m, LUFS (game class names; slope ratios where the class has no name)
    'rifle': RIFLE, 'rifle-s': RIFLE + db(42), 'mg': -13.5, 'hmg': -9.0, 'launcher': -9.0, 'gl': RIFLE, 'pistol': RIFLE,
    'mortar': RIFLE + db(45), 'he': RIFLE + db(65), 'practice': RIFLE + db(65), 'smoke': RIFLE + db(20), 'illum': RIFLE + db(50),
}
NOISE = {'still': -55, 'breeze': -50, 'windy': -45, 'storm': -40}
out = {k: {n: int(round(reach(v, nl) / 5) * 5) for n, nl in NOISE.items()} for k, v in G.items()}
for k, v in out.items():
    print(f'{k:9s} {G[k]:6.1f}', v)
json.dump({'levels': G, 'noise': NOISE, 'reach': out}, open('audible.json', 'w'), indent=1)
