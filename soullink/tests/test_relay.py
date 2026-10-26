import asyncio
import tempfile
import unittest
from pathlib import Path
from soullink.relay.model import Store, Rules, ProtocolError, LINKED, DEAD, FORFEITED, PENDING, DEFAULT_RULES, BUILD
from soullink.relay.server import Relay

NAME = 'bb'*10 + 'ff'
TRAINER = 'cc'*7 + 'ff'


class StateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'relay.db'
        self.store = Store(self.path)
        self.state = self.store.create('test')
        self.seq = [0, 0]
        self.event(0, 'confirm', DEFAULT_RULES, 1)
        self.event(1, 'confirm', DEFAULT_RULES, 1)

    def tearDown(self):
        self.store.db.close()
        self.directory.cleanup()

    def event(self, player, kind, *args):
        result = self.store.event('test', player, self.seq[player]+1, kind, list(map(str,args)))
        self.seq[player] += 1
        return result

    def catch(self, player, area=1, species=1, type=1, gender=0):
        return self.event(player, 'catch', area, species, type, gender, NAME, 1)

    def test_nuzlocke_options_confirm_lock_and_restart(self):
        from soullink.relay.model import START_OPTIONS
        rules = int(DEFAULT_RULES | Rules.NO_BATTLE_ITEMS | Rules.FORCE_SET) | START_OPTIONS | (2 << 14) | (19 << 18)
        self.store.create('options', rules=rules)
        self.store.configure('options', 42, rules)
        self.store.event('options', 0, 1, 'confirm', [rules, 42])
        state = self.store.event('options', 1, 1, 'confirm', [rules, 42])
        self.assertTrue(state['locked'])
        self.assertEqual(state['rules'], rules)
        with self.assertRaises(ProtocolError):
            self.store.configure('options', 42, 97)
        self.store.event('options', 0, 2, 'wipe', [])
        self.assertEqual(self.store.restart('options')['rules'], rules)

    def test_qol_permissions_defaults_legacy_and_host_lock(self):
        from soullink.relay.model import QOL_RULES, validate_rules
        from soullink.launcher.storage import RULE_BITS, RULES as LABELS
        self.assertEqual(DEFAULT_RULES & QOL_RULES, QOL_RULES)
        self.assertEqual(validate_rules(97), 97)
        self.assertEqual(len(RULE_BITS), len(LABELS))
        self.assertEqual(set(RULE_BITS[-5:]), set(range(24, 29)))
        for bit in range(24, 29):
            self.assertEqual(validate_rules(1 << bit), 1 << bit)
        self.store.create('qol', rules=97)
        with self.assertRaises(ProtocolError):
            self.store.event('qol', 1, 1, 'settings', [DEFAULT_RULES, 1])
        self.store.configure('qol', 1, DEFAULT_RULES)
        self.store.event('qol', 0, 1, 'confirm', [DEFAULT_RULES, 1])
        self.store.event('qol', 1, 1, 'confirm', [DEFAULT_RULES, 1])
        with self.assertRaises(ProtocolError):
            self.store.configure('qol', 1, 97)

    def test_invalid_start_options_rejected(self):
        from soullink.relay.model import START_OPTIONS
        for rules in (1 << 29, START_OPTIONS | (3 << 14), START_OPTIONS | (20 << 18), 1 << 16):
            with self.subTest(rules=rules), self.assertRaises(ProtocolError):
                self.store.create('invalid', rules=rules)

    def test_duplicate_room_preserves_existing_run(self):
        self.catch(0)
        before = self.store.get('test')
        with self.assertRaisesRegex(ProtocolError, 'without --create'):
            self.store.create('test', seed=999)
        self.assertEqual(self.store.get('test'), before)

    def test_pair_and_death_after_restart(self):
        self.assertEqual(Store.status(self.catch(0), 1), PENDING)
        self.assertEqual(Store.status(self.catch(1), 1), LINKED)
        self.event(0, 'death', 1)
        self.store.db.close()
        self.store = Store(self.path)
        self.assertEqual(Store.status(self.store.get('test'), 1), DEAD)

    def test_restart_preserves_credentials_clears_run_and_reuses_sequences(self):
        self.catch(0); self.catch(1)
        ended = self.event(0, 'wipe')
        admin = Store(self.path)
        try:
            fresh = admin.restart('test')
        finally:
            admin.db.close()
        self.assertNotEqual(fresh['run'], ended['run'])
        for field in ('tokens', 'rules', 'seed'):
            self.assertEqual(fresh[field], ended[field])
        self.assertFalse(fresh['ended'])
        self.assertFalse(fresh['locked'])
        self.assertEqual(fresh['mons'], [{}, {}])
        self.assertEqual(fresh['seq'], [0, 0])
        self.assertEqual(self.store.get('test'), fresh)
        with self.assertRaises(ProtocolError):
            self.store.event('test', 0, 1, 'confirm', [DEFAULT_RULES, 1], expected_run=ended['run'])
        for p in range(2):
            self.store.authenticate('test', p, ended['tokens'][p])
            self.store.event('test', p, 1, 'confirm', [DEFAULT_RULES, 1], expected_run=fresh['run'])
        self.assertTrue(self.store.get('test')['locked'])

    def test_restart_rejects_active_run_and_invalid_seed_atomically(self):
        before = self.store.get('test')
        with self.assertRaises(ProtocolError):
            self.store.restart('test')
        self.assertEqual(self.store.get('test'), before)
        ended = self.event(0, 'wipe')
        with self.assertRaises(ProtocolError):
            self.store.restart('test', -1)
        self.assertEqual(self.store.get('test'), ended)
        self.assertEqual(self.store.restart('test', 123)['seed'], 123)

    def test_failure_before_partner_catch(self):
        self.event(0, 'fail', 8)
        self.assertEqual(Store.status(self.catch(1, 8), 8), FORFEITED)

    def test_duplicate_event_is_idempotent(self):
        state = self.catch(0)
        same = self.store.event('test', 0, self.seq[0], 'catch', ['1','1','1','0',NAME,'1'])
        self.assertEqual(state, same)
        with self.assertRaises(ProtocolError):
            self.store.event('test', 0, self.seq[0], 'death', ['1'])

    def test_gap_and_locked_settings_rejected_without_commit(self):
        before = self.store.get('test')
        with self.assertRaises(ProtocolError):
            self.store.event('test', 0, 100, 'wipe', [])
        with self.assertRaises(ProtocolError):
            self.event(0, 'settings', 0, 3)
        self.assertEqual(before, self.store.get('test'))

    def test_pair_death_before_second_catch(self):
        self.catch(0)
        self.event(0, 'death', 1)
        self.assertEqual(Store.status(self.catch(1), 1), DEAD)

    def test_party_requires_agreement(self):
        self.catch(0); self.catch(1)
        self.catch(0, 2); self.catch(1, 2)
        state = self.event(0, 'party', 1)
        self.assertEqual(state['party'], [[1,2], [1,2]])
        state = self.event(1, 'party', 1)
        self.assertEqual(state['party'], [[1], [1]])

    def test_type_and_gender_rules(self):
        a = dict(type=1, gender=0)
        self.assertFalse(Store.compatible(int(Rules.GENDER), a, a))
        self.assertTrue(Store.compatible(int(Rules.GENDER), a, dict(type=1,gender=255)))
        self.assertFalse(Store.compatible(int(Rules.PAIR_TYPE), a, a))
        self.assertTrue(Store.compatible(0, a, a))

    def test_wipe_ends_run(self):
        self.catch(0); self.catch(1)
        state = self.event(0, 'wipe')
        self.assertTrue(state['ended'])
        self.assertEqual(Store.status(state, 1), DEAD)

    def test_bad_names_and_bounds(self):
        for args in (['512','1','1','0',NAME,'1'], ['1','1','1','0','00','1']):
            with self.assertRaises(ProtocolError):
                self.store.event('test', 0, 2, 'catch', args)

    def test_simultaneous_incompatible_encounters_reroll_second(self):
        state = self.store.get('test')
        state['rules'] |= int(Rules.PAIR_TYPE)
        with self.store.db: self.store.save('test', state)
        self.event(0,'reserve',1,1,1,0,NAME,0)
        self.event(1,'reserve',1,2,1,254,NAME,0)
        state = self.store.get('test')
        self.assertIn('1',state['reservations'][0])
        self.assertNotIn('1',state['reservations'][1])
        self.event(1,'finish',1)
        self.assertNotIn(1,self.store.get('test')['failures'])
        self.event(0,'finish',1)
        self.assertIn(1,self.store.get('test')['failures'])

    def test_evolution_updates_remote_species_and_type(self):
        self.catch(0); self.catch(1)
        state = self.event(0,'rename',1,NAME,2,3)
        self.assertEqual(state['mons'][0]['1']['species'],2)
        self.assertEqual(state['mons'][0]['1']['type'],3)

    def test_snapshot_has_fixed_abi_size(self):
        self.catch(0); self.catch(1)
        fields = Relay(self.store).snapshot('test', 0).split()
        self.assertEqual(len(fields), 12)
        self.assertEqual(len(bytes.fromhex(fields[-1])), 512*18)


class NetworkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store(':memory:')
        self.state = self.store.create('room')
        self.relay = Relay(self.store)
        self.server = await asyncio.start_server(self.relay.handle, '127.0.0.1', 0, limit=4096)
        self.port = self.server.sockets[0].getsockname()[1]
        self.writers = []

    async def asyncTearDown(self):
        for writer in self.writers:
            writer.close()
            await writer.wait_closed()
        self.server.close()
        await self.server.wait_closed()
        await asyncio.sleep(0.01)
        self.store.db.close()

    async def connect(self, player, token=None):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.port)
        self.writers.append(writer)
        token = token or self.state['tokens'][player]
        writer.write(f'HELLO 1 {BUILD} room {player} {token} {TRAINER} 0\n'.encode())
        await writer.drain()
        return reader, writer, (await asyncio.wait_for(reader.readline(), 2)).decode()

    async def test_auth_presence_and_fragmented_event(self):
        a, aw, snapshot = await self.connect(0)
        self.assertEqual(snapshot.split()[8], '0')
        b, bw, snapshot = await self.connect(1)
        self.assertEqual(snapshot.split()[8], '1')
        aw.write(f'EVENT 1 confirm {DEFAULT_RULES}'.encode())
        await aw.drain()
        aw.write(b' 1\n')
        await aw.drain()
        self.assertEqual(await a.readline(),b'NOTICE 0\n')
        self.assertTrue((await a.readline()).startswith(b'STATE'))
        bw.write(f'EVENT 1 confirm {DEFAULT_RULES} 1\n'.encode())
        await bw.drain()
        self.assertEqual(await b.readline(),b'NOTICE 0\n')
        self.assertEqual((await b.readline()).split()[6], b'1')
        aw.write(b'POS 1 2 3 1 0 1 1\n')
        await aw.drain()
        self.assertEqual(await b.readline(), b'POS 1 2 3 1 0 1 1\n')

    async def test_restart_rejects_connected_old_run_and_accepts_same_credentials(self):
        reader, writer, _ = await self.connect(0)
        with self.store.db:
            ended = self.store.get('room')
            ended['ended'] = True
            self.store.save('room', ended)
        self.store.restart('room')
        writer.write(f'EVENT 1 confirm {DEFAULT_RULES} 1\n'.encode())
        await writer.drain()
        self.assertIn(b'run restarted', await reader.readline())
        self.assertEqual(await reader.read(), b'')
        self.assertEqual(self.store.get('room')['seq'], [0, 0])
        _, _, snapshot = await self.connect(0)
        self.assertTrue(snapshot.startswith('STATE'))
        self.assertNotEqual(int(snapshot.split()[1]), ended['run'])

    async def test_invalid_auth_does_not_evict_real_player(self):
        _, _, first = await self.connect(0)
        _, _, error = await self.connect(0, 'invalid')
        self.assertTrue(error.startswith('ERROR'))
        self.assertIn(('room', 0), self.relay.clients)


if __name__ == '__main__':
    unittest.main()
