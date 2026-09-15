# SPDX-License-Identifier: MIT
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('launcher', Path(__file__).resolve().parents[1] / 'scripts/ds2-fix-haptics.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
CID = '{0CE6054C-0000-FFFF-8AF9-BD7600000000}'
END = '{4AFBE95D-3391-4FD8-BA16-CF58AD351674}'


class Tests(unittest.TestCase):
    def test_endpoint_parser_and_sony_identity(self):
        ids, eps = m.parse_probe(f'SONY_ID={CID}\r\nENDPOINT=Render|{{0.0.0.00000000}}.{END}|72|{CID}\r\n')
        self.assertEqual(ids, [CID]); self.assertEqual(eps, [('Render', END, 72, CID)])

    def test_ambiguous_endpoints_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse_probe(f'ENDPOINT=Render|{END}|0|\n' * 2)

    def test_no_controller_refused(self):
        with self.assertRaises(RuntimeError):
            m.parse_probe('WIRED_COUNT=0\n')

    def test_atomic_copy_does_not_follow_target_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); a=root/'app'; a.write_text('stock')
            b=root/'bottle'; b.symlink_to(a); src=root/'patch'; src.write_text('patch')
            m.atomic_copy(src,b)
            self.assertEqual(a.read_text(),'stock'); self.assertFalse(b.is_symlink())

    def exercise(self, fail_stage=None, existing=False, permanent=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); bottle=root/'bottle'; cx=root/'cx'; state=bottle/'.ds2-haptics'; assets=root/'assets'
            dll=bottle/'drive_c/windows/system32/mmdevapi.dll'; stock=cx/'lib/wine/x86_64-windows/mmdevapi.dll'
            for p in (dll,stock):p.parent.mkdir(parents=True);p.write_bytes(b'stock')
            state.mkdir();assets.mkdir();(assets/'mmdevapi.dll').write_bytes(b'patch')
            fix=m.Fix(bottle,cx,state); calls=[]; registry={}; deletes=[]
            key=f'{m.MMDEV}\\Render\\{END}\\Properties'
            if existing:registry[key]='user-value'
            def run(args, **kwargs):
                calls.append(args)
                if args[0].endswith('controller-probe.exe'):
                    if fail_stage=='probe':raise RuntimeError('probe failed')
                    if args[1]=='-':
                        value='wrong' if fail_stage=='verify' else CID
                        return 0, f'ENDPOINT=Render|{END}|72|{value}\n'
                    return 0,f'SONY_ID={CID}\nENDPOINT=Render|{END}|0|\n'
                op,k=args[1:3]
                if op=='query':return (0 if k in registry else 1),'REG_SZ    '+registry.get(k,'')
                if op=='add':
                    registry[k]=args[args.index('/d')+1]
                    if fail_stage=='stamp':raise RuntimeError('partial write')
                if op=='delete':deletes.append(k);registry.pop(k,None)
                return 0,''
            with patch.object(m,'STOCK_SHA',m.sha(stock)), patch.object(m,'PATCH_SHA',m.sha(assets/'mmdevapi.dll')), patch.object(fix,'run',side_effect=run), patch.object(fix,'start'), patch.object(fix,'keeper') as keeper:
                keeper.poll.return_value=None
                if fail_stage or existing:
                    with self.assertRaises(RuntimeError):fix.launch(root/'Sony.dll',root/'DS2.exe',assets,True)
                else:
                    fix.launch(root/'Sony.dll',root/'DS2.exe',assets,not permanent,permanent)
                    if permanent:
                        self.assertEqual(dll.read_bytes(),b'patch')
                        self.assertEqual(registry[key],CID)
                        saved=json.loads((state/'state.json').read_text())
                        self.assertEqual(saved['mode'],'installed')
                        self.assertEqual(registry[saved['override_key']],'native,builtin')
                        fix.restore()
            self.assertEqual(dll.read_bytes(),b'stock')
            self.assertFalse((state/'state.json').exists())
            if existing:
                self.assertEqual(registry[key],'user-value');self.assertEqual(deletes,[])
            else:self.assertEqual(registry,{})

    def test_successful_preflight_restores(self):self.exercise()
    def test_permanent_install_and_uninstall(self):self.exercise(permanent=True)
    def test_failed_probe_restores(self):self.exercise('probe')
    def test_partial_registry_write_restores(self):self.exercise('stamp')
    def test_wrong_identity_restores(self):self.exercise('verify')
    def test_existing_property_is_preserved(self):self.exercise(existing=True)

    def test_recovery_refuses_external_dll_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);state=root/'state';state.mkdir()
            original=state/'mmdevapi.original.dll';original.write_bytes(b'stock')
            fix=m.Fix(root,root,state);fix.dll=root/'dll';fix.dll.write_bytes(b'other change')
            (state/'state.json').write_text(json.dumps({'bottle':str(root),'original_sha256':m.sha(original),'keys':[]}))
            with self.assertRaises(RuntimeError):fix.restore()
            self.assertEqual(fix.dll.read_bytes(),b'other change')
            self.assertTrue((state/'state.json').exists())

if __name__=='__main__':unittest.main()
