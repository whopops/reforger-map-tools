# `audible/`: gunshot audibility scripts

How far a gunshot can be heard, from the game's own sound files. These five scripts read the game's `.pak` archives
directly, so they need no Workbench and no running game. The full method, assumptions and run order are in
[../docs/audible.md](../docs/audible.md); `README.txt` is the short plain-text quick start.

## Run (from inside this folder)

```bash
python audible.py        # 1. measure the shot and noise samples -> S.npy, N.npy
python audible3.py       # 2. result table -> audible.json
python loud.py "regex"   # optional: loudness of any game .wav
```
Needs `numpy`, `scipy` and an installed copy of the game. Install the root `requirements.txt` using the same
interpreter you will run here. If using the launcher's environment, run `..\.venv\Scripts\python.exe` instead of
`python`. Check `GAME` in `pakx.py` before starting: it defaults to the standard Steam installation's `addons`
folder and does not use `rmtlib.steam` discovery. Run from this folder: the scripts import each other by bare name
and read and write spectra/results in the current folder. `audible.py` must run before `audible2.py` or
`audible3.py`, which load `S.npy` and `N.npy` at import. `loud.py` can run independently.

These are estimates from sound assets and assumed background levels, not measured in-game hearing distances.
The scripts write `audible.json` locally; copying results into a website or `everon-data/sound/` is a separate step.

## The scripts

| Script | Role | Inputs | Outputs |
|---|---|---|---|
| `pakx.py` | Index and read the game's paks. `list <regex>`, `cat <path>`, `grep <pathregex>::<textregex>`. API: `index()`, `read(pak, off, stored, size, comp)`. | game `addons/*/*.pak` (path in `GAME` at the top) | `pakindex.json` (built on first run, a minute or two) |
| `loud.py` | BS.1770 loudness. API: `load(path)`, `kweight`, `lufs(x, fs)`, `stats(path)`; `FILES` maps every game `.wav` to its pak. | game wavs | prints LUFS, peak, RMS and length |
| `audible.py` | Third-octave spectra. API: `mono`, `band_energy`, `shot_bands(paths)`, `noise_bands(paths)`, `absorption_db_per_km(f)` (ISO 9613-1), `BANDS`, `db`. As a script it measures the 5.56 Far/Mid blast layers and the meadow, forest and hills bed and wind recordings. | game wavs | `S.npy` (shot), `N.npy` (noise); prints the band table |
| `audible2.py` | `reach(class_lufs, noise_lufs, thresh=0, sample_lufs=-31.7, inner=2.0, rh=70)`: the distance at which the shot's best band (60 Hz and up) falls to the noise. As a script prints reaches for rifle, MG, heavy and suppressed. | `S.npy`, `N.npy` | prints |
| `audible3.py` | The final table: each gun and impact type (`G`, a loudness in LUFS) at four noise levels (`NOISE`: still -55, breeze -50, windy -45, storm -40), rounded to 5 m. | `audible2.reach` | `audible.json` `{levels, noise, reach}` |

## Changing things
- A new gun or impact type: add it to the `G` table in `audible3.py` (level at 2 m in LUFS; use the slope-ratio
  formula already there for anything without a named class).
- A new noise level: add it to `NOISE`.
- A different game install path: edit `GAME` in `pakx.py`.
- Delete `pakindex.json` if the game updates or `GAME` changes, so it is rebuilt. Re-run both measurement steps
  after an asset update; an old index or old spectra can give stale results.
- Generated files (`S.npy`, `N.npy`, `pakindex.json`, `audible.json`) are results, not source.
