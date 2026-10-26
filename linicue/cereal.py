"""Schema-less decoder for C++ cereal XML archives as written by iCUE.

cereal conventions handled here:
  * ``size="dynamic"`` marks a sequence; items are ``value0..valueN``.
  * ``polymorphic_id``: bit 31 set means ``polymorphic_name`` follows and
    registers the type; later uses carry only the numeric id.  Bit 30 alone
    marks a plain (non-polymorphic) pointer.  Zero is a null pointer.
  * ``ptr_wrapper``: ``id`` with bit 31 set introduces a shared object (its
    ``data`` follows); without it, ``id`` refers to an earlier shared object.
    ``valid`` + ``data`` is a unique_ptr.
  * ``base`` holds base-class members and is merged into its parent.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

MSB = 0x80000000
MSB2 = 0x40000000
_VALUE_RE = re.compile(r"value\d+$")
_DROP = {"cereal_class_version"}


class Node(dict):
    """A decoded struct. ``type`` is the polymorphic type name, if any."""

    type: str | None = None

    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError:
            raise AttributeError(item) from None


def _scalar(text: str | None) -> Any:
    if text is None:
        return ""
    if text == "true":
        return True
    if text == "false":
        return False
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


class Decoder:
    def __init__(self) -> None:
        self.type_names: dict[int, str] = {}
        self.shared: dict[int, Any] = {}

    def decode_root(self, root: ET.Element) -> Any:
        return {c.tag: self.decode(c) for c in root}

    def decode(self, el: ET.Element) -> Any:
        kids = [k for k in el if k.tag not in _DROP]
        if not kids:
            if el.get("size") == "dynamic":
                return []
            text = (el.text or "").strip()
            return _scalar(text) if text else ""
        tags = [k.tag for k in kids]
        if "polymorphic_id" in tags:
            return self._pointer(kids)
        if "ptr_wrapper" in tags:  # raw ptr_wrapper without polymorphic header
            return self._wrapper(next(k for k in kids if k.tag == "ptr_wrapper"), None)
        if el.get("size") == "dynamic" or all(_VALUE_RE.match(t) for t in tags):
            return [self.decode(k) for k in kids]
        node = Node()
        for k in kids:
            val = self.decode(k)
            if k.tag == "base":
                if isinstance(val, dict):
                    for bk, bv in val.items():
                        node.setdefault(bk, bv)
                continue
            node[k.tag] = val
        return node

    def _pointer(self, kids: list[ET.Element]) -> Any:
        by = {k.tag: k for k in kids}
        pid = int(by["polymorphic_id"].text)
        if pid == 0:
            return None
        name = None
        if pid & MSB:
            name = by["polymorphic_name"].text
            self.type_names[pid & ~(MSB | MSB2)] = name
        elif not pid & MSB2:
            name = self.type_names.get(pid & ~MSB2)
        return self._wrapper(by["ptr_wrapper"], name)

    def _wrapper(self, wrapper: ET.Element, name: str | None) -> Any:
        by = {k.tag: k for k in wrapper}
        data = by.get("data")
        if "id" in by:
            sid = int(by["id"].text)
            if sid & MSB:
                val = self._with_type(self.decode(data), name) if data is not None else None
                self.shared[sid & ~MSB] = val
                return val
            return self.shared.get(sid)
        if by.get("valid") is not None and by["valid"].text == "0":
            return None
        return self._with_type(self.decode(data), name) if data is not None else None

    @staticmethod
    def _with_type(val: Any, name: str | None) -> Any:
        if isinstance(val, Node):
            val.type = name
        return val


def load(path: str) -> Any:
    """Decode a cereal XML file into nested dict/list/scalar values."""
    return Decoder().decode_root(ET.parse(path).getroot())
