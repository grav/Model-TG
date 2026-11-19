"""Execute PR #22's shared FX snap logic as ColdFire at standalone Samples addresses."""
from pathlib import Path
import shutil
import struct
import tempfile
import unittest

from build_samples_fx import build
from build_samples_firmware import CACHE_BASE

CONTROLS = ('mfx_drv', 'mfx_crs', 'mfx_rt', 'mfx_pump', 'mfx_filt', 'mfx_res',
            'mfx_ring', 'mfx_noise', 'mfx_gate', 'mfx_tape', 'mfx_vinyl', 'mfx_flg')


@unittest.skipUnless(shutil.which('m68k-elf-as') or shutil.which('m68k-linux-gnu-as'),
                     'ColdFire binutils not installed')
class SnapExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import unicorn
            from unicorn import m68k_const
        except ImportError:
            raise unittest.SkipTest('run with DigiEmu Python to execute ColdFire snap tests')
        cls.u, cls.r = unicorn, m68k_const
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.report = build(cls.temp.name, payload_base=CACHE_BASE, cold_boot=True)
        cls.payload = (Path(cls.temp.name) / 'samples_fx.bin').read_bytes()
        cls.symbols = cls.report['symbols']
        cls.uc = unicorn.Uc(unicorn.UC_ARCH_M68K, unicorn.UC_MODE_BIG_ENDIAN)
        cls.uc.ctl_set_cpu_model(m68k_const.UC_CPU_M68K_CFV4E)
        cls.uc.mem_map(CACHE_BASE & ~0xffff, 0x10000)
        cls.stack, cls.stop = 0x47ff0800, 0x47000000
        cls.uc.mem_map(cls.stack & ~0xfff, 0x1000)
        cls.uc.mem_map(cls.stop, 0x1000)

    def write(self, name, value):
        self.uc.mem_write(self.symbols[name], struct.pack('>I', value & 0xffffffff))

    def read(self, name):
        return struct.unpack('>i', self.uc.mem_read(self.symbols[name], 4))[0]

    def reset(self, func=True):
        self.uc.mem_write(CACHE_BASE, self.payload)
        self.write('rtg_func', int(func))

    def turn(self, logical, delta):
        r = self.r
        self.uc.reg_write(r.UC_M68K_REG_SR, 0x2700)
        self.uc.reg_write(r.UC_M68K_REG_A7, self.stack)
        self.uc.mem_write(self.stack, struct.pack('>I', self.stop))
        self.uc.reg_write(r.UC_M68K_REG_D0, delta & 0xffffffff)
        registers = (r.UC_M68K_REG_D2, r.UC_M68K_REG_D3, r.UC_M68K_REG_D4,
                     r.UC_M68K_REG_D5, r.UC_M68K_REG_D6, r.UC_M68K_REG_D7)
        for i, register in enumerate(registers):
            self.uc.reg_write(register, logical if i == 1 else 0x12340000 + i)
        self.uc.emu_start(self.symbols['mfx_knob'], self.stop, count=100000)
        self.assertEqual(self.uc.reg_read(r.UC_M68K_REG_PC), self.stop)
        self.assertEqual(self.uc.reg_read(r.UC_M68K_REG_A7), self.stack + 4)
        for i, register in enumerate(registers):
            self.assertEqual(self.uc.reg_read(register), logical if i == 1 else 0x12340000 + i)
        return self.uc.reg_read(r.UC_M68K_REG_D0)

    def test_all_6168_snap_cases_and_normal_setter_side_effects(self):
        cases = 0
        for logical, name in enumerate(CONTROLS, 2):
            minimum, maximum = (-127 if logical == 6 else 0), (6 if logical == 10 else 127)
            for current in range(minimum, maximum + 1):
                for delta in (-4, -1, 1, 4):
                    self.reset()
                    self.write(name, current)
                    expected = (0 if current < 0 else maximum) if delta > 0 else (0 if current > 0 else minimum)
                    with self.subTest(knob=logical, value=current, delta=delta):
                        self.assertEqual(self.turn(logical, delta), 1)
                        self.assertEqual(self.read(name), expected)
                        if logical == 6:
                            self.assertEqual(self.read('mfx_on'), int(expected != 0))
                            self.assertEqual(self.read('mfx_fwait'), int(current != 0 and expected == 0))
                            self.assertEqual(self.read('mfx_fsteps'), 0)
                        if logical == 3:
                            self.assertEqual(self.read('mfx_mask'), -1 if expected == 0 else -2147483648)
                        if logical == 4:
                            self.assertEqual(self.read('mfx_rinc'), 65536 if expected == 0 else 1365)
                    cases += 1
        self.assertEqual(cases, 6168)

    def test_filter_holds_for_four_fresh_clicks_from_either_side(self):
        for initial, direction in ((-50, 1), (50, -1)):
            self.reset()
            self.write('mfx_filt', initial)
            self.turn(6, direction)
            self.assertEqual(self.read('mfx_filt'), 0)
            self.assertEqual(self.read('mfx_fwait'), 1)
            for click in range(1, 4):
                self.assertEqual(self.turn(6, direction), 0)
                self.assertEqual(self.read('mfx_filt'), 0)
                self.assertEqual(self.read('mfx_fsteps'), click * direction)
            self.turn(6, direction)
            self.assertEqual(self.read('mfx_filt'), direction * 127)
            self.assertEqual(self.read('mfx_fwait'), 0)
            self.assertEqual(self.read('mfx_fsteps'), 0)

    def test_filter_hold_uses_net_travel_and_both_escape_directions(self):
        self.reset()
        self.write('mfx_filt', -50)
        self.turn(6, 1)
        for delta, total in ((1, 1), (1, 2), (-1, 1), (-1, 0), (-1, -1), (-1, -2), (-1, -3)):
            self.turn(6, delta)
            self.assertEqual(self.read('mfx_filt'), 0)
            self.assertEqual(self.read('mfx_fsteps'), total)
        self.turn(6, -1)
        self.assertEqual(self.read('mfx_filt'), -127)

    def test_zero_delta_invalid_indices_and_plain_turns(self):
        for logical, name in enumerate(CONTROLS, 2):
            self.reset()
            self.write(name, 3)
            self.assertEqual(self.turn(logical, 0), 0)
            self.assertEqual(self.read(name), 3)
        for logical in (0, 1, 14, 15, 100):
            self.reset()
            self.assertEqual(self.turn(logical, 1), 0)
        self.reset(func=False)
        self.turn(2, 4)
        self.assertEqual(self.read('mfx_drv'), 4)
        self.turn(6, -4)
        self.assertEqual(self.read('mfx_filt'), -4)
        self.turn(10, 4)
        self.assertEqual(self.read('mfx_gate'), 1)


if __name__ == '__main__':
    unittest.main()
