"""PyInstaller entry point. --smoke-test writes a report without opening a window."""
import argparse
import json
from pathlib import Path
import sys
import tempfile


def smoke_test(output):
    import tkinter as tk
    import miniupnpc
    from soullink.launcher.gui import Launcher
    from soullink.tools.player_script import generate_script
    root = tk.Tk()
    root.withdraw()
    with tempfile.TemporaryDirectory() as temporary:
        app = Launcher(root, data_root=temporary)
        script = generate_script(0x02000000, 'smoketest', 0, 'a' * 32,
                                 Path(temporary) / 'player.lua')
        assert 'socket.bind' in script.read_text(encoding='utf-8')
        assert len(app.tabs.tabs()) == 4
        # Service teardown uses the same path as closing the GUI, without prompts.
        app.closing = True
        app.worker.close(False)
        root.after(15000, root.quit)
        root.mainloop()
        app.worker.thread.join(timeout=5)
        assert not app.worker.thread.is_alive(), 'Service thread did not shut down'
        Path(output).write_text(json.dumps(dict(ok=True, tkinter=tk.TkVersion,
                   upnp=hasattr(miniupnpc, 'UPnP'), bundled=bool(getattr(sys, 'frozen', False)))), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Emerald Soul Link launcher')
    parser.add_argument('--smoke-test', type=Path)
    parser.add_argument('--data-root', type=Path)
    args = parser.parse_args()
    if args.smoke_test:
        try:
            smoke_test(args.smoke_test)
        except Exception as exc:
            args.smoke_test.write_text(json.dumps(dict(ok=False, error=str(exc))), encoding='utf-8')
            raise
    else:
        from soullink.launcher.gui import main
        main(data_root=args.data_root)
