# Model:Samples retrig/master FX: emulator DSP prototype

**Development-only. No installable Samples firmware is produced.**

The first executable port runs the existing Model-TG retrig and all twelve
master-FX controls on the stock Model:Samples 1.13 audio path in DigiEmu. This
is real ColdFire assembly executing in the emulator, not host-side audio
processing. Stock Samples playback and its project/sample formats remain in
use. The feature's **panel page, buttons, knob events and LEDs are not ported
yet**: the test controls the DSP through a development mailbox and state writes.

## Prerequisites

- ColdFire binutils, as in [BUILD.md](BUILD.md).
- A DigiEmu checkout with its Python environment and patched Unicorn library.
- A settled, factory-enabled Samples 1.13 firmware folder with stock sections,
  card and `snapshots/model-samples_OS1.13/gui.snap`.
- See `model-samples-analysis` commit `03fb8bb` and its `EMULATOR.md` for the
  factory-bank reconstruction and emulator boot procedure. Firmware, snapshots,
  card images, bank audio and captures are private local inputs/artifacts, not
  committed to this repository.

Close any panel using the input firmware folder before running: the harness
locks it while making disposable copies. It never patches the source firmware,
snapshots or card. DigiEmu's lock metadata file is updated by acquiring the lock.

## Run

From this repository, with sibling checkouts in `~/repo`:

```sh
python3 tools/build_samples_fx.py
python3 -m unittest discover -s tools -p 'test_*samples_fx.py'

LIBUNICORN_PATH=/Applications/digiemu.app/Contents/Frameworks/unicorn/lib \
  ../digiemu/.venv/bin/python tools/test_samples_fx_emulator.py \
  --digiemu ../digiemu \
  --firmware-dir ../model-samples-analysis/.local-emulator/test-firmware \
  --work build/samples-emulator-test
```

Substitute your actual factory-enabled firmware folder. The library override
above uses the installed macOS app's patched Unicorn; omit/adjust it if the
checkout environment already provides the patched library.

Choose a **new** `--work` directory for every run; existing output is refused.
The harness creates separate stock, bypass, dry-control and exercised copies,
including independent writable card images. On macOS files are cloned CoW when
possible; elsewhere the fallback copies the files, which can take considerable
disk space. It never uses hard links for writable inputs.

Outputs under `--work`:

- `payload/samples_fx.{s,o,elf,bin,json}`: build products and symbol map.
- `stock/`, `bypass/`, `dry/`, `exercise/`: disposable emulator firmware folders.
- Each case's `audio.wav`, `final.png`, and `result.json`.
- `results.json`: aggregate comparison and assertion results.

## What is being patched, and where

`tools/build_samples_fx.py` extracts the shared DSP and its tables/state from
`src/model_tg.s`, relocates the identified Samples runtime dependencies, and
links it with `src/samples_fx_glue.s`. It excludes the Model-TG sampler engines,
view construction, rendering, transfer identity changes and Cycles machine
optimizations. Source boundaries and the knob entry are checked; the linker
rejects unresolved dependencies. The payload and shared source hashes are
recorded in JSON. The stock Cycles builder is unchanged.

The harness restores a stock snapshot, validates its hook/capacity instructions,
checks resident sample usage, then modifies **guest memory only**:

| Samples site | Development hook |
|---|---|
| `0x40058892`, output-call site | Once per block, before stock sends/mix; command mailbox and `rtg_audio` |
| `0x400555b4`, mixer entry | `rtg_fxpass` for each L/R return pass; stock prologue replayed |
| `0x40055adc`, mixed-bus scaling call | `mfx_master` for Noise/Vinyl, followed by stock x4 scaling |

The wrapper tail-calls stock output at `0x4005575e` with its arguments intact.
The channels are stock Samples' six mono channels at `0x80001b48`; the Cycles
sampler's stereo side streams are disabled. Return streams retain the shared
DSP's indices 12–15. The block clock is incremented at the once-per-block hook.
Tempo, audio clock, transport step and bar timing use Samples addresses, not
a single global Cycles-to-Samples offset.

The prototype reduces all five capacity immediates from `0x04000050` to
`0x03c00050`, then clears/uses histories at `0x4dedd4e0..0x4e2dd4e0`. It refuses
snapshots with resident sample allocations beyond the reduced limit. This
preserves the stock delay ring. See [the investigation](notes/model_samples_fx_port.md)
for allocator evidence and the paths still requiring audit.

The 12,464-byte payload currently uses **`0x47000000` as emulator scratch**.
The injector requires this region and its guards to be empty. It is **not a
hardware reservation**: no boot clear, heap, cache or filesystem ownership is
changed to protect it. The emulator checks guards afterwards. Do not append
this blob to a `.syx`, copy these runtime patches to a device, or treat restoring
a preboot snapshot as a cold-boot test.

## Development controls

The JSON symbol map exposes the DSP's state and these mailbox words:

- `command_knob`: panel knob number **plus one** (2–13).
- `command_delta`: signed knob delta; consumed and cleared at the next block.
- `command_reset`: nonzero requests the normal master-FX reset at the next block.

A single producer must wait for the delta to be consumed before sending another
command; this is a one-slot test mailbox, not an input queue. The shared knob
entry accepts the signed delta directly instead of calling the stock UI event
acceleration function. Gate advances one division per command sign, just as the
shared UI handler does. Resonance is tested with the filter engaged.

The harness also writes `rtg_on`, `rtg_latch`, `rtg_lstep`, `rtg_held`, `rtg_sel`
and `rtg_fx` directly. Those writes test the engine's behavior, **not** actual
pad/step event delivery, page lifecycle, encoder acceleration or screen/LED UI.

## Checks

The integration harness checks:

- Stock and patched-bypass pattern PCM are byte-identical for the captured
  one-second segment (48,000 stereo frames).
- Recording histories without applying effects is byte-identical to the
  matched stock segment; all six track histories contain audio.
- All twelve controls reach their intended DSP state and change captured PCM
  versus the matching dry timeline. This is a smoke/differential test, not a
  golden-reference proof of each effect's transfer function or audio quality.
- FX reset, a latched repeat, repeat release, and return-stream wet ramps.
- Momentary newest-held priority, fallback to an older held step, and release.
- FX continue after the page-state flag closes; deselection fades stream FX out.
- No emulator halt, command consumption, and unchanged payload boundary guards.

The tests do **not** establish physical CPU headroom, cache coherency, maximum
sample occupancy, all loading/compaction/preview paths, actual panel UI behavior,
or safe cold boot/recovery. Those, a real code-memory reservation and a
Samples-only builder remain necessary before creating hardware firmware.
