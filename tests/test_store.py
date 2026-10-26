import json
import tempfile
import unittest
from pathlib import Path

from linicue import store
from linicue.dpi import load_icue_presets
from linicue.lighting import render
from linicue.profile import Color, load_profiles

APPDATA = Path(__file__).resolve().parent.parent / "icue-appdata"


@unittest.skipUnless((APPDATA / "profiles").is_dir(), "icue-appdata not present")
class RealRoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = [p for p in load_profiles(APPDATA / "profiles") if not p.is_hardware]

    def test_every_profile_survives_a_json_round_trip_exactly(self):
        for p in self.profiles:
            d = store.profile_to_dict(p)
            again = store.profile_from_dict(json.loads(json.dumps(d, default=str)))
            self.assertEqual(store.profile_to_dict(again), d, p.name)

    def test_behaviour_is_unchanged_after_round_trip(self):
        for p in self.profiles:
            q = store.profile_from_dict(json.loads(json.dumps(store.profile_to_dict(p), default=str)))
            self.assertEqual(render(q.mouse.lighting, 777, 55), render(p.mouse.lighting, 777, 55), p.name)
            self.assertEqual([(b.button, type(b.action).__name__) for b in q.mouse.bindings],
                             [(b.button, type(b.action).__name__) for b in p.mouse.bindings], p.name)

    def test_import_writes_store_and_dpi(self):
        with tempfile.TemporaryDirectory() as d:
            n = store.import_icue(APPDATA / "profiles", Path(d))
            profiles, presets = store.load_store(Path(d))
        self.assertEqual((n, len(profiles)), (len(self.profiles), len(self.profiles)))
        self.assertTrue(presets)

    def test_dpi_presets_keep_disabled_stages(self):
        raw = load_icue_presets(APPDATA / "dpi" / "dpi.cuelibrary")
        self.assertTrue(raw)
        for preset in raw.values():  # all five stages are kept, each with an enabled flag, so the editor can switch them on
            self.assertEqual(set(preset["stages"]), {"1", "2", "3", "4", "5"})
            self.assertTrue(all(isinstance(s["enabled"], bool) for s in preset["stages"].values()))


class StoreTests(unittest.TestCase):
    def test_save_load_delete_and_stamp(self):
        from tests.test_daemon import profile
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = profile("A", "a.exe")
            self.assertEqual(store.stamp(root), 0.0)
            path = store.save_profile(p, root)
            self.assertTrue(path.is_file() and not list(root.rglob("*.tmp")))
            self.assertGreater(store.stamp(root), 0)
            self.assertEqual([x.name for x in store.load_store(root)[0]], ["A"])
            store.delete_profile(p, root)
            self.assertEqual(store.load_store(root)[0], [])

    def test_color_floats_survive(self):
        from linicue.profile import Effect
        e = store.effect_from_dict(store.effect_to_dict(Effect("GradientLighting", 1000, 10, [(0.25, Color(0.1, 0.2, 0.3))])))
        self.assertEqual(e.stops, [(0.25, Color(0.1, 0.2, 0.3))])


if __name__ == "__main__":
    unittest.main()
