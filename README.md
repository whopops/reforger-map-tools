# Reforger map tools

Workbench export for any Arma Reforger map: enterable buildings, roads (including dirt tracks and bridge decks the old road tool skipped), and your own satellite pictures. Nothing here is merged into a map repo. Raw screenshots stay on disk.

The addon depends on the game project `58D0FB3206B6F859`. Open Workbench on this `addon.gproj` (or enable the addon on the project you already use). Plugins run from `-plugin`, not a toolbar button.

`maps/everon.json` has the island size, tile size, and the world resource. **Confirm that world in the World Editor before the first run.** The usual Everon world is `worlds/Eden/Eden.ent`. If it is not the world you have open, change the string. The plugin does not hardcode it. A probe of nine boxes across the island exits 3 and writes nothing when the world did not load. A loaded Everon has about 1.2 million editor entities.

## From another program

One command runs the whole export through the World Editor with no button and no prompt. Workbench is started with `-wbModule=WorldEditor -run -load <world> -plugin=MapExportPlugin`, closed when the plugin calls `Workbench.Exit`, and started again until that job's status file says `done`. The building JSON, the dirt/bridge check, and the satellite tiles run after the matching job. The caller just waits for the process.

```
scripts\run_export.cmd --map everon
```

The same thing from Python, or from PowerShell if you can set the execution policy:

```
python py/run_export.py --map everon
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_export.ps1 -Map everon
```

`--jobs buildings,roads,satellite` is the default. `--max-tiles 2` is how many new tiles one Workbench launch may write. `--workbench` is the exe if it is not in the usual Steam folder (`ARMA_REFORGER_WORKBENCH` is checked too). While it runs, `<profile>\reforger_map\<map>\pipeline.status.json` is `partial`, then `done` or `failed`.

| Exit | Meaning |
|---|---|
| 0 | Every requested step finished |
| 1 | A step failed, or a launch made no progress |
| 2 | The map file, Python, or Workbench could not be found |
| 3 | The world did not load. Nothing was written, and later jobs are not started |

`scripts\export_buildings.ps1`, `export_roads.ps1`, and `export_satellite.ps1` are the same runner with one job. The editor camera fov and far plane still have to be set once before a satellite run. No script API can set them.

## Buildings

```
ArmaReforgerWorkbenchSteam.exe -wbModule=WorldEditor -run -load "<world>" -plugin=MapExportPlugin -job=buildings -size=12800 -tile=500 -buildingStep=2 -maxTiles=2 -out=$profile:reforger_map/everon
```

`scripts/export_buildings.ps1` repeats that until `export.status.json` says `done`. Default is 2 new tiles a launch. A tile is skipped only when its CSV and its `.ok` both exist. The `.ok` is written after the file is closed. `maxTiles` is checked before a file is created.

For each 500 m tile: `buildings/b_TX_TZ.csv` (one building per origin tile), `d_TX_TZ.csv` (door, sliding-door, hatch, ladder, gap), `f_TX_TZ.csv` (floor clusters). A building's class contains `Building`, or its prefab contains `/Structures/`, `/Buildings/`, or `/Houses/`. Decals, lights, roads, probes, anything wider than 400 m, and anything under 3 m on both horizontal axes or under 2 m tall are skipped.

```
python py/buildings_to_json.py --src "<export folder>" --out buildings.json --map maps/everon.json
```

The JSON is `id`, `prefab`, `position`, `yaw`, `bounds`, `enterable`, `floors`, `entrances`. It is not written if it would exceed 40 MB, and it does not invent rows. `samples/buildings.sample.json` is that file with zero buildings. The schema is `schema/buildings.schema.json`.

## Roads

The previous road tool only walked top-level editor entities. It wrote `SplinePoints` on a `RoadEntity`, or the curve of a top-level shape whose direct child class contains `RoadGenerator`. That missed parts of dirt roads and bridges:

- a dirt `RoadEntity` parented under the shape's generator (the usual road hierarchy is shape, then generator, then road)
- the line living on the shape's `Points` / `GetPointsPositions`, which that tool could not copy onto the nested road
- bridge decks, which are not `RoadEntity` (prefab under `/Bridges/`, or a `RoadNetworkBridgeComponent` whose points are the drivable link)

`-job=roads` walks every child. The shape is one piece: its curve (or, if the curve is empty, its control points) is the line, and the nested road's material says whether it is dirt. The nested road is not written again. A road with no parent shape still contributes its own `SplinePoints`, `Points`, or a float list of triples. A `RoadNetworkBridgeComponent` contributes its points (`Points`, `SplinePoints`, `m_aPoints`, `LinePoints`, or `BridgePoints`, local or world). A bridge that still has no line gets the long axis of its bounds, marked `bounds`, so the deck is not a hole. Dirt is never accepted on bounds alone.

`py/check_roads.py` fails the export if a dirt piece has fewer than two real points, or a bridge has no line at all. Real points are `curve`, `spline`, `points`, and `bridge`.

```
scripts\export_roads.ps1
python py/check_roads.py --src "<export folder>"
```

Tiles are `roads/n_TX_TZ.csv` and `roads/p_TX_TZ.csv`, with `roads.status.json`.

## Satellite tiles

The field map's pictures are `tiles/{z}/{x}/{y}.jpg`. Level 0 is the finest (128 tiles a side, about 100 m each) and level 5 is the coarsest. They use the same Leaflet placement as the map: a 50 m origin offset, a scale of 12.501, 256 px tiles, north at the top. This builds that pyramid on disk. Copy it into the map's `tile_cache/` and the server serves the file it already has instead of downloading from an external tile site. Nothing in the map repo has to change.

From one north-up picture of the whole island (west at the left, covering 0..12800):

```
python py/make_tiles.py --image everon.png --out tiles --size 12800
```

Or from Workbench shots. Set the editor camera to fov 15 and a far plane above the height the plugin prints (it cannot set either itself). Then:

```
scripts\export_satellite.ps1
python py/make_tiles.py --shots "<profile>\reforger_map\everon\satellite" --png-dir "<profile>\screenshots" --out tiles
```

Each shot's center square is the ground square in `s_TX_TZ.txt`. Workbench's screenshot often lands in the profile `screenshots` folder as `s_TX_TZ.png` rather than next to the txt; `--png-dir` is that folder. Copy `tiles/` into the map's `tile_cache/` (same `z/x/y.jpg` layout).

## Tests

```
python -m unittest test_run_export.py test_road_cover.py test_make_tiles.py test_buildings_to_json.py
```

Run that from `py/`.
