import unittest
from pathlib import Path

from linicue import evcodes as ev
from linicue import keys
from linicue.profile import KeyRemapAction, MacroAction, MediaAction, load_profiles

REAL = Path(__file__).resolve().parent.parent / "profiles-src"


class KeyTests(unittest.TestCase):
    def test_known_names(self):
        self.assertEqual(keys.resolve("SlashAndQuestionMark").code, ev.KEY_SLASH)
        self.assertEqual(keys.resolve("LeftGui").code, ev.KEY_LEFTMETA)
        self.assertEqual(keys.resolve("4").code, ev.KEY_4)
        self.assertEqual(keys.resolve(4).code, ev.KEY_4)  # digit names decode as ints

    def test_buttons_and_tilt(self):
        self.assertTrue(keys.resolve("Mouse4").is_button)
        self.assertEqual([keys.resolve(f"Mouse{n}").code for n in (6, 7, 8)], [keys.DPI_UP, keys.DPI_DOWN, keys.SNIPER])
        self.assertEqual(keys.resolve("Mouse8").kind, "dpi")  # Sniper, not a button
        t = keys.resolve("Mouse_TiltLeft")
        self.assertEqual((t.kind, t.code, t.value), ("rel", ev.REL_HWHEEL, -1))

    def test_unknown_raises(self):
        with self.assertRaises(keys.UnknownKey):
            keys.resolve("NoSuchKey")


@unittest.skipUnless(REAL.is_dir(), "profiles-src not present")
class RealKeysTests(unittest.TestCase):
    def test_every_key_in_every_profile_resolves(self):
        for p in load_profiles(REAL):
            for b in p.mouse.bindings:
                a = b.action
                names = []
                if isinstance(a, KeyRemapAction):
                    names = ([a.key] if a.key else []) + list(a.keystroke)
                elif isinstance(a, MacroAction):
                    names = [k for e in a.events for k in e.keys]
                for n in names:
                    keys.resolve(n)
                if isinstance(a, MediaAction):
                    keys.resolve_media(a.media)


if __name__ == "__main__":
    unittest.main()
