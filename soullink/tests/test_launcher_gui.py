"""A focused native-Tk regression: network status must survive address refreshes."""
import tempfile
import unittest

try:
    import tkinter as tk
except ImportError:
    tk = None


@unittest.skipIf(tk is None, 'Tkinter not installed')
class LauncherGuiTests(unittest.TestCase):
    def test_upnp_failure_stays_visible_after_session_address_update(self):
        from soullink.launcher.gui import Launcher
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest('No graphical display')
        root.withdraw()
        with tempfile.TemporaryDirectory() as directory:
            app = Launcher(root, directory)
            try:
                profile = dict(id='a' * 32, name='test', role='host', host='127.0.0.1',
                               internet=True, port=8768, advertised='', lan='10.0.0.90')
                info = dict(seed=1, rules=97, locked=False, ended=False, players=[False, False])
                app.worker.events.put(dict(kind='session', profile=profile, info=info))
                app.worker.events.put(dict(kind='network', message='UPnP disabled', lan='10.0.0.90', port=8768))
                app.worker.events.put(dict(kind='session', profile=dict(profile, advertised='8.8.4.4'), info=info))
                app.events()
                self.assertEqual(app.address.get(), '8.8.4.4')
                self.assertIn('UPnP disabled', app.network.get())
            finally:
                app.worker.close(False)
                root.after(5000, root.quit)
                root.mainloop()
                app.worker.thread.join(5)
