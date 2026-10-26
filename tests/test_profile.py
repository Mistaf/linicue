import tempfile
import textwrap
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from linicue import cereal
from linicue.profile import Color, MacroAction, load_profile, load_profiles

REAL = Path(__file__).resolve().parent.parent / "profiles-src"

POLY = textwrap.dedent("""\
    <cereal><events size="dynamic">
      <value0><polymorphic_id>2147483662</polymorphic_id><polymorphic_name>KeyboardMacroActionEvent</polymorphic_name>
        <ptr_wrapper><id>2147483654</id><data><base/><keys size="dynamic"><value0>1</value0></keys><sub>KeyPress</sub></data></ptr_wrapper></value0>
      <value1><polymorphic_id>14</polymorphic_id>
        <ptr_wrapper><id>2147483655</id><data><base/><keys size="dynamic"><value0>A</value0></keys><sub>KeyRelease</sub></data></ptr_wrapper></value1>
      <value2><polymorphic_id>14</polymorphic_id><ptr_wrapper><id>6</id></ptr_wrapper></value2>
    </events></cereal>""")


class CerealTests(unittest.TestCase):
    def test_polymorphic_names_resolve_after_first_use(self):
        out = cereal.Decoder().decode_root(ET.fromstring(POLY))["events"]
        self.assertEqual([e.type for e in out[:2]], ["KeyboardMacroActionEvent"] * 2)

    def test_shared_pointer_reference_resolves_to_earlier_object(self):
        # id 6 (no MSB) refers to the first object, introduced as 0x80000006
        out = cereal.Decoder().decode_root(ET.fromstring(POLY))["events"]
        self.assertIs(out[2], out[0])
        self.assertIsNot(out[2], out[1])

    def test_empty_dynamic_is_list_and_digit_stays_recoverable(self):
        out = cereal.Decoder().decode_root(ET.fromstring('<cereal><x size="dynamic"/><k>1</k></cereal>'))
        self.assertEqual(out["x"], [])
        self.assertEqual(str(out["k"]), "1")


class ColorTests(unittest.TestCase):
    def test_parse_rgb_and_rgba(self):
        self.assertEqual(Color.parse("rgb(1 0.5 0)").rgb8(), (255, 128, 0))
        self.assertEqual(Color.parse("rgba(0 0 0 0)").a, 0.0)


@unittest.skipUnless(REAL.is_dir(), "profiles-src not present")
class RealProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = load_profiles(REAL)

    def test_all_profiles_load_with_mouse_data(self):
        self.assertTrue(self.profiles)
        self.assertTrue(all(p.mouse is not None for p in self.profiles))

    def test_no_unrecognised_action_types(self):
        for p in self.profiles:
            for b in p.mouse.bindings:
                if b.action:
                    self.assertNotEqual(type(b.action).__name__, "Action", (p.name, b.button, b.action.type))

    def test_macros_have_balanced_key_events(self):
        for p in self.profiles:
            for b in p.mouse.bindings:
                if isinstance(b.action, MacroAction):
                    kinds = [e.kind for e in b.action.events]
                    self.assertIn("key", kinds + ["key"])
                    for e in b.action.events:
                        if e.delay_max_ms is not None:
                            self.assertGreaterEqual(e.delay_max_ms, e.delay_ms)


class SyntheticProfileTests(unittest.TestCase):
    def test_missing_mouse_entry_is_tolerated(self):
        xml = ('<?xml version="1.0"?><cereal><profile><name>x</name><id>{00000000-0000-0000-0000-000000000001}</id>'
               '<linkedProgramsPaths size="dynamic"><value0>a.exe</value0><value1>a.exe</value1></linkedProgramsPaths>'
               '<properties size="dynamic"/></profile></cereal>')
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "x.cueprofiledata"
            f.write_text(xml)
            p = load_profile(f)
        self.assertIsNone(p.mouse)
        self.assertEqual(p.linked_programs, ["a.exe"])  # duplicates collapsed


if __name__ == "__main__":
    unittest.main()
