"""Nonblocking network connector. mGBA only accepts a local socket; it never dials the internet."""
import argparse
import asyncio


async def copy(reader, writer):
    while data := await reader.read(32768):
        writer.write(data)
        await asyncio.wait_for(writer.drain(), 5)


class WrongRelayError(Exception):
    pass


def notify(callback, kind, message, **details):
    if callback:
        callback(dict(kind=kind, message=message, **details))
    else:
        print(message, flush=True)


async def copy_relay(reader, writer, on_status=None):
    first = True
    while True:
        try:
            line = await reader.readline()
        except ValueError as exc:
            raise WrongRelayError('Server response exceeds the Soul Link message limit') from exc
        if not line:
            return
        if first and not line.startswith((b'STATE ', b'ERROR ')):
            raise WrongRelayError('The selected server is not a Soul Link relay. '
                                  'Check the address and port; another service may be using that port.')
        first = False
        writer.write(line)
        await asyncio.wait_for(writer.drain(), 5)
        if line.startswith(b'STATE ') and on_status:
            fields = line.split(b' ', 10)
            if len(fields) >= 10:
                try:
                    online = int(fields[8]) == 1
                    notify(on_status, 'connected' if online else 'waiting_partner',
                           'Connected to both players' if online else 'Connected; waiting for your partner')
                except ValueError:
                    pass  # The ROM bridge validates the complete snapshot.
        elif line.startswith(b'ERROR '):
            notify(on_status, 'error', line[6:].decode('ascii', errors='replace').strip()[:240])
            return False


async def run(host, port, local_port, on_status=None):
    while True:
        writers = []
        tasks = []
        try:
            notify(on_status, 'connecting', f'Connecting to relay {host}:{port}')
            remote_reader, remote_writer = await asyncio.wait_for(asyncio.open_connection(host, port), 5)
            writers.append(remote_writer)
            notify(on_status, 'waiting_emulator', 'Waiting for the game and its Soul Link script')
            local_reader, local_writer = await asyncio.wait_for(asyncio.open_connection('127.0.0.1', local_port), 2)
            writers.append(local_writer)
            tasks = [asyncio.create_task(copy(local_reader, remote_writer)),
                     asyncio.create_task(copy_relay(remote_reader, local_writer, on_status))]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task.result() is False:
                    return
            notify(on_status, 'disconnected', 'Connection closed; retrying')
        except WrongRelayError as exc:
            notify(on_status, 'error', f'Connection error at {host}:{port}: {exc}')
            return
        except (OSError, asyncio.TimeoutError) as exc:
            stage = 'waiting_emulator' if len(writers) else 'connecting'
            message = ('Waiting for mGBA. The script starts after New Game or Continue.'
                       if stage == 'waiting_emulator' else
                       f'Cannot reach {host}:{port}. Check the address, relay, and firewall.')
            notify(on_status, stage, message)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for writer in writers:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass
        await asyncio.sleep(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--local-port', type=int, default=8766)
    args = parser.parse_args()
    try:
        asyncio.run(run(args.server, args.port, args.local_port))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
