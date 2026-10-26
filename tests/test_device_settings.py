import json
import tempfile
import unittest
from pathlib import Path

from linicue import nxp, store
from linicue.daemon import Daemon
from linicue.switcher import RuleSet
from tests.test_daemon import FakeControl, Rec, profile


class PacketTests(unittest.TestCase):
    def test_polling_rate_uses_iCUEs_interval_table(self):
        self.assertEqual({hz: nxp.polling_rate(hz)[4] for hz in (125, 250, 500, 1000)}, {125: 8, 250: 4, 500: 2, 1000: 1})
        self.assertEqual(nxp.polling_rate(1000)[:5], bytes([7, 0x0A, 0, 0, 1]))
        with self.assertRaises(ValueError):
            nxp.polling_rate(750)

    def test_angle_snapping_packet(self):
        self.assertEqual(nxp.angle_snapping(True, 5)[:6], bytes([7, 0x13, 4, 0, 1, 5]))  # byte 3 = 0: live, not saved
        self.assertEqual(nxp.angle_snapping(False)[:6], bytes([7, 0x13, 4, 0, 0, 5]))
        with self.assertRaises(ValueError):
            nxp.angle_snapping(True, 300)


def rig(settings=None, state_path=None, dry=False, snap=False):
    ctl = FakeControl()
    a = profile("A", "a.exe", initial=True)
    b = profile("B", "b.exe")
    a.mouse.angle_snapping = snap
    d = Daemon([a, b], RuleSet([a, b]), Rec(), ctl, log=lambda m: None, dry=dry, settings=settings, state_path=state_path)
    return d, ctl, a, b


def of(ctl, field):
    return [p for p in ctl.sent if p[1] == field]


class DaemonSettingsTests(unittest.TestCase):
    def test_snapping_follows_the_profile_and_is_not_resent_when_unchanged(self):
        d, ctl, a, b = rig(snap=True)
        d.start()
        self.assertEqual([p[4] for p in of(ctl, 0x13)], [1])  # profile A: on
        d._apply(a, None)  # same setting again: nothing new
        self.assertEqual(len(of(ctl, 0x13)), 1)
        d.on_window("b", "", "", "", 0)  # profile B has it off
        self.assertEqual([p[4] for p in of(ctl, 0x13)], [1, 0])
        d.start()  # a reconnect forgets everything, so it is written again
        self.assertEqual(len(of(ctl, 0x13)), 3)

    def test_polling_rate_is_written_once_per_change_and_survives_a_restart(self):
        with tempfile.TemporaryDirectory() as t:
            state = Path(t) / "state.json"
            d, ctl, *_ = rig({"polling_rate_hz": 500}, state)
            d.start()
            self.assertEqual([p[4] for p in of(ctl, 0x0A)], [2])
            self.assertEqual(json.loads(state.read_text()), {"polling_rate_hz": 500})  # recorded
            d.start()  # the mouse re-enumerated and we reconnect: no second write, or it would loop forever
            self.assertEqual(len(of(ctl, 0x0A)), 1)
            d2, ctl2, *_ = rig({"polling_rate_hz": 500}, state)  # daemon restarted
            d2.start()
            self.assertEqual(of(ctl2, 0x0A), [])
            d2.reload(d2.profiles, d2.switcher.rules, d2.presets, {"polling_rate_hz": 1000})  # user picked another rate
            self.assertEqual([p[4] for p in of(ctl2, 0x0A)], [1])

    def test_unset_or_invalid_polling_rate_writes_nothing(self):
        for settings in ({}, {"polling_rate_hz": 750}, {"polling_rate_hz": None}):
            d, ctl, *_ = rig(settings)
            d.start()
            self.assertEqual(of(ctl, 0x0A), [], settings)

    def test_dry_run_does_not_record_state(self):
        with tempfile.TemporaryDirectory() as t:
            state = Path(t) / "state.json"
            d, ctl, *_ = rig({"polling_rate_hz": 250}, state, dry=True)
            d.start()
            self.assertFalse(state.exists())  # nothing was applied, so nothing is remembered


class StoreSettingsTests(unittest.TestCase):
    def test_round_trip_and_reload_trigger(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            self.assertEqual(store.load_settings(root), {})
            store.save_settings({"polling_rate_hz": 500}, root)
            self.assertEqual(store.load_settings(root), {"polling_rate_hz": 500})
            self.assertGreater(store.stamp(root), 0)  # saving settings makes the daemon reload


if __name__ == "__main__":
    unittest.main()
