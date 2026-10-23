"""Verify installation commits only a complete, compatible game and emulator."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from soullink.launcher.storage import Profiles, GamePackage
from soullink.tests.test_launcher import game_package
from soullink.tools.install import install


class InstallTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.package = game_package(self.base / 'package')
        self.launcher = self.base / 'launcher'
        (self.launcher / 'licenses').mkdir(parents=True)
        (self.launcher / 'SoulLink.exe').write_bytes(b'launcher')
        (self.launcher / 'licenses' / 'Python.txt').write_text('license')
        self.emulator = self.base / 'emulator'
        (self.emulator / 'nested').mkdir(parents=True)
        (self.emulator / 'nested' / 'mGBA.exe').write_bytes(b'emulator')
        (self.emulator / 'nested' / 'Qt.dll').write_bytes(b'dependency')
        self.root = self.base / 'installed app'
        profiles = Profiles(self.root)
        profiles.remember(package='old-package', mgba='old-emulator', custom='keep')
        self.profile = profiles.create(name='Existing run', token='private')
        self.save = profiles.directory(self.profile) / 'game.sav'
        self.save.write_bytes(b'precious save')
        self.settings = (self.root / 'settings.json').read_bytes()

    async def run_install(self):
        return await install(self.package.directory, self.launcher, self.emulator,
                             self.root, create_shortcut=False)

    @patch('soullink.tools.install.check_mgba', new_callable=AsyncMock)
    async def test_installs_complete_package_and_preserves_sessions_on_rerun(self, check):
        first = await self.run_install()
        settings = Profiles(self.root).settings
        self.assertEqual(GamePackage.load(settings['package']).sha256, self.package.sha256)
        self.assertEqual(Path(settings['mgba']).read_bytes(), b'emulator')
        self.assertEqual(Path(settings['mgba']).with_name('Qt.dll').read_bytes(), b'dependency')
        self.assertTrue((first.parent / 'licenses' / 'Python.txt').is_file())
        second = await self.run_install()
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_file())
        self.assertEqual(Profiles(self.root).settings['custom'], 'keep')
        self.assertEqual(Profiles(self.root).list(), [self.profile])
        self.assertEqual(self.save.read_bytes(), b'precious save')
        self.assertTrue(Profiles(self.root).settings['keyboard_only'])
        Profiles(self.root).remember(keyboard_only=False)
        await self.run_install()
        self.assertFalse(Profiles(self.root).settings['keyboard_only'])

    @patch('soullink.tools.install.check_mgba', new_callable=AsyncMock)
    async def test_failed_installed_emulator_check_keeps_previous_setup(self, check):
        check.side_effect = [None, ValueError('Missing script support')]
        with self.assertRaisesRegex(ValueError, 'script support'):
            await self.run_install()
        self.assertEqual((self.root / 'settings.json').read_bytes(), self.settings)
        self.assertEqual(list((self.root / 'installations').iterdir()), [])
        self.assertEqual(self.save.read_bytes(), b'precious save')

    async def test_corrupt_rom_cannot_replace_existing_setup(self):
        self.package.rom.write_bytes(b'bad build')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            await self.run_install()
        self.assertEqual((self.root / 'settings.json').read_bytes(), self.settings)

    @patch('soullink.tools.install.check_mgba', new_callable=AsyncMock)
    async def test_incompatible_download_is_rejected_before_copying(self, check):
        check.side_effect = ValueError('Missing script support')
        with self.assertRaisesRegex(ValueError, 'script support'):
            await self.run_install()
        self.assertFalse((self.root / 'installations').exists())
        self.assertEqual((self.root / 'settings.json').read_bytes(), self.settings)

    @patch('soullink.tools.install.check_mgba', new_callable=AsyncMock)
    @patch('soullink.tools.install.shortcut', side_effect=OSError('Desktop unavailable'))
    async def test_shortcut_failure_keeps_working_install(self, shortcut, check):
        with self.assertWarnsRegex(UserWarning, 'desktop shortcut'):
            executable = await install(self.package.directory, self.launcher, self.emulator, self.root)
        self.assertTrue(executable.is_file())
        GamePackage.load(Profiles(self.root).settings['package'])
