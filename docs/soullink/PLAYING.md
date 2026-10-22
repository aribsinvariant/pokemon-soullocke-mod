# Playing Emerald Soul Link

This mod runs two independent Emerald adventures in mGBA. Use **SELECT** in the overworld or **SOUL LINK** in the Start menu for settings, encounters, and party requests. Pokémon summaries show their linked partner. You do not need a website or manual tracker.

Build and package the game using the repository README first. The commands below can be run from the generated `dist/` directory. On Ubuntu/WSL, use `python3` in place of `python`.

## Requirements

- Two PCs with a desktop mGBA build that includes **Tools → Scripting** (0.10 or newer), plus Python 3.10 or newer.
- The same Soul Link ROM build and its matching generated player scripts.
- Fresh save files. Original Emerald saves and other ROM hacks are incompatible.
- A relay reachable by both players: a private VPN address is simplest; alternatively forward TCP port 8765 to the relay PC.

The ROM and relay are experimental. Automated tests cover the protocol and game hooks; a complete two-PC campaign has not been played through.

## Host a room

From the project or packaged build directory:

```sh
python -m soullink.relay.server --create adventure --seed 12345 --host 0.0.0.0
```

This creates `soullink.sqlite3` and two private credential files, `players/player1.lua` and `players/player2.lua`. Keep the database: it records settings, catches, and deaths. To restart the same room:

```sh
python -m soullink.relay.server --host 0.0.0.0
```

Do not repeat `--create` for an existing room. Reuse it with the restart command below.

## Quick restart after a loss

Keep the relay and both connectors running. In another terminal, from the same directory/database as the relay, the host runs:

```sh
python -m soullink.relay.server --restart adventure
```

Both players then **reset mGBA and select New Game**, keeping their existing player scripts loaded. Confirm the settings in Soul Link again. No new room, credentials, or script generation is needed. Save the new game normally to replace the previous attempt's save.

Restart clears both players' encounters, parties, deaths, and event history together. It preserves the rules and randomizer seed; add `--seed 54321` to choose a different seed. If the relay uses a custom database path, supply the same `--db PATH` to the restart command. The command exits immediately; the running relay picks up the reset.

Only a run marked ended can restart (the default **Wipe ends run** rule does this). Old saves and existing connections cannot submit events into the new attempt. A restart message in the scripting console is expected until you reset the emulator. Do not select Continue or load an old save state.

## Generate each player's script

In the packaged build directory (Python is sufficient):

```sh
python -m soullink.tools.player_script manifest.json players/player1.lua players/player1.player.lua
python -m soullink.tools.player_script manifest.json players/player2.lua players/player2.player.lua
```

When working directly from source, use `pokeemerald_modern.elf` instead of `manifest.json`; this requires `arm-none-eabi-nm` on the build machine. Send each player their own `.player.lua` file. Each file contains that player's private room credential. Never load the same identity on both PCs.

Use the same ROM build used to generate the scripts. Changing the ROM requires regenerating both scripts, even when the protocol version is unchanged.

## Connect and start

1. Open the ROM in mGBA and start a new game. Each player needs a separate save file.
2. In **Tools → Scripting**, load your generated `.player.lua` script.
3. Start the connector on each PC:

   ```sh
   python -m soullink.bridge.client --server RELAY_ADDRESS
   ```

   The host uses `127.0.0.1` if playing on the relay PC. Keep this terminal open.

4. After the opening sequence, press **SELECT**. Player 1 selects settings with Up/Down and changes them with Left/Right. Both players select **Confirm** and press A. The rules then lock for the run.
5. Close the menu with B and play. Each starter can fight Birch's opening battle; normal exploration waits for the starter pair to form.

For two emulator instances on one PC, generate the second script with `--local-port 8767` and run its connector with `--local-port 8767`. Use separate ROM filenames so the emulator does not share a save file.

## Rules and controls

- Encounter allowances begin after the Poké Ball introduction. Dungeon floors share their named area. Grass, caves, fishing, surfing, and Rock Smash use the same area's allowance.
- Your first eligible encounter reserves the allowance. Fleeing, knocking it out, or losing it forfeits the pair. Duplicate-family and enabled gender/type exceptions permit rerolls. Simultaneous encounters are ordered by the relay.
- Pending catches cannot fight. A partner's failed encounter makes your corresponding catch unusable. Starters have their own guaranteed pair and are exempt from pair gender/type checks; their types still exclude future duplicate team types.
- If a catch has its species name, the mod supplies a `SoulNNN` nickname. Normal nickname prompts and the Name Rater remain available.
- Dead Pokémon stay visible and permanently unusable. They cannot be released. Healing does not revive them. A remote death is applied at the next safe overworld point after battles, scripts, and menus finish.
- With paired parties enabled, arrange your desired party at a PC, then choose **A: propose current party** in Soul Link. Your partner can press **L** to review the request, then **R: accept party**. Approval retrieves matching Pokémon from their boxes and deposits displaced party members, provided there is storage space. Movement pauses if the party does not match the approved set; PC interaction and menus remain accessible.
- **Left/Right** browses encounter areas; **Up/Down** jumps to an area with a recorded encounter. Pokémon summaries display the partner's latest name and species while connected.
- Optional shiny exceptions create collectibles that cannot battle. A Shedinja produced as an extra evolution is also a collectible.
- Required obstacle/water field moves can use a Pokémon in storage, including dead/pending Pokémon; normal badge requirements remain. Fly and party-menu-only field actions still use party Pokémon.
- Trading, daycare services, and Battle Frontier challenges are disabled.
- Disconnection allows a current battle/script to finish, then pauses movement. SELECT and saving through the Start menu remain available. Reconnection replays authoritative outcomes. Ordinary save reloads preserve recorded deaths. A save that predates an already committed catch requires a newer save, because the missing Pokémon cannot be reconstructed. Emulator save-state rollback stops synchronization and requires resetting to an in-game save.

## Randomization

Wild encounters and starters have separate toggles. Both players use the same seed with player-specific results. Levels, encounter rates, trainers, gifts, and static species remain unchanged. Similar-strength mode selects from the nearest 50-point base-stat-total band. Legendary exclusion also excludes mythical Pokémon. Settings are fixed after both players confirm.

## Troubleshooting

- **Room already exists / UNIQUE constraint failed: rooms.id:** run `python -m soullink.relay.server --host 0.0.0.0` without `--create`, from the same directory as before. Keep your database and existing player scripts. To reset a finished run, use the quick restart instructions above.

- **Waiting for connection:** confirm the relay and both connectors are running, the correct scripts are loaded, and the host address/port is reachable.
- **Already connected:** close the duplicate connector or wait for the old connection to time out.
- **Sync error:** inspect mGBA's scripting console. A wrong run, incompatible build, malformed event, or unsupported rollback stops progression. Correct the configuration and reset/reload the in-game save. Do not delete the relay database to bypass recorded outcomes.
- **Party rejected:** all proposed members must be live, paired, and satisfy enabled type restrictions. Ensure enough free PC space for displaced members.
- **Updated ROM:** regenerate player scripts from the matching ELF. Save compatibility across development builds is not guaranteed.

A BPS release patch can be generated from a user-supplied original English Emerald ROM; the build instructions describe the command. No original ROM is included in the repository.
