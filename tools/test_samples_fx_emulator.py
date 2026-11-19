#!/usr/bin/env python3
"""Exercise the Samples DSP port in disposable DigiEmu firmware folders.

Requires a factory-enabled Samples 1.13 GUI snapshot (see analysis/EMULATOR.md),
DigiEmu, patched Unicorn and ColdFire binutils. Never opens MIDI or patches a
source firmware folder. Results and private images stay under build/.
"""
import argparse
import array
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import wave

from build_samples_fx import build
from map_samples_fx import BASE, CAPACITY_SITES, SAMPLE_POOL_BASE, SAMPLE_POOL_CAPACITY, load_stock, audit_samples_pool

ROOT = Path(__file__).resolve().parents[1]


def clone_file(source, dest):
    # CoW keeps the sparse multi-GB card cheap. No hard links to writable input.
    result = subprocess.run(["cp", "-c", str(source), str(dest)], capture_output=True)
    if result.returncode:
        shutil.copy2(source, dest)
    return str(dest)


def put(machine, address, data):
    for page in machine._pages(address, len(data)):
        machine.ensure(page)
    machine.poke(address, data)
    machine.uc.ctl_remove_cache(address, address + len(data))


def install(session, report, payload, stock):
    m = session.m
    read = lambda address, n: bytes(m.uc.mem_read(address, n))
    # No hooks are installed unless the snapshot actually contains stock code
    # at every site. Reject wrong versions, already-patched sessions and large
    # live sample sets before touching either the payload or history region.
    hooks = [(0x40058892, 6), (0x400555B4, 8), (0x40055ADC, 14)]
    if report.get('native_panel_ui'):
        hooks += [(0x4007146C, 10), (0x4001E8D8, 8)]
    from build_samples_firmware import HOOKS
    gate_hooks = [h for h in HOOKS if h[2].startswith(('gate_', 'samples_gate_'))] if report.get('midi_gate') else []
    hooks += [(address, len(bytes.fromhex(old))) for address, old, *_ in gate_hooks]
    for address, n in hooks:
        if read(address, n) != stock[address - BASE:address - BASE + n]:
            raise ValueError(f"snapshot hook site differs from stock: {address:08x}")
    for address, _, _ in CAPACITY_SITES:
        if read(address, 6) != stock[address - BASE:address - BASE + 6]:
            raise ValueError(f"snapshot allocator differs from stock: {address:08x}")
    used = struct.unpack(">I", read(0x40DBF268, 4))[0]
    capacity = SAMPLE_POOL_CAPACITY - report['history_bytes']
    if used > capacity:
        raise ValueError(f"snapshot has too many resident sample bytes: {used}")
    if hashlib.sha256(payload).hexdigest() != report['payload_sha256']:
        raise ValueError("payload digest mismatch")
    syms = report['symbols']
    scratch = report['payload_base']
    for page in m._pages(scratch - 16, len(payload) + 32):
        m.ensure(page)
    if any(read(scratch - 16, len(payload) + 32)):
        raise ValueError('development scratch region is not empty in this snapshot')
    put(m, scratch - 16, b'FX-GUARD-BEFORE!')
    put(m, scratch + len(payload), b'FX-GUARD-AFTER!!')
    put(m, report['payload_base'], payload)
    put(m, report['history_base'], b'\0' * report['history_bytes'])
    for address, _, _ in CAPACITY_SITES:
        put(m, address + 2, struct.pack(">I", capacity))
    # Caller already pushed its two arguments; wrapper tail-calls stock output.
    put(m, 0x40058892, b'\x4e\xb9' + struct.pack('>I', syms['samples_audio']))
    put(m, 0x400555B4, b'\x4e\xf9' + struct.pack('>I', syms['samples_mix']) + b'\x4e\x71')
    # Same stack contract as Cycles: compensate for the original addq #8.
    put(m, 0x40055ADC, b'\x4e\xb9' + struct.pack('>I', syms['mfx_master'])
        + b'\x51\x8f' + b'\x4e\x71' * 3)
    if report.get('native_panel_ui'):
        put(m, 0x4007146C, b'\x4e\xf9' + struct.pack('>I', syms['samples_key']) + b'\x4e\x71' * 2)
        put(m, 0x4001E8D8, b'\x4e\xf9' + struct.pack('>I', syms['pad_hook']) + b'\x4e\x71')
    for address, old, label, _, nops in gate_hooks:
        put(m, address, b'\x4e\xf9' + struct.pack('>I', syms[label]) + b'\x4e\x71' * nops)
    return {'resident_sample_bytes': used, 'reduced_capacity': capacity,
            'sample_pool_base': SAMPLE_POOL_BASE}


def pcm_stats(pcm):
    values = array.array('h', pcm)
    return {'frames': len(pcm) // 4, 'peak': max(map(abs, values), default=0),
            'nonzero': sum(v != 0 for v in values),
            'sha256': hashlib.sha256(pcm).hexdigest()}


def worker(args):
    sys.path.insert(0, str(Path(args.digiemu).resolve()))
    from emu.bootstrap import FirmwarePaths
    from emu.portable import FolderLock
    from emu.session import Session
    from emu import panel

    work = Path(args.work).resolve()
    target = work / args.worker
    source = Path(args.firmware_dir).resolve()
    if target.exists():
        raise ValueError(f"refusing to overwrite {target}; choose a fresh --work")
    # Hold the source lock only while copying a coherent snapshot/card pair.
    with FolderLock(str(source), 'samples-fx-copy').acquire(0):
        shutil.copytree(source, target, copy_function=clone_file,
                        ignore=shutil.ignore_patterns('.lock', 'logs'))
    paths = FirmwarePaths(str(target), 'model-samples_OS1.13.syx',
                          str(Path(args.digiemu).resolve() / 'devices'))
    os.environ.update(paths.env())
    stock = load_stock(paths.main_img, 'samples')
    audit_samples_pool(stock)
    report = json.loads((work / 'payload/samples_fx.json').read_text())
    payload = (work / 'payload/samples_fx.bin').read_bytes()
    result = {'case': args.worker, 'segments': [], 'mode': 'snapshot-injected DSP only'}
    with FolderLock(str(target), 'samples-fx-test').acquire(0):
        s = Session(paths.gui, paths.syx)
        try:
            if args.worker != 'stock':
                result['installation'] = install(s, report, payload, stock)
            symbols = report['symbols']
            def write(name, value):
                put(s.m, symbols[name], struct.pack('>I', value & 0xffffffff))
            def read(name):
                return struct.unpack('>I', s.m.uc.mem_read(symbols[name], 4))[0]
            def run(label, ms):
                start = len(s.pcm)
                s.run_ms(ms)
                if s.halted:
                    raise RuntimeError(s.halted)
                item = {'label': label, **pcm_stats(bytes(s.pcm[start:]))}
                result['segments'].append(item)
                print(json.dumps(item), flush=True)
            s.run_ms(250)
            s.tap(s.code('PLAY'), after_ms=100)
            run('pattern bypass', 1000)
            if args.worker in ('stock', 'bypass'):
                run('record histories', 250)  # identical dry timeline for comparison
            if args.worker in ('exercise', 'dry'):
                # Histories on, but no repeat/effect: should still sound dry.
                write('rtg_on', 1)
                run('record histories', 250)
                assert read('blk_clk') > 0
                # The real ColdFire code, not a Python DSP approximation,
                # consumes signed knob deltas at the next block boundary.
                for knob, value, label in ((1, 90, 'Drive'), (2, 90, 'Crush'),
                                           (3, 90, 'Rate'), (4, 90, 'Pump'),
                                           (5, -90, 'Filter'), (6, 90, 'Resonance'),
                                           (7, 90, 'Ring'), (8, 90, 'Noise'),
                                           (9, 4, 'Gate'), (10, 100, 'Tape'),
                                           (11, 90, 'Vinyl'), (12, 90, 'Flanger')):
                    write('command_reset', 1)
                    run('reset before ' + label, 20)
                    if knob == 6:
                        # Resonance has no audible effect with the filter off.
                        if args.worker == 'exercise':
                            write('command_knob', 6)  # panel Filter
                            write('command_delta', -90)
                        run('set filter before Resonance', 20)
                    if args.worker == 'exercise':
                        write('command_knob', knob + 1)
                        write('command_delta', value)
                    run(label, 250)
                    assert read('command_delta') == 0, 'audio mailbox was not consumed'
                    if args.worker == 'exercise':
                        name = {1: 'mfx_drv', 2: 'mfx_crs', 3: 'mfx_rt',
                                4: 'mfx_pump', 5: 'mfx_filt', 6: 'mfx_res',
                                7: 'mfx_ring', 8: 'mfx_noise', 9: 'mfx_gate',
                                10: 'mfx_tape', 11: 'mfx_vinyl', 12: 'mfx_flg'}[knob]
                        expected = (1 if knob == 9 else value) & 0xffffffff
                        assert read(name) == expected, (name, read(name), expected)
                write('command_reset', 1)
                run('FX reset', 100)
                for name in ('mfx_act', 'mfx_noise', 'mfx_vinyl', 'mfx_filt'):
                    assert read(name) == 0, f'{name} did not reset'
                write('rtg_latch', 1)
                write('rtg_fx', 1)
                if args.worker == 'exercise':
                    write('rtg_lstep', 7)  # 1/6 repeat, zero-based
                run('latched repeat', 500)
                result['repeat_length'] = read('rtg_len')
                if args.worker == 'exercise':
                    assert 0 < result['repeat_length'] < 131072
                    result['return_repeat_wet'] = list(struct.unpack('>4I',
                        s.m.uc.mem_read(symbols['rtg_wet'] + 48, 16)))
                    assert result['return_repeat_wet'] == [65536] * 4
                write('rtg_fx', 0)
                run('FX returns off during repeat', 100)
                assert not any(s.m.uc.mem_read(symbols['rtg_wet'] + 48, 16))
                write('rtg_lstep', -1)
                run('release repeat', 100)
                result['final_repeat_wet'] = read('rtg_wet')
                assert result['final_repeat_wet'] == 0
                # Momentary's newest-held priority and fallback to an older key.
                write('rtg_latch', 0)
                held = symbols['rtg_held']
                for step, serial, expected, label in (
                        (1, 1, 1, 'momentary first'),
                        (4, 2, 4, 'momentary newest'),
                        (4, 0, 1, 'momentary fallback'),
                        (1, 0, 0xffffffff, 'momentary release')):
                    if args.worker == 'exercise':
                        put(s.m, held + step * 4, struct.pack('>I', serial))
                    run(label, 100)
                    if args.worker == 'exercise':
                        assert read('rtg_act') == expected, label
                # Effects persist after the page closes; deselecting tracks fades
                # their stream FX away without resetting the global settings.
                if args.worker == 'exercise':
                    write('command_knob', 2)
                    write('command_delta', 90)
                run('Drive before page close', 100)
                write('rtg_on', 0)
                run('Drive after page close', 100)
                if args.worker == 'exercise':
                    assert read('mfx_wet') == 65536
                write('rtg_sel', 0)
                run('tracks deselected', 100)
                assert read('mfx_wet') == 0
                write('command_reset', 1)
                run('final reset', 100)
            if args.worker != 'stock':
                result['blocks'] = read('blk_clk')
                scratch = report['payload_base']
                assert bytes(s.m.uc.mem_read(scratch - 16, 16)) == b'FX-GUARD-BEFORE!'
                assert bytes(s.m.uc.mem_read(scratch + len(payload), 16)) == b'FX-GUARD-AFTER!!'
                if args.worker in ('exercise', 'dry'):
                    result['history_nonzero_streams'] = [
                        i for i in range(6) if any(s.m.uc.mem_read(
                            report['history_base'] + i * 131072 * 2, 131072 * 2))]
                    assert result['history_nonzero_streams'] == list(range(6))
            panel.write_png(s.screen_at(s.ms), str(target / 'final.png'))
            s.tap(s.code('STOP'))
            result['pcm'] = pcm_stats(s.pcm)
            with wave.open(str(target / 'audio.wav'), 'wb') as wav:
                wav.setnchannels(2)
                wav.setsampwidth(2)
                wav.setframerate(48000)
                wav.writeframes(s.pcm)
        finally:
            s.close()
    (target / 'result.json').write_text(json.dumps(result, indent=2) + '\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--digiemu', required=True)
    ap.add_argument('--firmware-dir', required=True, help='factory-enabled stock Samples folder; never modified')
    ap.add_argument('--work', default=str(ROOT / 'build/samples-emulator-test'))
    ap.add_argument('--worker', choices=('stock', 'bypass', 'dry', 'exercise'), help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.worker:
        worker(args)
        return
    work = Path(args.work).resolve()
    if work.exists():
        raise ValueError(f'refusing to overwrite {work}; choose a fresh --work')
    build(work / 'payload')
    for case in ('stock', 'bypass', 'dry', 'exercise'):
        subprocess.run([sys.executable, str(Path(__file__).resolve()),
                        '--digiemu', args.digiemu, '--firmware-dir', args.firmware_dir,
                        '--work', str(work), '--worker', case], check=True)
    results = {case: json.loads((work / case / 'result.json').read_text())
               for case in ('stock', 'bypass', 'dry', 'exercise')}
    baseline = results['stock']['segments'][0]
    bypass = results['bypass']['segments'][0]
    results['bypass_pcm_identical'] = baseline['sha256'] == bypass['sha256']
    dry = {seg['label']: seg for seg in results['dry']['segments']}
    wet = {seg['label']: seg for seg in results['exercise']['segments']}
    labels = ('Drive', 'Crush', 'Rate', 'Pump', 'Filter', 'Resonance', 'Ring',
              'Noise', 'Gate', 'Tape', 'Vinyl', 'Flanger', 'latched repeat')
    results['effect_changes_pcm'] = {
        label: dry[label]['sha256'] != wet[label]['sha256'] for label in labels}
    results['history_recording_is_dry'] = (
        results['stock']['segments'][1]['sha256'] ==
        dry['record histories']['sha256'] == wet['record histories']['sha256'])
    (work / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    print(f'Results: {work / "results.json"}')
    if not results['bypass_pcm_identical']:
        raise AssertionError('bypass PCM differs from stock; inspect captures before proceeding')
    if not results['history_recording_is_dry'] or not all(results['effect_changes_pcm'].values()):
        raise AssertionError('dry/wet comparison failed; inspect results.json')


if __name__ == '__main__':
    main()
