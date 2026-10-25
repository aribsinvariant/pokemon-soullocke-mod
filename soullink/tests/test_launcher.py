import asyncio
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, patch
from soullink.launcher.storage import GamePackage, Invite, Profiles, save_json
from soullink.launcher.service import Controller, check_mgba, session_info
from soullink.launcher.network import PortMapping, public_ipv4
from soullink.relay.model import DEFAULT_RULES, ProtocolError


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def game_package(root, content=b'test game'):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'emerald-soullink.gba').write_bytes(content)
    save_json(root / 'manifest.json', dict(protocol=1, build='534c0001', mailbox='0203ac30',
                                          sha256=hashlib.sha256(content).hexdigest()))
    return GamePackage.load(root)


class PackageInviteTests(unittest.TestCase):
    def test_invite_roundtrip_and_input_validation(self):
        invite = Invite('192.168.1.10', 8768, 'room123', 'a' * 32, 'b' * 64)
        self.assertEqual(Invite.decode(invite.encode()), invite)
        for invalid in ('http://server', 'soullink://join?data=???', 'x' * 3000):
            with self.assertRaises(ValueError):
                Invite.decode(invalid)
        for host in ('http://server', 'server/path', 'bad\nhost'):
            with self.assertRaises(ValueError):
                Invite(host, 8768, 'room', 'a' * 32, 'b' * 64)
        data = json.loads(base64.urlsafe_b64decode(invite.encode().split('data=')[1] + '==='))
        data['player'] = 0
        forged = 'soullink://join?data=' + base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip('=')
        with self.assertRaises(ValueError):
            Invite.decode(forged)

    def test_package_detects_mismatched_rom(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = game_package(Path(tmp))
            package.rom.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'does not match'):
                GamePackage.load(tmp)

    def test_profiles_persist_and_reject_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            profiles = Profiles(tmp)
            profile = profiles.create(name='test', token='private')
            self.assertEqual(Profiles(tmp).list(), [profile])
            profiles.remember(package='game')
            self.assertEqual(Profiles(tmp).settings['package'], 'game')
            with self.assertRaises(ValueError):
                profiles.directory(dict(id='../outside'))


class Router:
    lanaddr = '192.168.1.20'
    discoverdelay = 0

    def __init__(self, external='8.8.4.4', existing=None):
        self.external = external
        self.entry = existing
        self.deleted = []
        self.added = []

    def discover(self): return 1
    def selectigd(self): pass
    def externalipaddress(self): return self.external
    def getspecificportmapping(self, port, protocol): return self.entry

    def addportmapping(self, port, protocol, client, internal, description, remote, lease):
        self.entry = client, internal, description, '1', lease
        self.added.append((port, client, lease))
        return True

    def deleteportmapping(self, port, protocol):
        self.deleted.append(port)
        self.entry = None


class PublicAddressTests(unittest.TestCase):
    def test_external_address_detection_does_not_require_upnp(self):
        def opener(request, timeout):
            self.assertTrue(request.full_url.startswith('https://'))
            self.assertEqual(timeout, 3)
            return io.BytesIO(b'8.8.4.4\n')
        self.assertEqual(public_ipv4(opener), '8.8.4.4')

    def test_provider_failure_uses_the_next_provider(self):
        replies = iter([OSError('unavailable'), io.BytesIO(b'8.8.4.4')])
        def opener(*args, **kwargs):
            result = next(replies)
            if isinstance(result, Exception):
                raise result
            return result
        self.assertEqual(public_ipv4(opener), '8.8.4.4')

    def test_private_ipv6_html_and_oversized_responses_are_rejected(self):
        for response in (b'100.64.0.1', b'10.0.0.1', b'2001:4860:4860::8888',
                         b'<!doctype html>', b'x' * 200):
            self.assertIsNone(public_ipv4(lambda *args, **kwargs: io.BytesIO(response)))

class MappingTests(unittest.TestCase):
    def test_own_mapping_renewed_and_removed(self):
        router = Router()
        mapping = PortMapping(lambda: router)
        self.assertTrue(mapping.open(8768)['ok'])
        self.assertTrue(mapping.renew())
        mapping.close()
        self.assertEqual(router.deleted, [8768])
        self.assertEqual(len(router.added), 2)

    def test_conflicting_mapping_never_overwritten_or_removed(self):
        router = Router(existing=('192.168.1.99', 8768, 'another app'))
        mapping = PortMapping(lambda: router)
        self.assertFalse(mapping.open(8768)['ok'])
        mapping.close()
        self.assertEqual(router.added, [])
        self.assertEqual(router.deleted, [])

    def test_mapping_replaced_by_another_app_is_left_alone(self):
        router = Router()
        mapping = PortMapping(lambda: router)
        mapping.open(8768)
        router.entry = router.lanaddr, 8768, 'someone else'
        mapping.close()
        self.assertEqual(router.deleted, [])

    def test_cgnat_and_disabled_upnp_have_manual_fallback(self):
        router = Router(external='100.64.0.1')
        mapping = PortMapping(lambda: router)
        self.assertIn('CGNAT', mapping.open(8768)['message'])
        self.assertEqual(router.added, [])
        router.discover = lambda: 0
        self.assertFalse(mapping.open(8768)['ok'])

    def test_mapping_failure_preserves_router_public_address(self):
        router = Router()
        def denied(*args):
            raise OSError('Router denied forwarding')
        router.addportmapping = denied
        result = PortMapping(lambda: router).open(8768)
        self.assertFalse(result['ok'])
        self.assertEqual(result['address'], '8.8.4.4')

    def test_router_exception_does_not_break_local_hosting(self):
        def broken(): raise OSError('UPnP disabled')
        self.assertFalse(PortMapping(broken).open(8768)['ok'])


class Emulator:
    def __init__(self, args, **kwargs):
        self.args, self.kwargs = args, kwargs
        self.returncode = None
    def poll(self): return self.returncode
    def terminate(self): self.returncode = 0
    def kill(self): self.returncode = -1
    def wait(self, timeout=None): return self.returncode


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.package = game_package(self.root / 'package')
        self.events = []
        self.host = Controller(self.root / 'host', self.events.append, address_lookup=lambda: '8.8.4.4')
        self.guest = Controller(self.root / 'guest')
        for controller in (self.host, self.guest):
            controller.profiles.remember(package=str(self.package.directory), mgba=str(self.root / 'mgba.exe'))
        self.port = free_port()
        self.profile = await self.host.host('Test run', self.port, 12345, DEFAULT_RULES)

    async def asyncTearDown(self):
        await self.guest.stop(close_game=True)
        await self.host.stop(close_game=True)
        self.tmp.cleanup()

    async def join(self):
        invitation = await self.host.invite('127.0.0.1', self.port)
        return await self.guest.join(invitation)

    async def test_info_authentication_does_not_take_player_slots(self):
        await self.join()
        info = await self.guest.info()
        self.assertEqual(info['seed'], 12345)
        self.assertEqual(info['players'], [False, False])
        self.assertEqual(self.host.store.get(self.profile['room'])['seq'], [0, 0])
        with self.assertRaisesRegex(ValueError, 'invalid credential'):
            await session_info('127.0.0.1', self.port, self.profile['room'], 1, '0' * 32)
        self.assertEqual(self.host.relay.clients, {})
        diagnostic = json.dumps(self.events)
        self.assertNotIn(self.profile['token'], diagnostic)
        self.assertNotIn(self.profile['partner_token'], diagnostic)

    async def test_start_options_reach_guest(self):
        from soullink.relay.model import DEFAULT_START_OPTIONS, Rules
        rules = DEFAULT_RULES | DEFAULT_START_OPTIONS | Rules.NO_BATTLE_ITEMS | Rules.FORCE_SET | (19 << 18)
        await self.join()
        await self.host.configure(999, rules)
        self.assertEqual((await self.guest.info())['rules'], rules)

    async def test_host_settings_and_in_game_lock_share_state(self):
        await self.join()
        await self.host.configure(999, 1)
        self.assertEqual((await self.guest.info())['rules'], 1)
        for player in range(2):
            self.host.store.event(self.profile['room'], player, 1, 'confirm', ['1', '999'])
        with self.assertRaisesRegex(ProtocolError, 'locked'):
            await self.host.configure(1, 97)
        self.assertEqual((await self.guest.info())['seed'], 999)

    async def test_resume_preserves_identity_and_handles_occupied_port(self):
        room, token = self.profile['room'], self.profile['token']
        await self.host.stop()
        with socket.socket() as occupied:
            occupied.bind(('0.0.0.0', self.port))
            occupied.listen()
            with self.assertRaisesRegex(ValueError, 'Cannot listen'):
                await self.host.resume(self.profile['id'])
        await self.host.change_port(self.profile['id'], free_port())
        await self.host.resume(self.profile['id'])
        self.assertEqual(self.host.profile['room'], room)
        self.assertEqual(self.host.profile['token'], token)

    async def test_play_resume_and_restart_isolate_saves(self):
        await self.join()
        with patch('soullink.launcher.service.check_mgba', AsyncMock(return_value=self.root / 'mgba.exe')), \
             patch('soullink.launcher.service.subprocess.Popen', Emulator):
            await self.host.play()
            args = self.host.emulator.args
            self.assertEqual(args[1], '--script')
            self.assertTrue(Path(args[2]).exists())
            rom = Path(args[-1])
            self.assertIn(f'savegamePath={rom.parent}', args)
            self.assertIn('pauseOnFocusLost=0', args)
            self.assertNotEqual(self.host.emulator.kwargs['stdout'], subprocess.DEVNULL)
            self.assertTrue(list(rom.parent.glob('mgba-*.log')))
            save = rom.with_suffix('.sav')
            save.write_bytes(b'first attempt progress')
            await self.host.close_emulator()
            await self.host.play()
            self.assertEqual(Path(self.host.emulator.args[-1]), rom)
            with self.assertRaisesRegex(ValueError, 'already running'):
                await self.host.play()
            with self.assertRaisesRegex(ProtocolError, 'finished'):
                await self.host.restart(44)
            with self.host.store.db:
                state = self.host.store.get(self.profile['room'])
                state['ended'] = True
                self.host.store.save(self.profile['room'], state)
            await self.host.restart(44)
            self.assertEqual((await self.guest.info())['seed'], 44)
            await self.host.close_emulator()
            await self.host.play()
            next_rom = Path(self.host.emulator.args[-1])
            self.assertNotEqual(next_rom.parent, rom.parent)
            self.assertFalse(next_rom.with_suffix('.sav').exists())
            self.assertEqual(save.read_bytes(), b'first attempt progress')

    async def test_unexpected_emulator_exit_reports_code_and_keeps_host_running(self):
        original_run = (await self.host.info())['run']
        log = self.root / 'emulator.log'
        with log.open('wb') as output:
            process = subprocess.Popen([sys.executable, '-c',
                       "import sys; print('native failure diagnostic', flush=True); sys.exit(7)"],
                       stdout=output, stderr=subprocess.STDOUT)
        self.host.emulator = process
        try:
            await asyncio.wait_for(self.host.watch_emulator(process, log), 5)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
        diagnostic = next(e['message'] for e in self.events if e['kind'] == 'emulator_exit')
        self.assertIn('unexpectedly', diagnostic)
        self.assertIn('7', diagnostic)
        self.assertIn(str(log), diagnostic)
        self.assertIn('native failure diagnostic', log.read_text())
        self.assertIsNotNone(self.host.server)
        self.assertEqual((await self.host.info())['run'], original_run)

    async def test_keyboard_mode_filters_child_controllers_and_preserves_parent_environment(self):
        with patch.dict(os.environ, SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT='existing-filter'), \
             patch('soullink.launcher.service.check_mgba', AsyncMock(return_value=self.root / 'mgba.exe')), \
             patch('soullink.launcher.service.subprocess.Popen', Emulator):
            await self.host.play()
            self.assertEqual(self.host.emulator.kwargs['env']['SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT'],
                             '0xffff/0xffff')
            self.assertEqual(os.environ['SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT'], 'existing-filter')
            await self.host.close_emulator()
            self.host.profiles.remember(keyboard_only=False)
            await self.host.play()
            self.assertEqual(self.host.emulator.kwargs['env']['SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT'],
                             'existing-filter')

    async def test_setup_remembers_gamepad_opt_out(self):
        emulator = self.root / 'mgba.exe'
        with patch('soullink.launcher.service.check_mgba', AsyncMock(return_value=emulator)):
            await self.guest.setup(self.package.directory, emulator, keyboard_only=False)
        self.assertFalse(Profiles(self.root / 'guest').settings['keyboard_only'])

    async def test_stopping_session_cancels_monitor_and_leaves_game_running(self):
        process = Emulator(['mgba'])
        self.host.emulator = process
        monitor = asyncio.create_task(self.host.watch_emulator(process, self.root / 'mgba.log'))
        self.host.emulator_monitor = monitor
        await asyncio.sleep(0)
        await self.host.stop(close_game=False)
        self.assertTrue(monitor.cancelled())
        self.assertIsNone(self.host.emulator_monitor)
        self.assertIsNone(process.poll())
        self.assertFalse(any(e['kind'] == 'emulator_exit' for e in self.events))

    async def test_internet_host_falls_back_and_cleans_up_mapping(self):
        class Mapping:
            closed = False
            def open(self, port):
                return dict(ok=False, message='UPnP disabled')
            def close(self):
                self.closed = True
        await self.host.stop()
        mapping = Mapping()
        self.host.mapping_factory = lambda: mapping
        profile = self.host.profiles.list()[0]
        profile['internet'] = True
        self.host.profiles.save(profile)
        await self.host.resume(profile['id'])
        self.assertIsNotNone(self.host.server)
        self.assertEqual(self.host.profile['advertised'], '8.8.4.4')
        self.assertTrue(any(e['kind'] == 'network' and 'disabled' in e['message'] for e in self.events))
        await self.host.stop()
        self.assertTrue(mapping.closed)

    async def test_router_public_ip_is_used_even_when_mapping_already_exists(self):
        class Mapping:
            def open(self, port):
                return dict(ok=False, address='8.8.4.4', message='Port already mapped')
            def close(self): pass
        await self.host.stop()
        self.host.mapping_factory = Mapping
        self.host.address_lookup = lambda: self.fail('Router already supplied a public IP')
        profile = self.host.profiles.list()[0]
        profile['internet'] = True
        self.host.profiles.save(profile)
        await self.host.resume(profile['id'])
        invite = Invite.decode(await self.host.invite(self.host.profile['advertised'], self.port))
        self.assertEqual(invite.host, '8.8.4.4')

    async def test_lookup_failure_is_explained_and_retry_persists_address(self):
        class Mapping:
            def open(self, port): return dict(ok=False, message='No router found')
            def close(self): pass
        await self.host.stop()
        self.host.mapping_factory = Mapping
        self.host.address_lookup = lambda: None
        profile = self.host.profiles.list()[0]
        profile['internet'] = True
        self.host.profiles.save(profile)
        await self.host.resume(profile['id'])
        self.assertEqual(self.host.profile['advertised'], '')
        self.assertTrue(any('Public IP detection failed' in e.get('message', '') for e in self.events))
        self.host.address_lookup = lambda: '8.8.4.4'
        await self.host.refresh_address()
        self.assertEqual(self.host.profiles.list()[0]['advertised'], '8.8.4.4')

    async def test_manual_invite_address_survives_automatic_detection(self):
        class Mapping:
            def open(self, port): return dict(ok=False, message='No router found')
            def close(self): pass
        await self.host.invite('my.vpn.example', self.port)
        await self.host.stop()
        self.host.mapping_factory = Mapping
        self.host.address_lookup = lambda: self.fail('Manual addresses must not be overwritten')
        profile = self.host.profiles.list()[0]
        profile['internet'] = True
        self.host.profiles.save(profile)
        await self.host.resume(profile['id'])
        self.assertEqual(self.host.profile['advertised'], 'my.vpn.example')

    async def test_cancelled_upnp_start_cleans_up_late_mapping(self):
        started, release = threading.Event(), threading.Event()
        class Mapping:
            closed = False
            def open(self, port):
                started.set()
                release.wait(2)
                return dict(ok=True, address='8.8.4.4', message='mapped')
            def close(self):
                self.closed = True
        await self.host.stop()
        mapping = Mapping()
        self.host.mapping_factory = lambda: mapping
        profile = self.host.profiles.list()[0]
        profile['internet'] = True
        self.host.profiles.save(profile)
        starting = asyncio.create_task(self.host.resume(profile['id']))
        await asyncio.to_thread(started.wait, 2)
        starting.cancel()
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await starting
        self.assertTrue(mapping.closed)
        self.assertIsNone(self.host.server)

    async def test_join_rejects_different_build_before_connecting(self):
        invitation = Invite('127.0.0.1', self.port, self.profile['room'],
                            self.profile['partner_token'], 'f' * 64).encode()
        with self.assertRaisesRegex(ValueError, 'differs'):
            await self.guest.join(invitation)
        self.assertEqual(self.guest.profiles.list(), [])

    async def test_shutdown_closes_idle_and_authenticated_connections(self):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.port)
        writer.write(f'HELLO 1 1397489665 {self.profile["room"]} 0 {self.profile["token"]} {"ff"*8} 0\n'.encode())
        await writer.drain()
        self.assertTrue((await reader.readline()).startswith(b'STATE '))
        await self.host.stop()
        self.assertEqual(await asyncio.wait_for(reader.read(), 1), b'')
        writer.close()
        await writer.wait_closed()

    async def test_wrong_service_is_reported_without_html(self):
        async def http(reader, writer):
            writer.write(b'<!DOCTYPE HTML>\n')
            await writer.drain()
            writer.close()
        server = await asyncio.start_server(http, '127.0.0.1', 0)
        try:
            with self.assertRaisesRegex(ValueError, 'not a compatible'):
                await session_info('127.0.0.1', server.sockets[0].getsockname()[1], 'room', 1, 'a' * 32)
        finally:
            server.close()
            await server.wait_closed()


class CompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_mgba_without_script_support_is_rejected(self):
        class HelpProcess:
            async def communicate(self): return b'mGBA 0.10.5 Usage: mgba [ROM]', None
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'mgba.exe'
            exe.touch()
            with patch('asyncio.create_subprocess_exec', AsyncMock(return_value=HelpProcess())):
                with self.assertRaisesRegex(ValueError, '0.10.5'):
                    await check_mgba(exe)
