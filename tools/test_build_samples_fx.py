#!/usr/bin/env python3
"""Firmware-free tests for the Samples emulator DSP build."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import tempfile
from types import SimpleNamespace
import unittest

from build_samples_fx import ADDRESS_MAP, ROOT, PAYLOAD_BASE, build, section, shared_source, ui_source, gate_source
from run_samples_fx_emulator import panel_overlay
from map_samples_fx import SAMPLE_POOL_CAPACITY
from test_samples_fx_emulator import install


class SourceExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = (ROOT / 'src/model_tg.s').read_text()
        cls.port = shared_source(cls.shared)

    def test_audio_not_sampler_or_view_construction(self):
        for label in ('rtg_audio:', 'rtg_stream:', 'rtg_fxpass:', 'mfx_master:',
                      'mfx_stream:', 'mfx_coef:', 'sys_dec:', 'rtg_env:'):
            self.assertEqual(self.port.count('\n' + label), 1, label)
        for label in ('sampler_voice:', 'rtg_open:', 'pad_hook:', 'rtg_render:', 'mm_open:'):
            self.assertNotIn('\n' + label, self.port)

    def test_all_known_cycles_runtime_addresses_are_relocated(self):
        code = '\n'.join(line.partition('|')[0] for line in self.port.splitlines())
        for old in ADDRESS_MAP:
            self.assertNotIn(f'0x{old:08x}', code.lower())
        self.assertNotIn('0x4006f73a', code)
        self.assertIn('0x80001b48', code)
        self.assertIn('0x8000c690', code)

    def test_direct_knob_delta_not_stock_event_api(self):
        entry = section(self.port, '\nmfx_knob:\n', '\nmfk_no:')
        self.assertTrue(entry.lstrip().startswith('tstl'))
        self.assertNotIn('jsr', entry)

    def test_changed_boundary_is_rejected(self):
        with self.assertRaises(ValueError):
            shared_source(self.shared.replace('\nrtg_want:\n', '\nrenamed:\n'))

    def test_ambiguous_boundary_is_rejected(self):
        with self.assertRaises(ValueError):
            section('a START b START c END', 'START', 'END')

    def test_unknown_absolute_runtime_dependency_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unmapped runtime dependency'):
            shared_source(self.shared.replace('movel   0x40149310,%d5',
                                             'movel   0x40dead00,%d5'))

    def test_changed_knob_entry_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'knob entry changed'):
            shared_source(self.shared.replace('jsr     0x4006f73a', 'jsr     0x4006f73c'))


class GateSourceTests(unittest.TestCase):
    def test_gate_and_framework_dependencies_are_relocated(self):
        text = gate_source((ROOT / 'src/model_tg.s').read_text())
        code = '\n'.join(line.partition('|')[0] for line in text.splitlines())
        for old in ('0x4049dca0', '0x4049dcbc', '0x4049dccc', '0x40a7883c',
                    '0x40076082', '0x40fe4278', '0x40140ab0', '0x400732f8', '0x400732ec'):
            self.assertNotIn(old, code.lower())
        for new in ('0x404acb14', '0x404acb30', '0x404acb40', '0x4096814c',
                    '0x40072358', '0x40034030'):
            self.assertIn(new, code.lower())

    def test_unknown_gate_helper_dependency_is_rejected(self):
        shared = (ROOT / 'src/model_tg.s').read_text()
        with self.assertRaisesRegex(ValueError, 'unmapped gate dependency'):
            gate_source(shared.replace('jsr     0x400732f8', 'jsr     0x40dead00'))


class NativeUISourceTests(unittest.TestCase):
    def test_shared_handlers_and_renderer_are_relocated(self):
        text = ui_source((ROOT / 'src/model_tg.s').read_text())
        code = '\n'.join(line.partition('|')[0] for line in text.splitlines())
        for label in ('rtg_render:', 'sys_left:', 'rtg_zero:', 'pad_hook:', 'kh_rtg:'):
            self.assertIn(label, code)
        for old in ('0x40070dea', '0x40071a04', '0x401001d0', '0x4001d188', '0x40124b58'):
            self.assertNotIn(old, code)
        self.assertIn('sp_redraw', code)
        self.assertIn('0x4001e8e0', code)
        self.assertIn('sp_fmt_s', code)

    def test_overlay_keeps_input_codes_and_makes_settings_latchable(self):
        import tomllib
        source = '''[panel.labels]
32 = "PITCH"
[[panel.group]]
name = "keys"
kind = "button"
codes = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 32]
layout = "row"
'''
        overlay = panel_overlay(source)
        result = tomllib.loads(overlay)['panel']
        self.assertEqual(result['labels']['32'], 'DATA')
        groups = result['group']
        modifiers = next(g for g in groups if g['name'] == 'modifiers')
        self.assertIn(13, modifiers['codes'])
        codes = [c for group in groups for c in group['codes']]
        self.assertEqual(sorted(codes), list(range(1, 16)) + [32])
        self.assertEqual(panel_overlay(overlay), overlay)


    def test_unknown_gui_layout_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'panel layout changed'):
            panel_overlay('[panel.labels]\n32="PITCH"\n[[panel.group]]\n'
                          'name="keys"\nkind="button"\ncodes=[13,32]\n')


class InjectionSafetyTests(unittest.TestCase):
    def setUp(self):
        self.stock = bytes(0xA1800)
        self.mem = {}
        def read(address, size):
            return bytes(self.mem.get(address + i, 0) for i in range(size))
        # Rejection must happen before any guest writes or mapping changes.
        self.session = SimpleNamespace(m=SimpleNamespace(uc=SimpleNamespace(mem_read=read)))
        self.report = {'history_bytes': 0x400000,
                       'payload_sha256': hashlib.sha256(b'payload').hexdigest()}

    def test_changed_hook_is_rejected_before_guest_writes(self):
        self.mem[0x40058892] = 0xff
        with self.assertRaisesRegex(ValueError, 'hook site differs'):
            install(self.session, self.report, b'payload', self.stock)

    def test_changed_ui_hook_is_rejected_before_guest_writes(self):
        self.report['native_panel_ui'] = True
        self.mem[0x4007146C] = 0xff
        with self.assertRaisesRegex(ValueError, 'hook site differs'):
            install(self.session, self.report, b'payload', self.stock)

    def test_changed_gate_hooks_are_rejected_before_guest_writes(self):
        self.report['midi_gate'] = True
        for address in (0x40001154, 0x4000124e, 0x40001320, 0x4003402a):
            with self.subTest(address=address):
                self.mem[address] = 0xff
                with self.assertRaisesRegex(ValueError, 'hook site differs'):
                    install(self.session, self.report, b'payload', self.stock)
                self.mem.clear()

    def test_changed_capacity_is_rejected_before_guest_writes(self):
        self.mem[0x400A12A6] = 0xff
        with self.assertRaisesRegex(ValueError, 'allocator differs'):
            install(self.session, self.report, b'payload', self.stock)

    def test_large_sample_set_is_rejected_before_guest_writes(self):
        used = SAMPLE_POOL_CAPACITY - self.report['history_bytes'] + 16
        self.mem.update({0x40DBF268 + i: value for i, value in
                         enumerate(struct.pack('>I', used))})
        with self.assertRaisesRegex(ValueError, 'too many resident'):
            install(self.session, self.report, b'payload', self.stock)

    def test_corrupt_payload_is_rejected_before_guest_writes(self):
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            install(self.session, self.report, b'corrupt', self.stock)


@unittest.skipUnless(shutil.which('m68k-elf-as') or shutil.which('m68k-linux-gnu-as'),
                     'ColdFire binutils not installed')
class PayloadBuildTests(unittest.TestCase):
    def test_links_without_vendor_firmware_and_is_reproducible(self):
        with tempfile.TemporaryDirectory() as folder:
            a = build(Path(folder) / 'a')
            b = build(Path(folder) / 'b')
            self.assertEqual(a, b)
            self.assertFalse(a['hardware_installable'])
            self.assertTrue(a['native_panel_ui'])
            self.assertTrue(a['midi_gate'])
            self.assertEqual(a['payload_base'], PAYLOAD_BASE)
            self.assertLess(a['payload_bytes'], 65536)
            for label in ('samples_audio', 'samples_mix', 'samples_key', 'page_obj',
                          'sp_encoder', 'sp_render', 'pad_hook', 'rtg_lstep', 'mfx_drv',
                          'command_knob', 'command_delta', 'command_reset', 'gate_service',
                          'gate_tx_buffer', 'gate_tx_byte', 'gate_mode', 'samples_gate_config'):
                self.assertGreaterEqual(a['symbols'][label], PAYLOAD_BASE)
                self.assertLess(a['symbols'][label], PAYLOAD_BASE + a['payload_bytes'])
            binary = (Path(folder) / 'a/samples_fx.bin').read_bytes()
            self.assertEqual(hashlib.sha256(binary).hexdigest(), a['payload_sha256'])
            self.assertEqual(json.loads((Path(folder) / 'a/samples_fx.json').read_text()), a)


if __name__ == '__main__':
    unittest.main()
