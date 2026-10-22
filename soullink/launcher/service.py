"""Async session controller. No GUI imports or global event-loop side effects."""
import asyncio
import contextlib
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
from soullink.bridge.client import run as connect
from soullink.relay.model import Store, PROTOCOL, BUILD, integer
from soullink.relay.server import start_relay
from soullink.tools.player_script import generate_script
from .storage import GamePackage, Invite, Profiles, validate_host
from .network import PortMapping, lan_address


async def session_info(host, port, room, player, token):
    """Read one bounded, authenticated response; never occupy a gameplay slot."""
    writer = None
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port, limit=4096), 5)
        writer.write(f'INFO {PROTOCOL} {BUILD} {room} {player} {token}\n'.encode('ascii'))
        await asyncio.wait_for(writer.drain(), 3)
        raw = await asyncio.wait_for(reader.readline(), 5)
        if raw.startswith(b'ERROR '):
            raise ValueError(raw[6:].decode('ascii', errors='replace').strip())
        if not raw.startswith(b'SESSION '):
            raise ValueError('This address is not a compatible Soul Link relay. Check the IP and port.')
        data = json.loads(raw[8:])
        if data.get('protocol') != PROTOCOL or data.get('build') != BUILD:
            raise ValueError('The relay uses an incompatible game protocol.')
        integer(data['run'], 1)
        integer(data['seed'])
        integer(data['rules'], 0, 4095)
        return data
    except (OSError, asyncio.TimeoutError) as exc:
        raise ValueError('Cannot reach the relay. Check the address, port, firewall, and router forwarding.') from exc
    finally:
        if writer:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()


async def check_mgba(path):
    executable = Path(path).resolve()
    if not executable.is_file():
        raise ValueError('Select your mGBA executable.')
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    process = await asyncio.create_subprocess_exec(str(executable), '--help',
              stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, creationflags=flags)
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 10)
    except BaseException:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()
        raise
    if b'--script' not in output:
        raise ValueError('This mGBA build cannot load scripts automatically. Select a newer desktop '
                         'build whose --help includes --script. mGBA 0.10.5 does not support it.')
    return executable


class Controller:
    def __init__(self, root=None, emit=None, mapping_factory=PortMapping):
        self.profiles = Profiles(root)
        self.emit_callback = emit or (lambda event: None)
        self.mapping_factory = mapping_factory
        self.profile = self.store = self.relay = self.server = None
        self.poller = self.connector = self.renewal = None
        self.mapping = None
        self.emulator = None
        self.last_info = None
        self.active_run = None
        self._last_status = None
        self._lan = None

    def emit(self, kind, message='', **details):
        # Never expose profile credentials or whole invites in diagnostics.
        if self.profile:
            for key in ('token', 'partner_token'):
                value = self.profile.get(key)
                if value:
                    message = message.replace(value, '[private]')
        message = re.sub(r'\b[0-9a-fA-F]{32,64}\b', '[private]', message)
        self.emit_callback(dict(kind=kind, message=message, **details))

    def bridge_status(self, event):
        status = event['kind'], event['message']
        if status != self._last_status:
            self._last_status = status
            self.emit('connection', event['message'], state=event['kind'])

    async def setup(self, package_directory, emulator):
        package = await asyncio.to_thread(GamePackage.load, package_directory)
        path = await check_mgba(emulator)
        self.profiles.remember(package=str(package.directory), mgba=str(path))
        self.emit('setup', 'Game package and mGBA verified')
        return package

    async def package(self):
        return await asyncio.to_thread(GamePackage.load, self.profiles.settings.get('package', ''))

    async def host(self, name, port, seed, rules, internet=False):
        if self.profile:
            raise ValueError('Stop the current session before creating another.')
        name = name.strip()
        if not 1 <= len(name) <= 64:
            raise ValueError('Enter a session name (1–64 characters).')
        port, seed, rules = integer(port, 1, 65535), integer(seed), integer(rules, 0, 4095)
        package = await self.package()
        identifier = secrets.token_hex(16)
        directory = self.profiles.root / 'sessions' / identifier
        directory.mkdir(parents=True)
        store = Store(directory / 'relay.sqlite3')
        try:
            state = store.create('room' + secrets.token_hex(8), seed, rules, package.sha256)
            # Room id is from the one new database; no private configs are exported.
            room = store.db.execute('SELECT id FROM rooms').fetchone()[0]
            profile = dict(id=identifier, name=name, role='host', room=room, port=port,
                           host='127.0.0.1', advertised='', internet=bool(internet),
                           token=state['tokens'][0], partner_token=state['tokens'][1], sha256=package.sha256)
        finally:
            store.db.close()
        self.profiles.save(profile)
        try:
            await self.resume(profile['id'])
        except BaseException:
            # Keep this created profile available for another port attempt.
            raise
        return profile

    async def join(self, invitation):
        if self.profile:
            raise ValueError('Stop the current session before joining another.')
        invite = Invite.decode(invitation)
        package = await self.package()
        if invite.sha256 != package.sha256:
            raise ValueError('Your game build differs from the host. Select the same built package.')
        info = await session_info(invite.host, invite.port, invite.room, 1, invite.token)
        if info.get('rom_sha256') != invite.sha256:
            raise ValueError('The relay game build differs from this invite.')
        matches = [p for p in self.profiles.list() if p.get('role') == 'join' and
                   p.get('room') == invite.room and p.get('token') == invite.token]
        values = dict(name=f'Joined {invite.host}', role='join', room=invite.room, host=invite.host,
                      port=invite.port, token=invite.token, sha256=invite.sha256)
        profile = self.profiles.save(dict(matches[0], **values)) if matches else self.profiles.create(**values)
        await self.resume(profile['id'])
        return profile

    async def resume(self, identifier):
        if self.emulator_running():
            raise ValueError('Close your running game before switching sessions.')
        await self.stop()
        profiles = [p for p in self.profiles.list() if p['id'] == identifier]
        if not profiles:
            raise ValueError('Saved session not found')
        profile = profiles[0]
        package = await self.package()
        if profile['sha256'] != package.sha256:
            raise ValueError('Select the game package originally used for this saved session.')
        self.profile = profile
        try:
            if profile['role'] == 'host':
                self.store = Store(self.profiles.directory(profile) / 'relay.sqlite3')
                self.relay, self.server = await start_relay(self.store, '0.0.0.0', profile['port'])
                self._lan = await asyncio.to_thread(lan_address)
                profile['lan'] = self._lan
                if not profile.get('manual_address') and not profile.get('internet'):
                    profile['advertised'] = self._lan
                    self.profiles.save(profile)
            self.last_info = await self.info()
            if self.last_info.get('rom_sha256') != package.sha256:
                raise ValueError('This session was not created for the selected game package.')
            self.emit('session', 'Session ready', profile=self.public_profile(), info=self.last_info)
            self.poller = asyncio.create_task(self.poll())
            if profile.get('internet'):
                self.mapping = self.mapping_factory()
                opening = asyncio.create_task(asyncio.to_thread(self.mapping.open, profile['port']))
                try:
                    result = await asyncio.shield(opening)
                except asyncio.CancelledError:
                    await opening  # A late mapping must be owned and cleaned up by stop().
                    raise
                if result.get('ok'):
                    if not profile.get('manual_address'):
                        profile['advertised'] = result['address']
                        self.profiles.save(profile)
                    self.renewal = asyncio.create_task(self.renew_mapping())
                self.emit('network', result['message'], result=result, lan=self._lan, port=profile['port'])
                self.emit('session', '', profile=self.public_profile(), info=self.last_info)
        except BaseException as exc:
            await self.stop()
            self.emit('stopped', 'Session could not start. It remains available in Saved sessions.')
            if isinstance(exc, OSError):
                raise ValueError(f'Cannot listen on port {profile["port"]}. '
                                 'Another app may be using it. Change the saved host port and resume.') from exc
            raise

    def public_profile(self):
        return {key: value for key, value in self.profile.items() if key not in ('token', 'partner_token')}

    async def info(self):
        p = self.profile
        if self.relay:
            return self.relay.session(p['room'], 0)
        return await session_info(p['host'], p['port'], p['room'], 1, p['token'])

    async def poll(self):
        while True:
            await asyncio.sleep(2)
            try:
                info = await self.info()
                if self.last_info and self.last_info['run'] != info['run']:
                    await self.disconnect()
                    self.emit('new_run', 'The host restarted the run. Close the previous game, then click Play New Run.')
                if info != self.last_info:
                    self.last_info = info
                    self.emit('info', '', info=info)
            except (ValueError, OSError) as exc:
                self.emit('connection', str(exc), state='disconnected')

    async def renew_mapping(self):
        while True:
            await asyncio.sleep(1800)
            try:
                renewal = asyncio.create_task(asyncio.to_thread(self.mapping.renew))
                try:
                    renewed = await asyncio.shield(renewal)
                except asyncio.CancelledError:
                    await renewal
                    raise
                if not renewed:
                    self.emit('network', 'UPnP mapping expired or changed. Check manual forwarding.')
            except Exception:
                self.emit('network', 'UPnP renewal failed. Check router forwarding.')

    async def configure(self, seed, rules):
        if not self.store:
            raise ValueError('Only the host can change settings.')
        self.last_info = None  # Ensure both confirmations are refreshed in the GUI.
        self.store.configure(self.profile['room'], seed, rules)
        self.last_info = await self.info()
        self.emit('info', 'Settings applied; both players must confirm in-game.', info=self.last_info)

    async def change_port(self, identifier, port):
        if self.profile:
            raise ValueError('Stop the current session before changing a listening port.')
        profiles = [p for p in self.profiles.list() if p['id'] == identifier and p['role'] == 'host']
        if not profiles:
            raise ValueError('Select a saved host session.')
        profile = profiles[0]
        previous = profile['port']
        profile['port'] = integer(port, 1, 65535)
        if profile.get('invite_port') == previous:
            profile['invite_port'] = profile['port']
        self.profiles.save(profile)
        self.emit('changed', 'Port updated. Resume the session and share an updated invite.')

    async def invite(self, address, port):
        if not self.profile or self.profile['role'] != 'host':
            raise ValueError('Host a session to create an invite.')
        address = validate_host(address)
        port = integer(port, 1, 65535)
        if address != self.profile.get('advertised'):
            self.profile['manual_address'] = True
        self.profile['advertised'], self.profile['invite_port'] = address, port
        self.profiles.save(self.profile)
        p = self.profile
        return Invite(address, port, p['room'], p['partner_token'], p['sha256']).encode()

    def emulator_running(self):
        return self.emulator is not None and self.emulator.poll() is None

    async def play(self):
        if not self.profile:
            raise ValueError('Host or join a session first.')
        if self.emulator_running():
            raise ValueError('Your game is already running. Close it before launching again.')
        package = await self.package()
        mgba = await check_mgba(self.profiles.settings.get('mgba', ''))
        info = await self.info()
        if info.get('rom_sha256') != package.sha256:
            raise ValueError('Your game package does not match the session.')
        if info['ended']:
            raise ValueError('This run ended. The host can choose Restart Run.')
        await self.disconnect()
        p = self.profile
        directory = self.profiles.directory(p) / 'attempts' / str(info['run'])
        directory.mkdir(parents=True, exist_ok=True)
        rom = directory / 'emerald-soullink.gba'
        if not rom.exists():
            await asyncio.to_thread(shutil.copy2, package.rom, rom)
        elif await asyncio.to_thread(lambda: hashlib.sha256(rom.read_bytes()).hexdigest()) != package.sha256:
            raise ValueError('The saved attempt game copy has changed. Restore the matching ROM.')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            local_port = sock.getsockname()[1]
        script = generate_script(package.mailbox, p['room'], 0 if p['role'] == 'host' else 1,
                                 p['token'], directory / 'player.lua', local_port)
        self.emulator = subprocess.Popen([str(mgba), '--script', str(script),
                              '-C', f'savegamePath={directory}', '-C', f'savestatePath={directory}', str(rom)],
                              cwd=str(directory), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.active_run = info['run']
        self.connector = asyncio.create_task(connect(p['host'], p['port'], local_port, self.bridge_status))
        self.emit('launched', 'mGBA launched. Start New Game or Continue; confirm the rules with SELECT.')

    async def restart(self, seed):
        if not self.store:
            raise ValueError('Only the host can restart a run.')
        state = self.store.restart(self.profile['room'], seed)
        await self.disconnect()
        self.last_info = await self.info()
        self.emit('new_run', 'New run ready. Close the previous game and click Play New Run.')
        self.emit('info', '', info=self.last_info)
        return state['run']

    async def disconnect(self):
        if self.connector:
            self.connector.cancel()
            await asyncio.gather(self.connector, return_exceptions=True)
            self.connector = None
        self._last_status = None

    async def close_emulator(self):
        if self.emulator_running():
            self.emulator.terminate()
            try:
                await asyncio.to_thread(self.emulator.wait, timeout=5)
            except subprocess.TimeoutExpired:
                self.emulator.kill()
                await asyncio.to_thread(self.emulator.wait)

    async def stop(self, close_game=False):
        for name in ('poller', 'renewal'):
            task = getattr(self, name)
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                setattr(self, name, None)
        await self.disconnect()
        if close_game:
            await self.close_emulator()
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        if self.relay:
            await self.relay.close()
            self.relay = None
        if self.mapping:
            try:
                await asyncio.to_thread(self.mapping.close)
            except Exception:
                self.emit('network', 'Could not remove the UPnP mapping. Remove it in your router settings.')
            self.mapping = None
        if self.store:
            self.store.db.close()
            self.store = None
        self.profile = self.last_info = None
        self.emit('stopped', 'Session stopped. Saved sessions are available to resume.')
