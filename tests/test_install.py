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
        self.assertEqual(names, ["kpackagetool6", "kpackagetool6", "kwriteconfig6", "busctl", "systemctl", "systemctl", "systemctl"])
        self.assertIn("--install", r.ran[1])  # not installed yet
        self.assertEqual(r.ran[-1][-2:], ["restart", "linicue.service"])  # restart, so a re-install loads the new code
        r.tmp.cleanup()

    def test_example_config_is_installed_once_and_never_overwritten(self):
        r = Rig()
        rules = r.home / ".config/linicue/rules.toml"
        r.inst.install()
        self.assertIn("[steam]", rules.read_text())
        rules.write_text("# my edits\n")
        r.inst.install()
        self.assertEqual(rules.read_text(), "# my edits\n")
        r.tmp.cleanup()

    def test_reports_other_launchers_that_start_linicue_another_way(self):
        r = Rig()
        icons = r.home / ".local/share/plasma_icons"
        icons.mkdir(parents=True)
        (icons / "linicue.desktop").write_text("[Desktop Entry]\nExec=env PYTHONPATH=/old /old/.venv/bin/python -m linicue gui\n")
        (icons / "other.desktop").write_text("[Desktop Entry]\nExec=/usr/bin/true\n")  # unrelated: not reported
        auto = r.home / ".config/autostart"
        auto.mkdir(parents=True)
        (auto / "linicue.desktop").write_text("[Desktop Entry]\nExec=linicue gui\n")
        r.inst.install()
        found = {f.name for f, _ in r.inst.other_launchers()}
        self.assertEqual(found, {"linicue.desktop"})
        self.assertEqual(len(r.inst.other_launchers()), 2)  # the plasma_icons copy and the autostart entry
        self.assertTrue(any("/old/.venv/bin/python" in s for s in r.said))
        self.assertTrue(any("kbuildsycoca6" in s for s in r.said))
        r.tmp.cleanup()

    def test_menu_cache_is_rebuilt_when_the_tool_exists(self):
        r = Rig(tools=("systemctl", "kpackagetool6", "kbuildsycoca6"))
        r.inst.install()
        self.assertIn(["kbuildsycoca6", "--noincremental"], r.ran)
        r.ran.clear()
        r.inst.uninstall()
        self.assertIn(["kbuildsycoca6", "--noincremental"], r.ran)
        r.tmp.cleanup()

    def test_launcher_names_its_window_class_so_the_icon_matches(self):
        self.assertIn("StartupWMClass=linicue", desktop_text("/venv/bin/python", Path("/proj")))

    def test_tells_you_to_reload_the_kwin_script(self):
        r = Rig()
        r.inst.install()
        self.assertTrue(any("log out and in" in s for s in r.said))
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
