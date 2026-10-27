"""A small Chrome DevTools Protocol client over a pipe, for the wizard's tests.

Starts headless Chrome with --remote-debugging-pipe (no network port, no
websocket library: the protocol's messages are JSON separated by NUL bytes on
file descriptors 3 and 4), opens one page, and lets a test evaluate
JavaScript in it, set a file input's files, and collect console errors.
POSIX only; the tests skip it elsewhere.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time


def find_chrome() -> str | None:
    for name in (os.environ.get("CHROME_PATH"), "google-chrome-stable", "google-chrome", "chromium", "chromium-browser"):
        if name and (shutil.which(name) or os.path.exists(name)):
            return shutil.which(name) or name
    return None


class Browser:
    def __init__(self, chrome: str, timeout: float = 30):
        self.timeout = timeout
        self.profile = tempfile.mkdtemp(prefix="sel-chrome-")
        self.downloads = tempfile.mkdtemp(prefix="sel-downloads-")
        to_chrome_r, self._to_chrome_w = os.pipe()
        self._from_chrome_r, from_chrome_w = os.pipe()

        def child():
            # Copy each end above 4 first: dup2 onto the same number is a
            # no-op that would leave the descriptor closed at exec.
            a, b = os.dup(to_chrome_r), os.dup(from_chrome_w)
            os.dup2(a, 3)
            os.dup2(b, 4)

        self.proc = subprocess.Popen(
            [chrome, "--headless=new", "--remote-debugging-pipe", f"--user-data-dir={self.profile}",
             "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--disable-extensions",
             "--allow-file-access-from-files", "about:blank"],
            preexec_fn=child, close_fds=False, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(to_chrome_r)
        os.close(from_chrome_w)
        self._id = 0
        self._lock = threading.Lock()
        self._waiting: dict[int, dict] = {}
        self._cond = threading.Condition()
        self.events: list[dict] = []
        self.errors: list[str] = []
        threading.Thread(target=self._read, daemon=True).start()
        self.send("Browser.setDownloadBehavior", {"behavior": "allow", "downloadPath": self.downloads, "eventsEnabled": True})
        target = self.send("Target.createTarget", {"url": "about:blank"})["targetId"]
        self.session = self.send("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        for m in ("Page.enable", "Runtime.enable", "Log.enable", "DOM.enable"):
            self.send(m, session=True)

    def _read(self):
        buf = b""
        while True:
            try:
                chunk = os.read(self._from_chrome_r, 65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\0" in buf:
                raw, buf = buf.split(b"\0", 1)
                msg = json.loads(raw)
                with self._cond:
                    if "id" in msg:
                        self._waiting[msg["id"]] = msg
                    else:
                        self.events.append(msg)
                        self._note(msg)
                    self._cond.notify_all()

    def _note(self, msg):
        m, p = msg.get("method"), msg.get("params", {})
        if m == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails", {})
            self.errors.append("exception: " + (d.get("exception", {}).get("description") or d.get("text", "")))
        elif m == "Runtime.consoleAPICalled" and p.get("type") in ("error", "assert"):
            self.errors.append("console: " + " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", [])))
        elif m == "Log.entryAdded" and p.get("entry", {}).get("level") == "error":
            self.errors.append("log: " + p["entry"].get("text", ""))

    def send(self, method, params=None, session=False):
        with self._lock:
            self._id += 1
            mid = self._id
            msg = {"id": mid, "method": method, "params": params or {}}
            if session:
                msg["sessionId"] = self.session
            os.write(self._to_chrome_w, json.dumps(msg).encode() + b"\0")
        deadline = time.time() + self.timeout
        with self._cond:
            while mid not in self._waiting:
                left = deadline - time.time()
                if left <= 0:
                    raise TimeoutError(method)
                self._cond.wait(left)
            res = self._waiting.pop(mid)
        if "error" in res:
            raise RuntimeError(f"{method}: {res['error']}")
        return res.get("result", {})

    def wait_event(self, method, since=0, timeout=None):
        deadline = time.time() + (timeout or self.timeout)
        with self._cond:
            while True:
                for e in self.events[since:]:
                    if e.get("method") == method:
                        return e
                left = deadline - time.time()
                if left <= 0:
                    raise TimeoutError(method)
                self._cond.wait(left)

    def goto(self, url):
        n = len(self.events)
        self.send("Page.navigate", {"url": url}, session=True)
        self.wait_event("Page.loadEventFired", since=n)

    def js(self, expression):
        r = self.send("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True}, session=True)
        if r.get("exceptionDetails"):
            raise RuntimeError("JS: " + json.dumps(r["exceptionDetails"])[:500])
        return r.get("result", {}).get("value")

    def until(self, expression, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.js(expression):
                return True
            time.sleep(0.05)
        raise TimeoutError("waited for: " + expression)

    def set_files(self, selector, paths):
        root = self.send("DOM.getDocument", {"depth": 0}, session=True)["root"]["nodeId"]
        node = self.send("DOM.querySelector", {"nodeId": root, "selector": selector}, session=True)["nodeId"]
        if not node:
            raise RuntimeError("no element " + selector)
        self.send("DOM.setFileInputFiles", {"nodeId": node, "files": [str(p) for p in paths]}, session=True)

    def close(self):
        try:
            self.send("Browser.close")
        except Exception:
            pass
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        for fd in (self._to_chrome_w, self._from_chrome_r):
            try:
                os.close(fd)
            except OSError:
                pass
        shutil.rmtree(self.profile, ignore_errors=True)
