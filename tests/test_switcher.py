import tempfile
import unittest
from pathlib import Path

from linicue.profile import Profile
from linicue.steam import SteamLibrary, installdir_from_path, parse_vdf
from linicue.switcher import (Overrides, RuleSet, Switcher, WindowInfo, inspect_process, load_overrides,
                              window_from_event)

REAL = Path(__file__).resolve().parent.parent / "profiles-src"


def prof(name, *paths, initial=False):
    return Profile(f"{{{name}}}", name, list(paths), None, is_initial=initial)


PROFILES = [
    prof("Default", initial=True),
    prof("Discord", "C:/Users/x/AppData/Local/Discord/app-1.0/Discord.exe"),
    prof("Rust", "D:/Games/steamapps/common/Rust/Rust.exe"),
    prof("JavaApp1", "C:/Java/bin/javaw.exe"),
    prof("JavaApp2", "C:/Java/bin/javaw.exe"),
]


class SteamTests(unittest.TestCase):
    def test_vdf_nested_and_escaped(self):
        d = parse_vdf('"libraryfolders" { "0" { "path" "/mnt/a\\\\b" "apps" { "1" "2" } } }')
        self.assertEqual(d["libraryfolders"]["0"]["path"], "/mnt/a\\b")
        self.assertEqual(d["libraryfolders"]["0"]["apps"], {"1": "2"})

    def test_installdir_from_either_slash_style(self):
        self.assertEqual(installdir_from_path("D:/Games/steamapps/common/Foo Bar/bin/x.exe"), "Foo Bar")
        self.assertEqual(installdir_from_path("D:\\Games\\SteamApps\\Common\\Foo\\x.exe"), "Foo")
        self.assertIsNone(installdir_from_path("C:/Games/x.exe"))

    def test_discover_reads_manifests_from_extra_library(self):
        with tempfile.TemporaryDirectory() as d:
            apps = Path(d) / "steamapps"
            apps.mkdir()
            (apps / "appmanifest_252490.acf").write_text('"AppState" { "appid" "252490" "installdir" "Rust" }')
            lib = SteamLibrary.discover(roots=(), extra_libraries=(d,))
        self.assertEqual(lib.appid_for_installdir("rust"), 252490)


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.rs = RuleSet(PROFILES, SteamLibrary({"Rust": 252490}))

    def name(self, **kw):
        return self.rs.match(WindowInfo(**kw)).profile.name

    def test_native_app_by_class(self):
        self.assertEqual(self.name(resource_class="discord"), "Discord")

    def test_a_different_program_only_matches_once_it_is_added_as_an_app_link(self):
        self.assertEqual(self.name(resource_class="otherclient"), "Default")  # no automatic guessing between similar programs
        added = Profile("{Discord}", "Discord", [*PROFILES[1].linked_programs, "otherclient"], None)
        rs = RuleSet([PROFILES[0], added, *PROFILES[2:]])
        self.assertEqual(rs.match(WindowInfo(resource_class="otherclient")).profile.name, "Discord")
        self.assertEqual(rs.match(WindowInfo(resource_class="other", desktop_file="org.example.OtherClient")).profile.name, "Discord")

    def test_proton_game_by_steam_app_id(self):
        self.assertEqual(self.name(resource_class="steam_app_252490", steam_appid=252490), "Rust")

    def test_wine_exe_when_appid_unknown(self):
        self.assertEqual(self.name(resource_class="steam_app_1", wine_exes=("Rust.exe",)), "Rust")

    def test_unlinked_window_falls_back_to_default(self):
        self.assertEqual(self.name(resource_class="firefox"), "Default")

    def test_shared_exe_is_reported_ambiguous_and_tied(self):
        self.assertIn("javaw.exe", self.rs.ambiguities())
        m = self.rs.match(WindowInfo(resource_class="java", exe_names=("java",)))
        self.assertEqual(len(m.ties), 1)

    def test_title_override_disambiguates(self):
        rs = RuleSet(PROFILES, overrides=Overrides(titles={"JavaApp1": "^App one", "JavaApp2": "App two"}))
        w = lambda cap: WindowInfo(resource_class="java", exe_names=("java",), caption=cap)
        self.assertEqual(rs.match(w("App one 1.2")).profile.name, "JavaApp1")
        self.assertEqual(rs.match(w("App two")).profile.name, "JavaApp2")
        self.assertNotIn("javaw.exe", rs.ambiguities())

    def test_hardware_profiles_never_match(self):
        hw = Profile("{008b1b00-0001-0000-0000-000000000000}", "HW1", ["x/discord.exe"], None)
        self.assertEqual(RuleSet([hw, *PROFILES]).match(WindowInfo(resource_class="discord")).profile.name, "Discord")


class SwitcherTests(unittest.TestCase):
    def test_ignored_windows_do_not_switch_and_repeats_are_debounced(self):
        log = []
        sw = Switcher(RuleSet(PROFILES), lambda p, m: log.append(p.name))
        for cls in ("discord", "discord", "plasmashell", "firefox", "discord"):
            sw.on_window(WindowInfo(resource_class=cls))
        self.assertEqual(log, ["Discord", "Default", "Discord"])


class PairedProfileTests(unittest.TestCase):
    def test_tied_profile_in_use_is_kept(self):
        a, b = prof("A", "x/g.exe"), prof("B", "x/g.exe")
        log = []
        sw = Switcher(RuleSet([prof("Default", initial=True), a, b]), lambda p, m: log.append(p.name))
        win = WindowInfo(wine_exes=("g.exe",))
        sw.on_window(win)
        sw.current = b  # the profile-switch button chose B
        sw.on_window(win)
        self.assertIs(sw.current, b)
        self.assertEqual(log, ["A"])


class ProcTests(unittest.TestCase):
    def test_wine_process_details_from_fake_proc(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "42"
            p.mkdir()
            (p / "cmdline").write_bytes(b"Z:\\home\\u\\Games\\Rust\\Rust.exe\0-popupwindow\0")
            (p / "environ").write_bytes(b"HOME=/h\0SteamGameId=252490\0")
            info = inspect_process(42, d)
            w = window_from_event("steam_app_252490", "", "", "Rust", 42, d)
        self.assertEqual(info["wine_exes"], ("Rust.exe",))
        self.assertEqual(info["steam_appid"], 252490)
        self.assertEqual(w.steam_appid, 252490)

    def test_missing_process_does_not_raise(self):
        self.assertEqual(inspect_process(999999, "/nonexistent")["wine_exes"], ())


class OverridesTests(unittest.TestCase):
    def test_load_toml(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "rules.toml"
            f.write_text('[ignore]\nclasses=["Foo"]\n[[profile]]\nname="Discord"\nclass=["OtherClient"]\n'
                         '[[profile]]\nname="JavaApp1"\ntitle="^App"\n')
            o = load_overrides(f)
        self.assertIn("foo", o.ignored)
        self.assertEqual(o.classes["Discord"], {"otherclient"})
        self.assertEqual(o.titles["JavaApp1"], "^App")


@unittest.skipUnless(REAL.is_dir(), "profiles-src not present")
class RealRulesTests(unittest.TestCase):
    def test_every_linked_profile_matches_its_own_exe_as_a_wine_window(self):
        from linicue.profile import load_profiles
        profiles = load_profiles(REAL)
        rs = RuleSet(profiles)
        for r in rs.rules:
            for exe in r.exes:
                m = rs.match(WindowInfo(wine_exes=(exe,)))
                self.assertIn(r.profile, [m.profile, *m.ties], (r.profile.name, exe))


if __name__ == "__main__":
    unittest.main()
