"""Keeps the daemon attached to the mouse: notices when it disappears, reconnects, and re-initialises it."""
from __future__ import annotations

import asyncio
from typing import Callable

from . import mouse, nxp

POLL_SECONDS = 1.0


class MouseLink:
    def __init__(self, daemon, log: Callable[[str], None], dry: bool = False, find_button=nxp.find_button_node,
                 find_control=nxp.find_control_node, open_control=nxp.ControlChannel, watch=mouse.watch):
        self.daemon, self.log, self.dry = daemon, log, dry
        self.find_button, self.find_control, self.open_control, self.watch = find_button, find_control, open_control, watch
        self.up = False
        self.waiting = False
        self._stop_buttons: Callable[[], None] | None = None
        daemon.on_link_lost = self.lost

    def step(self) -> None:
        """One poll: if the mouse is not attached, try to attach it."""
        if self.up:
            return
        button, control = self.find_button(), self.find_control()
        if not button or (not self.dry and not control):
            if not self.waiting:
                self.waiting = True
                self.log("waiting for the Scimitar (plug it in)…")
            return
        channel = None
        try:
            channel = None if self.dry else self.open_control(control)
            self._stop_buttons = self.watch(button, self.daemon.on_button, self.lost)
        except OSError as e:  # the node exists but is not usable yet (e.g. permissions still being applied)
            if channel:
                channel.close()
            self.log(f"mouse found but not ready yet: {e}")
            return
        self.daemon.control = channel
        self.up, self.waiting = True, False
        self.daemon.start()  # software mode, DPI stages, and a fresh lighting frame
        self.log("mouse connected")

    def lost(self, reason) -> None:
        """The device went away (or must be re-initialised): drop the handles and let step() reattach."""
        if not self.up:
            return
        self.up = False
        if self._stop_buttons:
            self._stop_buttons()
            self._stop_buttons = None
        channel, self.daemon.control = self.daemon.control, None
        if channel:
            try:
                channel.close()
            except OSError:
                pass
        self.daemon.player.release_all()  # a key held when the mouse vanished would stay down forever
        if self.daemon.dpi:
            self.daemon.dpi.sniping = False
        self.log(f"mouse disconnected ({reason}); waiting for it to come back")

    def resumed(self) -> None:
        """After suspend the mouse has usually reset to hardware mode: re-attach and re-initialise from scratch."""
        self.lost("resumed from sleep")

    async def run(self) -> None:
        while True:
            self.step()
            await asyncio.sleep(POLL_SECONDS)
