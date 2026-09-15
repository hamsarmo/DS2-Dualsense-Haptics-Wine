# v1.0.0 downloads

Download **[ds2-fix-haptics.py](https://github.com/hamsarmo/DS2-Dualsense-Haptics-Wine/raw/refs/heads/main/release/ds2-fix-haptics.py)** and run it with Python 3.
See the [main README](../README.md) for supported versions, permanent/session modes and uninstall.

Only the Python file is needed to use the fix. It embeds the helper, Wine DLL and licenses.
The other files are for verification, licensing and rebuilding:

- `SHA256SUMS`: SHA-256 hashes of downloadable files.
- `asset-manifest.json`: hashes of assets embedded in the Python file.
- `wine-crossover-26.3.0-source.tar.gz`: complete original Wine source subtree from CodeWeavers 26.3.0.
- `LICENSE.txt`: project MIT license; `LICENSE-Wine-LGPL-2.1.txt`: Wine's LGPL.

The Wine modification is in [patches/](../patches/0001-mmdevapi-return-ContainerId-as-VT_CLSID.patch).
[Build instructions](../docs/BUILDING.md), [helper source](../src/controller-probe.c),
and [launcher source](../scripts/ds2-fix-haptics.py) are included in this repository.
No Sony runtime, game binaries or raw gameplay captures are distributed.
