"""Two real mGBA Lua engines -> local connectors -> TCP relay -> compiled ROM hooks."""
import asyncio
import ctypes as C
import os
from pathlib import Path
import socket
import tempfile
import unittest
import test_rom
from soullink.relay.model import Store
from soullink.relay.server import Relay
from soullink.bridge.client import run


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


@unittest.skipUnless(os.environ.get('SOUL_ADAPTER'), 'requires mGBA adapter')
class EndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_emulators_pair_and_defer_remote_death(self):
        test_rom.RomTests.setUpClass()
        lib=test_rom.RomTests.lib
        lib.sl_script.argtypes=[C.c_void_p,C.c_char_p];lib.sl_script.restype=C.c_int
        lib.sl_tick.argtypes=[C.c_void_p]
        emulators=[];tasks=[];server=None
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'relay.sqlite3')
            state=store.create('integration')
            relay=Relay(store)
            try:
                server=await asyncio.start_server(relay.handle,'127.0.0.1',0,limit=4096)
                relay_port=server.sockets[0].getsockname()[1]
                template=(Path(__file__).parents[1]/'bridge/bridge.lua').read_text()
                for player in range(2):
                    t=test_rom.RomTests();t.setUp();emulators.append(t)
                    # These isolated game fixtures have not yet joined a room.
                    t.write(t.save+4,0);t.write(t.box+24,0)
                    t.write(t.box+20,0);t.write(t.box+40,0)
                    port=free_port()
                    script=Path(directory)/f'player{player}.lua'
                    script.write_text(f'SOUL_ADDRESS={t.box}\nSOUL_CONFIG={{room="integration",player={player},token="{state["tokens"][player]}",local_port={port}}}\n'+template)
                    self.assertEqual(lib.sl_script(t.h,str(script).encode()),1)
                    tasks.append(asyncio.create_task(run('127.0.0.1',relay_port,port)))
                async def tick_until(predicate):
                    for _ in range(500):
                        for t in emulators:
                            t.call('SoulLink_Frame');lib.sl_tick(t.h)
                        if predicate(): return
                        await asyncio.sleep(0.01)
                    self.fail('timed out waiting for end-to-end synchronization; connection states: '+str([t.read(t.box+20) for t in emulators]))
                await tick_until(lambda:all(t.read(t.box+20)==2 for t in emulators))
                # Simulate a long focus pause: Python/relay keep running while
                # neither emulator produces frame callbacks. Both must reconnect
                # after the relay's idle timeout without losing the run.
                await asyncio.sleep(5.2)
                self.assertFalse(relay.clients)
                await tick_until(lambda:all(t.read(t.box+20)==2 for t in emulators))
                for t in emulators:t.call('SoulLink_SendSettings',state['rules'],1,1)
                await tick_until(lambda:all(t.read(t.box+40)==1 for t in emulators))
                for t in emulators:t.mon()
                await tick_until(lambda:all(t.read(t.box+160+511*18+16,1)==2 for t in emulators))
                for t in emulators:
                    t.call('ScriptContext_Init');t.call('UnlockPlayerFieldControls');t.call('SoulLink_Overworld')
                    self.assertEqual(t.read(t.save+20+511,1),2)
                a,b=emulators
                b.call('LockPlayerFieldControls')
                a.call('SoulLink_Faint',a.party)
                await tick_until(lambda:b.read(b.box+160+511*18+16,1)==3)
                b.call('SoulLink_Overworld')
                self.assertEqual(b.read(b.save+20+511,1),2,'remote death must wait until safe')
                b.call('UnlockPlayerFieldControls');b.call('SoulLink_Overworld')
                self.assertEqual(b.read(b.save+20+511,1),3)
                self.assertEqual(b.call('GetMonData3',b.party,b.fields['MON_DATA_HP'],0),0)
            finally:
                for task in tasks:task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)
                if server:server.close();await server.wait_closed()
                await asyncio.sleep(0.02)
                for t in emulators:t.tearDown()
                store.db.close()
