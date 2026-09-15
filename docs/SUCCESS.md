# Successful DS2 haptic test — 2026-09-15

## Controlled comparison

Same game, USB controller, CrossOver installation and VT_CLSID DLL patch.
The decisive change was using the identity from Sony's runtime rather than
Windows HID's ContainerId property.

| Measurement | Previous runs | Sony-identity run |
|---|---|---|
| Adaptive triggers | working | working |
| Controller speaker | working after USB reset | working |
| Speaker stream | 4 channels, ch 3–4 zero | 4 channels, ch 3–4 zero |
| Separate haptic stream | absent | present, 48 kHz / 4 channels |
| Haptic channel 3 nonzero samples | 0 | 1,194,364 |
| Haptic channel 4 nonzero samples | 0 | 1,195,132 |
| Player feedback | no vibration | “IT WORKED!!!” |
| Game exit | normal | 0 |

The haptic stream included 2,482,176 measured frames. Its first two channels were
zero. Thus the additional signal is separate from ordinary controller speaker
sound. The original DLL and temporary endpoint values were restored and checked
after the capture; the successful experiment did not silently leave a fix behind.

## Root-cause evidence

Static inspection of the motion endpoint lookup shows it queries Sony's
controller identity, enumerates render devices, reads
`{8c7ed206-3f8a-4827-b3ab-ae9e1faefc6c},2`, converts that GUID to text, and compares
it against the Sony string. It proceeds only after finding a match.

A read-only probe found different Sony and Windows HID identities within a
single Wine session. Previous identity patches had stamped the latter. Matching
the former enabled the additional haptic stream and felt feedback.

This establishes a working fix for the tested setup. It does not establish why
Sony and HID derive different identities, or whether every other game/version
requires the same patch. The install script queries the value rather than
embedding a controller-specific GUID.

## Validated combination

- CrossOver 26.3.0.39832; macOS 26.5; Apple M3 Max.
- Standard USB DualSense, VID 054C / PID 0CE6.
- Sony PS-PC runtime S22 5.50.00.11.
- Stock mmdevapi SHA256:
  `ef72fbb20bad5527ccf978d5fc6d451a4a529a574385ff50ad56d7301ccb05da`.
- Patched mmdevapi SHA256:
  `abb0a074db3a7025c6373eca399748a888ec209cb020c11b807defaaf9e20e22`.

Local raw diagnostic captures are excluded from the public distribution.
The public helper performs identity/property queries only and records no audio.

## Permanent installer validation

The single-file launcher passed a real preflight on the tested bottle, restored
stock state, then installed the fix permanently. A subsequent fresh-session
check read the same Sony identity and verified VT_CLSID on both endpoints.

Without an explicit override, a normally named helper loaded builtin mmdevapi
and saw VT_LPWSTR for the added property. The same helper named DS2.exe loaded
the patched native DLL and saw the matching VT_CLSID. This verifies that the
saved per-executable override selects the DLL as intended; it does not claim
that the endpoint property is invisible to other applications in the bottle.

The public uninstall path was exercised on the real bottle and the restored DLL
matched the original SHA-256. The permanent fix was then reinstalled. Eleven
unit tests passed, including install/uninstall and failure recovery paths.
A very short initial wait for Wine shutdown caused one harmless refusal after a
probe exited; the final launcher waits up to 20 seconds before asking the user
to close remaining programs.
