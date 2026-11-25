"""Exercise the offline workflow in a disposable ComponentLibrary. No game, network or real account."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from PIL import Image, ImageChops

from local_group import read_json, validate_data

SCRIPTS = Path(__file__).resolve().parent
ASSETS = SCRIPTS.parent / "assets"


def run(tool, *args, fail=None):
    proc = subprocess.run([sys.executable, "-B", "-X", "utf8", str(SCRIPTS/tool), *map(str,args)],
                          cwd=SCRIPTS.parent, capture_output=True, encoding="utf8")
    output = proc.stdout + proc.stderr
    if (fail is None and proc.returncode) or (fail is not None and (not proc.returncode or fail not in output)):
        raise RuntimeError(f"{tool}: {output}")
    return output


def demand(test, message):
    if not test:
        raise RuntimeError(message)


def save(path, obj):
    path.write_text(json.dumps(obj,ensure_ascii=False),encoding="utf-8")


def main():
    plan = read_json(ASSETS/"gate.plan.json")
    with tempfile.TemporaryDirectory(prefix="qqspeed-skill-") as tmp:
        scratch = Path(tmp)
        card, cover, front = [scratch/name for name in ("component.json","cover.png","front.png")]
        args = (ASSETS/"gate.plan.json","--output",card)
        run("native_card.py",*args)
        original = card.read_bytes()
        run("native_card.py",*args)
        demand(card.read_bytes() == original, "Unstable card bytes")
        data = read_json(card)
        demand(validate_data(data) == 8 and data["spawn"]["Items"][0]["$uid"] > 2**53, "Object count or integer UIDs")
        for view, out in (("angle",cover),("front",front)):
            run("native_preview.py",card,"--view",view,"--size",256,"--output",out)
        with Image.open(cover) as a, Image.open(front) as b:
            demand(a.size == b.size == (256,256) and ImageChops.difference(a,b).getbbox(), "Expected two distinct views")
            demand(a.getpixel((0,0)) == b.getpixel((128,160)) and b.getpixel((128,35)) != b.getpixel((128,160)),
                   "The front view should have a clear doorway and visible roof")
        account = scratch/"Saved"/"ComponentLibrary"/"12345"
        account.mkdir(parents=True)
        install = (card,"--cover",cover,"--install-to",account,"--name",plan["name"])
        run("local_group.py",*install)
        run("local_group.py",*install)
        folders = list(account.iterdir())
        demand(len(folders) == 1 and (folders[0]/"component.json").read_bytes() == original, "Duplicate installation")
        found = json.loads(run("library_lookup.py",scratch,"--card",plan["name"]))
        demand(found["unique_name_match"] and Path(found["matching_accounts"][0]["directory"])==account,
               "Library lookup did not recognize the visible card")
        (account.parent/"54321").mkdir()
        found = json.loads(run("library_lookup.py",account.parent))
        demand(len(found["matching_accounts"])==2 and not found["unique_name_match"],"Guessed an account without a card match")
        run("local_group.py",card,"--cover",front,"--install-to",account,"--name",plan["name"],fail="different content")
        run("local_group.py",card,"--cover",cover,"--install-to",account.parent,"--name","test",fail="account directory")
        copy_plan = copy.deepcopy(plan)
        bad, unused = scratch/"changed.json",scratch/"rejected.json"
        copy_plan["budget"]["limit"] = 140
        save(bad,copy_plan)
        run("native_card.py",bad,"--output",unused,fail="exceeds")
        demand(not unused.exists(), "Over-budget plan produced a card")
        malformed = copy.deepcopy(data)
        malformed["component"]["Items"][0]["Components"][0]["LocalTransform"]["Position"][0] += 1
        save(bad,malformed)
        run("local_group.py",bad,"--cover",cover,fail="transform disagrees")
        # A native asset unknown to the previewer is preserved by donor cloning, never rendered as a box.
        marker = "OFFLINE_TEST_MESH"
        donor = copy.deepcopy(data)
        donor["spawn"]["Items"][0]["$template"] = marker
        save(bad,donor)
        source_plan = {"name":"test donor","parts":[dict(plan["parts"][0],template=marker)]}
        source_plan["parts"][0].pop("collision")
        custom = scratch/"custom-plan.json"
        save(custom,source_plan)
        run("native_card.py",custom,"--output",unused,fail="Supply --from-card")
        run("native_card.py",custom,"--output",unused,"--from-card",bad)
        run("native_preview.py",unused,"--output",scratch/"invalid.png",fail="No verified offline geometry")
        demand(not (scratch/"invalid.png").exists(), "Unsupported shapes generated a misleading preview")
        mask = Image.new("RGBA",(8,8))
        mask.paste("#AF543A",(1,1,7,3))
        mask.paste("#405850",(1,3,3,7))
        mask_path, thin_plan, thin = [scratch/v for v in ("mask.png","thin-plan.json","thin-card.json")]
        mask.save(mask_path)
        mask_args = (mask_path,"--output",thin_plan,"--name","flat test","--world-height",6,
                     "--height",6,"--colors",2,"--unit-estimate",10)
        run("mask_plan.py",*mask_args,"--budget",10,fail="exceeds")
        run("mask_plan.py",*mask_args,"--budget",20)
        parts = read_json(thin_plan)["parts"]
        demand(len(parts) == 2 and sum(p["scale"][0]*p["scale"][2] for p in parts)==20,
               "Color-run merging changed the silhouette")
        run("native_card.py",thin_plan,"--output",thin)
        demand(validate_data(read_json(thin)) == 2 and b".png" not in thin.read_bytes(),"Image leaked into card")
        run("native_preview.py",thin,"--output",scratch/"thin.png","--size",128)
    print("PASS: native build, large integer UIDs, front/angle geometry, pure-component 2D, budget, donor and transform checks, idempotent install, name conflict.")
    print("The temporary mock library has been cleaned. Live editor placement was not needed.")


if __name__ == "__main__":
    main()
