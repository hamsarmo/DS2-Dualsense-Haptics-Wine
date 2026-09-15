# Prompt for Claude Code / Codex — build a patched mmdevapi.dll for CrossOver

Paste everything below into an agent running in a scratch directory on the Mac.

---

## Task

Build a patched `mmdevapi.dll` (PE, x86_64) that is ABI-compatible with
CrossOver 26.3.0.39832 on macOS, and install it into a CrossOver bottle as a
native DLL override.

## Why

Wine's `dlls/mmdevapi/devenum.c`, function `MMDevice_GetPropValue`, returns
`DEVPKEY_Device_ContainerId` as `VT_LPWSTR` because it maps registry types
mechanically (`REG_SZ`→`VT_LPWSTR`, `REG_DWORD`→`VT_UI4`,
`REG_BINARY`→`VT_BLOB`). Windows returns that property as `VT_CLSID`. Sony's
libScePad reads `PROPVARIANT.puuid` directly, so under Wine it dereferences a
string pointer and gets a garbage GUID; it can never bind a DualSense HID device
to its USB-audio endpoint, and HD haptics stay silent.

The patch is in `patches/0001-mmdevapi-return-ContainerId-as-VT_CLSID.patch`.

## Hard constraints

- **Build from CrossOver's own source, not upstream Wine.** `mmdevapi.dll` talks
  to `winecoreaudio.drv` over an internal, version-specific interface. An
  upstream build dropped into CrossOver 26.3 may load and then crash or
  misbehave. Source: https://www.codeweavers.com/crossover/source (CodeWeavers
  publish it to meet their LGPL obligations). Match `26.3.0.39832` exactly;
  if only a nearby version is published, say so and stop rather than guessing.
- Target `x86_64-windows` (the bottle is a 64-bit win10 template). Confirm with
  `ls /Applications/CrossOver.app/Contents/SharedSupport/CrossOver/lib/wine/` —
  it should show `x86_64-windows`, `i386-windows`, `x86_64-unix`.
- Do not modify anything inside `/Applications/CrossOver.app`. Install the built
  DLL into the bottle only.

## Steps

1. `brew install mingw-w64 bison flex` (and whatever else `configure` demands).
   Verify `x86_64-w64-mingw32-gcc --version` works.
2. Download and unpack the CrossOver source for 26.3.0.39832.
3. Apply the patch to `dlls/mmdevapi/devenum.c`. It is a single hunk in the
   `case REG_SZ:` branch of `MMDevice_GetPropValue`. If it does not apply
   cleanly, apply it by hand — do not force it — and show me the final function.
4. Confirm `devenum.c` includes what the patch needs: `devpkey.h` for
   `DEVPKEY_Device_ContainerId` and `CLSIDFromString` from `ole32`. Add the
   include if missing.
5. Configure for a cross build with mingw, then build **only** the one DLL:
   `./configure --enable-win64 --with-mingw` then `make dlls/mmdevapi` (or
   `make dlls/mmdevapi/mmdevapi.dll`). A full `make` is not needed and takes
   hours — avoid it.
6. Verify the output is a PE DLL: `file dlls/mmdevapi/mmdevapi.dll` should say
   `PE32+ executable (DLL) (console) x86-64`.
7. Install into the bottle:
   - copy to `/Volumes/WD/Crossover/DS2/drive_c/windows/system32/mmdevapi.dll`
     (back up the existing file first if one is there)
   - set the override: `CX_BOTTLE_PATH=/Volumes/WD/Crossover \
     /Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine \
     --bottle DS2 reg add 'HKCU\Software\Wine\DllOverrides' /v mmdevapi \
     /t REG_SZ /d native,builtin /f`
8. Verify it loaded rather than the builtin:
   `CX_DEBUGMSG=+loaddll` and check the log says
   `Loaded L"C:\\windows\\system32\\mmdevapi.dll" ... native`.

## Confidence

This is a hypothesis, not a known fix. What is proven: Wine never sets the
property, the game queries it constantly, and writing it as `REG_SZ` makes the
query succeed without restoring haptics. The theory is that the game requires
`VT_CLSID` specifically. Two registry-level workarounds failed. Build it, test
it, and report the result honestly — a negative result is worth having.

The decisive signal is NOT "does it rumble" alone. It is whether the game ever
opens an audio client on the DualSense **render** endpoint with 4 channels. In
every trace so far it initialises only `BuiltInSpeakerDevice`.

## Test

Run the stamping script WITHOUT `--rawguid` (the patch parses a normal GUID
string; the raw-bytes variant will not parse). With the DualSense on USB:

```sh
python3 /Volumes/WD/Crossover/DS2/ds2-fix-haptics.py \
  --debug /Volumes/WD/Crossover/DS2/verify.log
```

Then in `verify.log`:

- `{8C7ED206-3F8A-4827-B3AB-AE9E1FAEFC6C},2` should no longer log
  `returned 2` for the DualSense endpoints.
- Look for `client_Initialize` on the DualSense render endpoint GUID with
  `nChannels: 4` and `dwChannelMask: 0x33`. That is the haptic stream opening.
- The pad should vibrate in game.

## Report back

Whether it built, whether the override loaded, and the two log checks above —
quoting the actual lines. If the build fails, show the first real error rather
than a summary; do not work around it by switching to upstream Wine sources
without telling me.
