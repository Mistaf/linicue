import unittest

try:
    from linicue.dbus_service import _Iface
    HAVE_DBUS = True
except ImportError:  # dbus-next not installed here
    HAVE_DBUS = False


@unittest.skipUnless(HAVE_DBUS, "dbus-next not installed")
class DbusInterfaceTests(unittest.TestCase):
    def test_methods_and_signatures(self):
        class D:
            def status(self):
                return "ok"

        methods = {m.name: (''.join(a.signature for a in m.in_args), ''.join(a.signature for a in m.out_args))
                   for m in _Iface(D(), lambda: None).introspect().methods}
        self.assertEqual(methods["WindowActivated"], ("ssssi", ""))
        self.assertEqual(methods["ForceProfile"], ("s", "b"))
        self.assertEqual(methods["Status"], ("", "s"))
        self.assertEqual(methods["Reload"], ("", ""))


if __name__ == "__main__":
    unittest.main()
