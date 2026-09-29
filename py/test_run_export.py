"""An external program can start one command. Workbench is relaunched until the export is done."""

import json
import os
import tempfile
import unittest

import run_export


MAP = {"size": 500, "tile": 500, "buildingStep": 2, "world": "worlds/Eden/Eden.ent"}


def write_status(folder, name, result, remaining):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), "w", encoding="utf8") as f:
        json.dump({"result": result, "made": 1, "skipped": 0, "remaining": remaining}, f)


def write_buildings(folder):
    buildings = os.path.join(folder, "buildings")
    os.makedirs(buildings, exist_ok=True)
    for name, header in (
        ("b_0_0.csv", "id,class,prefab,x,y,z,yaw,pitch,roll,scale,minx,miny,minz,maxx,maxy,maxz,enterable,doors,floors,parts\n"),
        ("d_0_0.csv", "id,kind,x,y,z,class\n"),
        ("f_0_0.csv", "id,y,samples\n"),
    ):
        with open(os.path.join(buildings, name), "w", encoding="utf8") as f:
            f.write(header)
        with open(os.path.join(buildings, name + ".ok"), "w", encoding="utf8") as f:
            f.write("ok\n")


def write_roads(folder):
    roads = os.path.join(folder, "roads")
    os.makedirs(roads, exist_ok=True)
    files = {
        "n_0_0.csv": (
            "id,role,class,prefab,parent,material,width,type,x,y,z,yaw,minx,miny,minz,maxx,maxy,maxz\n"
            "d_1,dirt,RoadEntity,dirt.et,,dirt,4,2,1,2,3,0,0,0,0,4,1,3\n"
            "b_1,bridge,StaticModelEntity,Structures/Bridges/Bridge_01.et,, ,0,0,10,1,10,90,8,0,9,20,2,12\n"
        ),
        "p_0_0.csv": (
            "id,which,i,x,y,z\n"
            "d_1,spline,0,1,2,3\n"
            "d_1,spline,1,4,2,6\n"
            "b_1,bounds,0,8,1,10\n"
            "b_1,bounds,1,20,1,10\n"
        ),
    }
    for name, text in files.items():
        with open(os.path.join(roads, name), "w", encoding="utf8") as f:
            f.write(text)
        with open(os.path.join(roads, name + ".ok"), "w", encoding="utf8") as f:
            f.write("ok\n")


class RunExportTests(unittest.TestCase):
    def test_command_launches_workbench_with_no_button(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = os.path.join(tmp, "ArmaReforgerWorkbenchSteam.exe")
            open(exe, "wb").close()
            args = run_export.build_args(["--map", "everon", "--jobs", "roads", "--workbench", exe, "--src", tmp])
            cmd = args.commands["roads"]
            self.assertEqual(cmd[0], exe)
            self.assertEqual(cmd[1:5], ["-wbModule=WorldEditor", "-run", "-load", "worlds/Eden/Eden.ent"])
            self.assertIn("-plugin=MapExportPlugin", cmd)
            self.assertIn("-job=roads", cmd)
            self.assertIn("-out=$profile:reforger_map/everon", cmd)

    def test_missing_workbench_is_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "missing.exe")
            self.assertEqual(run_export.main(["--map", "everon", "--workbench", missing, "--src", tmp]), 2)

    def test_relaunches_until_the_status_says_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.args(tmp, ["roads"])
            calls = {"n": 0}

            def launch(cmd):
                self.assertIn("-run", cmd)
                calls["n"] += 1
                remaining = 4 if calls["n"] == 1 else 0
                result = "partial" if remaining else "done"
                write_status(tmp, "roads.status.json", result, remaining)
                if result == "done":
                    write_roads(tmp)
                return 0

            self.assertEqual(run_export.run_pipeline(args, launch), 0)
            self.assertEqual(calls["n"], 2)
            with open(os.path.join(tmp, "pipeline.status.json"), encoding="utf8") as f:
                state = json.load(f)
            self.assertEqual(state["result"], "done")
            self.assertEqual(state["exit"], 0)
            self.assertEqual([step["name"] for step in state["steps"]], ["roads", "check_roads"])

    def test_empty_world_stops_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.args(tmp, ["buildings", "roads"])
            seen = []

            def launch(cmd):
                seen.append([part for part in cmd if part.startswith("-job=")][0])
                return 3

            self.assertEqual(run_export.run_pipeline(args, launch), 3)
            self.assertEqual(seen, ["-job=buildings"])

    def test_no_progress_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.args(tmp, ["buildings"])

            def launch(cmd):
                write_status(tmp, "export.status.json", "partial", 5)
                return 0

            self.assertEqual(run_export.run_pipeline(args, launch), 1)

    def test_full_run_chains_the_python_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.args(tmp, ["buildings", "roads", "satellite"])
            tiled = {}

            def launch(cmd):
                job = [part for part in cmd if part.startswith("-job=")][0].split("=", 1)[1]
                write_status(tmp, run_export.STATUS_NAME[job], "done", 0)
                if job == "buildings":
                    write_buildings(tmp)
                if job == "roads":
                    write_roads(tmp)
                return 0

            def tiles(argv):
                tiled["argv"] = argv
                return 0

            self.assertEqual(run_export.run_pipeline(args, launch, tiles_main=tiles), 0)
            self.assertTrue(os.path.isfile(os.path.join(tmp, "buildings.json")))
            self.assertIn("--shots", tiled["argv"])
            self.assertTrue(tiled["argv"][tiled["argv"].index("--shots") + 1].endswith(os.path.join("satellite")))

    def test_image_does_not_wait_for_screenshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.args(tmp, ["buildings"])
            args.image = os.path.join(tmp, "island.png")
            tiled = {}

            def launch(cmd):
                write_status(tmp, "export.status.json", "done", 0)
                write_buildings(tmp)
                return 0

            def tiles(argv):
                tiled["argv"] = list(argv)
                return 0

            self.assertEqual(run_export.run_pipeline(args, launch, tiles_main=tiles), 0)
            self.assertIn("--image", tiled["argv"])
            self.assertNotIn("--shots", tiled["argv"])

    def args(self, src, jobs):
        map_path = os.path.join(src, "map.json")
        with open(map_path, "w", encoding="utf8") as f:
            json.dump(MAP, f)
        ns = run_export.build_args([
            "--map", map_path,
            "--jobs", ",".join(jobs),
            "--src", src,
            "--skip-workbench",
            "--min-dirt", "1",
            "--min-bridge", "1",
        ])
        ns.skip_workbench = False
        ns.commands = {
            job: run_export.workbench_command("Workbench.exe", MAP, job, 2, "everon", "", "")
            for job in jobs
        }
        return ns


if __name__ == "__main__":
    unittest.main()
