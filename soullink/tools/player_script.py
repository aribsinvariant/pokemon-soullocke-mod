"""Generate a self-contained mGBA script tied to an ELF and private player config."""
import argparse
import json
import re
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('elf', type=Path)
    parser.add_argument('config', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--nm', default='arm-none-eabi-nm')
    parser.add_argument('--local-port', type=int, default=8766)
    args = parser.parse_args()
    if args.elf.suffix == '.json':
        manifest = json.loads(args.elf.read_text())
        if manifest['protocol'] != 1 or manifest['build'] != '534c0001':
            raise SystemExit('Unsupported build manifest')
        address = int(manifest['mailbox'], 16)
    else:
        symbols = subprocess.check_output([args.nm, '-g', str(args.elf)], text=True)
        match = re.search(r'^([0-9a-fA-F]+)\s+\w\s+gSoulLinkMailbox$', symbols, re.M)
        if not match:
            raise SystemExit('ELF has no Soul Link mailbox')
        address = int(match[1], 16)
    if not 0x02000000 <= address < 0x02040000:
        raise SystemExit('Mailbox outside EWRAM')
    config = args.config.read_text().strip()
    if not config.startswith('return '):
        raise SystemExit('Expected generated player config')
    template = Path(__file__).parents[1] / 'bridge' / 'bridge.lua'
    args.output.write_text(f'SOUL_ADDRESS = 0x{address:08x}\nSOUL_CONFIG = {config[7:]}\n'
                           f'SOUL_CONFIG.local_port = {args.local_port}\n' + template.read_text())
    args.output.chmod(0o600)
    print(f'Wrote {args.output} for mailbox 0x{address:08x}')


if __name__ == '__main__':
    main()
