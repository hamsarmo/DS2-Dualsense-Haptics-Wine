#!/usr/bin/env python3
"""
DualSense HD-haptics fix for Death Stranding 2 in the CrossOver "DS2" bottle.

THE BUG
-------
libScePad (statically linked into DS2.exe) finds the controller's USB-audio
endpoint -- channels 3/4 of which drive the haptic actuators -- by reading
DEVPKEY_Device_ContainerId {8C7ED206-3F8A-4827-B3AB-AE9E1FAEFC6C},2 from the HID
device and matching it against the same property on each audio endpoint.  Wine's
mmdevapi never writes that property on endpoints, so the match never succeeds and
the haptic stream is never opened.  Adaptive triggers are unaffected -- they ride
the HID pipe.  (Verified in a wine log: queried 6342 times, ERROR_FILE_NOT_FOUND
every time.)

WHY A KEEPALIVE
---------------
Wine's winebus builds the container ID in make_unique_container_id() with
QueryPerformanceCounter() in the low 8 bytes, so it is regenerated every time the
device object is created -- i.e. on every new wineserver.  If each `wine` command
gets its own wineserver, the value we stamp is stale before the game reads it.
So this script holds ONE wineserver open (via a parked cmd.exe started through
CrossOver's own wrapper, which keeps msync registered) and does the read, the
stamp and the launch inside it.

USAGE
    python3 ds2-fix-haptics.py              # stamp + launch, one wineserver
    python3 ds2-fix-haptics.py --hold       # stamp, then hold the server open so
                                            #   you can launch the game yourself
                                            #   (CrossOver GUI or any way you like)
    python3 ds2-fix-haptics.py --binary     # stamp ContainerId as REG_BINARY
    python3 ds2-fix-haptics.py --debug LOG  # stamp + launch with a wine debug log
    python3 ds2-fix-haptics.py --probe      # re-test which wine invocation works
    python3 ds2-fix-haptics.py --kill-orphans   # clear stray wineservers first
"""
import argparse, os, pathlib, re, signal, subprocess, sys, time

CX      = "/Applications/CrossOver.app/Contents/SharedSupport/CrossOver"
WINE    = f"{CX}/bin/wine"
BOTTLE  = "DS2"
BOTTLES = "/Volumes/WD/Crossover"
PREFIX  = f"{BOTTLES}/{BOTTLE}"
DRIVE_C = f"{PREFIX}/drive_c"
GAME    = r"C:\Program Files\DEATH STRANDING 2 ON THE BEACH\DS2.exe"

HID_KEY   = r"HKEY_LOCAL_MACHINE\System\CurrentControlSet\Enum\HID"
AUDIO_KEY = r"HKEY_CURRENT_USER\Software\Wine\Drivers\winecoreaudio.drv\devices"
MMDEV     = r"HKEY_LOCAL_MACHINE\Software\Microsoft\Windows\CurrentVersion\MMDevices\Audio"
CONTAINER_ID = "{8C7ED206-3F8A-4827-B3AB-AE9E1FAEFC6C},2"
PHYS_SPK     = "{1DA5D803-D492-4EDD-8C23-E0C0FFEE7F0E},3"
PAD_RE = re.compile(r'DualSense Wireless Controller:([0-9A-Fa-f]+):(\d+)')


def base_env(extra=None):
    e = dict(os.environ)
    e["CX_BOTTLE_PATH"] = BOTTLES
    e.setdefault("ROSETTA_ADVERTISE_AVX", "1")   # DS2 crashes without it
    for junk in ("CX_DEBUGMSG", "WINEDEBUG", "CX_LOG", "CX_INITIALIZED",
                 "WINEPREFIX", "CX_BOTTLE"):
        e.pop(junk, None)
    if extra: e.update(extra)
    return e


def wine(args, extra_env=None, capture=True):
    return subprocess.run([WINE, "--bottle", BOTTLE, *args], env=base_env(extra_env),
                          capture_output=capture, text=True, errors="replace")


# ---------------------------------------------------------------- wineserver --
def find_wineservers():
    try:
        out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True,
                             text=True, errors="replace").stdout
    except OSError:
        return []
    hits = []
    for line in out.splitlines():
        line = line.strip()
        if "wineserver" in line and "grep" not in line:
            pid, _, cmd = line.partition(" ")
            if pid.isdigit(): hits.append((int(pid), cmd.strip()))
    return hits


def kill_wineservers():
    procs = find_wineservers()
    if not procs:
        print("no wineserver processes running."); return
    print(f"killing {len(procs)} wineserver process(es)")
    for pid, _ in procs:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try: os.kill(pid, sig)
            except (ProcessLookupError, PermissionError): break
            time.sleep(1.0)
            if not any(p == pid for p, _ in find_wineservers()): break
    print("   remaining:", len(find_wineservers()))


def start_keepalive():
    """Park a Windows process so ONE wineserver (with msync registered) stays up."""
    p = subprocess.Popen([WINE, "--bottle", BOTTLE, "cmd"], env=base_env(),
                         stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    time.sleep(4.0)
    if p.poll() is None:
        return p, "cmd.exe"
    p = subprocess.Popen([WINE, "--bottle", BOTTLE, "ping", "-n", "3600", "127.0.0.1"],
                         env=base_env(), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3.0)
    return (p, "ping.exe") if p.poll() is None else (None, None)


def stop_keepalive(proc):
    if not proc or proc.poll() is not None: return
    try:
        if proc.stdin: proc.stdin.close()
    except OSError: pass
    try:
        proc.terminate(); proc.wait(timeout=5)
    except Exception:
        try: proc.kill()
        except Exception: pass


# ------------------------------------------------------------------ registry --
def export_key(key, which):
    host = pathlib.Path(f"{DRIVE_C}/ds2fix_{which}.reg")
    win = rf"C:\ds2fix_{which}.reg"
    if host.exists():
        try: host.unlink()
        except OSError: pass
    wine(["reg", "export", key, win, "/y"])
    time.sleep(0.6)
    if not host.exists(): return ""
    data = host.read_bytes()
    for enc in ("utf-16", "utf-8-sig", "utf-8", "latin-1"):
        try:
            t = data.decode(enc)
            if "[HKEY" in t: return t
        except UnicodeError: continue
    return ""


def parse_reg(text):
    text = re.sub(r'\\\r?\n\s*', '', text)
    out, key = {}, None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("["):
            key = s[1:s.rindex("]")] if "]" in s else s[1:]
            out.setdefault(key, {})
        elif key and s.startswith('"'):
            m = re.match(r'"((?:[^"\\]|\\.)*)"=(.*)', s)
            if m: out[key][m.group(1)] = m.group(2)
    return out


def guid_from_hex(h):
    b = bytes(int(x, 16) for x in re.findall(r'[0-9A-Fa-f]{2}', h))
    if len(b) != 16: return None
    rest = b[8:].hex().upper()
    return "{%08X-%04X-%04X-%s-%s}" % (int.from_bytes(b[0:4], "little"),
                                       int.from_bytes(b[4:6], "little"),
                                       int.from_bytes(b[6:8], "little"),
                                       rest[:4], rest[4:])


def read_pad_containers():
    text = export_key(HID_KEY, "hid")
    out, total = {}, 0
    for key, vals in parse_reg(text).items():
        total += 1
        if "VID_054C" not in key.upper(): continue
        cid = vals.get("ContainerId", "").strip('"')
        leaf = key.split("\\")[-1]; parts = leaf.split("&")
        if not cid or len(parts) <= 3: continue
        loc, primary = parts[2].lower(), leaf.endswith("&0&0")
        if loc not in out or (primary and not out[loc][1]):
            out[loc] = (cid, primary)
    return {k: v[0] for k, v in out.items()}, total


def read_endpoints():
    eps = []
    for key, vals in parse_reg(export_key(AUDIO_KEY, "audio")).items():
        if "devices\\" not in key: continue
        dev = key.split("devices\\", 1)[1]
        m, raw = PAD_RE.search(dev), vals.get("guid", "")
        if m and raw.startswith("hex:"):
            g = guid_from_hex(raw[4:])
            if g: eps.append((m.group(1).lower(),
                              "Render" if dev.split(",", 1)[0] == "0" else "Capture", g))
    return eps


def stamp(eps, pads, binary):
    n = 0
    for loc, flow, guid in sorted(eps):
        cid = pads.get(loc)
        if not cid:
            print(f"   -  {flow:7s} {guid} (loc {loc}) - no live HID node, skipped"); continue
        key = f"{MMDEV}\\{flow}\\{guid}\\Properties"
        if binary:
            b = bytes.fromhex(cid.strip("{}").replace("-", ""))
            raw = (b[3::-1] + b[5:3:-1] + b[7:5:-1] + b[8:]).hex()
            wine(["reg", "add", key, "/v", CONTAINER_ID, "/t", "REG_BINARY", "/d", raw, "/f"])
        else:
            wine(["reg", "add", key, "/v", CONTAINER_ID, "/t", "REG_SZ", "/d", cid, "/f"])
        if flow == "Render":
            wine(["reg", "add", key, "/v", PHYS_SPK, "/t", "REG_DWORD", "/d", "51", "/f"])
        print(f"   +  {flow:7s} {guid} (loc {loc}) <- {cid}")
        n += 1
    return n


def guid_bytes(cid):
    """'{0CE6054C-0000-FFFF-08A0-6C92E8010000}' -> the 16 raw bytes Windows stores."""
    h = cid.strip("{}").replace("-", "")
    b = bytes.fromhex(h)
    return b[3::-1] + b[5:3:-1] + b[7:5:-1] + b[8:]


def stamp_rawguid(eps, pads):
    """Write ContainerId as a REG_SZ whose FIRST 16 BYTES are the raw GUID.

    The game reads PROPVARIANT.puuid without checking .vt.  Wine can only return
    VT_LPWSTR for a REG_SZ, so the game dereferences pwszVal and reads 16 bytes
    from the string buffer.  If those bytes *are* the GUID, the blind read yields
    the right answer.  hex(1): lets us store a REG_SZ containing NUL bytes, which
    'reg add /t REG_SZ' cannot express.
    """
    lines = ["Windows Registry Editor Version 5.00", ""]
    n = 0
    for loc, flow, guid in sorted(eps):
        cid = pads.get(loc)
        if not cid:
            print(f"   -  {flow:7s} {guid} (loc {loc}) - no live HID node, skipped"); continue
        raw = guid_bytes(cid) + b"\x00\x00"          # + UTF-16 NUL terminator
        csv = ",".join(f"{x:02x}" for x in raw)
        lines.append(f"[{MMDEV}\\{flow}\\{guid}\\Properties]")
        lines.append(f'"{CONTAINER_ID}"=hex(1):{csv}')
        if flow == "Render":
            lines.append(f'"{PHYS_SPK}"=dword:00000033')
        lines.append("")
        print(f"   +  {flow:7s} {guid} (loc {loc}) <- raw bytes of {cid}")
        n += 1
    if not n:
        return 0
    host = pathlib.Path(f"{DRIVE_C}/ds2fix_guid.reg")
    host.write_bytes(b"\xff\xfe" + "\r\n".join(lines).encode("utf-16-le"))
    r = wine(["reg", "import", r"C:\ds2fix_guid.reg"])
    if r.returncode != 0:
        print("   !! reg import failed:", (r.stdout or "") + (r.stderr or ""))
        return 0
    return n


def revert(eps):
    """Remove the ContainerId property we added, restoring stock behaviour."""
    n = 0
    for loc, flow, guid in sorted(eps):
        key = f"{MMDEV}\\{flow}\\{guid}\\Properties"
        wine(["reg", "delete", key, "/v", CONTAINER_ID, "/f"])
        print(f"   -  removed ContainerId from {flow:7s} {guid} (loc {loc})")
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", action="store_true",
                    help="stamp, then keep the wineserver open and let you launch the game")
    ap.add_argument("--binary", action="store_true",
                    help="write ContainerId as REG_BINARY - KNOWN TO CRASH THE GAME, diagnostic only")
    ap.add_argument("--rawguid", action="store_true",
                    help="write ContainerId as a REG_SZ whose bytes ARE the GUID "
                         "(works around Wine being unable to return VT_CLSID)")
    ap.add_argument("--revert", action="store_true",
                    help="remove the ContainerId property entirely and exit")
    ap.add_argument("--debug", metavar="LOGFILE", default=None)
    ap.add_argument("--kill-orphans", action="store_true")
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args()

    if not os.path.isdir(PREFIX): sys.exit(f"!! bottle not found at {PREFIX}")
    if args.kill_orphans:
        kill_wineservers(); time.sleep(2.0); print()

    t0 = time.time()
    print("holding one wineserver open ...")
    keeper, how = start_keepalive()
    if not keeper:
        sys.exit("!! could not park a process to hold wineserver open.")
    print(f"   parked {how}  (pid {keeper.pid})")

    try:
        pads, total = read_pad_containers()
        eps = read_endpoints()
        print(f"\nHID nodes: {total}   DualSense nodes: {len(pads)}   audio endpoints: {len(eps)}")
        for loc, cid in sorted(pads.items()):
            print(f"   usb location {loc:8s} -> {cid}")
        if not pads: sys.exit("!! no DualSense HID node - pad connected by USB?")
        if not eps:  sys.exit("!! no DualSense audio endpoint registered in this bottle.")

        # prove the IDs are stable inside this server before relying on them
        time.sleep(2.0)
        again, _ = read_pad_containers()
        drift = sorted(l for l in pads if again.get(l) != pads[l])
        if drift:
            print(f"\n!! container IDs still drifting (locations {drift}) even with the")
            print("   wineserver held open. The keepalive is not holding the device object;")
            print("   this approach cannot work - tell me and we patch mmdevapi instead.")
            return
        print("   container IDs stable across two reads - good.")

        if args.revert:
            print("\nremoving the ContainerId property from the DualSense endpoints ...")
            revert(eps)
            print("   done - the bottle is back to stock behaviour.")
            return

        if args.binary:
            print("\n!! --binary is diagnostic only: it makes the game read a VT_BLOB where it\n"
                  "   expects a GUID pointer, which crashes it. Continuing because you asked.")
        if args.rawguid:
            print("\nstamping ContainerId as raw GUID bytes inside a REG_SZ ...")
            if not stamp_rawguid(eps, pads): sys.exit("!! nothing stamped.")
        else:
            print("\nstamping ContainerId onto the matching audio endpoints ...")
            if not stamp(eps, pads, args.binary): sys.exit("!! nothing stamped.")

        final, _ = read_pad_containers()
        if any(final.get(l) != pads[l] for l in pads):
            print("!! IDs changed after stamping - aborting rather than launching stale.")
            return
        print(f"   verified current.  ({time.time()-t0:.0f}s elapsed)")

        if args.hold:
            print("\nwineserver is held open and the endpoints are stamped.")
            print("Launch Death Stranding 2 now, any way you like (CrossOver app is fine).")
            print("Leave this terminal running while you play; press Ctrl-C when done.")
            try:
                while keeper.poll() is None: time.sleep(5)
            except KeyboardInterrupt:
                print("\nreleasing.")
            return

        print("\nlaunching the game in this same wineserver ...")
        argv, extra = ["--bottle", BOTTLE], None
        if args.debug:
            extra = {"CX_DEBUGMSG": "+mmdevapi,+coreaudio,+setupapi"}
            argv += ["--cx-log", args.debug]
        argv.append(GAME)
        subprocess.run([WINE, *argv], env=base_env(extra))
    finally:
        stop_keepalive(keeper)


if __name__ == "__main__":
    main()
