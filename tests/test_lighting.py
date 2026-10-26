import unittest
from pathlib import Path

from linicue.lighting import ZONES, effect_color, render
from linicue.profile import Color, Effect, LightingLayer, load_profiles

REAL = Path(__file__).resolve().parent.parent / "profiles-src"
ALL = tuple(ZONES)


def eff(kind, stops, duration=1000, brightness=10):
    return Effect(kind, duration, brightness, [(t, Color(*(c / 255 for c in rgb))) for t, rgb in stops])


def layer(effect, leds=ALL, enabled=True):
    return LightingLayer("l", "id", leds, enabled, effect)


class EffectTests(unittest.TestCase):
    def test_gradient_loops_and_interpolates(self):
        g = eff("GradientLighting", [(0, (0, 0, 0)), (0.5, (200, 100, 0)), (1, (0, 0, 0))], 1000)
        self.assertEqual(effect_color(g, 0, None), (0, 0, 0))
        self.assertEqual(effect_color(g, 500, None), (200, 100, 0))
        self.assertEqual(effect_color(g, 250, None), (100, 50, 0))
        self.assertEqual(effect_color(g, 1500, None), (200, 100, 0))  # second loop

    def test_temperature_maps_degrees_to_colour(self):
        t = eff("TemperatureLighting", [(0, (0, 255, 0)), (50, (0, 255, 0)), (80, (255, 0, 0))])
        self.assertEqual(effect_color(t, 0, 30), (0, 255, 0))
        self.assertEqual(effect_color(t, 0, 80), (255, 0, 0))
        self.assertEqual(effect_color(t, 0, None), (0, 255, 0))  # no sensor -> coolest colour

    def test_brightness_scales_and_unknown_kind_is_none(self):
        self.assertEqual(effect_color(eff("StaticLighting", [(0, (200, 100, 50))], brightness=5), 0, None), (100, 50, 25))
        self.assertIsNone(effect_color(eff("RainbowLighting", [(0, (0, 0, 0))]), 0, None))


class RenderTests(unittest.TestCase):
    def test_first_layer_is_on_top_and_unknown_leds_ignored(self):
        top = layer(eff("StaticLighting", [(0, (255, 0, 0))]), ("MouseFrontLed", "NotAnLed"))
        base = layer(eff("StaticLighting", [(0, (0, 0, 255))]))
        frame = render([top, base], 0)
        self.assertEqual(frame[1], (255, 0, 0))
        self.assertEqual(frame[2], (0, 0, 255))
        self.assertEqual(set(frame), {1, 2, 3, 4, 5})

    def test_disabled_layer_skipped(self):
        self.assertEqual(render([layer(eff("StaticLighting", [(0, (9, 9, 9))]), enabled=False)], 0), {})


@unittest.skipUnless(REAL.is_dir(), "profiles-src not present")
class RealTests(unittest.TestCase):
    def test_a_temperature_layer_on_top_decides_the_front_led(self):
        for p in (p for p in load_profiles(REAL) if not p.is_hardware):
            top = p.mouse.lighting[0] if p.mouse.lighting else None
            if top and top.enabled and top.effect and top.effect.kind == "TemperatureLighting" and "MouseFrontLed" in top.leds:
                self.assertEqual(render(p.mouse.lighting, 0, 30)[1], effect_color(top.effect, 0, 30), p.name)

    def test_every_profile_renders_valid_zone_colours(self):
        for p in (p for p in load_profiles(REAL) if not p.is_hardware):
            frame = render(p.mouse.lighting, 1234, 40)
            self.assertTrue(frame and set(frame) <= {1, 2, 3, 4, 5}, p.name)
            self.assertTrue(all(0 <= c <= 255 for rgb in frame.values() for c in rgb), p.name)


if __name__ == "__main__":
    unittest.main()
