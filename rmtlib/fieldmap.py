"""`rmt.py fieldmap`: install a baked site into the field map website (arma-map's everon-map), 2D and 3D views both.

The site reads, per map, from static/data/maps/<id>/ (the field map and the 3D view at /3d/ read the very same
files):

    roads.json                the road network
    places.json               town and landmark names
    foliage.json, plants/     the plant kinds (with each kind's measured shape, which the 3D view's "Measured tree
                              shapes" draws), and every tree and bush (position, ground height, scale, kind)
    los/                      500 m line-of-sight tiles and index.json (the 3D view also draws its terrain and
                              objects from them)
    light/                    10 m grids (height, forest, canopy, buildings, lz, foliage, clutter)
    foliage/foliage_profiles.json   the measured plant profiles for the Measured line of sight
    trees/                    the 3D view's shaped trees (rmtlib/trees.py, from the entities export)
    tiles/                    satellite tiles, for every map whose map.json names no "upstream" tile server
                              (Everon's come from it for now; pass --tiles to copy them anyway)
    relief/                   the shaded-relief map as tiles (rmtlib/relief.py), the site's second base layer
    map.json                  what the site knows about the map: title, size, grid, 3D camera start... The site lists
                              every folder with one (its join screen and the 3D view), so a new map needs no code.
                              Fields that the bake doesn't measure (title, start, order, slug, upstream) are kept
                              from the one already there.

foliage_shots.csv, the raw measurements, is a working file and isn't copied. Files with identical contents are left
alone; changed files are replaced even when their size and timestamps match.

Tree colours: the foliage photos are taken against a bright hazy sky, which washes leaf colours out, so Everon's
species table (static/data/maps/everon/trees/species.json) carries hand-tuned colours. Every kind in it keeps them, on
every map; other kinds get plain tree and bush greens, or colours from the photos with `photos`.

Port of arma-map's old everon-map/tools/import_map_data.py and everon-3d-map's old tools/import_rmt.py.
"""

import json
import os
import shutil
import filecmp

from . import trees as tree_builder

def site_maps(field_map):
    """{map id: its map.json} for every map the site already has (static/data/maps/<id>/map.json)."""
    base = os.path.join(field_map or '', 'static', 'data', 'maps')
    out = {}
    if not field_map or not os.path.isdir(base):
        return out
    for name in sorted(os.listdir(base)):
        path = os.path.join(base, name, 'map.json')
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf8') as f:
                    out[name] = json.load(f)
            except (OSError, ValueError):
                pass
    return out


def site_map_id(field_map, slug):
    """The site's id for a world, from the "slug" in its map.json; None when the site doesn't have it yet."""
    return next((k for k, m in site_maps(field_map).items() if m.get('slug') == slug), None)


def default_field_map(repo):
    """arma-map/everon-map beside the folder this repo is in, if it is there."""
    from pathlib import Path
    root = Path(repo).resolve()
    for parent in (root, *list(root.parents)[:3]):
        for folder in ('arma-map/arma-map', 'arma-map/everon-map', 'arma-map', 'everon-map'):
            candidate = parent/folder
            if (candidate/'server.py').is_file():
                return str(candidate)
    return None


def copy_tree(src, dst, base, log):
    # Binary exports often retain their size after changing; compare contents before skipping.
    def keep_new(s, d):
        filecmp.clear_cache()  # repeated installs must not reuse an earlier stat-based comparison
        if os.path.isfile(d) and filecmp.cmp(s, d, shallow=False):
            return d
        return shutil.copy2(s, d)
    shutil.copytree(src, dst, copy_function=keep_new, dirs_exist_ok=True)
    files = [os.path.join(r, f) for r, _, fs in os.walk(dst) for f in fs]
    log(f'  {os.path.relpath(dst, base)}: {len(files)} files, {sum(os.path.getsize(f) for f in files) / 1e6:.1f} MB')


def copy_file(src, dst, base, log):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)
    log(f'  {os.path.relpath(dst, base)}: {os.path.getsize(dst) / 1e6:.2f} MB')


def tuned_colours(field_map):
    """{species name: (trunk, crown)} from the site's Everon tree table, read before anything is rebuilt."""
    path = os.path.join(field_map, 'static', 'data', 'maps', 'everon', 'trees', 'species.json')
    if not os.path.isfile(path):
        return {}
    with open(path, encoding='utf8') as f:
        return {s['name']: (s['trunk'], s['crown']) for s in json.load(f)['species']}


def build_trees(raw, site, out, colours, photos, log):
    """The 3D view's trees for one map, with the tuned colours put back. Returns how many kinds kept them."""
    table = tree_builder.build(os.path.join(raw, 'objects'), os.path.join(site, 'foliage'), out, photos=photos, log=log)
    borrowed = 0
    for s in table['species']:
        if s['name'] in colours:
            s['trunk'], s['crown'] = colours[s['name']]
            borrowed += 1
    table['version'] += 'c'
    with open(os.path.join(out, 'species.json'), 'w', encoding='utf8', newline='\n') as f:
        json.dump(table, f, separators=(',', ':'))
        f.write('\n')
    return borrowed, len(table['species'])


def map_entry(manifest, raw, out, map_id, field_map, title=None):
    """The map's map.json, from its line-of-sight index and the export's probe; title, camera start, list order and
    anything else the bake doesn't measure come from the map.json already there (a new map: `title`, or the world's
    name, the land chunk nearest the middle, and last in the list)."""
    known = site_maps(field_map)
    old = known.get(map_id, {})
    title = title or old.get('title') or manifest.get('world') or map_id.title()
    start = old.get('start')
    with open(os.path.join(out, 'los', 'index.json'), encoding='utf8') as f:
        index = json.load(f)
    probe = manifest.get('probe')
    if not probe:
        with open(os.path.join(raw, 'probe.json'), encoding='utf8') as f:
            probe = json.load(f)
    g = index['grid']
    if start is None:
        land = [tuple(map(int, t.split('_'))) for t in index['tiles']]
        cx = sum(t[0] for t in land) / len(land)
        cz = sum(t[1] for t in land) / len(land)
        tx, tz = min(land, key=lambda t: (t[0] - cx) ** 2 + (t[1] - cz) ** 2)
        start = (g['x0'] + (tx + 0.5) * g['tile'], g['z0'] + (tz + 0.5) * g['tile'])
    orders = [m['order'] for k, m in known.items() if k != map_id and isinstance(m.get('order'), (int, float))]
    entry = {
        'title': title, 'slug': manifest['slug'], 'order': old.get('order', max(orders, default=0) + 1),
        'world': float(probe['max'][0] - probe['min'][0]), 'tile': g['tile'], 'cols': g['cols'],
        'rows': g['rows'], 'lightCols': index['light']['cols'], 'lightCell': index['light']['cell'],
        'unit': index['terrain']['unit'], 'start': list(start),
        'hasTrees': os.path.isfile(os.path.join(out, 'trees', 'species.json')),
        # when the relief tiles were made (browsers keep map data for a week, so the address changes with them)
        'hasRelief': int(os.path.getmtime(os.path.join(out, 'relief'))) if os.path.isdir(os.path.join(out, 'relief')) else 0,
    }
    return {**old, **entry}


def install(manifest, site, field_map, map_id, tiles=False, photos=None, title=None, log=print):
    """Install one world's bake into <field_map>/static/data/maps/<map_id>/, with its map.json."""
    raw = manifest['raw']
    base = os.path.join(field_map, 'static', 'data')
    out = os.path.join(base, 'maps', map_id)
    log(f'{map_id}: {site} -> {out}')
    colours = tuned_colours(field_map)
    upstream = 'upstream' in site_maps(field_map).get(map_id, {})   # its tiles come from another site
    copy_file(os.path.join(site, 'foliage', 'foliage_profiles.json'), os.path.join(out, 'foliage', 'foliage_profiles.json'), base, log)
    for name in ('roads.json', 'places.json', 'foliage.json'):
        copy_file(os.path.join(site, name), os.path.join(out, name), base, log)
    for name in ('los', 'plants', 'light', 'relief') + (('tiles',) if not upstream or tiles else ()):
        if os.path.isdir(os.path.join(site, name)):
            copy_tree(os.path.join(site, name), os.path.join(out, name), base, log)
        else:
            log(f'  {name}/: not in the bake, left as it is')

    if os.path.isdir(os.path.join(raw, 'objects')) and os.path.isfile(os.path.join(site, 'foliage', 'foliage_shots.csv')):
        borrowed, kinds = build_trees(raw, site, os.path.join(out, 'trees'), colours, photos, log)
        log(f'  trees/: tuned colours for {borrowed}/{kinds} kinds')
    else:
        log('  trees/: no entities export or foliage measurements, left as they are')

    entry = map_entry(manifest, raw, out, map_id, field_map, title)
    with open(os.path.join(out, 'map.json'), 'w', encoding='utf8', newline='\n') as f:
        json.dump(entry, f, indent=1)
        f.write('\n')
    log(f'  maps/{map_id}/map.json: listed as {entry["title"]}')
