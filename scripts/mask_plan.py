"""Convert a transparent subject mask into a native thin-box plan. Pixels never enter the card."""
import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np
from PIL import Image

from local_group import check, write_new


def rectangles(bitmap):
    """Merge equal horizontal runs on successive rows. Every foreground cell is covered exactly once."""
    active, finished = {}, []
    for y, row in enumerate(bitmap):
        edges = np.flatnonzero(np.diff(np.r_[0,row,0].astype(int))).tolist()
        runs = set(zip(edges[::2],edges[1::2]))
        for l,r in sorted(active.keys()-runs):
            y0 = active.pop((l,r))
            finished.append((l,y0,r-l,y-y0))
        for span in runs-active.keys():
            active[span] = y
    for (l,r),y0 in sorted(active.items()):
        finished.append((l,y0,r-l,len(bitmap)-y0))
    return finished


def make_plan(source, title, height, colors, world_height, thickness, budget=None, unit=None):
    check(2 <= height <= 256 and 2 <= colors <= 64, "Use height 2..256 and 2..64 colors")
    check(all(math.isfinite(v) and v > 0 for v in (world_height,thickness)), "Positive finite dimensions required")
    with Image.open(source) as opened:
        im = opened.convert("RGBA")
    alpha = im.getchannel("A")
    check(alpha.getextrema()[0] < 128 and alpha.getextrema()[1] >= 128, "Supply an isolated subject on transparency")
    im = im.crop(alpha.point(lambda a: 255 if a >= 128 else 0).getbbox())
    width = max(1,round(im.width*height/im.height))
    check(width <= 1024, "The subject is too wide for the selected sampling height")
    im = im.resize((width,height),Image.Resampling.LANCZOS)
    arr = np.array(im)
    mask = arr[:,:,3] >= 128
    check(mask.any(), "No opaque subject at this resolution")
    rgb = arr[:,:,:3][mask]
    q = Image.fromarray(rgb.reshape(-1,1,3)).quantize(colors=colors,method=Image.Quantize.MEDIANCUT,
                                                       dither=Image.Dither.NONE)
    indices = np.full(mask.shape,-1,dtype=int)
    indices[mask] = np.array(q).ravel()
    palette = q.getpalette()
    cell = world_height/height
    parts = []
    for color in sorted(set(indices[mask])):
        layer = indices == color
        rows = rectangles(layer)
        cols = [(y,x,h,w) for x,y,w,h in rectangles(layer.T)]
        best = min((rows,cols),key=len)
        shade = "#" + bytes(palette[color*3:color*3+3]).hex()
        for x,y,w,h in best:
            parts.append({"name":f"色面 {len(parts)+1}","template":"UGC_Base_001",
                          "position":[round((x+w/2-width/2)*cell,8),0,round((height-y-h/2)*cell,8)],
                          "scale":[round(w*cell,8),thickness,round(h*cell,8)],"color":shade,"collision":False})
    plan = {"name":title,"parts":parts}
    if budget is not None or unit is not None:
        check(budget is not None and unit is not None and math.isfinite(unit) and unit>0 and math.isfinite(budget) and budget>0,
              "Supply positive finite --budget and --unit-estimate together")
        estimated = len(parts)*unit
        check(estimated<=budget, f"{len(parts)} pieces; estimate {estimated:g} exceeds {budget:g}. Reduce sampling height/colors or redraw major contours.")
        plan["budget"] = {"limit":budget,"unit_estimates":{"UGC_Base_001":unit}}
    return plan


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("source",type=Path)
    cli.add_argument("--output",type=Path,required=True)
    cli.add_argument("--name",required=True)
    cli.add_argument("--height",type=int,default=64,help="Number of sample rows")
    cli.add_argument("--colors",type=int,default=8)
    cli.add_argument("--world-height",type=float,required=True)
    cli.add_argument("--thickness",type=float,default=.08)
    cli.add_argument("--budget",type=float)
    cli.add_argument("--unit-estimate",type=float)
    args = cli.parse_args()
    try:
        plan = make_plan(args.source,args.name,args.height,args.colors,args.world_height,
                         args.thickness,args.budget,args.unit_estimate)
        payload = json.dumps(plan,ensure_ascii=False,allow_nan=False,separators=(",",":")).encode("utf-8")
        write_new(args.output,payload)
        print(f"{len(plan['parts'])} native thin boxes. Compare the silhouette and the angled view before scaling up.")
    except (ValueError, OSError) as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
