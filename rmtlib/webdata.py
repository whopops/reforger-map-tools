"""Website input inventory and producers for data formerly embedded in application code."""
import csv
import fnmatch
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
from .ballistics import Catalog, write_json
from . import paths, sights

INPUTS = [
    ('Map metadata', 'maps/*/map.json', 'rmtlib/fieldmap.py', 'Data: Full map export + install'),
    ('Roads', 'maps/*/roads.json', 'rmtlib/bake_roads.py', 'Data: Roads'),
    ('Places', 'maps/*/places.json', 'rmtlib/bake_places.py', 'Data: Place names'),
    ('LOS / terrain / objects', 'maps/*/los/*', 'rmtlib/bake_los.py', 'Data: Terrain, objects and line of sight'),
    ('Light grids', 'maps/*/light/*', 'rmtlib/bake_los.py', 'Data: Terrain, objects and line of sight'),
    ('Plants', 'maps/*/plants/*', 'rmtlib/bake_plants.py', 'Data: Trees and foliage'),
    ('Foliage kinds', 'maps/*/foliage.json', 'rmtlib/bake_plants.py', 'Data: Trees and foliage'),
    ('Measured foliage profiles', 'maps/*/foliage/*', 'rmtlib/foliage.py', 'Data: Trees and foliage'),
    ('Shaped 3D trees', 'maps/*/trees/*', 'rmtlib/trees.py', 'Data: Install into field map'),
    ('Satellite', 'maps/*/tiles/*', 'rmtlib/satellite.py', 'Data: Satellite imagery'),
    ('Relief', 'maps/*/relief/*', 'rmtlib/relief.py', 'Data: Relief map'),
    ('Conflict references', '*.json', 'conflict.py', 'Website data: Conflict references'),
    ('Mortar firing tables', 'mortar-tables.json', 'rmtlib/webdata.py', 'Website data: Mortar tables'),
    ('Bullet flights', 'bullets.json', 'bullettest.py', 'Labs: Bullet flight test'),
    ('Rocket flights / launcher marks', 'rockets.json', 'rocketfit.py', 'Labs: Rocket flight test'),
    ('Custom ammunition', 'custom-ballistics/*', 'customballistics.py', 'Ballistics'),
    ('Custom sights / sketches', 'sights/*', 'sighttools.py', 'Sights'),
]


def inventory(site):
    site = Path(site).resolve()
    if not (site/'server.py').is_file():
        raise ValueError('Choose the application folder containing server.py (arma-map/arma-map).')
    data = site/'static'/'data'
    rows = [{'name': name, 'pattern': pattern, 'producer': producer, 'gui': gui,
             'producerPresent': (Path(paths.bundle())/producer).is_file(),
             'files': 0, 'bytes': 0} for name, pattern, producer, gui in INPUTS]
    unknown = []
    for file in data.rglob('*'):
        if not file.is_file():
            continue
        relative = file.relative_to(data).as_posix()
        # Broad root Conflict pattern is allowed only for recognized map IDs, never unknown future inputs.
        candidates = [r for r in rows if r['name'] != 'Conflict references' and fnmatch.fnmatchcase(relative, r['pattern'])]
        if not candidates and '/' not in relative and file.stem in {p.name for p in (data/'maps').glob('*') if p.is_dir()}:
            candidates = [r for r in rows if r['name'] == 'Conflict references']
        if not candidates:
            unknown.append(relative)
            continue
        row = candidates[0]; row['files'] += 1; row['bytes'] += file.stat().st_size
    return {'site': str(site), 'inputs': rows, 'unknown': unknown,
            'embeddedData': ['Mortar shell physics: webdata mortar', 'Mortar measured dispersion: webdata barrel',
                             'Sound reach: audible/audible3.py -> audible.json', 'Blast radii: webdata blast',
                             'Sight artwork/scale/zeros: Sights; legacy recipes in recipes/website-calibration.json',
                             'Construction registry membership: webdata construction; role recipes are curated',
                             'Tree colour calibration / cave coordinates: recipes/website-calibration.json'],
            'runtimeExcluded': ['rooms.json', 'bans.json', 'tile_cache', 'compressed_cache'],
            'note': 'Presence is not freshness or measurement validation. New unknown files require adding a producer.'}


def effective(catalog, record, context=None):
    result = None
    for item in reversed(catalog.chain(record, context)):
        tree = sights.parse(catalog.text(item), item['resource'])
        result = sights.merge(result, tree) if result else tree
    return result


def inherited_node(catalog, node, context):
    header = node['header']
    if ':' in header:
        reference = sights.unquote(header[header.index(':')+1])
        return sights.merge(effective(catalog, catalog.resolve(reference, context=context), context), node)
    return node


def value(node, key, default=None):
    found = node['fields'].get(key, {}).get('value', [])
    return sights.unquote(found[0]) if len(found) == 1 else default


SHELL_NAMES = {'M821': 'HE M821', 'M879': 'Practice M879', 'M819': 'Smoke M819',
               'M853A1': 'Illumination M853A1', 'O832DU': 'HE O-832DU',
               'D832DU': 'Smoke D-832DU', 'S832S': 'Illumination S-832C'}


def mortar_plan(catalog):
    plan, physics = [], {}
    for weapon, country in (('M252', 'US'), ('2B14', 'USSR')):
        record = catalog.resolve(f'Prefabs/Items/Equipment/BallisticTable/BallisticTable_{country}_base.et', owner='58D0FB3206B6F859')
        for node in sights.walk(effective(catalog, record)):
            if 'SCR_VisualisedBallisticConfig' not in node['header']:
                continue
            node = inherited_node(catalog, node, record['addonGuid'])
            ammo = catalog.resolve(value(node, 'm_sProjectilePrefab'), context=record['addonGuid'])
            code = next((k for k in SHELL_NAMES if k in ammo['path']), None)
            if code is None:
                raise ValueError(f'Unmapped mortar shell: {ammo["resource"]}')
            coef = float(value(node, 'm_fProjectileInitSpeedCoef', '1'))
            tree = effective(catalog, ammo, record['addonGuid'])
            move = next(n for n in sights.walk(tree) if 'ShellMoveComponent' in n['header'])
            gadget = next(n for n in sights.walk(tree) if 'SCR_MortarShellGadgetComponent' in n['header'])
            configs = next(n for n in gadget['children'] if n['header'] == ['m_aChargeRingConfig'])
            tokens = [t for k, v in configs['fields'].items() for t in [k]+v['value']]
            vals = list(map(float, tokens)); rings = {int(vals[i]): vals[i+1] for i in range(0, len(vals), 3)}
            ring = next((k for k, v in rings.items() if abs(v-coef) < .00001), None)
            if ring is None:
                raise ValueError('Table coefficient does not match a shell charge ring')
            name = SHELL_NAMES[code]
            phys = {'v0': float(value(move, 'InitSpeed')), 'mass': float(value(move, 'Mass')),
                    'airDrag': float(value(move, 'AirDrag')), 'rings': rings, 'source': ammo['resource']}
            phys['k'] = phys['airDrag']/phys['mass']; physics[weapon+'|'+name] = phys
            mils = 6000 if value(node, 'm_sUnitType') == 'MILS_WARSAW' else 6400
            plan.append({'id': str(len(plan)), 'weapon': weapon, 'shell': name, 'ring': ring, 'prefab': ammo['resource'],
                         'coef': coef, 'min': max(1, int(value(node, 'm_iMinRange', '50'))),
                         'max': int(value(node, 'm_iMaxRange', '5000')), 'step': int(value(node, 'm_iRangeStep', '100')),
                         'mils': mils, 'dispersion': float(value(node, 'm_fStandardDispersion', '0'))})
    return plan, physics


def bake_mortar(plan, raw):
    grouped = {}
    with Path(raw).open(newline='', encoding='utf8') as file:
        for row in csv.DictReader(file):
            grouped.setdefault(row['id'], []).append([float(row[k]) for k in ('range', 'elevation', 'time', 'delevation')])
    weapons = {}
    for page in plan:
        table = sorted(grouped.get(page['id'], []))
        if len(table) < 2 or any(not all(math.isfinite(v) for v in r) or r[2] <= 0 for r in table):
            raise ValueError(f'Missing/invalid mortar rows: {page["weapon"]} / {page["shell"]} / ring {page["ring"]}')
        if len({r[0] for r in table}) != len(table):
            raise ValueError('Duplicate mortar range rows')
        # Last half-step may be outside the engine table; use previous derivative, as the paper table does.
        if table[-1][3] <= 0:
            table[-1][3] = table[-2][3]
        weapon = weapons.setdefault(page['weapon'], {'label': 'M252 81mm (US)' if page['weapon'] == 'M252' else '2B14 82mm (USSR)',
                                                    'milsPerCircle': page['mils'], 'shells': {}})
        weapon['shells'].setdefault(page['shell'], {})[str(page['ring'])] = {'dispersion': page['dispersion'], 'table': table}
    return {'source': 'Engine BallisticTable lookup; dispersion is the current game config standard value, not measured 90% spread.',
            'columns': ['range_m', 'elev_mil', 'time_s', 'delev_mil_per_100m'], 'weapons': weapons}


def mortar(catalog, output, launch=True):
    from .export import Exporter
    from .workbench import Runner, read_status
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    plan, physics = mortar_plan(catalog)
    write_json(output/'mortar-plan.json', plan); write_json(output/'mortar-physics.json', physics)
    signature = hashlib.sha256(json.dumps([plan, catalog.install.game_build], sort_keys=True).encode()).hexdigest()[:16]
    relative = f'rmt/_mortar/{signature}'; profile = Path(catalog.install.profile)/relative
    profile.mkdir(parents=True, exist_ok=True)
    with (profile/'plan.csv').open('w', newline='', encoding='utf8') as file:
        writer = csv.writer(file); keys = ('id', 'prefab', 'coef', 'min', 'max', 'step', 'mils')
        writer.writerow(keys); writer.writerows([[row[k] for k in keys] for row in plan])
    if not launch:
        return str(output.resolve())
    resource, _, _ = Exporter(catalog.install).resolve('EmptyEden')
    code, _, _ = Runner(catalog.install).run('mortar_tables', relative, resource,
                                            args=[f'-rmtMortarPlan={relative}/plan.csv'], stall=300)
    status = read_status(str(profile/'mortar_tables.status.json'))
    if code != 0 or not status or status.get('result') != 'done':
        raise ValueError('Mortar table lookup did not finish; raw plan/results preserved in '+str(profile))
    doc = bake_mortar(plan, profile/'mortar_tables'/'tables.csv')
    doc['gameBuild'] = catalog.install.game_build
    write_json(output/'mortar-tables.json', doc)
    return str(output.resolve())


def blast(summary):
    result = {}
    for key, row in summary.items():
        parts = key.split('|')
        if len(parts) != 3 or parts[1].lower() not in ('stand', 'standing') or parts[2] != 'uncon':
            continue
        kill, danger = row.get('down50'), row.get('hurt10')
        if not isinstance(kill, (int, float)) or not isinstance(danger, (int, float)) or not all(math.isfinite(x) and x >= 0 for x in (kill, danger)):
            raise ValueError('Blast fit has missing/nonfinite radii; measure more trials')
        result[parts[0]] = {'kill': kill, 'danger': danger}
    if not result:
        raise ValueError('No standing/unconscious-enabled blast fits found')
    return {'source': 'blasttest summary: down50 kill / hurt10 danger, standing, unconsciousness enabled', 'BLAST': result}


def barrel(folder):
    import firetest
    samples = firetest.muzzle_samples(str(folder))
    result = {}
    for weapon in sorted({s['w'] for s in samples}):
        rows = [s for s in samples if s['w'] == weapon]
        if len(rows) < 3:
            raise ValueError('At least 3 complete muzzle samples are required per mortar')
        rad = 2*math.pi/6400
        result[weapon] = {'rounds': len(rows), 'speedSD': statistics.stdev(s['dv_base'] for s in rows),
                          'speedBias': statistics.mean(s['dv_base'] for s in rows),
                          'barrelSD': [statistics.pstdev(s[k] for s in rows)*rad for k in ('de', 'da')]}
    if not result:
        raise ValueError('No complete muzzle samples')
    return {'source': str(Path(folder).resolve()), 'units': 'm/s base speed; barrel angular SD radians', 'weapons': result}


REGISTRIES = ('Configs/Editor/PlaceableEntities/Compositions/Compositions_FreeRoamBuilding.conf',
              'Configs/Editor/PlaceableEntities/Compositions/Compositions_FreeRoamBuilding_HQC.conf')


def construction(catalog):
    entries = {}
    for path in REGISTRIES:
        record = catalog.resolve(path, owner='58D0FB3206B6F859')
        for reference in re.findall(r'"(\{[0-9A-Fa-f]{16}\}[^"\r\n]+\.et)"', catalog.text(record)):
            entries.setdefault(reference, []).append(record['resource'])
    if not entries:
        raise ValueError('No construction registry entries')
    mapping = json.loads((Path(paths.bundle())/'recipes'/'website-calibration.json').read_text(encoding='utf8'))['constructionMapping']
    return {'gameBuild': catalog.install.game_build, 'registries': list(REGISTRIES),
            'unmapped': [r for r in entries if r.split('}', 1)[-1] not in mapping],
            'entries': [{'resource': resource, 'registries': registries, 'role': mapping.get(resource.split('}', 1)[-1])} for resource, registries in sorted(entries.items())],
            'note': 'Membership export. Website role merging and schematic artwork are curated recipes, not measured footprints.'}


def recipes(output):
    source = Path(paths.bundle())/'recipes'/'website-calibration.json'
    doc = json.loads(source.read_text(encoding='utf8'))
    folder = Path(output); folder.mkdir(parents=True, exist_ok=True)
    write_json(folder/'website-calibration.json', doc)
    from . import reticles
    sketches = folder/'legacy-sights'; sketches.mkdir(exist_ok=True)
    for name, definition in doc['sightDefinitions'].items():
        (sketches/(name+'.svg')).write_text(reticles.svg(name, definition), encoding='utf8')
    (folder/'legacy-reticles.js').write_bytes((source.parent/'legacy-reticles.js').read_bytes())
    for map_id, caves in doc['caves'].items():
        write_json(folder/'manual'/(map_id+'-caves.json'), caves)
    for map_id, colours in doc['treeColours'].items():
        write_json(folder/'manual'/(map_id+'-tree-colours.json'), colours)
    write_json(folder/'construction-roles.json', doc['constructionRoles'])
    write_json(folder/'legacy-sight-definitions.json', doc['sightDefinitions'])
    write_json(folder/'sound-calibration.json', doc['sound'])
    write_json(folder/'blast-calibration-snapshot.json', doc['blast'])
    (folder/'README.txt').write_text('Curated recipes reviewed 2026-10-05. They preserve the known website values, not fresh measurements.\nUse the mortar, blast, barrel, construction and audible producers to refresh their measurable inputs.\nLegacy SVGs use a 1024-square viewport, 128 display pixels per degree; bore/display origin 512,512.\nThey reproduce gunReticle geometry and do not change solver code or register new weapons in arma-map.\n', encoding='utf8')
    return str(Path(output).resolve())
