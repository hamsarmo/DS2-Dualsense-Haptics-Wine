# DualSense HD haptics under Wine / CrossOver

Adaptive triggers work. The controller speaker works. Vibration does nothing.
This repository documents why, and ships two fixes: a registry-only workaround
that needs no compiler, and a small patch to Wine's `mmdevapi`.

Reproduced on: Death Stranding 2 (PC), CrossOver 26.3.0 on macOS 15 / Apple M3 Max,
DualSense (VID 054C, PID 0CE6) over USB.

## The mechanism

The DualSense delivers feedback over two independent USB pipes:

- **HID interrupt** — output report `0x02` carries adaptive-trigger parameters,
  the LEDs, audio routing flags and the legacy rumble motor bytes.
- **USB Audio Class isochronous** — the pad enumerates as a 48 kHz, 4-channel
  audio device. Channels 1–2 are speaker/headphone; **channels 3–4 are the left
  and right haptic actuators**. PS5-style "HD haptics" are literally waveforms
  played into channels 3–4.

Sony's `libScePad` (statically linked into these game binaries) has to work out
*which* audio endpoint belongs to the pad. It does this by reading
`DEVPKEY_Device_ContainerId` from the HID device via
`SetupDiGetDeviceRegistryPropertyW(SPDRP_BASE_CONTAINERID)`, then comparing it
against the same property on each audio endpoint via `IPropertyStore::GetValue`.

**Wine's `mmdevapi` never sets that property on audio endpoints.** See
`dlls/mmdevapi/devenum.c`: endpoints get `InstanceId`, `FriendlyName`,
`DeviceDesc`, `FormFactor`, `PhysicalSpeakers` and `Driver`, and nothing else.
The match therefore always fails, the haptic stream is never opened, and
haptics are silent. Triggers are unaffected because they ride the HID pipe.

Evidence from a `WINEDEBUG=+mmdevapi` trace of an unmodified bottle: the game
queried `{8C7ED206-3F8A-4827-B3AB-AE9E1FAEFC6C},2` **6342 times** and every
single call returned `ERROR_FILE_NOT_FOUND`.

## Two further traps

**1. The container ID is not stable.** Wine's `winebus` builds it in
`make_unique_container_id()` as vendor/product ID, device index, input index,
and then `QueryPerformanceCounter()` memcpy'd into the low 8 bytes. The tail is
a timestamp, regenerated every time the device object is created — i.e. on every
new `wineserver`. Any value written once is stale by the next launch. The fix
must read the live value and stamp it inside a single wineserver session.

**2. Wine cannot return `VT_CLSID`.** Windows returns a `DEVPROP_TYPE_GUID`
property as `PROPVARIANT.vt = VT_CLSID` with `puuid` pointing at the GUID.
Wine's `MMDevice_GetPropValue` can only produce `VT_LPWSTR` (from `REG_SZ`),
`VT_UI4` (`REG_DWORD`) or `VT_BLOB` (`REG_BINARY`). There is no registry value
type that yields `VT_CLSID`.

What has been tried, and what happened:

| property written | Wine returns | observed |
|---|---|---|
| (nothing — stock Wine) | `VT_EMPTY` | lookup fails 6342/6342; silent haptics |
| `REG_SZ`, normal `{...}` GUID string | `VT_LPWSTR` | lookup succeeds (1416 hits / 12 endpoints × 354 passes); **still silent** |
| `REG_BINARY`, 16 raw bytes | `VT_BLOB` | game crashed on launch (n=1, cause unconfirmed) |
| `REG_SZ` via `hex(1):`, first 16 bytes = raw GUID | `VT_LPWSTR` | no crash; **still silent** |

The `hex(1):` row was an attempt to satisfy a caller that reads
`PROPVARIANT.puuid` without checking `.vt`: with `VT_LPWSTR` that field is
`pwszVal`, so a string buffer whose first 16 bytes *are* the GUID would make a
blind read land on the right answer. It did not help, which argues the caller
either checks `.vt`, or parses the string properly (in which case the plain
`REG_SZ` row should have worked), or the container match is not the only gate.
Those cannot be separated from outside the binary.

## Fix A — registry only, no compiler (`--rawguid`)

Store the ContainerId as a `REG_SZ` whose first 16 bytes are the raw
little-endian GUID, followed by a UTF-16 NUL. `reg add /t REG_SZ /d` cannot
express this because GUIDs contain NUL bytes, but Wine's registry importer
accepts `hex(1):` for a `REG_SZ` with arbitrary content. The blind `puuid` read
then lands on the correct bytes.

```sh
python3 scripts/ds2-fix-haptics.py --rawguid
```

**This did not restore haptics in testing.** It is kept because it is cheap to
retry on other titles and other Wine versions, and because ruling it out is
itself a useful result.

The script holds one wineserver open (a parked `cmd.exe` started through
CrossOver's wrapper, so msync stays registered), reads the live container IDs,
matches HID nodes to audio endpoints by USB location id, imports the values, and
launches the game in the same session.

This is a workaround that exploits a bug in the caller. It is not correct, and
it will stop working against any build that checks `.vt`.

## Fix B — patch Wine (`patches/0001-…`)

Make `MMDevice_GetPropValue` return `VT_CLSID` for `DEVPKEY_Device_ContainerId`,
parsing the stored `REG_SZ` with `CLSIDFromString`. This is the correct fix and
is what should go upstream. It still needs the container ID to be present on the
endpoint, so Fix A's stamping step (without `--rawguid`) remains necessary until
Wine populates the property itself — a proper upstream fix would do that in
`load_devices_from_reg()` / `MMDevice_Create()` from the driver's device info.

## Status

**Established by traces, not guesswork:** the property is absent on stock Wine;
the game queries it thousands of times; writing it makes the query succeed; the
container ID is timestamp-volatile; Wine cannot emit `VT_CLSID`.

**Not established:** that supplying a correct `VT_CLSID` restores haptics. Two
registry-level attempts to fake it both failed, and the game has never once been
observed opening a 4-channel client on the DualSense endpoint — under any of
them it initialises only the built-in speakers. Fix B is written but unbuilt and
untested. It is the correct behaviour regardless, but treat "this fixes haptics"
as an open hypothesis, not a claim.

If Fix B does not work either, the next step is instrumenting or disassembling
the game binary around its `IPropertyStore::GetValue` call to see what it does
with the result. Everything short of that has been tried.

**Note:** Fix B parses a normal `REG_SZ` GUID string, so run the stamping script
**without** `--rawguid` when testing it — the raw-bytes value will not parse.

## Licence

The patch is against Wine and is offered under the LGPL-2.1-or-later, matching
Wine. The scripts are MIT.
