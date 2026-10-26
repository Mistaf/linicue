import re
import unittest
from pathlib import Path

from linicue.mouse import ButtonTracker, pressed_buttons

PROBE = Path(__file__).resolve().parent.parent / "probe-output.txt"


def rep(**bytes_at):
    r = bytearray(64)
    r[0] = 3
    for i, v in bytes_at.items():
        r[1 + int(i[1:])] = v
    return bytes(r)


class MouseTests(unittest.TestCase):
    def test_bit_layout(self):
        self.assertEqual(pressed_buttons(rep(p1=0x01)), {"MouseG1"})
        self.assertEqual(pressed_buttons(rep(p1=0x80)), {"MouseG8"})
        self.assertEqual(pressed_buttons(rep(p2=0x02)), {"MouseG10"})
        self.assertEqual(pressed_buttons(rep(p1=0x03)), {"MouseG1", "MouseG2"})

    def test_ignores_other_reports(self):
        self.assertEqual(pressed_buttons(bytes.fromhex("01000000000100000000")), set())

    def test_edges(self):
        t = ButtonTracker()
        self.assertEqual(t.update(rep(p1=0x01)), [("MouseG1", True)])
        self.assertEqual(t.update(rep(p1=0x01)), [])
        self.assertEqual(t.update(rep()), [("MouseG1", False)])

    @unittest.skipUnless(PROBE.is_file(), "no probe capture")
    def test_real_capture_gives_valid_balanced_button_events(self):
        t, seen = ButtonTracker(), []
        for line in PROBE.read_text().splitlines():
            m = re.match(r"hidraw0: (03[0-9a-f]+)$", line)
            if m:
                seen += t.update(bytes.fromhex(m.group(1)))
        names = {b for b, _ in seen}
        self.assertTrue(names)
        self.assertTrue(all(re.fullmatch(r"MouseG(1[0-2]|[1-9])|MouseDpiToggle|MouseProfileSwitch", n) for n in names), names)
        self.assertEqual(sum(p for _, p in seen), sum(not p for _, p in seen))  # every press has a release
        self.assertFalse(t.down)


if __name__ == "__main__":
    unittest.main()
