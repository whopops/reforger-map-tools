"""The Labs page's tools: the standalone scripts beside rmt.py (mortar, blast and rocket tests in the game, gunshot
audibility, the game-file reader, the self-tests), described as data so the page can build a form for each command.

No Qt in here. Every command becomes a command line for `rmt_gui.py --script <file> ...` (or `--module`), which the
worker runs like an export: in a child process, with its output and the engine's heartbeat shown on the Run page.

Option kinds:
  int, float   a number box (default shown; left out of the command line when it is the script's own default)
  text         free text (left out when empty)
  folder       a folder, with Browse (left out when empty)
  shells       blasttest's shells, as checkboxes, joined with commas
  site         the field map's static/data folder: filled in from the Data page's field map folder
Positional options (flag None) go before the flagged ones, in order.
"""

import os

# blasttest.py's SHELLS and DEFAULT_SHELLS (kept here so the page doesn't import the test scripts)
BLAST_SHELLS = ("HE M821", "HE O-832DU", "Practice M879", "Smoke M819", "Smoke D-832DU")
BLAST_DEFAULT = ("HE M821", "HE O-832DU", "Practice M879")


def opt(flag, label, kind, default=None, help=""):
    return {"flag": flag, "label": label, "kind": kind, "default": default, "help": help}


def cmd(name, label, desc, game=False, minutes=None, opts=(), script=None, args=(), folder_skips_game=False, workbench=False):
    """game: the command starts the game on screen; folder_skips_game: given a run folder it only reports on it."""
    return {"name": name, "label": label, "desc": desc, "game": game, "workbench": workbench, "minutes": minutes, "opts": list(opts),
            "script": script, "args": list(args), "folder_skips_game": folder_skips_game}


SITE = opt("--site", "Field map data", "site", help="The field map's static/data folder (mortar tables and the "
           "baked Everon terrain are read from it).")
RUN_FOLDER = opt(None, "Run folder (optional)", "folder",
                 help="A run folder (or a copy of one) to report on. Empty: the last run in the game profile.")

TOOLS = [
    {
        "key": "conflict", "title": "Conflict references", "script": "conflict.py", "doc": "docs/website-data.md",
        "results": None,
        "desc": "Export/bake scenario bases, HQ starts, supply stashes, spawns, repair/refuel and FIA caches. Run after installing the map data. Workbench starts for export; existing caves are preserved.",
        "cmds": [
            cmd("export", "Export, bake and install", "Loads the selected world's Conflict scenario in Workbench.", script="conflict.py", workbench=True,
                opts=[opt(None, "World", "text", "Eden"), opt("--to", "Website application folder", "folder")]),
            cmd("bake", "Bake newest export and install", "Uses the existing scenario export.", script="conflict.py", args=["--skip-export"],
                opts=[opt(None, "World", "text", "Eden"), opt("--to", "Website application folder", "folder")]),
            cmd("preview", "Export and bake without installing", "Loads Workbench and saves conflict.json in the workspace.", script="conflict.py", args=["--no-install"], workbench=True,
                opts=[opt(None, "World", "text", "Eden")]),
        ],
    },
    {
        "key": "firetest", "title": "Mortar fire test", "script": "firetest.py", "doc": "docs/firetest.md",
        "results": "rmt/firetest",
        "desc": "Real mortar shells fired in the game on Everon, aimed with the field map's own firing solution, and "
                "where every round landed scored against it.",
        "cmds": [
            cmd("run", "Run the full test", "Plan the aims, then fire them in the game and write the report.",
                game=True, minutes=25, opts=[SITE]),
            cmd("score", "Report on a run", "The report on the last run (or a copy of one). No game.",
                opts=[RUN_FOLDER, SITE]),
            cmd("plan", "Write the plan only", "Write the plan into the game profile; nothing is fired.", opts=[SITE]),
            cmd("group", "Group: one aim, many rounds",
                "One aim fired again and again with the same numbers, a pause between rounds (as a crew re-laying "
                "after each), then where each landed. With a run folder it only reports on it.",
                game=True, minutes=10, folder_skips_game=True,
                opts=[opt("--distance", "Distance to the target", "float", 1200, "metres"),
                      opt("--ring", "Charge ring", "int", 3), opt("--rounds", "Rounds", "int", 10),
                      opt("--gap", "Seconds between rounds", "float", 15), RUN_FOLDER, SITE]),
            cmd("gun", "Gun: through a real mortar",
                "The group test fired through a real mortar (laid on the numbers before every round, the shell loaded "
                "and fired), so the barrel's dispersion is in it. With a run folder it only reports on it.",
                game=True, minutes=10, folder_skips_game=True,
                opts=[opt("--distance", "Distance to the target", "float", 1200, "metres"),
                      opt("--ring", "Charge ring", "int", 3), opt("--rounds", "Rounds", "int", 10),
                      opt("--gap", "Seconds between rounds", "float", 15), RUN_FOLDER, SITE]),
            cmd("barrel", "Barrel: the muzzle study",
                "Every charge ring of both mortars through the real weapon, each round measured leaving the muzzle; "
                "1 in 8 followed to impact. With a run folder it only reports on it.",
                game=True, minutes=60, folder_skips_game=True,
                opts=[opt("--per-ring", "Rounds per charge ring", "int", 40),
                      opt("--out", "Run folder in the game profile", "text", "",
                          "Empty: rmt/firetest-barrel. Give each study its own so one doesn't overwrite another."),
                      opt("--resume", "Resume a stopped run", "folder", "",
                          "A run folder that stopped part way: fire only the rounds it lacks."),
                      RUN_FOLDER, SITE]),
        ],
    },
    {
        "key": "blasttest", "title": "Mortar blast test", "script": "blasttest.py", "doc": "docs/firetest.md",
        "results": "rmt/blasttest",
        "desc": "What a mortar round does to soldiers around where it lands: riflemen stood in rings on empty Everon, a "
                "real shell dropped among them, and who is dead, down or hurt. The field map's kill and danger zones.",
        "cmds": [
            cmd("run", "Run the test", "Plan the trials, then run them in the game (on EmptyEden) and score them.",
                game=True, minutes=20,
                opts=[opt("--shells", "Shells", "shells", BLAST_DEFAULT),
                      opt("--trials", "Only the first N trials", "int", 0, "0: all of them. A few is a quick check."),
                      opt("--out", "Run folder in the game profile", "text", "",
                          "Empty: rmt/blasttest. Give each set of shells its own."), SITE]),
            cmd("score", "Report on a run", "The report on the last run (or a copy of one); writes summary.json.",
                opts=[RUN_FOLDER, opt("--out", "Run folder in the game profile", "text", ""), SITE]),
            cmd("plan", "Write the plan only", "Write the plan into the game profile; nothing runs.",
                opts=[opt("--shells", "Shells", "shells", BLAST_DEFAULT),
                      opt("--out", "Run folder in the game profile", "text", ""), SITE]),
        ],
    },
    {
        "key": "rockettest", "title": "Rocket flight test", "script": "rockettest.py", "doc": "docs/firetest.md",
        "results": "rmt/rockettest", "site_file": ("out/rockets.json", "rockets.json"),
        "desc": "How the game's shoulder-fired rockets fly, wind included: six rockets at eleven elevations in fifteen "
                "winds (3 to 20 m/s, from both sides, head and tail), flown high over open sea. Scoring writes "
                "rockets.json for the field map's rocket calculator.",
        "cmds": [
            cmd("run", "Fly the rockets",
                "One game run per wind, and one more of still air laid out like them (each wind's shots measured "
                "against their twins), about 80 minutes for all sixteen. Run it again to finish a broken run: runs "
                "already flown are skipped.", game=True, minutes=80),
            cmd("score", "Fit and write rockets.json",
                "Fit the flights (rocketfit.py), report how each wind moved them and how the launchers' sights fit, "
                "and write out/rockets.json. Only finished runs are read.", opts=[RUN_FOLDER]),
            cmd("check", "Check the site's answers in the game",
                "Random shots solved the site's way from out/rockets.json, fired in the game in ten random winds of 2 "
                "to 20 m/s (one run per wind, about 50 minutes); how far each passed from its target.",
                game=True, minutes=50),
            cmd("check-twins", "Check the wind's part in the game",
                "After a check: its shots fired again in still air, each the twin of one (the game's scatter repeats "
                "run to run), about 50 minutes; how far the calculator's wind was from the wind's real part of each "
                "shot, with the scatter taken out.", game=True, minutes=50),
            cmd("check-twins-score", "Report on the twins", "That report again. No game.", opts=[RUN_FOLDER]),
            cmd("check-score", "Report on a check", "That report again. No game.", opts=[RUN_FOLDER]),
            cmd("plan", "Write the plans only", "Write the plans (one per wind) into the game profile."),
        ],
    },
    {
        "key": "bullettest", "title": "Bullet flight test", "script": "bullettest.py", "doc": "docs/firetest.md",
        "results": "rmt/bullettest", "site_file": ("out/bullets.json", "bullets.json"),
        "desc": "How the rounds of the field map's scoped rifles, machine guns and vehicle guns fly: fourteen rounds at "
                "eleven elevations in five winds, flown high over open sea. Scoring writes bullets.json for the field "
                "map's sight calculator; the check fires its answers in random winds.",
        "cmds": [
            cmd("run", "Fly the rounds",
                "One game run per wind, about 15 minutes. Run it again to finish a broken run: winds already flown "
                "are skipped.", game=True, minutes=15),
            cmd("score", "Write bullets.json", "Table the flights (rocketfit.py) and write out/bullets.json.",
                opts=[RUN_FOLDER]),
            cmd("check", "Check the site's answers in the game",
                "Random shots solved the site's way from out/bullets.json, fired in the game in eight random winds of "
                "2 to 20 m/s (one run per wind, about 30 minutes); how far each passed from its target.",
                game=True, minutes=30),
            cmd("check-twins", "Check the wind's part in the game",
                "After a check: its shots fired again in still air, each the twin of one, about 30 minutes; how far the "
                "calculator's wind was from the wind's real part of each shot.", game=True, minutes=30),
            cmd("check-twins-score", "Report on the twins", "That report again. No game.", opts=[RUN_FOLDER]),
            cmd("check-score", "Report on a check", "That report again. No game.", opts=[RUN_FOLDER]),
            cmd("plan", "Write the plans only", "Write the plans (one per wind) into the game profile."),
        ],
    },
    {
        "key": "launchertest", "title": "Rocket launcher test", "script": "launchertest.py", "doc": "docs/firetest.md",
        "results": "rmt/launchertest",
        "desc": "The rockets fired the way a player does: the game's AT soldiers on a cliff above the sea zero the "
                "sight, aim and pull the trigger. Checks the sights against the bore, how a rocket leaves the tube, "
                "and how far the rocket calculator's own shots pass from their targets.",
        "cmds": [
            cmd("run", "Run the test", "Plan, then fire in the game and report.", game=True, minutes=30),
            cmd("score", "Report on a run", "The three reports (sights, launch, hits) on the last run or a copy. "
                "No game.", opts=[RUN_FOLDER]),
            cmd("plan", "Write the plan only", "Write the plan into the game profile; nothing is fired."),
        ],
    },
    {
        "key": "audible", "title": "Gunshot audibility", "script": None, "doc": "docs/audible.md", "cwd": "audible",
        "results": None,
        "desc": "How far a gunshot is heard, from the game's own sound files (read straight out of its paks; no game "
                "or Workbench). Do step 1 before step 2. Results are written in the audible folder.",
        "cmds": [
            cmd("measure", "1. Measure the samples",
                "Third-octave spectra of the shot and of the ambient noise: S.npy and N.npy. The first run indexes "
                "the game's paks (a minute or two).", script="audible/audible.py"),
            cmd("table", "2. Make the result table",
                "Every gun and impact type at four noise levels, rounded to 5 m: audible.json.",
                script="audible/audible3.py"),
            cmd("reach", "Reach by gun class",
                "Prints the reach of rifle, MG, heavy and suppressed shots at four noise levels.",
                script="audible/audible2.py"),
            cmd("loud", "Loudness of game sounds",
                "LUFS, peak, RMS and length of every game .wav matching a pattern.", script="audible/loud.py",
                opts=[opt(None, "Pattern (regex)", "text", "Bed_Meadow")]),
        ],
    },
    {
        "key": "pak", "title": "Game files", "module": "rmtlib.pak", "doc": "README.md", "results": None,
        "desc": "Look inside the game's .pak archives, to see how BI does something. The first search scans every "
                "pak and takes a few seconds.",
        "cmds": [
            cmd("list", "Find files", "Every path in the game paks matching a pattern, with its size and pak.",
                opts=[opt(None, "Pattern (regex)", "text", "SCR_WorldDataExport")]),
            cmd("cat", "Show a file", "One file as text, by its exact path.",
                opts=[opt(None, "Path", "text", "scripts/WorkbenchGame/WorldEditor/SCR_WorldDataExportTool.c")]),
        ],
    },
    {
        "key": "selftest", "title": "Self-test", "module": "unittest", "doc": None, "results": None, "stderr_info": True,
        "desc": "The repository's own regression tests (test_*.py): the field map install, the foliage dependencies "
                "and the mortar test's terrain reader. Quick, and nothing is launched.",
        "cmds": [
            cmd("all", "Run the tests", "python -m unittest over every test_*.py beside rmt.py.",
                args=["discover", "-v", "-p", "test_*.py"]),
        ],
    },
]

# All categories use explicit target selection through labtest.py. Keep standalone CLIs available.
for tool in TOOLS:
    tool['selection'] = True
    if tool['key'] in ('firetest', 'blasttest', 'rockettest', 'bullettest', 'launchertest'):
        tool['desc'] = 'Test only the ticked baseline or installed-mod targets. Inspect the selection to choose resolved projectiles and validate dependencies. Results are kept in a separate folder for this selection.'
    elif tool['key'] == 'audible':
        tool['desc'] = 'Measure selected WAV samples from installed addons. Choose a calibrated shot level at 2 metres for reach estimates; results remain separate for each selection.'
    elif tool['key'] == 'pak':
        tool['desc'] = 'Search or read archives from the ticked installed addons, including Workshop mods.'
    for command in tool['cmds']:
        command['minutes'] = None
        if tool['key'] in ('rockettest', 'bullettest') and command['name'] == 'run':
            command['desc'] = 'Fly only the selected projectile pairings, one game run per wind. Runtime depends on selection size; completed successful blocks can be resumed.'
    if tool['key'] == 'firetest':
        for command in tool['cmds']:
            if command['name'] == 'plan': command['workbench'] = True
    for command in tool['cmds']:
        command['legacy_opts'] = command['opts']
        command['opts'] = [o for o in command['opts'] if o['flag'] not in ('--shells', '--out')
                           and not (tool['key'] == 'conflict' and o['flag'] is None)]
        if tool['key'] == 'conflict':
            command['opts'].append(opt('--map-id', 'Website map id (for a selected scenario)', 'text', '', 'Required when an explicit mod scenario cannot be matched to an installed terrain map.'))

BY_KEY = {t["key"]: t for t in TOOLS}


def runs_game(command, values):
    """Whether this command, with these option values, starts the game."""
    if not command["game"]:
        return False
    if command["folder_skips_game"]:
        return not any(values.get(i) for i, o in enumerate(command["opts"]) if o["flag"] is None)
    return True


def build(tool, command, values):
    """The wrapper arguments for rmt_gui.py: ['--script', file, ...] or ['--module', name, ...].
    values: option index -> value (str, int, float, or a list for shells)."""
    positional, flagged = [], []
    for i, o in enumerate(command.get("legacy_opts", command["opts"])):
        v = values.get(i, o["default"])
        if o["kind"] == "shells":
            v = ",".join(v or ())
            if not v or tuple(v.split(",")) == tuple(o["default"]):
                continue
        elif o["kind"] in ("int", "float"):
            if v is None or v == o["default"] or (o["kind"] == "int" and v == 0 and o["default"] == 0):
                continue
            v = str(v)
        else:
            v = (v or "").strip()
            if not v:
                continue
        if o["flag"] is None:
            positional.append(v)
        else:
            flagged += [o["flag"], v]
    if tool.get("module"):
        head = ["--module", tool["module"]]
        sub = [command["name"]] if tool["module"] != "unittest" else []
    else:
        head = ["--script", command["script"] or tool["script"]]
        sub = [] if command["script"] else [command["name"]]
    if tool.get("stderr_info"):
        head = ["--stderr-info"] + head
    return head + sub + list(command["args"]) + positional + flagged


def shown(args):
    """The same command as someone would type it in a terminal (from the repo folder)."""
    a = list(args)
    if a and a[0] == "--stderr-info":
        a = a[1:]
    if a[0] == "--module":
        head = ["python", "-m", a[1]]
    else:
        script = a[1].replace("/", os.sep)
        head = ["python", script] if os.sep not in script else \
            ["cd", os.path.dirname(script), "&&", "python", os.path.basename(script)]
    return " ".join(head + [f'"{x}"' if " " in x else x for x in a[2:]])


def selected_build(tool, command, values, selection, output, workbench=None):
    """Selected wrapper command; forwards supported form values without legacy fixed target lists."""
    args = ['--script', 'labtest.py', command['name'], '--tool', tool['key'], '--selection', selection, '--output', output]
    if workbench: args += ['--workbench', workbench]
    for i, option in enumerate(command['opts']):
        value = values.get(i, option['default'])
        if value is None or value == '': continue
        flag = option['flag']
        if flag is None:
            if tool['key'] == 'pak': flag = '--pattern' if command['name'] == 'list' else '--path'
            else:
                args.append(str(value)); continue
        args += [flag, str(value)]
    return (['--stderr-info']+args) if tool['key'] == 'selftest' else args
