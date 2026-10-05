"""Custom asset identity, inheritance, dependencies and isolated flight plans."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from rmtlib.ballistics import Catalog, ELEVATIONS, WINDS, make_plan


class CustomBallisticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalog = Catalog(SimpleNamespace(), selected=[])

    def addon(self, guid, depends=()):
        folder = self.root / guid
        folder.mkdir()
        a = SimpleNamespace(guid=guid, folder=str(folder), source='workshop', depends=list(depends), title=guid)
        self.catalog.by_guid[guid] = a
        return a

    def record(self, guid, path, text, resource_guid):
        file = self.root / guid / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)
        ref = '{'+resource_guid+'}'+path
        item = {'resource': ref, 'path': path, 'addonGuid': guid, 'addon': guid, 'kind': 'weapon',
                'source': 'workshop', 'storage': ('file', str(file))}
        self.catalog.records.append(item)
        self.catalog.by_ref.setdefault(ref.lower(), []).append(item)
        self.catalog.by_path.setdefault(path.lower(), []).append(item)
        return item

    def test_mod_inherits_base_physics_and_weapon_references_ammo(self):
        self.addon('AAAAAAAAAAAAAAAA')
        self.addon('BBBBBBBBBBBBBBBB', ['AAAAAAAAAAAAAAAA'])
        parent = self.record('AAAAAAAAAAAAAAAA', 'Prefabs/Ammo/Base.et',
            'GenericEntity {\n ShellMoveComponent {\n InitSpeed 800\n AirDrag 0.1\n }\n}', '1111111111111111')
        ammo = self.record('BBBBBBBBBBBBBBBB', 'Prefabs/Ammo/Custom.et',
            'GenericEntity : "'+parent['resource']+'" {\n Mass 0.012\n}', '2222222222222222')
        gun = self.record('BBBBBBBBBBBBBBBB', 'Prefabs/Weapons/Gun.et',
            'GenericEntity {\n BulletInitSpeedCoef 0.93\n AmmoTemplate "'+ammo['resource']+'"\n}', '3333333333333333')
        report = self.catalog.inspect(gun['resource'])
        self.assertEqual(report['selected']['fields']['BulletInitSpeedCoef']['values'], [0.93])
        custom = next(p for p in report['projectiles'] if p['resource'] == ammo['resource'])
        self.assertEqual(custom['fields']['InitSpeed']['resource'], parent['resource'])
        self.assertEqual(custom['fields']['Mass']['values'], [0.012])
        guids, dirs = self.catalog.launch_addons([gun, ammo])
        self.assertEqual(set(guids), {'AAAAAAAAAAAAAAAA', 'BBBBBBBBBBBBBBBB'})
        self.assertEqual(dirs, [str(self.root)])

    def test_guid_identity_never_substitutes_another_mod_with_the_same_path(self):
        for guid in ('AAAAAAAAAAAAAAAA', 'BBBBBBBBBBBBBBBB'):
            self.addon(guid)
        first = self.record('AAAAAAAAAAAAAAAA', 'Prefabs/Ammo/Same.et', 'GenericEntity {}', '1111111111111111')
        self.record('BBBBBBBBBBBBBBBB', 'Prefabs/Ammo/Same.et', 'GenericEntity {}', '2222222222222222')
        self.assertEqual(self.catalog.resolve(first['resource']), first)
        with self.assertRaisesRegex(ValueError, '2 matches'):
            self.catalog.resolve('Prefabs/Ammo/Same.et')
        with self.assertRaisesRegex(ValueError, '0 matches'):
            self.catalog.resolve('{9999999999999999}Prefabs/Ammo/Same.et')

    def test_missing_dependencies_fail_instead_of_launching_without_mod(self):
        self.addon('AAAAAAAAAAAAAAAA', ['BBBBBBBBBBBBBBBB'])
        item = self.record('AAAAAAAAAAAAAAAA', 'a.et', 'GenericEntity {}', '1111111111111111')
        with self.assertRaisesRegex(ValueError, 'Missing installed dependency'):
            self.catalog.launch_addons([item])

    def test_multiple_muzzles_are_preserved_instead_of_arbitrarily_flattened(self):
        self.addon('AAAAAAAAAAAAAAAA')
        item = self.record('AAAAAAAAAAAAAAAA', 'vehicle.et',
            'GenericEntity {\n BulletInitSpeedCoef 0.8\n BulletInitSpeedCoef 1.2\n}', '1111111111111111')
        self.assertEqual(self.catalog.details(item)['fields']['BulletInitSpeedCoef']['values'], [0.8, 1.2])

    def test_flight_plan_covers_every_wind_elevation_and_calms_have_repeats(self):
        rows = make_plan('{1111111111111111}Ammo.et', 'test', 0.93, WINDS, 10, 5000)
        self.assertEqual(len(rows), len(ELEVATIONS)*6)
        self.assertEqual(len({r['id'] for r in rows}), len(rows))
        self.assertTrue(all(r['prefab'].startswith('{1111111111111111}') and r['coef'] == 0.93 for r in rows))
        self.assertEqual({(r['wspeed'], r['wfrom']) for r in rows}, set(WINDS))
        with self.assertRaises(ValueError):
            make_plan('Ammo.et', 'test', float('nan'), WINDS, 10, 5000)
        with self.assertRaises(ValueError):
            make_plan('Ammo,broken.et', 'test', 1, WINDS, 10, 5000)


    def test_unrelated_installed_override_does_not_contaminate_selected_mod(self):
        self.addon('AAAAAAAAAAAAAAAA')
        self.addon('BBBBBBBBBBBBBBBB')
        base = self.record('AAAAAAAAAAAAAAAA', 'Core.et', 'GenericEntity {}', '1111111111111111')
        base['source'] = 'game'
        override = self.record('BBBBBBBBBBBBBBBB', 'Core.et', 'GenericEntity {}', '1111111111111111')
        self.assertEqual(self.catalog.resolve(base['resource'], context='AAAAAAAAAAAAAAAA'), base)
        self.assertEqual(self.catalog.resolve(base['resource'], context='BBBBBBBBBBBBBBBB'), override)

    def test_ammo_config_is_followed_from_magazine_to_projectile(self):
        self.addon('AAAAAAAAAAAAAAAA')
        ammo = self.record('AAAAAAAAAAAAAAAA', 'Ammo.et', 'GenericEntity {\n ShellMoveComponent {}\n}', '1111111111111111')
        config = self.record('AAAAAAAAAAAAAAAA', 'Ammo.conf', 'SCR_AmmoTypeDefinition {\n AmmoPrefab "'+ammo['resource']+'"\n}', '2222222222222222')
        magazine = self.record('AAAAAAAAAAAAAAAA', 'Magazine.et', 'GenericEntity {\n AmmoConfig "'+config['resource']+'"\n}', '3333333333333333')
        self.assertEqual(self.catalog.inspect(magazine['resource'])['projectiles'][0]['resource'], ammo['resource'])

    def test_engine_done_without_trajectories_cannot_export_a_result_table(self):
        from rmtlib.ballistics import capture
        a=self.addon('AAAAAAAAAAAAAAAA')
        a.source='game'
        ammo=self.record('AAAAAAAAAAAAAAAA', 'Ammo.et', 'GenericEntity {\n ShellMoveComponent {}\n}', '1111111111111111')
        ammo['source']='game'
        self.catalog.install=SimpleNamespace(game_profile=str(self.root/'profile'),game_build='1',tools_build='2')
        with patch('rmtlib.ballistics.Exporter.resolve', return_value=('EmptyWorld',[],[])), patch('rmtlib.ballistics.Runner') as runner:
            runner.return_value.run_game.return_value=(0,[],{'result':'done'})
            with self.assertRaisesRegex(ValueError,'trajectories are missing'):
                capture(self.catalog,ammo['resource'],a.guid,None,None,'custom',str(self.root/'results'),wind=False)
        self.assertEqual(list((self.root/'results').rglob('ballistics.json')),[])

if __name__ == '__main__':
    unittest.main()
