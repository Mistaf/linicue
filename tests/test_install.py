import tempfile
import unittest
from pathlib import Path

from linicue.install import KWIN_ID, Installer, desktop_text, unit_text


class Rig:
    def __init__(self, dry=False, tools=("systemctl", "kpackagetool6"), kwin_listing=""):
        self.tmp = tempfile.TemporaryDirectory()
        self.home, self.said, self.ran = Path(self.tmp.name), [], []
        self.listing = kwin_listing
        self.inst = Installer(self.home, "/venv/bin/python", Path("/proj"), dry, self.runner, self.said.append,
                              lambda t: "/usr/bin/" + t if t in tools else None)

    def runner(self, cmd):
        self.ran.append(cmd)
        return 0, (self.listing if "--list" in cmd else "")


class InstallTests(unittest.TestCase):
    def test_unit_and_desktop_entry_use_the_given_python_and_project(self):
        u = unit_text("/venv/bin/python", Path("/proj"))
        self.assertIn("ExecStart=/venv/bin/python -m linicue run", u)
        self.assertIn("Environment=PYTHONPATH=/proj", u)
        self.assertIn("WantedBy=graphical-session.target", u)
        d = desktop_text("/venv/bin/python", Path("/proj"))
        self.assertIn("Exec=env PYTHONPATH=/proj /venv/bin/python -m linicue gui", d)

    def test_install_writes_files_and_runs_steps_in_order(self):
        r = Rig()
        r.inst.install()
        self.assertTrue(r.inst.unit.is_file() and r.inst.desktop.is_file())
        names = [c[0] for c in r.ran]
        self.assertEqual(names, ["kpackagetool6", "kpackagetool6", "kwriteconfig6", "busctl", "systemctl", "systemctl"])
        self.assertIn("--install", r.ran[1])  # not installed yet
        self.assertEqual(r.ran[-1][-2:], ["--now", "linicue.service"])
        r.tmp.cleanup()

    def test_upgrades_the_kwin_script_when_already_installed(self):
        r = Rig(kwin_listing=f"Listing service types: KWin/Script\n{KWIN_ID}\n")
        r.inst.install()
        self.assertIn("--upgrade", r.ran[1])
        r.tmp.cleanup()

    def test_dry_run_touches_nothing(self):
        r = Rig(dry=True)
        r.inst.install()
        self.assertFalse(r.inst.unit.exists() or r.inst.desktop.exists())
        self.assertEqual(r.ran, [])
        self.assertTrue(any("daemon-reload" in s for s in r.said))  # but it says what it would do
        r.tmp.cleanup()

    def test_missing_tools_are_skipped_with_a_message(self):
        r = Rig(tools=())
        r.inst.install()
        self.assertEqual(r.ran, [])
        self.assertTrue(any("kpackagetool6 not found" in s for s in r.said))
        self.assertTrue(any("systemctl not found" in s for s in r.said))
        r.tmp.cleanup()

    def test_uninstall_removes_files_and_disables(self):
        r = Rig()
        r.inst.install()
        r.ran.clear()
        r.inst.uninstall()
        self.assertFalse(r.inst.unit.exists() or r.inst.desktop.exists())
        self.assertIn(["systemctl", "--user", "disable", "--now", "linicue.service"], r.ran)
        self.assertIn(["kpackagetool6", "--type=KWin/Script", "--remove", KWIN_ID], r.ran)
        r.tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
