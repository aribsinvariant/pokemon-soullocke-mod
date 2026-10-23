"""Tk desktop UI. Network and subprocess work run on one background event loop."""
import asyncio
from collections import deque
from datetime import datetime
import os
from pathlib import Path
import queue
import secrets
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import webbrowser
from .service import Controller
from .storage import DEFAULT_RULES, RULES


class Worker:
    def __init__(self, root=None):
        self.events = queue.Queue()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self.run, args=(root,), daemon=True, name='SoulLink services')
        self.thread.start()
        self.ready.wait()
        if getattr(self, 'startup_error', None):
            raise self.startup_error

    def run(self, root):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.controller = Controller(root, self.events.put)
        except Exception as exc:
            self.startup_error = exc
            self.ready.set()
            self.loop.close()
            return
        self.lock = asyncio.Lock()
        self.ready.set()
        self.loop.run_forever()
        self.loop.close()

    def call(self, method, *args):
        async def operation():
            async with self.lock:
                try:
                    result = await getattr(self.controller, method)(*args)
                    if method == 'invite':
                        self.events.put(dict(kind='invite', value=result))
                except Exception as exc:
                    self.controller.emit('error', str(exc))
                finally:
                    self.snapshot()
                    self.events.put(dict(kind='done'))
        asyncio.run_coroutine_threadsafe(operation(), self.loop)

    def snapshot(self):
        self.events.put(dict(kind='profiles', profiles=[{k: v for k, v in p.items()
                             if k not in ('token', 'partner_token')} for p in self.controller.profiles.list()],
                             settings=self.controller.profiles.settings.copy()))

    def refresh(self):
        self.loop.call_soon_threadsafe(self.snapshot)

    def close(self, close_game):
        async def shutdown():
            async with self.lock:
                try:
                    await self.controller.stop(close_game)
                finally:
                    self.events.put(dict(kind='closed'))
        asyncio.run_coroutine_threadsafe(shutdown(), self.loop)


class Launcher:
    def __init__(self, root, data_root=None):
        self.root = root
        self.worker = Worker(data_root)
        self.profile = None
        self.info = None
        self.saved = []
        self.busy = False
        self.closing = False
        self.settings_dirty = False
        self.log = deque(maxlen=250)
        self.action_buttons = []
        root.title('Emerald Soul Link')
        root.geometry('980x850')
        root.minsize(840, 760)
        root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(root)
        style.configure('Title.TLabel', font=('Segoe UI', 19, 'bold'))
        style.configure('Heading.TLabel', font=('Segoe UI', 11, 'bold'))
        style.configure('TButton', padding=(10, 5))
        page = ttk.Frame(root, padding=18)
        page.pack(fill='both', expand=True)
        ttk.Label(page, text='Emerald Soul Link', style='Title.TLabel').pack(anchor='w')
        ttk.Label(page, text='Host a run, invite your partner, and play together.').pack(anchor='w', pady=(4, 12))
        self.tabs = ttk.Notebook(page)
        self.tabs.pack(fill='both', expand=True)
        self.setup_tab = ttk.Frame(self.tabs, padding=14)
        self.host_tab = ttk.Frame(self.tabs, padding=14)
        self.join_tab = ttk.Frame(self.tabs, padding=14)
        self.saved_tab = ttk.Frame(self.tabs, padding=14)
        for widget, title in ((self.setup_tab, 'Game setup'), (self.host_tab, 'Host'),
                              (self.join_tab, 'Join'), (self.saved_tab, 'Saved sessions')):
            self.tabs.add(widget, text=title)
        self.build_setup()
        self.build_host()
        self.build_join()
        self.build_saved()
        self.build_session(page)
        self.worker.refresh()
        root.after(100, self.events)

    def button(self, parent, text, command, **pack):
        widget = ttk.Button(parent, text=text, command=command)
        widget.pack(**pack)
        self.action_buttons.append(widget)
        return widget

    def field(self, parent, row, label, variable, width=50):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', padx=(0, 12), pady=5)
        entry = ttk.Entry(parent, textvariable=variable, width=width)
        entry.grid(row=row, column=1, sticky='ew', pady=5)
        parent.columnconfigure(1, weight=1)
        return entry

    def build_setup(self):
        self.package_path = tk.StringVar()
        self.mgba_path = tk.StringVar()
        fields = ttk.Frame(self.setup_tab)
        fields.pack(fill='x')
        self.field(fields, 0, 'Built game folder', self.package_path)
        ttk.Button(fields, text='Browse…', command=self.browse_package).grid(row=0, column=2, padx=(8, 0))
        self.field(fields, 1, 'mGBA executable', self.mgba_path)
        ttk.Button(fields, text='Browse…', command=self.browse_mgba).grid(row=1, column=2, padx=(8, 0))
        ttk.Label(self.setup_tab, wraplength=790, text='Select the dist folder produced when packaging your local '
                  'game build. It must contain emerald-soullink.gba and its matching manifest.json.').pack(anchor='w', pady=(12, 8))
        ttk.Label(self.setup_tab, wraplength=790, text='Choose a desktop mGBA build with --script support. '
                  'Older releases such as 0.10.5 cannot load the player script automatically.').pack(anchor='w', pady=(0, 12))
        self.button(self.setup_tab, 'Verify and save setup', self.setup, anchor='w')
        ttk.Button(self.setup_tab, text='Open mGBA downloads', command=lambda: webbrowser.open('https://mgba.io/downloads.html')).pack(anchor='w', pady=8)
        ttk.Label(self.setup_tab, wraplength=790, text='Game compilation is a separate setup step. This launcher '
                  'does not include a ROM or emulator. No Python installation is needed for the packaged Windows app.').pack(anchor='w', pady=8)

    def build_host(self):
        fields = ttk.Frame(self.host_tab)
        fields.pack(fill='x')
        self.name = tk.StringVar(value='Our Soul Link run')
        self.seed = tk.StringVar(value=str(secrets.randbits(32)))
        self.port = tk.StringVar(value='8768')
        self.internet = tk.BooleanVar(value=False)
        self.field(fields, 0, 'Session name', self.name)
        self.seed_entry = self.field(fields, 1, 'Randomizer seed', self.seed, 20)
        self.random_button = ttk.Button(fields, text='Random seed', command=self.random_seed)
        self.random_button.grid(row=1, column=2, padx=8)
        self.field(fields, 2, 'Relay TCP port', self.port, 10)
        ttk.Checkbutton(self.host_tab, text='Internet hosting — try automatic router forwarding (UPnP)',
                        variable=self.internet).pack(anchor='w', pady=(8, 4))
        ttk.Label(self.host_tab, text='Your public address is detected when hosting starts; port forwarding is checked separately.',
                  wraplength=790).pack(anchor='w', pady=(0, 4))
        self.rule_frame = ttk.LabelFrame(self.host_tab, text='Challenge rules', padding=8)
        self.rule_frame.pack(fill='x', pady=6)
        self.rules = []
        self.rule_widgets = []
        for i, label in enumerate(RULES):
            var = tk.BooleanVar(value=bool(DEFAULT_RULES & (1 << i)))
            var.trace_add('write', self.mark_dirty)
            self.rules.append(var)
            checkbox = ttk.Checkbutton(self.rule_frame, text=label, variable=var)
            checkbox.grid(row=i // 2, column=i % 2, sticky='w', padx=(0, 18), pady=2)
            self.rule_widgets.append(checkbox)
        self.seed.trace_add('write', self.mark_dirty)
        ttk.Label(self.host_tab, text='Both players confirm these rules in-game with SELECT. Settings then lock.',
                  wraplength=790).pack(anchor='w', pady=4)
        buttons = ttk.Frame(self.host_tab)
        buttons.pack(fill='x', pady=8)
        self.button(buttons, 'Create and host', self.host, side='left')
        self.apply_button = self.button(buttons, 'Apply to current session', self.apply, side='left', padx=8)

    def build_join(self):
        ttk.Label(self.join_tab, text='Paste the private invite your host shared.', style='Heading.TLabel').pack(anchor='w')
        ttk.Label(self.join_tab, text='The invite includes the address, port, and your player access. Keep it private.',
                  wraplength=790).pack(anchor='w', pady=8)
        self.invitation = tk.Text(self.join_tab, height=6, wrap='char', font=('Consolas', 10))
        self.invitation.pack(fill='x', pady=8)
        self.button(self.join_tab, 'Check invite and join', self.join, anchor='w', pady=6)
        ttk.Label(self.join_tab, text='The launcher checks that your game matches the host. '
                  'Once the session is ready, click Play below.', wraplength=790).pack(anchor='w', pady=8)

    def build_saved(self):
        ttk.Label(self.saved_tab, text='Resume a session with its existing progress.', style='Heading.TLabel').pack(anchor='w', pady=(0, 8))
        self.session_list = ttk.Treeview(self.saved_tab, columns=('role', 'address'), show='tree headings', height=9, selectmode='browse')
        self.session_list.heading('#0', text='Session')
        self.session_list.heading('role', text='Role')
        self.session_list.heading('address', text='Relay')
        self.session_list.column('#0', width=290)
        self.session_list.column('role', width=80)
        self.session_list.column('address', width=200)
        self.session_list.pack(fill='both', expand=True)
        buttons = ttk.Frame(self.saved_tab)
        buttons.pack(fill='x', pady=10)
        self.button(buttons, 'Resume selected', self.resume, side='left')
        self.button(buttons, 'Change host port…', self.change_port, side='left', padx=8)
        ttk.Button(buttons, text='Open local data folder', command=self.open_data).pack(side='left')
        ttk.Label(self.saved_tab, text='Only sessions created by this launcher are supported. '
                  'Each restart uses a separate save folder, preserving earlier attempts.', wraplength=790).pack(anchor='w')

    def build_session(self, parent):
        frame = ttk.LabelFrame(parent, text='Current session', padding=10)
        frame.pack(fill='x', pady=(14, 0))
        self.session_title = tk.StringVar(value='Host or join a session to begin.')
        self.status = tk.StringVar(value='Select your built game package and mGBA in Game setup.')
        self.summary = tk.StringVar()
        self.network = tk.StringVar()
        ttk.Label(frame, textvariable=self.session_title, style='Heading.TLabel').pack(anchor='w')
        ttk.Label(frame, textvariable=self.status, wraplength=860).pack(anchor='w', pady=3)
        ttk.Label(frame, textvariable=self.summary, wraplength=860).pack(anchor='w')
        self.address_fields = ttk.Frame(frame)
        self.address_fields.pack(fill='x', pady=4)
        self.address = tk.StringVar()
        self.invite_port = tk.StringVar(value='8768')
        ttk.Label(self.address_fields, text='Invite address').pack(side='left')
        ttk.Entry(self.address_fields, textvariable=self.address, width=25).pack(side='left', padx=8)
        ttk.Label(self.address_fields, text='Port').pack(side='left')
        ttk.Entry(self.address_fields, textvariable=self.invite_port, width=7).pack(side='left', padx=8)
        self.refresh_address_button = self.button(self.address_fields, 'Find public IP',
                                                 lambda: self.submit('refresh_address'), side='left', padx=(0, 8))
        self.invite_button = self.button(self.address_fields, 'Copy player 2 invite', self.copy_invite, side='left')
        ttk.Label(frame, textvariable=self.network, wraplength=860).pack(anchor='w', pady=2)
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=(6, 0))
        self.play_button = self.button(buttons, 'Play', lambda: self.submit('play'), side='left')
        self.restart_button = self.button(buttons, 'Restart Run…', self.restart, side='left', padx=8)
        self.button(buttons, 'Close game', self.close_game, side='left')
        self.button(buttons, 'Stop session', self.stop_session, side='left', padx=8)
        ttk.Button(buttons, text='Diagnostics', command=self.diagnostics).pack(side='right')
        ttk.Button(buttons, text='Firewall settings', command=self.firewall).pack(side='right', padx=8)
        self.update_buttons()

    def mark_dirty(self, *_):
        self.settings_dirty = True

    def random_seed(self):
        self.seed.set(str(secrets.randbits(32)))

    def rule_mask(self):
        return sum((1 << i) for i, var in enumerate(self.rules) if var.get())

    def browse_package(self):
        path = filedialog.askdirectory(title='Select the built dist folder')
        if path:
            self.package_path.set(path)

    def browse_mgba(self):
        path = filedialog.askopenfilename(title='Select mGBA', filetypes=[('mGBA executable', '*.exe'), ('All files', '*')])
        if path:
            self.mgba_path.set(path)

    def submit(self, method, *args):
        if not self.busy:
            self.busy = True
            self.status.set('Working…')
            self.update_buttons()
            self.worker.call(method, *args)

    def numeric(self, variable, label, low=0, high=0xffffffff):
        try:
            value = int(variable.get())
            if not low <= value <= high:
                raise ValueError()
            return value
        except ValueError:
            messagebox.showerror('Check your settings', f'{label} must be an integer between {low} and {high}.', parent=self.root)
            return None

    def setup(self):
        if self.profile:
            messagebox.showinfo('Stop session first', 'Stop the current session before changing the game setup.', parent=self.root)
            return
        self.submit('setup', self.package_path.get(), self.mgba_path.get())

    def host(self):
        seed = self.numeric(self.seed, 'Seed')
        port = self.numeric(self.port, 'Port', 1, 65535)
        if seed is not None and port is not None:
            self.submit('host', self.name.get(), port, seed, self.rule_mask(), self.internet.get())

    def apply(self):
        seed = self.numeric(self.seed, 'Seed')
        if seed is not None:
            self.settings_dirty = False
            self.submit('configure', seed, self.rule_mask())

    def join(self):
        invitation = self.invitation.get('1.0', 'end').strip()
        self.submit('join', invitation)
        self.invitation.delete('1.0', 'end')

    def selected_profile(self):
        selected = self.session_list.selection()
        if not selected:
            messagebox.showinfo('Select a session', 'Choose a saved session first.', parent=self.root)
            return None
        return next(p for p in self.saved if p['id'] == selected[0])

    def resume(self):
        profile = self.selected_profile()
        if profile:
            self.submit('resume', profile['id'])

    def change_port(self):
        profile = self.selected_profile()
        if not profile:
            return
        if profile['role'] != 'host':
            messagebox.showinfo('Host setting', 'Only a saved host session has a listening port.', parent=self.root)
            return
        port = simpledialog.askinteger('Relay port', 'New host TCP port (update and resend the invite afterward):',
                                      initialvalue=profile['port'], minvalue=1, maxvalue=65535, parent=self.root)
        if port:
            self.submit('change_port', profile['id'], port)

    def copy_invite(self):
        port = self.numeric(self.invite_port, 'Invite port', 1, 65535)
        if port is not None:
            self.submit('invite', self.address.get(), port)

    def restart(self):
        if messagebox.askyesno('Restart finished run', 'Start a new attempt? The old attempt’s saves will be preserved. '
                              'Both players will need to close their old game and click Play New Run.', parent=self.root):
            seed = simpledialog.askinteger('New attempt', 'Seed for the new run:', initialvalue=self.info['seed'],
                                          minvalue=0, maxvalue=0xffffffff, parent=self.root)
            if seed is not None:
                self.submit('restart', seed)

    def close_game(self):
        if messagebox.askyesno('Close game', 'Close the launched mGBA game? Save in-game first if you want to keep progress.', parent=self.root):
            self.submit('close_emulator')

    def stop_session(self):
        if messagebox.askyesno('Stop session', 'Disconnect synchronization and stop hosting? '
                              'Your game will stay open and pause when it reaches the overworld.', parent=self.root):
            self.submit('stop')

    def open_data(self):
        path = str(self.worker.controller.profiles.root)
        if os.name == 'nt':
            os.startfile(path)
        else:
            subprocess.Popen(['xdg-open', path])

    def firewall(self):
        if os.name == 'nt':
            subprocess.Popen(['control.exe', '/name', 'Microsoft.WindowsFirewall'])
        else:
            messagebox.showinfo('Firewall', 'Allow inbound TCP connections on the host relay port in your firewall.', parent=self.root)

    def diagnostics(self):
        window = tk.Toplevel(self.root)
        window.title('Soul Link diagnostics — credentials excluded')
        window.geometry('850x440')
        text = tk.Text(window, wrap='word', font=('Consolas', 10))
        text.pack(fill='both', expand=True, padx=10, pady=10)
        text.insert('1.0', '\n'.join(self.log))
        text.configure(state='disabled')
        ttk.Button(window, text='Copy diagnostics', command=lambda: self.copy_text('\n'.join(self.log))).pack(pady=(0, 10))

    def copy_text(self, value):
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.root.update_idletasks()

    def update_info(self, info):
        self.info = info
        self.summary.set(f'Seed: {info["seed"]}    Rules: {"locked" if info["locked"] else "awaiting confirmation"}'
                         f'    Players: {sum(info["players"])} / 2' + ('    RUN ENDED' if info['ended'] else ''))
        if not self.settings_dirty or info['locked']:
            self.seed.set(str(info['seed']))
            for i, var in enumerate(self.rules):
                var.set(bool(info['rules'] & (1 << i)))
            self.settings_dirty = False
        editable = self.profile and self.profile['role'] == 'host' and not info['locked']
        for widget in self.rule_widgets:
            widget.configure(state='normal' if editable else 'disabled')
        self.update_buttons()

    def update_buttons(self):
        for button in self.action_buttons:
            button.configure(state='disabled' if self.busy or self.closing else 'normal')
        can_edit = (not self.profile or (self.profile['role'] == 'host' and self.info and not self.info['locked']))
        rule_state = 'normal' if can_edit and not self.busy and not self.closing else 'disabled'
        for widget in self.rule_widgets + [self.seed_entry, self.random_button]:
            widget.configure(state=rule_state)
        if self.busy or self.closing:
            return
        active = self.profile is not None
        host = active and self.profile['role'] == 'host'
        self.play_button.configure(state='normal' if active and self.info and not self.info['ended'] else 'disabled')
        self.invite_button.configure(state='normal' if host else 'disabled')
        self.refresh_address_button.configure(state='normal' if host and self.profile.get('internet') else 'disabled')
        self.apply_button.configure(state='normal' if host and self.info and not self.info['locked'] else 'disabled')
        self.restart_button.configure(state='normal' if host and self.info and self.info['ended'] else 'disabled')

    def events(self):
        try:
            while True:
                event = self.worker.events.get_nowait()
                kind = event['kind']
                message = event.get('message', '')
                if message:
                    self.log.append(f'{datetime.now():%H:%M:%S} {message}')
                    if kind not in ('network', 'info'):
                        self.status.set(message)
                if kind == 'profiles':
                    self.saved = event['profiles']
                    selected = self.session_list.selection()
                    self.session_list.delete(*self.session_list.get_children())
                    for p in self.saved:
                        self.session_list.insert('', 'end', iid=p['id'], text=p['name'],
                                                 values=(p['role'], f'{p["host"]}:{p["port"]}'))
                    if selected and self.session_list.exists(selected[0]):
                        self.session_list.selection_set(selected[0])
                    if not self.package_path.get():
                        self.package_path.set(event['settings'].get('package', ''))
                        self.mgba_path.set(event['settings'].get('mgba', ''))
                elif kind == 'session':
                    changed_session = not self.profile or self.profile['id'] != event['profile']['id']
                    self.profile = event['profile']
                    self.session_title.set(self.profile['name'] + ' — ' + self.profile['role'])
                    self.address.set(self.profile.get('advertised', self.profile['host']))
                    self.invite_port.set(str(self.profile.get('invite_port', self.profile['port'])))
                    self.settings_dirty = False
                    self.update_info(event['info'])
                    if self.profile['role'] == 'host' and changed_session:
                        self.network.set(f'Manual forwarding: TCP {self.profile["port"]} → '
                                         f'{self.profile.get("lan") or "your PC LAN IP"}:{self.profile["port"]}. '
                                         'Allow this app through Windows Firewall on your home network.')
                elif kind == 'info':
                    self.update_info(event['info'])
                elif kind == 'network':
                    details = event.get('result', {})
                    forwarding = (f' Manual forwarding: TCP {event["port"]} → {event["lan"]}:{event["port"]}.'
                                  if 'port' in event else '')
                    self.network.set(message + forwarding)
                elif kind == 'invite':
                    self.copy_text(event['value'])
                    self.status.set('Private player 2 invite copied. Share it with your partner.')
                elif kind == 'new_run':
                    self.play_button.configure(text='Play New Run')
                elif kind == 'stopped':
                    self.profile = self.info = None
                    self.session_title.set('No active session')
                    self.summary.set('')
                    self.network.set('')
                    self.status.set('Session stopped. Saved sessions are available to resume.')
                    self.play_button.configure(text='Play')
                    for widget in self.rule_widgets:
                        widget.configure(state='normal')
                elif kind == 'error':
                    messagebox.showerror('Soul Link', message, parent=self.root)
                elif kind == 'done':
                    self.busy = False
                    self.update_buttons()
                elif kind == 'closed':
                    self.worker.loop.call_soon_threadsafe(self.worker.loop.stop)
                    self.root.destroy()
                    return
        except queue.Empty:
            pass
        self.root.after(100, self.events)

    def close(self):
        if self.closing:
            return
        choice = messagebox.askyesnocancel('Close launcher', 'Closing disconnects synchronization. '
                   'Also close the launched mGBA game? Save in-game before choosing Yes. '
                   'Choose No to leave the game open.', parent=self.root)
        if choice is None:
            return
        self.closing = True
        self.status.set('Stopping services and cleaning up router forwarding…')
        self.update_buttons()
        self.worker.close(choice)


def main(data_root=None):
    root = tk.Tk()
    try:
        Launcher(root, data_root=data_root)
    except Exception as exc:
        messagebox.showerror('Cannot start Soul Link', str(exc), parent=root)
        root.destroy()
        return
    root.mainloop()
