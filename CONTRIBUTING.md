# Contributing

## Development setup

Use Linux or WSL and Python 3.10 or newer. Build dependencies and emulator test setup are documented in [Development](docs/soullink/DEVELOPMENT.md). The Python relay and connector use only the standard library.

```sh
sudo apt-get install build-essential gcc-arm-none-eabi binutils-arm-none-eabi libnewlib-arm-none-eabi libpng-dev pkg-config lua5.4 libmgba-dev
make modern -j8
python3 -m unittest discover -s soullink/tests -v
lua5.4 soullink/tests/test_bridge.lua
```

The basic Python command skips emulator integration tests. Follow the development guide to build the mGBA adapter and run those tests. GitHub Actions builds the ROM and runs both emulator integration tests and Lua tests.

## Changes

Create a branch from `main`, make a focused change, and open a pull request describing the behavior and verification. Document protocol, save-layout, or player setup changes. Changes to the ROM mailbox may require regenerating player scripts; save-layout changes require a clean rebuild and fresh saves.

Keep ROMs, save files, build output, relay databases, and player credentials out of commits. Use `dist/` for local packages and `players/` for private player configs. Custom credential files should also remain there. Do not upload runtime databases in bug reports.

For gameplay bugs, include the build revision, enabled rules, emulator version, reproduction steps, and sanitized console output. See the manual acceptance checklist in the development guide before calling a build stable.

## Upstream

The source imports pret/pokeemerald at the revision in `soullink/UPSTREAM_COMMIT`. Original setup documentation and tool license notices remain in the tree. Mod integration files are listed in `soullink/MODIFIED_FILES`. Preserve upstream attribution and existing license notices.

The Windows launcher has an independent Windows build workflow. See [launcher development](docs/soullink/LAUNCHER.md#build-the-launcher-from-source). Keep executable output in the ignored `release/` directory and runtime profiles outside the checkout.
