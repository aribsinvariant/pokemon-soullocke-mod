# One-step Windows setup

1. Download the repository's source ZIP using **Code → Download ZIP**, and extract it. You can also use an existing source checkout.
2. Double-click **Setup-SoulLink.cmd** in the extracted folder. Leave the setup window open while it downloads and builds.
3. When setup completes, the game launcher opens with the game and emulator already configured. Use **Host** or **Join**. Afterward, open the **Emerald Soul Link** desktop shortcut to play.

Requires an Intel/AMD x64 PC running Windows 10 (1809+) or Windows 11, Internet access, and several GB of free space. The ROM is compiled on your PC; no original Emerald ROM is needed. Windows may ask you to permit running downloaded software. Setup does not need WSL or administrator mode.

## What gets installed

- A private MSYS2 UCRT64 environment and ARM/native compilers, under `C:\SoulLinkBuild-<Windows user SID>` (or the equivalent system drive).
- A private Windows Python 3.13 installation if a compatible registered Python 3.12/3.13 is not already available, plus an isolated launcher build environment.
- A copy of your source in that private build folder. Setup cleans and builds this copy, leaving the original checkout untouched.
- The locally built game, matching manifest, SoulLink.exe, license notices, and an official Windows x64 mGBA development build under `%LOCALAPPDATA%\EmeraldSoulLink\installations`.
- A desktop shortcut, and saved game/emulator paths so you can immediately host or join.

The setup window displays six stages. Its log is `setup.log` in the build folder. MSYS2 and Python installers are checked against pinned SHA-256 checksums. MSYS2 packages are verified by its package manager. The mGBA development download uses the official HTTPS endpoint and is checked for `--script` support before setup selects it. MSYS2 packages and mGBA development builds can change over time.

Both players must use matching game builds. Start from the same source version; the launcher rejects invites for a different ROM checksum.

## Rerun, update, or troubleshoot

Run **Setup-SoulLink.cmd** again after a failed download or build, or after obtaining updated source. Setup reuses its build tools and makes a fresh game build. It preserves existing sessions, credentials, saves, and older installed builds. Close your existing game and launcher before updating. Older sessions require their original game build; its `game` folder remains under `installations` and can be selected in **Game setup**.

- **Downloads fail:** check Internet access and retry. Python/MSYS2 checksum failures stop setup before the downloaded installer runs.
- **Cannot create the build folder:** choose a writable local folder with a short ASCII path and no spaces, using the command below. Do not run setup as a different Windows user.
- **Build fails:** inspect the first error in `setup.log`. Include the error and ARM GCC version when reporting a problem. Setup stops without replacing the existing game configuration.
- **No desktop shortcut:** setup prints the installed executable path. The installation remains usable even if desktop shortcut creation fails.
- **Windows Firewall prompt when hosting:** permit Soul Link on the network used by your partner. Router connectivity is separate from installing the game; use the [launcher guide](LAUNCHER.md) for hosting.

Advanced options, from PowerShell in the source folder:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\soullink\setup\windows.ps1 -BuildRoot C:\slbuild -NoLaunch
```

`-InstallRoot` changes the application data and installation folder; its shortcut passes that location to the launcher. `-NoShortcut` skips creating the desktop shortcut. Neither option is needed for normal setup.

To remove the tools after a successful install, delete the private `SoulLinkBuild-...` folder; the game and launcher do not depend on it. If setup installed private Python, uninstall that Python through Windows Settings first. To remove the installed game, delete the desktop shortcut and `%LOCALAPPDATA%\EmeraldSoulLink`; **that application folder also contains your saves and sessions**, so back it up first.

## Validation status

The installation service has automated tests covering reruns, save preservation, incompatible emulators, corrupt game packages, and shortcut failures. A Windows setup workflow is provided to exercise the complete download/build/install path on a Windows runner. A successful local Linux build does not verify native Windows compiler compatibility; check the Windows workflow result for that evidence.

Download sources: [MSYS2](https://www.msys2.org/docs/installer/), [Python 3.13.17](https://www.python.org/downloads/release/python-31317/), and [mGBA development builds](https://mgba.io/downloads.html).
