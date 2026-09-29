"""The old road tool dropped these. This export must still have a line for each."""

import json
import os
import tempfile
import unittest

import check_roads
from road_cover import new_has_line, old_has_line, role_of


class CoverTests(unittest.TestCase):
    def test_nested_dirt_was_missed(self):
        self.assertFalse(old_has_line("RoadEntity", top_level=False, is_shape=False, generator_cls="", point_sources=["spline"]))
        self.assertTrue(new_has_line("RoadEntity", "Prefabs/Roads/dirt_road.et", "roads/data/dirt.emat", ["spline"], False))

    def test_dirt_points_array_was_missed(self):
        self.assertFalse(old_has_line("RoadEntity", True, False, "", ["points"]))
        self.assertTrue(new_has_line("RoadEntity", "Prefabs/Roads/forest.et", "Forest_Road", ["points"], False))

    def test_bridge_deck_was_missed(self):
        self.assertFalse(old_has_line("StaticModelEntity", True, False, "", []))
        self.assertTrue(new_has_line("StaticModelEntity", "Structures/Bridges/Bridge_01.et", "", [], True))

    def test_plain_asphalt_still_kept(self):
        self.assertTrue(old_has_line("RoadEntity", True, False, "", ["spline"]))
        self.assertTrue(new_has_line("RoadEntity", "Prefabs/Roads/asphalt.et", "asphalt_dashed", ["spline"], False))

    def test_dirt_box_alone_is_not_a_line(self):
        self.assertFalse(new_has_line("RoadEntity", "dirt.et", "dirt", [], True))

    def test_checker_accepts_dirt_and_bridge(self):
        with tempfile.TemporaryDirectory() as tmp:
            roads = os.path.join(tmp, "roads")
            os.makedirs(roads)
            write_pair(roads, "n_0_0.csv", "p_0_0.csv",
                       ["d_1,dirt,RoadEntity,dirt.et,,dirt,4,2,1,2,3,0,0,0,0,4,1,3\n",
                        "b_1,bridge,StaticModelEntity,Structures/Bridges/Bridge_01.et,, ,0,0,10,1,10,90,8,0,9,20,2,12\n"],
                       ["d_1,spline,0,1,2,3\n", "d_1,spline,1,4,2,6\n",
                        "b_1,bounds,0,8,1,10\n", "b_1,bounds,1,20,1,10\n"])
            with open(os.path.join(tmp, "roads.status.json"), "w", encoding="utf8") as f:
                json.dump({"result": "done", "made": 1, "skipped": 0, "remaining": 0}, f)
            self.assertEqual(check_roads.main(["--src", tmp, "--min-dirt", "1", "--min-bridge", "1"]), 0)

    def test_nested_dirt_points_live_on_the_parent_shape(self):
        # The road entity is under the generator, so the old tool never saw it.
        # The spline is the parent shape's Points, not the road's SplinePoints.
        self.assertFalse(old_has_line("RoadEntity", top_level=False, is_shape=False, generator_cls="", point_sources=[]))
        self.assertTrue(new_has_line(
            "RoadEntity", "Prefabs/WEGenerators/Roads/Dirt/Dirt_8m.et", "", [], False, parent_points=True))

    def test_shape_is_not_written_twice_as_the_child(self):
        self.assertFalse(new_has_line(
            "RoadEntity", "Prefabs/WEGenerators/Roads/Dirt/Dirt_8m.et", "dirt", [], False,
            parent_points=True, ancestor_exported=True))

    def test_dirt_prefab_under_roads_needs_no_material_word(self):
        self.assertEqual(role_of("SplineShapeEntity", "Prefabs/WEGenerators/Roads/Dirt/forest_road.et", ""), "dirt")
        self.assertEqual(role_of("StaticModelEntity", "Prefabs/Props/Dirt/Pile.et", ""), "")

    def test_bridge_component_points_were_missed(self):
        # Not a RoadEntity, prefab does not contain /Bridges/, no spline. The old tool had nothing.
        # The drivable line is RoadNetworkBridgeComponent.
        self.assertFalse(old_has_line("StaticModelEntity", True, False, "", []))
        self.assertTrue(new_has_line(
            "StaticModelEntity", "Prefabs/Props/Infrastructure/Crossing.et", "", [], False, bridge_component=True))
        self.assertEqual(role_of("StaticModelEntity", "Prefabs/Props/Infrastructure/Crossing.et", "", bridge_component=True), "bridge")

    def test_checker_accepts_bridge_component_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            roads = os.path.join(tmp, "roads")
            os.makedirs(roads)
            write_pair(roads, "n_0_0.csv", "p_0_0.csv",
                       ["b_1,bridge,StaticModelEntity,Crossing.et,, ,0,0,10,1,10,90,8,0,9,20,2,12\n"],
                       ["b_1,bridge,0,10,1,10\n", "b_1,bridge,1,18,1,12\n"])
            with open(os.path.join(tmp, "roads.status.json"), "w", encoding="utf8") as f:
                json.dump({"result": "done", "made": 1, "skipped": 0, "remaining": 0}, f)
            self.assertEqual(check_roads.main(["--src", tmp, "--min-dirt", "0", "--min-bridge", "1"]), 0)

    def test_checker_rejects_dirt_without_a_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            roads = os.path.join(tmp, "roads")
            os.makedirs(roads)
            write_pair(roads, "n_0_0.csv", "p_0_0.csv",
                       ["d_1,dirt,RoadEntity,dirt.et,,dirt,4,2,1,2,3,0,0,0,0,4,1,3\n"],
                       ["d_1,bounds,0,0,1,1\n", "d_1,bounds,1,4,1,1\n"])
            with open(os.path.join(tmp, "roads.status.json"), "w", encoding="utf8") as f:
                json.dump({"result": "done", "made": 1, "skipped": 0, "remaining": 0}, f)
            self.assertEqual(check_roads.main(["--src", tmp]), 1)


def write_pair(folder, nodes, points, node_rows, point_rows):
    header_n = "id,role,class,prefab,parent,material,width,type,x,y,z,yaw,minx,miny,minz,maxx,maxy,maxz\n"
    header_p = "id,which,i,x,y,z\n"
    for name, header, rows in ((nodes, header_n, node_rows), (points, header_p, point_rows)):
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf8") as f:
            f.write(header)
            f.writelines(rows)
        with open(path + ".ok", "w", encoding="utf8") as f:
            f.write("ok\n")


if __name__ == "__main__":
    unittest.main()
