"""Component inheritance, binary texture decoding and portable calibration contracts."""
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from PIL import Image
from rmtlib import sights
from rmtlib.ballistics import Catalog


class SightTests(unittest.TestCase):
    def test_component_guid_survives_class_change_without_merging_other_channel(self):
        base = sights.parse('Entity {\n components {\n BaseSightsComponent "{1111111111111111}" {\n m_fReticlePortion 0.5\n }\n BaseSightsComponent "{2222222222222222}" {\n m_fReticlePortion 0.8\n }\n }\n}', 'base')
        child = sights.parse('Entity {\n components {\n SCR_2DPIPSightsComponent "{1111111111111111}" {\n m_fReticleAngularSize 6\n }\n }\n}', 'child')
        tree = sights.merge(base, child)
        channels = [n for n in sights.walk(tree) if any(t.endswith('SightsComponent') for t in n['header'])]
        self.assertEqual(len(channels), 2)
        self.assertEqual(channels[0]['header'][0], 'SCR_2DPIPSightsComponent')
        self.assertEqual(channels[0]['fields']['m_fReticlePortion']['source'], 'base')
        self.assertEqual(channels[1]['fields']['m_fReticlePortion']['value'], ['0.8'])

    def test_enfusion_chunked_dds_and_corrupt_payload(self):
        # A tiny uncompressed DDS payload wrapped in the same ENF1/LZ4 container.
        buffer = io.BytesIO(); Image.new('RGBA', (4, 4), (230, 40, 10, 255)).save(buffer, format='DDS')
        raw = buffer.getvalue(); header = bytearray(raw[:128]); header[36:40] = b'ENF1'
        payload = raw[128:]; literal = bytes([0xf0, len(payload)-15])+payload
        chunks = struct.pack('<I', len(literal) | 0x80000000)+literal
        encoded = bytes(header)+b'LZ4 '+struct.pack('<II', len(chunks)+4, len(payload))+chunks
        decoded = sights.decode_texture(encoded)
        self.assertEqual(decoded.size, (4, 4)); self.assertEqual(decoded.getpixel((0, 0)), (230, 40, 10, 255))
        with self.assertRaises(ValueError): sights.decode_texture(encoded[:-1])
        with self.assertRaises(ValueError): sights.lz4_block(b'\x00\x00\x00', bytearray(), 100)

    def test_lz4_shared_dictionary_and_overlap(self):
        output = bytearray(b'abcd')
        sights.lz4_block(b'\x08\x04\x00', output, 16)
        self.assertEqual(output, b'abcdabcdabcdabcd')

    def test_reverse_mip_directory_selects_largest_copy(self):
        buffer = io.BytesIO(); Image.new('RGBA', (4, 4), (10, 90, 210, 255)).save(buffer, format='DDS')
        raw = buffer.getvalue(); header = bytearray(raw[:128]); header[36:40] = b'ENF1'
        struct.pack_into('<I', header, 28, 2)
        payload = raw[128:]; small = bytes([255, 0, 0, 255])
        encoded = bytes(header)+b'COPY'+struct.pack('<I', len(small))+b'COPY'+struct.pack('<I', len(payload))+small+payload
        image = sights.decode_texture(encoded)
        self.assertEqual(image.size, (4, 4)); self.assertEqual(image.getpixel((0, 0)), (10, 90, 210, 255))
        with self.assertRaises(ValueError): sights.decode_texture(encoded[:-1])

    def test_same_size_image_replacement_invalidates_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); spec = self.spec(root); path = Path(spec['image'])
            spec['imageSha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            Image.new('RGBA', (32, 32), (0, 0, 0, 255)).save(path)
            with self.assertRaises(ValueError): sights.export(spec, root/'replaced')

    def spec(self, root):
        path = root/'input.png'; Image.new('RGBA', (32, 32), (255, 255, 255, 100)).save(path)
        return {'schema': 'rmt-sight-v1', 'name': 'test', 'kind': 'texture', 'image': str(path),
                'width': 32, 'height': 32, 'pixelsPerDegree': 8, 'aim': [16, 8], 'bore': [16, 12],
                'ranges': [{'angleDegrees': .3, 'rangeMetres': 100}], 'markers': [{'rangeMetres': 200, 'x': 16, 'y': 20}],
                'calibrationVerified': True, 'notes': 'test calibration'}

    def test_export_is_portable_and_preserves_axes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); spec = self.spec(root); folder = root/'export'
            sights.export(spec, folder)
            doc = json.loads((folder/'sight.json').read_text())
            self.assertEqual(doc['image'], 'reticle.png'); self.assertEqual(doc['website']['axis'], 12)
            self.assertEqual(doc['website']['centre'], 8); self.assertEqual(doc['website']['lines'], [[200, 20, True]])
            self.assertIn('data:image/png;base64,', (folder/'sketch.svg').read_text())
            self.assertNotIn(str(root), (folder/'preview.html').read_text())
            self.assertTrue((folder/'sight-renderer.mjs').is_file())

    def test_reject_unverified_nonfinite_and_image_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); spec = self.spec(root)
            for key, val in [('calibrationVerified', False), ('pixelsPerDegree', float('nan')), ('bore', None), ('aim', [33, 0])]:
                bad = dict(spec); bad[key] = val
                with self.assertRaises(ValueError): sights.export(bad, root/'bad')
            spec['width'] = 64
            with self.assertRaises(ValueError): sights.export(spec, root/'changed')


if __name__ == '__main__': unittest.main()
