# Pokémon Emerald Soul Link

Source for a two-player Emerald mod with linked Pokémon, shared permanent deaths, in-game encounter tracking, partner overworld sprites, configurable rules, and seeded wild/starter randomization.

Build the game locally using the instructions below. No playable ROM or compiler output is included in this repository.

## Build the .gba

**Windows without WSL:** follow the [native Windows / MSYS2 guide](docs/soullink/WINDOWS.md).

### Ubuntu / WSL

Use **Ubuntu 24.04**, or **Ubuntu 24.04 in WSL on Windows**. Run these commands in the Ubuntu terminal. On WSL, clone into your Linux home directory for faster builds.

```sh
sudo apt-get update
sudo apt-get install -y git build-essential gcc-arm-none-eabi binutils-arm-none-eabi libnewlib-arm-none-eabi libpng-dev pkg-config python3

git clone https://github.com/aribsinvariant/pokemon-soullocke-mod.git
cd pokemon-soullocke-mod
make modern -j4
```

The output is **`pokeemerald_modern.gba`** in the project directory. Open it in desktop mGBA. This build uses the included source and assets; no original Emerald ROM is required as a build input.

Use `make modern`, as shown above. The original matching-ROM build target is not supported for this mod.

## Set up multiplayer

Use the [Windows GUI launcher](docs/soullink/LAUNCHER.md) to host, join with an invite, configure rules, and launch mGBA without terminal commands. Build/package the game below once, then select its `dist` folder in the launcher. A compatible mGBA build with automatic script loading is required.

Package your local build and its matching bridge metadata:

```sh
python3 -m soullink.tools.package
cd dist
```

The ignored `dist/` directory now contains `emerald-soullink.gba`, `manifest.json`, the multiplayer runtime, and a setup guide. Both players need the same build, desktop mGBA with **Tools → Scripting**, Python 3.10 or newer, and fresh save files.

Follow [the play guide](docs/soullink/PLAYING.md) to create a room, generate each player's script, and connect. Player PCs do not need the compiler tools once the build and scripts have been prepared.

After a loss, the host can reuse the room and scripts:

```sh
python3 -m soullink.relay.server --restart adventure
```

Run that from the same directory as the relay database. Both players then reset mGBA and select **New Game**.

## Status and source

Experimental: automated tests cover the relay, bridge, and compiled game hooks, but a complete two-PC campaign still needs manual testing.

- [Windows launcher](docs/soullink/LAUNCHER.md)
- [Play guide and rules](docs/soullink/PLAYING.md)
- [Build details and tests](docs/soullink/DEVELOPMENT.md)
- [Contributing](CONTRIBUTING.md)

Based on pret/pokeemerald, pinned in `soullink/UPSTREAM_COMMIT`. Original source assets and tool license notices are retained. Generated ROMs, packages, saves, and private room credentials are ignored by Git.
