import struct
import unittest

from chutku import icon
from chutku.tray import OPEN, STOP, TOGGLE, Tray, menu_items


class TrayTests(unittest.TestCase):
    def test_menu_reflects_state(self):
        paused = menu_items(True, True)
        self.assertEqual(paused[0][1], "Chutku: actions paused")
        self.assertIn((TOGGLE, "Resume actions", True), paused)
        self.assertIn((STOP, "Stop Chutku (emergency)", True), paused)
        ready = menu_items(False, False)
        self.assertIn((TOGGLE, "Pause actions", True), ready)
        self.assertEqual([i for i in ready if i and i[0] == STOP][0][2], False)  # no guard: stop is greyed
        self.assertIn((OPEN, "Open dashboard", True), ready)

    def test_icon_is_a_valid_multi_size_ico(self):
        data = icon.icon_bytes()
        reserved, kind, count = struct.unpack_from("<HHH", data)
        self.assertEqual((reserved, kind, count), (0, 1, 3))
        sizes = [data[6 + 16 * i] for i in range(count)]
        self.assertEqual(sizes, [16, 32, 48])
        self.assertEqual(icon.ensure_icon().read_bytes(), data)

    def test_real_tray_icon_starts_and_closes(self):
        tray = Tray(open_dashboard=lambda: None, toggle_pause=lambda: None, stop=lambda: None,
                    is_paused=lambda: False, guard_active=lambda: True)
        tray.start()
        self.assertTrue(tray.ready.wait(5))
        self.assertIsNone(tray.error, tray.error)
        self.assertTrue(tray.hwnd)
        tray.close()
        tray.join(5)
        self.assertFalse(tray.is_alive())


if __name__ == "__main__":
    unittest.main()
