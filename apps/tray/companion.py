"""Windows notification-area companion for one live web Host instance."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import threading


class NamedEvent:
    def __init__(self, name):
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        for function, args, result in (
            ('CreateEventW', [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
            ('SetEvent', [wintypes.HANDLE], wintypes.BOOL),
            ('WaitForSingleObject', [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            ('CloseHandle', [wintypes.HANDLE], wintypes.BOOL),
        ):
            fn = getattr(self.api, function); fn.argtypes = args; fn.restype = result
        self.handle = self.api.CreateEventW(None, True, False, name)
        if not self.handle: raise ctypes.WinError(ctypes.get_last_error())
        self.name = name

    def set(self):
        if not self.api.SetEvent(self.handle): raise ctypes.WinError(ctypes.get_last_error())

    def wait(self, milliseconds):
        code = self.api.WaitForSingleObject(self.handle, milliseconds)
        if code not in (0, 258): raise ctypes.WinError(ctypes.get_last_error())
        return code == 0

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle); self.handle = None


class TrayCompanion:
    def __init__(self, server, data_dir):
        self.server = server
        self.events = []
        self.process = None
        self.log = None
        self.thread = None
        self.closing = threading.Event()
        directory = Path(data_dir)/'diagnostics/tray'
        directory.mkdir(parents=True, exist_ok=True)
        self.state_path = directory/'state.json'
        try:
            for suffix in ('quit', 'close', 'ready'):
                self.events.append(NamedEvent('Local\\Jarvis.Tray.'+server.instance_id+'.'+suffix))
            self.quit_event, self.close_event, self.ready_event = self.events
            script = Path(__file__).with_name('tray.ps1')
            shell = Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
            self.log = (directory/'tray.log').open('wb')
            self.process = subprocess.Popen([str(shell), '-NoProfile', '-NonInteractive', '-STA',
                '-WindowStyle', 'Hidden', '-File', str(script), '-Port', str(server.server_address[1]),
                '-OwnerPid', str(os.getpid()), '-InstanceId', server.instance_id,
                '-Version', server.version, '-StatePath', str(self.state_path)],
                stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log,
                creationflags=subprocess.CREATE_NO_WINDOW)
            if not self.ready_event.wait(15000):
                raise RuntimeError('Tray did not become ready; inspect '+str(directory/'tray.log'))
            self.thread = threading.Thread(target=self._watch, name='jarvis-tray-exit', daemon=True)
            self.thread.start()
        except BaseException:
            self.close(); raise

    def _watch(self):
        while not self.closing.is_set():
            if self.quit_event.wait(250):
                # This is an explicit desktop app exit, never a global latch.
                if not self.closing.is_set(): self.server.shutdown()
                return

    def close(self):
        self.closing.set()
        if len(self.events) >= 2: self.events[1].set()
        if self.thread: self.thread.join(timeout=2)
        if self.process:
            try: self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                # The helper observes the parent's lifetime. Never kill by PID.
                pass
        if self.log: self.log.close(); self.log = None
        for event in self.events: event.close()
        self.events = []
