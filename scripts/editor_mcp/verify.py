"""Replay prior QQ Speed evidence, optionally exercise Windows input on a private test window."""
import argparse
import copy
import multiprocessing
import os
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import card_drag

import window
from controller import Controller
from panel import Unavailable, read_frame


class Replay:
    def __init__(self, frame):
        self.frame = frame
        self.clicks = []
        self.win = window.Window(1, 1, (0, 0, *frame.size), 8192, 8192)
        self.visible = True

    def locate(self):
        return self.win

    def unobstructed(self, _):
        return self.visible

    def capture(self, _, live=False):
        return self.frame, "foreground"

    def click(self, _, point, before_press):
        before_press()
        self.clicks.append(point)


def replay_card_drag():
    # The frame and every input function are private fixtures. Never enumerate a real window.
    frame = Image.new("RGB",(320,240),(112,122,132))
    win = window.Window(1,1,(0,0,320,240),8192,8192)
    start,end = (40,50),(170,140)
    with tempfile.TemporaryDirectory() as tmp, ExitStack() as mocks:
        def stub(obj,key,**kw):
            return mocks.enter_context(patch.object(obj,key,**kw))
        stub(window,"locate",return_value=win)
        stub(window,"foreground",return_value=True)
        fetch = stub(window,"capture",return_value=(frame,"foreground"))
        stub(card_drag,"identity",return_value={"target":"test-window"})
        guard = stub(card_drag,"guarded_point",side_effect=lambda w,p: p)
        stub(window,"check_point",side_effect=lambda w,p: p)
        move = stub(card_drag.win32api,"SetCursorPos")
        stub(card_drag.gui,"GetCursorPos",side_effect=lambda: move.call_args.args[0])
        stub(card_drag.time,"sleep")
        events = stub(card_drag,"mouse")
        def reject(call, phrase):
            try:
                call()
            except ValueError as e:
                assert phrase in str(e), e
            else:
                raise AssertionError(phrase)
        folder = Path(tmp)/"stable"
        card_drag.snapshot(folder,False)
        card_drag.drag(folder,start,end)
        assert [v.args[0] for v in events.call_args_list] == [2,4]
        reject(lambda: card_drag.drag(folder,start,end), "spent")
        folder = Path(tmp)/"changed"
        card_drag.snapshot(folder,False)
        fetch.return_value = (Image.new("RGB",frame.size,"red"),"foreground")
        reject(lambda: card_drag.drag(folder,start,end), "changed")
        assert events.call_count == 2 and not (folder/"used").exists()
        fetch.return_value = (frame,"foreground")
        calls = 0
        def lose_focus(w,p):
            nonlocal calls
            calls += 1
            if events.call_count == 3:
                raise ValueError("fixture lost focus during drag")
            return p
        guard.side_effect = lose_focus
        reject(lambda: card_drag.drag(folder,start,end),"lost focus")
        assert calls and [v.args[0] for v in events.call_args_list] == [2,4,2,4]
        assert (folder/"used").exists()
    print("PASS one drag per receipt, changed frame rejection and release on interrupted drag (simulated)")


def replay(evidence):
    def load(name):
        with Image.open(evidence / (name+".png")) as image:
            return image.convert("RGB")

    frame = load("prism-flat")
    flat = read_frame(frame)
    rotated = read_frame(load("prism-z90"))
    slope = read_frame(load("slope-x90"))
    arc = read_frame(load("arc-equal"))
    other = read_frame(load("mixed-samples-1114"))
    assert all(p.outline and len(p.values) == len(p.buttons) == 12 for p in (flat, rotated, slope, arc))
    assert other.kind != "precision"
    assert (rotated.title, rotated.values["rotation.z"], flat.values["rotation.z"]) == (
        "等腰三棱柱", "90.00", "0.00")
    assert slope.title == "斜坡" and slope.values["rotation.x"] == "90.00"
    assert arc.title == "1/4圆环" and arc.values["size.x"] == "7.00"
    print("PASS 4 precision frames with all 12 fields and button pairs, 1 other panel")

    def scenario(fresh=flat, post=rotated, change=None, old="0", new="90"):
        backend = Replay(frame)
        states = iter([flat, fresh, post, post])
        control = Controller(backend, lambda _: next(states))
        token = control.observe()["observation"]
        if change:
            change(control, backend)
        try:
            result = control.nudge(token, "rotation.z", old, new)
        except Unavailable as e:
            result = {"status": "blocked", "reason": str(e)}
        try:
            control.nudge(token, "rotation.z", old, new)
            raise AssertionError("Token reused")
        except Unavailable:
            pass
        return result, backend.clicks

    result, points = scenario()
    assert result["status"] == "verified" and points == [flat.buttons["rotation.z"][1]]
    # The archived frames represent two distinct orientations, not a measured game step.
    result, points = scenario(fresh=rotated, post=flat)
    assert result["status"] == "blocked" and not points
    selection = copy.deepcopy(flat)
    selection.outline = "different-selection"
    for case in [dict(fresh=selection), dict(fresh=other), dict(old="11"),
                 dict(change=lambda c, b: setattr(c.last, "expires", 0)),
                 dict(change=lambda c, b: setattr(b, "visible", False))]:
        result, points = scenario(**case)
        assert result["status"] == "blocked" and not points, (result, points)
    for post in [slope, flat, other]:
        result, points = scenario(post=post)
        assert result["status"] == "uncertain" and len(points) == 1
    inconsistent = copy.deepcopy(rotated)
    inconsistent.values["position.x"] = "12.00"
    result, points = scenario(post=inconsistent)
    assert result.get("reason") == "unexpected_readback" and len(points) == 1
    backend = Replay(frame)
    backend.win = window.Window(1, 1, (0, 0, *frame.size), 8192, 12288)
    assert Controller(backend, lambda _: flat).observe()["observation"] is None
    print("PASS one-shot inputs, mismatch, expiry, selection, focus, higher privilege and readback")


def draw_fixture(pipe, evidence, foreground_input):
    from PIL import ImageWin
    import win32con as flags

    g = window.gui
    pictures = []
    for name in ["prism-flat", "prism-z90"]:
        with Image.open(evidence / (name+".png")) as im:
            width = im.width
            pictures.append(ImageWin.Dib(im.convert("RGB").crop((0, 0, width, 1000))))
    active = 0
    def draw(dc):
        pictures[active].draw(dc, (0, 0, width, 1000))
    def events(hwnd, msg, wp, lp):
        nonlocal active
        if msg == flags.WM_PAINT:
            dc, ps = g.BeginPaint(hwnd)
            try:
                draw(dc)
            finally:
                g.EndPaint(hwnd, ps)
            return 0
        if msg in (0x317, 0x318):
            draw(wp)
            return 0
        if msg == flags.WM_LBUTTONDOWN:
            x, y = lp & 0xffff, (lp >> 16) & 0xffff
            pipe.send(("click", x, y))
            if abs(x-(width-48)) < 7 and abs(y-486) < 7:
                active = 1
                g.InvalidateRect(hwnd, None, False)
                g.UpdateWindow(hwnd)
            return 0
        if msg == flags.WM_DESTROY:
            g.PostQuitMessage(0)
            return 0
        return g.DefWindowProc(hwnd, msg, wp, lp)
    wc = g.WNDCLASS()
    wc.hInstance = window.win32api.GetModuleHandle(None)
    wc.lpszClassName = "QQSpeedPrivateMCPFixture"
    wc.lpfnWndProc = events
    atom = g.RegisterClass(wc)
    hwnd = g.CreateWindowEx(flags.WS_EX_TOPMOST if foreground_input else 0, atom,
                            "QQSpeed MCP input test", flags.WS_POPUP, 35, 35, width, 1000,
                            0, 0, wc.hInstance, None)
    g.ShowWindow(hwnd, flags.SW_SHOW if foreground_input else flags.SW_SHOWNOACTIVATE)
    g.UpdateWindow(hwnd)
    pipe.send(("ready", hwnd, hwnd))
    g.PumpMessages()


def windows_input(evidence, foreground_input):
    """Exercise a private fixture via window messages or opt in to foreground SendInput."""
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    gui = ctx.Process(target=draw_fixture, args=(child, evidence, foreground_input))
    gui.start()
    try:
        assert parent.poll(15), "Test window did not appear"
        event, hwnd, label_hwnd = parent.recv()
        assert event == "ready"
        def test_window():
            g = window.gui
            if not g.IsWindow(hwnd) or window.win32process.GetWindowThreadProcessId(hwnd)[1] != gui.pid:
                raise Unavailable("private_test_window_closed")
            x, y = g.ClientToScreen(hwnd, (0, 0))
            _, _, w, h = g.GetClientRect(hwnd)
            level = window.integrity(window.win32api.GetCurrentProcess())
            return window.Window(hwnd, gui.pid, (x, y, w, h), level, level)
        class PrivateFixture:
            locate = staticmethod(test_window)

            @staticmethod
            def capture(w, live=False):
                assert w == test_window()
                return window.window_image(w), "foreground"

            @staticmethod
            def unobstructed(w):
                return w == test_window()

            @staticmethod
            def click(w, point, before_press):
                assert w == test_window()
                before_press()
                assert window.win32process.GetWindowThreadProcessId(label_hwnd)[1] == gui.pid
                x, y = point
                xy = (y << 16) | x
                window.gui.SendMessage(label_hwnd, 0x201, 1, xy)
                window.gui.SendMessage(label_hwnd, 0x202, 0, xy)

        with patch.object(window, "locate", test_window):
            c = Controller()
            if foreground_input:
                window.focus(test_window())
                time.sleep(.6)
            else:
                c = Controller(PrivateFixture())
            observed = c.observe()
            for _ in range(2):
                if observed["observation"] or not foreground_input:
                    break
                if not window.foreground(test_window()):
                    break
                observed = c.observe()
            assert observed["observation"], (observed, window.foreground(test_window()),
                                             window.visible_height(test_window()))
            result = c.nudge(observed["observation"], "rotation.z", "0", "90")
            receipt = parent.recv() if parent.poll(1) else None
            assert result["status"] == "verified", (result, receipt)
            assert receipt and receipt[0] == "click"
            assert not parent.poll(.25), "More than one click"
        mode = "foreground SendInput" if foreground_input else "addressed test-window message"
        print(f"PASS one {mode} and OCR readback on private test window")
    finally:
        gui.terminate()
        gui.join(5)
        parent.close()
        child.close()


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--evidence", type=Path, default=Path(__file__).resolve().parents[2]/"references/evidence")
    cli.add_argument("--windows-input", action="store_true")
    cli.add_argument("--window-replay", action="store_true")
    args = cli.parse_args()
    replay(args.evidence)
    replay_card_drag()
    if args.windows_input or args.window_replay:
        windows_input(args.evidence, args.windows_input)
