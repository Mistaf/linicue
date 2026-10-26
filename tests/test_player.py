import asyncio
import unittest

from linicue import evcodes as ev
from linicue.player import Player
from linicue.profile import (ExecHints, KeyRemapAction, MacroAction, MacroEvent, MediaAction, RepeatOptions,
                             ProfileSwitchAction, TextAction)


class Rec:
    def __init__(self):
        self.log = []

    def key(self, code, down):
        self.log.append(("k", code, down))

    def rel(self, code, value):
        self.log.append(("r", code, value))


def common(when="OnPress", restart=False, repeat="NoRepeat", **rep):
    return dict(type="", name="t", id="", raw={}, hints=ExecHints(when, False, restart),
                repeat=RepeatOptions(mode=repeat, **rep))


def key(k, down):
    return MacroEvent("key", (k,), pressed=down)


def run(coro_fn):
    """Run a scenario with a virtual clock: sleep(0) yields, so tasks progress deterministically."""
    async def main():
        rec = Rec()
        async def fake_sleep(s):
            await asyncio.sleep(0)
        p = Player(rec, sleep=fake_sleep)
        await coro_fn(p, rec)
        return rec.log
    return asyncio.run(main())


async def settle(n=20):
    for _ in range(n):
        await asyncio.sleep(0)


class RemapTests(unittest.TestCase):
    def test_onboth_holds_key_for_button_hold(self):
        a = KeyRemapAction(**common("OnBoth"), key="F5")

        async def s(p, rec):
            p.button("G1", a, True)
            self.assertEqual(rec.log, [("k", ev.KEY_F5, True)])
            p.button("G1", a, False)
        self.assertEqual(run(s)[-1], ("k", ev.KEY_F5, False))

    def test_combo_releases_in_reverse(self):
        a = KeyRemapAction(**common("OnBoth"), keystroke=("LeftCtrl", "C"))

        async def s(p, rec):
            p.button("G1", a, True)
            p.button("G1", a, False)
        self.assertEqual(run(s), [("k", ev.KEY_LEFTCTRL, True), ("k", ev.KEY_C, True),
                                  ("k", ev.KEY_C, False), ("k", ev.KEY_LEFTCTRL, False)])

    def test_tilt_is_a_wheel_step(self):
        a = KeyRemapAction(**common("OnBoth"), key="Mouse_TiltLeft")

        async def s(p, rec):
            p.button("G1", a, True)
            p.button("G1", a, False)
        self.assertEqual(run(s), [("r", ev.REL_HWHEEL, -1)])


class MacroTests(unittest.TestCase):
    MACRO = [key("A", True), MacroEvent("delay", delay_ms=5), key("A", False)]

    def test_runs_once_in_order(self):
        a = MacroAction(**common(), events=self.MACRO)

        async def s(p, rec):
            p.button("G1", a, True)
            await settle()
        self.assertEqual(run(s), [("k", ev.KEY_A, True), ("k", ev.KEY_A, False)])

    def test_cancel_mid_macro_releases_held_key(self):
        a = MacroAction(**common(restart=True), events=[key("A", True), MacroEvent("delay", delay_ms=5), key("A", False)])

        async def s(p, rec):
            p.button("G1", a, True)
            await asyncio.sleep(0)  # A is down, macro is inside the delay
            p.release_all()
            await settle()
        log = run(s)
        self.assertEqual(log[0], ("k", ev.KEY_A, True))
        self.assertEqual(log[-1], ("k", ev.KEY_A, False))
        self.assertEqual(sum(1 for e in log if e == ("k", ev.KEY_A, False)), 1)

    def test_while_pressed_loops_until_release(self):
        a = MacroAction(**common("WhilePressed", repeat="RepeatConstantly"), events=[key("A", True), key("A", False)])

        async def s(p, rec):
            p.button("G1", a, True)
            await settle(10)
            p.button("G1", a, False)
            await settle()
            n = len(rec.log)
            await settle(10)
            self.assertEqual(len(rec.log), n)  # stopped
            self.assertGreater(n, 2)  # looped
        run(s)

    def test_toggle_starts_then_stops(self):
        a = MacroAction(**common("Toggle", repeat="RepeatConstantly"), events=[key("A", True), key("A", False)])

        async def s(p, rec):
            p.button("G1", a, True)
            p.button("G1", a, False)  # release does nothing for Toggle
            await settle(10)
            n = len(rec.log)
            self.assertGreater(n, 2)
            p.button("G1", a, True)
            await settle()
            m = len(rec.log)
            await settle(10)
            self.assertEqual(len(rec.log), m)
        run(s)


class OneShotTests(unittest.TestCase):
    def test_media_tap_and_profile_switch(self):
        switched = []

        async def s(p, rec):
            p.on_switch = switched.append
            p.button("G6", MediaAction(**common(), media="NextTrack"), True)
            p.button("G6", MediaAction(**common(), media="NextTrack"), False)  # release: no repeat
            sw = ProfileSwitchAction(**common(), target="{x}")
            p.button("P", sw, True)
        log = run(s)
        self.assertEqual(log, [("k", ev.KEY_NEXTSONG, True), ("k", ev.KEY_NEXTSONG, False)])
        self.assertEqual(len(switched), 1)

    def test_text_types_with_shift_for_capitals(self):
        async def s(p, rec):
            p.button("G1", TextAction(**common(), text="Hi"), True)
            await settle()
        log = run(s)
        self.assertEqual(log[0], ("k", ev.KEY_LEFTSHIFT, True))
        self.assertIn(("k", ev.KEY_H, True), log)
        self.assertIn(("k", ev.KEY_I, True), log)
        self.assertEqual(log.count(("k", ev.KEY_LEFTSHIFT, True)), 1)  # not shifted for lower-case "i"


if __name__ == "__main__":
    unittest.main()
