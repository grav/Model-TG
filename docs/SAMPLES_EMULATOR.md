# Model:Samples retrig/master FX in DigiEmu

**Interactive emulator prototype. An experimental standalone `.syx` is now
available locally; it is not validated or approved for physical hardware.**

You can now use the emulator's panel to open the retrig page, play momentary or
latched repeats, select tracks with the pads and adjust all twelve master FX.
The handlers and screen renderer are **native ColdFire firmware code**, not
Python input interception or host-side DSP. Stock Samples playback, factory
samples and project/sample formats remain in use.

## Generate a standalone firmware file

The Samples-only builder now packages the native DSP/UI and cold-boot hook into
a real Model:Samples update container, starting from **your own** stock OS 1.13:

```sh
python3 tools/build_samples_firmware.py \
  --stock /path/to/model-samples_OS1.13.zip \
  --tool build/elektron-firmware-tool/elektron-firmware-tool \
  --out build/Model-TG-Samples-experimental.syx
```

`--stock` also accepts the extracted `.syx`. The builder refuses an existing
output/work folder, pins the stock MAIN OS hash and Samples device ID, checks
every replaced instruction, and round-trips the result. All non-MAIN sections
(bootstrap, updater and metadata) must remain byte-identical. The container keeps
stock version 1.13 and Samples identity; its SHA-256 identifies the modified file.

Unlike the snapshot-injection prototype, this image links the payload at
`0x401b0760`, retires the first of the stock filesystem's sixteen 16 KiB cache
blocks, and replaces the boot-clear function. Boot still clears the complete
stock BSS, skipping only the aligned payload, and initializes the 4 MiB history
reservation. Stock CPU cache configuration is unchanged. The filesystem's
chunk-blanking buffer at `0x401ac760..0x401b0760` remains zero. The payload is
currently **14,672 bytes**, leaving fifteen cache blocks for stock firmware.

This `.syx` can be checked/imported by ordinary DigiEmu; it needs **no runtime
injection**. Run **Check firmware**, comparing against the unmodified Samples
1.13 image, before using it. Adding it as a separate firmware creates a separate
emulated card: it does **not** automatically copy your restored factory bank or
projects. Preserve the working stock profile/card and follow the analysis
repository's factory-bank documentation if setting up the new profile. The
host panel's mouse-latchable SETTINGS/DATA grouping still needs the same local
`devices/model-samples.toml` overlay made by `panel_overlay()` in the launcher;
firmware cannot change DigiEmu's host-side button groups. The older injection
launcher below remains a separate workflow, not a loader for the new `.syx`.

The generated image passed DigiEmu's standalone **Check firmware** against
stock: container layout, its own bootloader, cold boot and runtime all passed.
The six named comparison screenshots matched stock; a transient frame differed,
and captured bypass audio was identical over 6.3 seconds. That run has no
restored factory bank and does not verify the new FX audio at cold-boot addresses.
DigiEmu warned its bundled checksum code was absent; `elektron-firmware-tool`
separately reported valid checksums and exact decompressed section round-trip.
All **37** stock-free port/builder tests passed with DigiEmu's Python, including
execution of the ColdFire boot-clear routine.

**Do not flash a physical Samples.** Container validity and emulator boot do not
establish hardware safety, CPU headroom or allocator correctness at maximum
sample occupancy. The builder never sends MIDI or contacts a physical device.
Generated `.syx`, unpacked stock sections and private emulation artifacts stay
under Git-ignored `build/`; do not distribute the resulting vendor-containing
image.

## Launch the snapshot-injected interactive panel

Prerequisites: ColdFire binutils ([BUILD.md](BUILD.md)), a DigiEmu checkout with
its Python environment/patched Unicorn, and a factory-enabled Samples OS 1.13
GUI snapshot. The factory-bank setup is documented in `model-samples-analysis`
commit `03fb8bb`, `EMULATOR.md`.

Close any panel using the source firmware folder, then run from this repository:

```sh
LIBUNICORN_PATH=/Applications/digiemu.app/Contents/Frameworks/unicorn/lib \
  ../digiemu/.venv/bin/python tools/run_samples_fx_emulator.py \
  --digiemu ../digiemu \
  --firmware-dir ../model-samples-analysis/.local-emulator/test-firmware
```

Use your actual factory-enabled firmware folder. For the installed app it may
instead be:

```text
~/Library/Application Support/digiemu/firmware/ms-1.13-e11859b6
```

The launcher builds the payload, clones the source into a timestamped directory
under `build/samples-panel-*/`, injects it **into guest RAM only**, and opens the
DigiEmu window with live audio. `--work NEW_DIRECTORY` and `--scale 4` override
the output location and panel zoom. Existing work directories are refused.

The source firmware/card/snapshots are not patched or reset. A source-folder
lock is held while copying; acquiring it updates the lock metadata file.
Writable inputs are independent copies, never hard links. macOS uses CoW clones
when available; the fallback can require substantial disk space.

On this Mac the checkout Python lacks `_tkinter`. The launcher can borrow the
installed app's bundled Tk extension **only when its Python ABI matches**, and
sets its Tcl/Tk resource paths. Otherwise install Tk for your Python version.
The library override above supplies the installed app's patched Unicorn; omit
or adjust it if your environment already provides that library.

### Using the panel

1. Click **SETTINGS** in the **modifiers** group to latch it down.
2. Click **RETRIG**, then click **SETTINGS** again to release the modifier.
3. Click **PLAY** to hear the factory pattern.
4. Hold a step **1–16** for a momentary repeat. The newest held step wins;
   releasing it falls back to an older held step.
5. Click pads **T1–T6** to toggle which tracks are affected. The six boxes on
   the screen show the selection.
6. Turn **LEVEL/DATA** to choose a row; click **DATA** to edit that row, then
   turn LEVEL/DATA again. The rows choose **Momentary/Latch** and **FX returns
   Off/On**. Click DATA again to leave row editing.
7. In Latch mode a step click starts/switches a repeat; clicking the same step
   again stops it.

Use the encoder `+`/`−` buttons or scroll over an encoder to turn it. The
launcher makes a local device-label/group overlay in the disposable copy:
SETTINGS, FUNCTION, TRACK and PATTERN are mouse-latchable modifiers, and stock
key code 32 (previously labelled PITCH by DigiEmu) is labelled **DATA**. All
physical input wires and codes remain unchanged. Click **latch / clear** if a
modifier is stuck.

The physical knob mapping follows the stock event indices used by Model-TG:

| Samples panel encoder | On the retrig page |
|---|---|
| PITCH | Drive |
| DECAY | Crush |
| SMPL START | Rate reduction |
| SMPL LENGTH | Pump |
| CUTOFF | Filter: turn left for LP, right for HP, centre off |
| RESONANCE | Filter resonance |
| DELAY SEND | Ring modulation |
| REVERB SEND | Noise riser |
| LFO SPEED | Gate division |
| VOL+DIST | Tape stop |
| SWING/NUDGE | Vinyl |
| CHANCE/COND | Flanger |

REVERB SIZE and DELAY TIME are unused on this page. Master VOLUME remains a
stock control. Resonance needs the filter engaged to be audible.

**BACK** resets master FX and a latched repeat without closing the page.
**RETRIG**, SETTINGS or WAVE closes the page; PATTERN closes it for stock pattern
selection. Repeats fade out on close, but FX and track selection persist.
**SETTINGS + BACK** resets FX from outside the page too.

Current UI limitations: pad LEDs still follow stock firmware rather than the
new selection (use the screen boxes), and the bottom-line FX hint's expiry is
refreshed on the next UI event rather than by a dedicated page timer.

## Automated tests

Verified locally with the factory-enabled Samples 1.13 snapshot: **29 unit
checks passed**, the native panel integration passed, all four DSP differential
cases passed, and the real Tk GUI started with live audio and the latchable
SETTINGS/DATA overlay. The current linked DSP/UI payload is 14,576 bytes.
These are emulator results, not physical-device validation.

No firmware is needed for the unit tests:

```sh
python3 -m unittest discover -s tools -p 'test_*samples_fx.py'
```

Run the native panel test against a fresh disposable work directory:

```sh
LIBUNICORN_PATH=/Applications/digiemu.app/Contents/Frameworks/unicorn/lib \
  ../digiemu/.venv/bin/python tools/test_samples_ui_emulator.py \
  --digiemu ../digiemu \
  --firmware-dir ../model-samples-analysis/.local-emulator/test-firmware \
  --work build/samples-ui-test
```

This test uses **press/release/turn through DigiEmu's real panel input API**.
It does not set the FX/retrig control state through the debug mailbox. It checks
opening/closing, momentary newest-held/fallback, track selection, every FX knob,
DATA row editing, latch, reset, FX returns, global reset, repeated reopen/cleanup
and Pattern closing. It saves screen PNGs, `audio.wav`, `panel-inputs.json` and
`ui-results.json` under the work directory.

The DSP differential test is retained separately:

```sh
LIBUNICORN_PATH=/Applications/digiemu.app/Contents/Frameworks/unicorn/lib \
  ../digiemu/.venv/bin/python tools/test_samples_fx_emulator.py \
  --digiemu ../digiemu \
  --firmware-dir ../model-samples-analysis/.local-emulator/test-firmware \
  --work build/samples-dsp-test
```

It creates independent stock, bypass, dry-control and exercised copies. It
checks byte-identical stock/bypass PCM over a one-second pattern segment,
unchanged dry PCM when recording histories, all six histories receiving audio,
all twelve controls changing PCM versus the matching dry timeline, repeat/return
ramps, reset, persistence, command consumption and payload boundary guards.
This is a smoke/differential test, not a golden-reference proof of audio quality.
Its debug mailbox remains available for focused DSP tests:

- `command_knob`: shared FX index, 2–13 (not the physical scan encoder number).
- `command_delta`: signed delta, consumed at the next block.
- `command_reset`: requests FX reset at the next block.

The JSON symbol map exposes these words. This is a one-slot mailbox: wait until
a delta has been consumed before sending another. The interactive panel does
not use this mailbox; its view's encoder handler calls the same DSP directly.

## Implementation and hardware boundary

`tools/build_samples_fx.py` extracts shared DSP/tables/state, the renderer,
repeat-key state machine, pad handler and drawing helpers from `src/model_tg.s`.
It links them with `src/samples_fx_glue.s` and `src/samples_fx_ui.s`, without the
added Cycles sampler engines or machine-select UI. The new page subclasses the
stock Samples **base View**, clones its vtable group, and uses stock allocation,
reference-holder, view-stack presentation and deferred close/destruction.

Guest-memory hooks for Samples OS 1.13:

| Site | Hook |
|---|---|
| `0x40058892` | Once per block before stock sends/mixing; DSP and block clock |
| `0x400555b4` | Mixer entry; L/R return repeat passes, replaying stock prologue |
| `0x40055adc` | Noise/Vinyl on the mixed bus, then stock x4 scaling |
| `0x4007146c` | Key accessor; Settings chords and repeat keys |
| `0x4001e8d8` | Pad-event method; track selection while the page is up |

The six stock mono channels start at `0x80001b48`. The Cycles sampler's stereo
side streams are disabled; return streams retain shared indices 12–15. Runtime
dependencies use Samples addresses, not a single global relocation offset.
The stock Cycles builder and executable source are unchanged.

The injector checks the supported stock MAIN OS hash, hook/capacity instructions,
resident sample usage, payload digest and empty development scratch space. It
reduces all five capacity immediates from `0x04000050` to `0x03c00050`, reserving
histories at `0x4dedd4e0..0x4e2dd4e0` without overlapping the stock delay ring.
The [allocator investigation](notes/model_samples_fx_port.md) records evidence
and paths still requiring audit. Histories are cleared on page open and on
re-enabling a selected track or FX return.

**The snapshot launcher's `0x47000000` is emulator scratch, not a hardware code
reservation.** Only the separate standalone builder implements the boot-clear
and filesystem-cache reservation described above; `build_samples_fx.py` still
defaults to the original RAM-only prototype. Do not reuse those runtime scratch
patches on hardware, or open a patched RAM snapshot with stock firmware.

Before any physical-device testing: audit loading/compaction/preview and all
remaining memory writers at maximum sample occupancy; validate transport,
pattern and tempo changes, USB/Transfer, recovery and real CPU/cache/DMA
headroom. The standalone container and startup reservation are implemented, not
a guarantee of safety. Restoring a settled snapshot is not a cold-boot test.

Run both the original port checks and stock-free standalone-builder checks:

```sh
LIBUNICORN_PATH=/Applications/digiemu.app/Contents/Frameworks/unicorn/lib \
  ../digiemu/.venv/bin/python -m unittest discover -s tools -p 'test_*samples*.py'
```

The standalone tests include executing the real ColdFire boot-clear code in
Unicorn against nonzero memory: the entire stock BSS and histories must clear,
the payload and boundary guards must survive, and saved registers/stack must be
restored. This test does not model physical caches or DMA.
