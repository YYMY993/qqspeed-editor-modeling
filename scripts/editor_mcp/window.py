"""Windows client-area capture and one bounded mouse click."""
import ctypes as ct
import subprocess
import sys
import time
from ctypes import wintypes as wt
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

import numpy as np
from comtypes import COMError
import win32api
import win32gui as gui
import win32process
import win32security
import win32ui
from PIL import Image, ImageGrab

from panel import Unavailable

user = ct.WinDLL("user32", use_last_error=True)
try:
    user.SetProcessDpiAwarenessContext(ct.c_void_p(-4))
except AttributeError:
    user.SetProcessDPIAware()


def integrity(process):
    token = win32security.OpenProcessToken(process, 8)
    try:
        sid = win32security.GetTokenInformation(token, 25)[0]
        return int(win32security.ConvertSidToStringSid(sid).rsplit("-", 1)[1])
    finally:
        token.Close()


@dataclass(frozen=True)
class Window:
    hwnd: int
    pid: int
    bounds: tuple
    own_level: int
    app_level: int


def locate():
    matches = []
    def check(h, _):
        if gui.GetClassName(h) != "GAMEAPP" or not gui.IsWindowVisible(h):
            return
        if "IDC构建区" not in gui.GetWindowText(h):
            return
        pid = win32process.GetWindowThreadProcessId(h)[1]
        process = win32api.OpenProcess(0x1000, False, pid)
        try:
            name = PureWindowsPath(win32process.GetModuleFileNameEx(process, 0)).name
            if name.casefold() != "gameapp.exe":
                return
            app_level = integrity(process)
        finally:
            process.Close()
        _, _, w, hgt = gui.GetClientRect(h)
        x, y = gui.ClientToScreen(h, (0, 0))
        matches.append(Window(h, pid, (x, y, w, hgt),
                              integrity(win32api.GetCurrentProcess()), app_level))
    gui.EnumWindows(check, None)
    if len(matches) != 1:
        raise Unavailable("editor_window_missing_or_ambiguous")
    return matches[0]


def foreground(win):
    return gui.GetForegroundWindow() == win.hwnd and not gui.IsIconic(win.hwnd)


def automation_root(win):
    from comtypes.client import CreateObject, GetModule
    lib = GetModule("UIAutomationCore.dll")
    client = CreateObject(lib.CUIAutomation, interface=lib.IUIAutomation)
    return client, client.ElementFromHandle(win.hwnd)


def has_accessible_children(win):
    try:
        client, root = automation_root(win)
        return bool(client.RawViewWalker.GetFirstChildElement(root))
    except (COMError, OSError, AttributeError):
        return None


def focus(win):
    if not foreground(win):
        user.SetForegroundWindow(win.hwnd)
        if not foreground(win):
            try:
                _, root = automation_root(win)
                root.SetFocus()
            except (COMError, OSError, AttributeError):
                pass
        for _ in range(8):
            if foreground(win):
                break
            time.sleep(.05)
    if not foreground(win):
        raise Unavailable("editor_needs_foreground")


def visible_height(win):
    if not foreground(win):
        return 0
    ox, oy, w, h = win.bounds
    sx, sy, sw, sh = [user.GetSystemMetrics(k) for k in (76, 77, 78, 79)]
    if not (sx <= ox and ox+w <= sx+sw and sy <= oy < sy+sh):
        return 0
    height = min(h, sy+sh-oy)
    other = gui.GetTopWindow(0)
    while other and other != win.hwnd:
        if gui.IsWindowVisible(other) and not gui.IsIconic(other):
            a, b, c, d = gui.GetWindowRect(other)
            if min(c, ox+w) > max(a, ox) and min(d, oy+h) > max(b, oy):
                cloaked = wt.DWORD(0)
                ct.windll.dwmapi.DwmGetWindowAttribute(other, 14, ct.byref(cloaked), 4)
                if not cloaked.value:
                    height = min(height, max(0, b-oy))
        other = gui.GetWindow(other, 2)
    return height if other == win.hwnd else 0


def unobstructed(win):
    return visible_height(win) >= min(800, win.bounds[3])


def window_image(win):
    if user.IsHungAppWindow(win.hwnd):
        raise Unavailable("editor_unresponsive")
    w, h = win.bounds[2:]
    dc = gui.GetDC(win.hwnd)
    src = win32ui.CreateDCFromHandle(dc)
    mem = src.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    try:
        bitmap.CreateCompatibleBitmap(src, w, h)
        previous = mem.SelectObject(bitmap)
        try:
            ok = user.PrintWindow(win.hwnd, mem.GetSafeHdc(), 3)
            if ok:
                return Image.frombytes("RGB", (w, h), bitmap.GetBitmapBits(True),
                                       "raw", "BGRX", 0, 1)
        finally:
            mem.SelectObject(previous)
    finally:
        mem.DeleteDC()
        src.DeleteDC()
        gui.ReleaseDC(win.hwnd, dc)
        gui.DeleteObject(bitmap.GetHandle())


def capture(win, *, live=False):
    if gui.IsIconic(win.hwnd) or min(win.bounds[2:]) < 100:
        raise Unavailable("editor_minimized_or_too_small")
    # Desktop pixels are used for writes: PrintWindow may return a cached Direct3D frame.
    if not live:
        companion = Path(__file__).with_name("capture_window.py")
        try:
            packet = subprocess.run([sys.executable, str(companion), str(win.hwnd), str(win.pid)],
                                    stdin=subprocess.DEVNULL, capture_output=True, timeout=8,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            w, h = win.bounds[2:]
            if packet.returncode == 0 and len(packet.stdout) == w*h*3 and locate() == win:
                return Image.frombytes("RGB", (w, h), packet.stdout), "graphics_capture"
        except (OSError, subprocess.TimeoutExpired):
            pass
        img = window_image(win)
        if img is not None and np.asarray(img.resize((100, 80))).std() > 9:
            return img, "window"
    height = visible_height(win)
    if height < min(800, win.bounds[3]):
        raise Unavailable("desktop_capture_needs_unobstructed_foreground_editor")
    x, y, w, h = win.bounds
    img = ImageGrab.grab((x, y, x+w, y+height), all_screens=True)
    if visible_height(win) < height or locate() != win:
        raise Unavailable("window_changed_during_capture")
    return img, "foreground"


class Mouse(ct.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("data", wt.DWORD),
                ("flags", wt.DWORD), ("time", wt.DWORD), ("extra", ct.c_size_t)]


class Input(ct.Structure):
    _fields_ = [("kind", wt.DWORD), ("mouse", Mouse)]


def check_point(win, point):
    if win.own_level < win.app_level:
        raise Unavailable("editor_has_higher_integrity")
    if locate() != win or not unobstructed(win) or not 0 <= point[1] < visible_height(win):
        raise Unavailable("target_changed_before_click")
    if any(user.GetAsyncKeyState(k) & 0x8000 for k in (1, 2, 4, 16, 17, 18, 91, 92)):
        raise Unavailable("mouse_or_modifier_already_held")
    x, y = win.bounds[0]+point[0], win.bounds[1]+point[1]
    if gui.GetAncestor(gui.WindowFromPoint((x, y)), 2) != win.hwnd:
        raise Unavailable("button_covered")
    return x, y


def click(win, point, before_press):
    x, y = check_point(win, point)
    vx, vy, width, height = [user.GetSystemMetrics(k) for k in (76, 77, 78, 79)]
    if not (vx <= x < vx+width and vy <= y < vy+height):
        raise Unavailable("button_off_screen")
    move = Mouse(int((x-vx+.5)*65536/width), int((y-vy+.5)*65536/height),
                 0, 0xC001, 0, 0)
    event = Input(0, move)
    if user.SendInput(1, ct.byref(event), ct.sizeof(Input)) != 1:
        raise Unavailable("pointer_move_failed")
    time.sleep(.16)
    before_press()
    if check_point(win, point) != gui.GetCursorPos():
        raise Unavailable("pointer_moved_before_click")
    events = (Input*2)(Input(0, Mouse(flags=2)), Input(0, Mouse(flags=4)))
    sent = user.SendInput(2, events, ct.sizeof(Input))
    if sent != 2:
        if sent == 1:
            up = Input(0, Mouse(flags=4))
            user.SendInput(1, ct.byref(up), ct.sizeof(Input))
        raise RuntimeError("partial_input_delivery")
