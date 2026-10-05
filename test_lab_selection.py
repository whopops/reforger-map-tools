"""Selected test plans, source identity, engine loading and failure contracts."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from rmtlib import labselection
from rmtgui import labs
import labtest


class LabSelectionTests(unittest.TestCase):
    def fixture(self):
        from test_custom_ballistics import CustomBallisticsTests
        f = CustomBallisticsTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.catalog.install.game_build = 'test-build'
        f.addon('AAAAAAAAAAAAAAAA')
        ammo = f.record('AAAAAAAAAAAAAAAA', 'Prefabs/Weapons/Ammo/Ammo_Bullet_Custom.et',
                       'Entity {\n ShellMoveComponent {\n InitSpeed 700\n Mass 0.01\n AirDrag 0.001\n }\n}', '1111111111111111')
        return f, ammo

    def test_mod_selection_is_isolated_and_saved_recipe_round_trips(self):
        f, ammo = self.fixture()
        request = {'tool': 'bullettest', 'targets': [ammo['addonGuid']+'|'+ammo['resource']], 'coefficient': .93}
        result = labselection.prepare(f.catalog, request)
        self.assertEqual(result['guids'], ['AAAAAAAAAAAAAAAA'])
        self.assertEqual(result['items'][0]['prefab'], ammo['resource'])
        self.assertEqual(result['items'][0]['coefficient'], .93)
        self.assertEqual(result['signature'], labselection.prepare(f.catalog, json.loads(json.dumps(result)))['signature'])
        changed = copy.deepcopy(request); changed['coefficient'] = 1
        self.assertNotEqual(result['signature'], labselection.prepare(f.catalog, changed)['signature'])
        with self.assertRaises(ValueError): labselection.prepare(f.catalog, dict(request, targets=[]))
        with self.assertRaises(ValueError): labselection.prepare(f.catalog, dict(request, targets=request['targets']*2))

    def test_resolved_projectile_filter_cannot_silently_select_everything(self):
        f, ammo = self.fixture(); request = {'tool': 'bullettest', 'targets': [ammo['addonGuid']+'|'+ammo['resource']]}
        result = labselection.prepare(f.catalog, request); identifier = result['items'][0]['selectionId']
        self.assertEqual(len(labselection.prepare(f.catalog, dict(request, projectiles=[identifier]))['items']), 1)
        for ids in ([], ['stale-resource']):
            with self.assertRaises(ValueError): labselection.prepare(f.catalog, dict(request, projectiles=ids))

    def test_installed_ammo_enters_legacy_flight_plan_without_game_rdb_lookup(self):
        import rockettest
        ref = '{1111111111111111}Prefabs/Weapons/Ammo/Ammo_Bullet_Custom.et'
        with patch('rockettest.sea_spots', side_effect=lambda n: [(100, 200)]*n):
            rows = rockettest.make_plan({'custom': (ref, .93)}, elevs=(0, 4), winds=((0, 0),), repeats=2)
        self.assertEqual(len(rows), 4)
        self.assertEqual({r['prefab'] for r in rows}, {ref})
        self.assertEqual({r['rocket'] for r in rows}, {'custom'})
        self.assertEqual({r['coef'] for r in rows}, {.93})

    def test_selected_runner_loads_mods_and_rejects_lost_or_empty_tests(self):
        from rmtlib.workbench import Runner
        recipe = {'guids': ['AAAAAAAAAAAAAAAA'], 'addonDirs': ['mods']}
        labselection.activate(recipe); self.addCleanup(lambda: labselection.activate(None))
        with patch.object(Runner, '__init__', return_value=None) as init:
            runner = labselection.runner(SimpleNamespace())
        self.assertEqual(init.call_args.kwargs['extra_guids'], recipe['guids'])
        for status in ({'result': 'done', 'made': 0}, {'result': 'done', 'made': 1, 'skipped': 1}, {'result': 'failed', 'made': 1}):
            with patch.object(Runner, 'run_game', return_value=(0, [], status)):
                with self.assertRaises(RuntimeError): runner.run_game('firetest', 'selected')
        with patch.object(Runner, 'run_game', return_value=(0, [], {'result': 'done', 'made': 1, 'skipped': 0})):
            self.assertEqual(runner.run_game('firetest', 'selected')[0], 0)

    def test_gui_routes_every_category_to_selected_cli(self):
        for tool in labs.TOOLS:
            for command in tool['cmds']:
                args = labs.selected_build(tool, command, {}, 'selection.json', 'output')
                if args[0] == '--stderr-info': args = args[1:]
                self.assertEqual(args[:2], ['--script', 'labtest.py'])
                parsed = labtest.parser().parse_intermixed_args(args[2:])
                self.assertEqual(parsed.tool, tool['key'])
                self.assertEqual(parsed.selection, 'selection.json')
        # Optional report folders remain positional even after wrapper flags.
        tool = labs.BY_KEY['bullettest']; command = next(c for c in tool['cmds'] if c['name'] == 'score')
        parsed = labtest.parser().parse_intermixed_args(labs.selected_build(tool, command, {0: 'saved run'}, 'selection.json', 'out')[2:])
        self.assertEqual(parsed.folder, 'saved run')

    def test_selected_selftest_dispatch_does_not_require_game_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp)/'selection.json'; file.write_text(json.dumps({'tool': 'selftest', 'targets': ['test_asset_selection']}))
            with patch('labtest.Install', side_effect=AssertionError('Game discovery should not run')):
                self.assertEqual(labtest.main(['all', '--tool', 'selftest', '--selection', str(file), '--output', tmp]), 0)

    def test_recorded_physics_are_used_for_reports_without_re_resolving_updated_mods(self):
        request = {'tool': 'bullettest', 'targets': ['mod|ammo']}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); saved = dict(request, signature='old', items=[{'prefab': 'old-ammo', 'coefficient': .93}])
            (root/'selection.json').write_text(json.dumps(saved)); (root/'firetest').mkdir()
            self.assertEqual(labtest.recorded_selection(root/'firetest', request)['items'][0]['coefficient'], .93)
            with self.assertRaises(ValueError): labtest.recorded_selection(root/'firetest', dict(request, coefficient=1))

    def test_partial_wind_suite_cannot_be_fitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); block = root/'w0'; (block/'firetest').mkdir(parents=True)
            (block/'firetest'/'plan.json').write_text(json.dumps([{'id': 'T0'}, {'id': 'T1'}]))
            status = block/'firetest.status.json'
            status.write_text(json.dumps({'result': 'done', 'made': 2, 'skipped': 0}))
            with patch('rockettest.flights_in', return_value=[({'id': 'T0'}, [0, 1])]):
                with self.assertRaises(ValueError): labtest.require_flights(root, 1)
            with patch('rockettest.flights_in', return_value=[({'id': i}, [0, 1]) for i in ('T0', 'T1')]):
                labtest.require_flights(root, 1)
                with self.assertRaises(ValueError): labtest.require_flights(root, 2)
                status.write_text(json.dumps({'result': 'done', 'made': 2, 'skipped': 1}))
                with self.assertRaises(ValueError): labtest.require_flights(root, 1)

    def test_saved_run_cannot_be_reported_as_another_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'selection.json').write_text(json.dumps({'signature': 'one'})); (root/'firetest').mkdir()
            labtest.assert_run(root/'firetest', 'one')
            with self.assertRaises(ValueError): labtest.assert_run(root/'firetest', 'two')

if __name__ == '__main__': unittest.main()
