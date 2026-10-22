"""Launcher-created profiles and scripts connecting two actual mGBA Lua engines."""
import asyncio
import ctypes as C
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import test_rom
from test_launcher import Emulator, free_port, game_package
from soullink.launcher.service import Controller
from soullink.relay.model import DEFAULT_RULES


@unittest.skipUnless(os.environ.get('SOUL_ADAPTER'), 'requires mGBA adapter')
class LauncherRomTests(unittest.IsolatedAsyncioTestCase):
    async def test_play_generated_scripts_link_and_defer_death(self):
        test_rom.RomTests.setUpClass()
        lib = test_rom.RomTests.lib
        lib.sl_script.argtypes = [C.c_void_p, C.c_char_p]
        lib.sl_script.restype = C.c_int
        lib.sl_tick.argtypes = [C.c_void_p]
        emulators = []
        controllers = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                package = game_package(root / 'package', Path(os.environ['SOUL_ROM']).read_bytes())
                for _ in range(2):
                    emulator = test_rom.RomTests()
                    emulator.setUp()
                    emulators.append(emulator)
                    emulator.write(emulator.save+4, 0)
                    emulator.write(emulator.box+24, 0)
                    emulator.write(emulator.box+20, 0)
                    emulator.write(emulator.box+40, 0)
                import json
                manifest = json.loads((package.directory / 'manifest.json').read_text())
                manifest['mailbox'] = f'{emulators[0].box:08x}'
                (package.directory / 'manifest.json').write_text(json.dumps(manifest))
                host, guest = Controller(root / 'host'), Controller(root / 'guest')
                controllers.extend([host, guest])
                for controller in controllers:
                    controller.profiles.remember(package=str(package.directory), mgba=str(root / 'mgba.exe'))
                port = free_port()
                await host.host('integration', port, 1, DEFAULT_RULES)
                await guest.join(await host.invite('127.0.0.1', port))
                with patch('soullink.launcher.service.check_mgba', AsyncMock(return_value=root / 'mgba.exe')), \
                     patch('soullink.launcher.service.subprocess.Popen', Emulator):
                    for controller, emulator in zip(controllers, emulators):
                        await controller.play()
                        script = controller.emulator.args[2]
                        self.assertEqual(lib.sl_script(emulator.h, str(script).encode()), 1)
                    async def tick_until(predicate):
                        for _ in range(700):
                            for emulator in emulators:
                                emulator.call('SoulLink_Frame')
                                lib.sl_tick(emulator.h)
                            if predicate():
                                return
                            await asyncio.sleep(0.01)
                        self.fail('launcher scripts did not synchronize')
                    await tick_until(lambda: all(t.read(t.box+20) == 2 for t in emulators))
                    for t in emulators:
                        t.call('SoulLink_SendSettings', DEFAULT_RULES, 1, 1)
                    await tick_until(lambda: all(t.read(t.box+40) == 1 for t in emulators))
                    self.assertTrue((await guest.info())['locked'])
                    for t in emulators:
                        t.mon()
                    await tick_until(lambda: all(t.read(t.box+160+511*18+16, 1) == 2 for t in emulators))
                    for t in emulators:
                        t.call('ScriptContext_Init')
                        t.call('UnlockPlayerFieldControls')
                        t.call('SoulLink_Overworld')
                    a, b = emulators
                    b.call('LockPlayerFieldControls')
                    a.call('SoulLink_Faint', a.party)
                    await tick_until(lambda: b.read(b.box+160+511*18+16, 1) == 3)
                    b.call('SoulLink_Overworld')
                    self.assertEqual(b.read(b.save+20+511, 1), 2)
                    b.call('UnlockPlayerFieldControls')
                    b.call('SoulLink_Overworld')
                    self.assertEqual(b.read(b.save+20+511, 1), 3)
            finally:
                for controller in reversed(controllers):
                    await controller.stop(close_game=True)
                for emulator in emulators:
                    emulator.tearDown()
