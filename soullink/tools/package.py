"""Package a local build; optionally produce a BPS patch against a user-supplied base."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import re
import zlib

BASE_SHA1 = 'f3ae088181bf583e55daf962a92bb46f4f1d07b7'


def number(value):
    result = bytearray()
    while True:
        byte = value & 127
        value >>= 7
        if value == 0:
            result.append(byte | 128)
            return result
        result.append(byte)
        value -= 1


def bps(source, target):
    patch = bytearray(b'BPS1') + number(len(source)) + number(len(target)) + number(0)
    offset = 0
    while offset < len(target):
        same = offset < len(source) and source[offset] == target[offset]
        end = offset + 1
        while end < len(target) and (end < len(source) and source[end] == target[end]) == same:
            end += 1
        patch += number(((end-offset-1) << 2) | (0 if same else 1))
        if not same:
            patch += target[offset:end]
        offset = end
    patch += struct.pack('<II', zlib.crc32(source), zlib.crc32(target))
    patch += struct.pack('<I', zlib.crc32(patch))
    return patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, default=Path('pokeemerald_modern.gba'))
    parser.add_argument('--elf', type=Path, default=Path('pokeemerald_modern.elf'))
    parser.add_argument('--base', type=Path)
    parser.add_argument('--nm', default='arm-none-eabi-nm')
    parser.add_argument('--output', type=Path, default=Path('dist'))
    args = parser.parse_args()
    target = args.rom.read_bytes()
    args.output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.rom, args.output/'emerald-soullink.gba')
    shutil.copy2(args.elf, args.output/'emerald-soullink.elf')
    root = Path(__file__).parents[2]
    for part in ['relay', 'bridge', 'tools', 'launcher']:
        shutil.copytree(root/'soullink'/part, args.output/'soullink'/part, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(root/'soullink/__init__.py', args.output/'soullink/__init__.py')
    shutil.copy2(root/'docs/soullink/PLAYING.md', args.output/'README.md')
    shutil.copy2(root/'docs/soullink/LAUNCHER.md', args.output/'LAUNCHER.md')
    shutil.copy2(root/'soullink/UPSTREAM_COMMIT', args.output/'soullink/UPSTREAM_COMMIT')
    symbols = subprocess.check_output([args.nm, '-g', str(args.elf)], text=True)
    match = re.search(r'^([0-9a-fA-F]+)\s+\w\s+gSoulLinkMailbox$', symbols, re.M)
    if not match: raise SystemExit('ELF has no Soul Link mailbox')
    manifest = dict(protocol=1, build='534c0001', mailbox=match[1],
                    upstream=(root/'soullink/UPSTREAM_COMMIT').read_text().strip(),
                    sha256=hashlib.sha256(target).hexdigest(),
                    base_sha1=BASE_SHA1, save_compatibility='fresh Soul Link saves only')
    if args.base:
        source = args.base.read_bytes()
        if hashlib.sha1(source).hexdigest() != BASE_SHA1:
            raise SystemExit('Base must be an unmodified English Emerald ROM matching '+BASE_SHA1)
        (args.output/'emerald-soullink.bps').write_bytes(bps(source,target))
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'Local build packaged in {args.output}. BPS patch: {bool(args.base)}')


if __name__ == '__main__':
    main()
