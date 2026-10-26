import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication, QMessageBox
    HAVE_QT = True
except ImportError:  # PySide6 (or its system libs) missing: GUI tests are skipped
    HAVE_QT = False

from linicue import store
from tests.test_daemon import profile

PRESET = {"name": "Default", "default": 2, "sniper": {"dpi": [400, 400], "enabled": True, "color": [255, 255, 0]},
          "stages": {str(i): {"dpi": [800 * i, 800 * i], "enabled": i <= 3, "color": [i * 10, 0, 0]} for i in range(1, 6)}}


@unittest.skipUnless(HAVE_QT, "PySide6 not available")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        a = profile("Alpha", "a.exe", initial=True)
        b = profile("Beta", "b.exe")
        a.mouse.dpi_ref = b.mouse.dpi_ref = "{preset}"
        for p in (a, b):
            store.save_profile(p, self.root)
        store.save_presets({"{preset}": PRESET}, self.root)
        from linicue.gui.window import MainWindow
        self.w = MainWindow(self.root)
        self.select("Alpha")

    def tearDown(self):
        self.w.saver.stop()
        self.tmp.cleanup()

    def select(self, name):
        for i in range(self.w.list.count()):
            if self.w.list.item(i).text().lstrip("★ ") == name:
                self.w.list.setCurrentRow(i)
        self.assertEqual(self.w.current.name, name)

    def saved(self, name):
        return next(p for p in store.load_store(self.root)[0] if p.name == name)

    # --- window -------------------------------------------------------------------------
    def test_lists_profiles_default_first_and_selects_into_tabs(self):
        self.assertEqual([self.w.list.item(i).text() for i in range(2)], ["★ Alpha", "Beta"])
        self.assertIs(self.w.links.profile, self.w.current)

    def test_startup_and_delete_select_the_default_profile(self):
        from linicue.gui.window import MainWindow
        self.select("Beta")
        self.w._make_default()  # Beta is now the default, Alpha is not
        fresh = MainWindow(self.root)
        self.assertEqual(fresh.current.name, "Beta")
        fresh.saver.stop()
        self.select("Alpha")
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        self.w._delete()
        self.assertEqual(self.w.current.name, "Beta")

    def test_links_edit_autosaves(self):
        self.w.links._add("otherclient")
        self.assertTrue(self.w.saver.isActive())
        self.w.save_now()
        self.assertIn("otherclient", self.saved("Alpha").linked_programs)
        self.w.links.list.setCurrentRow(self.w.links.list.count() - 1)
        self.w.links._remove()
        self.w.save_now()
        self.assertNotIn("otherclient", self.saved("Alpha").linked_programs)

    def test_duplicate_and_delete(self):
        self.w._duplicate()
        self.assertEqual(self.w.current.name, "Alpha copy")
        self.assertEqual({p.name for p in store.load_store(self.root)[0]}, {"Alpha", "Beta", "Alpha copy"})
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        self.w._delete()
        self.assertEqual({p.name for p in store.load_store(self.root)[0]}, {"Alpha", "Beta"})

    def test_make_default_moves_the_flag(self):
        self.select("Beta")
        self.w._make_default()
        self.assertEqual([p.name for p in store.load_store(self.root)[0] if p.is_initial], ["Beta"])

    def test_rename_via_list(self):
        self.w.list.item(1).setText("Gamma")
        self.w.save_now()
        self.assertIn("Gamma", [p.name for p in store.load_store(self.root)[0]])

    # --- lighting ------------------------------------------------------------------------
    def test_lighting_add_kind_change_and_save(self):
        t = self.w.lighting
        n = len(t.layers)
        t._add("GradientLighting")
        self.assertEqual((len(t.layers), t.layers[0].effect.kind), (n + 1, "GradientLighting"))  # new layer on top
        t.kind.setCurrentIndex(t.kind.findData("StaticLighting"))
        t._kind_edited(0)
        self.assertEqual((t.layers[0].effect.kind, len(t.layers[0].effect.stops)), ("StaticLighting", 1))
        t._stop_color(0, __import__("linicue.profile", fromlist=["Color"]).Color(1, 0, 0))
        t.brightness.setValue(4)
        self.w.save_now()
        eff = self.saved("Alpha").mouse.lighting[0].effect
        self.assertEqual((eff.kind, eff.brightness, eff.stops[0][1].r), ("StaticLighting", 4, 1))

    def test_lighting_leds_toggle_remove_and_reorder(self):
        t = self.w.lighting
        t.leds["MouseLogoLed"].setChecked(False)
        self.assertNotIn("MouseLogoLed", t.layers[0].leds)
        t._add("TemperatureLighting")
        t._move(1)
        self.assertEqual(t.layers[1].effect.kind, "TemperatureLighting")
        t.list.setCurrentRow(1)
        t._remove()
        self.assertEqual(len(t.layers), 1)

    def test_gradient_stops_add_move_remove(self):
        t = self.w.lighting
        t._add("GradientLighting")
        e = t.layers[0].effect
        t._add_stop()
        self.assertEqual(len(e.stops), 4)
        t._stop_pos(3, 70)
        self.assertEqual(e.stops[-1][0], 1.0)  # stops stay sorted by position
        t._del_stop(0)
        self.assertEqual(len(e.stops), 3)

    # --- DPI -------------------------------------------------------------------------------
    def test_dpi_edit_saves_presets_file(self):
        d = self.w.dpi
        d.rows["2"][2].setValue(2600)
        d.rows["4"][1].setChecked(True)
        d.default.setCurrentIndex(2)
        d._default_edited(2)
        self.w.save_now()
        raw = store.load_raw_presets(self.root)["{preset}"]
        self.assertEqual((raw["stages"]["2"]["dpi"], raw["stages"]["4"]["enabled"], raw["default"]), ([2600, 2600], True, 3))

    def test_dpi_new_preset_is_assigned_to_the_profile(self):
        self.w.dpi._new_preset()
        self.w.save_now()
        self.assertEqual(len(store.load_raw_presets(self.root)), 2)
        self.assertNotEqual(self.saved("Alpha").mouse.dpi_ref, "{preset}")

    # --- buttons ------------------------------------------------------------------------------
    def make_dialog(self, current=None):
        from linicue.gui.buttons_tab import ActionDialog
        return ActionDialog("G1", current, self.w.profiles)

    def test_key_combo_capture_and_action(self):
        from linicue.profile import KeyRemapAction
        dlg = self.make_dialog()
        dlg.kind.setCurrentIndex(1)
        dlg.capture._start()
        for k in ("LeftCtrl", "C"):
            dlg.capture.press(k)
        for k in ("C", "LeftCtrl"):
            dlg.capture.release(k)
        a = dlg.result_action()
        self.assertIsInstance(a, KeyRemapAction)
        self.assertEqual((a.keystroke, a.hints.when), (("LeftCtrl", "C"), "OnBoth"))
        self.w.buttons.set_action("MouseG1", a)
        self.assertEqual(self.w.buttons.table.item(0, 1).text(), "Key: Ctrl + C")
        self.w.save_now()
        self.assertEqual(self.saved("Alpha").mouse.binding("MouseG1").action.keystroke, ("LeftCtrl", "C"))

    def test_key_picker_offers_f13_to_f24_and_modifiers(self):
        from linicue import keys
        from linicue.gui.buttons_tab import KEY_GROUPS
        for names in KEY_GROUPS.values():
            for n in names:
                keys.resolve(n)  # every offered key is one the daemon can emit
        self.assertEqual([f"F{i}" for i in range(13, 25)], [n for n in KEY_GROUPS["Function keys (F1 – F24)"] if int(n[1:]) >= 13])
        dlg = self.make_dialog()
        dlg.kind.setCurrentIndex(dlg.KEY)
        picker = dlg.picker
        picker.key.setCurrentIndex(picker.key.findData("F20"))
        picker.mods["LeftCtrl"].setChecked(True)
        picker.mods["LeftShift"].setChecked(True)
        picker._add()
        self.assertEqual(dlg.result_action().keystroke, ("LeftCtrl", "LeftShift", "F20"))
        self.assertEqual(dlg.capture.text(), "Ctrl + Shift + F20")
        self.assertFalse(any(cb.isChecked() for cb in picker.mods.values()))  # modifiers are one-shot

    def test_several_keys_at_once_remove_last_and_clear(self):
        dlg = self.make_dialog()
        dlg.kind.setCurrentIndex(dlg.KEY)
        for name in ("F13", "F14", "F13"):  # the repeated F13 is not added twice
            dlg.picker.group.setCurrentIndex(0)
            dlg.picker.key.setCurrentIndex(dlg.picker.key.findData(name))
            dlg.picker._add()
        self.assertEqual(dlg.result_action().keystroke, ("F13", "F14"))
        dlg.picker.removedLast.emit()
        self.assertEqual(dlg.result_action().keystroke, ("F13",))
        dlg.picker.cleared.emit()
        self.assertIsNone(dlg.result_action())

    def test_picking_a_modifier_key_does_not_duplicate_it(self):
        dlg = self.make_dialog()
        dlg.picker.group.setCurrentText("Modifiers")
        dlg.picker.key.setCurrentIndex(dlg.picker.key.findData("LeftCtrl"))
        dlg.picker.mods["LeftCtrl"].setChecked(True)
        self.assertEqual(dlg.picker.combo(), ["LeftCtrl"])

    def pick(self, dlg, group, key):
        dlg.kind.setCurrentIndex(dlg.KEY)
        dlg.picker.group.setCurrentText(group)
        dlg.picker.key.setCurrentIndex(dlg.picker.key.findData(key))
        dlg.picker._add()

    def test_media_keys_are_key_actions_that_tap_by_default(self):
        dlg = self.make_dialog()
        self.assertTrue(dlg.hold.isChecked())
        self.pick(dlg, "Media", "PlayPause")
        a = dlg.result_action()
        self.assertEqual((a.keystroke, a.hints.when), (("PlayPause",), "OnPress"))  # tapped: holding would auto-repeat it
        self.assertFalse(dlg.hold.isChecked())

    def test_existing_media_action_opens_as_a_key(self):
        from linicue.gui.buttons_tab import make_action
        from linicue.profile import MediaAction
        dlg = self.make_dialog(make_action(MediaAction, "MediaAction", "Media", media="NextTrack"))
        self.assertEqual((dlg.kind.currentIndex(), dlg.capture.combo), (dlg.KEY, ["ScanNextTrack"]))
        self.assertEqual(dlg.result_action().keystroke, ("ScanNextTrack",))

    def test_dpi_and_profile_switch_actions(self):
        dlg = self.make_dialog()
        dlg.kind.setCurrentIndex(dlg.DPI)
        self.assertEqual(dlg.result_action().key, "Mouse8")  # Sniper
        dlg.kind.setCurrentIndex(dlg.SWITCH)
        dlg.target.setCurrentIndex(dlg.target.findText("Beta"))
        a = dlg.result_action()
        beta = next(p for p in self.w.profiles if p.name == "Beta")
        self.assertEqual((a.type, a.target), ("ProfileSwitchingAction", beta.id))

    def test_clear_removes_binding(self):
        from linicue.gui.buttons_tab import describe
        dlg = self.make_dialog()
        self.pick(dlg, "Media", "PlayPause")
        self.w.buttons.set_action("MouseG2", dlg.result_action())
        self.assertEqual(describe(self.w.current.mouse.binding("MouseG2").action), "Key: Play / Pause")
        self.w.buttons.set_action("MouseG2", None)
        self.assertIsNone(self.w.current.mouse.binding("MouseG2"))

    def test_macro_recording_builds_events_with_delays(self):
        from linicue.gui.buttons_tab import ActionDialog
        dlg = self.make_dialog()
        dlg.kind.setCurrentIndex(dlg.MACRO)
        ed = dlg.macro_editor
        for name, down, t in (("A", True, 10.0), ("A", False, 10.12), ("B", True, 10.5)):
            ed.record_event(name, down, now=t)
        kinds = [(e.kind, e.pressed if e.kind == "key" else e.delay_ms) for e in dlg.macro.events]
        self.assertEqual(kinds, [("key", True), ("delay", 120), ("key", False), ("delay", 380), ("key", True)])
        ed.mode.setCurrentIndex(1)  # repeat while held
        a = dlg.result_action()
        self.assertEqual((a.hints.when, a.repeat.mode, len(a.events)), ("WhilePressed", "RepeatConstantly", 5))

    def test_macro_event_editing(self):
        dlg = self.make_dialog()
        dlg.kind.setCurrentIndex(dlg.MACRO)
        ed = dlg.macro_editor
        ed._add_tap("Q")
        self.assertEqual(len(dlg.macro.events), 3)
        ed.table.selectRow(1)
        ed._delete()
        self.assertEqual(len(dlg.macro.events), 2)
        ed._clear()
        self.assertIsNone(dlg.result_action())  # an empty macro is not an action

    def test_scancode_to_ikue_name(self):
        from linicue.gui.buttons_tab import KeyStream
        self.assertEqual(KeyStream.name_for(30 + 8), "A")  # KEY_A = 30, Qt scancode = evdev + 8
        self.assertEqual(KeyStream.name_for(43 + 8), "Backslash")
        self.assertIsNone(KeyStream.name_for(0))

    def test_existing_actions_round_trip_through_the_dialog(self):
        from linicue.gui.buttons_tab import describe
        for p in store.load_store(self.root)[0]:
            for b in p.mouse.bindings:
                self.assertTrue(describe(b.action))


if __name__ == "__main__":
    unittest.main()
