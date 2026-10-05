"""Website coverage drift, mortar output and measurement-selection contracts."""
import json
from pathlib import Path
import tempfile
import unittest
from rmtlib import webdata, fieldmap, reticles
from rmtgui import labs


class WebsiteDataTests(unittest.TestCase):
    def test_nested_tiles_classified_but_new_dataset_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'server.py').touch(); data = root/'static'/'data'
            for name in ('maps/test/map.json', 'maps/test/tiles/0/2/3.jpg', 'maps/test/relief/2/4/6.jpg', 'test.json', 'mortar-tables.json', 'new-data.json'):
                file = data/name; file.parent.mkdir(parents=True, exist_ok=True); file.write_text('{}')
            report = webdata.inventory(root)
            self.assertEqual(report['unknown'], ['new-data.json'])
            self.assertEqual(sum(r['files'] for r in report['inputs']), 5)
            self.assertTrue(all(r['producerPresent'] for r in report['inputs']))

    def test_current_nested_website_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); tools = root/'reforger-map-tools'; tools.mkdir()
            app = root/'arma-map'/'arma-map'; app.mkdir(parents=True); (app/'server.py').touch()
            self.assertEqual(fieldmap.default_field_map(tools), str(app))

    def test_mortar_schema_and_missing_ring_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp)/'tables.csv'; file.write_text('id,range,elevation,time,delevation\n0,50,1500,13.2,61\n0,100,1450,13.0,0\n')
            page = {'id': '0', 'weapon': 'M252', 'shell': 'HE M821', 'ring': 0, 'mils': 6400, 'dispersion': 10}
            doc = webdata.bake_mortar([page], file)
            self.assertEqual(doc['weapons']['M252']['shells']['HE M821']['0']['table'][-1][3], 61)
            missing = dict(page); missing['id'] = '1'
            with self.assertRaises(ValueError): webdata.bake_mortar([page, missing], file)

    def test_blast_standing_uncon_selection_and_nonfinite_rejected(self):
        summary = {'HE|standing|uncon': {'down50': 18, 'hurt10': 27}, 'HE|prone|uncon': {'down50': 2, 'hurt10': 4}}
        self.assertEqual(webdata.blast(summary)['BLAST']['HE'], {'kill': 18, 'danger': 27})
        summary['HE|standing|uncon']['down50'] = None
        with self.assertRaises(ValueError): webdata.blast(summary)

    def test_conflict_gui_arguments_use_world_not_fake_subcommand(self):
        tool = labs.BY_KEY['conflict']; command = tool['cmds'][0]
        self.assertEqual(labs.build(tool, command, {0: 'Cain', 1: 'C:/site'}), ['--script', 'conflict.py', 'Cain', '--to', 'C:/site'])

    def test_curated_recipes_produce_all_existing_sight_sketches(self):
        with tempfile.TemporaryDirectory() as tmp:
            webdata.recipes(tmp)
            doc = json.loads((Path(tmp)/'website-calibration.json').read_text())
            svgs = list((Path(tmp)/'legacy-sights').glob('*.svg'))
            self.assertEqual(len(svgs), len(doc['sightDefinitions']))
            self.assertEqual(len(doc['constructionRoles']), 26)
            for file in svgs:
                self.assertIn('<path', file.read_text())
            self.assertTrue((Path(tmp)/'manual'/'everon-caves.json').is_file())


if __name__ == '__main__': unittest.main()
