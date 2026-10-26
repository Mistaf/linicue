import unittest
from pathlib import Path

from linicue import nxp
from linicue.daemon import Daemon
from linicue.dpi import Dpi, Preset, load_presets, manual_preset
from linicue.keys import DPI_DOWN, DPI_UP, SNIPER
from linicue.profile import Binding, ExecHints, KeyRemapAction, RepeatOptions
from linicue.switcher import RuleSet
from tests.test_daemon import FakeControl, Rec, profile

LIB = Path(__file__).resolve().parent.parent / "icue-appdata" / "dpi" / "dpi.cuelibrary"
RED, GREEN, BLUE, YELLOW = (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)


def preset(default=2):
    return Preset({1: (1500, 1500, None), 2: (2400, 2400, GREEN), 3: (3000, 3000, BLUE)}, (400, 400, YELLOW), default)


class PacketTests(unittest.TestCase):
    def test_dpi_packets(self):
        self.assertEqual(nxp.dpi_stage(1, 800)[:9], bytes([7, 0x13, 0xD1, 0, 0, 0x20, 0x03, 0x20, 0x03]))
        self.assertEqual(nxp.dpi_stage(0, 400, 800)[:9], bytes([7, 0x13, 0xD0, 0, 1, 0x90, 0x01, 0x20, 0x03]))  # x != y sets the flag
        self.assertEqual(nxp.dpi_mask({0, 1, 2})[:5], bytes([7, 0x13, 5, 0, 0b111]))
        self.assertEqual(nxp.dpi_select(2)[:5], bytes([7, 0x13, 2, 0, 2]))
        for bad in ((6, 800), (1, 0), (1, 70000)):
            with self.assertRaises(ValueError):
                nxp.dpi_stage(*bad)


class DpiTests(unittest.TestCase):
    def make(self, **kw):
        sent = []
        return Dpi(sent.append, preset(**kw)), sent

    def test_setup_writes_sniper_and_stages_then_mask_then_selects_default(self):
        d, sent = self.make()
        d.setup()
        self.assertEqual([p[2] for p in sent], [0xD0, 0xD1, 0xD2, 0xD3, 5, 2])
        self.assertEqual(sent[0][5:7], bytes([0x90, 0x01]))  # sniper = 400
        self.assertEqual(sent[4][4], 0b1111)
        self.assertEqual(sent[5][4], 2)

    def test_sniper_holds_stage_zero_and_returns(self):
        d, sent = self.make()
        d.handle(SNIPER, True)
        self.assertEqual(d.color(), YELLOW)
        d.handle(SNIPER, False)
        self.assertEqual([p[4] for p in sent], [0, 2])
        self.assertEqual(d.color(), GREEN)

    def test_up_down_clamp_and_ignore_release(self):
        d, sent = self.make(default=3)
        d.handle(DPI_UP, True)
        d.handle(DPI_UP, False)
        d.handle(DPI_DOWN, True)
        self.assertEqual([p[4] for p in sent], [3, 2])

    def test_cycle_wraps_over_enabled_stages_only(self):
        d, sent = self.make(default=3)
        d.cycle()
        d.cycle()
        self.assertEqual([p[4] for p in sent], [1, 2])

    def test_release_drops_a_held_sniper(self):
        d, sent = self.make()
        d.handle(SNIPER, True)
        d.release()
        d.release()
        self.assertEqual([p[4] for p in sent], [0, 2])

    def test_no_sniper_stage_does_nothing_and_unconfigured_is_inert(self):
        sent = []
        d = Dpi(sent.append, Preset({1: (800, 800, None)}, None, 1))
        d.handle(SNIPER, True)
        Dpi(sent.append).cycle()
        self.assertEqual(sent, [])
        with self.assertRaises(ValueError):
            d.configure(Preset())

    def test_manual_preset(self):
        p = manual_preset([800, 1600], 400, 2, [YELLOW, RED, GREEN])
        self.assertEqual((p.stages[2], p.sniper, p.default), ((1600, 1600, GREEN), (400, 400, YELLOW), 2))


@unittest.skipUnless(LIB.is_file(), "icue-appdata not present")
class RealLibraryTests(unittest.TestCase):
    def test_library_parses_into_usable_presets(self):
        presets = load_presets(LIB)
        self.assertTrue(presets)
        for p in presets.values():
            self.assertTrue(p.stages and set(p.stages) <= {1, 2, 3, 4, 5})
            self.assertIn(p.default, range(1, 6))
            for x, y, colour in [*p.stages.values(), *([p.sniper] if p.sniper else [])]:
                self.assertTrue(x > 0 and y > 0 and len(colour) == 3 and all(0 <= c <= 255 for c in colour))
        self.assertEqual(load_presets(LIB, model="NO SUCH MOUSE"), {})


def remap(key):
    return KeyRemapAction(type="KeyRemapAction", name="a", id="", repeat=RepeatOptions(), hints=ExecHints("OnBoth"), raw={}, key=key)


class DaemonDpiTests(unittest.TestCase):
    def make(self, bindings=()):
        ctl = FakeControl()
        prof = profile("Default", initial=True, bindings=bindings)
        dpi = Dpi(ctl.send)
        presets = {prof.mouse.dpi_ref: preset()}
        return Daemon([prof], RuleSet([prof]), Rec(), ctl, log=lambda m: None, dpi=dpi, presets=presets), ctl

    def selects(self, ctl):
        return [p[4] for p in ctl.sent if p[1] == 0x13 and p[2] == 2]

    def test_profile_selects_its_preset_and_sniper_works(self):
        d, ctl = self.make([Binding("MouseG5", remap("Mouse8"))])
        self.assertEqual(d.dpi.preset.default, 2)
        d.on_button("MouseG5", True)
        d.on_button("MouseG5", False)
        self.assertEqual(self.selects(ctl), [0, 2])

    def test_unbound_dpi_button_cycles_but_a_bound_one_does_not(self):
        d, ctl = self.make()
        d.on_button("MouseDpiToggle", True)
        d.on_button("MouseDpiToggle", False)
        self.assertEqual(self.selects(ctl), [3])
        d2, ctl2 = self.make([Binding("MouseDpiToggle", remap("F5"))])
        d2.on_button("MouseDpiToggle", True)
        self.assertEqual(self.selects(ctl2), [])

    def test_settle_delay_then_frames_and_keepalive(self):
        d, ctl = self.make()
        d.start()
        base = d.hold_until
        colour = lambda: len([p for p in ctl.sent if p[1] == 0x22])
        d.tick(base - 0.1)
        self.assertEqual(colour(), 0)
        d.tick(base + 0.01)
        d.tick(base + 0.5)
        self.assertEqual(colour(), 1)
        d.tick(base + 1.5)
        self.assertEqual(colour(), 2)

    def test_dpi_light_uses_stage_colour(self):
        d, ctl = self.make()
        d.tick(10.0)
        pkt = [p for p in ctl.sent if p[1] == 0x22][-1]
        zones = {pkt[4 + 4 * i]: tuple(pkt[5 + 4 * i:8 + 4 * i]) for i in range(pkt[2])}
        self.assertEqual(zones[3], GREEN)


if __name__ == "__main__":
    unittest.main()
