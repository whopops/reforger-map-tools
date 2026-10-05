"""Selected Labs targets, dependency loading and isolated results. No Qt."""
import hashlib
import json
import math
from pathlib import Path
import re
from . import addons, paths
from .ballistics import Catalog, archive_entries, write_json
from .workbench import Runner

LIVE_TOOLS = ('firetest', 'blasttest', 'rockettest', 'bullettest', 'launchertest')
_ACTIVE = None
_ACTIVE_INSTALL = None


def legacy_targets(tool):
    if tool == 'selftest':
        return [{'id': p.stem, 'name': p.stem, 'addon': 'Repository tests', 'addonGuid': 'tests', 'kind': 'test module'}
                for p in sorted(Path(paths.bundle()).glob('test_*.py'))]
    if tool == 'firetest':
        import firetest as m
        return [{'id': 'baseline:'+w+'|'+s, 'name': w+' / '+s, 'addon': 'Website baseline', 'addonGuid': 'baseline',
                 'kind': 'mortar', 'baseline': [w, s]} for w, s in m.SHELLS]
    if tool == 'blasttest':
        import blasttest as m
        names = m.SHELLS
    elif tool == 'bullettest':
        import bullettest as m
        names = m.BULLETS
    elif tool == 'rockettest':
        import rockettest as m
        names = m.ROCKETS
    elif tool == 'launchertest':
        import launchertest as m
        names = m.LAUNCHERS
    else:
        return []
    return [{'id': 'baseline:'+n, 'name': n, 'addon': 'Website baseline', 'addonGuid': 'baseline',
             'kind': 'baseline', 'baseline': n} for n in names]


def accepts(record, tool):
    p, k = record['path'].lower(), record['kind']
    if not p.endswith('.et'): return False
    if tool == 'firetest': return k in ('weapon', 'ammunition') and ('mortar' in p or re.search(r'shell_(81|82|60|120)mm', p)) is not None
    if tool == 'blasttest': return k == 'ammunition'
    if tool == 'bullettest': return k in ('weapon', 'vehicle', 'ammunition') and 'rocket' not in p and 'mortar' not in p
    if tool == 'rockettest': return k == 'ammunition' and ('rocket' in p or 'missile' in p)
    if tool == 'launchertest': return k == 'weapon' and '/launchers/' in p
    return False


def catalog(install):
    c = Catalog(install); c.scan()
    report = {tool: legacy_targets(tool)+[
        {'id': r['addonGuid']+'|'+r['resource'], 'name': Path(r['path']).stem, 'addon': r['addon'],
         'addonGuid': r['addonGuid'], 'kind': r['kind'], 'resource': r['resource']}
        for r in c.records if r['addonGuid'] and accepts(r, tool)] for tool in LIVE_TOOLS}
    report['conflict'] = [dict(w, id=w['addonGuid']+'|'+w['resource']) for w in addons.list_worlds(install)
                          if w['addonGuid'] and (w['worldKind'] == 'terrain' or (w['worldKind'] == 'scenario' and ('cti' in Path(w['resource']).stem.lower() or 'conflict' in Path(w['resource']).stem.lower())))]
    report['pak'] = [{'id': a.guid, 'name': a.title, 'addon': a.title, 'addonGuid': a.guid, 'kind': 'archive'}
                     for a in c.addons if a.guid]
    sounds = []
    for a in c.addons:
        if not a.guid: continue
        for arc in sorted(Path(a.folder).rglob('*.pak')):
            if any(p.lower() == 'temp' for p in arc.relative_to(a.folder).parts): continue
            try:
                for path, *_ in archive_entries(arc):
                    if path.lower().endswith('.wav'):
                        sounds.append({'id': a.guid+'|'+path, 'name': Path(path).stem, 'resource': path,
                                       'addon': a.title, 'addonGuid': a.guid, 'kind': 'sound'})
            except (OSError, ValueError): continue
    report['audible'] = sounds
    report['selftest'] = [{'id': p.stem, 'name': p.stem, 'addon': 'Repository tests', 'addonGuid': 'tests', 'kind': 'test module'}
                          for p in sorted(Path(paths.bundle()).glob('test_*.py'))]
    return report


def number(fields, name, required=True):
    vals = fields.get(name, {}).get('values', [])
    if len(vals) == 1 and math.isfinite(vals[0]): return vals[0]
    if required: raise ValueError(f'{name} must have one finite inherited value; inspect this prefab first')
    return None


def rings(c, record, context):
    from .sights import parse, merge, walk
    tree = None
    for parent in reversed(c.chain(record, context)):
        node = parse(c.text(parent), parent['resource']); tree = merge(tree, node) if tree else node
    for node in walk(tree):
        if node['header'] == ['m_aChargeRingConfig']:
            vals = [t for k, v in node['fields'].items() for t in [k]+v['value']]
            try:
                vals = list(map(float, vals)); out = {int(vals[i]): vals[i+1] for i in range(0, len(vals), 3)}
                if out and all(math.isfinite(v) and v > 0 for v in out.values()): return out
            except (ValueError, IndexError): pass
    raise ValueError('No readable charge-ring configuration. Select a supported shell; no default rings will be invented.')


def prepare(c, request):
    request = {k: request[k] for k in ('tool', 'targets', 'coefficient', 'dataset', 'soldier', 'soundLevelLUFS', 'launchAngleDegrees', 'projectiles', 'mortarWeapon') if k in request}
    tool = request['tool']; ids = request.get('targets', [])
    if tool not in LIVE_TOOLS or not ids: raise ValueError('Choose at least one test target')
    if len(ids) != len(set(ids)): raise ValueError('Duplicate test target')
    baseline = {t['id']: t for t in legacy_targets(tool)}
    items, sources = [], []
    override = request.get('coefficient')
    if override is not None and (not math.isfinite(override) or not 0 < override <= 10): raise ValueError('Invalid launch coefficient')
    for target in ids:
        known = baseline.get(target); weapon = None; stock = None
        if known:
            stock = known['baseline']
            if tool == 'firetest':
                import firetest
                w, s = stock; root = c.resolve(firetest.MORTARS[w], owner=addons.GAME_GUID)
                prefab = firetest.SHELLS[(w, s)][0]; ammo = c.resolve(prefab, owner=addons.GAME_GUID)
                candidates = [{'resource': ammo['resource'], 'addonGuid': ammo['addonGuid'], 'fields': c.details(ammo)['fields']}]
                weapon = root['resource']; name = s
            elif tool == 'blasttest':
                import blasttest
                root = c.resolve(blasttest.SHELLS[stock], owner=addons.GAME_GUID); name = stock
                candidates = [{'resource': root['resource'], 'addonGuid': root['addonGuid'], 'fields': c.details(root)['fields']}]
            elif tool in ('bullettest', 'rockettest'):
                if tool == 'bullettest':
                    import bullettest
                    prefab, coef = bullettest.BULLETS[stock]
                else:
                    import rockettest
                    prefab, coef = rockettest.ROCKETS[stock], 1
                root = c.resolve(prefab, owner=addons.GAME_GUID); name = stock
                candidates = [{'resource': root['resource'], 'addonGuid': root['addonGuid'], 'fields': c.details(root)['fields']}]
            else:
                import launchertest, rockettest
                soldier, launcher, rocket, sight = launchertest.LAUNCHERS[stock]
                root = c.resolve(soldier, owner=addons.GAME_GUID); name = stock
                ammo = c.resolve(rockettest.ROCKETS[rocket], owner=addons.GAME_GUID)
                candidates = [{'resource': ammo['resource'], 'addonGuid': ammo['addonGuid'], 'fields': c.details(ammo)['fields']}]
        else:
            owner, ref = target.split('|', 1); root = c.resolve(ref, owner=owner)
            if not accepts(root, tool): raise ValueError('Selected resource does not belong to this test category')
            inspection = c.inspect(root['resource'], root['addonGuid'])
            candidates = [p for p in inspection['projectiles'] if p['resource'].lower().endswith('.et')]
            if inspection['selected']['projectile']:
                candidates = [inspection['selected']]
            elif tool == 'launchertest':
                candidates = [p for p in candidates if not any(fragment in p['resource'].lower() for fragment in ('spall', 'penetrator', 'effectmodule', '/warheads/'))]
            if not candidates: raise ValueError(f'No projectile found for {root["resource"]}; select ammunition directly')
            name = Path(root['path']).stem+' ['+root['addonGuid']+']'
            if root['kind'] == 'weapon': weapon = root['resource']
            if tool == 'firetest' and root['kind'] == 'ammunition' and request.get('mortarWeapon'):
                owner, ref = request['mortarWeapon'].split('|', 1)
                selected_weapon = c.resolve(ref, owner=owner)
                compatible = c.inspect(selected_weapon['resource'], selected_weapon['addonGuid'])['projectiles']
                if not any(p['resource'] == root['resource'] for p in compatible):
                    raise ValueError('Selected shell is not referenced by the chosen mortar; inspect its ammo compatibility')
                weapon = selected_weapon['resource']; sources.append(selected_weapon)
            values = inspection['selected']['fields'].get('BulletInitSpeedCoef', {}).get('values', [])
            if len(values) > 1 and override is None:
                raise ValueError('Multiple muzzle coefficients: select ammunition and specify the intended coefficient')
            coef = values[0] if len(values) == 1 else 1
        sources.append(root)
        for i, candidate in enumerate(candidates):
            ammo = c.resolve(candidate['resource'], owner=candidate['addonGuid']); sources.append(ammo)
            fields = candidate['fields']; label = name if len(candidates) == 1 else name+' / '+Path(ammo['path']).stem
            if any(ch in label+ammo['resource'] for ch in ',\r\n'): raise ValueError('CSV-unsafe target/resource name')
            item = {'name': label, 'prefab': ammo['resource'], 'addonGuid': ammo['addonGuid'], 'weapon': weapon,
                    'weaponAddonGuid': root['addonGuid'], 'baseline': stock, 'coefficient': override if override is not None else (coef if tool in ('bullettest', 'rockettest') or not known else 1),
                    'fields': fields}
            if tool == 'firetest':
                if not weapon: raise ValueError('Mortar tests need the mortar weapon selected, not a shell alone')
                from .webdata import effective
                from .sights import walk
                move = next((n for n in walk(effective(c, ammo, root['addonGuid'])) if 'ShellMoveComponent' in n['header']), None)
                if move is None: raise ValueError('Mortar shell has no readable ShellMoveComponent')
                def physics(key):
                    values = move['fields'].get(key, {}).get('value', [])
                    if len(values) != 1: raise ValueError('Missing mortar '+key)
                    value = float(values[0])
                    if not math.isfinite(value): raise ValueError('Nonfinite mortar '+key)
                    return value
                v0, mass, drag = physics('InitSpeed'), physics('Mass'), physics('AirDrag')
                if mass <= 0 or v0 <= 0 or drag < 0: raise ValueError('Invalid mortar physics')
                item.update(v0=v0, k=drag/mass, rings=rings(c, ammo, root['addonGuid']), mortarId=stock[0] if known else Path(weapon).stem+' ['+root['addonGuid']+']')
            if tool == 'launchertest':
                import launchertest
                item['soldier'] = c.resolve(request.get('soldier') or (launchertest.LAUNCHERS[stock][0] if known else launchertest.CHAR+'OPFOR/USSR_Army/Character_USSR_AT.et'), context=root['addonGuid'])['resource']
                soldier_record = c.resolve(item['soldier'], context=root['addonGuid']); sources.append(soldier_record)
            items.append(item)
    for item in items:
        item['selectionId'] = item['name']+'|'+item['addonGuid']+'|'+item['prefab']
    if 'projectiles' in request:
        allowed = set(request['projectiles'])
        if not allowed or not allowed <= {i['selectionId'] for i in items}:
            raise ValueError('Selected projectile list is empty or stale; inspect the targets again')
        items = [i for i in items if i['selectionId'] in allowed]
    if len({i['name'] for i in items}) != len(items): raise ValueError('Duplicate resolved projectile names')
    guids, dirs = c.launch_addons(sources)
    inherited = [ancestor for record in sources for ancestor in c.chain(record, record['addonGuid'])]
    fingerprints = {r['addonGuid']+'|'+r['resource']: hashlib.sha256(c.text(r).encode()).hexdigest() for r in inherited}
    result = dict(request, items=items, guids=guids, addonDirs=dirs, sourceHashes=fingerprints, gameBuild=c.install.game_build)
    if request.get('dataset'):
        result['datasetHash'] = hashlib.sha256(Path(request['dataset']).read_bytes()).hexdigest()
    if not math.isfinite(request.get('launchAngleDegrees', 0)):
        raise ValueError('Invalid launcher spawn angle')
    result['signature'] = hashlib.sha256(json.dumps(result, sort_keys=True, allow_nan=False).encode()).hexdigest()[:16]
    return result


def activate(selection, install=None):
    global _ACTIVE, _ACTIVE_INSTALL
    _ACTIVE = selection
    _ACTIVE_INSTALL = install


def runner(install):
    if _ACTIVE is None: return Runner(install)
    return SelectedRunner(_ACTIVE_INSTALL or install, addon_dirs=_ACTIVE['addonDirs'], extra_guids=_ACTIVE['guids'])


class SelectedRunner(Runner):
    def run_game(self, *args, **kwargs):
        result = super().run_game(*args, **kwargs)
        code, lines, status = result
        if (code or not status or status.get('result') != 'done'
                or status.get('made', 0) <= 0 or status.get('skipped', 0) > 0):
            raise RuntimeError('Selected Labs test did not finish successfully; inspect engine errors and result status')
        return result
