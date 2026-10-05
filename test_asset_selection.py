"""World evidence and category-specific installed addon selection contracts."""
import unittest
from rmtlib.addons import classify_world
from rmtlib.ballistics import asset_kind, matches_asset

class AssetSelectionTests(unittest.TestCase):
    def test_mod_name_matching_world_folder_is_not_terrain_evidence(self):
        kind, _ = classify_world('Worlds/WCS_M2A2/WCS_M2A2.ent', b'SubScene { Parent "worlds/GameMaster/GM_Arland.ent" }')
        self.assertEqual(kind, 'scenario')
        self.assertEqual(classify_world('worlds/NewIsland/NewIsland.ent', b'GenericTerrainEntity')[0], 'terrain')
        self.assertEqual(classify_world('worlds/NewIsland/NewIsland.ent', None)[0], 'unknown')

    def test_test_and_image_worlds_stay_advanced_even_with_terrain(self):
        for path in ['Worlds/ImageGeneration/ImageGenerator.ent', 'worlds/MpTest/MpTest.ent', 'worlds/Tutorial/SF-Tutorial-Empty.ent']:
            self.assertEqual(classify_world(path, b'GenericTerrainEntity')[0], 'utility')

    def test_asset_scope_excludes_ammo_named_characters_and_sound_configs(self):
        self.assertEqual(asset_kind('Prefabs/Characters/Character_USSR_Ammo.et'), 'other')
        self.assertEqual(asset_kind('Sounds/Configs/Weapons/Mortar.conf'), 'other')
        self.assertEqual(asset_kind('Prefabs/Weapons/Ammo/Ammo_Bullet_762x51.et'), 'ammunition')
        self.assertEqual(asset_kind('Prefabs/Weapons/Attachments/Optics/PSO1.et'), 'optic')

    def test_bullet_mortar_and_rocket_filters_include_real_projectile_paths(self):
        for category, path in [('bullets', 'Prefabs/Weapons/Ammo/Ammo_Bullet_762x51.et'),
                               ('mortars', 'Prefabs/Weapons/Ammo/Ammo_Shell_81mm_HE_M821.et'),
                               ('rockets', 'Prefabs/Weapons/Ammo/Ammo_Rocket_PG7V.et')]:
            record = {'path': path, 'kind': asset_kind(path)}
            self.assertTrue(matches_asset(record, category))
            self.assertFalse(matches_asset(record, 'vehicle'))

if __name__ == '__main__': unittest.main()
