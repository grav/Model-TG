#!/usr/bin/env python3
"""Native panel-input integration test for the Samples retrig page."""
import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import wave

from build_samples_fx import build
from map_samples_fx import load_stock
from test_samples_fx_emulator import clone_file, install


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--digiemu', required=True)
    ap.add_argument('--firmware-dir', required=True)
    ap.add_argument('--work', required=True)
    args = ap.parse_args()
    sys.path.insert(0, str(Path(args.digiemu).resolve()))
    from emu.bootstrap import FirmwarePaths
    from emu.portable import FolderLock
    from emu.session import Session
    from emu import panel
    work = Path(args.work).resolve()
    if work.exists():
        raise ValueError(f'refusing to overwrite {work}')
    report = build(work / 'payload')
    source = Path(args.firmware_dir).resolve()
    target = work / 'firmware'
    with FolderLock(str(source), 'samples-ui-copy'):
        shutil.copytree(source, target, copy_function=clone_file,
                        ignore=shutil.ignore_patterns('.lock', 'logs'))
    paths = FirmwarePaths(str(target), 'model-samples_OS1.13.syx',
                          str(Path(args.digiemu).resolve() / 'devices'))
    os.environ.update(paths.env())
    stock = load_stock(paths.main_img, 'samples')
    payload = (work / 'payload/samples_fx.bin').read_bytes()
    observations = []
    with FolderLock(str(target), 'samples-ui-test'):
        s = Session(paths.gui, paths.syx)
        install(s, report, payload, stock)
        syms = report['symbols']
        from unicorn import UC_HOOK_CODE
        from unicorn.m68k_const import UC_M68K_REG_A7
        acceleration = []
        def acceleration_probe(uc, address, size, user):
            stack = uc.reg_read(UC_M68K_REG_A7)
            caller, _, minimum, maximum = struct.unpack('>IIII', uc.mem_read(stack, 16))
            if report['payload_base'] <= caller < report['payload_base'] + report['payload_bytes']:
                acceleration.append({'logical': read('sp_last_encoder'),
                                     'func': read('rtg_func'), 'minimum': minimum,
                                     'maximum': maximum})
        s.m.uc.hook_add(UC_HOOK_CODE, acceleration_probe, begin=0x4006e79a, end=0x4006e79a)
        def read(name):
            return struct.unpack('>I', s.m.uc.mem_read(syms[name], 4))[0]
        def run(ms=150):
            s.run_ms(ms)
            if s.halted:
                raise RuntimeError(s.halted)
        def capture(label):
            item = {name: read(name) for name in ('page_obj', 'rtg_on', 'rtg_row',
                    'rtg_edit', 'rtg_latch', 'rtg_lstep', 'rtg_sel', 'mfx_drv',
                    'rtg_func', 'mfx_filt', 'mfx_fwait', 'mfx_fsteps')}
            item['label'] = label
            print(json.dumps(item), flush=True)
            observations.append(item)
            frame = s.screen_at(s.ms)
            if frame:
                panel.write_png(frame, str(work / (label + '.png')))
        try:
            run(250)
            s.press(s.code('SETTINGS')); run(100)
            s.tap(s.code('RETRIG'), after_ms=100)
            s.release(s.code('SETTINGS')); run(250)
            capture('opened')
            assert read('page_obj') != 0 and read('rtg_on') == 1, 'page did not open'
            s.tap(s.code('PLAY'), after_ms=250)
            # Newest-held key wins; releasing it falls back to the older key.
            s.press(s.code('5')); run(150)
            capture('momentary-held')
            assert read('rtg_act') == 4
            s.press(s.code('9')); run(100)
            assert read('rtg_act') == 8
            s.release(s.code('9')); run(100)
            assert read('rtg_act') == 4
            s.release(s.code('5')); run(150)
            assert read('rtg_act') == 0xffffffff
            s.tap(s.code('T2'))
            capture('track-two-off')
            assert read('rtg_sel') == 0x3d
            # Physical scan encoder 13 is Pitch (panel knob 1 / Drive).
            s.turn(13, 5)
            capture('drive')
            assert read('mfx_drv') > 0, 'physical Pitch knob did not control Drive'
            controls = ((13, 'mfx_drv'), (1, 'mfx_crs'), (2, 'mfx_rt'),
                        (3, 'mfx_pump'), (14, 'mfx_filt'), (5, 'mfx_res'),
                        (6, 'mfx_ring'), (7, 'mfx_noise'), (15, 'mfx_gate'),
                        (9, 'mfx_tape'), (10, 'mfx_vinyl'), (11, 'mfx_flg'))
            for logical, (physical, state) in enumerate(controls, 2):
                s.tap(s.code('BACK'), after_ms=50)
                s.turn(physical, 5)
                assert read('sp_last_encoder') == logical, (physical, logical)
                assert read(state) > 0, (physical, state, read(state))
            capture('all-knobs')
            s.tap(s.code('BACK'))
            # PR #22: real FUNC input and physical encoders, no mailbox/state writes.
            func = s.code('FUNCTION')
            s.press(func); run(100)
            assert read('rtg_func') == 1
            for logical, (physical, state) in enumerate(controls, 2):
                s.turn(physical, 1)
                assert read(state) == (6 if logical == 10 else 127), (physical, state)
                s.turn(physical, -1)
                assert read(state) == 0, (physical, state)
            capture('func-all-knobs')
            s.release(func); run(100)
            assert read('rtg_func') == read('mfx_fwait') == read('mfx_fsteps') == 0
            s.turn(14, -5)
            assert read('mfx_filt') & 0x80000000
            s.press(func); run(100)
            s.turn(14, 1)
            assert read('mfx_filt') == 0 and read('mfx_fwait') == 1
            for click in range(1, 4):
                # Short-spaced physical events exercise the Filter hold.
                s.turn(14, 1, after_ms=70)
                assert read('mfx_filt') == 0 and read('mfx_fsteps') == click
            s.turn(14, 1, after_ms=70)
            assert read('mfx_filt') == 127 and read('mfx_fwait') == 0
            capture('func-filter-four-clicks')
            s.turn(14, -1)
            assert read('mfx_filt') == 0 and read('mfx_fwait') == 1
            for delta, steps in ((-1, -1), (-1, -2), (1, -1)):
                s.turn(14, delta, after_ms=70)
                assert read('mfx_filt') == 0
                assert read('mfx_fsteps') == (steps & 0xffffffff)
            s.turn(14, -3)
            assert read('mfx_filt') == 0xffffff81  # -127 LP
            s.turn(14, 1)
            assert read('mfx_filt') == 0 and read('mfx_fwait') == 1
            s.release(func); run(100)
            assert read('mfx_fwait') == read('mfx_fsteps') == 0
            s.press(func); run(100)
            s.turn(14, 1)
            assert read('mfx_filt') == 127  # fresh gesture may leave zero immediately
            s.release(func); run(100)
            s.turn(14, -1)
            assert 0 < read('mfx_filt') < 127  # ordinary additive control restored
            s.press(func); run(100)
            s.turn(14, -1)
            assert read('mfx_filt') == 0 and read('mfx_fwait') == 1
            s.tap(s.code('RETRIG'))
            s.release(func); run(100)  # release outside the page is not tracked
            assert read('rtg_on') == 0
            s.press(s.code('SETTINGS')); run(100)
            s.tap(s.code('RETRIG'), after_ms=100)
            s.release(s.code('SETTINGS')); run(150)
            assert read('rtg_on') == 1
            assert read('rtg_func') == read('mfx_fwait') == read('mfx_fsteps') == 0
            capture('func-reopen-cleared')
            s.tap(s.code('BACK'))
            # DATA push is stock key code 32 (currently labelled PITCH in DigiEmu).
            s.tap(32)
            capture('data-edit')
            assert read('rtg_edit') == 1
            s.turn(4, 1)
            capture('latch-mode')
            assert read('rtg_latch') == 1
            s.tap(s.code('8'))
            capture('latched-repeat')
            assert read('rtg_lstep') == 7 and read('rtg_act') == 7
            s.tap(s.code('BACK'))
            capture('reset')
            assert read('mfx_act') == 0 and read('rtg_lstep') == 0xffffffff
            # Leave mode editing, move to the FX RETURNS row, edit it.
            s.tap(32)
            s.turn(4, 1)
            assert read('rtg_row') == 1
            s.tap(32)
            s.turn(4, 1)
            capture('returns-on')
            assert read('rtg_fx') == 1
            s.turn(4, -1)
            assert read('rtg_fx') == 0
            # FX survive closing; Settings+Back turns them off globally.
            s.turn(13, 5)
            s.tap(s.code('RETRIG'))
            capture('closed')
            assert read('page_obj') == 0 and read('rtg_on') == 0
            assert read('mfx_drv') > 0
            s.press(s.code('SETTINGS')); run(100)
            s.tap(s.code('BACK'), after_ms=100)
            s.release(s.code('SETTINGS')); run(150)
            assert read('mfx_act') == 0
            # Reopen and close repeatedly to exercise reference-holder cleanup.
            for i in range(3):
                s.press(s.code('SETTINGS')); run(100)
                s.tap(s.code('RETRIG'), after_ms=100)
                s.release(s.code('SETTINGS')); run(150)
                assert read('page_obj') != 0 and read('rtg_on') == 1
                s.tap(s.code('RETRIG'))
                assert read('page_obj') == 0
            capture('reopened-and-closed')
            s.press(s.code('SETTINGS')); run(100)
            s.tap(s.code('RETRIG'), after_ms=100)
            s.release(s.code('SETTINGS')); run(150)
            assert read('rtg_on') == 1
            s.tap(s.code('PATTERN'))
            capture('pattern-closes-page')
            assert read('page_obj') == 0 and read('rtg_on') == 0
            s.tap(s.code('BACK'))
            s.tap(s.code('STOP'))
            # A plain Settings tap must still reach the stock config menu.
            s.tap(s.code('SETTINGS'))
            capture('stock-settings')
            assert read('page_obj') == 0
            s.tap(s.code('BACK'))
            assert {e['maximum'] for e in acceleration if e['logical'] == 6 and e['func']} == {1}
            assert {e['maximum'] for e in acceleration if e['logical'] == 6 and not e['func']} == {4}
            assert {e['maximum'] for e in acceleration if e['logical'] == 1} == {1}
            assert {e['maximum'] for e in acceleration if e['logical'] not in (1, 6) and e['func']} == {4}
        finally:
            s.close()
            (work / 'ui-results.json').write_text(json.dumps(observations, indent=2) + '\n')
            (work / 'panel-inputs.json').write_text(json.dumps(s.inputs, indent=2) + '\n')
            (work / 'acceleration.json').write_text(json.dumps(acceleration, indent=2) + '\n')
            with wave.open(str(work / 'audio.wav'), 'wb') as wav:
                wav.setnchannels(2)
                wav.setsampwidth(2)
                wav.setframerate(48000)
                wav.writeframes(s.pcm)
    print(f'Native UI checks passed: {work}')


if __name__ == '__main__':
    main()
