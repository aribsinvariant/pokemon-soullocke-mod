# Development

The game is based on the pinned `pret/pokeemerald` revision in `soullink/UPSTREAM_COMMIT`. Original upstream setup documentation remains in `INSTALL.md`.

## Build

For Windows without WSL, follow the [MSYS2 build guide](WINDOWS.md).

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

## Launcher

The Windows play launcher is described in [LAUNCHER.md](LAUNCHER.md), including executable build instructions. Its GUI uses a background asyncio worker; `Controller` owns relay/connector tasks and calls reusable script generation. Settings, credentials, and per-attempt saves are stored outside the installation directory.

Launcher-created rooms record their ROM SHA-256. An additive authenticated `INFO protocol build room player token` request returns `SESSION` followed by JSON metadata (protocol, build, run, seed, rules, lock/ended state, confirmations, players online, and ROM hash), then closes. It does not occupy a gameplay slot or change the mailbox ABI. Existing HELLO/EVENT/POLL/POS clients remain compatible. Only the local hosting controller can configure the database; the INFO endpoint is read-only.

UPnP tests use fake routers to cover denied discovery, private WAN addresses, mapping conflicts, renewal, cancellation, and ownership-checked cleanup. A successful mapping is not proof of Internet reachability. Actual two-PC WAN play and router interoperability remain manual acceptance checks.

The Windows workflow builds and smoke-tests a frozen executable, uploads its ZIP as an Actions artifact, and attaches it when a GitHub release is published. The ZIP contains neither a ROM nor mGBA. A local GUI screenshot/smoke check can establish that Tk widgets and bundled resources load; it cannot establish a completed two-PC campaign.

## Architecture

- C game hooks own rule enforcement. `MON_DATA_SOUL_ID` uses the previously unused, encrypted 16-bit field in `PokemonSubstruct0`; Pokémon record sizes are unchanged. IDs are encounter area plus one, with 512 reserved for starters and 65535 for unusable collectibles.
- `SoulSave` extends Pokémon storage within the existing nine save sectors. It stores run configuration, local outcomes, duplicate-family history, and a durable outbound ring. Linker size checks protect the flash layout.
- `SoulMailbox` is a versioned EWRAM interface. Build-generated scripts locate it through the ELF symbol. Compile-time assertions check record and event offsets. Inbound state is applied by the ROM only at safe overworld points.
- mGBA Lua listens only on localhost. A Python connector handles remote connection establishment outside the emulator, because mGBA's documented outbound connect call is blocking. Reads and writes handle fragmented TCP messages, partial sends, and bounded buffers.
- The asyncio relay stores room state and ordered event identities transactionally in SQLite with full synchronization. Events are acknowledged only after commit. Position updates are transient and expire independently.
- Both players run separate game simulation clocks. No battles, NPCs, collision, or story flags are synchronized.

Configuration retains the existing 32-bit rules field and save/mailbox sizes. Bits 0–11 keep their original meanings; bits 12 and 13 disable battle bag items and force Set. Starting options use bits 14–15 (text speed 0–2), 16 (Set), 17 (animations off), and 18–22 (zero-based frame 0–19), with bit 23 indicating their presence. Legacy configuration without bit 23 does not overwrite game options. Bits 24–28 enable QoL permissions; bits 29–31 and invalid option values are rejected. No save migration is required.

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

The ROM tests also measure emulated CPU cycles for stable overworld parties of one through six Pokémon. After initial reconciliation, `SoulLink_Overworld` must use less than half of the GBA's 280896-cycle frame, leaving time for normal field processing. Party membership and death checks share a fresh snapshot of the six encrypted Soul IDs on each update. This budget does not cover membership changes or unresolved reconciliation, which can scan PC storage; those paths have separate correctness tests. Rebuild the test adapter when its exported functions change.

## Acceptance still requiring manual play

Run two desktop mGBA instances through setup, both starter battles, an area capture, an incompatible reroll, a PC party change, a linked death during the partner's battle, a disconnect, and a saved-game reload. Check sprites while walking, cycling, surfing, entering buildings, and changing maps. Complete a campaign before treating this as a stable release. Emulator function tests cannot establish that every story script and UI transition is safe.

RAM usage is close to the GBA limit; inspect linker memory reports after changes. Do not increase mailbox/save arrays without checking both EWRAM and flash bounds. Existing build artifacts must be rebuilt whenever the save layout changes.

QoL permissions use rules bits 24–28 (teleport, heal, level, moves, PC). They do not depend on starting-options bit 23; bits 29–31 remain invalid. The launcher maps rule labels to explicit bit positions. Existing saved rules stay unchanged; new rooms enable all five permissions. Auto-run uses persistent event flag 0x20. Save, Pokémon, and mailbox layouts are unchanged.

The party move relearner uses a bounded ancestral learnset union and a separate return callback, while the original scripted Heart Scale relearner retains its behavior. QoL level changes bypass move prompts but reuse evolution scenes. Battle previews use pure chart lookups and do not advance RNG. Manual QoL acceptance includes indoor/cave travel and cancellation, surf/bike arrival, PC return, a full party action list, evolution cancellation/chains, learn/replace/cancel, nickname propagation, saved auto-run, and double-battle info/description return. Check pending partner deaths while these screens are open.

Partner species badges reuse the first existing Pokémon icon frame at 16×16. Party badges follow each slot’s Pokémon sprite; battle badges follow the local battler’s healthbox and resolve identity through its party index. Dedicated palettes are shared and released when the last badge disappears; existing party icon palettes are borrowed. ROM tests cover lookup, resource reuse, party rearrangement, remote species updates, and doubles healthbox visibility/switching.
