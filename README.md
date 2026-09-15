# DS2 DualSense haptics for CrossOver

**Working haptic feedback in Death Stranding 2 on macOS.** Fix the case where
adaptive triggers and controller audio work, but vibration is missing.

Confirmed by gameplay and an audio capture: after the fix, DS2 opens a separate
four-channel motion stream with nonzero samples on both haptic channels.

## Download and run

1. Download **[ds2-fix-haptics.py](https://github.com/hamsarmo/DS2-Dualsense-Haptics-Wine/raw/refs/heads/main/release/ds2-fix-haptics.py)**.
2. Connect **one standard DualSense by USB**. Close DS2 and other Windows programs
   in its CrossOver bottle.
3. Run this in Terminal (Python 3 required):

   ```sh
   python3 ~/Downloads/ds2-fix-haptics.py
   ```

The script finds a DS2 bottle in CrossOver's standard Bottles folder. For a
custom location or multiple installations, supply the **full bottle folder**:

```sh
python3 ~/Downloads/ds2-fix-haptics.py --bottle "/path/to/CrossOver/Bottles/DS2"
```

It installs the fix permanently. **Launch DS2 normally afterward.** There is no
need to run the script before each game. Keep the script to check or uninstall.
The download contains the helper and patched Wine DLL; **no compiler or Python
packages are needed**. The script extracts them to a local cache, verifies their
checksums, and uses Sony's runtime already installed by your game.

### Two modes

| Command | Behavior |
|---|---|
| no mode flag | Install once; leave the fix installed |
| `--check` | Verify an existing installation; on a clean bottle, temporarily apply and verify, then restore without starting the game |
| `--session` | Apply, launch DS2, and restore when the game exits; use on a clean bottle |
| `--uninstall` | Restore the backed-up DLL and remove the properties/override added by this script |

Repeat `--bottle` for these commands if your bottle is outside the standard folder.
Do not close Terminal during `--session`. If interrupted by a crash or power loss,
run `--uninstall` before another session. Recovery state and the latest log live
inside the bottle at `.ds2-haptics/`.

### Requirements and supported scope

- **CrossOver 26.3.0.39832**, x86-64 Windows bottle, macOS. The release checks the
  stock DLL's SHA-256 and refuses other versions. A Wine DLL uses private audio
  interfaces, so assuming compatibility with another CrossOver version is unsafe.
- **Death Stranding 2 PC**, with the game's PlayStation PC SDK runtime installed.
  The tested runtime is S22 **5.50.00.11**. If the script cannot find it, run the
  game's prerequisite/runtime installer. Sony's DLL is not included here.
- **One USB DualSense**, Sony VID `054C`, PID `0CE6`. Bluetooth, DualSense Edge,
  multiple controllers, other games, upstream Wine and Linux are not validated.
- In-game vibration enabled. Keep ordinary game audio on your usual speakers.
- Tested on an Apple M3 Max with macOS 26.5. The original diagnostic notes contain
  historical experiments; use this README and the release script for installation.

Optional paths (use macOS paths, not `C:\...`):

```sh
python3 ds2-fix-haptics.py --bottle "/path/to/bottle" \
  --game "/path/to/SteamLibrary/steamapps/common/DEATH STRANDING 2 ON THE BEACH/DS2.exe" \
  --runtime "/path/to/bottle/drive_c/ProgramData/Sony Interactive Entertainment Inc/PSPC_SDK/S22/5.50.00.11/libScePad.dll"
```

`--game` is needed when discovery is ambiguous or the library is outside the bottle.
`--crossover "/path/to/CrossOver.app"` supports a nonstandard app location.
Run `--help` for all options. Genuine Steam installations have not yet been tested
with this launcher; permanent mode lets you continue launching through Steam.

## Why this works

Wwise's motion integration asks Sony's `libScePad` for the controller's
**ContainerId**, then looks for an audio endpoint with that same identity. Stock
CrossOver's controller audio endpoint had no ContainerId.

The crucial finding: **Sony's runtime and Windows HID reported different
ContainerIds for the same controller in the same Wine session**. Earlier attempts
that copied the Windows HID property to the audio endpoint did not work.

The successful combination:

1. Query the identity returned by **Sony's runtime**, without substituting the
   Windows HID value or hardcoding the author's controller identity.
2. Assign that identity to the connected controller's audio endpoints.
3. Load a small Wine `mmdevapi` patch that returns this property as `VT_CLSID`,
   the Windows GUID property type.

Before the fix, haptic channels 3 and 4 were exactly zero. After it, DS2 opened
an additional stream with about **1.19 million nonzero samples on each haptic
channel** in the recorded gameplay interval. The player confirmed clear vibration.
See [the successful test report](docs/SUCCESS.md).

## What changes, and what else could it affect?

The script replaces `drive_c/windows/system32/mmdevapi.dll` in the **selected
bottle**, adds ContainerId values to the detected controller's audio endpoints,
and sets `HKCU\Software\Wine\AppDefaults\DS2.exe\DllOverrides\mmdevapi` to
`native,builtin`. It backs up the original DLL and records all changes before
writing. It does not edit CrossOver.app, Sony's DLL, the game, or other bottles.

The override is per executable, but audio endpoint properties are shared within
that bottle. Other applications there can see the added identity. Applications
that independently force native mmdevapi could also load the patched DLL. This
is not a blanket guarantee for every program: keep unrelated apps in separate
bottles, or use temporary mode if you want the bottle restored between runs.

Sony's identity stayed stable across the tested sessions. It may change with a
new controller, runtime, Wine or CrossOver update. If haptics stop, run `--check`.
Uninstall and reinstall after changing controllers; uninstall before updating
CrossOver. Keep the same USB connection during installation/gameplay.

The installer refuses multiple candidate endpoints, existing ContainerId values,
an existing DS2 mmdevapi override, or an unfamiliar DLL rather than overwrite
someone else's setup. `--uninstall` retains recovery files if an unexpected DLL
or override change makes automatic recovery ambiguous.

## Build and validation

The source launcher is `scripts/ds2-fix-haptics.py`; the Windows helper source is
`src/controller-probe.c`. For development and source builds, see
[BUILDING.md](docs/BUILDING.md). Download files and the `SHA256SUMS` manifest are in [release/](release/).

```sh
python3 -m unittest discover -s tests -v
```

Tests exercise rollback after probe/stamping/verification failures, preservation
of existing properties, controller ambiguity, and atomic replacement of symlinks.
The standalone release script also passed a real bottle preflight.

## License

Launcher, helper and scripts: [MIT](LICENSE). Wine patch and DLL:
[LGPL-2.1-or-later](docs/LICENSE-Wine-LGPL-2.1.txt).
The download directory includes the corresponding Wine source from CodeWeavers, the patch is in this repository,
and build instructions. Sony/game binaries and gameplay recordings are excluded.

This is a community workaround, not an official Sony, Kojima, Audiokinetic or
CodeWeavers release. Please report your CrossOver/runtime versions and the
script's log when filing an issue; review logs for private paths before posting.
