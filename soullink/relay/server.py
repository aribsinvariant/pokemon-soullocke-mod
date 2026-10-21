"""Bounded newline protocol; run with python -m soullink.relay.server."""
import argparse
import asyncio
import json
import struct
import time
from pathlib import Path
from .model import Store, ProtocolError, integer, name_bytes, PROTOCOL, BUILD, AREAS


class Relay:
    def __init__(self, store):
        self.store = store
        self.clients = {}
        self.positions = {}

    async def send(self, writer, line):
        writer.write((line + '\n').encode('ascii'))
        await asyncio.wait_for(writer.drain(), 3)

    def snapshot(self, room, p):
        s = self.store.get(room)
        records = bytearray()
        for area in range(AREAS):
            mon = s['mons'][1-p].get(str(area)) or s['reservations'][1-p].get(str(area), {})
            active = (area in s['party'][p]) | ((area in (s['proposed'][1-p] or [])) << 1) | ((str(area) in s['reservations'][p]) << 2)
            records.extend(struct.pack('<12sHBBBB', bytes.fromhex(mon.get('name', 'ff'*11)),
                                       mon.get('species', 0), mon.get('type', 0), mon.get('gender', 255),
                                       Store.status(s, area), active))
        online = all((room, player) in self.clients and time.monotonic()-self.clients[room, player][1] < 3
                     for player in range(2))
        fields = [s['run'], s['version'], s['seq'][p], s['rules'], s['seed'],
                  int(s['locked']), int(s['ended']), int(online), int(s['confirmed'][p])]
        return 'STATE ' + ' '.join(map(str, fields)) + ' ' + s['trainers'][1-p] + ' ' + records.hex()

    async def handle(self, reader, writer):
        identity = None
        try:
            hello = (await asyncio.wait_for(reader.readline(), 10)).decode('ascii').strip().split()
            if len(hello) != 8 or hello[0] != 'HELLO':
                raise ProtocolError('expected HELLO version build room player token trainer')
            _, version, build, room, player, token, trainer, run = hello
            if integer(version) != PROTOCOL or integer(build) != BUILD:
                raise ProtocolError('incompatible ROM or protocol')
            p = integer(player, 0, 1)
            s = self.store.authenticate(room, p, token)
            if integer(run) not in (0, s['run']):
                raise ProtocolError('save belongs to a different run')
            session_run = s['run']
            identity = (room, p)
            if identity in self.clients:
                raise ProtocolError('player already connected')
            trainer = name_bytes(trainer, 8)
            with self.store.db:
                self.store.db.execute('BEGIN IMMEDIATE')
                s = self.store.get(room)
                if s['run'] != session_run:
                    raise ProtocolError('run restarted; reset mGBA and select New Game')
                s['trainers'][p] = trainer
                self.store.save(room, s)
            self.clients[identity] = (writer, time.monotonic())
            await self.send(writer, self.snapshot(room, p))
            while True:
                raw = await asyncio.wait_for(reader.readline(), 5)
                if not raw:
                    break
                fields = raw.decode('ascii').strip().split()
                if not fields or len(fields) > 20:
                    raise ProtocolError('invalid message')
                if self.store.get(room)['run'] != session_run:
                    raise ProtocolError('run restarted; reset mGBA and select New Game')
                self.clients[identity] = (writer, time.monotonic())
                if fields[0] == 'EVENT' and len(fields) >= 3:
                    state = self.store.event(room, p, fields[1], fields[2], fields[3:], expected_run=session_run)
                    await self.send(writer, 'NOTICE ' + str(state['notice'][p]))
                    await self.send(writer, self.snapshot(room, p))
                elif fields[0] == 'POLL' and len(fields) == 1:
                    await self.send(writer, self.snapshot(room, p))
                elif fields[0] == 'POS' and len(fields) == 8:
                    position = [integer(x, 0, 65535) for x in fields[1:]]
                    self.positions[identity] = position
                    partner = self.clients.get((room, 1-p))
                    if partner:
                        await self.send(partner[0], 'POS ' + ' '.join(map(str, position)))
                else:
                    raise ProtocolError('unknown message')
        except (ProtocolError, ValueError, UnicodeError) as exc:
            try:
                await self.send(writer, 'ERROR ' + str(exc))
            except (ConnectionError, asyncio.TimeoutError):
                pass
        except (ConnectionError, asyncio.TimeoutError):
            pass
        finally:
            if identity and self.clients.get(identity, (None,))[0] is writer:
                self.clients.pop(identity, None)
                self.positions.pop(identity, None)
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass


async def serve(store, host, port):
    relay = Relay(store)
    server = await asyncio.start_server(relay.handle, host, port, limit=4096)
    print(f'Soul Link relay listening on {host}:{port}', flush=True)
    async with server:
        await server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='soullink.sqlite3')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--create', metavar='ROOM')
    action.add_argument('--restart', metavar='ROOM', help='reset a finished run and exit; reuse credentials')
    parser.add_argument('--seed', type=int, help='seed for a new room or restarted attempt')
    parser.add_argument('--output', default='players')
    args = parser.parse_args()
    store = Store(args.db)
    if args.restart:
        try:
            state = store.restart(args.restart, args.seed)
        except ProtocolError as exc:
            parser.error(str(exc))
        finally:
            store.db.close()
        print(f'Restarted {args.restart} (seed {state["seed"]}). Keep the relay running. '
              'Both players: reset mGBA, select New Game, and confirm settings. '
              'Reuse the same player scripts.')
        return
    if args.create:
        state = store.create(args.create, 1 if args.seed is None else args.seed)
        directory = Path(args.output)
        directory.mkdir(parents=True, exist_ok=True)
        for p in range(2):
            config = (f'return {{host="127.0.0.1", port={args.port}, room="{args.create}", '
                      f'player={p}, token="{state["tokens"][p]}"}}\n')
            path = directory / f'player{p+1}.lua'
            path.write_text(config)
            path.chmod(0o600)
        print(f'Created room {args.create}. Private player configs: {directory}')
    asyncio.run(serve(store, args.host, args.port))


if __name__ == '__main__':
    main()
