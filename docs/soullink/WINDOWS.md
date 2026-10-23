# Build on Windows without WSL

For automatic installation and a desktop shortcut, double-click **Setup-SoulLink.cmd** in the repository. See [one-step Windows setup](SETUP.md). The instructions below describe the manual build process.

Use MSYS2 UCRT64 on an x64 Windows PC. MSYS2 supplies the Bash shell, Make, and Windows compiler tools used by this project's Makefiles. It does not require WSL or a Linux virtual machine. See the [MSYS2 installer and system requirements](https://www.msys2.org/).

These instructions have been checked against the Makefiles and official package listings. A complete native Windows build has not been verified here; the currently verified build uses Ubuntu's ARM GCC 13 toolchain.

## 1. Install MSYS2

Install MSYS2 in its default location, `C:\msys64`. Open **MSYS2 UCRT64** from the Start menu. Run all commands below in that terminal, rather than PowerShell, Command Prompt, or Git Bash.

Update the packages:

```sh
pacman -Syu
```

If the update asks you to close the terminal, close it, reopen **MSYS2 UCRT64**, and run `pacman -Syu` again to finish.

## 2. Install build tools

```sh
pacman -S --needed git make \
  mingw-w64-ucrt-x86_64-gcc \
  mingw-w64-ucrt-x86_64-libpng \
  mingw-w64-ucrt-x86_64-pkgconf \
  mingw-w64-ucrt-x86_64-python \
  mingw-w64-ucrt-x86_64-arm-none-eabi-gcc \
  mingw-w64-ucrt-x86_64-arm-none-eabi-binutils \
  mingw-w64-ucrt-x86_64-arm-none-eabi-newlib
```

The host compiler builds the asset tools; the ARM compiler builds the GBA code. The ARM packages include the required C library. Official listings: [ARM GCC](https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-arm-none-eabi-gcc), [newlib](https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-arm-none-eabi-newlib), and [pkgconf](https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-pkgconf).

Check the installation:

```sh
echo "$MSYSTEM"
gcc --version
arm-none-eabi-gcc --version
pkg-config --modversion libpng
python --version
```

`MSYSTEM` should print `UCRT64`. All other commands should print a version.

## 3. Download and build

Use a short directory without spaces, such as `C:\soullink`. Its MSYS2 path is `/c/soullink`.

```sh
mkdir -p /c/soullink
cd /c/soullink
git clone https://github.com/aribsinvariant/pokemon-soullocke-mod.git
cd pokemon-soullocke-mod
make modern -j4 CC=gcc CXX=g++ TOOLCHAIN=
```

`TOOLCHAIN=` selects the ARM tools installed above instead of any existing devkitARM installation. Keep that option when rebuilding with this setup.

When the build succeeds, the playable file is:

```text
C:\soullink\pokemon-soullocke-mod\pokeemerald_modern.gba
```

Open that file in Windows mGBA. No original Emerald ROM is required as a build input. Use `make modern`, not plain `make`.

## 4. Prepare multiplayer

In the same terminal and project directory:

```sh
python -m soullink.tools.package
cd dist
```

The `dist` folder contains the ROM, matching build manifest, and multiplayer runtime. Follow [the play guide](PLAYING.md) from this folder to create the room, generate player scripts, and run the connector. You can keep using the MSYS2 terminal for Python commands while running Windows mGBA normally.

Create a room only once. On subsequent launches, resume it with:

```sh
python -m soullink.relay.server --host 0.0.0.0
```

## Troubleshooting

- **Command not found:** confirm you opened MSYS2 UCRT64 and completed the package installation.
- **Missing `png.h` or libpng:** run `pkg-config --modversion libpng`; reinstall the UCRT64 libpng and pkgconf packages above if that check fails.
- **Missing `libc.a` or `libnosys.a`:** install the ARM newlib package. `arm-none-eabi-gcc -mthumb -print-file-name=libc.a` should return a full path, not just `libc.a`.
- **Build fails after changing compilers:** run `make clean`, then repeat the build command. Keep builds from different environments in separate checkouts.
- **Other compiler/linker errors:** record `arm-none-eabi-gcc --version` and the first error. MSYS2 packages roll forward; newer compiler versions may expose compatibility problems or change RAM usage. Do not bypass linker memory-limit errors.
- **Linker says `memory.ld` appears multiple times:** update to the latest source and rerun setup. Some Windows binutils versions falsely reject included linker scripts. The modern build now generates a self-contained linker script to avoid this bug.
