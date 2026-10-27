"""Nothing personal or machine-specific in any file of the repository: no
home-folder paths, user or host names, real e-mail addresses, session IDs or
key-like strings, and no paths of the private course repository. The patterns
are assembled from pieces so that this file does not match itself."""
import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FICTIONAL = (".example", ".invalid", ".test", "example.com", "example.org", "example.net")

PATTERNS = {
    "a home folder path": re.compile("/" + r"home/[A-Za-z0-9_]|/" + r"Users/[A-Za-z]|C:\\\\" + "Users"),
    "a user name": re.compile(r"(?i)(?<![a-z0-9])" + "s" + "dl" + r"(?![a-z0-9])"),
    "a personal name or address": re.compile("(?i)" + "lil" + "burn|@" + "gmail|simon" + "lilburn"),
    "a host name": re.compile("(?i)" + "home" + "base"),
    "a key-like string": re.compile("sk-" + "ant-|gh" + "p_[A-Za-z0-9]{8}|github" + "_pat_|xox[abps]" + "-|AK" + "IA[0-9A-Z]{16}|-----BEGIN " + "[A-Z ]*PRIVATE"),
    "a session or account ID": re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
    "a course repository path": re.compile("course" + "-planning/|assess" + "ments/0|build/" + "agents|api" + r"\.keys|external/" + "ai-5100"),
}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}")


def files():
    try:
        out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=REPO, capture_output=True, text=True, check=True).stdout
        names = [n for n in out.splitlines() if n]
    except (OSError, subprocess.CalledProcessError):
        names = [p.relative_to(REPO).as_posix() for p in REPO.rglob("*") if p.is_file() and ".git" not in p.parts]
    return [REPO / n for n in names if (REPO / n).is_file()]


class Privacy(unittest.TestCase):
    def test_no_personal_or_machine_data(self):
        hits = []
        for p in files():
            if p.suffix in (".png", ".jpg", ".ico") or p.name == "test_privacy.py":
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            for what, rx in PATTERNS.items():
                for m in rx.finditer(text):
                    line = text.count("\n", 0, m.start()) + 1
                    hits.append(f"{p.relative_to(REPO)}:{line}: {what}: {m.group(0)!r}")
            for m in EMAIL.finditer(text):
                if not m.group(0).lower().endswith(FICTIONAL):
                    line = text.count("\n", 0, m.start()) + 1
                    hits.append(f"{p.relative_to(REPO)}:{line}: an e-mail address: {m.group(0)!r}")
        self.assertEqual(hits, [], "\n".join(hits[:50]))


if __name__ == "__main__":
    unittest.main()
