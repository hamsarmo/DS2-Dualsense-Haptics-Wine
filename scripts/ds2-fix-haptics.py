#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Install the verified DualSense haptics fix in a CrossOver DS2 bottle."""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zlib

STOCK_SHA = 'ef72fbb20bad5527ccf978d5fc6d451a4a529a574385ff50ad56d7301ccb05da'
PATCH_SHA = 'abb0a074db3a7025c6373eca399748a888ec209cb020c11b807defaaf9e20e22'
VALUE = '{8c7ed206-3f8a-4827-b3ab-ae9e1faefc6c},2'
MMDEV = r'HKLM\Software\Microsoft\Windows\CurrentVersion\MMDevices\Audio'
GUID = r'\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}'
EMBEDDED = {}  # Release builder inserts compressed, checksummed open-source binaries.


class ControllerIdentityChanged(RuntimeError):
    """The saved Sony identity no longer matches the connected controller."""


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_copy(source, target):
    fd, name = tempfile.mkstemp(prefix='.ds2-haptics-', dir=target.parent)
    os.close(fd)
    try:
        shutil.copyfile(source, name)
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def winpath(path):
    return 'Z:' + str(Path(path).resolve()).replace('/', '\\')


def parse_probe(text):
    ids = re.findall(r'^SONY_ID=(' + GUID + r')\s*$', text, re.M)
    endpoints = []
    for flow, endpoint, vt, cid in re.findall(
            r'^ENDPOINT=(Render|Capture)\|([^|\r\n]+)\|(\d+)\|([^\r\n]*)', text, re.M):
        guids = re.findall(GUID, endpoint)
        if not guids:
            raise RuntimeError('Malformed audio endpoint identifier')
        endpoints.append((flow, guids[-1].upper(), int(vt), cid.strip().upper()))
    if len([e for e in endpoints if e[0] == 'Render']) != 1:
        raise RuntimeError('Connect exactly one USB DualSense with a four-channel audio endpoint.')
    if len(endpoints) > 2 or len(set((e[0], e[1]) for e in endpoints)) != len(endpoints):
        raise RuntimeError('Ambiguous controller endpoints; disconnect other controllers.')
    return ids, endpoints


def select_path(candidates, label, option):
    paths = sorted(set(p.resolve() for p in candidates if p.exists()))
    if len(paths) != 1:
        listing = '\n'.join('  ' + str(p) for p in paths) or '  none found'
        raise RuntimeError(f'Specify {option}; {label} candidates:\n{listing}')
    return paths[0]


def discover_bottle(explicit):
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not (p / 'cxbottle.conf').is_file():
            raise RuntimeError(f'Not a CrossOver bottle: {p}')
        return p
    root = Path.home() / 'Library/Application Support/CrossOver/Bottles'
    candidates = [p for p in root.glob('*') if (p / 'drive_c').is_dir() and
                  list((p / 'drive_c').glob('Program Files*/**/DS2.exe'))]
    return select_path(candidates, 'DS2 bottle', '--bottle /path/to/bottle')


def assets():
    if EMBEDDED:
        root = Path.home() / 'Library/Caches/DS2-Dualsense-Haptics-Wine' / PATCH_SHA[:12]
        root.mkdir(parents=True, exist_ok=True)
        for name, item in EMBEDDED.items():
            data = zlib.decompress(base64.b64decode(item['data']))
            if hashlib.sha256(data).hexdigest() != item['sha256']:
                raise RuntimeError(f'Corrupt embedded asset: {name}')
            path = root / name
            if not path.exists() or sha(path) != item['sha256']:
                fd, tmp = tempfile.mkstemp(dir=root)
                with os.fdopen(fd, 'wb') as f:
                    f.write(data)
                os.replace(tmp, path)
        return root
    root = Path(__file__).resolve().parents[1] / 'dist/assets'
    if not (root / 'controller-probe.exe').exists():
        raise RuntimeError('Download the standalone script from the repository release/ folder, or build the release assets first.')
    return root


class Fix:
    def __init__(self, bottle, crossover, state):
        self.bottle, self.cx, self.state = bottle, crossover, state
        self.dll = bottle / 'drive_c/windows/system32/mmdevapi.dll'
        self.env = dict(os.environ)
        for key in ('CX_INITIALIZED', 'CX_BOTTLE', 'WINEPREFIX', 'CX_LOG',
                    'WINEDLLOVERRIDES', 'CX_DLL_OVERRIDES', 'CX_ENV', 'WINEDEBUG',
                    'WINELOADER', 'WINEDLLPATH', 'DYLD_INSERT_LIBRARIES'):
            self.env.pop(key, None)
        self.env.update(CX_BOTTLE_PATH=str(bottle.parent), CX_DEBUGMSG='-all', ROSETTA_ADVERTISE_AVX='1')
        self.cmd = [str(crossover / 'bin/wine'), '--bottle', bottle.name]
        self.keeper = None
        self.log = None
        self.data = None

    def run(self, args, check=True, timeout=45, native=True):
        # Use files: Wine services can inherit pipes and keep communicate() waiting.
        with tempfile.TemporaryFile(mode='w+') as out:
            r = subprocess.run(self.cmd + (['--dll', 'mmdevapi=n'] if native else []) + args,
                               env=self.env, stdout=out, stderr=subprocess.STDOUT, timeout=timeout)
            out.seek(0)
            text = out.read()
        if self.log:
            self.log.write(text); self.log.flush()
        if check and r.returncode:
            raise RuntimeError(f'Windows command failed ({r.returncode}):\n{text[-2500:]}')
        return r.returncode, text

    def save(self):
        path = self.state / 'state.json'
        tmp = self.state / 'state.tmp'
        tmp.write_text(json.dumps(self.data, indent=2) + '\n')
        os.replace(tmp, path)

    def verify_installed(self, runtime, asset_dir):
        self.data = json.loads((self.state / 'state.json').read_text())
        if self.data.get('mode') != 'installed' or sha(self.dll) != PATCH_SHA:
            raise RuntimeError('Incomplete or changed installation. Use --uninstall to recover first.')
        self.start()
        _, output = self.run([str(asset_dir / 'controller-probe.exe'), winpath(runtime)])
        ids, endpoints = parse_probe(output)
        expected = self.data['sony_id']
        if ids != [expected] or any(vt != 72 or cid != expected for _,_,vt,cid in endpoints):
            raise ControllerIdentityChanged(
                'Controller identity or endpoints changed. Run the installer again with the controller connected.')
        code, value = self.run(['reg','query',self.data['override_key'],'/v','mmdevapi'], check=False, native=False)
        if code or not re.search(r'REG_SZ\s+native,builtin', value):
            raise RuntimeError('The DS2 DLL override changed. See the saved installation state before repairing.')
        print('The permanent fix is installed and verified. Launch DS2 normally.', flush=True)

    def restore(self):
        path = self.state / 'state.json'
        if not path.exists():
            print('No pending changes to restore.', flush=True)
            return
        self.data = json.loads(path.read_text())
        if self.data['bottle'] != str(self.bottle):
            raise RuntimeError('Recovery state belongs to a different bottle.')
        backup = self.state / 'mmdevapi.original.dll'
        if sha(backup) != self.data['original_sha256']:
            raise RuntimeError('Recovery backup checksum mismatch; leaving state intact.')
        if sha(self.dll) not in (self.data['original_sha256'], PATCH_SHA):
            raise RuntimeError('The bottle DLL changed outside this script; leaving recovery state intact.')
        override = self.data.get('override_key')
        if override:
            code, text = self.run(['reg','query',override,'/v','mmdevapi'], check=False, native=False)
            if code == 0:
                if not re.search(r'REG_SZ\s+native,builtin', text):
                    raise RuntimeError('DS2 override changed outside this script; recovery state retained.')
                self.run(['reg','delete',override,'/v','mmdevapi','/f'], native=False)
        for key in self.data['keys']:
            code, _ = self.run(['reg', 'query', key, '/v', VALUE], check=False, native=False)
            if code == 0:
                self.run(['reg', 'delete', key, '/v', VALUE, '/f'], native=False)
            code, _ = self.run(['reg', 'query', key, '/v', VALUE], check=False, native=False)
            if code == 0:
                raise RuntimeError('Could not remove temporary endpoint property.')
        atomic_copy(backup, self.dll)
        if sha(self.dll) != self.data['original_sha256']:
            raise RuntimeError('DLL restoration did not verify.')
        path.unlink()
        print('Restored the original DLL and removed temporary endpoint properties.', flush=True)

    def start(self):
        try:
            self.run(['--wait-all'], timeout=20, native=False)
        except subprocess.TimeoutExpired:
            raise RuntimeError('Close the game and all Windows programs in this bottle, then retry.')
        self.state.mkdir(parents=True, exist_ok=True)
        self.log = (self.state / 'latest.log').open('w')
        self.keeper = subprocess.Popen(self.cmd + ['cmd'], env=self.env,
                                       stdin=subprocess.PIPE, stdout=self.log, stderr=subprocess.STDOUT)
        time.sleep(4)
        if self.keeper.poll() is not None:
            raise RuntimeError('Could not keep the Wine session open.')

    def stop(self):
        if self.keeper and self.keeper.poll() is None:
            self.keeper.stdin.close()
            try:
                self.keeper.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.keeper.terminate()
                self.keeper.wait(timeout=10)
        if self.log:
            self.log.close()

    def launch(self, runtime, game, asset_dir, check_only, permanent=False, refresh=False):
        if sha(self.cx / 'lib/wine/x86_64-windows/mmdevapi.dll') != STOCK_SHA:
            raise RuntimeError('Unsupported CrossOver DLL. This release is tested with CrossOver 26.3.0.39832 only.')
        if (self.state / 'state.json').exists() and permanent:
            try:
                self.verify_installed(runtime, asset_dir)
                return
            except ControllerIdentityChanged:
                if not refresh:
                    raise
                print('The controller identity changed. Refreshing the permanent DS2 mapping.', flush=True)
                self.restore()
                # verify_installed() opened a Wine session. Close it before the
                # fresh install waits for the bottle and opens its own session.
                self.stop()
        if sha(self.dll) != STOCK_SHA:
            raise RuntimeError('The bottle already has a modified mmdevapi.dll. Restore it before using this fix.')
        if sha(asset_dir / 'mmdevapi.dll') != PATCH_SHA:
            raise RuntimeError('Patched DLL checksum mismatch.')
        if (self.state / 'state.json').exists():
            raise RuntimeError('Previous session needs recovery. Run this script with --restore first.')
        self.start()
        # Backup and journal before the first mutation; finally also handles failed probes.
        atomic_copy(self.dll, self.state / 'mmdevapi.original.dll')
        self.data = {'bottle': str(self.bottle), 'original_sha256': sha(self.dll), 'keys': []}
        self.save()
        restore_needed = True
        try:
            atomic_copy(asset_dir / 'mmdevapi.dll', self.dll)
            _, output = self.run([str(asset_dir / 'controller-probe.exe'), winpath(runtime)])
            ids, endpoints = parse_probe(output)
            if len(ids) != 1:
                raise RuntimeError('Sony did not return exactly one valid controller identity.')
            cid = ids[0].upper()
            # Verify all baseline values first so unexpected existing values are preserved.
            for flow, guid, vt, _ in endpoints:
                key = f'{MMDEV}\\{flow}\\{guid}\\Properties'
                code, _ = self.run(['reg', 'query', key, '/v', VALUE], check=False)
                if code == 0 or vt != 0:
                    raise RuntimeError('An endpoint already has a ContainerId. No endpoint properties were overwritten.')
            for flow, guid, _, _ in endpoints:
                key = f'{MMDEV}\\{flow}\\{guid}\\Properties'
                self.data['keys'].append(key); self.save()
                self.run(['reg', 'add', key, '/v', VALUE, '/t', 'REG_SZ', '/d', cid, '/f'])
            _, verified = self.run([str(asset_dir / 'controller-probe.exe'), '-'])
            _, actual = parse_probe(verified)
            if {(f,g) for f,g,_,_ in actual} != {(f,g) for f,g,_,_ in endpoints} or any(
                    vt != 72 or value != cid for _,_,vt,value in actual):
                raise RuntimeError('Audio endpoint identity/type verification failed.')
            if self.keeper.poll() is not None:
                raise RuntimeError('Wine session ended during preparation.')
            print(f'Verified Sony identity {cid} on {len(actual)} audio endpoint(s).', flush=True)
            if check_only:
                print('Preflight passed. Restoring now; no game launched.', flush=True)
                return
            if permanent:
                key = r'HKCU\Software\Wine\AppDefaults\DS2.exe\DllOverrides'
                code, _ = self.run(['reg','query',key,'/v','mmdevapi'], check=False, native=False)
                if code == 0:
                    raise RuntimeError('DS2 already has a mmdevapi override; it was not overwritten.')
                self.data['override_key'] = key
                self.data['sony_id'] = cid
                self.save()
                self.run(['reg','add',key,'/v','mmdevapi','/t','REG_SZ','/d','native,builtin','/f'], native=False)
                code, value = self.run(['reg','query',key,'/v','mmdevapi'], native=False)
                if not re.search(r'REG_SZ\s+native,builtin', value):
                    raise RuntimeError('DS2 override did not verify.')
                self.data['mode'] = 'installed'; self.save()
                restore_needed = False
                print('Installed permanently for DS2.exe in this bottle. Launch DS2 normally.', flush=True)
                print('To undo: run this script with the same --bottle and --uninstall.', flush=True)
                return
            print('Launching DS2 with haptics. Keep this terminal open until the game exits.', flush=True)
            # Do not restore a DLL under a running game on Ctrl-C. Wait for normal exit.
            game_proc = subprocess.Popen(self.cmd + ['--dll','mmdevapi=n', winpath(game)],
                                         env=self.env, stdout=self.log, stderr=subprocess.STDOUT)
            while True:
                try:
                    code = game_proc.wait()
                    break
                except KeyboardInterrupt:
                    print('Quit DS2 normally so the script can restore the bottle.', flush=True)
            print(f'DS2 exited with code {code}.', flush=True)
            if code:
                raise RuntimeError(f'DS2 launch failed. See {self.state / "latest.log"}')
        finally:
            if restore_needed:
                self.restore()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bottle', help='Full path to a CrossOver bottle (auto-detects standard DS2 installations)')
    ap.add_argument('--game', type=Path, help='Full macOS path to DS2.exe, including an external Steam library')
    ap.add_argument('--runtime', type=Path, help='Full macOS path to the installed libScePad.dll')
    ap.add_argument('--crossover', type=Path, default=Path('/Applications/CrossOver.app'))
    ap.add_argument('--session', action='store_true', help='Apply temporarily, launch DS2, and restore after exit')
    ap.add_argument('--check', action='store_true', help='Verify the fix and restore it without launching the game')
    ap.add_argument('--uninstall', '--restore', dest='restore', action='store_true', help='Remove the permanent fix or recover an interrupted session')
    args = ap.parse_args(argv)
    if sys.platform != 'darwin':
        raise RuntimeError('This release supports macOS CrossOver only.')
    bottle = discover_bottle(args.bottle)
    cx = args.crossover.expanduser().resolve() / 'Contents/SharedSupport/CrossOver'
    if not (cx / 'bin/wine').is_file():
        raise RuntimeError('CrossOver was not found. Use --crossover /path/to/CrossOver.app')
    state = bottle / '.ds2-haptics'
    state.mkdir(exist_ok=True)
    with (state / 'lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another fix session is already using this bottle.')
        fix = Fix(bottle, cx, state)
        try:
            if args.restore:
                fix.start(); fix.restore(); return
            runtime = select_path([args.runtime.expanduser()] if args.runtime else
                                  list((bottle / 'drive_c/ProgramData').glob('Sony Interactive Entertainment Inc/PSPC_SDK/**/libScePad.dll')),
                                  'Sony runtime', '--runtime /path/to/libScePad.dll')
            game = select_path([args.game.expanduser()] if args.game else
                               list((bottle / 'drive_c').glob('Program Files*/**/DS2.exe')),
                               'game executable', '--game /path/to/DS2.exe')
            fix.launch(runtime, game, assets(), args.check, permanent=not args.session,
                       refresh=not args.check and not args.session)
        finally:
            fix.stop()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
