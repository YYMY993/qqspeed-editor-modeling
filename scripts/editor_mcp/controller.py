import hashlib
import secrets
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import numpy as np

import window
from panel import Unavailable, outline_signature, read_frame

EDITABLE = {f"{section}.{axis}" for section in ("position", "rotation") for axis in "xyz"}


def state_stamp(frame, panel):
    rgb = np.asarray(frame)
    digest = hashlib.sha256()
    for key in sorted(panel.buttons):
        x1, y = panel.buttons[key][-1]
        x2, _ = panel.buttons[key][1]
        radius = max(4, (x2-x1)//9)
        region = rgb[y-radius:y+radius+1, x1+radius*2:x2-radius*2]
        digest.update(np.packbits(region.min(2) > 170).tobytes())
    return (outline_signature(rgb, panel.left), digest.digest())


@dataclass
class Observation:
    token: str
    expires: float
    win: object
    panel: object


class Controller:
    def __init__(self, backend=window, reader=read_frame):
        self.backend = backend
        self.reader = reader
        self.last = None

    def status(self):
        w = self.backend.locate()
        return {"window_found": True, "foreground": self.backend.foreground(w),
                "client_size": w.bounds[2:], "editor_integrity": w.app_level,
                "uia_root_has_children": self.backend.has_accessible_children(w),
                "mcp_integrity": w.own_level, "input_privilege_ok": w.own_level >= w.app_level}

    def observe(self, activate=False):
        self.last = None
        w = self.backend.locate()
        if activate:
            try:
                self.backend.focus(w)
            except Unavailable as exc:
                if str(exc) != "editor_needs_foreground":
                    raise
            w = self.backend.locate()
        frame, mode = self.backend.capture(w, live=self.backend.unobstructed(w))
        p = self.reader(frame)
        if self.backend.locate() != w:
            raise Unavailable("window_changed_during_read")
        result = {"panel": p.kind, "source": mode, "object_type": p.title or None,
                  "fields": p.values, "selection_outline_visible": bool(p.outline),
                  "writable_fields": [], "observation": None}
        if w.own_level < w.app_level:
            result["write_blocker"] = "editor_has_higher_integrity"
        elif mode != "foreground" or not self.backend.unobstructed(w):
            result["write_blocker"] = "foreground_observation_required"
        elif p.kind != "precision" or not p.outline or not (EDITABLE & p.buttons.keys()):
            result["write_blocker"] = "select_one_object_and_open_precision_panel"
        else:
            token = secrets.token_urlsafe(18)
            self.last = Observation(token, time.monotonic()+60, w, p)
            result.update(observation=token, writable_fields=sorted(EDITABLE & p.buttons.keys()))
        return result

    def nudge(self, token, field, expected_before, expected_after):
        obs, self.last = self.last, None
        if not obs or obs.token != token or time.monotonic() >= obs.expires:
            raise Unavailable("missing_or_stale_observation")
        if field not in EDITABLE or field not in obs.panel.buttons:
            raise Unavailable("unsupported_field")
        try:
            before, after = Decimal(expected_before), Decimal(expected_after)
        except InvalidOperation:
            raise Unavailable("invalid_decimal") from None
        if not (before.is_finite() and after.is_finite()) or before == after:
            raise Unavailable("distinct_finite_values_required")
        if before != Decimal(obs.panel.values[field]):
            raise Unavailable("expected_value_mismatch")
        w = self.backend.locate()
        if w != obs.win or w.own_level < w.app_level:
            raise Unavailable("window_or_integrity_changed")
        if not self.backend.unobstructed(w):
            raise Unavailable("foreground_observation_required")
        frame, _ = self.backend.capture(w, live=True)
        current = self.reader(frame)
        original = obs.panel
        if (current.kind != "precision" or current.title != original.title or
            current.values != original.values or not current.outline or
            current.outline != original.outline or current.buttons != original.buttons):
            raise Unavailable("selection_or_fields_changed")
        point = current.buttons[field][1 if after > before else -1]
        stamp = state_stamp(frame, current)
        def check_pixels():
            fresh, _ = self.backend.capture(w, live=True)
            if time.monotonic() >= obs.expires:
                raise Unavailable("missing_or_stale_observation")
            if fresh.size != frame.size or state_stamp(fresh, current) != stamp:
                raise Unavailable("pixels_changed_before_click")
        check_pixels()
        try:
            self.backend.click(w, point, check_pixels)
        except Unavailable:
            raise
        except Exception as exc:
            return {"status": "uncertain", "reason": type(exc).__name__, "retry": False}
        try:
            # Poll readback only. Input is issued once regardless of the result.
            for _ in range(2):
                time.sleep(.2)
                frame, _ = self.backend.capture(w, live=True)
                updated = self.reader(frame)
                if (updated.kind != "precision" or updated.title != current.title or
                    not updated.outline or updated.values.keys() != current.values.keys()):
                    return {"status": "uncertain", "reason": "selection_after_click", "retry": False}
                changes = {k: v for k, v in updated.values.items() if v != current.values[k]}
                if changes:
                    if set(changes) == {field} and Decimal(changes[field]) == after:
                        return {"status": "verified", "field": field, "before": str(before),
                                "after": changes[field]}
                    return {"status": "uncertain", "reason": "unexpected_readback",
                            "observed_changes": changes, "retry": False}
            return {"status": "uncertain", "reason": "no_visible_change", "retry": False}
        except Exception as exc:
            return {"status": "uncertain", "reason": str(exc) if isinstance(exc, Unavailable)
                    else type(exc).__name__, "retry": False}
