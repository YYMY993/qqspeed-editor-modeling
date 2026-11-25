"""Take an editor client snapshot and perform at most one foreground drag from that snapshot."""
import argparse
import ctypes
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
import win32api
import win32gui as gui

import window


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def identity(win):
    process = win32api.OpenProcess(0x1000, False, win.pid)
    try:
        exe = win32api.GetModuleFileNameEx(process, 0)
    finally:
        process.Close()
    return {"pid":win.pid, "hwnd":win.hwnd, "bounds":list(win.bounds), "exe":os.path.normcase(exe)}


def snapshot(folder, activate):
    win = window.locate()
    if activate:
        window.focus(win)
        win = window.locate()
    require(window.foreground(win), "A foreground observation is needed for a drag")
    frame, mode = window.capture(win, live=True)
    require(mode == "foreground", "A fresh foreground client image is required")
    folder.mkdir(parents=True, exist_ok=False)
    frame.save(folder/"client.png")
    receipt = {"target":identity(win), "time":time.time(),
               "sha256":hashlib.sha256((folder/"client.png").read_bytes()).hexdigest()}
    (folder/"receipt.json").write_text(json.dumps(receipt),encoding="utf-8")
    print(folder/"client.png")


def in_frame(point,image):
    x,y = point
    return 15 <= x < image.width-15 and 15 <= y < image.height-15


def similar(reference,live,point, *, card=False):
    x,y = point
    # Include the label below the thumbnail and its nearby tiles for the source.
    rect = ((max(0,x-52),max(0,y-35),min(reference.width,x+53),min(reference.height,y+65))
            if card else (x-14,y-14,x+15,y+15))
    diff = np.abs(np.asarray(reference.crop(rect), dtype=np.int16) -
                  np.asarray(live.crop(rect), dtype=np.int16))
    return diff.mean() < 6 and (diff.max(axis=2)>30).mean() < .055


def mouse(flags):
    event = window.Input(0,window.Mouse(flags=flags))
    require(window.user.SendInput(1,ctypes.byref(event),ctypes.sizeof(event)) == 1, "Mouse event delivery uncertain")


def route(start,end):
    for i in range(1,19):
        yield tuple(round(a+(b-a)*i/18) for a,b in zip(start,end))


def guarded_point(win,point):
    current = window.locate()
    require(current == win and window.foreground(win), "Editor moved or lost focus")
    x,y = point
    require(0 <= x < win.bounds[2] and 0 <= y < win.bounds[3], "Point outside editor")
    screen = (win.bounds[0]+x,win.bounds[1]+y)
    require(gui.GetAncestor(gui.WindowFromPoint(screen),2) == win.hwnd, "Point is covered")
    require(not any(window.user.GetAsyncKeyState(k)&0x8000 for k in (2,4,16,17,18,91,92,0x77)),
            "Manual input or F8 interrupted the drag")
    return screen


def drag(folder,start,end):
    receipt = json.loads((folder/"receipt.json").read_text(encoding="utf-8"))
    def fresh():
        require(0 <= time.time()-receipt["time"] <= 90, "Take a fresh snapshot")
    fresh()
    require(not (folder/"used").exists(), "This drag receipt was spent; inspect the scene")
    data = (folder/"client.png").read_bytes()
    require(hashlib.sha256(data).hexdigest() == receipt["sha256"], "Snapshot changed")
    from io import BytesIO
    with Image.open(BytesIO(data)) as img:
        reference = img.convert("RGB")
    win = window.locate()
    require(identity(win) == receipt["target"] and window.foreground(win), "Foreground editor changed")
    require(win.own_level >= win.app_level, "editor_has_higher_integrity")
    require(start != end and all(in_frame(p,reference) for p in (start,end)), "Invalid client points")
    for p in (start,*route(start,end)):
        guarded_point(win,p)
    def check_pixels():
        fresh()
        frame,mode = window.capture(win,live=True)
        require(mode == "foreground" and frame.size == reference.size and
                similar(reference,frame,start,card=True) and similar(reference,frame,end), "Card or drop site changed")
    check_pixels()
    screen = window.check_point(win,start)
    win32api.SetCursorPos(screen)
    time.sleep(.15)
    check_pixels()
    require(window.check_point(win,start) == gui.GetCursorPos(), "Pointer moved")
    # Exclusive receipt consumption precedes the first button event. No automatic retry.
    with (folder/"used").open("x",encoding="utf-8") as used:
        used.write("Inspect the scene before repeating.")
    try:
        mouse(2)
        time.sleep(.14)
        for p in route(start,end):
            screen = guarded_point(win,p)
            win32api.SetCursorPos(screen)
            require(gui.GetCursorPos() == screen, "Pointer moved unexpectedly")
            time.sleep(.025)
        time.sleep(.12)
        require(guarded_point(win,end) == gui.GetCursorPos(), "Editor changed before release")
    finally:
        mouse(4)
    print("One mouse drag sent. Verify map delta and selected object before any further action.")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command",required=True)
    snap = commands.add_parser("snapshot")
    snap.add_argument("folder",type=Path,help="New private observation folder")
    snap.add_argument("--activate",action="store_true")
    move = commands.add_parser("drag")
    move.add_argument("folder",type=Path)
    move.add_argument("--start",type=int,nargs=2,required=True)
    move.add_argument("--end",type=int,nargs=2,required=True)
    args = cli.parse_args()
    try:
        if args.command == "snapshot":
            snapshot(args.folder,args.activate)
        else:
            drag(args.folder,tuple(args.start),tuple(args.end))
    except (OSError,RuntimeError,ValueError,KeyError) as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
