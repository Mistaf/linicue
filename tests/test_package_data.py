import unittest
from pathlib import Path

from linicue import __version__
from linicue.install import DATA, Installer


class PackageDataTests(unittest.TestCase):
    def test_files_the_installer_needs_ship_with_the_package(self):
        for rel in ("udev/70-linicue.rules", "kwin/linicue-windowwatcher/metadata.json",
                    "kwin/linicue-windowwatcher/contents/code/main.js", "rules.example.toml"):
            self.assertTrue((DATA / rel).is_file(), rel)
        self.assertEqual(Installer().data, DATA)

    def test_pyproject_ships_that_data_and_names_the_command(self):
        text = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
        self.assertIn('linicue = ["data/**/*"]', text)
        self.assertIn('linicue = "linicue.__main__:main"', text)
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
