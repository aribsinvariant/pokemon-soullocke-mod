# Play with the Windows launcher

The launcher handles rooms, private invites, player scripts, the connector, and opening mGBA. Players do not need Python or terminal commands when using `SoulLink.exe`.

## Get the app

For automatic ROM building and installation, extract the repository source and double-click **Setup-SoulLink.cmd**. It installs the tools, builds the game and launcher, installs compatible mGBA, configures the paths, and creates a desktop shortcut. See [one-step setup](SETUP.md). The manual setup below is for using the launcher ZIP separately.

Download `SoulLink-Windows-x64.zip` from a published repository release, or the **SoulLink-Windows-x64** artifact of the [Windows launcher workflow](https://github.com/aribsinvariant/pokemon-soullocke-mod/actions/workflows/launcher.yml). Workflow artifact downloads may require signing in to GitHub. The ZIP contains `SoulLink.exe`; the executable includes Python and the required runtime libraries.

## One-time setup

1. Extract the **SoulLink-Windows-x64.zip** launcher download and open **SoulLink.exe**.
2. In **Game setup**, choose the built game's **dist folder**. It must contain `emerald-soullink.gba` and its matching `manifest.json`. Build and package instructions are in the repository README. The launcher download does not include the ROM.
3. Choose your **mGBA executable** and click **Verify and save setup**. Use a desktop build with `--script` support, available in newer/development builds from [mGBA downloads](https://mgba.io/downloads.html). Version 0.10.5 cannot automatically load scripts and is rejected by the launcher.

Both players must use the same built game package. The launcher checks its checksum against the host's invite.

## Host

1. Open **Host**, enter a session name, and choose a seed and challenge rules. The default TCP port is **8768**.
2. For players on the same home network, leave Internet hosting off. For remote players, enable **Internet hosting** to try UPnP automatic router forwarding.
3. Click **Create and host**. Allow the app through Windows Firewall on your home network if Windows prompts.
4. Review **Invite address** and **Port**. For LAN play, use the host PC's LAN address. For Internet play, use the router's public IPv4 address. Edit these fields when using custom forwarding or a VPN.
5. Click **Copy player 2 invite** and share it privately with your partner. The invite contains their access credential.
6. Click **Play**. The launcher opens mGBA and loads your script automatically.

## Join

1. Open **Join** and paste the complete invite.
2. Click **Check invite and join**, then **Play**.
3. Start **New Game** for your first attempt. Both players press **SELECT** in the overworld and confirm the rules. The rules lock once both have confirmed.

Keep the launcher open while playing. It shows connection status and whether your partner is connected. In-game pairing, encounter tracking, and deaths follow the rules in the play guide.

## Resume and restart

Use **Saved sessions → Resume selected**, then **Play**, to continue an existing attempt. The host resumes the original relay database; it is not recreated.

After a run ends, the host can click **Restart Run** and choose the next seed. Both players close their previous game and click **Play New Run**, then choose **New Game**. The room credentials and invite remain valid. Each attempt has its own save folder, preserving the previous attempt's save.

**Close game** closes the mGBA process launched by the app; save in-game first. **Stop session** disconnects synchronization and stops hosting, leaving the game open. Closing the launcher asks whether to close mGBA too. No automatic in-game saving is performed.

New GUI sessions only: the first release does not import databases or saves from command-line runs. Those runs can continue with the existing command-line tools.

## Internet connections

Internet hosting fills the invite address using the router’s public IPv4 address or an HTTPS public-IP lookup (ipify, with an AWS fallback). Address detection works even when UPnP forwarding fails. Click **Find public IP** to retry, or enter an address manually. If detection fails, the launcher explains that in the network status. Your address and router-forwarding result are shown separately.

UPnP requires a compatible router with UPnP enabled. The launcher will not overwrite another application's port mapping. It removes mappings it created when hosting stops; an unexpected crash can require removing a remaining mapping in your router.

If automatic forwarding fails, the launcher displays the exact LAN address and TCP port for a manual router rule. Forward the chosen external TCP port to the host PC's relay TCP port. Keep the emulator's local bridge port private; the launcher selects it automatically.

A successful UPnP message means the router accepted a mapping. Internet reachability is confirmed when the remote partner connects. To test your public address, put the second device on a different Internet connection, such as a phone hotspot; testing from the same Wi-Fi depends on router loopback support.

If the router reports a private/CGNAT WAN address, an additional router or the ISP may also need configuration. The launcher cannot bypass ISP CGNAT. Use manual forwarding, a reachable VPN address, or ask your ISP for inbound IPv4 access.

## Troubleshooting

- **Cannot listen:** another app may own that port. Stop the current session, select the saved host session, choose **Change host port**, resume, and copy an updated invite.
- **Cannot reach the relay:** verify the invite address, host app, firewall, and router forwarding. The relay must run on the Windows host when playing with Windows mGBA; the GUI handles this automatically.
- **Wrong service / HTML:** the selected address and port reach a web server rather than Soul Link. Correct the invite endpoint.
- **Wrong build:** both players must select the same game package. Regenerate the package after changing the ROM.
- **Player already connected:** close the duplicate game/connector and wait a few seconds before trying again.
- **Waiting for the game:** choose New Game or Continue. The script starts communicating when the ROM initializes Soul Link.
- **Sync stopped:** inspect **Diagnostics**. Avoid loading emulator save states. Run resets require closing the old game and launching the new attempt.

Local profiles, credentials, databases, scripts, and saves are stored in `%LOCALAPPDATA%\EmeraldSoulLink`. Open that folder from **Saved sessions**. Keep it when updating the app. Diagnostics omit credentials; invites remain private.

## Build the launcher from source

On Windows, install 64-bit CPython **3.12 or 3.13**, including Tcl/Tk. In the project directory:

```powershell
py -3.13 -m venv .launcher-venv
.launcher-venv\Scripts\python -m pip install -r soullink\launcher\requirements-build.txt
.launcher-venv\Scripts\python -m soullink.tools.build_launcher
```

The output is `release\launcher\SoulLink-Windows-x64.zip`. It contains the executable, these instructions, and third-party license notices. The build runs a packaged GUI/resource smoke test before producing the ZIP. Generated binaries stay outside Git.

For development, run `.launcher-venv\Scripts\python -m soullink.launcher`. On Linux, install Tkinter (`python3-tk`) before running the Python GUI; the packaged release targets Windows x64.
