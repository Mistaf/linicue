// Sends the focused window's identity to the linicue daemon (Plasma 6, X11 and Wayland).
// The daemon reads /proc/<pid> itself for Wine/Proton details; KWin only exposes these fields.
const SERVICE = "org.linicue.Daemon";
const PATH = "/org/linicue/Daemon";
const IFACE = "org.linicue.Daemon";

let current = null;

// A window can be destroyed under us at any moment, and touching a dead window throws.
// One uncaught error would stop every later focus report, so each step is guarded on its own.
function safely(fn) {
    try {
        fn();
    } catch (e) {
        // the window is gone; nothing to do
    }
}

function report(w) {
    if (!w) {
        return;
    }
    safely(() => callDBus(SERVICE, PATH, IFACE, "WindowActivated",
                          w.resourceClass || "", w.resourceName || "", w.desktopFileName || "",
                          w.caption || "", w.pid || 0));
}

function onCaptionChanged() {
    report(current); // lets title-based rules (two profiles sharing one program) react to title changes
}

function onActivated(w) {
    if (current) {
        safely(() => current.captionChanged.disconnect(onCaptionChanged));
    }
    current = w;
    if (current) {
        safely(() => current.captionChanged.connect(onCaptionChanged));
    }
    report(current);
}

workspace.windowActivated.connect(onActivated);
safely(() => workspace.windowRemoved.connect(function (w) {
    if (w === current) {
        current = null;
    }
}));
onActivated(workspace.activeWindow);
