# /// script
# requires-python = ">=3.10"
# dependencies = ["olefile>=0.47", "extract-msg>=0.55", "pycryptodome>=3.20"]
# ///
"""Generate the five-target table: uv run vprl/build_table.py."""
from pathlib import Path
import struct

import olefile
from Crypto.Hash import MD2
from extract_msg.ole_writer import OleWriter

ROOT = Path(__file__).resolve().parents[1]

# Native VPU coordinates; five rounded targets in a fan.
PLAYFIELD_RGB = (20, 65, 120)  # Dark blue; silver ball and neutral targets stay unchanged.
TARGETS = [(140, 1050, -40), (290, 700, -15), (437, 460, 0),
           (584, 700, 15), (734, 1050, 40)]
# VPX wall polygons use negative signed area in native XY (matching stock walls).
LEFT_RETURN = [(20, 1800), (102, 1740), (102, 1510), (105, 1430), (20, 1340)]
RIGHT_RETURN = [(874-x, y) for x, y in reversed(LEFT_RETURN)]


def records(data, offset=0):
    """VPX BIFF records, including its length-exempt CODE payload."""
    while offset < len(data):
        size = struct.unpack_from('<I', data, offset)[0]
        if size < 4 or offset + 4 + size > len(data):
            raise ValueError('Malformed BIFF record')
        tag = data[offset+4:offset+8]
        end = offset+4+size
        payload = data[offset+8:end]
        if tag == b'CODE':
            length = struct.unpack_from('<I', data, end)[0]
            payload = data[end+4:end+4+length]
            end += 4+length
            if end > len(data):
                raise ValueError('Truncated script')
        yield tag, payload
        offset = end


def encode(parts):
    return b''.join((struct.pack('<I', 4)+tag+struct.pack('<I', len(value))+value)
                   if tag == b'CODE' else (struct.pack('<I', 4+len(value))+tag+value)
                   for tag, value in parts)


def integer(value): return struct.pack('<i', value)
def floats(*value): return struct.pack('<'+'f'*len(value), *value)
def text(value, wide=False):
    data = value.encode('utf-16le' if wide else 'cp1252')
    return integer(len(data))+data


def patch(data, updates, offset=4):
    parts = list(records(data, offset))
    for tag, value in updates.items():
        indices = [i for i, (key, _) in enumerate(parts) if key == tag]
        if len(indices) != 1:
            raise ValueError(f'Expected one {tag!r}, found {len(indices)}')
        parts[indices[0]] = tag, value
    return data[:offset]+encode(parts)


def named_items(streams):
    items = {}
    for path, data in streams.items():
        if path.startswith('GameStg/GameItem'):
            # Compressed primitive meshes are not all BIFF-framed. Only inspect
            # the types needed by this authoring tool.
            kind = struct.unpack_from('<I', data)[0]
            if kind not in (0, 7, 22): continue
            value = dict(records(data, 4))[b'NAME']
            name = value[4:4+struct.unpack_from('<I', value)[0]].decode('utf-16le')
            items[name] = data
    return items


def script_from(streams):
    return dict(records(streams['GameStg/GameData']))[b'CODE'].decode('cp1252').replace('\r\n', '\n')


def table_mac(streams):
    """VPX's legacy MD2 integrity hash (not a security signature)."""
    digest = MD2.new(b'Visual Pinball')
    digest.update(streams['GameStg/Version'])
    for name in ('TableName', 'AuthorName', 'TableVersion', 'ReleaseDate', 'AuthorEmail',
                 'AuthorWebSite', 'TableBlurb', 'TableDescription', 'TableRules', 'Screenshot'):
        digest.update(streams.get('TableInfo/'+name, b''))
    custom = list(records(streams['GameStg/CustomInfoTags']))
    for tag, value in custom: digest.update(tag+value)
    for tag, value in custom:
        if tag == b'CUST':
            name = value[4:].decode('cp1252')
            digest.update(streams.get('TableInfo/'+name, b''))
    for tag, value in records(streams['GameStg/GameData']): digest.update(tag+value)
    for path in sorted((p for p in streams if p.startswith('GameStg/Collection')),
                       key=lambda p: int(p.split('Collection')[1])):
        for tag, value in records(streams[path]): digest.update(tag+value)
    return digest.digest()


def load(path):
    with olefile.OleFileIO(path) as file:
        return {'/'.join(p): file.openstream(p).read() for p in file.listdir()}


def build():
    base_path = ROOT/'src/assets/strippedTable.vpx'
    base = load(base_path)
    if table_mac(base) != base['GameStg/MAC']:
        raise ValueError('Source integrity calculation differs from VPX; refusing to write')
    streams = base.copy()
    base_items = named_items(base)
    example = named_items(load(ROOT/'src/assets/exampleTable.vpx'))
    count = struct.unpack('<i', dict(records(base['GameStg/GameData']))[b'SEDT'])[0]
    added = []
    for i, (x, y, angle) in enumerate(TARGETS, 1):
        target = patch(example['sw1'], {
            b'NAME': text(f'RLTarget{i}', True), b'VPOS': floats(x, y, 0, 0),
            # Broad round face, shallow base, stock height.
            b'VSIZ': floats(140, 15, 32, 0), b'ROTZ': floats(angle), b'TRTY': integer(3),
            b'TMON': integer(0), b'ISDR': integer(0), b'THRS': floats(.1),
            b'RSCT': floats(0), b'OVPH': integer(1), b'IMAG': text(''),
            b'MATR': dict(records(base_items['Wall5top'], 4))[b'TOMA'],
        })
        added.append(target)
        # Stock GI material with a rectangular insert in front of the target.
        light = with_polygon(base_items['gi1'],
                             [(x-35,y+45),(x-35,y+95),(x+35,y+95),(x+35,y+45)], {b'NAME': text(f'RLIndicator{i}', True), b'VCEN': floats(x, y+70),
                             b'RADI': floats(48), b'STAT': integer(0),
                             b'BULT': integer(0), b'SHBM': integer(0), b'HGHT': floats(0),
                             b'BWTH': floats(2), b'FASP': floats(100), b'FASD': floats(100),
                             b'COLR': integer(0x20FF40), b'COL2': integer(0x80FF80)})
        added.append(light)
    for name, points in [('RLLeftReturn', LEFT_RETURN), ('RLRightReturn', RIGHT_RETURN)]:
        wall = with_polygon(base_items['Wall5top'], points, {b'NAME': text(name, True), b'HTBT': floats(0), b'HTTP': floats(120),
                            b'HTEV': integer(0), b'CLDW': integer(1)})
        added.append(wall)
    for i, data in enumerate(added, count): streams[f'GameStg/GameItem{i}'] = data

    script = script_from(base)
    old = """\tIf BIP = 0 then
\t\t'Plunger.CreateBall
\t\tBallRelease.CreateBall
\t\tBallRelease.Kick 90, 7
\t\tPlaySound SoundFX("ballrelease",DOFContactors), 0,1,AudioPan(BallRelease),0.25,0,0,1,AudioFade(BallRelease)
\t\tBIP = BIP + 1
\tEnd If"""
    if script.count(old) != 1: raise ValueError('Stripped drain handler changed')
    script = script.replace(old, '\tIf BIP = 0 Then RLGameOver = True', 1)
    key = 'Sub Table1_KeyDown(ByVal keycode)\n'
    if script.count(key) != 1: raise ValueError('Stripped key handler changed')
    script = script.replace(key, key+'    If keycode = PlungerKey And Not RLGameOver Then RLStarted = True\n', 1)
    script += '\n' + (ROOT/'vprl/five_targets_hooks.vbs').read_text()
    streams['GameStg/GameData'] = patch(base['GameStg/GameData'],
        {b'SEDT': integer(count+len(added)), b'CODE': script.encode('cp1252')}, offset=0)
    # Color only the playfield's existing material. Keep every physics field
    # intact, and clear the old wood-image reference for a uniform background.
    color = integer(PLAYFIELD_RGB[0] | (PLAYFIELD_RGB[1] << 8) | (PLAYFIELD_RGB[2] << 16))
    parts = list(records(streams['GameStg/GameData']))
    modern_matches = legacy_matches = 0
    for i, (tag, value) in enumerate(parts):
        if tag == b'MATR' and dict(records(value))[b'NAME'] == text('Playfield'):
            parts[i] = tag, patch(value, {b'BASE': color}, offset=0)
            modern_matches += 1
        elif tag == b'MATE':
            # Legacy SaveMaterial entries: 76 bytes, 32-byte name then base COLORREF.
            legacy = bytearray(value)
            if len(legacy) % 76: raise ValueError('Unexpected legacy material format')
            for pos in range(0, len(legacy), 76):
                if legacy[pos:pos+32].split(b'\0')[0] == b'Playfield':
                    legacy[pos+32:pos+36] = color
                    legacy_matches += 1
            parts[i] = tag, bytes(legacy)
        elif tag == b'IMAG':
            parts[i] = tag, text('')
    if (modern_matches, legacy_matches) != (1, 1):
        raise ValueError('Expected one playfield material in both material representations')
    streams['GameStg/GameData'] = encode(parts)
    streams['GameStg/MAC'] = table_mac(streams)
    output = ROOT/'vprl/assets/rl_table.vpx'
    output.parent.mkdir(parents=True, exist_ok=True)
    writer = OleWriter()
    with olefile.OleFileIO(base_path) as original: writer.fromOleFile(original)
    for path, data in streams.items():
        if path in base:
            if data != base[path]: writer.editEntry(path, data=data)
        else: writer.addEntry(path, data)
    writer.write(output)
    (ROOT/'vprl/assets/embedded_script.txt').write_text(script)
    print(f'Wrote {output}: {len(added)} new parts')


def with_polygon(data, points, updates):
    parts = list(records(data, 4))
    cut = next(i for i, (tag, _) in enumerate(parts) if tag in (b'PNTS', b'DPNT'))
    # Walls have a PNTS marker; lights begin directly with drag points.
    fields = data[:4] + encode(parts[:cut] + [(b'ENDB', b'')])
    prefix = patch(fields, updates)[:-8]
    parts = [(b'PNTS', b'')] if parts[cut][0] == b'PNTS' else []
    for x, y in points:
        parts.extend([(b'DPNT', b''), (b'VCEN', floats(x,y)), (b'POSZ', floats(0)),
                      (b'SMTH', integer(0)), (b'SLNG', integer(0)), (b'ATEX', integer(1)),
                      (b'TEXC', floats(0)), (b'ENDB', b'')])
    return prefix + encode(parts + [(b'ENDB', b'')])


if __name__ == '__main__': build()
