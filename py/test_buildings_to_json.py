import json
import os
import tempfile
import unittest

import buildings_to_json as baker


HEADER_B = "id,class,prefab,x,y,z,yaw,pitch,roll,scale,minx,miny,minz,maxx,maxy,maxz,enterable,doors,floors,parts\n"
HEADER_D = "id,kind,x,y,z,class\n"
HEADER_F = "id,y,samples\n"


def write_csv(folder, name, text):
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf8") as f:
        f.write(text)
    with open(path + ".ok", "w", encoding="utf8") as f:
        f.write("ok\n")


class BakerTests(unittest.TestCase):
    def test_one_building_and_empty_tiles_are_not_invented(self):
        with tempfile.TemporaryDirectory() as tmp:
            buildings = os.path.join(tmp, "buildings")
            os.makedirs(buildings)
            write_csv(buildings, "b_1_2.csv", HEADER_B + "10_20_30_0,SCR_DestructibleBuildingEntity,Prefabs/Houses/House.et,10,20,30,90,0,0,1,8,19,28,14,28,36,1,1,1,DoorEntity\n")
            write_csv(buildings, "d_1_2.csv", HEADER_D + "10_20_30_0,door,11,21,31,DoorComponent\n")
            write_csv(buildings, "f_1_2.csv", HEADER_F + "10_20_30_0,21.5,4\n")
            with open(os.path.join(tmp, "export.status.json"), "w", encoding="utf8") as f:
                json.dump({"result": "done", "made": 1, "skipped": 0, "remaining": 0}, f)
            out = os.path.join(tmp, "buildings.json")
            self.assertEqual(baker.main(["--src", tmp, "--out", out]), 0)
            doc = json.loads(open(out, encoding="utf8").read())
            self.assertEqual(len(doc["buildings"]), 1)
            row = doc["buildings"][0]
            self.assertEqual(row["id"], "10_20_30_0")
            self.assertEqual(row["enterable"], 1)
            self.assertEqual(row["entrances"][0]["kind"], "door")
            self.assertEqual(row["floors"][0]["samples"], 4)
            self.assertFalse(os.path.isfile(out + ".partial"))

    def test_refuses_over_40_megabytes_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            buildings = os.path.join(tmp, "buildings")
            os.makedirs(buildings)
            huge = "x" * 200
            write_csv(buildings, "b_0_0.csv", HEADER_B + f"1,Building,{huge},0,0,0,0,0,0,1,0,0,0,4,4,4,0,0,0,\n")
            write_csv(buildings, "d_0_0.csv", HEADER_D)
            write_csv(buildings, "f_0_0.csv", HEADER_F)
            with open(os.path.join(tmp, "export.status.json"), "w", encoding="utf8") as f:
                json.dump({"result": "done", "made": 1, "skipped": 0, "remaining": 0}, f)
            out = os.path.join(tmp, "buildings.json")
            with self.assertRaises(SystemExit):
                baker.main(["--src", tmp, "--out", out, "--max-bytes", "80"])
            self.assertFalse(os.path.isfile(out))

    def test_partial_export_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "buildings"))
            with open(os.path.join(tmp, "export.status.json"), "w", encoding="utf8") as f:
                json.dump({"result": "partial", "made": 1, "skipped": 0, "remaining": 4}, f)
            with self.assertRaises(SystemExit):
                baker.read_export(tmp)


if __name__ == "__main__":
    unittest.main()
