import asyncio
import os
import tempfile
import unittest

from linicue import evcodes as ev
from linicue import mouse, nxp
from linicue.daemon import Daemon
from linicue.link import MouseLink
from linicue.profile import Binding, ExecHints, KeyRemapAction, RepeatOptions
from linicue.switcher import RuleSet
from tests.test_daemon import Rec, profile


class Channel:
    instances = []

    def __init__(self, path):
        self.path, self.sent, self.closed, self.fail = path, [], False, False
        Channel.instances.append(self)

    def send(self, pkt):
        if self.fail:
            raise OSError(19, "No such device")
        self.sent.append(pkt)

    def close(self):
        self.closed = True


class Rig:
    """A daemon + link wired to fake device nodes that can appear and disappear."""

    def __init__(self, bindings=()):
        Channel.instances = []
        prof = profile("Default", initial=True, bindings=bindings)
        self.sink, self.logs = Rec(), []
        self.daemon = Daemon([prof], RuleSet([prof]), self.sink, None, log=self.logs.append)
        self.present = False
        self.watchers = []
        self.link = MouseLink(self.daemon, self.logs.append,
                              find_button=lambda: "/dev/hidraw0" if self.present else None,
                              find_control=lambda: "/dev/hidraw1" if self.present else None,
                              open_control=Channel, watch=self.fake_watch)

    def fake_watch(self, path, on_edge, on_error):
        self.watchers.append({"on_edge": on_edge, "on_error": on_error, "stopped": False})
        return lambda: self.watchers[-1].__setitem__("stopped", True)


def hold_key(key):
    return KeyRemapAction(type="KeyRemapAction", name="a", id="", repeat=RepeatOptions(), hints=ExecHints("OnBoth"), raw={}, key=key)


class LinkTests(unittest.TestCase):
    def test_waits_for_the_mouse_then_connects_and_initialises(self):
        r = Rig()
        r.link.step()
        r.link.step()
        self.assertFalse(r.link.up)
        self.assertEqual(sum("waiting" in m for m in r.logs), 1)  # said once, not every second
        r.present = True
        r.link.step()
        self.assertTrue(r.link.up)
        self.assertEqual(Channel.instances[0].sent[0], nxp.special_mode(True))
        self.assertIs(r.daemon.control, Channel.instances[0])

    def test_write_failure_disconnects_without_raising_then_reconnects_with_a_fresh_frame(self):
        r = Rig()
        r.present = True
        r.link.step()
        r.daemon.tick(r.daemon.hold_until + 0.1)
        first = Channel.instances[0]
        self.assertTrue(any(p[1] == 0x22 for p in first.sent))
        first.fail = True  # the mouse is unplugged: the next write raises
        r.daemon.tick(r.daemon.hold_until + 5)  # keepalive write fails
        self.assertFalse(r.link.up)
        self.assertIsNone(r.daemon.control)
        self.assertTrue(first.closed)
        r.daemon.tick(r.daemon.hold_until + 6)  # while disconnected: ignored, no error
        r.present = True  # replugged (possibly as a different hidraw node)
        r.link.step()
        second = Channel.instances[1]
        self.assertEqual(second.sent[0], nxp.special_mode(True))  # software mode re-entered
        r.daemon.tick(r.daemon.hold_until + 0.1)
        self.assertTrue(any(p[1] == 0x22 for p in second.sent))  # colours resent, not assumed

    def test_reader_error_disconnects_and_releases_held_keys(self):
        r = Rig([Binding("MouseG1", hold_key("F13"))])
        r.present = True
        r.link.step()
        r.daemon.on_button("MouseG1", True)
        self.assertEqual(r.sink.log[-1], (ev.KEY_F13, True))
        r.watchers[0]["on_error"](OSError(5, "I/O error"))
        self.assertFalse(r.link.up)
        self.assertEqual(r.sink.log[-1], (ev.KEY_F13, False))  # not left stuck down
        self.assertTrue(r.watchers[0]["stopped"])

    def test_resume_from_sleep_reinitialises(self):
        r = Rig()
        r.present = True
        r.link.step()
        r.link.resumed()
        self.assertFalse(r.link.up)
        r.link.step()
        self.assertEqual(len(Channel.instances), 2)
        self.assertEqual(Channel.instances[1].sent[0], nxp.special_mode(True))

    def test_node_present_but_unopenable_is_retried(self):
        r = Rig()
        r.present = True
        real_open = r.link.open_control
        calls = []

        def flaky(path):
            calls.append(path)
            if len(calls) == 1:
                raise PermissionError(13, "Permission denied")
            return real_open(path)
        r.link.open_control = flaky
        r.link.step()
        self.assertFalse(r.link.up)
        r.link.step()
        self.assertTrue(r.link.up)

    def test_dry_run_needs_no_control_channel(self):
        r = Rig()
        r.link.dry = r.daemon.dry = True
        r.link.find_control = lambda: None
        r.present = True
        r.link.step()
        self.assertTrue(r.link.up)
        self.assertEqual(Channel.instances, [])


class WatchTests(unittest.TestCase):
    def test_end_of_file_is_reported_once_and_stops_the_reader(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                fifo = os.path.join(d, "node")
                os.mkfifo(fifo)
                errors, edges = [], []
                w = os.open(fifo, os.O_RDWR)  # keep a writer open so opening the read end doesn't block
                stop = mouse.watch(fifo, lambda *e: edges.append(e), errors.append)
                report = bytearray(64)
                report[0], report[2] = 3, 0x01  # G1 down
                os.write(w, bytes(report))
                await asyncio.sleep(0.05)
                self.assertEqual(edges, [("MouseG1", True)])
                os.close(w)  # device gone: the read end sees end-of-file
                await asyncio.sleep(0.05)
                self.assertEqual(len(errors), 1)
                self.assertEqual(errors[0].errno, 19)
                stop()  # stopping again is harmless
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
