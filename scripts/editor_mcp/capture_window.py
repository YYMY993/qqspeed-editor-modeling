"""Bounded by the parent process. Return one client-area RGB frame on stdout."""
import ctypes as ct
import sys
from ctypes import wintypes as wt
from pathlib import Path

import numpy as np
import win32gui as gui
import win32process

# The wheel shares the OCR environment's OpenCV and NumPy implementations.
sys.path.insert(0, str(Path(sys.prefix).parent / "capture-binding"))
from windows_capture import WindowsCapture


def main(hwnd, pid):
    ct.windll.user32.SetProcessDpiAwarenessContext(ct.c_void_p(-4))
    def geometry():
        if (not gui.IsWindow(hwnd) or gui.IsIconic(hwnd) or gui.GetClassName(hwnd) != "GAMEAPP"
            or win32process.GetWindowThreadProcessId(hwnd)[1] != pid):
            raise ValueError("invalid_window")
        x, y = gui.ClientToScreen(hwnd, (0, 0))
        _, _, w, h = gui.GetClientRect(hwnd)
        rect = wt.RECT()
        if ct.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ct.byref(rect), ct.sizeof(rect)) != 0:
            raise ValueError("window_bounds_unavailable")
        return (x, y, w, h), (rect.left, rect.top, rect.right, rect.bottom)
    initial = geometry()
    frames = []
    seen = 0
    session = WindowsCapture(window_hwnd=hwnd, cursor_capture=False)

    @session.event
    def on_frame_arrived(frame, control):
        nonlocal seen
        seen += 1
        try:
            (x, y, w, h), (l, t, r, b) = initial
            if (frame.width, frame.height) == (w, h):
                left, top = 0, 0
            elif (frame.width, frame.height) == (r-l, b-t):
                left, top = x-l, y-t
            else:
                return
            rgb = frame.frame_buffer[top:top+h, left:left+w, 2::-1]
            if rgb.shape == (h, w, 3) and rgb[::16, ::16].std() > 9:
                frames.append(rgb.tobytes())
        finally:
            if frames or seen >= 3:
                control.stop()

    @session.event
    def on_closed():
        pass

    handle = session.start_free_threaded()
    handle.wait()
    if len(frames) != 1 or geometry() != initial:
        return 1
    sys.stdout.buffer.write(frames[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]), int(sys.argv[2])))
