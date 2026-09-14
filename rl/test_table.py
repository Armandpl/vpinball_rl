"""Saved-table authoring/physics tests (see rl/README.md for test dependencies)."""
from pathlib import Path
import tempfile
import unittest

try:
    import olefile
    from extract_msg.ole_writer import OleWriter
    from rl.build_table import ROOT, load, records, patch, script_from, table_mac
except ImportError as exc:
    raise unittest.SkipTest("Table tests need extract-msg, olefile and pycryptodome") from exc

from rl import Pinball

TABLE = ROOT / 'rl/assets/rl_table.vpx'


class SavedTableTests(unittest.TestCase):
    def test_minimal_asset_diff_and_integrity(self):
        base = load(ROOT / 'src/assets/strippedTable.vpx')
        saved = load(TABLE)
        changed = {key for key in base if base[key] != saved[key]}
        self.assertEqual(changed, {'GameStg/GameData', 'GameStg/MAC'})
        self.assertEqual(len(saved.keys() - base.keys()), 12)  # Five targets, five lights, two returns.
        self.assertEqual(table_mac(saved), saved['GameStg/MAC'])
        script = script_from(saved)
        self.assertEqual(script, (ROOT/'rl/assets/embedded_script.txt').read_text())
        for line in script_from(base).splitlines():
            if 'Nudge ' in line:
                self.assertIn(line, script)
        self.assertFalse(TABLE.with_suffix('.vbs').exists())

    def test_playfield_recolor_does_not_change_material_physics(self):
        def materials(path):
            return [dict(records(value)) for tag, value in records(load(path)['GameStg/GameData'])
                    if tag == b'MATR']
        before = materials(ROOT/'src/assets/strippedTable.vpx')
        after = materials(TABLE)
        changed = [(a, b) for a, b in zip(before, after) if a != b]
        self.assertEqual(len(before), len(after))
        self.assertEqual(len(changed), 1)
        a, b = changed[0]
        self.assertEqual(a[b'NAME'][4:], b'Playfield')
        self.assertEqual({key for key in a if a[key] != b[key]}, {b'BASE'})
        self.assertEqual(b[b'BASE'], bytes([20, 65, 120, 0]))

    def test_client_does_not_patch_the_saved_table(self):
        with Pinball(width=320, height=240) as game:
            copied = game.log_path.parent/'table.vpx'
            self.assertEqual(copied.read_bytes(), TABLE.read_bytes())
            self.assertFalse(copied.with_suffix('.vbs').exists())


class PhysicsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        source = load(TABLE)
        script = script_from(source)
        # Offline diagnostic fixture ONLY. Production has no teleport/debug actions.
        script = script.replace('Sub RLApplyAction(l, r, s)', 'Sub RLNormalAction(l, r, s)')
        script = script.replace('Function RLObserve\n', 'Function RLNormalObserve\n').replace('    RLObserve =', '    RLNormalObserve =')
        script += '''
Sub RLApplyAction(l, r, s)
    Dim id, a, b, targets, target, angle, nx, ny
    id = l + 2*r + 4*s
    If id = 0 Then Exit Sub
    RLStarted = True
    a = GetBalls
    Set b = a(0)
    b.Z = 25: b.VelZ = 0
    If id <= 5 Then
        targets = Array(RLTarget1, RLTarget2, RLTarget3, RLTarget4, RLTarget5)
        Set target = targets(id-1)
        angle = target.Orientation * 3.141592653589793 / 180
        nx = -Sin(angle): ny = Cos(angle)
        b.X = target.X + nx*100: b.Y = target.Y + ny*100
        b.VelX = -nx*15: b.VelY = -ny*15
    Else
        If id = 6 Then b.X = 60 Else b.X = 814
        b.Y = 1200: b.VelX = 0: b.VelY = 12
    End If
End Sub
Function RLObserve
    Dim a, b, result
    result = RLNormalObserve()
    a = GetBalls
    result = Left(result, Len(result)-1) & ",""native_ms"":" & CStr(GameTime) & ",""ball_count"":" & CStr(UBound(a)+1) & "}"
    If UBound(a) >= 0 Then
        Set b = a(0)
        result = Left(result, Len(result)-1) & ",""ball"": [" & CStr(b.X) & "," & CStr(b.Y) & "," & CStr(b.Z) & "]}"
    End If
    RLObserve = result
End Function
'''
        self.table = Path(self.directory.name)/'fixture.vpx'
        writer = OleWriter()
        with olefile.OleFileIO(TABLE) as original:
            writer.fromOleFile(original)
        source['GameStg/GameData'] = patch(source['GameStg/GameData'], {b'CODE': script.encode('cp1252')}, offset=0)
        writer.editEntry('GameStg/GameData', data=source['GameStg/GameData'])
        writer.editEntry('GameStg/MAC', data=table_mac(source))
        writer.write(self.table)

    @staticmethod
    def step(game, code=0, ticks=10):
        game._sock.sendall(f'step {code&1} {(code>>1)&1} {(code>>2)&1} {ticks}\n'.encode())
        header = game._header()
        game._stream.read(header['bytes'])
        return header['state']

    def test_reset_keeps_native_clock_and_serves_exactly_one_ball(self):
        with Pinball(table=self.table, width=320, height=240) as game:
            prior_time = 0
            for _ in range(20):
                hit = self.step(game, 1, ticks=150)
                self.assertEqual(hit['score'], 100)  # Cooldown must reset each episode.
                self.assertGreater(hit['native_ms'], prior_time)
                game._sock.sendall(b'reset\n')
                header = game._header()
                game._stream.read(header['bytes'])
                state = header['state']
                self.assertEqual(header['ticks'], 0)
                self.assertEqual(state['native_ms'], hit['native_ms'])
                self.assertEqual(state['ball_count'], 1)
                self.assertEqual((state['score'], state['active_target']), (0, 1))
                self.assertFalse(state['started'] or state['game_over'] or state['launch_pending'])
                prior_time = state['native_ms']

    def test_real_target_contacts_lit_unlit_and_full_cycle(self):
        with Pinball(table=self.table, width=320, height=240) as game:
            for target, score, active in [(5,10,1),(1,110,2),(2,210,3),(3,310,4),(4,410,5),(5,510,1)]:
                state = self.step(game, target, ticks=150)
                self.assertEqual((state['score'], state['active_target']), (score, active))

    def test_right_target_wall_gap_does_not_trap_glancing_balls(self):
        # Reproduce downward approaches between the rightmost target and the
        # shooter-lane wall, without relocating either target or wall.
        streams = load(self.table)
        script = script_from(streams)
        old = 'If id = 6 Then b.X = 60 Else b.X = 814\n        b.Y = 1200: b.VelX = 0: b.VelY = 12'
        self.assertEqual(script.count(old), 1)
        script = script.replace(old, 'If id = 6 Then b.X = 804 Else b.X = 818\n        b.Y = 900: b.VelX = 0: b.VelY = 8')
        streams['GameStg/GameData'] = patch(streams['GameStg/GameData'], {b'CODE': script.encode('cp1252')}, offset=0)
        path = Path(self.directory.name)/'gap-test.vpx'
        writer = OleWriter()
        with olefile.OleFileIO(self.table) as original:
            writer.fromOleFile(original)
        writer.editEntry('GameStg/GameData', data=streams['GameStg/GameData'])
        writer.editEntry('GameStg/MAC', data=table_mac(streams))
        writer.write(path)
        for code in (6, 7):
            with self.subTest(code=code), Pinball(table=path, width=320, height=240) as game:
                self.step(game, code, ticks=1)
                escaped = False
                for _ in range(400):
                    state = self.step(game)
                    if state['game_over'] or state['ball'][1] > 1200:
                        escaped = True
                        break
                self.assertTrue(escaped, 'Ball remained trapped at the right target')

    def test_side_outlane_approaches_are_deflected_inward(self):
        for side in (6, 7):
            with self.subTest(side=side), Pinball(table=self.table, width=320, height=240) as game:
                self.step(game, side, ticks=1)
                reached_inside = False
                for _ in range(250):  # Observe every 10ms, not only after a whole frame-skip.
                    state = self.step(game)
                    if state['game_over']:
                        self.assertTrue(reached_inside, 'Drained without being redirected into the playfield')
                        break
                    x, y, z = state['ball']
                    if side == 6 and x > 130 or side == 7 and x < 744:
                        reached_inside = True
                    if 1530 < y < 1650 and z < 60:
                        self.assertTrue(105 < x < 769, (side, x, y, z))
                self.assertTrue(reached_inside, 'Ball did not leave the side-outlane approach')


if __name__ == '__main__':
    unittest.main()
