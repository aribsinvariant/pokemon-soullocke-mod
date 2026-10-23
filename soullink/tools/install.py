"""Install a locally built game and Windows launcher without touching saved sessions."""
import argparse
import asyncio
import os
from pathlib import Path
import shutil
import subprocess
import uuid
import warnings

from soullink.launcher.service import check_mgba
from soullink.launcher.storage import GamePackage, Profiles, app_directory


def shortcut(executable, root):
    # Pass paths as environment data, never as PowerShell source code.
    environment = dict(os.environ, SOULLINK_INSTALLED_EXE=str(executable),
                       SOULLINK_LAUNCH_ARGUMENTS=subprocess.list2cmdline(['--data-root', str(root)]))
    subprocess.run(['powershell.exe', '-NoProfile', '-Command',
        "$ErrorActionPreference = 'Stop'; $shell = New-Object -ComObject WScript.Shell; "
        "$link = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Emerald Soul Link.lnk')); "
        "$link.TargetPath = $env:SOULLINK_INSTALLED_EXE; "
        "$link.Arguments = $env:SOULLINK_LAUNCH_ARGUMENTS; "
        "$link.WorkingDirectory = Split-Path $env:SOULLINK_INSTALLED_EXE; "
        "$link.Save()"], env=environment, check=True)


async def install(package, launcher, emulator_directory, root=None, create_shortcut=True):
    package = GamePackage.load(package)
    launcher, emulator_directory = Path(launcher), Path(emulator_directory)
    if not (launcher / 'SoulLink.exe').is_file():
        raise ValueError('Build SoulLink.exe before installing.')
    candidates = list(emulator_directory.rglob('mGBA.exe'))
    if len(candidates) != 1:
        raise ValueError('The emulator download must contain exactly one mGBA.exe.')
    await check_mgba(candidates[0])
    root = Path(root) if root else app_directory()
    root = root.resolve()
    destination = root / 'installations' / uuid.uuid4().hex
    destination.mkdir(parents=True)
    try:
        game = destination / 'game'
        game.mkdir()
        shutil.copy2(package.rom, game / package.rom.name)
        shutil.copy2(package.directory / 'manifest.json', game / 'manifest.json')
        shutil.copy2(launcher / 'SoulLink.exe', destination / 'SoulLink.exe')
        shutil.copytree(launcher / 'licenses', destination / 'licenses')
        shutil.copytree(emulator_directory, destination / 'emulator')
        emulator = destination / 'emulator' / candidates[0].relative_to(emulator_directory)
        # Validate the final installed files before switching the saved configuration.
        GamePackage.load(game)
        await check_mgba(emulator)
        executable = destination / 'SoulLink.exe'
        profiles = Profiles(root)
        profiles.remember(package=str(game), mgba=str(emulator),
                          keyboard_only=profiles.settings.get('keyboard_only', True))
    except BaseException:
        shutil.rmtree(destination)
        raise
    if create_shortcut:
        try:
            shortcut(executable, root)
        except (OSError, subprocess.SubprocessError) as exc:
            warnings.warn(f'Installed successfully, but could not create the desktop shortcut: {exc}')
    return executable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--launcher', type=Path, required=True)
    parser.add_argument('--emulator-directory', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=app_directory())
    parser.add_argument('--no-shortcut', action='store_true')
    parser.add_argument('--no-launch', action='store_true')
    args = parser.parse_args()
    executable = asyncio.run(install(args.package, args.launcher, args.emulator_directory,
                                    args.root, not args.no_shortcut))
    print(f'Installed {executable}')
    if not args.no_launch:
        subprocess.Popen([str(executable), '--data-root', str(args.root.resolve())], cwd=executable.parent)


if __name__ == '__main__':
    main()
