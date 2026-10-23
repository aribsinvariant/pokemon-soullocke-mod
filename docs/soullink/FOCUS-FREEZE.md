# Windows mGBA focus-freeze reproduction

Tested on October 22, 2026 using Windows desktop capture, mouse/keyboard input, and actual Alt+Tab presses. Orca was running, but its computer-use tools were unavailable in the agent session, so Windows desktop controls were used instead. All games used separate test profiles and fresh attempts; existing player saves were not loaded.

## Reproduction

Two native Windows mGBA processes were launched through the committed Soul Link controller, with a local host and guest. The ROM and emulator paths came from the existing launcher configuration. The baseline used commit `f8b77cc`, before the local bridge/launcher mitigations. The game reached the new-game introduction; no completed campaign or remote two-PC test is claimed.

The installed emulator reported `0.11-9157-fd9dc5c2c` (`fd9dc5c2cbf234365068855851107e762fc6211b`). Its executable is 32-bit. A separate official portable 64-bit build reported the same revision.

| Configuration | Observed result |
| --- | --- |
| Installed 32-bit mGBA, existing settings | Host stopped responding during focus/input testing in the new-game introduction; guest remained responsive. |
| Official 64-bit mGBA, copied settings | Host also stopped responding; changing architecture was insufficient. |
| 64-bit mGBA, Software (Qt) display | Host stopped responding after the second automated Alt+Tab cycle; guest remained responsive. |
| 64-bit software display, individual SDL input-driver flags disabled | Host stopped responding at cycle 7; those flags were insufficient. |
| Same 64-bit software display, SDL controller allow-list excluding devices | Both processes remained responsive for all 30 Alt+Tab cycles. |
| Updated launcher, 64-bit software display, keyboard-only default | Both processes remained responsive for all 30 Alt+Tab cycles. |
| Updated launcher, original installed 32-bit emulator and display settings, keyboard-only default | Both processes remained responsive for all 30 Alt+Tab cycles. |

Each automated cycle focused one game, sent a game input, pressed Alt+Tab away, returned to the game, and recorded both processes' responsiveness, CPU time, and window captions. The selected process alternated between host and guest. The freeze occurred before normal linked overworld gameplay, so a WAN connection was not needed to trigger it.

## Captured stacks

Full-memory dumps of the frozen 32-bit host were captured before terminating the test processes. A 32-bit dump was needed for useful x86 thread contexts. Microsoft DbgEng extracted the thread stacks; the official matching mGBA debug-symbol archive resolved the executable offsets.

The UI thread included `ScriptingController::updateGamepad` at `ScriptingController.cpp:305`, through `QReadLocker::relock`. The emulation thread included `InputController::pollEvents` at `InputController.cpp:377`, called by `CoreController::updateKeys`. Both were blocked acquiring the controller input read lock. This is evidence of an emulator input-lock deadlock; software rendering did not resolve it.

## Workaround and limits

The launcher now defaults to keyboard-only input and supplies `SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT=0xffff/0xffff` in the emulator child's environment. This allow-list excludes the tested controller devices, avoiding the blocked polling path. The setting is reversible in **Game setup** and does not change the parent environment or Windows devices. Gamepads are unavailable while it is enabled.

This is a measured workaround on the affected PC, not a fix to mGBA's native locking implementation or proof that every emulator freeze is resolved. In particular, the 30-cycle test does not replace a complete two-PC campaign or long-duration play test. Focus-related connection recovery is tested separately with two real mGBA Lua engines.

Raw desktop captures, process dumps, generated credentials, and test sessions stay outside Git in the local `SoulLinkFocusTest` / `EmeraldSoulLinkFocusTest` directories. They are not part of a release package.

References: [SDL controller allow-list](https://wiki.libsdl.org/SDL2/SDL_HINT_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT), [mGBA input polling source](https://github.com/mgba-emu/mgba/blob/fd9dc5c2cbf234365068855851107e762fc6211b/src/platform/qt/InputController.cpp), [mGBA scripting gamepad source](https://github.com/mgba-emu/mgba/blob/fd9dc5c2cbf234365068855851107e762fc6211b/src/platform/qt/scripting/ScriptingController.cpp).
