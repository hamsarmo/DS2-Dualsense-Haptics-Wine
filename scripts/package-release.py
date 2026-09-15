#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bundle audited local binaries into the standalone launcher; no downloads."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import zlib

ROOT = Path(__file__).resolve().parents[1]
PATCH_SHA = 'abb0a074db3a7025c6373eca399748a888ec209cb020c11b807defaaf9e20e22'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dll', type=Path, required=True)
    p.add_argument('--probe', type=Path, required=True)
    args = p.parse_args()
    if hashlib.sha256(args.dll.read_bytes()).hexdigest() != PATCH_SHA:
        raise SystemExit('The DLL differs from the gameplay-validated release binary.')
    out = ROOT / 'dist'
    (out / 'assets').mkdir(parents=True, exist_ok=True)
    embedded = {}
    for name, source in [('mmdevapi.dll', args.dll), ('controller-probe.exe', args.probe),
                         ('LICENSE-Wine-LGPL-2.1.txt', ROOT / 'docs/LICENSE-Wine-LGPL-2.1.txt'),
                         ('LICENSE.txt', ROOT / 'LICENSE')]:
        data = source.read_bytes()
        embedded[name] = {'sha256': hashlib.sha256(data).hexdigest(),
                          'data': base64.b64encode(zlib.compress(data, 9)).decode()}
        shutil.copyfile(source, out / 'assets' / name)
    source = (ROOT / 'scripts/ds2-fix-haptics.py').read_text()
    source = source.replace('EMBEDDED = {}', 'EMBEDDED = ' + repr(embedded), 1)
    (out / 'ds2-fix-haptics.py').write_text(source)
    (out / 'asset-manifest.json').write_text(json.dumps(
        {name: {'sha256': item['sha256']} for name, item in embedded.items()}, indent=2) + '\n')
    print(out / 'ds2-fix-haptics.py')


if __name__ == '__main__':
    main()
