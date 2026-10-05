"""Custom ballistics page; scans/inspection/flight work stays in the worker process."""
import json
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)


class BallisticsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.records = []
        self.inspected = None
        self.selected_record = None
        self.output = None
        layout = QVBoxLayout(self)
        title = QLabel('Weapons, vehicles and custom ballistics')
        title.setStyleSheet('font-size: 22px; font-weight: bold')
        layout.addWidget(title)
        intro = QLabel('1. Scan installed addons.  2. Select a weapon, vehicle or ammo prefab and inspect it.\n'
                       '3. Choose its projectile and launch-speed coefficient, then record flights in the game.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        row = QHBoxLayout()
        self.scan = QPushButton('Scan installed addons')
        self.scan.clicked.connect(self.scan_addons)
        row.addWidget(self.scan)
        self.addon = QComboBox()
        self.addon.addItem('All addons', None)
        self.addon.currentIndexChanged.connect(self.fill)
        row.addWidget(self.addon)
        self.kind = QComboBox()
        for label, key in [('Weapons, ammo and vehicles', None), ('Weapons', 'weapon'),
                           ('Ammunition', 'ammunition'), ('Vehicles', 'vehicle'), ('All prefabs', 'all')]:
            self.kind.addItem(label, key)
        self.kind.currentIndexChanged.connect(self.fill)
        row.addWidget(self.kind)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search weapon, calibre or prefab path')
        self.search.textChanged.connect(self.fill)
        row.addWidget(self.search, 1)
        layout.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Prefab', 'Addon', 'Type', 'Resource'])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.itemSelectionChanged.connect(self.selection_changed)
        self.tree.itemDoubleClicked.connect(lambda *_: self.inspect())
        layout.addWidget(self.tree, 2)
        self.inspect_button = QPushButton('Inspect selection / find ammunition')
        self.inspect_button.clicked.connect(self.inspect)
        self.inspect_button.setEnabled(False)
        layout.addWidget(self.inspect_button)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(140)
        self.details.setPlaceholderText('Inspection shows inherited physics values, source prefabs and referenced projectiles.')
        layout.addWidget(self.details)
        form = QFormLayout()
        self.projectile = QComboBox()
        self.projectile.currentIndexChanged.connect(self.projectile_changed)
        form.addRow('Projectile', self.projectile)
        self.coefficient = QDoubleSpinBox()
        self.coefficient.setRange(0.001, 10)
        self.coefficient.setDecimals(4)
        self.coefficient.setValue(1)
        self.coefficient.setToolTip('Ammo InitSpeed is multiplied by this. Select the actual muzzle BulletInitSpeedCoef; multiple vehicle guns may differ.')
        form.addRow('Launch-speed coefficient', self.coefficient)
        self.name = QLineEdit('custom-round')
        form.addRow('Dataset name', self.name)
        self.duration = QDoubleSpinBox()
        self.duration.setRange(3, 30)
        self.duration.setValue(10)
        self.duration.setSuffix(' seconds')
        form.addRow('Record each flight for', self.duration)
        self.height = QDoubleSpinBox()
        self.height.setRange(500, 20000)
        self.height.setValue(5000)
        self.height.setSuffix(' m above sea level')
        form.addRow('Launch height', self.height)
        self.world = QLineEdit('EmptyEden')
        form.addRow('Test world', self.world)
        self.wind = QCheckBox('Measure calm, crosswind, headwind and tailwind (5 runs)')
        self.wind.setChecked(True)
        form.addRow(self.wind)
        self.confirm_coefficient = QCheckBox('I verified the coefficient for the selected weapon / vehicle gun')
        form.addRow(self.confirm_coefficient)
        layout.addLayout(form)
        note = QLabel('Records direct projectile flight, not firing a complete vehicle or measuring its sights/dispersion.\n'
                      'Scripted, guided and unusual ammunition need separate in-game validation. Results go to the Data page’s output folder; base-game tables stay separate.')
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        self.run_button = QPushButton('Record custom ballistics')
        self.run_button.setObjectName('primary')
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self.run)
        row.addWidget(self.run_button)
        self.results = QPushButton('Open last results')
        self.results.clicked.connect(self.open_results)
        self.results.setEnabled(False)
        row.addWidget(self.results)
        layout.addLayout(row)
        self.win.worker.event.connect(self.on_event)

    def folder(self):
        from rmtlib import paths
        return os.path.join(self.win.data.out.text().strip() or paths.workspace(), 'ballistics')

    def command(self, command, extra=(), game=False):
        args = ['--script', 'customballistics.py', command, '--output',
                self.folder() if game else os.path.join(self.folder(), command+'.json')]
        wb = self.win.setup.workbench()
        if wb:
            args += ['--workbench', wb]
        args += list(extra)
        self.win.launch_script(args, 'Custom ballistics: '+command, game, self.folder())

    def scan_addons(self):
        self.command('scan')

    def fill(self, *_):
        self.tree.clear()
        query = self.search.text().strip().lower()
        addon, kind = self.addon.currentData(), self.kind.currentData()
        for record in self.records:
            if addon and record['addonGuid'] != addon:
                continue
            if kind is None and record['kind'] not in ('weapon', 'vehicle', 'ammunition'):
                continue
            if kind not in (None, 'all') and kind != record['kind']:
                continue
            if query and query not in (record['path']+' '+record['addon']).lower():
                continue
            item = QTreeWidgetItem([Path(record['path']).stem, record['addon'], record['kind'], record['resource']])
            item.setData(0, Qt.ItemDataRole.UserRole, record)
            self.tree.addTopLevelItem(item)

    def selection_changed(self):
        self.inspected = None
        self.selected_record = None
        self.projectile.clear()
        self.confirm_coefficient.setChecked(False)
        self.run_button.setEnabled(False)
        self.inspect_button.setEnabled(bool(self.tree.selectedItems()))

    def inspect(self):
        selected = self.tree.selectedItems()
        if not selected:
            return
        self.selected_record = selected[0].data(0, Qt.ItemDataRole.UserRole)
        record = self.selected_record
        extra = ['--resource', record['resource']]
        if record['addonGuid']:
            extra += ['--addon', record['addonGuid']]
        self.command('inspect', extra)

    def projectile_changed(self, *_):
        self.confirm_coefficient.setChecked(False)
        candidate = self.projectile.currentData()
        self.run_button.setEnabled(candidate is not None)
        if candidate:
            text = json.dumps({'selected': self.inspected['selected'], 'projectile': candidate,
                               'warnings': self.inspected['warnings'], 'note': self.inspected['note']}, indent=2)
            self.details.setPlainText(text)

    def on_event(self, event):
        try:
            if event.get('ballisticsCatalog'):
                self.records = json.loads(Path(event['ballisticsCatalog']).read_text(encoding='utf8'))
                self.addon.blockSignals(True)
                self.addon.clear()
                self.addon.addItem('All addons', None)
                groups = sorted({(r['addon'], r['addonGuid']) for r in self.records if r['addonGuid']})
                for label, guid in groups:
                    self.addon.addItem(label, guid)
                self.addon.blockSignals(False)
                self.fill()
                self.win.go('ballistics')
            if event.get('ballisticsInspection'):
                self.inspected = json.loads(Path(event['ballisticsInspection']).read_text(encoding='utf8'))
                self.projectile.clear()
                fields = self.inspected['selected']['fields'].get('BulletInitSpeedCoef', {}).get('values', [])
                self.coefficient.setValue(fields[0] if len(fields) == 1 else 1)
                self.details.setPlainText(json.dumps(self.inspected, indent=2))
                for candidate in self.inspected['projectiles']:
                    self.projectile.addItem(candidate['resource'], candidate)
                self.win.go('ballistics')
            if event.get('customBallistics'):
                self.output = event['customBallistics']
                self.results.setEnabled(True)
        except (OSError, ValueError) as e:
            self.details.setPlainText(f'Unable to read result: {e}')

    def run(self):
        projectile = self.projectile.currentData()
        if not projectile or not self.inspected:
            return
        if not self.confirm_coefficient.isChecked():
            QMessageBox.information(self, 'Custom ballistics', 'Verify the launch-speed coefficient and tick the confirmation. The wrong muzzle coefficient changes the results.')
            return
        blocking = self.win.setup.blocking()
        if blocking:
            QMessageBox.warning(self, 'Custom ballistics', 'Resolve the problems on Setup before recording flights.')
            return
        if QMessageBox.question(self, 'Custom ballistics', 'Open the game and record projectile flights? Leave the game window alone until the run finishes.') != QMessageBox.StandardButton.Yes:
            return
        selected = self.inspected['selected']
        extra = ['--resource', projectile['resource'], '--name', self.name.text().strip(),
                 '--coefficient', str(self.coefficient.value()), '--duration', str(self.duration.value()),
                 '--height', str(self.height.value()), '--world', self.world.text().strip(),
                 '--weapon', selected['resource']]
        if projectile['addonGuid']:
            extra += ['--addon', projectile['addonGuid']]
        if selected['addonGuid']:
            extra += ['--weapon-addon', selected['addonGuid']]
        if not self.wind.isChecked():
            extra += ['--calm-only']
        self.command('run', extra, True)

    def open_results(self):
        if self.output:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.output))
