"""Installed-mod target selection shared by every Labs category."""
import hashlib
import json
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit,
    QPushButton, QTreeWidget, QTreeWidgetItem, QFileDialog, QCheckBox, QDoubleSpinBox, QDialog, QDialogButtonBox)
from rmtlib import paths, labselection


class LabTargets(QWidget):
    changed = Signal()
    def __init__(self, page):
        super().__init__(); self.page = page; self.records = {}; self.selected = {}; self.projectile_filters = {}; self.key = 'conflict'; self.latest = None
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel('Test targets (tick the items to test; installed mods are included after scanning)'))
        row = QHBoxLayout(); button = QPushButton('Scan installed targets'); button.clicked.connect(self.scan); row.addWidget(button)
        self.addon = QComboBox(); self.addon.currentIndexChanged.connect(self.fill); row.addWidget(self.addon)
        self.search = QLineEdit(); self.search.setPlaceholderText('Filter targets / resource paths'); self.search.textChanged.connect(self.fill); row.addWidget(self.search, 1)
        layout.addLayout(row)
        self.tree = QTreeWidget(); self.tree.setHeaderLabels(['Test item', 'Addon', 'Type']); self.tree.setMinimumHeight(140); self.tree.setMaximumHeight(220)
        self.tree.itemChanged.connect(self.tick); layout.addWidget(self.tree)
        row = QHBoxLayout()
        for title, action in [('Select visible', self.select_visible), ('Clear selection', self.clear), ('Save selection', self.save), ('Load selection', self.load)]:
            button = QPushButton(title); button.clicked.connect(action); row.addWidget(button)
        layout.addLayout(row)
        row = QHBoxLayout(); self.manual = QCheckBox('Override launch coefficient'); self.manual.toggled.connect(self.changed.emit); row.addWidget(self.manual)
        self.manual.setToolTip('For a weapon with several muzzles, explicitly choose the coefficient belonging to the projectile being tested.')
        self.coef = QDoubleSpinBox(); self.coef.setRange(.001, 10); self.coef.setDecimals(4); self.coef.setValue(1); self.coef.valueChanged.connect(self.changed.emit); row.addWidget(self.coef)
        self.level = QDoubleSpinBox(); self.level.setRange(-100, 20); self.level.setDecimals(1); self.level.setValue(-15.5); self.level.setSuffix(' LUFS at 2 m'); self.level.setToolTip('Calibrated shot level at 2 metres; WAV loudness alone does not establish an in-game hearing distance.'); self.level.valueChanged.connect(self.changed.emit); row.addWidget(self.level)
        self.angle = QDoubleSpinBox(); self.angle.setRange(-10, 10); self.angle.setDecimals(3); self.angle.setSuffix(' degrees launch above bore'); self.angle.setToolTip("Verify the selected launcher's launch-above-bore angle; zero is an explicit initial assumption."); self.angle.valueChanged.connect(self.changed.emit); row.addWidget(self.angle)
        layout.addLayout(row)
        row = QHBoxLayout(); self.dataset = QLineEdit(); self.dataset.setPlaceholderText('Optional measured flight JSON for check / launcher tests'); self.dataset.textChanged.connect(self.changed.emit); row.addWidget(self.dataset, 1)
        button = QPushButton('Choose measured dataset'); button.clicked.connect(self.browse_data); row.addWidget(button); layout.addLayout(row); self.data_row = row
        self.mortar = QComboBox(); self.mortar.currentIndexChanged.connect(self.changed.emit); layout.addWidget(self.mortar)
        self.prepare_button = QPushButton('Inspect selected targets / validate dependencies')
        self.prepare_button.clicked.connect(self.prepare); layout.addWidget(self.prepare_button)
        self.note = QLabel('Nothing selected. Empty selection never runs every installed asset.'); self.note.setWordWrap(True); layout.addWidget(self.note)
        self.page.win.worker.event.connect(self.on_event)

    def folder(self):
        return Path(self.page.win.data.out.text().strip() or paths.workspace())/'labs'

    def scan(self):
        args = ['--script', 'labtest.py', 'catalog', '--output', str(self.folder())]
        wb = self.page.win.setup.workbench()
        if wb: args += ['--workbench', wb]
        self.page.win.launch_script(args, 'Labs: scan installed test targets', False, str(self.folder()))

    def prepare(self):
        if not self.request()['targets']:
            self.note.setText('Tick at least one target first.'); return
        args = ['--script', 'labtest.py', 'prepare', '--tool', self.key, '--selection', self.selection_file(write=True), '--output', str(self.folder())]
        wb = self.page.win.setup.workbench()
        if wb: args += ['--workbench', wb]
        self.page.win.launch_script(args, 'Labs: inspect selected targets', False, str(self.folder()))

    def set_tool(self, key):
        self.key = key
        self.prepare_button.setVisible(key in labselection.LIVE_TOOLS)
        if key not in self.records: self.records[key] = labselection.legacy_targets(key)
        self.selected.setdefault(key, set()); self.search.clear()
        previous = self.mortar.currentData(); self.mortar.blockSignals(True); self.mortar.clear()
        self.mortar.addItem('Mortar weapon for directly selected shells (choose if needed)', None)
        for record in self.records.get('firetest', []):
            if record.get('kind') == 'weapon': self.mortar.addItem(record['name']+' / '+record['addon'], record['id'])
        index = self.mortar.findData(previous); self.mortar.setCurrentIndex(max(0, index)); self.mortar.blockSignals(False)
        self.mortar.setVisible(key == 'firetest')
        self.manual.setVisible(key in ('bullettest', 'rockettest')); self.coef.setVisible(key in ('bullettest', 'rockettest'))
        self.level.setVisible(key == 'audible'); self.angle.setVisible(key == 'launchertest')
        self.dataset.setVisible(key in ('bullettest', 'rockettest', 'launchertest'))
        for i in range(self.data_row.count()): self.data_row.itemAt(i).widget().setVisible(key in ('bullettest', 'rockettest', 'launchertest'))
        self.addon.blockSignals(True); self.addon.clear(); self.addon.addItem('All related addons', None)
        for name, guid in sorted({(r['addon'], r['addonGuid']) for r in self.records[key]}): self.addon.addItem(name, guid)
        self.addon.blockSignals(False); self.fill()

    def fill(self, *_):
        self.tree.blockSignals(True); self.tree.clear(); addon = self.addon.currentData(); query = self.search.text().lower().strip()
        for record in self.records.get(self.key, []):
            if addon and addon != record['addonGuid']: continue
            if query and query not in json.dumps(record).lower(): continue
            row = QTreeWidgetItem([record.get('name', record['id']), record['addon'], record.get('kind', record.get('worldKind', 'world'))])
            row.setData(0, Qt.ItemDataRole.UserRole, record); row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(0, Qt.CheckState.Checked if record['id'] in self.selected.get(self.key, set()) else Qt.CheckState.Unchecked)
            row.setToolTip(0, record.get('resource', record['id'])); self.tree.addTopLevelItem(row)
        for col in (0, 1): self.tree.resizeColumnToContents(col)
        self.tree.blockSignals(False); self.notify()

    def tick(self, item, column):
        if column: return
        self.projectile_filters.pop(self.key, None)
        target = item.data(0, Qt.ItemDataRole.UserRole)['id']; selected = self.selected.setdefault(self.key, set())
        if item.checkState(0) == Qt.CheckState.Checked: selected.add(target)
        else: selected.discard(target)
        self.notify()

    def notify(self):
        count = len(self.selected.get(self.key, set()))
        self.note.setText(f'{count} targets selected, including any hidden by the current filter. Weapon/vehicle inspection resolves their ammunition; ambiguous muzzle coefficients stop the test.')
        self.changed.emit()

    def select_visible(self):
        for i in range(self.tree.topLevelItemCount()): self.tree.topLevelItem(i).setCheckState(0, Qt.CheckState.Checked)

    def clear(self):
        self.selected[self.key] = set(); self.projectile_filters.pop(self.key, None); self.fill()

    def request(self):
        req = {'tool': self.key, 'targets': sorted(self.selected.get(self.key, set()))}
        if self.key in self.projectile_filters: req['projectiles'] = self.projectile_filters[self.key]
        if self.key == 'firetest' and self.mortar.currentData(): req['mortarWeapon'] = self.mortar.currentData()
        if self.key in ('bullettest', 'rockettest') and self.manual.isChecked(): req['coefficient'] = self.coef.value()
        if self.key == 'audible': req['soundLevelLUFS'] = self.level.value()
        if self.key == 'launchertest': req['launchAngleDegrees'] = self.angle.value()
        if self.key in ('bullettest', 'rockettest', 'launchertest') and self.dataset.text().strip(): req['dataset'] = self.dataset.text().strip()
        return req

    def selection_file(self, write=False):
        request = self.request(); sig = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()[:16]
        file = self.folder()/'selections'/(self.key+'-'+sig+'.json')
        if write:
            file.parent.mkdir(parents=True, exist_ok=True); file.write_text(json.dumps(request, indent=2)+'\n', encoding='utf8')
        return str(file)

    def save(self):
        file, _ = QFileDialog.getSaveFileName(self, 'Save Labs selection', self.key+'-selection.json', 'JSON (*.json)')
        if file: Path(file).write_text(json.dumps(self.request(), indent=2)+'\n', encoding='utf8')

    def load(self):
        file, _ = QFileDialog.getOpenFileName(self, 'Load Labs selection or saved run selection.json', '', 'JSON (*.json)')
        if not file: return
        try:
            req = json.loads(Path(file).read_text(encoding='utf8'))
            if req['tool'] != self.key: raise ValueError('Selection belongs to another test category')
            self.selected[self.key] = set(req['targets'])
            if 'projectiles' in req: self.projectile_filters[self.key] = req['projectiles']
            else: self.projectile_filters.pop(self.key, None)
            for target in req['targets']:
                if target not in {r['id'] for r in self.records.get(self.key, [])}:
                    self.records.setdefault(self.key, []).append({'id': target, 'name': target, 'addon': 'Saved selection (rescan to verify)', 'addonGuid': 'saved', 'kind': 'saved'})
            self.manual.setChecked(req.get('coefficient') is not None); self.coef.setValue(req.get('coefficient', 1))
            self.level.setValue(req.get('soundLevelLUFS', -15.5)); self.angle.setValue(req.get('launchAngleDegrees', 0)); self.dataset.setText(req.get('dataset', '')); self.set_tool(self.key)
            if req.get('mortarWeapon'):
                if self.mortar.findData(req['mortarWeapon']) < 0:
                    self.mortar.addItem('Saved mortar weapon (rescan to verify)', req['mortarWeapon'])
                self.mortar.setCurrentIndex(self.mortar.findData(req['mortarWeapon']))
        except (OSError, ValueError, KeyError, TypeError) as e: self.note.setText(str(e))

    def browse_data(self):
        file, _ = QFileDialog.getOpenFileName(self, 'Measured flight dataset', '', 'JSON (*.json)')
        if file: self.dataset.setText(file)

    def choose_projectiles(self, report):
        if report['tool'] != self.key: return
        dialog = QDialog(self); dialog.setWindowTitle('Choose the resolved projectile / mortar-shell pairings'); dialog.resize(1000, 450)
        layout = QVBoxLayout(dialog); layout.addWidget(QLabel('Only ticked pairings will be tested. Multiple vehicle muzzles require a verified coefficient.'))
        tree = QTreeWidget(); tree.setHeaderLabels(['Pairing / projectile', 'Coefficient', 'Prefab']); layout.addWidget(tree)
        chosen = set(self.projectile_filters.get(self.key, []))
        for item in report['items']:
            row = QTreeWidgetItem([item['name'], str(item['coefficient']), item['prefab']]); row.setData(0, Qt.ItemDataRole.UserRole, item['selectionId'])
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(0, Qt.CheckState.Checked if not chosen or item['selectionId'] in chosen else Qt.CheckState.Unchecked)
            tree.addTopLevelItem(row)
        tree.resizeColumnToContents(0); tree.resizeColumnToContents(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.projectile_filters[self.key] = [tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) for i in range(tree.topLevelItemCount())
                                                if tree.topLevelItem(i).checkState(0) == Qt.CheckState.Checked]
            self.note.setText(f'{len(self.projectile_filters[self.key])} resolved projectile pairings selected.'); self.changed.emit()

    def on_event(self, event):
        try:
            if event.get('labCatalog'):
                self.records = json.loads(Path(event['labCatalog']).read_text(encoding='utf8')); self.set_tool(self.key); self.page.win.go('labs')
            if event.get('labPrepared'):
                report = json.loads(Path(event['labPrepared']).read_text(encoding='utf8'))
                self.note.setText(f'Resolved {len(report["items"])} projectile targets; loaded mod dependencies: '+(', '.join(report['guids']) or 'base game')+'. See '+event['labPrepared'])
                self.page.win.go('labs'); self.choose_projectiles(report)
            if event.get('labResults'):
                self.latest = event['labResults']; self.note.setText('Results: '+self.latest)
        except (OSError, ValueError, KeyError) as e: self.note.setText(str(e))
