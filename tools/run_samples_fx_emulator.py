#!/usr/bin/env python3
"""Launch DigiEmu with the native Samples retrig/FX page in a disposable copy.

This does not install firmware or modify the source card/snapshots. Close the
source panel first. The development payload is injected in guest RAM after
restoring its stock GUI snapshot; all panel handling executes in ColdFire code.
"""
import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
import sys

from build_samples_fx import ROOT, build
from map_samples_fx import load_stock
from test_samples_fx_emulator import clone_file, install


def panel_overlay(text):
    """Make mouse chords possible; keep every physical wire/code unchanged."""
    import tomllib
    text = text.replace('32 = "PITCH"', '32 = "DATA"')
    keys = 'codes = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 32]'
    if keys in text:
        text = text.replace(keys, 'codes = [4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 32]')
        text += ('\n[[panel.group]]\nname = "modifiers"\nkind = "button"\n'
                 'codes = [1, 2, 3, 13]\nlayout = "row"\n')
    panel = tomllib.loads(text)['panel']
    if not any(g['name'] == 'modifiers' and 13 in g['codes'] for g in panel['group']):
        raise ValueError('DigiEmu panel layout changed: SETTINGS must be mouse-latchable')
    return text


def prepare_tk():
    """Borrow matching bundled Tk on Macs whose checkout Python lacks it."""
    try:
        import tkinter  # noqa: F401
        return
    except ModuleNotFoundError as error:
        if error.name != '_tkinter' or sys.platform != 'darwin':
            raise
    frameworks = Path('/Applications/digiemu.app/Contents/Frameworks')
    tag = f'{sys.version_info.major}{sys.version_info.minor}'
    matches = list(frameworks.glob(f'python*/lib-dynload/_tkinter.cpython-{tag}-darwin.so'))
    if not matches:
        raise RuntimeError('This Python needs Tk support. Use DigiEmu\'s Python '
                           'version or install the matching python-tk package.')
    sys.path.append(str(matches[0].parent))
    os.environ.setdefault('TCL_LIBRARY', str(frameworks / '_tcl_data'))
    os.environ.setdefault('TK_LIBRARY', str(frameworks / '_tk_data'))
    import tkinter  # noqa: F401


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--digiemu', required=True, help='DigiEmu source checkout')
    ap.add_argument('--firmware-dir', required=True, help='factory-enabled stock Samples 1.13 folder')
    ap.add_argument('--work', help='new disposable folder; defaults to a timestamp under build/')
    ap.add_argument('--scale', type=int, default=4)
    args = ap.parse_args()
    prepare_tk()
    checkout = Path(args.digiemu).resolve()
    sys.path.insert(0, str(checkout))
    from emu.bootstrap import FirmwarePaths
    from emu.portable import FolderLock
    work = Path(args.work).resolve() if args.work else ROOT / 'build' / (
        'samples-panel-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    if work.exists():
        raise ValueError(f'refusing to overwrite {work}')
    report = build(work / 'payload')
    source = Path(args.firmware_dir).resolve()
    target = work / 'firmware'
    with FolderLock(str(source), 'samples-fx-panel-copy'):
        shutil.copytree(source, target, copy_function=clone_file,
                        ignore=shutil.ignore_patterns('.lock', 'logs'))
    paths = FirmwarePaths(str(target), 'model-samples_OS1.13.syx', str(checkout / 'devices'))
    # Correct the stock emulator's label for its DATA push switch (wire/code
    # unchanged). Keep this overlay inside the disposable copy only.
    overlay = target / 'devices'
    overlay.mkdir(exist_ok=True)
    device_file = overlay / 'model-samples.toml'
    source_device = device_file if device_file.exists() else checkout / 'devices/model-samples.toml'
    labels = panel_overlay(source_device.read_text())
    device_file.write_text(labels)
    os.environ.update(paths.env())
    stock = load_stock(paths.main_img, 'samples')
    payload = (work / 'payload/samples_fx.bin').read_bytes()
    from emu import gui
    stock_build = gui.build
    def patched_build(*build_args, **kwargs):
        result = stock_build(*build_args, **kwargs)
        install(SimpleNamespace(m=result[0]), report, payload, stock)
        return result
    gui.build = patched_build
    print(f'Disposable emulator: {target}', flush=True)
    print('Click SETTINGS to latch, click RETRIG, click SETTINGS again to release.', flush=True)
    print('BACK resets FX; RETRIG closes the page. Click latch/clear if a modifier is stuck.', flush=True)
    print('Turn LEVEL/DATA to select/edit a row; click the DATA button to toggle editing.', flush=True)
    with FolderLock(str(target), 'samples-fx-panel'):
        gui.App(paths.gui, syx=paths.syx, scale=max(1, args.scale)).mainloop()


if __name__ == '__main__':
    main()
