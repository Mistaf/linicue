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
    def Status(self) -> 's':  # noqa: F821
        return self.daemon.status()

    @method()
    def Reload(self):
        self.daemon.reload(*self.rebuild())

    @method()
    def ForceProfile(self, profile_id: 's') -> 'b':  # noqa: F821  ("" releases the pin)
        return self.daemon.force(profile_id)


async def serve(daemon, rebuild) -> None:
    bus = await MessageBus().connect()
    bus.export("/org/linicue/Daemon", _Iface(daemon, rebuild))
    from dbus_next import RequestNameReply

    if await bus.request_name("org.linicue.Daemon") != RequestNameReply.PRIMARY_OWNER:
        raise RuntimeError("another linicue daemon already owns org.linicue.Daemon, so this one gets no window events: "
                           "stop the other one (a terminal, or an old service)")
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


def status_main() -> int:
    """`linicue status`: ask the running daemon what it is doing."""
    async def ask() -> str:
        bus = await MessageBus().connect()
        path, name = "/org/linicue/Daemon", "org.linicue.Daemon"
        proxy = bus.get_proxy_object(name, path, await bus.introspect(name, path))
        return await proxy.get_interface(name).call_status()

    try:
        print(asyncio.run(ask()))
        return 0
    except Exception as e:  # no daemon on the bus, no session bus, ...
        print(f"cannot reach the linicue daemon ({type(e).__name__}): is it running?  systemctl --user status linicue")
        return 1
