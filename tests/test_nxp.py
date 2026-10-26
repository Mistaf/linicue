import tempfile
import unittest
from pathlib import Path

from linicue import nxp


class PacketTests(unittest.TestCase):
    def test_modes(self):
        self.assertEqual(nxp.special_mode(True)[:3], bytes([7, 4, 2]))
        self.assertEqual(nxp.special_mode(False)[:3], bytes([7, 4, 1]))
        self.assertEqual(nxp.lighting_control(True)[:5], bytes([7, 5, 2, 0, 3]))
        self.assertEqual(nxp.lighting_control(False)[:3], bytes([7, 5, 1]))
        self.assertTrue(all(len(p) == 64 for p in (nxp.special_mode(True), nxp.lighting_control(True), nxp.mouse_colors({1: (0, 0, 0)}))))

    def test_colour_packet_layout(self):
        p = nxp.mouse_colors({3: (1, 2, 4), 1: (255, 0, 0)})
        self.assertEqual(p[:4], bytes([7, 0x22, 2, 1]))
        self.assertEqual(p[4:12], bytes([1, 255, 0, 0, 3, 1, 2, 4]))  # sorted by zone, no colour scaling
        self.assertEqual(p[12:], bytes(52))

    def test_validation(self):
        for bad in ({}, {1: (256, 0, 0)}, {256: (0, 0, 0)}, {z: (0, 0, 0) for z in range(16)}):
            with self.assertRaises(ValueError):
                nxp.mouse_colors(bad)
        with self.assertRaises(ValueError):
            nxp.lighting_control(True, 4)


class NodeTests(unittest.TestCase):
    def test_finds_the_vendor_interface_by_descriptor(self):
        with tempfile.TemporaryDirectory() as d:
            for name, desc in (("hidraw0", bytes.fromhex("05010902")), ("hidraw1", bytes.fromhex("06c2ff0904"))):
                n = Path(d) / name / "device"
                n.mkdir(parents=True)
                (n / "uevent").write_text("HID_ID=0003:00001B1C:00001B8B\n")
                (n / "report_descriptor").write_bytes(desc)
            self.assertEqual(nxp.find_control_node(d), "/dev/hidraw1")
            self.assertIsNone(nxp.find_control_node(d, pid="ffff"))


class CliTests(unittest.TestCase):
    def test_dry_run_sends_nothing(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(nxp.lights_cli(["--zone", "3", "--color", "00ff00"]), 0)
        self.assertIn("dry run", buf.getvalue())


if __name__ == "__main__":
    unittest.main()


class VariantTests(unittest.TestCase):
    def test_variant_packets(self):
        setup, first, flag = nxp.VARIANTS["ckb"]
        self.assertEqual((setup[0][:3], first, flag), (bytes([7, 4, 2]), 1, 1))
        setup, first, flag = nxp.VARIANTS["openrgb"]
        self.assertEqual((setup[0][:5], first, flag), (bytes([7, 5, 2, 0, 1]), 0, 0))
        self.assertEqual(nxp.mouse_colors({0: (1, 2, 3)}, 0)[:8], bytes([7, 0x22, 1, 0, 0, 1, 2, 3]))
