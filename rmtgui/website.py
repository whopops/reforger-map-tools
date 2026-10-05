"""Website dataset inventory and the missing reference/calibration producers."""
import json
from pathlib import Path
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QHeaderView, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)
from rmtlib import paths, webdata


class WebsiteDataPage(QWidget):
    def __init__(self, win):
        super().__init__(); self.win = win; self.output = None
        layout = QVBoxLayout(self)
        title = QLabel('All website data'); title.setStyleSheet('font-size:22px;font-weight:bold'); layout.addWidget(title)
        note = QLabel('The producers for arma-map’s game data live here. Map jobs are on Data, flight/sound measurements on Labs,\n'
                      'custom ammunition on Ballistics, and artwork/calibration on Sights. Audit checks the website’s current static/data files.\n'
                      'Select the application folder containing server.py on Data; production rooms and caches are runtime state.')
        note.setWordWrap(True); layout.addWidget(note)
        self.tree = QTreeWidget(); self.tree.setHeaderLabels(['Website input', 'Producer', 'Run from / inventory']); self.tree.setMinimumHeight(360)
        layout.addWidget(self.tree)
        for name, _, producer, gui in webdata.INPUTS:
            self.tree.addTopLevelItem(QTreeWidgetItem([name, producer, gui]))
        self.add_embedded_rows()
        self.size_columns()
        row = QHBoxLayout()
        button = QPushButton('Audit selected website'); button.clicked.connect(lambda: self.run('audit')); row.addWidget(button)
        for title, page in [('Map data', 'data'), ('Measurements', 'labs'), ('Custom ballistics', 'ballistics'), ('Sight sketches', 'sights')]:
            button = QPushButton(title); button.clicked.connect(lambda checked=False, key=page: self.win.go(key)); row.addWidget(button)
        layout.addLayout(row)
        self.action = QComboBox()
        for label, key in [('Mortar reference tables + shell physics (Workbench)', 'mortar'), ('Mortar plan + physics only', 'mortar-plan'),
                           ('Blast summary → website radii', 'blast'), ('Muzzle study → mortar dispersion constants', 'barrel'),
                           ('Construction registry membership (read only)', 'construction'),
                           ('Export curated website recipes + legacy sight sketches', 'recipes')]:
            self.action.addItem(label, key)
        layout.addWidget(self.action)
        row = QHBoxLayout(); self.input = QLineEdit(); self.input.setPlaceholderText('Blast summary.json or muzzle-study run folder (only for those two actions)')
        row.addWidget(self.input, 1); button = QPushButton('Browse input'); button.clicked.connect(self.browse); row.addWidget(button); layout.addLayout(row)
        row = QHBoxLayout(); button = QPushButton('Produce selected dataset'); button.clicked.connect(lambda: self.run(self.action.currentData())); row.addWidget(button)
        button = QPushButton('Conflict references (Labs)'); button.clicked.connect(self.conflict); row.addWidget(button)
        button = QPushButton('Open latest output'); button.clicked.connect(self.open_output); row.addWidget(button); layout.addLayout(row)
        self.status = QLabel('Outputs go to the Data output folder / website-data. Review before installing them in arma-map.\n'
                             'Curated recipes retain known cave coordinates, tree colours and embedded website values with snapshot provenance.'); self.status.setWordWrap(True)
        layout.addWidget(self.status); self.win.worker.event.connect(self.on_event)

    def size_columns(self):
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setStretchLastSection(True)

    def add_embedded_rows(self):
        for name, producer, workflow in [
            ('Mortar physics / dispersion', 'rmtlib/webdata.py', 'Mortar tables; Labs barrel study + conversion'),
            ('Blast radii', 'blasttest.py / webdata.py', 'Labs blast measurement + summary conversion'),
            ('Sound reach', 'audible/audible3.py', 'Labs: Gunshot audibility steps 1 and 2'),
            ('Construction roles', 'rmtlib/webdata.py', 'Construction registry + curated recipes'),
            ('Caves / tree colours', 'recipes/website-calibration.json', 'Curated recipe export; reviewed manual values'),
            ('Legacy sight definitions', 'rmtlib/reticles.py', 'Curated recipe export; 16 SVG sketches')]:
            self.tree.addTopLevelItem(QTreeWidgetItem([name, producer, workflow]))

    def folder(self):
        return Path(self.win.data.out.text().strip() or paths.workspace())/'website-data'

    def browse(self):
        if self.action.currentData() == 'barrel':
            path = QFileDialog.getExistingDirectory(self, 'Muzzle-study run folder')
        else:
            path, _ = QFileDialog.getOpenFileName(self, 'Blast summary', '', 'JSON (*.json)')
        if path:
            self.input.setText(path)

    def run(self, action):
        args = ['--script', 'webdata.py', action, '--output', str(self.folder())]
        if action == 'audit':
            site = self.win.data.fieldmap.text().strip()
            if not site:
                QMessageBox.information(self, 'Website audit', 'Set the application folder containing server.py on Data.'); return
            args += ['--site', site]
        if action in ('blast', 'barrel'):
            if not self.input.text().strip():
                QMessageBox.information(self, 'Website data', 'Choose a completed measurement input first.'); return
            args += ['--input', self.input.text().strip()]
        if action == 'mortar':
            if self.win.setup.blocking():
                QMessageBox.warning(self, 'Mortar tables', 'Resolve the Setup problems and close Workbench/the game first.'); return
            if QMessageBox.question(self, 'Mortar tables', 'Launch Workbench to look up the game’s mortar firing tables?') != QMessageBox.StandardButton.Yes:
                return
        wb = self.win.setup.workbench()
        if wb:
            args += ['--workbench', wb]
        self.win.launch_script(args, 'Website data: '+action, False, str(self.folder()))

    def conflict(self):
        from . import labs
        self.win.labs.list.setCurrentRow(next(i for i, t in enumerate(labs.TOOLS) if t['key'] == 'conflict')); self.win.go('labs')

    def open_output(self):
        if self.output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.output))

    def on_event(self, event):
        try:
            if event.get('websiteAudit'):
                report = json.loads(Path(event['websiteAudit']).read_text(encoding='utf8')); self.tree.clear()
                for row in report['inputs']:
                    self.tree.addTopLevelItem(QTreeWidgetItem([row['name'], row['producer'], f'{row["files"]} files / {row["bytes"]/1e6:.1f} MB · {row["gui"]}']))
                self.add_embedded_rows(); self.size_columns()
                self.status.setText('Unknown inputs: '+(', '.join(report['unknown']) or 'none')+'\nAudit checks coverage; rerun measurements to establish freshness.')
                self.win.go('website')
            if event.get('websiteData'):
                self.output = event['websiteData']
                if not event.get('websiteAudit'):
                    self.status.setText('Produced '+self.output)
                self.win.go('website')
        except (OSError, ValueError, KeyError) as e:
            self.status.setText(str(e))
