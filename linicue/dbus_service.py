"""Session-bus endpoint the KWin script calls (needs the `dbus-next` package)."""
import asyncio

from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, method


class _Iface(ServiceInterface):
    def __init__(self, daemon, rebuild):
        super().__init__("org.linicue.Daemon")
        self.daemon, self.rebuild = daemon, rebuild

    @method()
    def WindowActivated(self, resource_class: 's', resource_name: 's', desktop_file: 's', caption: 's', pid: 'i'):  # noqa: F821 (dbus-next reads these as D-Bus signatures)
        self.daemon.on_window(resource_class, resource_name, desktop_file, caption, pid)


    @method()
    def Reload(self):
        self.daemon.reload(*self.rebuild())

    @method()
    def ForceProfile(self, profile_id: 's') -> 'b':  # noqa: F821  ("" releases the pin)
        return self.daemon.force(profile_id)


async def serve(daemon, rebuild) -> None:
    bus = await MessageBus().connect()
    bus.export("/org/linicue/Daemon", _Iface(daemon, rebuild))
    await bus.request_name("org.linicue.Daemon")
    await asyncio.Event().wait()  # run until cancelled


async def watch_sleep(on_resume) -> None:
    """Call on_resume() when the system wakes from suspend (systemd-logind's PrepareForSleep(false))."""
    from dbus_next import BusType

    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    path = "/org/freedesktop/login1"
    intro = await bus.introspect("org.freedesktop.login1", path)
    manager = bus.get_proxy_object("org.freedesktop.login1", path, intro).get_interface("org.freedesktop.login1.Manager")
    manager.on_prepare_for_sleep(lambda going_to_sleep: None if going_to_sleep else on_resume())
    await asyncio.Event().wait()
