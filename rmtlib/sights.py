"""Prefab-derived sight metadata, Enfusion texture decoding and portable sight sketches.

Coordinates use original texture pixels, angles use degrees; positive hold is right/up.
No meshes are reconstructed and no sight-to-bore alignment is inferred from texture centre.
"""
import base64
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import re
import struct
from xml.sax.saxutils import escape

from PIL import Image, ImageOps
from .ballistics import Catalog, write_json


def parse(text, source=''):
    """Read line-oriented Enfusion blocks, preserving component/entry identities."""
    root = {'header': [], 'fields': {}, 'children': [], 'source': source}
    stack, pending = [root], []
    # Retain newlines. Braces inside quoted resource GUIDs are not delimiters.
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|//[^\n]*|[{}\n]|[^\s{}"]+', text)
    def flush():
        if pending:
            stack[-1]['fields'][pending[0]] = {'value': pending[1:], 'source': source}
            pending.clear()
    for token in tokens:
        if token.startswith('//'):
            continue
        if token == '\n':
            flush()
        elif token == '{':
            node = {'header': pending[:], 'fields': {}, 'children': [], 'source': source}
            pending.clear()
            stack[-1]['children'].append(node)
            stack.append(node)
        elif token == '}':
            flush()
            if len(stack) == 1:
                raise ValueError('Unbalanced prefab block')
            stack.pop()
        else:
            pending.append(token)
    flush()
    if len(stack) != 1:
        raise ValueError('Unclosed prefab block')
    return root['children'][0] if root['children'] else root


def merge(base, child):
    result = copy.deepcopy(base)
    result['fields'].update(copy.deepcopy(child['fields']))
    result['header'] = child['header'][:]
    for node in child['children']:
        # Match identity including property, concrete type and GUID/name.
        identity = next((t for t in node['header'] if re.fullmatch(r'"\{[0-9A-Fa-f]{16}\}"', t)), None)
        match = next((n for n in result['children'] if (identity and identity in n['header'])
                      or (not identity and n['header'] == node['header'])), None)
        if match is None:
            result['children'].append(copy.deepcopy(node))
        else:
            result['children'][result['children'].index(match)] = merge(match, node)
    return result


def walk(node):
    yield node
    for child in node['children']:
        yield from walk(child)


def unquote(value):
    return value[1:-1] if value.startswith('"') and value.endswith('"') else value


def sight_components(catalog, record, context=None):
    tree = None
    chain = catalog.chain(record, context)
    for ancestor in reversed(chain):
        node = parse(catalog.text(ancestor), ancestor['resource'])
        tree = merge(tree, node) if tree else node
    found = []
    for node in walk(tree):
        if not any(t.endswith('SightsComponent') for t in node['header']):
            continue
        fields = node['fields']
        ranges = []
        for entry in walk(node):
            if 'SightRangeInfo' in entry['header'] and 'Range' in entry['fields']:
                v = entry['fields']['Range']
                try:
                    angle, distance = map(float, v['value'])
                    if math.isfinite(angle) and math.isfinite(distance):
                        ranges.append({'angleDegrees': angle, 'rangeMetres': distance, 'source': v['source']})
                except (ValueError, TypeError):
                    pass
        found.append({'resource': record['resource'], 'addonGuid': record['addonGuid'], 'component': ' '.join(node['header']), 'fields': fields,
                      'ranges': sorted(ranges, key=lambda x: x['rangeMetres'])})
    return {'resource': record['resource'], 'addon': record['addon'], 'addonGuid': record['addonGuid'],
            'ancestors': [x['resource'] for x in chain], 'sights': found}


def discover(catalog):
    records, warnings = [], []
    for record in catalog.records:
        if not record['path'].lower().endswith('.et'):
            continue
        try:
            # Weapons/vehicles can carry sights in referenced turret or attachment prefabs.
            text = catalog.text(record)
            if record['kind'] not in ('weapon', 'vehicle', 'optic') and 'SightsComponent' not in text:
                continue
            item = {k: record[k] for k in ('resource', 'path', 'addon', 'addonGuid', 'source', 'kind')}
            item['directSight'] = 'SightsComponent' in text
            records.append(item)
        except (ValueError, OSError) as e:
            warnings.append(str(e))
    return {'records': records, 'warnings': sorted(set(warnings))}


def lz4_block(data, output, limit):
    """Bounded raw LZ4 decoder; Enfusion 64 KiB chunks share preceding dictionary."""
    p = 0
    def length(n):
        nonlocal p
        if n == 15:
            while True:
                if p >= len(data):
                    raise ValueError('Truncated LZ4 length')
                v = data[p]; p += 1; n += v
                if v != 255:
                    break
        return n
    while p < len(data):
        token = data[p]; p += 1
        n = length(token >> 4)
        if p+n > len(data) or len(output)+n > limit:
            raise ValueError('Invalid LZ4 literal length')
        output.extend(data[p:p+n]); p += n
        if p == len(data):
            break
        if p+2 > len(data):
            raise ValueError('Truncated LZ4 offset')
        offset = data[p] | data[p+1] << 8; p += 2
        n = length(token & 15)+4
        if offset == 0 or offset > len(output) or len(output)+n > limit:
            raise ValueError('Invalid LZ4 back reference')
        # Repeat an overlapping pattern without one Python iteration per byte.
        pattern = bytes(output[-offset:])
        output.extend((pattern * ((n+offset-1)//offset))[:n])


def decode_texture(data):
    if data[:4] == b'DDS ' and data[36:40] == b'ENF1':
        header = 148 if data[84:88] == b'DX10' else 128
        if len(data) < header:
            raise ValueError('Truncated Enfusion DDS')
        count = struct.unpack_from('<I', data, 28)[0] or 1
        if count > 32 or header+count*8 > len(data):
            raise ValueError('Invalid Enfusion mip directory')
        # ENF1 stores a directory, then mips from smallest to largest, unlike ordinary DDS.
        cursor = header+count*8
        top = None
        for mip in range(count):
            tag = data[header+mip*8:header+mip*8+4]
            stored = struct.unpack_from('<I', data, header+mip*8+4)[0]
            if stored == 0 or cursor+stored > len(data):
                raise ValueError('Truncated Enfusion texture payload')
            if mip == count-1:
                top = (tag, data[cursor:cursor+stored])
            cursor += stored
        tag, payload = top
        if tag == b'COPY':
            output = payload
        elif tag == b'LZ4 ':
            if len(payload) < 8:
                raise ValueError('Truncated Enfusion LZ4 mip')
            size = struct.unpack_from('<I', payload)[0]
            if size > 128*1024*1024:
                raise ValueError('Oversized Enfusion texture')
            output = bytearray(); p = 4
            while p < len(payload):
                if p+4 > len(payload):
                    raise ValueError('Truncated Enfusion texture chunk')
                chunk = struct.unpack_from('<I', payload, p)[0]; p += 4
                n = chunk & 0x7fffffff  # high bit marks the final dictionary chunk
                if n == 0 or p+n > len(payload):
                    raise ValueError('Invalid Enfusion texture chunk')
                lz4_block(payload[p:p+n], output, size); p += n
            if len(output) != size:
                raise ValueError('Enfusion texture size mismatch')
        else:
            raise ValueError('Unsupported Enfusion texture compression; import a PNG exported by Workbench')
        head = bytearray(data[:header]); struct.pack_into('<I', head, 28, 1)
        data = head+output
    with Image.open(io.BytesIO(data)) as image:
        return image.convert('RGBA')


def texture_bytes(catalog, reference, context):
    """Index textures only when requested, in the selected dependency scope."""
    from . import addons, pak
    from .ballistics import archive_entries
    loaded = set(addons.dependency_guids(context, catalog.by_guid))
    path = reference.split('}', 1)[-1].replace('\\', '/')
    matches = []
    for addon in catalog.addons:
        if addon.source != 'game' and addon.guid not in loaded:
            continue
        # Check referenced GUID, rather than silently accepting another resource at the same path.
        if reference.startswith('{') and Path(addon.rdb).is_file():
            raw = Path(addon.rdb).read_bytes()
            marker = path.encode('ascii')+b'\0'
            at = raw.find(marker)
            if at < 0:
                continue
            guid = raw[at+len(marker)+6:at+len(marker)+14][::-1].hex().upper()
            if guid != reference[1:17].upper():
                continue
        loose = Path(addon.folder)/path
        if loose.is_file():
            matches.append((addon, ('file', str(loose))))
            continue
        for archive in Path(addon.folder).rglob('*.pak'):
            if any(part.lower() == 'temp' for part in archive.relative_to(addon.folder).parts):
                continue
            for name, off, stored, size, comp in archive_entries(archive):
                if name.lower() == path.lower():
                    matches.append((addon, ('pak', str(archive), off, stored, size, comp)))
    overrides = [x for x in matches if x[0].source != 'game']
    matches = overrides or matches
    if len(matches) != 1:
        raise ValueError(f'{reference}: {len(matches)} texture sources in selected addon scope')
    addon, storage = matches[0]
    data = Path(storage[1]).read_bytes() if storage[0] == 'file' else pak.read(*storage[1:])
    return data, {'resource': reference, 'addonGuid': addon.guid, 'sha256': hashlib.sha256(data).hexdigest()}


def extract(catalog, reference, owner, output):
    from .ballistics import REFS, PARENT
    root = catalog.resolve(reference, owner)
    report = {'resource': root['resource'], 'addon': root['addon'], 'addonGuid': root['addonGuid'],
              'ancestors': [r['resource'] for r in catalog.chain(root)], 'sights': [], 'warnings': []}
    todo, seen = [(root, 0)], set()
    while todo and len(seen) < 500:
        record, depth = todo.pop(0)
        key = (record['addonGuid'], record['resource'])
        if key in seen:
            continue
        seen.add(key)
        try:
            direct = sight_components(catalog, record, root['addonGuid'])
            report['sights'].extend(direct['sights'])
            if depth < 8:
                for ancestor in catalog.chain(record, root['addonGuid']):
                    text = catalog.text(ancestor); parent = PARENT.match(text)
                    for ref in REFS.findall(text):
                        # Default occupants' personal weapons are not vehicle-mounted sights.
                        if '/characters/' in ref.lower() or '/loadouts/' in ref.lower():
                            continue
                        if parent and ref == parent[1]:
                            continue
                        try:
                            todo.append((catalog.resolve(ref, context=root['addonGuid']), depth+1))
                        except ValueError as e:
                            report['warnings'].append(str(e))
        except (ValueError, OSError) as e:
            report['warnings'].append(str(e))
    if todo:
        report['warnings'].append('Reference walk limited to 500 resources / 8 levels; inspect the specific turret/optic prefab if a channel is missing.')
    report['warnings'] = sorted(set(report['warnings']))
    folder = Path(output); folder.mkdir(parents=True, exist_ok=True)
    for index, sight in enumerate(report['sights']):
        value = sight['fields'].get('m_sReticleTexture', {}).get('value', [])
        if not value:
            sight['textureNote'] = 'No 2D reticle texture; use a schematic or import a Workbench screenshot.'
            continue
        try:
            raw, provenance = texture_bytes(catalog, unquote(value[0]), report['addonGuid'])
            image = decode_texture(raw)
            dest = folder/f'reticle-{index}.png'; image.save(dest)
            sight.update(image=str(dest.resolve()), imageSha256=hashlib.sha256(dest.read_bytes()).hexdigest(), width=image.width, height=image.height, texture=provenance)
        except (OSError, ValueError, NotImplementedError) as e:
            sight['textureNote'] = str(e)
    write_json(folder/'inspection.json', report)
    return report


def numeric(sight, name):
    value = sight.get('fields', {}).get(name, {}).get('value', [])
    try:
        return float(value[0]) if len(value) == 1 else None
    except ValueError:
        return None


def defaults(report, index=0):
    sight = report['sights'][index]
    width, height = sight.get('width', 1024), sight.get('height', 1024)
    angle, portion = numeric(sight, 'm_fReticleAngularSize'), numeric(sight, 'm_fReticlePortion')
    pxdeg = width*portion/angle if angle and portion and angle > 0 and portion > 0 else None
    return {'schema': 'rmt-sight-v1', 'name': Path(report['resource']).stem, 'kind': 'texture' if sight.get('image') else 'cross',
            'image': sight.get('image'), 'imageSha256': sight.get('imageSha256'), 'width': width, 'height': height,
            'pixelsPerDegree': pxdeg, 'aim': [width/2, height/2], 'bore': None,
            'markers': [], 'ranges': sight['ranges'], 'source': sight.get('resource', report['resource']), 'selectedPrefab': report['resource'],
            'addonGuid': sight.get('addonGuid', report['addonGuid']), 'component': sight['component'],
            'ancestors': report['ancestors'], 'fields': sight['fields'], 'texture': sight.get('texture'),
            'calibrationVerified': False, 'notes': 'Centre is an unverified default. Set the aim/bore points and verify in game.'}


def validate(spec):
    def finite(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if spec.get('kind') not in ('texture', 'cross', 'post', 'notch', 'peep'):
        raise ValueError('Choose texture, cross, post, notch or peep')
    for key in ('width', 'height', 'pixelsPerDegree'):
        if not finite(spec.get(key)) or spec[key] <= 0:
            raise ValueError(f'{key} must be a positive finite number')
    for key in ('aim', 'bore'):
        point = spec.get(key)
        if not isinstance(point, (list, tuple)) or len(point) != 2 or not all(finite(v) for v in point):
            raise ValueError(f'Set the {key} point explicitly')
        if not (0 <= point[0] <= spec['width'] and 0 <= point[1] <= spec['height']):
            raise ValueError(f'{key} point must be inside the original image')
    for marker in spec.get('markers', []):
        if not all(finite(marker.get(k)) for k in ('rangeMetres', 'x', 'y')) or marker['rangeMetres'] <= 0:
            raise ValueError('Range marks need positive metres and finite x/y pixels')
        if not (0 <= marker['x'] <= spec['width'] and 0 <= marker['y'] <= spec['height']):
            raise ValueError('Range mark is outside the image')
    if not spec.get('calibrationVerified'):
        raise ValueError('Verify scale/aim/bore calibration before exporting a website package')


def svg(spec, png=None):
    w, h = spec['width'], spec['height']; x, y = spec['aim']
    if spec['kind'] == 'texture':
        if png is None:
            png = Path(spec['image']).read_bytes()
        art = f'<image width="{w}" height="{h}" href="data:image/png;base64,{base64.b64encode(png).decode()}"/>'
    else:
        size = min(w, h)*.08
        kind = spec['kind']
        if kind == 'cross':
            art = f'<path d="M{x-size},{y}H{x+size} M{x},{y-size}V{y+size}"/>'
        elif kind == 'peep':
            art = f'<circle cx="{x}" cy="{y}" r="{size*2}"/><path d="M{x},{y}v{size*4}"/>'
        elif kind == 'notch':
            art = f'<path d="M{x-size*3},{y}h{size*2}v{size}h{size*2}v{-size}h{size*2} M{x},{y}v{size*3}"/>'
        else:
            art = f'<path d="M{x},{y}l{-size/2},{size*3}h{size}Z" fill="currentColor"/>'
        art = f'<g fill="none" stroke="currentColor" stroke-width="{max(1,w/512)}">{art}</g>'
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" style="color:#e8eef3"><title>{escape(spec["name"])}</title>{art}</svg>'


RENDERER = '''// Portable renderer for rmt-sight-v1. Angular inputs are DEGREES, not mils.
// Call from the website sight-picture view after loading sight.json. Returns SVG markup.
// The existing site's hardcoded gunReticle branches need a call to this renderer for custom sights.
export function sightPicture(sight, {width=640,height=640,fieldDegrees=6,holdRight=0,holdUp=0}={}) {
  if (!(fieldDegrees>0 && sight.pixelsPerDegree>0)) throw Error('Invalid angular scale');
  const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
  const k=width/fieldDegrees, scale=k/sight.pixelsPerDegree;
  const x=width/2-sight.aim[0]*scale, y=height/2-sight.aim[1]*scale;
  const tx=width/2+holdRight*k, ty=height/2-holdUp*k;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}">
    <rect width="100%" height="100%" fill="#263641"/>
    <circle cx="${tx}" cy="${ty}" r="5" fill="#d84b32"/>
    <image href="${esc(sight.sketch)}" x="${x}" y="${y}" width="${sight.width*scale}" height="${sight.height*scale}"/>
  </svg>`;
}
export function boreElevation(sight, row) { return (row-sight.bore[1])/sight.pixelsPerDegree; }
'''


def export(spec, folder):
    validate(spec)
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    out = copy.deepcopy(spec)
    png = None
    if spec['kind'] == 'texture':
        raw = Path(spec['image']).read_bytes()
        if spec.get('imageSha256') and hashlib.sha256(raw).hexdigest() != spec['imageSha256']:
            raise ValueError('Reticle image changed since calibration; inspect/calibrate again')
        image = decode_texture(raw)
        if image.size != (spec['width'], spec['height']):
            raise ValueError('Image size changed since calibration; inspect/calibrate again')
        buffer = io.BytesIO(); image.save(buffer, format='PNG'); png = buffer.getvalue()
        (folder/'reticle.png').write_bytes(png)
        out['image'] = 'reticle.png'
        out['imageSha256'] = hashlib.sha256(png).hexdigest()
    else:
        out['image'] = None
        out['notes'] += ' Iron/cross artwork is a schematic, not extracted mesh geometry.'
    (folder/'sketch.svg').write_text(svg(spec, png), encoding='utf8')
    out['sketch'] = 'sketch.svg'
    out['website'] = {'pxdeg': spec['pixelsPerDegree'], 'centre': spec['aim'][1], 'axis': spec['bore'][1],
                      'zeros': [x['rangeMetres'] for x in spec['ranges']],
                      'lines': [[m['rangeMetres'], m['y'], True] for m in spec['markers']]}
    write_json(folder/'sight.json', out)
    (folder/'sight-renderer.mjs').write_text(RENDERER, encoding='utf8')
    # No fetch: preview works directly from a file URL.
    embedded = 'data:image/svg+xml;base64,'+base64.b64encode(svg(spec, png).encode()).decode()
    demo = copy.deepcopy(out); demo['sketch'] = embedded
    module = RENDERER.replace('export function ', 'function ')
    html = '<!doctype html><meta charset="utf-8"><title>Sight preview</title><style>body{font:16px system-ui;background:#17202a;color:white;max-width:720px;margin:auto}svg{width:100%}input{width:80px}</style>'
    html += '<h1>'+escape(spec['name'])+'</h1><p>Positive hold: right/up. Angles in degrees.</p>'
    html += '<label>Right <input id="right" type="number" step="0.05" value="0"></label> <label>Up <input id="up" type="number" step="0.05" value="0"></label><div id="picture"></div>'
    html += '<script type="module">'+module+'\nconst sight='+json.dumps(demo).replace('<', '\\u003c')+';'
    html += 'function draw(){picture.innerHTML=sightPicture(sight,{holdRight:+right.value,holdUp:+up.value});} right.oninput=up.oninput=draw;draw();</script>'
    (folder/'preview.html').write_text(html, encoding='utf8')
    (folder/'README.txt').write_text('Open preview.html to view the calibrated sight.\nCopy sight.json, sketch.svg and sight-renderer.mjs into the website asset directory.\nResolve sketch/image paths relative to the JSON URL. Wire sightPicture into its custom sight selector.\nExisting shot-core.js does not automatically discover this package. website in sight.json supplies pxdeg/centre/axis/zeros/lines.\nLink the appropriate measured custom ballistics separately. Scale/aim/bore verification is user supplied.\nReticle assets may require the mod author permission before redistribution.\n', encoding='utf8')
    return str(folder.resolve())
