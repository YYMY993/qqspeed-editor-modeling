"""Build a new static v1/v5 group from a plan and individual native parts. Offline only."""
import argparse
import copy
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

from local_group import check, read_json, validate_data, write_new

ASSETS = Path(__file__).resolve().parents[1] / "assets"
IDENTITY = {"Position": [0, 0, 0], "Rotation": [1, 0, 0, 0], "Scale": [1, 1, 1]}
BASIC = {"UGC_Base_001", "UGC_Base_003", "UGC_Base_008", "UGC_Base_011", "Text"}
OPTIONS = {"template", "name", "position", "rotation", "scale", "color", "collision",
           "text", "font_size", "vertical", "vertical_spacing"}


def vector(values, n, field):
    check(isinstance(values, list) and len(values) == n and
          all(type(v) in (int, float) and math.isfinite(v) for v in values), f"Invalid {field}")
    return values


def rgb(value):
    check(isinstance(value, str) and len(value) == 7 and value.startswith("#"), "Use #RRGGBB")
    return [int(value[i:i+2], 16) / 255 for i in (1, 3, 5)]


def read_templates(paths, needed):
    found, reserved = {}, set()
    for path in paths:
        data = read_json(path)
        validate_data(data)
        objects = {n["$uid"]: n for n in data["component"]["Items"]}
        for s in data["spawn"]["Items"]:
            obj = objects[s["$uid"]]
            reserved.update([s["$uid"], *(n["$uid"] for n in obj["Components"])])
            template = s.get("$template")
            if template not in needed or template in found:
                continue
            nodes = obj["Components"]
            types = [n["$type"] for n in nodes]
            # These helpers clone static native geometry. Other behaviors have separate dependencies.
            check(s["$type"] == "AuItem" and len(types) == 3 and
                  types.count("AuSceneComponent") == types.count("AuCollisionComponent") == 1 and
                  (types.count("AuMeshComponent") + types.count("AuTextMeshComponent") == 1),
                  f"{template} is not a standalone static mesh or text sample")
            check(not s.get("Children") and s.get("Active") is True and not s.get("Properties"),
                  f"Export an active, unconfigured standalone sample for {template}")
            found[template] = (s, obj)
    check(needed <= found.keys(), f"Supply --from-card with a local sample for {sorted(needed-found.keys())}")
    return found, reserved


def remap(value, ids):
    if isinstance(value, list):
        return [remap(v, ids) for v in value]
    if isinstance(value, dict):
        return {k: (ids[v] if k in ("$uid", "$ref") else remap(v, ids)) for k, v in value.items()}
    return value


def number(value, label, minimum):
    check(type(value) in (int, float) and math.isfinite(value) and value >= minimum, f"Invalid {label}")
    return value


def instantiate(part, sample, uid):
    check(not (set(part) - OPTIONS), f"Unknown part fields {sorted(set(part)-OPTIONS)}")
    src, obj = sample
    ids = {src["$uid"]: uid}
    ids.update({n["$uid"]: uid+i for i, n in enumerate(obj["Components"], 1)})
    s, c = remap(src, ids), remap(obj, ids)
    name = part.get("name")
    check(isinstance(name, str) and name.strip(), "Give each part a name")
    s["Name"] = name
    q = vector(part.get("rotation", IDENTITY["Rotation"]), 4, "rotation [W,X,Y,Z]")
    check(math.isclose(sum(v*v for v in q), 1, abs_tol=1e-5), "Rotation must be a unit quaternion")
    scale = vector(part["scale"], 3, "native scale")
    check(min(scale) > 0, "Scale must be positive")
    s["Transform"] = {"Position": vector(part["position"], 3, "position"), "Rotation": q, "Scale": scale}
    nodes = {n["$type"]: n for n in c["Components"]}
    nodes["AuSceneComponent"]["LocalTransform"] = copy.deepcopy(s["Transform"])
    code = s["$template"]
    if "collision" in part:
        check(code in BASIC and type(part["collision"]) is bool, "Keep the donor collision for other assets")
        nodes["AuCollisionComponent"].update(bCollisionEnabled=part["collision"], CollisionType=int(part["collision"]), ShapeType=0)
    if code == "Text":
        node = nodes["AuTextMeshComponent"]
        check(isinstance(part.get("text"), str) and part["text"], "Text requires content")
        node["Text"] = part["text"]
        if "font_size" in part:
            node["FontSize"] = number(part["font_size"], "font_size", 0.01)
        if "vertical_spacing" in part:
            node["VerticalSpacingScale"] = number(part["vertical_spacing"], "vertical_spacing", 0.01)
        if "vertical" in part:
            check(type(part["vertical"]) is bool, "vertical must be true or false")
            node["bVerticalDisplay"] = part["vertical"]
        if "color" in part:
            values = rgb(part["color"])
            node["TextColor"] = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in values] + [1]
    else:
        check(not {"text", "font_size", "vertical", "vertical_spacing"}.intersection(part), "Text fields on a mesh")
        if "color" in part:
            check(code in BASIC or "TintColor" in s.get("Material", {}), "Tint has not been established for this donor")
            s.setdefault("Material", {})["TintColor"] = rgb(part["color"]) + [1]
    return s, c


def build(plan, sources):
    check(isinstance(plan, dict) and not (set(plan) - {"name","parts","budget"}), "Invalid plan fields")
    name, parts = plan["name"], plan["parts"]
    check(isinstance(name, str) and name.strip() and isinstance(parts, list) and parts, "Expected name and parts")
    counts = Counter(p["template"] for p in parts)
    budget = plan.get("budget")
    if budget is not None:
        check(isinstance(budget, dict) and set(budget) <= {"limit","unit_estimates","reserve"}, "Invalid budget fields")
        rates = budget["unit_estimates"]
        check(isinstance(rates, dict) and counts.keys() <= rates.keys(), "Missing unit estimates for one or more templates")
        estimate = sum(n*number(rates[k], k, 0.01) for k,n in counts.items())
        reserve = number(budget.get("reserve", 0), "reserve", 0)
        limit = number(budget["limit"], "limit", 0)
        print(f"Estimate {estimate:g} + reserve {reserve:g}, limit {limit:g}. Verify the actual map delta.")
        check(estimate + reserve <= limit, "Estimated group exceeds the plan limit")
    templates, reserved = read_templates([*sources, ASSETS / "basic-parts.json"], set(counts))
    identity_data = json.dumps([plan, templates], ensure_ascii=False, sort_keys=True, separators=(",",":"))
    digest = hashlib.sha256(identity_data.encode()).digest()
    base = (1 << 60) | ((int.from_bytes(digest[:6], "big") >> 8) << 20)
    check(len(parts) + 1 < (1 << 17), "Split this group before allocating native IDs")
    sp, co = [], []
    for i, part in enumerate(parts):
        s, c = instantiate(part, templates[part["template"]], base+i*8)
        sp.append(s)
        co.append(c)
    group = base+len(parts)*8
    sp.append({"$type":"AuGroupItem","$uid":group,"Active":True,"Children":[s["$uid"] for s in sp],
               "Name":name,"NextCompIndex":1,"Properties":{"ComponentLibraryFileName":""},"Transform":copy.deepcopy(IDENTITY)})
    co.append({"$type":"AuGroupItem","$uid":group,"Components":[{"$name":"AuSceneComponent_0",
               "$type":"AuSceneComponent","$uid":group+1}],"RootComponent":{"$ref":group+1}})
    check(not any(base <= uid <= group+1 for uid in reserved), "Template UID overlap. Give the new group a distinct name.")
    data = {"$format":"AuroraComponentLibraryEntry","$version":1,"manifest":{"Name":name,"RootGroupName":name},
            "component":{"$format":"AuroraComponentData","$version":5,"Items":co},
            "spawn":{"$format":"AuroraSpawnData","$version":5,"Items":sp,"SceneName":"PlayScene"}}
    validate_data(data)
    return data


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("plan", type=Path)
    cli.add_argument("--output", type=Path, required=True, help="New component.json in a private work directory")
    cli.add_argument("--from-card", action="append", type=Path, default=[], help="Matching local v1/v5 component.json. First matching donor wins.")
    args = cli.parse_args()
    try:
        data = build(read_json(args.plan), args.from_card)
        content = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",",":")).encode("utf-8")
        write_new(args.output,content,accept_identical=True)
        print(f"Wrote {len(data['spawn']['Items'])-1} native parts to {args.output}.")
    except (KeyError, ValueError, TypeError, OSError) as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
