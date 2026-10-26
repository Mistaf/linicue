// Sends the focused window's identity to the linicue daemon (Plasma 6, X11 and Wayland).
// The daemon reads /proc/<pid> itself for Wine/Proton details; KWin only exposes these fields.
const SERVICE = "org.linicue.Daemon";
const PATH = "/org/linicue/Daemon";
const IFACE = "org.linicue.Daemon";

let current = null;

function report(w) {
    if (!w) {
        return;
    }
    callDBus(SERVICE, PATH, IFACE, "WindowActivated",
             w.resourceClass || "", w.resourceName || "", w.desktopFileName || "",
             w.caption || "", w.pid || 0);
}

function onCaptionChanged() {
    report(current); // lets title-based rules (two profiles sharing one program) react to title changes
}

function onActivated(w) {
    if (current) {
        current.captionChanged.disconnect(onCaptionChanged);
    }
    current = w;
    if (current) {
        current.captionChanged.connect(onCaptionChanged);
    }
    report(current);
}

workspace.windowActivated.connect(onActivated);
onActivated(workspace.activeWindow);
