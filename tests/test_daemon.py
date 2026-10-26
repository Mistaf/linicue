import unittest

from linicue import evcodes as ev
from linicue import nxp
from linicue.daemon import Daemon
from linicue.profile import (Binding, Color, Effect, ExecHints, KeyRemapAction, LightingLayer, MouseSettings,
                             Profile, ProfileSwitchAction, RepeatOptions)
from linicue.switcher import RuleSet


class Rec:
    def __init__(self):
        self.log = []

    def key(self, code, down):
        self.log.append((code, down))

    def rel(self, code, value):
        pass


class FakeControl:
    def __init__(self):
        self.sent = []

    def send(self, pkt):
        self.sent.append(pkt)


def action(cls, **kw):
    return cls(type=cls.__name__, name="a", id="", repeat=RepeatOptions(), hints=ExecHints("OnBoth"), raw={}, **kw)


def static(rgb):
    return Effect("StaticLighting", 1000, 10, [(0, Color(*(c / 255 for c in rgb)))])


def profile(name, exe=None, initial=False, bindings=(), leds=("MouseFrontLed", "MouseLogoLed"), rgb=(10, 20, 30)):
    lay = LightingLayer("l", "id", leds, True, static(rgb))
    return Profile(f"{{{name}}}", name, [f"C:/x/{exe}"] if exe else [], MouseSettings(list(bindings), [lay]), is_initial=initial)


def make(*profiles, skip=frozenset()):
    sink, ctl = Rec(), FakeControl()
    return Daemon(list(profiles), RuleSet(list(profiles)), sink, ctl, skip, log=lambda m: None), sink, ctl


class DaemonTests(unittest.TestCase):
    def test_window_focus_switches_profile_and_unfocus_returns_to_default(self):
        d, _, _ = make(profile("Default", initial=True), profile("Discord", "Discord.exe"))
        self.assertEqual(d.profile.name, "Default")
        d.on_window("discord", "", "discord", "x", 0)
        self.assertEqual(d.profile.name, "Discord")
        d.on_window("firefox", "", "", "x", 0)
        self.assertEqual(d.profile.name, "Default")

    def test_button_runs_binding_and_profile_change_releases_held_key(self):
        a = profile("A", "a.exe", bindings=[Binding("MouseG1", action(KeyRemapAction, key="F5"))])
        d, sink, _ = make(profile("Default", initial=True), a)
        d.on_window("a", "", "", "", 0)
        d.on_button("MouseG1", True)
        self.assertEqual(sink.log, [(ev.KEY_F5, True)])
        d.on_window("firefox", "", "", "", 0)  # button still held while the profile changes
        self.assertEqual(sink.log[-1], (ev.KEY_F5, False))
        d.on_button("MouseUnbound", True)  # no binding: ignored

    def test_unknown_key_in_binding_does_not_crash(self):
        bad = profile("B", bindings=[Binding("MouseG1", action(KeyRemapAction, key="NoSuchKey"))], initial=True)
        d, _, _ = make(bad)
        d.on_button("MouseG1", True)

    def test_profile_switch_button_toggles_a_pair(self):
        f1, f2 = profile("F1", "g.exe"), profile("F2", "g.exe")
        sw = lambda tgt: action(ProfileSwitchAction, switch_type="Direct", target=tgt.id, targets=(), direction="Forward", loop=True)
        f1.mouse.bindings.append(Binding("MouseProfileSwitch", sw(f2)))
        f2.mouse.bindings.append(Binding("MouseProfileSwitch", sw(f1)))
        d, _, _ = make(profile("Default", initial=True), f1, f2)
        d.on_window("g", "", "", "", 0)
        self.assertEqual(d.profile.name, "F1")
        d.on_button("MouseProfileSwitch", True)
        self.assertEqual(d.profile.name, "F2")
        d.on_window("g", "", "", "title changed", 0)  # tied window event must not undo the manual choice
        self.assertEqual(d.profile.name, "F2")
        d.on_button("MouseProfileSwitch", True)
        self.assertEqual(d.profile.name, "F1")

    def test_lighting_frame_fills_unspecified_zones_black_and_skips_leds(self):
        d, _, ctl = make(profile("Default", initial=True, leds=("MouseFrontLed", "MouseLogoLed")), skip=frozenset({"MouseLogoLed"}))
        d.tick(100.0)
        pkt = ctl.sent[-1]
        self.assertEqual(pkt[:3], bytes([7, 0x22, 5]))
        zones = {pkt[4 + 4 * i]: tuple(pkt[5 + 4 * i:8 + 4 * i]) for i in range(5)}
        self.assertEqual(zones, {1: (10, 20, 30), 2: (0, 0, 0), 3: (0, 0, 0), 4: (0, 0, 0), 5: (0, 0, 0)})
        n = len(ctl.sent)
        d.tick(100.1)  # unchanged frame: nothing resent
        self.assertEqual(len(ctl.sent), n)

    def test_force_pins_a_profile_until_released(self):
        a, b = profile("A", "a.exe"), profile("B", "b.exe")
        d, _, _ = make(profile("Default", initial=True), a, b)
        self.assertFalse(d.force("{nope}"))
        self.assertTrue(d.force(b.id))
        d.on_window("a", "", "", "", 0)  # focus changes are ignored while pinned
        self.assertEqual(d.profile.name, "B")
        self.assertTrue(d.force(""))
        d.on_window("a", "", "", "", 0)
        self.assertEqual(d.profile.name, "A")

    def test_reload_keeps_the_profile_in_use_and_applies_edits(self):
        a = profile("A", "a.exe", rgb=(10, 0, 0))
        d, _, ctl = make(profile("Default", initial=True), a)
        d.on_window("a", "", "", "", 0)
        a2 = profile("A", "a.exe", rgb=(0, 99, 0))  # same id, edited lighting
        default = profile("Default", initial=True)
        d.reload([default, a2], RuleSet([default, a2]), {})
        self.assertEqual(d.profile.mouse.lighting[0].effect.stops[0][1].g, 99 / 255)
        d.tick(50.0)
        pkt = [p for p in ctl.sent if p[1] == 0x22][-1]
        self.assertEqual(tuple(pkt[5:8]), (0, 99, 0))

    def test_reload_falls_back_to_default_when_the_profile_was_deleted(self):
        a = profile("A", "a.exe")
        d, _, _ = make(profile("Default", initial=True), a)
        d.on_window("a", "", "", "", 0)
        default = profile("Default", initial=True)
        d.reload([default], RuleSet([default]), {})
        self.assertEqual(d.profile.name, "Default")

    def test_start_and_stop_hand_buttons_and_lighting_back(self):
        d, _, ctl = make(profile("Default", initial=True))
        d.start()
        d.stop()
        self.assertEqual(ctl.sent, [nxp.special_mode(True), nxp.angle_snapping(False, 5), nxp.special_mode(False), nxp.lighting_control(False)])


if __name__ == "__main__":
    unittest.main()
