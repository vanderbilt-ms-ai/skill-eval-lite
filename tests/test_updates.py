"""0.2.0: `run_ab.py updates` and `update` (Simon, 2026-11-07: "check
whether the Shared I and Personal I folders are up to date (and that
skill-eval-lite is up to date) ... so if we push further changes, students
can pull them in and keep running").

Every request goes to a small web server on this computer that stands in
for GitHub and the course site; nothing here uses the network.
"""
import functools
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tests.helpers import REPO, run_ab

VERSION = (REPO / "VERSION").read_text().strip()


class Site:
    """A folder served over HTTP, with each request's path recorded."""

    def __init__(self, root: Path):
        self.root, self.hits = root, []
        site = self

        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *args):
                site.hits.append(self.path)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(root)))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def pack(site: Site, pid: str, n: int, files: dict[str, str], made: str = "2026-11-06") -> dict:
    import hashlib
    sums = {k: hashlib.sha256(v.encode()).hexdigest() for k, v in sorted(files.items())}
    return {"schema": "ai5500-project-pack/1", "project": pid, "name": pid.title(), "title": "A project",
            "folder": f"ai5500-{pid}", "revision": {"n": n, "date": f"2026-10-{20 + n}"}, "made": made,
            "tools": [], "sha256": hashlib.sha256(json.dumps(sums).encode()).hexdigest(), "files": sums,
            "urls": {"page": f"{site.url}projects/{pid}.html", "zip": f"{site.url}projects/{pid}-for-ai.zip",
                     "manifest": f"{site.url}projects/{pid}-for-ai.json"}}


def write_folder(folder: Path, files: dict[str, str], p: dict | None):
    folder.mkdir(parents=True, exist_ok=True)
    for k, v in files.items():
        (folder / k).parent.mkdir(parents=True, exist_ok=True)
        (folder / k).write_text(v)
    if p:
        (folder / "pack.json").write_text(json.dumps(p, indent=2))


def publish(site: Site, pid: str, files: dict[str, str], p: dict | None):
    """The course site's ZIP and manifest for a project."""
    d = site.root / "projects"
    d.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in files.items():
            z.writestr(f"ai5500-{pid}/{k}", v)
        if p:
            z.writestr(f"ai5500-{pid}/pack.json", json.dumps(p, indent=2))
    (d / f"{pid}-for-ai.zip").write_bytes(buf.getvalue())
    if p:
        (d / f"{pid}-for-ai.json").write_text(json.dumps(p, indent=2))


def old_skill(site: Site, pid: str, n: int) -> str:
    """An older brief folder's SKILL.md, from before pack.json."""
    return (f"---\nname: ai5500-{pid}\ndescription: A project.\n---\n\n# {pid.title()}: A project\n\n"
            f"4. This copy holds revision {n} (Fri 2026-10-30) of the brief, made on 2026-11-06. If the course site "
            f"has a later revision, the student should download this again. The project's page: "
            f"{site.url}projects/{pid}.html\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.site = Site(self.tmp / "site")
        (self.tmp / "site").mkdir()
        self.addCleanup(self.site.close)
        (self.site.root / "VERSION").write_text(VERSION + "\n")
        self.ws = self.tmp / "ai5500"
        self.ws.mkdir()
        self.env = {"SKILL_EVAL_LITE_UPDATE_URL": self.site.url + "VERSION", "SKILL_EVAL_LITE_STATE": str(self.tmp / "state")}

    def updates(self, *args, env=None):
        return run_ab("updates", "--workspace", self.ws, *args, env={**self.env, **(env or {})})

    def report(self, *args):
        r = self.updates("--json", *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)


class Checks(Base):
    def test_each_state(self):
        same = {"brief.md": "The brief.", "rubric.md": "The rubric."}
        # Newer: revision 3 is out.
        write_folder(self.ws / "ai5500-shared-1", same, pack(self.site, "shared-1", 2, same))
        publish(self.site, "shared-1", same, pack(self.site, "shared-1", 3, same))
        # Up to date.
        write_folder(self.ws / "ai5500-personal-1", same, pack(self.site, "personal-1", 2, same))
        publish(self.site, "personal-1", same, pack(self.site, "personal-1", 2, same, made="2026-11-09"))
        # The same revision with a file changed.
        write_folder(self.ws / "ai5500-shared-2", same, pack(self.site, "shared-2", 1, same))
        fixed = {**same, "brief.md": "The brief, fixed."}
        publish(self.site, "shared-2", fixed, pack(self.site, "shared-2", 1, fixed))
        # An older folder with no pack.json, same revision.
        write_folder(self.ws / "ai5500-personal-2", {**same, "SKILL.md": old_skill(self.site, "personal-2", 1)}, None)
        publish(self.site, "personal-2", same, pack(self.site, "personal-2", 1, same))
        # No manifest published.
        write_folder(self.ws / "ai5500-personal-3", same, pack(self.site, "personal-3", 1, same))
        # Not a brief folder: ignored.
        write_folder(self.ws / "class-assistant", {"CLAUDE.md": "Wren."}, None)
        (self.site.root / "VERSION").write_text("9.9.9\n")

        r = self.report("--again")
        self.assertEqual(r["skill_eval_lite"]["status"], "newer")
        self.assertEqual(r["skill_eval_lite"]["published"], "9.9.9")
        got = {b["folder"]: b["status"] for b in r["briefs"]}
        self.assertEqual(got, {"ai5500-shared-1": "newer", "ai5500-personal-1": "current", "ai5500-shared-2": "changed",
                               "ai5500-personal-2": "old-copy", "ai5500-personal-3": "unknown"})
        changed = next(b for b in r["briefs"] if b["folder"] == "ai5500-shared-2")
        self.assertEqual(changed["changed"], ["brief.md"])

        text = self.updates().stdout
        self.assertIn("Skill Eval Lite: 9.9.9 is out. This copy is " + VERSION + ".", text)
        self.assertIn("ai5500-shared-1 (Shared-1): revision 3 (2026-10-23) is out. This copy is revision 2.", text)
        self.assertIn("ai5500-personal-1 (Personal-1): up to date (revision 2).", text)
        self.assertIn("1 of the course's files changed since this copy (brief.md)", text)
        self.assertIn("no pack.json", text)
        self.assertIn("the course site publishes no manifest for it yet", text)
        self.assertIn("/check-updates", text)
        self.assertIn("--again checks now", text, "the second call reads the day's check")

    def test_offline(self):
        same = {"brief.md": "The brief."}
        write_folder(self.ws / "ai5500-shared-1", same, pack(self.site, "shared-1", 2, same))
        self.site.close()
        r = self.report("--again")
        self.assertEqual(r["skill_eval_lite"]["status"], "unknown")
        self.assertEqual(r["briefs"][0]["status"], "unknown")
        self.assertIn("couldn't reach", r["briefs"][0]["reason"])

    def test_it_sends_nothing_of_the_students(self):
        same = {"brief.md": "The brief."}
        write_folder(self.ws / "ai5500-shared-1", {**same, "progress.md": "My plan."}, pack(self.site, "shared-1", 2, same))
        publish(self.site, "shared-1", same, pack(self.site, "shared-1", 2, same))
        self.report("--again")
        self.assertEqual(sorted(self.site.hits), ["/VERSION", "/projects/shared-1-for-ai.json"])


class Hook(Base):
    def setUp(self):
        super().setUp()
        self.same = {"brief.md": "The brief."}
        write_folder(self.ws / "ai5500-shared-1", self.same, pack(self.site, "shared-1", 2, self.same))
        publish(self.site, "shared-1", self.same, pack(self.site, "shared-1", 2, self.same))

    def hook(self, *args, env=None):
        r = self.updates("--hook", *args, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_silent_when_current_and_once_a_day(self):
        self.assertEqual(self.hook(), "")
        hits = len(self.site.hits)
        self.assertEqual(hits, 2)
        self.assertEqual(self.hook(), "")
        self.assertEqual(len(self.site.hits), hits, "a second session the same day reads the day's check")
        # Something newer is published: found at the next day's check (here, --again).
        publish(self.site, "shared-1", self.same, pack(self.site, "shared-1", 3, self.same))
        line = self.hook("--again")
        self.assertEqual(line.count("\n"), 1)
        self.assertIn("ai5500-shared-1 (Shared-1) has revision 3", line)
        self.assertIn("/check-updates", line)
        hits = len(self.site.hits)
        self.assertEqual(self.hook(), line, "the day's notice again, from the day's check")
        self.assertEqual(len(self.site.hits), hits)

    def test_a_changed_folder_is_checked_again(self):
        self.hook()
        hits = len(self.site.hits)
        write_folder(self.ws / "ai5500-shared-1", self.same, pack(self.site, "shared-1", 3, self.same))
        self.hook()
        self.assertGreater(len(self.site.hits), hits, "after an update the day's check no longer holds")

    def test_never_fails(self):
        self.blocked = self.tmp / "a-file"
        self.blocked.write_text("not a folder")
        for env in ({"SKILL_EVAL_LITE_UPDATE_URL": "http://127.0.0.1:9/VERSION"},
                    {"SKILL_EVAL_LITE_STATE": str(self.blocked / "state")},
                    {"SKILL_EVAL_LITE_WORKSPACE": str(self.tmp / "nowhere")}):
            r = run_ab("updates", "--hook", "--again", env={**self.env, **env})
            self.assertEqual(r.returncode, 0, (env, r.stderr))
            self.assertEqual(r.stdout, "", env)

    def test_the_settings_hook_runs_in_sh_and_never_fails(self):
        cmd = json.loads((REPO / ".claude" / "settings.json").read_text())["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        env = {**os.environ, **self.env, "SKILL_EVAL_LITE_WORKSPACE": str(self.ws), "CLAUDE_PROJECT_DIR": str(REPO)}
        r = subprocess.run(["/bin/sh", "-c", cmd], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        publish(self.site, "shared-1", self.same, pack(self.site, "shared-1", 4, self.same))
        r = subprocess.run(["/bin/sh", "-c", cmd.replace("--hook", "--hook --again")], capture_output=True, text=True,
                           env=env, timeout=60)
        self.assertIn("has revision 4", r.stdout)
        # With neither python3 nor py on the PATH it still exits 0, quietly.
        r = subprocess.run(["/bin/sh", "-c", cmd], capture_output=True, text=True,
                           env={**env, "PATH": str(self.tmp / "empty")}, timeout=60)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))


class UpdateBrief(Base):
    def test_new_revision_keeps_the_students_files(self):
        old = {"brief.md": "Old brief.", "rubric.md": "The rubric.", "guide.md": "A page since removed."}
        folder = self.ws / "ai5500-shared-1"
        write_folder(folder, old, pack(self.site, "shared-1", 2, old))
        mine = {"progress.md": "My plan.", "ai-use-log.md": "My log.", "notes.md": "My notes.", "drafts/report.md": "Draft."}
        write_folder(folder, mine, None)
        new = {"brief.md": "New brief.", "rubric.md": "The rubric.", "plan.md": "The plan.", "notes.md": "Not yours."}
        publish(self.site, "shared-1", new, pack(self.site, "shared-1", 3, {k: v for k, v in new.items() if k != "notes.md"}))

        dry = run_ab("update", "--brief", folder, "--dry-run", env=self.env)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertIn("would replace 1 of the course's files, add 1", dry.stdout)
        self.assertEqual((folder / "brief.md").read_text(), "Old brief.", "a dry run changes nothing")

        r = run_ab("update", "--brief", folder, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ai5500-shared-1: revision 2 -> 3", r.stdout)
        self.assertIn("Your own files stay as they are: ai-use-log.md, drafts/, notes.md, progress.md", r.stdout)
        self.assertIn('"What changed in revision 3"', r.stdout)
        self.assertEqual((folder / "brief.md").read_text(), "New brief.")
        self.assertEqual((folder / "plan.md").read_text(), "The plan.")
        for k, v in mine.items():
            self.assertEqual((folder / k).read_text(), v, k)
        kept = folder / "previous" / "r2-2026-11-06"
        self.assertEqual((kept / "brief.md").read_text(), "Old brief.")
        self.assertEqual((kept / "guide.md").read_text(), "A page since removed.")
        self.assertFalse((folder / "guide.md").exists())
        self.assertEqual(json.loads((folder / "pack.json").read_text())["revision"]["n"], 3)
        self.assertEqual(self.report("--again")["briefs"][0]["status"], "current")

    def test_an_older_folder_gets_pack_json(self):
        folder = self.ws / "ai5500-personal-1"
        write_folder(folder, {"brief.md": "Brief.", "SKILL.md": old_skill(self.site, "personal-1", 2),
                              "progress.md": "Mine."}, None)
        files = {"brief.md": "Brief.", "SKILL.md": "New instructions."}
        publish(self.site, "personal-1", files, pack(self.site, "personal-1", 2, files))
        r = run_ab("update", "--brief", folder, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("revision 2, brought up to date", r.stdout)
        self.assertTrue((folder / "pack.json").is_file())
        self.assertEqual((folder / "progress.md").read_text(), "Mine.")
        self.assertEqual((folder / "SKILL.md").read_text(), "New instructions.")

    def test_a_zip_with_a_path_outside_its_folder_is_refused(self):
        folder = self.ws / "ai5500-shared-1"
        same = {"brief.md": "Brief."}
        write_folder(folder, same, pack(self.site, "shared-1", 1, same))
        publish(self.site, "shared-1", same, pack(self.site, "shared-1", 2, same))
        with zipfile.ZipFile(self.site.root / "projects" / "shared-1-for-ai.zip", "a") as z:
            z.writestr("ai5500-shared-1/../../evil.txt", "no")
        r = run_ab("update", "--brief", folder, env=self.env)
        self.assertEqual(r.returncode, 2)
        self.assertIn("outside its folder", r.stderr)
        self.assertFalse((self.tmp / "evil.txt").exists())


class UpdateSelf(Base):
    def copy_of_skill_eval_lite(self, where: Path) -> Path:
        where.mkdir(parents=True)
        for f in ("run_ab.py", "VERSION", "README.md"):
            shutil.copy2(REPO / f, where / f)
        return where

    def test_a_zip_copy_keeps_experiments_and_runs(self):
        sel = self.copy_of_skill_eval_lite(self.ws / "skill-eval-lite")
        mine = {"experiments/board-memo/experiment.toml": "frozen", "runs/board-memo/bundle.json": "{}",
                ".claude/settings.local.json": '{"permissions": {"additionalDirectories": [".."]}}'}
        for k, v in mine.items():
            (sel / k).parent.mkdir(parents=True, exist_ok=True)
            (sel / k).write_text(v)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("skill-eval-lite-main/run_ab.py", (REPO / "run_ab.py").read_text())
            z.writestr("skill-eval-lite-main/VERSION", "9.9.9\n")
            z.writestr("skill-eval-lite-main/README.md", "The new README.")
            z.writestr("skill-eval-lite-main/NEW.md", "A new file.")
            z.writestr("skill-eval-lite-main/experiments/planted.txt", "no")
            z.writestr("skill-eval-lite-main/.claude/settings.local.json", "{}")
        (self.site.root / "sel.zip").write_bytes(buf.getvalue())
        env = {**self.env, "SKILL_EVAL_LITE_ZIP_URL": self.site.url + "sel.zip"}
        r = subprocess.run([sys.executable, str(sel / "run_ab.py"), "update", "--self"], capture_output=True, text=True,
                           env={**os.environ, **env}, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"Skill Eval Lite {VERSION} -> 9.9.9: replaced 2 files and added 1", r.stdout)
        self.assertEqual((sel / "VERSION").read_text(), "9.9.9\n")
        self.assertEqual((sel / "README.md").read_text(), "The new README.")
        self.assertTrue((sel / "NEW.md").is_file())
        self.assertFalse((sel / "experiments/planted.txt").exists())
        for k, v in mine.items():
            self.assertEqual((sel / k).read_text(), v, k)
        self.assertEqual((self.tmp / "state" / f"before-update-{VERSION}" / "VERSION").read_text().strip(), VERSION)

    def test_a_git_copy_pulls(self):
        if not shutil.which("git"):
            self.skipTest("no git")
        git = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.org", "-c", "init.defaultBranch=main"]
        origin = self.copy_of_skill_eval_lite(self.tmp / "origin")
        subprocess.run([*git, "init", "-q"], cwd=origin, check=True)
        subprocess.run([*git, "add", "."], cwd=origin, check=True)
        subprocess.run([*git, "commit", "-qm", "0.1"], cwd=origin, check=True)
        clone = self.ws / "skill-eval-lite"
        subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
        (origin / "VERSION").write_text("9.9.9\n")
        subprocess.run([*git, "commit", "-qam", "9.9.9"], cwd=origin, check=True)
        env = {**os.environ, **self.env}
        (clone / "README.md").write_text("Changed by hand.")
        r = subprocess.run([sys.executable, str(clone / "run_ab.py"), "update", "--self"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 2)
        self.assertIn("own files have changes", r.stderr)
        subprocess.run(["git", "checkout", "--", "README.md"], cwd=clone, check=True)
        (clone / "experiments").mkdir()
        (clone / "experiments" / "mine.toml").write_text("mine")
        r = subprocess.run([sys.executable, str(clone / "run_ab.py"), "update", "--self"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Skill Eval Lite is now 9.9.9", r.stdout)
        self.assertEqual((clone / "experiments" / "mine.toml").read_text(), "mine")


if __name__ == "__main__":
    unittest.main()
