"""Installed-addon prefab discovery and isolated custom projectile flight measurements."""
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct

from . import addons, events, pak
from .export import Exporter
from .workbench import Runner, read_status

RESOURCE = re.compile(r'\{([0-9a-fA-F]{16})\}(.+)')
REFS = re.compile(r'"(\{[0-9a-fA-F]{16}\}[^"\r\n]+\.(?:et|conf))"', re.I)
PARENT = re.compile(r'^\s*\w+\s*:\s*"([^"\r\n]+\.(?:et|conf))"', re.I)
FIELDS = ('InitSpeed', 'BulletInitSpeedCoef', 'Mass', 'AirDrag', 'ForwardAirFriction',
          'SideAirFriction', 'TimeToLive', 'ThrustForce', 'ThrustTime', 'ThrustInitTime',
          'DistanceEnableGravitation', 'AlignTorque')
ELEVATIONS = (-12, -8, -5, -2, 0, 2, 4, 7, 10, 15, 20)
WINDS = ((0, 0), (10, 90), (5, 90), (10, 0), (10, 180))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf8')


def archive_entries(path):
    """Read only the FILE directory chunk, not multi-GB archive payloads."""
    with open(path, 'rb') as f:
        head = f.read(12)
        if head[:4] != b'FORM' or head[8:] != b'PAC1':
            return
        while True:
            header = f.read(8)
            if len(header) != 8:
                return
            size = struct.unpack('>I', header[4:])[0]
            if header[:4] == b'FILE':
                data = f.read(size)
                if len(data) != size:
                    raise ValueError(f'Truncated archive directory: {path}')
                yield from pak._tree(data, 0, len(data), '')
                return
            f.seek(size, 1)


def asset_kind(path):
    low = path.replace('\\', '/').lower()
    if not low.startswith(('prefabs/', 'configs/')):
        return 'other'
    if low.startswith(('prefabs/weapons/core/ammo_', 'prefabs/ammo/', 'prefabs/ammunition/', 'prefabs/weapons/ammo/', 'configs/weapons/ammo/')):
        return 'ammunition'
    if low.startswith('prefabs/weapons/') and ('/optics/' in low or '/scopes/' in low):
        return 'optic'
    if low.startswith('prefabs/vehicles/'):
        return 'vehicle'
    if low.startswith('prefabs/weapons/') and '/attachments/' not in low and '/magazines/' not in low and low.endswith('.et'):
        return 'weapon'
    return 'other'


def matches_asset(record, category):
    kind, low = record['kind'], record['path'].lower()
    if category == 'all': return True
    if category is None: return kind in ('weapon', 'ammunition', 'vehicle')
    if category == 'mortars':
        return kind in ('weapon', 'ammunition') and ('mortar' in low or re.search(r'shell_(?:81|82|60|120)mm', low) is not None)
    if category == 'bullets':
        return kind == 'ammunition' and ('/bullets/' in low or 'bullet_' in low or re.search(r'/ammo_[0-9]+x[0-9]+', low) is not None)
    if category == 'rockets':
        return kind == 'ammunition' and ('rocket' in low or '/missiles/' in low)
    return kind == category


class Catalog:
    def __init__(self, install, selected=None):
        self.install = install
        self.addons = list(selected) if selected is not None else addons.installed(install)
        self.by_guid = {a.guid: a for a in self.addons if a.guid}
        self.records = []
        self.by_ref = {}
        self.by_path = {}
        self._text = {}

    def scan(self):
        for a in self.addons:
            events.emit('log', level='info', message=f'Indexing {a.title}')
            guid_paths = {}
            if os.path.isfile(a.rdb):
                data = Path(a.rdb).read_bytes()
                for m in re.finditer(rb'([A-Za-z0-9_\-./ ]+\.(?:et|conf))\x00', data):
                    guid = data[m.end()+6:m.end()+14]
                    if len(guid) == 8 and any(guid):
                        guid_paths[m.group(1).decode('ascii')] = guid[::-1].hex().upper()
            sources = {}
            for archive in sorted(Path(a.folder).rglob('*.pak')):
                # Workshop downloads may hold an incomplete/locked temp/data.pak.
                if any(part.lower() == 'temp' for part in archive.relative_to(a.folder).parts):
                    continue
                for path, off, stored, size, comp in archive_entries(archive):
                    if path.lower().endswith(('.et', '.conf')):
                        sources[path] = ('pak', str(archive), off, stored, size, comp)
            for loose in sorted(p for p in Path(a.folder).rglob('*') if p.suffix.lower() in ('.et', '.conf')):
                sources[loose.relative_to(a.folder).as_posix()] = ('file', str(loose))
            for path in sorted(set(sources) | set(guid_paths)):
                ref = '{%s}%s' % (guid_paths[path], path) if path in guid_paths else path
                low = path.lower()
                kind = asset_kind(path)
                record = {'resource': ref, 'path': path, 'addon': a.title, 'addonGuid': a.guid,
                          'source': a.source, 'kind': kind, 'storage': sources.get(path)}
                self.records.append(record)
                self.by_ref.setdefault(ref.lower(), []).append(record)
                self.by_path.setdefault(path.lower(), []).append(record)
        return self.records

    def resolve(self, ref, owner=None, context=None):
        ref = ref.replace('\\', '/')
        hits = self.by_ref.get(ref.lower(), [])
        if not hits:
            hits = self.by_path.get(ref.split('}', 1)[-1].lower(), [])
            # Never substitute another GUID that happens to use the same path.
            if RESOURCE.fullmatch(ref):
                hits = [h for h in hits if h['resource'].lower() == ref.lower()]
        if owner:
            hits = [h for h in hits if h['addonGuid'] == owner]
        elif context:
            loaded = set(addons.dependency_guids(context, self.by_guid))
            hits = [h for h in hits if h['source'] == 'game' or h['addonGuid'] in loaded]
            # Only selected dependencies can override game resources. Unrelated installed mods must not leak in.
            overrides = [h for h in hits if h['source'] != 'game']
            if overrides:
                hits = overrides
        if len(hits) != 1:
            raise ValueError(f'{ref}: {len(hits)} matches; select its owning addon/resource explicitly')
        return hits[0]

    def text(self, record):
        key = (record['addonGuid'], record['resource'])
        if key not in self._text:
            storage = record['storage']
            if not storage:
                raise ValueError(f"Source unavailable for {record['resource']}; it may be compiled or missing")
            if storage[0] == 'file':
                data = Path(storage[1]).read_bytes()
            else:
                data = pak.read(*storage[1:])
            if b'\x00' in data:
                raise ValueError(f"Binary prefab cannot be inspected: {record['resource']}")
            self._text[key] = data.decode('utf8', 'replace')
        return self._text[key]

    def chain(self, record, context=None):
        context = context or record['addonGuid']
        chain, seen = [], set()
        while record:
            key = (record['addonGuid'], record['resource'])
            if key in seen:
                raise ValueError('Prefab inheritance cycle')
            seen.add(key)
            chain.append(record)
            text = self.text(record)
            parent = PARENT.match(text)
            record = self.resolve(parent[1], context=context) if parent else None
        return chain

    def details(self, record, context=None):
        chain = self.chain(record, context)
        values = {}
        for key in FIELDS:
            rx = re.compile(r'^\s*'+re.escape(key)+r'\s+([-+0-9.eE]+)\s*$', re.M)
            for item in chain:
                found = rx.findall(self.text(item))
                if found:
                    values[key] = {'values': [float(v) for v in found], 'resource': item['resource']}
                    break
        components = sorted({c for item in chain for c in re.findall(
            r'\b(\w*(?:Move|Muzzle|Weapon)Component)\b', self.text(item))})
        return {'resource': record['resource'], 'addon': record['addon'], 'addonGuid': record['addonGuid'],
                'kind': record['kind'], 'ancestors': [c['resource'] for c in chain],
                'fields': values, 'components': components,
                'projectile': any(c in components for c in ('ProjectileMoveComponent', 'ShellMoveComponent', 'MissileMoveComponent'))}

    def inspect(self, ref, owner=None):
        first = self.resolve(ref, owner)
        main = self.details(first)
        todo, seen, candidates, warnings = [(first, 0)], set(), [], []
        while todo and len(seen) < 500:
            item, depth = todo.pop(0)
            key = (item['addonGuid'], item['resource'])
            if key in seen:
                continue
            seen.add(key)
            try:
                details = self.details(item, first['addonGuid'])
                if details['projectile']:
                    candidates.append(details)
                if depth < 8:
                    refs = set()
                    for ancestor in self.chain(item, first['addonGuid']):
                        text = self.text(ancestor); parent = PARENT.match(text)
                        refs.update(r for r in REFS.findall(text) if not parent or r != parent[1])
                    for linked in sorted(refs):
                        try:
                            todo.append((self.resolve(linked, context=first['addonGuid']), depth+1))
                        except ValueError as e:
                            warnings.append(str(e))
            except ValueError as e:
                warnings.append(str(e))
        if todo:
            warnings.append('Reference discovery reached its depth/resource limit; select ammunition directly if missing.')
        return {'selected': main, 'projectiles': candidates, 'warnings': sorted(set(warnings)),
                'note': 'Prefab numeric values retain their source. Multiple muzzle/component values require explicit selection. Direct projectile flight does not measure vehicle sights, barrel dispersion or scripted/guided behavior.'}

    def launch_addons(self, records):
        guids = []
        for record in records:
            for guid in addons.dependency_guids(record['addonGuid'], self.by_guid):
                if guid not in self.by_guid:
                    raise ValueError(f'Missing installed dependency {guid}')
                if guid not in guids:
                    guids.append(guid)
        dirs = sorted({str(Path(self.by_guid[g].folder).parent) for g in guids})
        return guids, dirs


def make_plan(resource, name, coefficient, winds, duration, height):
    if not math.isfinite(coefficient) or not 0 < coefficient <= 10:
        raise ValueError('Launch speed coefficient must be greater than 0 and at most 10')
    if not math.isfinite(duration) or not 3 <= duration <= 30:
        raise ValueError('Recording duration must be 3 to 30 seconds')
    if not math.isfinite(height) or not 500 <= height <= 20000:
        raise ValueError('Launch height must be 500 to 20000 metres')
    if any(c in resource for c in ',\r\n'):
        raise ValueError('Projectile resource contains a CSV delimiter')
    return [{'id': f'T{i:04d}', 'rocket': name, 'prefab': resource, 'coef': coefficient,
             'x': 2048, 'z': 2048, 'y': height, 'elev': elev, 'wspeed': ws, 'wfrom': wf}
            for i, (ws, wf, elev, rep) in enumerate((ws, wf, el, rep)
                for ws, wf in winds for el in ELEVATIONS for rep in range(2 if ws == 0 else 1))]


def capture(catalog, resource, owner, weapon, weapon_owner, name, output, duration=10,
            coefficient=1, wind=True, world='EmptyEden', height=5000):
    import rockettest
    import rocketfit
    projectile = catalog.resolve(resource, owner)
    info = catalog.details(projectile)
    if not info['projectile']:
        raise ValueError('Select a projectile prefab with a supported movement component, not a weapon or vehicle')
    selected = [projectile]
    if weapon:
        selected.append(catalog.resolve(weapon, weapon_owner))
    guids, dirs = catalog.launch_addons(selected)
    resolved_world, world_guids, world_dirs = Exporter(catalog.install).resolve(world)
    guids = list(dict.fromkeys(guids+world_guids))
    dirs = sorted(set(dirs+world_dirs))
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', name):
        raise ValueError('Dataset name: 1–64 letters, digits, underscores or hyphens')
    winds = WINDS if wind else WINDS[:1]
    rows = make_plan(resource, name, coefficient, winds, duration, height)
    fingerprints = {str(p): [p.stat().st_size, p.stat().st_mtime_ns]
                    for g in guids for p in Path(catalog.by_guid[g].folder).rglob('*')
                    if p.is_file() and p.suffix.lower() in ('.et', '.conf', '.pak', '.rdb', '.gproj')}
    metadata = {'projectile': info, 'weapon': weapon, 'weaponAddonGuid': weapon_owner,
                'coefficient': coefficient, 'duration': duration, 'height': height, 'winds': winds,
                'world': resolved_world, 'gameBuild': catalog.install.game_build,
                'toolsBuild': catalog.install.tools_build, 'addonGuids': guids,
                'addonFiles': fingerprints, 'plan': rows}
    signature = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()[:16]
    output = Path(output) / name / signature
    output.mkdir(parents=True, exist_ok=True)
    rel = f'rmt/custom-ballistics/{name}/{signature}'
    raw = Path(catalog.install.game_profile) / rel
    metadata.update({'raw': str(raw), 'measurement': 'Direct projectile launch; weapon coefficient explicitly chosen. Not a real gun/vehicle firing test.'})
    write_json(output / 'manifest.json', metadata)
    runner = Runner(catalog.install, addon_dirs=dirs, extra_guids=guids)
    for index, (ws, wf) in enumerate(winds):
        folder = raw / f'w{index}' / 'firetest'
        status_path = folder.parent / 'firetest.status.json'
        block = [r for r in rows if (r['wspeed'], r['wfrom']) == (ws, wf)]
        old = read_status(str(status_path))
        if not old or old.get('result') != 'done':
            folder.mkdir(parents=True, exist_ok=True)
            with (folder / 'plan.csv').open('w', newline='', encoding='utf8') as f:
                writer = csv.writer(f)
                writer.writerow('id,prefab,coef,x,z,az,elev,wspeed,wdir,count,tx,tz,y'.split(','))
                for r in block:
                    writer.writerow([r['id'], resource, coefficient, r['x'], r['z'], 0, r['elev'], ws,
                                     (wf+180)%360 if ws else 0, 1, r['x'], r['z']+500, height])
            write_json(folder / 'plan.json', block)
            code, _, status = runner.run_game('firetest', f'{rel}/w{index}', resolved_world,
                flag='-rmtFire', args=('-rmtFireGap=0.3', '-rmtFireTraceDt=0.02', f'-rmtFireMaxT={duration}'),
                stall=240, limit=1800)
            if code or not status or status.get('result') != 'done':
                raise ValueError(f'Wind {index} did not complete; rerun to resume')
        if not (folder / 'traj.csv').is_file():
            status_path.unlink(missing_ok=True)
            raise ValueError(f'Wind {index}: status exists but trajectories are missing')
        flown = rockettest.flights_in(str(folder))
        ids = {p['id'] for p, frames in flown if len(frames) > 2}
        expected = {r['id'] for r in block}
        if ids != expected:
            status_path.unlink(missing_ok=True)
            raise ValueError(f'Wind {index}: {len(expected-ids)} shots have no complete trajectory; inspect engine log')
        events.progress('lab', index+1, len(winds), 'winds')
    flights = rockettest.flights(str(raw))
    if not any(p['wspeed'] == 0 and frames[-1][0] >= 2 for p, frames in flights):
        raise ValueError('Flights ended before two seconds; raw CSVs were saved, but these short-lived projectiles cannot use the current table fitter')
    # No fabricated zero wind response when the user recorded calm only.
    tables = rocketfit.tables(flights, ELEVATIONS, dt=0.1)
    if not wind:
        for table in tables.values():
            for key in ('head', 'tail', 'cross'):
                table.pop(key, None)
    result = {'about': 'Custom projectile flight measured in Arma Reforger', 'measurement': metadata['measurement'],
              'windMeasured': wind, 'manifest': 'manifest.json', 'rounds': tables}
    write_json(output / 'ballistics.json', result)
    events.emit('result', customBallistics=str(output), raw=str(raw))
    print(f'Saved {output / "ballistics.json"}; raw trajectories: {raw}')
    return str(output)
