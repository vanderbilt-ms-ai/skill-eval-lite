"""The runner finds `claude` where Anthropic's installer puts it, when the
PATH of an app opened before the install doesn't have it yet."""
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

from tests.helpers import FAKE, run_ab


class FindClaude(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.bin = self.tmp / "bin"
        self.bin.mkdir(parents=True)
        # A PATH with Python and git but no claude.
        for tool in ("git",):
            w = shutil.which(tool)
            if w:
                (self.bin / tool).symlink_to(w)

    def env(self):
        e = {"HOME": str(self.home), "USERPROFILE": str(self.home), "PATH": str(self.bin)}
        e["SKILL_EVAL_LITE_CLAUDE"] = ""
        return e

    def test_not_found_says_get_ready(self):
        r = run_ab("doctor", "--no-probe", env=self.env())
        out = r.stdout + r.stderr
        self.assertIn("isn't installed", out)
        self.assertIn("/get-ready", out)

    def test_found_in_the_installers_folder(self):
        dest = self.home / ".local" / "bin"
        dest.mkdir(parents=True)
        claude = dest / ("claude.exe" if os.name == "nt" else "claude")
        claude.write_text(f"#!/bin/sh\nexec {os.sys.executable} {FAKE} \"$@\"\n")
        claude.chmod(claude.stat().st_mode | stat.S_IXUSR)
        r = run_ab("doctor", "--no-probe", env=self.env())
        out = r.stdout + r.stderr
        self.assertNotIn("isn't installed", out)
        self.assertRegex(out, r"(?m)^\s*ok\s+Claude Code")


if __name__ == "__main__":
    unittest.main()
