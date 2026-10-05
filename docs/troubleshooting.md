# Troubleshooting and hard rules

## Hard rules (found by testing)

- **Script file writes only go through `$profile:`.** Writing anywhere else (the addon folder, or an absolute path
  even inside the profile) opens a modal "Script Authorization Required" dialog that stalls the run. Output always
  goes to `$profile:`, and `rmt.py` reads it from there.
- **Workbench's working directory must be its own folder.** Otherwise a modal "Missing Addon" dialog blocks forever.
- **Folders are created one level at a time** (`MakeDirectory` is not recursive).
- **Pictures need the game, not Workbench.** Command-line Workbench draws nothing, so screenshots are black.
- **Orthographic cameras render black** in this build; satellite shots are narrow-lens perspective instead.
- **One export per game build.** A game update means a new `out/<slug>/<build>/` and a new raw folder; old and new are
  never mixed.
- **Steam must be running**, and Workbench and the game must be closed (they are checked by process name).

## Messages and fixes

| You see | Cause and fix |
|---|---|
| `Steam is not installed` / `Arma Reforger is not installed` / `Workbench not found` | `steam.py` could not find it. Check Steam is installed and the apps are installed; otherwise pass `--workbench`. |
| `no world 'X'. Run rmt.py worlds...` | The name is not in `out/worlds.txt`. Run `python rmt.py worlds --refresh`, or pass the `.ent` path. |
| `'X' matches several worlds` | Use the full resource path from `worlds`. |
| `Workbench is already running` / `Arma Reforger is already running` | Close it. |
| `the world did not load` (exit 3) | The world's addon is missing (mod maps need the Workshop download), or the path is wrong. Nothing was written. |
| `no progress for N s (a dialog, or a hang)` | A modal dialog is open or Workbench hung. Look at the screen. If it is a script authorization or missing addon dialog, a rule above is broken. Rerun resumes. |
| `script error: ...` | Enforce compile error in `addon/`. Not retried. Fix the script. |
| `the process started but wrote no log` | Engine failed to start. Check Steam and the game build. |
| `satellite needs the probe job first` | Run `--jobs probe,satellite` once. |
| `[job] FAILED` then `FAILED: ...` | Rerun the same command; finished chunks and jobs are kept. |
| `bake`: `no export of 'X' under out/` | No manifest. Run `export` first. |
| `satellite: no shots in <folder>` or `foliage: no photographs in <folder>` | The game jobs write to the game profile, not Workbench's; run them first. |
| `plants: no foliage measurements in site/foliage` | Bake `--parts foliage` before `plants`. |
| `no finished shots in <folder>` | The satellite folder has no picture with a matching `.txt`. |
| Everything works but a few chunks look empty | Open-sea chunks are skipped on purpose. |
| `check`: `no sight lines at <path>` | Run `python rmt.py export <world> --jobs sightlines` first. |
| `check`: `no baked line of sight in <folder>` | Run `python rmt.py bake <world> --parts los` first. |
| `check`: `bullets not scored (these tiles have no cover plane)` | The tiles were trimmed to four planes. Score a bake's own `site/` instead. |
| `check`: agreement far below 95% | The sight lines and the tiles are from different worlds or builds (`--csv` and `--site` mixed up), or the bake is broken. |
| `sightlines`: `nothing to do` or `no land found` | The world is under 400 m across, or has no ground 1 m above the water line inside its edge. |
| `fieldmap`: `--to must be the field map's folder` | arma-map is not at `..\..\arma-map\everon-map` from this repo; pass `--to` the folder holding `server.py`. |
| `fieldmap`: `no site id for <slug>` | A new map: pass `--as <id>`, add it to `MAPS` in the field map's `static/app.js` and `server.py`, and to `MAPS` in `rmtlib/fieldmap.py` (its 3D title and start). |
| `fieldmap`: `<file> isn't in <site>` | Bake the missing part (`los`, `places`, `roads`, `foliage`, `plants`) first. |
| `fieldmap`: `trees/: no entities export or foliage measurements` | The 3D trees weren't rebuilt (the rest was installed). Export `entities` and bake `foliage`, then rerun. |
| `fieldmap`: `tuned colours for 0/N kinds` | The site's `static/data/maps/everon/trees/species.json` was missing, so every kind got plain greens. Restore it from arma-map's git history and rerun. |

## Checks you can do without running anything heavy

```bash
python rmt.py --help
python rmt.py worlds                 # uses the cache, does not start Workbench
python -m rmtlib.pak list "Arland"   # proves the game paks are readable
```
`python rmt.py export <small world> --jobs probe` is the lightest real test: Arland loads in about 3 s and reports
173,226 entities.

## Not wired up or not finished

- `foliagetrace` is an experiment and is not part of the pipeline.
- The `sightlines` job is a port of the old Everon exporter's check and has not been run in Workbench yet; its scorer
  (`rmt.py check`) was proven on the old Everon `check.csv`. Try it on Arland first.
- The `.topo` sections `AREA`, `WATR` and `PWLN` are not decoded (forest outlines, water, power lines); `ROAD`,
  `BULD` and `HILL` are.
- Later work: doors, power lines and POIs. Nothing checks the 2.5 GB site-data budget yet ([bakers.md](bakers.md)).
- Game updates can rename classes or materials; every export records its game build, so compare a new build's bake
  with the last one's.
- `Exporter.export` accepts `fresh=True` but `rmt.py` has no `--fresh` option; the function refuses unless you delete
  the raw folder yourself, since `rmt` never deletes exports.
- Check Bohemia's content and licensing rules before hosting anything derived from the game's data publicly.
