"""Reforger Map Tools: the desktop app. Pick a world, tick the data you want, choose a folder, press Start.

Five pages, in the order a first run goes through them:
  Setup  what this PC has (rmtlib/detect.py), and the Workbench override
  World  every world the installed addons hold (rmtlib/addons.py; no Workbench launch needed), or a .ent on disk
  Data   what to make (rmtlib/products.py), where to put it, and whether to install it into the field map
  Run    the plan, live progress from the engine's heartbeat, the log, Cancel
  Runs   every export in the output folder: open it, bake it again, install it

All the work happens in a child process (`rmt.py --events run ...`, rmtgui/worker.py); this window only shows it.
"""

import glob
import json
import os
import sys
import time

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSpinBox, QSplitter, QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from rmtlib import addons, detect, paths, products
from rmtlib.fieldmap import MAP_IDS, default_field_map

from .worker import Worker

APP = "Reforger Map Tools"
OK, WARN, FAIL = QColor("#2e8b57"), QColor("#c88a00"), QColor("#c0392b")
STATE_COLOURS = {"ok": OK, "warn": WARN, "fail": FAIL, "done": OK, "failed": FAIL, "start": QColor("#2f6fb3"),
                 "skipped": QColor("#888888")}
STATE_TEXT = {"ok": "OK", "warn": "Check", "fail": "Problem"}


def heading(text):
    label = QLabel(text)
    f = label.font()
    f.setPointSize(f.pointSize() + 5)
    f.setBold(True)
    label.setFont(f)
    return label


def note(text):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setStyleSheet("color: palette(placeholder-text);")
    return label


def open_folder(path):
    if path and os.path.isdir(path):
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def folder_row(edit, parent, title):
    row = QHBoxLayout()
    row.addWidget(edit, 1)
    browse = QPushButton("Browse…")

    def pick():
        start = edit.text() or os.path.expanduser("~")
        d = QFileDialog.getExistingDirectory(parent, title, start)
        if d:
            edit.setText(os.path.normpath(d))
    browse.clicked.connect(pick)
    row.addWidget(browse)
    return row


def get_install(workbench=None):
    """The Steam install, or (None, message) when something is missing."""
    from rmtlib.steam import Install
    try:
        return Install(workbench or None), None
    except SystemExit as e:
        return None, str(e)


# ------------------------------------------------------------------------------------------------ Setup
class SetupPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.checks = []
        lay = QVBoxLayout(self)
        lay.addWidget(heading("Setup"))
        lay.addWidget(note("What this PC has. Everything here is found on its own; nothing is changed. Exports need "
                           "Steam running and both Workbench and the game closed."))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Check", "State", "Details"])
        self.tree.setRootIsDecorated(False)
        self.tree.setWordWrap(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.tree, 1)

        box = QGroupBox("Workbench (only if it isn't found)")
        form = QFormLayout(box)
        self.wb = QLineEdit(win.settings.value("workbench", ""))
        self.wb.setPlaceholderText("found through Steam")
        row = QHBoxLayout()
        row.addWidget(self.wb, 1)
        b = QPushButton("Browse…")
        b.clicked.connect(self.pick_workbench)
        row.addWidget(b)
        form.addRow("ArmaReforgerWorkbenchSteamDiag.exe", row)
        lay.addWidget(box)

        row = QHBoxLayout()
        again = QPushButton("Check again")
        again.clicked.connect(self.refresh)
        row.addWidget(again)
        row.addStretch(1)
        self.summary = QLabel()
        row.addWidget(self.summary)
        lay.addLayout(row)

    def pick_workbench(self):
        path, _ = QFileDialog.getOpenFileName(self, "Workbench", self.wb.text() or "C:\\",
                                              "Workbench (ArmaReforgerWorkbench*.exe)")
        if path:
            self.wb.setText(os.path.normpath(path))
            self.win.settings.setValue("workbench", self.wb.text())
            self.refresh()

    def workbench(self):
        return self.wb.text().strip() or None

    def refresh(self):
        self.win.settings.setValue("workbench", self.wb.text().strip())
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.checks = detect.report(self.workbench())
        finally:
            QApplication.restoreOverrideCursor()
        self.tree.clear()
        for c in self.checks:
            text = c["value"] + (f"\n{c['hint']}" if c["hint"] else "")
            item = QTreeWidgetItem([c["label"], STATE_TEXT[c["state"]], text])
            item.setForeground(1, QBrush(STATE_COLOURS[c["state"]]))
            if c["hint"]:
                item.setToolTip(2, c["hint"])
            self.tree.addTopLevelItem(item)
        bad = [c for c in self.checks if c["state"] == "fail"]
        self.summary.setText("Ready." if not bad else f"{len(bad)} problem(s) to fix before a run.")
        self.summary.setStyleSheet(f"color: {(FAIL if bad else OK).name()};")
        return self.checks

    def blocking(self):
        """Problems that stop a run right now (re-checked, since the game or Workbench may have been opened)."""
        return [c for c in self.refresh() if c["state"] == "fail"]


# ------------------------------------------------------------------------------------------------ World
class WorldPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.worlds = []
        self.disk_world = None
        lay = QVBoxLayout(self)
        lay.addWidget(heading("World"))
        lay.addWidget(note("Every world in the game and your downloaded mods, read from their files (Workbench isn't "
                           "started). A mod map brings the mods it depends on along. By default only each map's base "
                           "terrain is listed; game modes (Conflict, Game Master, ...) sit on the same terrain."))
        row = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter…")
        self.filter.textChanged.connect(self.fill)
        row.addWidget(self.filter, 1)
        self.show_all = QCheckBox("Show every world")
        self.show_all.toggled.connect(self.fill)
        row.addWidget(self.show_all)
        lay.addLayout(row)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["World", "Addon", "Source", "Resource"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setSortingEnabled(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemSelectionChanged.connect(self.selected_changed)
        self.tree.itemDoubleClicked.connect(lambda *_: self.win.go("data"))
        lay.addWidget(self.tree, 1)

        row = QHBoxLayout()
        refresh = QPushButton("Reload list")
        refresh.clicked.connect(self.load)
        row.addWidget(refresh)
        browse = QPushButton("Use a .ent file on disk…")
        browse.clicked.connect(self.browse)
        row.addWidget(browse)
        row.addStretch(1)
        self.choice = QLabel("No world chosen.")
        row.addWidget(self.choice)
        nxt = QPushButton("Next: choose data →")
        nxt.clicked.connect(lambda: self.win.go("data"))
        row.addWidget(nxt)
        lay.addLayout(row)

    def load(self):
        install, err = get_install(self.win.setup.workbench())
        if not install:
            self.worlds = []
            self.choice.setText(err)
            self.fill()
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.worlds = addons.list_worlds(install)
        finally:
            QApplication.restoreOverrideCursor()
        self.fill()

    def fill(self):
        want = self.filter.text().strip().lower()
        everything = self.show_all.isChecked()
        last = self.win.settings.value("world", "")
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        pick = None
        for w in self.worlds:
            if not everything and not (w["map"] and (w["terrain"] or w["source"] != "game")):
                continue
            if want and want not in (w["name"] + " " + w["addon"] + " " + w["resource"]).lower():
                continue
            source = {"game": "Arma Reforger", "workshop": "Workshop mod", "project": "Your project"}[w["source"]]
            item = QTreeWidgetItem([w["name"], w["addon"], source, w["resource"]])
            item.setData(0, Qt.ItemDataRole.UserRole, w)
            self.tree.addTopLevelItem(item)
            if w["resource"] == last:
                pick = item
        self.tree.setSortingEnabled(True)
        self.tree.sortItems(2, Qt.SortOrder.AscendingOrder)
        if pick:
            self.tree.setCurrentItem(pick)

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "A world file (.ent) in an addon folder", os.path.expanduser("~"),
                                              "World (*.ent)")
        if path:
            self.tree.clearSelection()
            self.disk_world = os.path.normpath(path)
            self.choice.setText(f"Chosen: {self.disk_world}")
            self.win.world_changed()

    def selected_changed(self):
        items = self.tree.selectedItems()
        if items:
            w = items[0].data(0, Qt.ItemDataRole.UserRole)
            self.disk_world = None
            self.choice.setText(f"Chosen: {w['name']} ({w['addon']})")
            self.win.settings.setValue("world", w["resource"])
            self.win.world_changed()

    def world(self):
        """(argument for rmt.py, display name, slug guess) or None."""
        if self.disk_world:
            name = os.path.splitext(os.path.basename(self.disk_world))[0]
            return self.disk_world, name, None
        items = self.tree.selectedItems()
        if not items:
            return None
        w = items[0].data(0, Qt.ItemDataRole.UserRole)
        from rmtlib.export import slug_of
        return w["resource"], w["name"], slug_of(w["resource"])


# ------------------------------------------------------------------------------------------------ Data
class DataPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        s = win.settings
        lay = QVBoxLayout(self)
        lay.addWidget(heading("Data"))
        self.world_label = QLabel()
        lay.addWidget(self.world_label)

        box = QGroupBox("What to make")
        grid = QVBoxLayout(box)
        self.boxes = {}
        saved = (s.value("products", "roads,los,places") or "").split(",")
        for key in products.ORDER:
            title, what, _, _, _, game = products.PRODUCTS[key]
            cb = QCheckBox(title + ("   (runs the game on screen)" if game else ""))
            cb.setChecked(key in saved)
            cb.toggled.connect(self.update_plan)
            grid.addWidget(cb)
            d = note(what)
            d.setContentsMargins(24, 0, 0, 4)
            grid.addWidget(d)
            self.boxes[key] = cb
        self.quick = QCheckBox("Quick test: only 2 chunks per job, to check that everything works before a full run")
        self.quick.setChecked(s.value("quick", "false") == "true")
        self.quick.toggled.connect(self.update_plan)
        grid.addWidget(self.quick)
        lay.addWidget(box)

        box = QGroupBox("Where it goes")
        form = QFormLayout(box)
        self.out = QLineEdit(s.value("workspace", "") or paths.workspace())
        form.addRow("Output folder", folder_row(self.out, self, "Output folder"))
        form.addRow("", note("Each run lands in <output folder>\\<world>\\<game build>\\: manifest.json and site\\ "
                             "(the data the website reads). The engine's raw export stays in its own profile "
                             "folder (Documents\\My Games\\ArmaReforgerWorkbench\\profile\\rmt): it can only write "
                             "there."))
        self.install = QCheckBox("Also install into the field map (arma-map's everon-map)")
        self.install.setChecked(s.value("install", "false") == "true")
        self.install.toggled.connect(self.update_plan)
        form.addRow(self.install)
        self.fieldmap = QLineEdit(s.value("fieldmap", "") or default_field_map(paths.REPO) or "")
        self.fieldmap.setPlaceholderText("the folder holding server.py")
        form.addRow("Field map folder", folder_row(self.fieldmap, self, "Field map folder (holding server.py)"))
        self.map_id = QLineEdit()
        self.map_id.setPlaceholderText("e.g. everon")
        form.addRow("Map id on the site", self.map_id)
        lay.addWidget(box)

        adv = QGroupBox("Advanced")
        adv.setCheckable(True)
        adv.setChecked(False)
        inner = QWidget()
        f2 = QFormLayout(inner)
        self.tile = QSpinBox()
        self.tile.setRange(50, 4000)
        self.tile.setValue(500)
        self.tile.setSuffix(" m")
        f2.addRow("Chunk size", self.tile)
        self.stall = QSpinBox()
        self.stall.setRange(60, 7200)
        self.stall.setValue(600)
        self.stall.setSuffix(" s")
        f2.addRow("Kill after no progress for", self.stall)
        self.retries = QSpinBox()
        self.retries.setRange(1, 10)
        self.retries.setValue(3)
        f2.addRow("Launches per job", self.retries)
        self.extra = QPlainTextEdit()
        self.extra.setPlaceholderText("Job settings, one NAME=VALUE per line (see docs/export-jobs.md), e.g.\n"
                                      "SatSpan=200\nFoliageLimit=3")
        self.extra.setMaximumHeight(80)
        f2.addRow("Settings", self.extra)
        v = QVBoxLayout(adv)
        v.addWidget(inner)
        inner.setVisible(False)
        adv.toggled.connect(inner.setVisible)
        lay.addWidget(adv)

        self.plan_label = note("")
        lay.addWidget(self.plan_label)
        lay.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.start = QPushButton("Start")
        self.start.setMinimumWidth(140)
        self.start.setDefault(True)
        self.start.clicked.connect(self.win.start_run)
        row.addWidget(self.start)
        lay.addLayout(row)

    def chosen(self):
        return [k for k, cb in self.boxes.items() if cb.isChecked()]

    def world_changed(self, world):
        if world:
            arg, name, slug = world
            self.world_label.setText(f"World: <b>{name}</b>")
            self.map_id.setText(MAP_IDS.get(slug, "") if slug else "")
            if not self.map_id.text():
                self.map_id.setText(name.lower())
        else:
            self.world_label.setText("World: <i>none chosen yet</i> (World page)")
        self.update_plan()

    def update_plan(self):
        chosen = self.chosen()
        install = self.install.isChecked()
        self.fieldmap.setEnabled(install)
        self.map_id.setEnabled(install)
        if not chosen and not install:
            self.plan_label.setText("Tick at least one thing to make.")
            self.start.setEnabled(False)
            return
        p = products.plan(chosen, install)
        added = [products.PRODUCTS[k][0] for k in p.products if k not in chosen]
        game = [s["label"] for s in p.steps if s["game"]]
        text = f"{len(p.steps)} steps: {len(p.jobs)} export jobs, {len(p.bakes)} bakes"
        if added:
            text += f". Also included because it's needed: {', '.join(added)}"
        if game:
            text += ". The game opens on screen for: " + ", ".join(game)
        if self.quick.isChecked():
            text += ". Quick test: 2 chunks per job"
        self.plan_label.setText(text + ".")
        self.start.setEnabled(self.win.world.world() is not None)

    def settings(self):
        out = []
        for line in self.extra.toPlainText().splitlines():
            line = line.strip()
            if line and "=" in line:
                out.append(line)
        return out

    def save(self):
        s = self.win.settings
        s.setValue("products", ",".join(self.chosen()))
        s.setValue("quick", "true" if self.quick.isChecked() else "false")
        s.setValue("workspace", self.out.text().strip())
        s.setValue("install", "true" if self.install.isChecked() else "false")
        s.setValue("fieldmap", self.fieldmap.text().strip())


# ------------------------------------------------------------------------------------------------ Run
class RunPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.items = {}
        self.started = None
        self.step_started = {}
        self.site = None
        self.errors = []
        lay = QVBoxLayout(self)
        lay.addWidget(heading("Run"))
        self.title = QLabel("Nothing running.")
        self.title.setWordWrap(True)
        lay.addWidget(self.title)

        split = QSplitter(Qt.Orientation.Vertical)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Step", "State", "Progress"])
        self.tree.setRootIsDecorated(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        split.addWidget(self.tree)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(20000)
        self.log.setFont(QFont("Consolas", 9))
        split.addWidget(self.log)
        split.setSizes([260, 340])
        lay.addWidget(split, 1)

        self.bar = QProgressBar()
        self.bar.setFormat("%v of %m steps")
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        self.clock = QLabel()
        row.addWidget(self.clock)
        row.addStretch(1)
        self.open_btn = QPushButton("Open output folder")
        self.open_btn.clicked.connect(lambda: open_folder(self.site or self.win.data.out.text()))
        row.addWidget(self.open_btn)
        self.save_btn = QPushButton("Save log…")
        self.save_btn.clicked.connect(self.save_log)
        row.addWidget(self.save_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel)
        row.addWidget(self.cancel_btn)
        lay.addLayout(row)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)

    # -- lifecycle
    def begin(self, title):
        self.items.clear()
        self.step_started.clear()
        self.tree.clear()
        self.log.clear()
        self.errors = []
        self.site = None
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.title.setText(title)
        self.started = time.time()
        self.cancel_btn.setEnabled(True)
        self.timer.start(1000)

    def finish(self, code):
        self.timer.stop()
        self.tick()
        self.cancel_btn.setEnabled(False)
        for item in self.items.values():
            if item.text(1) == "running":
                self.set_state(item, "failed" if code else "done")
        if code == -1:
            self.title.setText(self.title.text() + " — cancelled. Run it again to resume: finished jobs and chunks "
                               "are kept.")
        elif code == 0:
            self.title.setText(self.title.text() + " — finished.")
        else:
            msg = self.errors[-1] if self.errors else f"stopped (exit {code})"
            self.title.setText(self.title.text() + f" — failed: {msg}")

    def cancel(self):
        if QMessageBox.question(self, APP, "Stop the run? Workbench or the game is closed too. Run it again later to "
                                           "resume where it stopped.") == QMessageBox.StandardButton.Yes:
            self.append("info", "cancelling…")
            self.win.worker.cancel()

    def tick(self):
        if self.started:
            s = int(time.time() - self.started)
            self.clock.setText(f"Elapsed {s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}")

    def save_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save log", "rmt-log.txt", "Text (*.txt)")
        if path:
            with open(path, "w", encoding="utf8") as f:
                f.write(self.log.toPlainText())

    # -- events
    def append(self, level, text):
        if level == "error":
            self.log.appendHtml(f'<span style="color:{FAIL.name()}">{_esc(text)}</span>')
        else:
            self.log.appendPlainText(text)

    def set_state(self, item, state):
        text = {"start": "running", "done": "done", "failed": "failed", "skipped": "skipped"}.get(state, state)
        item.setText(1, text)
        item.setForeground(1, QBrush(STATE_COLOURS.get(state, QColor("#888888"))))
        self.bar.setValue(sum(1 for i in self.items.values() if i.text(1) in ("done", "failed", "skipped")))

    def on_event(self, ev):
        t = ev.get("t")
        if t == "log":
            self.append(ev.get("level", "info"), ev.get("text", ""))
        elif t == "plan":
            for s in ev["steps"]:
                item = QTreeWidgetItem([s["label"] + ("  (game)" if s.get("game") else ""), "waiting", ""])
                item.setForeground(1, QBrush(QColor("#888888")))
                self.tree.addTopLevelItem(item)
                self.items[s["id"]] = item
            self.bar.setRange(0, max(1, len(ev["steps"])))
        elif t == "step":
            item = self.items.get(ev["id"])
            if item is None:
                return
            if ev["state"] == "start":
                self.step_started[ev["id"]] = (time.time(), None)
            self.set_state(item, ev["state"])
        elif t == "progress":
            item = self.items.get(ev["id"])
            if item is None:
                return
            done, total = ev["done"], ev["total"]
            text = f"{done} / {total} {ev.get('unit', '')}"
            t0, first = self.step_started.get(ev["id"], (time.time(), None))
            if first is None:
                self.step_started[ev["id"]] = (time.time(), done)  # rate from here on (skipped chunks are free)
            elif done > first and total > done:
                rate = (time.time() - t0) / (done - first)
                left = int(rate * (total - done))
                text += f"   about {left // 60} min left" if left >= 60 else f"   about {left} s left"
            item.setText(2, text)
            if item.text(1) == "waiting":
                self.set_state(item, "start")
        elif t == "error":
            self.errors.append(ev.get("message", ""))
            self.append("error", "ERROR: " + ev.get("message", "") + (f"\n{ev['hint']}" if ev.get("hint") else ""))
        elif t == "result":
            if ev.get("site"):
                self.site = ev["site"]
            if ev.get("check"):
                c = ev["check"]
                self.append("info", f"Line of sight agrees with the engine on {100 * c['agree']:.1f}% of "
                                    f"{c['lines']:,} sight lines (terrain alone {100 * c['terrain']:.1f}%).")


def _esc(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ------------------------------------------------------------------------------------------------ Runs
def job_ok(m, job):
    st = (m.get("jobs", {}).get(job) or {}).get("status") or {}
    return st.get("result") in ("done", "partial")


def bakeable(m):
    parts = []
    if job_ok(m, "mapdata") or job_ok(m, "roads"):
        parts.append("roads")
    if all(job_ok(m, j) for j in ("terrain", "entities", "surface")):
        parts.append("los")
    if job_ok(m, "names"):
        parts.append("places")
    if job_ok(m, "satellite"):
        parts.append("satellite")
    if job_ok(m, "foliage"):
        parts.append("foliage")
        if "los" in parts:
            parts.append("plants")
    return parts


class RunsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.addWidget(heading("Runs"))
        self.where = note("")
        lay.addWidget(self.where)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["World", "Game build", "Updated", "Exported", "Baked"])
        self.tree.setRootIsDecorated(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.tree, 1)
        row = QHBoxLayout()
        for text, fn in (("Reload", self.load), ("Open folder", self.open), ("Open raw export", self.open_raw),
                         ("Bake again", self.rebake), ("Install into field map", self.install)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

    def load(self):
        ws = self.win.data.out.text().strip() or paths.workspace()
        self.where.setText(f"Every export in {ws}. Run the same world again from the Data page to resume one.")
        self.tree.clear()
        for path in sorted(glob.glob(os.path.join(ws, "*", "*", "manifest.json"))):
            try:
                with open(path, encoding="utf8") as f:
                    m = json.load(f)
            except (OSError, ValueError):
                continue
            site = os.path.join(os.path.dirname(path), "site")
            done = [j for j in m.get("jobs", {}) if job_ok(m, j)]
            baked = sorted(n for n in ("roads.json", "places.json", "los", "light", "tiles", "foliage", "plants",
                                       "foliage.json") if os.path.exists(os.path.join(site, n)))
            item = QTreeWidgetItem([m.get("world", "?").split("}", 1)[-1], m.get("gameBuild", "?"),
                                    (m.get("updated") or m.get("created") or "")[:16].replace("T", " "),
                                    ", ".join(done), ", ".join(baked)])
            item.setData(0, Qt.ItemDataRole.UserRole, (path, m))
            self.tree.addTopLevelItem(item)

    def current(self):
        items = self.tree.selectedItems()
        if not items:
            QMessageBox.information(self, APP, "Pick a run first.")
            return None
        return items[0].data(0, Qt.ItemDataRole.UserRole)

    def open(self):
        cur = self.current()
        if cur:
            open_folder(os.path.dirname(cur[0]))

    def open_raw(self):
        cur = self.current()
        if cur:
            open_folder(cur[1].get("raw"))

    def rebake(self):
        cur = self.current()
        if not cur:
            return
        parts = bakeable(cur[1])
        if not parts:
            QMessageBox.information(self, APP, "This run has nothing finished to bake yet.")
            return
        self.win.launch(["bake", cur[1]["slug"], "--parts", ",".join(parts)],
                        f"Baking {cur[1]['world']}: {', '.join(parts)}",
                        steps=[{"id": f"bake:{p}", "label": products.BAKE_LABELS[p]} for p in parts])

    def install(self):
        cur = self.current()
        if not cur:
            return
        d = self.win.data
        target = d.fieldmap.text().strip()
        map_id = MAP_IDS.get(cur[1]["slug"]) or d.map_id.text().strip()
        if not target or not os.path.isfile(os.path.join(target, "server.py")):
            QMessageBox.warning(self, APP, "Set the field map folder (the one holding server.py) on the Data page.")
            return
        if not map_id:
            QMessageBox.warning(self, APP, "Set the map id on the Data page.")
            return
        self.win.launch(["fieldmap", cur[1]["slug"], "--to", target, "--as", map_id],
                        f"Installing {cur[1]['world']} into {target} as '{map_id}'",
                        steps=[{"id": "install", "label": "Install into the field map"}])


# ------------------------------------------------------------------------------------------------ window
class MainWindow(QMainWindow):
    PAGES = [("setup", "1  Setup"), ("world", "2  World"), ("data", "3  Data"), ("run", "4  Run"), ("runs", "Runs")]

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP)
        self.resize(1100, 760)
        self.settings = QSettings("ReforgerMapTools", "ReforgerMapTools")
        self.worker = Worker(self)

        self.setup = SetupPage(self)
        self.world = WorldPage(self)
        self.data = DataPage(self)
        self.run = RunPage(self)
        self.runs = RunsPage(self)
        self.pages = {"setup": self.setup, "world": self.world, "data": self.data, "run": self.run, "runs": self.runs}

        self.nav = QListWidget()
        self.nav.setFixedWidth(150)
        self.nav.setFrameShape(QFrame.Shape.NoFrame)
        self.stack = QStackedWidget()
        for key, label in self.PAGES:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.nav.addItem(item)
            self.stack.addWidget(self.pages[key])
        self.nav.currentRowChanged.connect(self.page_changed)
        body = QWidget()
        h = QHBoxLayout(body)
        h.addWidget(self.nav)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(body)

        self.worker.event.connect(self.run.on_event)
        self.worker.output.connect(self.run.append)
        self.worker.finished.connect(self.run_finished)

        QTimer.singleShot(0, self.first_load)

    def first_load(self):
        checks = self.setup.refresh()
        install, _ = get_install(self.setup.workbench())
        if install:
            from rmtlib.workbench import restore_video_settings
            try:
                n = restore_video_settings(install.game_profile, log=lambda *_: None)
                if n:
                    self.statusBar().showMessage("Put back the game's screen settings from an interrupted run.", 10000)
            except OSError:
                pass
        self.world.load()
        self.world_changed()
        self.go("setup" if not detect.ready(checks) else ("data" if self.world.world() else "world"))

    def go(self, key):
        self.nav.setCurrentRow([k for k, _ in self.PAGES].index(key))

    def page_changed(self, row):
        self.stack.setCurrentIndex(row)
        key = self.PAGES[row][0]
        if key == "runs":
            self.runs.load()
        if key == "data":
            self.data.update_plan()

    def world_changed(self):
        self.data.world_changed(self.world.world())

    # -- running
    def start_run(self):
        world = self.world.world()
        if not world:
            QMessageBox.information(self, APP, "Choose a world first.")
            self.go("world")
            return
        d = self.data
        chosen = d.chosen()
        install = d.install.isChecked()
        if not chosen and not install:
            return
        out = d.out.text().strip()
        if not out:
            QMessageBox.warning(self, APP, "Choose an output folder.")
            return
        if install:
            if not os.path.isfile(os.path.join(d.fieldmap.text().strip(), "server.py")):
                QMessageBox.warning(self, APP, "The field map folder must be the one holding server.py.")
                return
            if not d.map_id.text().strip():
                QMessageBox.warning(self, APP, "Give the map an id for the site (lower case, e.g. everon).")
                return
        blocking = self.setup.blocking()
        if blocking:
            QMessageBox.warning(self, APP, "Fix these first (Setup page):\n\n" +
                                "\n".join(f"• {c['label']}: {c['hint'] or c['value']}" for c in blocking))
            self.go("setup")
            return
        plan = products.plan(chosen, install)
        game = [s["label"] for s in plan.steps if s["game"]]
        if game and QMessageBox.question(
                self, APP, "The game will open on screen and run by itself for: " + ", ".join(game) +
                ".\n\nLeave the PC alone meanwhile (no other 3D work, don't click into the game window). A large map "
                "takes hours. Start?") != QMessageBox.StandardButton.Yes:
            return
        os.makedirs(out, exist_ok=True)
        d.save()
        arg, name, _ = world
        # install on its own still needs what it copies (products.plan adds that)
        args = ["run", arg, "--products", ",".join(chosen or products.INSTALL_NEEDS), "--tile", str(d.tile.value()),
                "--stall", str(d.stall.value()), "--retries", str(d.retries.value())]
        if d.quick.isChecked():
            args += ["--max-chunks", "2"]
        for s in d.settings():
            args += ["--set", s]
        if install:
            args += ["--install", "--to", d.fieldmap.text().strip(), "--as", d.map_id.text().strip()]
        self.launch(args, f"{name}: {', '.join(products.PRODUCTS[p][0] for p in plan.products)}")

    def launch(self, args, title, steps=None):
        if self.worker.running():
            QMessageBox.information(self, APP, "A run is already going (Run page).")
            self.go("run")
            return
        self.run.begin(title)
        if steps:
            self.run.on_event({"t": "plan", "steps": steps})
        self.data.start.setEnabled(False)
        self.go("run")
        self.worker.start(args, self.data.out.text().strip() or paths.workspace(), self.setup.workbench())

    def run_finished(self, code):
        self.run.finish(code)
        self.data.update_plan()
        self.statusBar().showMessage("Finished." if code == 0 else "Cancelled." if code == -1 else "Failed.", 15000)

    def closeEvent(self, e):
        if self.worker.running():
            if QMessageBox.question(self, APP, "A run is going. Stop it and quit? (Run it again later to resume.)") \
                    != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self.worker.cancel()
        e.accept()


def main(argv=None):
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName(APP)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    return app.exec()
