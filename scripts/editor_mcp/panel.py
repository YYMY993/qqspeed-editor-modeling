"""Read one visible QQ Speed precision panel. All points are client-relative."""
import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

import cv2
import numpy as np
from rapidocr import RapidOCR

SECTIONS = {"坐标编辑": "position", "旋转编辑": "rotation",
            "缩放编辑": "scale", "尺寸编辑": "size"}
NUMBER = re.compile(r"[-+]?\d+\.\d{2}")


class Unavailable(ValueError):
    pass


@lru_cache(maxsize=1)
def engine():
    return RapidOCR()


@dataclass
class Token:
    text: str
    x: int
    y: int
    height: int
    score: float


@dataclass
class Panel:
    kind: str
    title: str
    values: dict
    buttons: dict
    left: int
    outline: str | None


def outline_signature(rgb, left):
    h, w = rgb.shape[:2]
    scene = rgb[int(.12*h):int(.87*h), int(.12*w):max(int(.12*w), left-6)]
    r, g, b = scene.transpose(2, 0, 1)
    mask = (r >= 245) & (g >= 121) & (g <= 134) & (b < 9)
    ys, xs = np.where(mask)
    if len(xs) < 80 or np.ptp(xs) < 12 or np.ptp(ys) < 12:
        return None
    return hashlib.sha256(np.packbits(mask).tobytes()).hexdigest()


def find_buttons(rgb, num, axis, dy):
    """Require two square buttons, each with the matching horizontal/vertical strokes."""
    radius = max(10, round(.43*dy))
    top = max(0, axis.y-radius)
    left = axis.x + round(dy)
    area = rgb[top:axis.y+radius+1, left:]
    if area.size == 0:
        return {}
    bright = (area.min(2) > 208).astype('uint8')
    _, _, stats, _ = cv2.connectedComponentsWithStats(bright)
    found = {}
    for x, y, w, h, count in stats[1:]:
        if not (.48*dy < w < .85*dy and abs(w-h) <= 3 and count > .68*w*h):
            continue
        cx, cy = left+x+w//2, top+y+h//2
        if abs(cy-num.y) > .22*dy or not .75*dy < abs(cx-num.x) < 2.2*dy:
            continue
        mid = area[y+h//4:y+h-h//4, x+w//4:x+w-w//4].mean(2) < 154
        if mid.sum(1).max() < .35*w:
            continue
        vertical = mid.sum(0).max()
        direction = -1 if cx < num.x and vertical <= .20*h else (
            1 if cx > num.x and vertical >= .32*h else None)
        if direction is not None:
            if direction in found:
                return {}
            found[direction] = (int(cx), int(cy))
    return found if len(found) == 2 else {}


def parse(rgb, tokens, offset):
    def only(items):
        if len(items) != 1:
            raise Unavailable("incomplete_or_ambiguous_precision_panel")
        return items[0]

    precision = [t for t in tokens if t.text == "精准编辑" and t.score >= .80]
    if not precision:
        kind = "sky_settings" if any("天空" in t.text for t in tokens) else "unrecognized"
        return Panel(kind, "", {}, {}, offset, None)
    anchor = only(precision)
    heads = [only([t for t in tokens if t.text == name and t.score >= .80 and
                   t.y > anchor.y and abs(t.x-anchor.x) < 2.5*anchor.height]) for name in SECTIONS]
    if sorted(t.y for t in heads) != [t.y for t in heads]:
        raise Unavailable("unexpected_section_order")
    cost = only([t for t in tokens if "占用值" in t.text and t.y < anchor.y])
    names = [t for t in tokens if t.y < cost.y and cost.y-t.y < 2.5*max(cost.height, t.height)
             and abs(t.x-cost.x) <= 2.2*cost.height and t.score >= .80]
    name = only(names).text
    values, buttons = {}, {}
    for i, head in enumerate(heads):
        end = heads[i+1].y if i+1 < len(heads) else head.y + (head.y-heads[i-1].y)
        rows = sorted([t for t in tokens if re.fullmatch("[XYZ]轴", t.text) and
                       head.y < t.y < end and abs(t.x-head.x) < 2.2*head.height
                       and t.score >= .72], key=lambda t: t.y)
        if [r.text for r in rows] != ["X轴", "Y轴", "Z轴"]:
            raise Unavailable("missing_axis_labels")
        dy = (rows[-1].y-rows[0].y)/2
        if dy < 12 or abs(rows[1].y-rows[0].y-dy) > .22*dy:
            raise Unavailable("unexpected_row_spacing")
        for axis in rows:
            num = only([t for t in tokens if abs(t.y-axis.y) < .36*dy and t.x > axis.x + 2*dy
                        and NUMBER.fullmatch(t.text) and t.score >= .84])
            key = SECTIONS[head.text] + "." + axis.text[0].lower()
            values[key] = str(Decimal(num.text))
            controls = find_buttons(rgb, num, axis, dy)
            if controls:
                buttons[key] = {sign: (offset+x, y) for sign, (x, y) in controls.items()}
    return Panel("precision", name, values, buttons, offset, None)


def read_frame(image):
    rgb = np.asarray(image.convert("RGB"))
    width = rgb.shape[1]
    # UI scale varies independently of viewport width. Find labels within a right-hand strip.
    offset = max(0, width - min(570, max(355, round(width*.24))))
    crop = rgb[:min(rgb.shape[0], 1250), offset:]
    result = engine()(cv2.cvtColor(crop, cv2.COLOR_RGB2BGR), use_cls=False)
    tokens = []
    if result.txts is not None:
        for word, box, score in zip(result.txts, result.boxes, result.scores):
            x, y = box.mean(0)
            word = word.replace(" ", "").replace("−", "-").replace("－", "-")
            if word.endswith("轴"):
                word = word.upper()
            tokens.append(Token(word, round(float(x)), round(float(y)),
                                int(np.ptp(box[:, 1])), float(score)))
    panel = parse(crop, tokens, offset)
    if panel.kind == "precision":
        panel.outline = outline_signature(rgb, offset)
    return panel
