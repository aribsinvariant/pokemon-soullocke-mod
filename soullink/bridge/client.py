"""Nonblocking network connector. mGBA only accepts a local socket; it never dials the internet."""
import argparse
import asyncio


async def copy(reader, writer):
    while data := await reader.read(32768):
        writer.write(data)
        await asyncio.wait_for(writer.drain(), 5)


class WrongRelayError(Exception):
    pass


async def copy_relay(reader, writer):
    # Do not forward an HTTP page (or another service's greeting) into mGBA.
    try:
        first = await reader.readline()
    except ValueError as exc:
        raise WrongRelayError('Server response exceeds the Soul Link message limit') from exc
    if not first:
        return
    if not first.startswith((b'STATE ', b'ERROR ')):
        raise WrongRelayError('The selected server is not a Soul Link relay. '
                              'Check --server and --port; another service may be using that port.')
    writer.write(first)
    await asyncio.wait_for(writer.drain(), 5)
    await copy(reader, writer)


async def run(host, port, local_port):
    while True:
        writers = []
        tasks = []
        try:
            remote_reader, remote_writer = await asyncio.wait_for(asyncio.open_connection(host, port), 5)
            writers.append(remote_writer)
            local_reader, local_writer = await asyncio.wait_for(asyncio.open_connection('127.0.0.1', local_port), 2)
            writers.append(local_writer)
            print(f'Connected to emulator and server {host}:{port}; waiting for Soul Link handshake', flush=True)
            tasks = [asyncio.create_task(copy(local_reader, remote_writer)),
                     asyncio.create_task(copy_relay(remote_reader, local_writer))]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except WrongRelayError as exc:
            print(f'Connection error at {host}:{port}: {exc}', flush=True)
            return
        except (OSError, asyncio.TimeoutError) as exc:
            print(f'Waiting for emulator / relay: {exc}', flush=True)
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
