"""Render supported static component.json geometry from disk with orthographic views and a depth buffer."""
import argparse
import hashlib
import math
import sys
from collections import Counter
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from local_group import check, read_json, validate_data, write_new

CAMERAS = {"front": (0,-1,0), "angle": (.73,-1,.52), "back": (-.8,1,.4)}
BOX, BALL, CYLINDER, PRISM = "UGC_Base_001", "UGC_Base_003", "UGC_Base_008", "UGC_Base_011"


def unit(v):
    return v / np.linalg.norm(v)


def triangles(faces, vertices):
    return np.array([[vertices[f[0]], vertices[f[j]], vertices[f[j+1]]]
                     for f in faces for j in range(1, len(f)-1)], dtype=float)


@lru_cache(None)
def mesh(template):
    if template in (BOX, PRISM):
        ring = [(-.5,-.5),(.5,-.5),(.5,.5),(-.5,.5)] if template == BOX else [
            (-math.sqrt(3)/4,-.25),(math.sqrt(3)/4,-.25),(0,.5)]
        n = len(ring)
        points = [(x,y,z) for z in (-.5,.5) for x,y in ring]
        faces = [list(reversed(range(n))), list(range(n,2*n))]
        faces += [[i,(i+1)%n,n+(i+1)%n,n+i] for i in range(n)]
    else:
        n = 20
        rings = [(-.5,.5),(.5,.5)] if template == CYLINDER else [
            (math.sin(t)/2,math.cos(t)/2) for t in np.linspace(-math.pi/2,math.pi/2,11)]
        points = [(r*math.cos(a*2*math.pi/n),r*math.sin(a*2*math.pi/n),z)
                  for z,r in rings for a in range(n)]
        faces = [[k*n+i,k*n+(i+1)%n,(k+1)*n+(i+1)%n,(k+1)*n+i]
                 for k in range(len(rings)-1) for i in range(n)]
        if template == CYLINDER:
            faces.extend([list(reversed(range(n))),list(range(n,2*n))])
    return triangles(faces, points)


def glyph_shape(node, font_path):
    check(font_path is not None, "Text needs --font with a local font containing the glyphs; layout is approximate")
    check(node.get("BillboardValue",0) == 0 and node.get("AlignmentValue",1) == 1
          and not node.get("MaxWidth") and not node.get("FontPath"), "Unsupported native text layout or custom font")
    font = ImageFont.truetype(str(font_path), 32)
    value = node["Text"]
    check(value and "\n" not in value and "\r" not in value, "Single-line Text only")
    advance = node.get("VerticalSpacingScale",1) if node.get("bVerticalDisplay") else 1
    vertical = bool(node.get("bVerticalDisplay"))
    faces = []
    missing = bytes(font.getmask(chr(0x10FFFF)))
    for i,c in enumerate(value):
        if c.isspace():
            continue
        check(bytes(font.getmask(c)) != missing, f"Preview font lacks glyph {c!r}")
        image = Image.new("L",(32,32))
        ImageDraw.Draw(image).text((16,16), c, font=font, fill=255, anchor="mm", stroke_width=0)
        mask = np.array(image) >= 96
        for row,line in enumerate(mask):
            edges = np.flatnonzero(np.diff(np.r_[0,line,0].astype(int)))
            for x0,x1 in zip(edges[::2],edges[1::2]):
                dx = 0 if vertical else i-(len(value)-1)/2
                dz = ((len(value)-1)/2-i)*advance if vertical else 0
                l,r = x0/32+dx-.5,x1/32+dx-.5
                t,b = .5-row/32+dz,.5-(row+1)/32+dz
                faces.extend([[(l,0,b),(r,0,b),(r,0,t)],[(l,0,b),(r,0,t),(l,0,t)]])
    return np.asarray(faces,dtype=float).reshape(-1,3,3)*node["FontSize"]/48


def rotation(q):
    w,x,y,z = q
    return np.array([[1-2*(y*y+z*z),2*(x*y-w*z),2*(x*z+w*y)],
                     [2*(x*y+w*z),1-2*(x*x+z*z),2*(y*z-w*x)],
                     [2*(x*z-w*y),2*(y*z+w*x),1-2*(x*x+y*y)]])


def geometry(data,font):
    validate_data(data)
    items = data["spawn"]["Items"]
    library = {o["$uid"]:o for o in data["component"]["Items"]}
    unsupported = Counter(s.get("$template",s["$type"]) for s in items if s["$type"] != "AuGroupItem"
                          and s.get("$template") not in (BOX,BALL,CYLINDER,PRISM,"Text"))
    check(not unsupported, f"No verified offline geometry for {dict(unsupported)}. Use a native scene sample.")
    shapes,colors = [], []
    for s in items:
        tr = s["Transform"]
        if s["$type"] == "AuGroupItem":
            check(s.get("Active",True) and tr["Position"] == [0,0,0] and tr["Scale"] == [1,1,1]
                  and tr["Rotation"] in ([1,0,0,0],[-1,0,0,0]), "Preview requires active groups at identity")
            continue
        if not s.get("Active",True):
            continue
        code = s["$template"]
        nodes = library[s["$uid"]]["Components"]
        if code == "Text":
            node = next(n for n in nodes if n["$type"] == "AuTextMeshComponent")
            local = glyph_shape(node,font)
            tint = node["TextColor"]
            col = np.array(tint[:3])
            col = np.where(col <= .0031308, col*12.92, 1.055*np.maximum(col,0)**(1/2.4)-.055)
        else:
            resource = next(n for n in nodes if n["$type"] == "AuMeshComponent")["MeshResourceID"]
            check(resource.lower() == f"asset://assets/basicshapes/{code}/{code}.nif".lower(),
                  f"Different mesh resource for {code}")
            local = mesh(code)
            tint = s.get("Material",{}).get("TintColor",[1,1,1,1])
            col = np.array(tint[:3])
        check(len(tint) == 4 and math.isclose(tint[3],1), "Preview requires opaque colors")
        if len(local):
            world = (local * tr["Scale"]) @ rotation(tr["Rotation"]).T + tr["Position"]
            shapes.append(world)
            colors.append(np.broadcast_to(col,(len(world),3)))
    check(bool(shapes), "No visible supported geometry")
    return np.concatenate(shapes), np.concatenate(colors)


def render(world, colors, view, size):
    toward = unit(np.array(CAMERAS[view],dtype=float))
    across = unit(np.cross([0,0,1],toward))
    up = np.cross(toward,across)
    projected = world @ np.array([across,-up,toward]).T
    flat = projected.reshape(-1,3)
    lo,hi = flat.min(axis=0),flat.max(axis=0)
    factor = (size-20)/max(max((hi-lo)[:2]),1e-9)
    projected[:,:,:2] = (projected[:,:,:2]-(lo+hi)[:2]/2)*factor+size/2
    depth = np.full((size,size),-np.inf)
    pixels = np.full((size,size,3),(232,232,225),dtype=np.uint8)
    normals = np.cross(world[:,1]-world[:,0],world[:,2]-world[:,0])
    normals /= np.maximum(np.linalg.norm(normals,axis=1,keepdims=True),1e-15)
    light = .73+.27*np.maximum(0,normals @ unit(np.array([-.5,-.7,1.])))
    palette = np.uint8(np.clip(colors*light[:,None]*255,0,255))
    for tri,color in zip(projected,palette):
        l,t = np.maximum(0,np.floor(tri[:,:2].min(axis=0)).astype(int))
        r,b = np.minimum(size-1,np.ceil(tri[:,:2].max(axis=0)).astype(int))
        if l > r or t > b:
            continue
        (ax,ay,az),(bx,by,bz),(cx,cy,cz) = tri
        denom = (by-cy)*(ax-cx)+(cx-bx)*(ay-cy)
        if abs(denom) < 1e-9:
            continue
        yy,xx = np.ogrid[t:b+1,l:r+1]
        u = ((by-cy)*(xx+.5-cx)+(cx-bx)*(yy+.5-cy))/denom
        v = ((cy-ay)*(xx+.5-cx)+(ax-cx)*(yy+.5-cy))/denom
        w = 1-u-v
        z = u*az+v*bz+w*cz
        plane = depth[t:b+1,l:r+1]
        hit = (u>=-1e-8)&(v>=-1e-8)&(w>=-1e-8)&(z>plane)
        plane[hit] = z[hit]
        pixels[t:b+1,l:r+1][hit] = color
    return Image.fromarray(pixels)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("component", type=Path)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--view", choices=CAMERAS, default="angle")
    cli.add_argument("--size", type=int, default=640)
    cli.add_argument("--font", type=Path, help="For native Text only. Used in offline preview pixels.")
    args = cli.parse_args()
    try:
        check(64 <= args.size <= 2048, "Use a size between 64 and 2048")
        check(args.output.suffix.lower() == ".png" and not args.output.exists(), "Choose a new PNG output")
        doc = read_json(args.component)
        world, colors = geometry(doc,args.font)
        result = render(world,colors,args.view,args.size)
        target = BytesIO()
        result.save(target,format="PNG")
        write_new(args.output,target.getvalue())
        stamp = hashlib.sha256(args.component.read_bytes()).hexdigest()[:12]
        print(f"Offline native geometry {stamp}, {args.view}, {validate_data(doc)} parts, {args.output}")
    except (ValueError, OSError, KeyError, TypeError, StopIteration) as exc:
        sys.exit(f"Preview unavailable: {exc}")


if __name__ == "__main__":
    main()
