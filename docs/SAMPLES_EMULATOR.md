# Model:Samples retrig/master FX in DigiEmu

**Interactive emulator prototype. Not hardware-installable firmware.**

You can now use the emulator's panel to open the retrig page, play momentary or
latched repeats, select tracks with the pads and adjust all twelve master FX.
The handlers and screen renderer are **native ColdFire firmware code**, not
Python input interception or host-side DSP. Stock Samples playback, factory
samples and project/sample formats remain in use.

## Launch the interactive panel

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

**`0x47000000` is emulator scratch, not a hardware code reservation.** No boot
clear, heap, cache or filesystem ownership changes protect it on a real device.
Neither the launcher nor builder produces an installable `.syx`. Do not reuse
these runtime patches on hardware, or open the disposable patched resume
snapshot with an ordinary stock emulator session.

Before hardware firmware is possible: reserve code/state memory, implement
safe startup/cache handling, audit loading/compaction/preview at maximum sample
occupancy, validate transport/pattern/tempo changes and real CPU headroom, and
build/verify a Samples-only update container. Restoring a settled snapshot is
not a cold-boot or recovery test.
