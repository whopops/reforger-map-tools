"""Sight discovery, original-pixel calibration and sketch export."""
import json
from pathlib import Path
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPainter, QPixmap, QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)
from rmtlib import sights
from rmtlib.ballistics import write_json


class ReticlePreview(QWidget):
    clicked = Signal(float, float)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(320)
        self.image = QPixmap()
        self.dimensions = (1024, 1024)
        self.aim = None; self.bore = None
        self.box = None

    def load(self, path, width, height):
        self.image = QPixmap(path) if path else QPixmap()
        self.dimensions = (width, height); self.update()

    def paintEvent(self, event):
        from PySide6.QtCore import QRectF
        painter = QPainter(self); painter.fillRect(self.rect(), QColor('#263641'))
        w, h = self.dimensions
        k = min(self.width()/w, self.height()/h)
        x, y = (self.width()-w*k)/2, (self.height()-h*k)/2
        self.box = (x, y, k)
        if not self.image.isNull():
            painter.drawPixmap(QRectF(x, y, w*k, h*k), self.image, QRectF(self.image.rect()))
        else:
            painter.setPen(QColor('#e8edf0'))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'No 2D texture: import an image or choose a schematic')
        for point, color in ((self.aim, '#ffcf40'), (self.bore, '#50dbff')):
            if point:
                px, py = x+point[0]*k, y+point[1]*k
                painter.setPen(QColor(color)); painter.drawLine(int(px-8), int(py), int(px+8), int(py))
                painter.drawLine(int(px), int(py-8), int(px), int(py+8))

    def mousePressEvent(self, event):
        if self.box:
            x, y, k = self.box; pos = event.position()
            px, py = (pos.x()-x)/k, (pos.y()-y)/k
            if 0 <= px <= self.dimensions[0] and 0 <= py <= self.dimensions[1]:
                self.clicked.emit(px, py)


class SightsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win; self.records = []; self.report = None; self.spec = None; self.output = None
        layout = QVBoxLayout(self)
        title = QLabel('Sights and reticle sketches'); title.setStyleSheet('font-size:22px;font-weight:bold')
        layout.addWidget(title)
        intro = QLabel('Scan game and Workshop optics, weapon iron sights and vehicle sights. Extract the real 2D reticle,\n'
                       'select its sight component, calibrate in original pixels and export a website package. No game launch needed.')
        intro.setWordWrap(True); layout.addWidget(intro)
        row = QHBoxLayout(); button = QPushButton('Scan sights'); button.clicked.connect(lambda: self.command('scan'))
        row.addWidget(button)
        self.addon = QComboBox(); self.addon.addItem('All addons', None); self.addon.currentIndexChanged.connect(self.fill)
        row.addWidget(self.addon)
        self.type_filter = QComboBox()
        for label, key in [('All sight candidates', None), ('Optics', 'optic'), ('Weapons', 'weapon'), ('Vehicles', 'vehicle')]:
            self.type_filter.addItem(label, key)
        self.type_filter.currentIndexChanged.connect(self.fill); row.addWidget(self.type_filter)
        self.search = QLineEdit(); self.search.setPlaceholderText('Search optic, weapon or vehicle'); self.search.textChanged.connect(self.fill)
        row.addWidget(self.search, 1); layout.addLayout(row)
        self.tree = QTreeWidget(); self.tree.setHeaderLabels(['Prefab', 'Addon', 'Type', 'Resource']); self.tree.setMinimumHeight(180)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.itemDoubleClicked.connect(lambda *_: self.inspect()); layout.addWidget(self.tree)
        row = QHBoxLayout()
        for label, action in [('Extract selected sight', self.inspect), ('Load saved calibration', self.load), ('Import reticle image', self.import_image)]:
            button = QPushButton(label); button.clicked.connect(action); row.addWidget(button)
        layout.addLayout(row)
        self.component = QComboBox(); self.component.currentIndexChanged.connect(self.choose_component)
        layout.addWidget(self.component)
        self.note = QLabel('Select a prefab to see its inherited zeroing and scale.'); self.note.setWordWrap(True); layout.addWidget(self.note)
        self.preview = ReticlePreview(); self.preview.clicked.connect(self.click_point); layout.addWidget(self.preview)
        row = QHBoxLayout(); self.click_mode = QComboBox()
        for label in ('Click to set aiming point (yellow)', 'Click to set bore point (blue)', 'Click to set selected range mark'):
            self.click_mode.addItem(label)
        row.addWidget(self.click_mode)
        button = QPushButton('Use aiming point as bore point'); button.clicked.connect(self.same_bore); row.addWidget(button)
        layout.addLayout(row)
        form = QFormLayout()
        self.name = QLineEdit('custom-sight'); form.addRow('Package name', self.name)
        self.kind = QComboBox()
        for label, value in [('Extracted / imported texture', 'texture'), ('Crosshair schematic', 'cross'), ('Post schematic', 'post'),
                             ('Notch schematic', 'notch'), ('Peep schematic', 'peep')]:
            self.kind.addItem(label, value)
        self.kind.currentIndexChanged.connect(self.unverify); form.addRow('Sketch artwork', self.kind)
        self.scale = self.spin(0.000001, 1000000, 6); form.addRow('Original pixels per degree', self.scale)
        self.coords = []
        for title in ('Aiming x', 'Aiming y', 'Bore x', 'Bore y'):
            spin = self.spin(0, 32768, 3); self.coords.append(spin); form.addRow(title, spin)
        self.scale.valueChanged.connect(self.unverify)
        for spin in self.coords:
            spin.valueChanged.connect(self.coordinates_changed)
        self.verified = QCheckBox('I verified the angular scale, aiming point and bore alignment against the game')
        form.addRow(self.verified); layout.addLayout(form)
        self.markers = QTableWidget(0, 3); self.markers.setHorizontalHeaderLabels(['Range (metres)', 'Original pixel x', 'Original pixel y'])
        self.markers.setMaximumHeight(160); self.markers.itemChanged.connect(self.unverify); layout.addWidget(self.markers)
        row = QHBoxLayout()
        for label, action in [('Add range mark', self.add_marker), ('Remove selected mark', self.remove_marker),
                              ('Save calibration', self.save), ('Export website package', self.export), ('Open preview', self.open_preview)]:
            button = QPushButton(label); button.clicked.connect(action); row.addWidget(button)
        layout.addLayout(row)
        footer = QLabel('Texture centre is only a default. Zeroing ranges are extracted values, not proof of bore alignment.\n'
                        'Iron sights use schematics because their artwork is 3D mesh geometry. Exports include an HTML preview, SVG, JSON and browser renderer;\n'
                        'custom sights need wiring into the website’s sight selector. Match each sight to its measured ammunition dataset.')
        footer.setWordWrap(True); layout.addWidget(footer)
        self.win.worker.event.connect(self.on_event)

    @staticmethod
    def spin(low, high, decimals):
        spin = QDoubleSpinBox(); spin.setRange(low, high); spin.setDecimals(decimals); return spin

    def folder(self):
        from rmtlib import paths
        return Path(self.win.data.out.text().strip() or paths.workspace())/'sights'

    def command(self, command, extra=()):
        target = self.folder()/('scan.json' if command == 'scan' else 'inspection' if command == 'inspect' else self.name.text().strip())
        if command == 'inspect':
            import hashlib
            target /= hashlib.sha256(json.dumps(list(extra)).encode()).hexdigest()[:16]
        if command == 'export':
            target = self.folder()/self.package_name()
        args = ['--script', 'sighttools.py', command, '--output', str(target), *extra]
        wb = self.win.setup.workbench()
        if wb:
            args += ['--workbench', wb]
        self.win.launch_script(args, 'Sights: '+command, False, str(self.folder()))

    def package_name(self):
        import re
        name = self.name.text().strip()
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', name):
            raise ValueError('Use a package name containing letters, numbers, dash or underscore (maximum 64 characters).')
        return name

    def fill(self, *_):
        self.tree.clear(); query = self.search.text().strip().lower(); addon = self.addon.currentData()
        for record in self.records:
            if addon and record['addonGuid'] != addon:
                continue
            if self.type_filter.currentData() and record.get('kind') != self.type_filter.currentData():
                continue
            if query and query not in (record['resource']+' '+record['addon']).lower():
                continue
            item = QTreeWidgetItem([Path(record['path']).stem, record['addon'], record.get('kind', 'other'), record['resource']]); item.setData(0, Qt.ItemDataRole.UserRole, record)
            self.tree.addTopLevelItem(item)

    def inspect(self):
        if self.tree.selectedItems():
            record = self.tree.selectedItems()[0].data(0, Qt.ItemDataRole.UserRole)
            self.command('inspect', ['--resource', record['resource'], '--addon', record['addonGuid']])

    def choose_component(self, index):
        if self.report and index >= 0:
            self.set_spec(sights.defaults(self.report, index))
            sight = self.report['sights'][index]
            self.note.setText('Zeroing ranges: '+', '.join(f'{r["rangeMetres"]:g} m / {r["angleDegrees"]:g}°' for r in sight['ranges'])+'\n'+sight.get('textureNote', 'Reticle decoded from the selected addon.'))

    def set_spec(self, spec):
        self.spec = spec
        import re
        self.name.setText(re.sub(r'[^A-Za-z0-9_-]+', '-', spec['name']).strip('-')[:64] or 'custom-sight')
        self.kind.setCurrentIndex(max(0, self.kind.findData(spec['kind'])))
        self.preview.load(spec.get('image'), spec['width'], spec['height'])
        self.scale.setValue(spec.get('pixelsPerDegree') or 1)
        for spin, value in zip(self.coords, spec['aim']+(spec.get('bore') or spec['aim'])):
            spin.setValue(value)
        self.markers.setRowCount(0)
        for marker in spec.get('markers', []):
            self.add_marker(marker)
        self.verified.setChecked(bool(spec.get('calibrationVerified')))
        self.coordinates_changed()
        self.verified.setChecked(bool(spec.get('calibrationVerified')))

    def unverify(self, *_):
        if hasattr(self, 'verified'):
            self.verified.setChecked(False)

    def coordinates_changed(self, *_):
        if hasattr(self, 'coords') and len(self.coords) == 4:
            self.preview.aim = [x.value() for x in self.coords[:2]]; self.preview.bore = [x.value() for x in self.coords[2:]]
            self.preview.update(); self.unverify()

    def click_point(self, x, y):
        mode = self.click_mode.currentIndex()
        if mode < 2:
            self.coords[mode*2].setValue(x); self.coords[mode*2+1].setValue(y)
        elif self.markers.currentRow() >= 0:
            row = self.markers.currentRow()
            for column, value in ((1, x), (2, y)):
                self.markers.setItem(row, column, QTableWidgetItem(f'{value:.3f}'))

    def same_bore(self):
        self.coords[2].setValue(self.coords[0].value()); self.coords[3].setValue(self.coords[1].value())

    def add_marker(self, marker=None):
        if not isinstance(marker, dict):
            marker = {'rangeMetres': 100, 'x': self.coords[0].value(), 'y': self.coords[1].value()}
        row = self.markers.rowCount(); self.markers.insertRow(row)
        for column, key in enumerate(('rangeMetres', 'x', 'y')):
            self.markers.setItem(row, column, QTableWidgetItem(str(marker[key])))
        self.markers.setCurrentCell(row, 0)

    def remove_marker(self):
        if self.markers.currentRow() >= 0:
            self.markers.removeRow(self.markers.currentRow()); self.unverify()

    def current_spec(self):
        if not self.spec:
            raise ValueError('Extract a sight, import an image or load a calibration first.')
        spec = dict(self.spec)
        spec.update(name=self.package_name(), kind=self.kind.currentData(), pixelsPerDegree=self.scale.value(),
                    aim=[x.value() for x in self.coords[:2]], bore=[x.value() for x in self.coords[2:]],
                    calibrationVerified=self.verified.isChecked())
        spec['markers'] = [{key: float(self.markers.item(row, col).text()) for col, key in enumerate(('rangeMetres', 'x', 'y'))}
                           for row in range(self.markers.rowCount())]
        return spec

    def save(self):
        try:
            spec = self.current_spec()
            filename, _ = QFileDialog.getSaveFileName(self, 'Save sight calibration', str(self.folder()/(spec['name']+'.json')), 'JSON (*.json)')
            if filename:
                write_json(filename, spec)
        except (OSError, ValueError, AttributeError) as e:
            QMessageBox.warning(self, 'Sight calibration', str(e))

    def load(self):
        filename, _ = QFileDialog.getOpenFileName(self, 'Load sight calibration', str(self.folder()), 'JSON (*.json)')
        if filename:
            try:
                spec = json.loads(Path(filename).read_text(encoding='utf8'))
                if spec.get('image') and not Path(spec['image']).is_absolute():
                    spec['image'] = str(Path(filename).parent/spec['image'])
                self.set_spec(spec)
            except (OSError, ValueError, KeyError, TypeError) as e:
                QMessageBox.warning(self, 'Sight calibration', str(e))

    def import_image(self):
        filename, _ = QFileDialog.getOpenFileName(self, 'Import reticle / sight reference image', '', 'Images (*.png *.dds *.edds *.tga *.jpg)')
        if filename:
            try:
                image = sights.decode_texture(Path(filename).read_bytes()); dest = self.folder()/'imported-reticle.png'
                dest.parent.mkdir(parents=True, exist_ok=True); image.save(dest)
                spec = dict(self.spec) if self.spec else {'schema': 'rmt-sight-v1', 'name': 'custom-sight', 'ranges': [], 'markers': [],
                    'source': 'user-imported-image', 'notes': 'Manually supplied scale and reference points.', 'fields': {}}
                import hashlib
                spec.update(image=str(dest.resolve()), imageSha256=hashlib.sha256(dest.read_bytes()).hexdigest(), width=image.width, height=image.height, kind='texture',
                            aim=[image.width/2, image.height/2], bore=None, calibrationVerified=False, pixelsPerDegree=None, markers=[])
                self.set_spec(spec)
                self.note.setText('Imported image. Set pixels per degree using an angular reference; a screenshot does not supply scale.')
            except (OSError, ValueError, NotImplementedError) as e:
                QMessageBox.warning(self, 'Reticle import', str(e))

    def export(self):
        try:
            spec = self.current_spec(); sights.validate(spec)
            path = self.folder()/'calibration.json'; write_json(path, spec)
            self.command('export', ['--spec', str(path)])
        except (OSError, ValueError, AttributeError) as e:
            QMessageBox.warning(self, 'Sight export', str(e))

    def open_preview(self):
        if self.output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.output)/'preview.html')))

    def on_event(self, event):
        try:
            if event.get('sightCatalog'):
                report = json.loads(Path(event['sightCatalog']).read_text(encoding='utf8')); self.records = report['records']
                self.addon.blockSignals(True); self.addon.clear(); self.addon.addItem('All addons', None)
                for title, guid in sorted({(r['addon'], r['addonGuid']) for r in self.records}):
                    self.addon.addItem(title, guid)
                self.addon.blockSignals(False); self.fill()
                self.note.setText(f'{len(self.records)} weapon/vehicle/optic candidates; {len(report["warnings"])} source warnings in scan.json.')
                self.win.go('sights')
            if event.get('sightInspection'):
                self.report = json.loads(Path(event['sightInspection']).read_text(encoding='utf8'))
                self.component.blockSignals(True); self.component.clear()
                for sight in self.report['sights']:
                    self.component.addItem(sight['component']+' — '+sight.get('resource', self.report['resource']))
                self.component.blockSignals(False)
                if not self.report['sights']:
                    self.spec = None; self.preview.load(None, 1024, 1024)
                    self.note.setText('No supported sight component found. Source warnings: '+str(len(self.report.get('warnings', [])))+' (see inspection.json).')
                else:
                    self.choose_component(self.component.currentIndex())
                self.win.go('sights')
            if event.get('sightExport'):
                self.output = event['sightExport']; self.note.setText('Exported '+self.output); self.win.go('sights'); self.open_preview()
        except (OSError, ValueError, KeyError, TypeError) as e:
            self.note.setText('Unable to read sight result: '+str(e))
