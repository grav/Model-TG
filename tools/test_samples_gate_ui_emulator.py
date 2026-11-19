#!/usr/bin/env python3
"""Exercise the PR #27 menu on a cold-built standalone Samples DigiEmu profile.

Never edits the input profile or opens a MIDI device. Requires the GUI snapshot
produced by DigiEmu's firmware check / first boot, not a patched stock snapshot.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

from build_samples_firmware import CACHE_BASE
from map_samples_fx import BASE
from test_samples_fx_emulator import clone_file


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--digiemu', required=True)
    ap.add_argument('--firmware-dir', required=True)
    ap.add_argument('--payload-report', required=True)
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
    source = Path(args.firmware_dir).resolve()
    report = json.loads(Path(args.payload_report).read_text())
    if not report.get('cold_boot') or not report.get('midi_gate') or report['payload_base'] != CACHE_BASE:
        raise ValueError('requires a standalone MIDI-gate payload report')
    target = work / 'firmware'
    with FolderLock(str(source), 'samples-gate-copy'):
        shutil.copytree(source, target, copy_function=clone_file,
                        ignore=shutil.ignore_patterns('.lock', 'logs'))
    syx = list(target.glob('*.syx'))
    if len(syx) != 1:
        raise ValueError('expected one firmware container in the profile')
    paths = FirmwarePaths(str(target), syx[0].name,
                          str(Path(args.digiemu).resolve() / 'devices'))
    image = Path(paths.main_img).read_bytes()
    payload = image[CACHE_BASE - BASE:CACHE_BASE - BASE + report['payload_bytes']]
    if hashlib.sha256(payload).hexdigest() != report['payload_sha256']:
        raise ValueError('profile does not contain the specified standalone payload')
    os.environ.update(paths.env())
    observations = []
    with FolderLock(str(target), 'samples-gate-ui'):
        s = Session(paths.gui, paths.syx, ddr=128 * 1024 * 1024)
        def read(name):
            return int.from_bytes(s.m.uc.mem_read(report['symbols'][name], 4), 'big')
        def capture(label):
            if s.halted:
                raise RuntimeError(s.halted)
            item = {'label': label, **{n: read(n) for n in
                    ('gate_mode', 'gate_active', 'gate_level', 'gate_timer', 'gate_count')}}
            observations.append(item)
            frame = s.screen_at(s.ms)
            if frame:
                panel.write_png(frame, str(work / (label + '.png')))
            print(json.dumps(item), flush=True)
        try:
            s.run_ms(250)
            assert read('gate_mode') == read('gate_active') == 0
            s.tap(s.code('SETTINGS'))
            for _ in range(7):
                s.turn(4, 1)
            s.tap(32)  # Device (8/8)
            capture('device-open')
            for _ in range(4):
                s.turn(4, 1)
            capture('gate-off')  # appended fifth row, after Contrast
            s.tap(32)  # select editing, without changing OFF
            assert read('gate_mode') == 0
            for expected in range(1, 7):
                s.turn(4, 1)
                capture(f'mode-{expected}')
                assert read('gate_mode') == expected
                assert read('gate_active') == expected
                assert read('gate_level') == (0 if expected == 5 else 1)
            s.turn(4, 1)
            assert read('gate_mode') == 6
            for expected in range(5, -1, -1):
                s.turn(4, -1)
                assert read('gate_mode') == read('gate_active') == expected
            s.turn(4, -1)
            assert read('gate_mode') == 0
            capture('restored-midi')
            s.tap(s.code('BACK'))  # stop editing
            s.tap(s.code('BACK'))  # root config
            s.tap(s.code('BACK'))  # home
            # Constructor ran once at boot; reopening must not duplicate rows.
            s.tap(s.code('SETTINGS'))
            s.tap(32)
            capture('device-reopened')
            assert read('gate_mode') == read('gate_active') == 0
        finally:
            s.close()
            (work / 'gate-ui-results.json').write_text(json.dumps(observations, indent=2) + '\n')
            (work / 'panel-inputs.json').write_text(json.dumps(s.inputs, indent=2) + '\n')
    print(f'Standalone gate menu checks passed: {work}')


if __name__ == '__main__':
    main()
