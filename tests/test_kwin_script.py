import shutil
import subprocess
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "linicue" / "data" / "kwin" / "linicue-windowwatcher" / "contents" / "code" / "main.js"

# A minimal fake of KWin's scripting API: signals, windows that throw once destroyed, and callDBus.
HARNESS = r"""
const vm = require('vm'), fs = require('fs');
const calls = [];
const signal = () => { const hs = []; return { connect: f => hs.push(f), disconnect: f => { const i = hs.indexOf(f); if (i < 0) throw new Error('not connected'); hs.splice(i, 1); }, emit: (...a) => hs.slice().forEach(h => h(...a)) }; };
function makeWindow(cls, pid) {
  const w = { resourceClass: cls, resourceName: cls, desktopFileName: cls, caption: 'title ' + cls, pid, dead: false, captionChanged: signal() };
  const real = w.captionChanged.disconnect;
  w.captionChanged.disconnect = f => { if (w.dead) throw new Error('window destroyed'); return real(f); };
  return w;
}
const workspace = { activeWindow: null, windowActivated: signal(), windowRemoved: signal() };
const sandbox = { workspace, callDBus: (...a) => calls.push(a.slice(3, 8)) };
const a = makeWindow('first', 1), b = makeWindow('second', 2), c = makeWindow('third', 3);
workspace.activeWindow = a;
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), sandbox);
workspace.windowActivated.emit(b);
a.dead = true;                       // the window that was focused earlier is closed ...
b.dead = true;                       // ... and so is the current one, without a windowRemoved reaching us
workspace.windowActivated.emit(c);   // the next focus change must still be reported
workspace.windowActivated.emit(null);
console.log(JSON.stringify(calls.map(x => x[1])));  // the window class of each report
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class KwinScriptTests(unittest.TestCase):
    def test_focus_reports_survive_closed_windows(self):
        out = subprocess.run(["node", "-e", HARNESS, str(SCRIPT)], capture_output=True, text=True, check=True).stdout
        # first (at load), second, third: nothing is lost after the earlier windows were destroyed; null focus reports nothing
        self.assertEqual(out.strip(), '["first","second","third"]')

    def test_script_parses(self):
        subprocess.run(["node", "--check", str(SCRIPT)], capture_output=True, text=True, check=True)


if __name__ == "__main__":
    unittest.main()
