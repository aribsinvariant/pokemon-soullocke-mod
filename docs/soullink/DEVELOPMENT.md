# Development

The game is based on the pinned `pret/pokeemerald` revision in `soullink/UPSTREAM_COMMIT`. Original upstream setup documentation remains in `INSTALL.md`.

## Build

On Ubuntu/WSL:

```sh
sudo apt-get install build-essential gcc-arm-none-eabi binutils-arm-none-eabi libnewlib-arm-none-eabi libpng-dev pkg-config
make modern -j8
```

Soul Link supports the modern compiler build. The original matching/agbcc target is not supported for the mod. `pokeemerald_modern.gba` is the local playable output; `pokeemerald_modern.elf` contains the symbols used to generate bridge scripts.

Package a build:

```sh
python -m soullink.tools.package
python -m soullink.tools.package --base /path/to/original-emerald.gba
```

The second command also emits a BPS patch. It requires English Emerald SHA-1 `f3ae088181bf583e55daf962a92bb46f4f1d07b7`. Outputs and private room files are ignored by Git.

## Architecture

- C game hooks own rule enforcement. `MON_DATA_SOUL_ID` uses the previously unused, encrypted 16-bit field in `PokemonSubstruct0`; Pokémon record sizes are unchanged. IDs are encounter area plus one, with 512 reserved for starters and 65535 for unusable collectibles.
- `SoulSave` extends Pokémon storage within the existing nine save sectors. It stores run configuration, local outcomes, duplicate-family history, and a durable outbound ring. Linker size checks protect the flash layout.
- `SoulMailbox` is a versioned EWRAM interface. Build-generated scripts locate it through the ELF symbol. Compile-time assertions check record and event offsets. Inbound state is applied by the ROM only at safe overworld points.
- mGBA Lua listens only on localhost. A Python connector handles remote connection establishment outside the emulator, because mGBA's documented outbound connect call is blocking. Reads and writes handle fragmented TCP messages, partial sends, and bounded buffers.
- The asyncio relay stores room state and ordered event identities transactionally in SQLite with full synchronization. Events are acknowledged only after commit. Position updates are transient and expire independently.
- Both players run separate game simulation clocks. No battles, NPCs, collision, or story flags are synchronized.

ABI v1: 160-byte header, 512 packed 18-byte remote Pokémon records, then 16 48-byte outbound events at offset 9376. Line protocol: `HELLO`, `EVENT`, `POLL`, `POS`, `STATE`, `NOTICE`, `ERROR`. Credentials and protocol/build identity are checked before processing gameplay messages. The bridge writes complete snapshots before publishing their version.

## Tests

```sh
python -m unittest discover -s soullink/tests -v
lua soullink/tests/test_bridge.lua
```

The standard Python run skips ROM integration tests unless an mGBA adapter is supplied. To run those tests against the actual compiled ARM code:

```sh
sudo apt-get install libmgba-dev
cc -shared -fPIC -O2 soullink/tests/emulator.c -lmgba -o /tmp/soullink-emulator.so
SOUL_ADAPTER=/tmp/soullink-emulator.so SOUL_ROM=$PWD/pokeemerald_modern.gba SOUL_ELF=$PWD/pokeemerald_modern.elf python -m unittest discover -s soullink/tests -v
```

The adapter invokes compiled functions inside mGBA with controlled inputs; it does not replace the rules with a host-side imitation. The Lua unit test checks fragmented messages and partial sends using a socket/memory test double. The end-to-end integration test additionally runs two actual mGBA Lua engines through two local connectors and a TCP relay, then verifies pairing and deferred linked death in the compiled ROM.

## Acceptance still requiring manual play

Run two desktop mGBA instances through setup, both starter battles, an area capture, an incompatible reroll, a PC party change, a linked death during the partner's battle, a disconnect, and a saved-game reload. Check sprites while walking, cycling, surfing, entering buildings, and changing maps. Complete a campaign before treating this as a stable release. Emulator function tests cannot establish that every story script and UI transition is safe.

RAM usage is close to the GBA limit; inspect linker memory reports after changes. Do not increase mailbox/save arrays without checking both EWRAM and flash bounds. Existing build artifacts must be rebuilt whenever the save layout changes.
