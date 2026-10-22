"""Build and smoke-test a Windows executable, then create a ROM-free player ZIP."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('release/launcher'))
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Build the Windows launcher on Windows using 64-bit Python 3.12 or 3.13.')
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                    '--distpath', str(output), '--workpath', str(output / 'build'),
                    str(root / 'soullink/launcher/launcher.spec')], cwd=root, check=True)
    report = output / 'smoke-test.json'
    if report.exists():
        report.unlink()
    subprocess.run([str(output / 'SoulLink.exe'), '--smoke-test', str(report)], check=True, timeout=60)
    if not json.loads(report.read_text())['ok']:
        raise SystemExit('Packaged GUI smoke test failed; inspect ' + str(report))
    licenses = output / 'licenses'
    licenses.mkdir(exist_ok=True)
    shutil.copy2(root / 'soullink/launcher/licenses/miniupnpc.txt', licenses / 'miniupnpc.txt')
    base = Path(sys.base_prefix)
    shutil.copy2(base / 'LICENSE.txt', licenses / 'Python.txt')
    for name in ('tcl', 'tk'):
        candidates = list((base / 'tcl').glob(name + '*/license*'))
        if not candidates:
            fallback = root / 'soullink/launcher/licenses' / (name + '.txt')
            if not fallback.exists():
                raise SystemExit(f'Cannot find the {name} license in the Python installation.')
            candidates = [fallback]
        shutil.copy2(candidates[0], licenses / (name + '.txt'))
    archive = output / 'SoulLink-Windows-x64.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(output / 'SoulLink.exe', 'SoulLink.exe')
        bundle.write(root / 'docs/soullink/LAUNCHER.md', 'README.md')
        for path in licenses.iterdir():
            bundle.write(path, 'licenses/' + path.name)
    print(f'Built {archive}; ROM and mGBA are not included.')


if __name__ == '__main__':
    main()
