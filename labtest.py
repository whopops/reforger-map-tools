"""Run Labs tests against explicit baseline or installed-mod selections."""
import argparse
import csv
import json
import math
import os
import re
from pathlib import Path
import sys

from rmtlib import events, paths, labselection as select
from rmtlib.ballistics import Catalog, write_json, archive_entries
from rmtlib.steam import Install


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('catalog', 'prepare', 'plan', 'run', 'score', 'group', 'gun', 'barrel', 'check',
                     'check-score', 'check-twins', 'check-twins-score', 'measure', 'table', 'reach', 'loud', 'list', 'cat',
                     'all', 'export', 'bake', 'preview'))
    p.add_argument('folder', nargs='?')
    p.add_argument('--tool', choices=(*select.LIVE_TOOLS, 'conflict', 'audible', 'pak', 'selftest'))
    p.add_argument('--selection', help='JSON with tool, targets and optional measured dataset / coefficient')
    p.add_argument('--output', required=True)
    p.add_argument('--workbench')
    p.add_argument('--site')
    p.add_argument('--distance', type=float, default=1200)
    p.add_argument('--ring', type=int, default=3)
    p.add_argument('--rounds', type=int, default=10)
    p.add_argument('--gap', type=float, default=15)
    p.add_argument('--per-ring', type=int, default=40)
    p.add_argument('--trials', type=int)
    p.add_argument('--out', default='')
    p.add_argument('--resume')
    p.add_argument('--pattern', default='.*')
    p.add_argument('--path')
    p.add_argument('--to')
    p.add_argument('--map-id', help='Website map id for an explicitly selected Conflict scenario')
    return p


def validate_recipe(request, tool):
    if request.get('tool') != tool: raise ValueError('Selection belongs to another Labs category')
    if not request.get('targets'): raise ValueError('Select at least one target. Empty selection never means all assets.')
    if len(set(request['targets'])) != len(request['targets']): raise ValueError('Duplicate selected targets')


def assert_run(folder, signature):
    path = Path(folder).resolve()
    for parent in (path, *list(path.parents)[:3]):
        file = parent/'selection.json'
        if file.is_file():
            if json.loads(file.read_text(encoding='utf8')).get('signature') != signature:
                raise ValueError('This run belongs to a different target selection; load its selection.json first')
            return
    raise ValueError('Selected-mode reporting/resume requires a saved selection.json with this run')



def require_flights(base, expected_blocks=None):
    """Do not fit partial wind suites or silently drop a selected shot."""
    import rockettest
    base = Path(base)
    blocks = sorted(base.glob('w[0-9]*'), key=lambda p: int(p.name[1:]))
    if not blocks or (expected_blocks is not None and len(blocks) != expected_blocks):
        raise ValueError('Selected flight suite is incomplete: finish every planned wind block before scoring')
    for index, block in enumerate(blocks):
        if block.name != 'w'+str(index): raise ValueError('Missing selected wind block')
        status = json.loads((block/'firetest.status.json').read_text(encoding='utf8'))
        plan = json.loads((block/'firetest'/'plan.json').read_text(encoding='utf8'))
        if status.get('result') != 'done' or status.get('skipped', 0) or status.get('made', 0) != len(plan):
            raise ValueError('Selected wind block has missing or failed shots: '+block.name)
        expected = {p['id'] for p in plan}
        flights = rockettest.flights_in(str(block/'firetest'))
        if not expected or {p['id'] for p, frames in flights if len(frames) > 1} != expected:
            raise ValueError('Selected trajectory data does not cover every planned shot: '+block.name)


def recorded_selection(folder, request):
    path = Path(folder).resolve()
    for parent in (path, *list(path.parents)[:3]):
        file = parent/'selection.json'
        if not file.is_file(): continue
        saved = json.loads(file.read_text(encoding='utf8'))
        for key in ('tool', 'targets', 'coefficient', 'projectiles', 'mortarWeapon', 'dataset', 'launchAngleDegrees'):
            if request.get(key) != saved.get(key):
                raise ValueError('Run selection differs: load its selection.json before reporting or resuming')
        if not saved.get('signature') or not saved.get('items'): raise ValueError('Saved run has no recorded target physics')
        return saved
    raise ValueError('No saved selection.json found beside this run')

def mortar_tables(c, selected, output, module):
    from rmtlib.webdata import mortar_plan, bake_mortar
    from rmtlib.workbench import read_status
    plans = []; base = None
    for item in selected['items']:
        if item['baseline']:
            if base is None: base, _ = mortar_plan(c)
            w, s = item['baseline']
            pages = [dict(p) for p in base if p['weapon'] == w and p['shell'] == s]
        else:
            pages = [{'weapon': item['mortarId'], 'shell': item['name'], 'ring': int(r), 'coef': coef,
                      'prefab': item['prefab'], 'min': 50, 'max': 5000, 'step': 100, 'mils': 6400,
                      'dispersion': 0} for r, coef in item['rings'].items()]
        for page in pages:
            page['id'] = str(len(plans)); plans.append(page)
    if not plans: raise ValueError('No mortar table pages for selected shells')
    rel = module.OUT_REL+'/tables'; folder = Path(c.install.profile)/rel; folder.mkdir(parents=True, exist_ok=True)
    with (folder/'plan.csv').open('w', newline='', encoding='utf8') as stream:
        keys = ('id', 'prefab', 'coef', 'min', 'max', 'step', 'mils'); writer = csv.writer(stream)
        writer.writerow(keys); writer.writerows([[p[k] for k in keys] for p in plans])
    write_json(output/'mortar-plan.json', plans)
    table_file = output/'mortar-tables.json'
    if not table_file.is_file():
        code, _, status = select.runner(c.install).run(['mortar_tables'], rel, module.WORLD,
                                           args=['-rmtMortarPlan='+rel+'/plan.csv'], stall=300, limit=1800)
        status = read_status(folder/'mortar_tables.status.json')
        if code or not status or status.get('result') != 'done': raise RuntimeError('Selected mortar tables did not finish')
        write_json(table_file, bake_mortar(plans, folder/'mortar-tables.csv'))
    module.TABLES = json.loads(table_file.read_text(encoding='utf8'))['weapons']


def selected_live(args, request, c):
    import firetest, blasttest, rockettest, bullettest, launchertest, rocketfit
    module = {'firetest': firetest, 'blasttest': blasttest, 'rockettest': rockettest,
              'bullettest': bullettest, 'launchertest': launchertest}[args.tool]
    if args.site:
        firetest.SITE = args.site
    else:
        from rmtlib.fieldmap import default_field_map
        site = default_field_map(paths.REPO)
        if site: firetest.SITE = str(Path(site)/'static'/'data')
    if args.tool == 'launchertest' and not request.get('dataset'):
        baseline_data = Path(firetest.SITE)/'rockets.json'
        if baseline_data.is_file() and all(t.startswith('baseline:') for t in request['targets']):
            request = dict(request, dataset=str(baseline_data.resolve()))
    selected = recorded_selection(args.folder or args.resume, request) if (args.folder or args.resume) else select.prepare(c, request)
    if args.resume:
        current = select.prepare(c, request)
        if current['signature'] != selected['signature']: raise ValueError('Sources changed since this run; start a fresh selected test instead of resuming')
    select.activate(selected, c.install)
    result = Path(args.output)/args.tool/selected['signature']; result.mkdir(parents=True, exist_ok=True)
    rel = 'rmt/labs/'+args.tool+'/'+selected['signature']
    module.OUT_REL = rel
    if args.site: firetest.SITE = args.site
    # Only this selection's files feed its score/check. Imported measured data must be explicitly selected.
    module.REPO = str(result); (result/'out').mkdir(exist_ok=True)
    data = request.get('dataset')
    if data and not (args.folder or args.resume):
        doc = json.loads(Path(data).read_text(encoding='utf8'))
        write_json(result/'out'/('bullets.json' if args.tool == 'bullettest' else 'rockets.json'), doc)
    write_json(result/'selection.json', selected)
    profile = Path(c.install.game_profile)/rel; profile.mkdir(parents=True, exist_ok=True)
    write_json(profile/'selection.json', selected)
    if args.folder: assert_run(args.folder, selected['signature'])
    if args.resume: assert_run(args.resume, selected['signature'])
    if args.command == 'prepare':
        print(f'{len(selected["items"])} resolved targets; addons {selected["guids"]}')
        events.emit('result', labPrepared=str(result/'selection.json')); return
    report = args.command in ('score', 'check-score', 'check-twins-score') or bool(args.folder)
    if args.tool == 'firetest':
        module.SHELLS = {}; module.MORTARS = {}; module.BARREL_SD = {}; module.STUDY = []
        for item in selected['items']:
            key = (item['mortarId'], item['name']); coefs = item['rings']; high = max(map(int, coefs))
            if set(map(int, coefs)) != set(range(high+1)): raise ValueError('Non-contiguous mortar ring configurations')
            module.SHELLS[key] = (item['prefab'], item['v0'], item['k'], [coefs.get(str(i), coefs.get(i)) for i in range(high+1)])
            module.MORTARS[key[0]] = item['weapon']; module.STUDY.append(key)
            module.BARREL_SD[key[0]] = (0, 0)  # unknown, not inherited vanilla dispersion
        module.STUDY = tuple(module.STUDY); module.GUN_REL = rel+'/gun-test'; module.BARREL_REL = rel+'/barrel'
        # Reports retain selected physics; native lookup is needed only for planning/firing.
        if not report: mortar_tables(c, selected, result, module)
        else:
            file = result/'mortar-tables.json'
            if file.is_file(): module.TABLES = json.loads(file.read_text(encoding='utf8'))['weapons']
        if args.command in ('plan', 'run'):
            rows = module.make_plan()
            if not rows: raise ValueError('No valid aims for the selected mortar physics')
            module.write_plan(rows)
            if args.command == 'run': module.run(rows); module.score(module.game_dir())
        elif args.command in ('group', 'gun'):
            key = next(iter(module.SHELLS))
            if len(module.SHELLS) != 1: raise ValueError('Group/gun tests require one mortar-shell pairing')
            if args.folder:
                (module.group_score if args.command == 'group' else module.gun_score)(args.folder)
            else:
                rows = module.group_plan(args.distance, args.ring, args.rounds, *key)
                if args.command == 'group': module.run(rows, args=(f'-rmtFireGap={args.gap}',)); module.group_score(module.game_dir())
                else: module.gun_score(module.gun_run(rows[0], args.rounds, args.gap))
        elif args.command == 'barrel':
            if args.folder: dirs = [args.folder]
            else:
                rows = module.barrel_plan(args.per_ring)
                if args.resume:
                    done = {r['id'] for r, _ in module.study_rows([args.resume])}; rows = [r for r in rows if r['id'] not in done]
                dirs = ([args.resume] if args.resume else [])+[module.barrel_run(rows, module.BARREL_REL)]
            module.barrel_score(dirs)
        else: module.score(args.folder or module.game_dir())
    elif args.tool == 'blasttest':
        module.SHELLS = {item['name']: item['prefab'] for item in selected['items']}
        shells = list(module.SHELLS)
        if args.command == 'plan': module.write_plan(module.make_plan(shells))
        elif args.command == 'run': module.run(shells, args.trials); module.score(module.game_dir())
        else: module.score(args.folder or module.game_dir())
    elif args.tool in ('rockettest', 'bullettest'):
        projectiles = {i['name']: (i['prefab'], i['coefficient']) for i in selected['items']}
        module.CHECK_REL = rel+'/check'; module.CHECK_TWIN_REL = rel+'/check-twins'
        if args.tool == 'bullettest': module.BULLETS = projectiles
        else: module.ROCKETS = projectiles
        dataset = result/'out'/('bullets.json' if args.tool == 'bullettest' else 'rockets.json')
        if args.command in ('plan', 'run'):
            rows = module.plan() if args.tool == 'bullettest' else module.make_plan()
            for i, block in enumerate(rockettest.blocks(rows)): rockettest.write_plan(block, i, rel)
            if args.command == 'run': rockettest.run(rows, rel, args=module.ARGS if args.tool == 'bullettest' else ('-rmtFireGap=1',))
        elif args.command == 'score':
            base = args.folder or rockettest.game_dir(rel=rel)
            require_flights(base, len(module.WINDS))
            flights = rockettest.flights(base)
            if not flights: raise ValueError('No complete selected flight runs to score')
            tables = rocketfit.tables(flights, rockettest.ELEVS, dt=module.DT) if args.tool == 'bullettest' else rocketfit.report(flights)
            if set(tables) != set(projectiles): raise ValueError('Scored flights do not cover exactly the selected targets')
            write_json(dataset, {'about': 'Selected Labs bullet flights', 'rounds': tables} if args.tool == 'bullettest' else rocketfit.site_json(tables))
        elif args.command == 'check':
            if not dataset.is_file(): raise ValueError('Score this selection first, or choose its measured dataset')
            rows = module.check_plan(); rockettest.run(rows, module.CHECK_REL, args=module.ARGS if args.tool == 'bullettest' else ('-rmtFireGap=1',))
            rockettest.check_score(rockettest.game_dir(rel=module.CHECK_REL))
        elif args.command == 'check-score':
            base = args.folder or rockettest.game_dir(rel=module.CHECK_REL)
            require_flights(base, module.CHECK_WINDS); rockettest.check_score(base)
        else:
            if args.command == 'check-twins':
                rockettest.run(rockettest.check_twin_rows(module.CHECK_REL), module.CHECK_TWIN_REL,
                               args=module.ARGS if args.tool == 'bullettest' else ('-rmtFireGap=1',))
            require_flights(rockettest.game_dir(rel=module.CHECK_REL), module.CHECK_WINDS)
            require_flights(args.folder or rockettest.game_dir(rel=module.CHECK_TWIN_REL), module.CHECK_WINDS)
            rockettest.check_twins_score(rockettest.game_dir(rel=module.CHECK_REL), args.folder or rockettest.game_dir(rel=module.CHECK_TWIN_REL),
                                         str(dataset), bullet=args.tool == 'bullettest')
    else:
        launcher_test(args, selected, result, module, c)
    events.emit('result', labResults=str(result.resolve()), labProfile=str(profile.resolve()))


def launcher_test(args, selected, result, module, c):
    import rocketfit, rockettest
    weapons = [i['weapon'] for i in selected['items'] if not i['baseline']]
    if len(weapons) != len(set(weapons)):
        raise ValueError('Inspect targets and choose one ammunition variant per launcher before running')
    file = result/'out'/'rockets.json'
    if not file.is_file():
        baseline = Path(paths.bundle())/'out'/'rockets.json'
        if all(i['baseline'] for i in selected['items']) and baseline.is_file():
            write_json(file, json.loads(baseline.read_text(encoding='utf8')))
        else: raise ValueError('Launcher tests need a measured rockets.json: choose the flight dataset, including the selected mod ammunition')
    J = json.loads(file.read_text(encoding='utf8'))
    module.LAUNCHERS = {i['baseline']: module.LAUNCHERS[i['baseline']] for i in selected['items'] if i['baseline']}
    for i in selected['items']:
        if i['baseline']: continue
        # Choose a rocket by persisted prefab mapping/name; never substitute a vanilla round.
        choices = [k for k in J.get('rockets', {}) if k == i['name'] or k == Path(i['prefab']).stem+' ['+i['addonGuid']+']']
        if len(choices) != 1: raise ValueError('Measured dataset has no unambiguous flight entry for '+i['prefab'])
        rocket = choices[0]; sight = i['name']
        from rmtlib.sights import sight_components
        weapon = c.resolve(i['weapon'], owner=i['weaponAddonGuid']); info = sight_components(c, weapon)
        ranges = next((s['ranges'] for s in info['sights'] if s['ranges']), [])
        if not ranges: raise ValueError('Launcher has no readable zeroing ranges; inspect/calibrate its sights first')
        J.setdefault('launchers', {})[sight] = {'spawn': selected.get('launchAngleDegrees', 0),
                     'sights': {'iron': {str(int(r['rangeMetres'])): r['angleDegrees'] for r in ranges}}, 'rockets': [rocket]}
        module.LAUNCHERS[i['name']] = (i['soldier'], sight, rocket, 'iron')
    write_json(file, J)
    if args.command == 'score': module.score(args.folder or module.game_dir()); return
    rows = module.make_plan()
    by_name = {i['baseline'] or i['name']: i for i in selected['items']}
    for row in rows:
        item = by_name[row['launcher']]; row['weaponPrefab'] = item['weapon'] or ''
    module.write_plan(rows)
    # Existing engine CSV already supports a launcher override in column 3.
    plan = Path(module.game_dir())/'plan.csv'
    with plan.open(newline='', encoding='utf8') as f: csvrows = list(csv.reader(f))
    csvrows[0].append('expectedProjectile')
    for row, model in zip(csvrows[1:], rows):
        row[2] = model['weaponPrefab']; row.append(by_name[model['launcher']]['prefab'])
    with plan.open('w', newline='', encoding='utf8') as f: csv.writer(f).writerows(csvrows)
    if args.command == 'run':
        code, _, status = select.runner(c.install).run_game('launchertest', module.OUT_REL, module.WORLD, flag='-rmtLauncher', stall=300, limit=5400)
        module.score(module.game_dir())


def non_live(args, request, install):
    from rmtlib import addons, pak
    selected = request['targets']
    if args.tool == 'selftest':
        import unittest
        known = {p.stem for p in Path(paths.bundle()).glob('test_*.py')}
        if not set(selected) <= known: raise ValueError('Unknown selected regression module')
        suite = unittest.defaultTestLoader.loadTestsFromNames(selected)
        if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful(): raise RuntimeError('Selected regression tests failed')
        return
    by_guid = {a.guid: a for a in addons.installed(install)}
    if args.tool == 'conflict':
        if args.map_id and (not re.fullmatch(r'[A-Za-z0-9_-]+', args.map_id) or len(selected) != 1):
            raise ValueError('An explicit website map id must be a simple id and have exactly one selected scenario')
        from rmtlib.export import Exporter, slug_of
        from rmtlib import bake_conflict, fieldmap
        ex = Exporter(install)
        for target in selected:
            guid, resource = target.split('|', 1)
            world, _, _ = ex.resolve(resource); stem = Path(world).stem
            scenario = world if ('cti' in stem.lower() or 'conflict' in stem.lower()) else ex.resolve('CTI_Campaign_'+stem)[0]
            if args.command != 'bake':
                _, bad = ex.export(scenario, ['conflict'])
                if bad: raise RuntimeError('Conflict export failed')
            raw = Path(install.profile)/'rmt'/slug_of(scenario)/install.game_build
            site = args.to or fieldmap.default_field_map(paths.REPO)
            map_id = args.map_id or (fieldmap.site_map_id(site, slug_of(world)) if site else None)
            site_dir = Path(site)/'static'/'data'/'maps'/map_id if site and map_id else None
            def existing(name):
                file = site_dir/name if site_dir else None
                return json.loads(file.read_text(encoding='utf8')) if file and file.is_file() else None
            doc = bake_conflict.bake(str(raw), stem, existing('places.json'), existing('roads.json'))
            output = Path(args.output)/'conflict'/slug_of(scenario)/'conflict.json'; write_json(output, doc)
            if args.command != 'preview':
                if not site or not (Path(site)/'server.py').is_file(): raise ValueError('Choose the website application folder containing server.py')
                if map_id and not (Path(site)/'static'/'data'/'maps'/map_id/'map.json').is_file(): raise ValueError('Selected website map id is not installed')
                if not map_id: raise ValueError('Install this map first, or use preview before installing Conflict data')
                dst = Path(site)/'static'/'data'/(map_id+'.json')
                if dst.is_file(): doc['caves'] = json.loads(dst.read_text(encoding='utf8')).get('caves', [])
                write_json(dst, doc)
        return
    if args.tool == 'audible':
        sound_test(args, request, install, by_guid); return
    import re
    pattern = re.compile(args.pattern, re.I); found = False
    for guid in selected:
        if guid not in by_guid: raise ValueError('Selected addon is no longer installed')
        addon = by_guid[guid]
        for arc in Path(addon.folder).rglob('*.pak'):
            if any(p.lower() == 'temp' for p in arc.relative_to(addon.folder).parts): continue
            for path, *entry in archive_entries(arc):
                if args.command == 'list' and pattern.search(path): print(addon.title, path, entry[2]); found = True
                elif args.command == 'cat' and path.lower() == (args.path or '').lower():
                    print(pak.read(str(arc), *entry).decode('utf8', errors='replace')); found = True
    if not found: raise ValueError('No file matched the selected addons and path/pattern')


def sound_test(args, request, install, by_guid):
    import hashlib
    signature = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()[:16]
    result = Path(args.output)/'audible'/signature; result.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(Path(paths.bundle())/'audible'))
    import pakx
    # The source selection stays addon-scoped. Identical paths in two packs retain separate keys.
    records = {}; noise = {}
    selected = set(request['targets'])
    from rmtlib import pak
    for guid, addon in by_guid.items():
        for arc in Path(addon.folder).rglob('*.pak'):
            if any(p.lower() == 'temp' for p in arc.relative_to(addon.folder).parts): continue
            for path, *entry in archive_entries(arc):
                key = guid+'|'+path
                if key in selected: records[key] = (str(arc), entry)
                elif addon.source == 'game' and re.search(r'Ambients2D/Samples/(Bed/Environment_Bed_(Meadow|Forest|Hills)_LP|Wind/Environment_Wind_(Meadow|Forest|Hills)_Mid_LP)\.wav', path): noise[key] = (str(arc), entry)
    if set(records) != selected: raise ValueError('Selected WAV source is unavailable; rescan installed addons')
    # Avoid importing loud's legacy hardcoded game index; supply exactly the indexed sources above.
    pakx.index = lambda: {}
    import loud
    loud.FILES = dict(records, **noise)
    if args.command == 'loud':
        for key in sorted(records): print(key, loud.stats(key))
    else:
        if args.command == 'measure':
            import audible as audio
            import numpy as np
            if not noise: raise ValueError('No baseline ambient-noise samples found')
            S, level = audio.shot_bands(list(records)); N = audio.noise_bands(list(noise))
            np.save(result/'S.npy', S); np.save(result/'N.npy', N)
            write_json(result/'samples.json', {'sampleLUFS': level, 'shots': sorted(records), 'noise': sorted(noise), 'selection': request})
        else:
            if not (result/'samples.json').is_file(): raise ValueError('Measure these selected samples before table/reach')
            old = os.getcwd()
            try:
                os.chdir(result)
                from audible2 import reach
                sample = json.loads((result/'samples.json').read_text(encoding='utf8'))
                level = request.get('soundLevelLUFS')
                if level is None or not math.isfinite(level): raise ValueError('Set a calibrated shot level at 2 metres (LUFS) for selected sound reach')
                doc = {n: int(round(reach(level, nl, sample_lufs=sample['sampleLUFS'])/5)*5) for n, nl in [('still', -55), ('breeze', -50), ('windy', -45), ('storm', -40)]}
                write_json(result/'audible.json', {'selection': request, 'referenceMetres': 2, 'referenceLUFS': level, 'reach': doc})
                print(doc)
            finally: os.chdir(old)
    write_json(result/'selection.json', request)
    events.emit('result', labResults=str(result.resolve()))


def main(argv=None):
    args = parser().parse_intermixed_args(argv)
    if args.command == 'catalog':
        report = select.catalog(Install(args.workbench)); file = Path(args.output)/'lab-catalog.json'; write_json(file, report)
        events.emit('result', labCatalog=str(file.resolve())); print('Installed Labs target catalog written'); return 0
    if not args.tool or not args.selection: raise ValueError('Choose a Labs tool and selection file')
    from rmtgui.labs import BY_KEY
    allowed = {c['name'] for c in BY_KEY[args.tool]['cmds']}
    if args.tool in select.LIVE_TOOLS: allowed.add('prepare')
    if args.command not in allowed: raise ValueError('Command is not supported for this Labs category')
    if args.out: raise ValueError('Use --output; selected runs always use an isolated signature folder')
    request = json.loads(Path(args.selection).read_text(encoding='utf8')); validate_recipe(request, args.tool)
    if args.tool == 'selftest': non_live(args, request, None)
    else:
        install = Install(args.workbench)
        if args.tool in select.LIVE_TOOLS: _live(args, request, install)
        else: non_live(args, request, install)
    return 0


def _live(args, request, install):
    c = Catalog(install); c.scan(); selected_live(args, request, c)

if __name__ == '__main__': raise SystemExit(main())
