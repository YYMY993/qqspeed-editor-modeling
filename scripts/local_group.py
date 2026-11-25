"""Check a newly authored static Aurora group and optionally add a private library card."""
import argparse
import hashlib
import json
import math
import os
import shutil
import struct
import tempfile
import zlib
from pathlib import Path


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def check(condition, message):
    if not condition:
        raise ValueError(message)


def write_new(path, payload, *, accept_identical=False):
    """Publish a complete offline output without overwriting a competing or prior version."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".new-file-",dir=path.parent) as scratch:
        pending = Path(scratch)/"data"
        pending.write_bytes(payload)
        try:
            if os.name == "nt":
                pending.rename(path)
            else:
                os.link(pending,path)
        except FileExistsError:
            if not accept_identical or path.read_bytes() != payload:
                raise ValueError("Output already exists. Choose a new path for different content.") from None


def validate_data(data):
    check((data.get("$format"), data.get("$version")) == ("AuroraComponentLibraryEntry", 1),
          "Expected AuroraComponentLibraryEntry v1")
    blocks = {}
    for key, fmt in (("spawn", "AuroraSpawnData"), ("component", "AuroraComponentData")):
        block = data[key]
        check((block["$format"], block["$version"]) == (fmt, 5), f"Expected {fmt} v5")
        items = block["Items"]
        ids = [item["$uid"] for item in items]
        check(all(type(uid) is int for uid in ids) and len(set(ids)) == len(items),
              f"Duplicate or non-integer ID in {fmt}")
        blocks[key] = dict(zip(ids, items))
    spawn, components = blocks["spawn"], blocks["component"]
    check(spawn.keys() == components.keys(), "Spawn and component item IDs differ")
    seen_ids, child_ids = set(spawn), set()
    for uid, instance in spawn.items():
        obj = components[uid]
        check(instance["$type"] == obj["$type"], "Item types disagree")
        internal = [node["$uid"] for node in obj["Components"]]
        check(all(type(n) is int for n in internal) and len(internal) == len(set(internal))
              and not seen_ids.intersection(internal), "Internal ID collision")
        seen_ids.update(internal)
        root_id = obj["RootComponent"]["$ref"]
        check(type(root_id) is int and root_id in internal, "Missing root component")
        root = next(n for n in obj["Components"] if n["$uid"] == root_id)
        pose = instance.get("Transform", {})
        for field, size in (("Position", 3), ("Rotation", 4), ("Scale", 3)):
            value = pose.get(field)
            check(isinstance(value, list) and len(value) == size and
                  all(type(x) in (float, int) and math.isfinite(x) for x in value),
                  f"Invalid transform {uid}/{field}")
        check(math.isclose(sum(x*x for x in pose["Rotation"]), 1, abs_tol=1e-4),
              "Invalid rotation quaternion")
        if "LocalTransform" in root:
            check(root["LocalTransform"] == pose, "SceneRoot transform disagrees with spawn")
        if "Children" in instance:
            check(instance["$type"] == "AuGroupItem" and isinstance(instance["Children"], list),
                  "Children must belong to a group")
        for child in instance.get("Children", []):
            check(type(child) is int and child in spawn and child not in child_ids, "Missing or repeated group child")
            child_ids.add(child)
    roots = set(spawn) - child_ids
    check(len(roots) == 1 and spawn[next(iter(roots))]["$type"] == "AuGroupItem",
          "Expected one root group")
    pending, visited = list(roots), set()
    while pending:
        uid = pending.pop()
        check(uid not in visited, "Cycle inside group")
        visited.add(uid)
        pending.extend(spawn[uid].get("Children", []))
    check(visited == set(spawn), "Unreachable component or detached cycle")
    return sum(item["$type"] == "AuItem" for item in spawn.values())


def validate(component, cover):
    count = validate_data(read_json(component))
    data = cover.read_bytes()
    check(data[:16] == b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" and
          len(data) >= 33 and struct.unpack(">II", data[16:24]) == (256, 256),
          "Expected a 256 x 256 PNG cover")
    offset, has_data = 8, False
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset:offset+4], "big")
        kind = data[offset+4:offset+8]
        end = offset+8+length
        check(end+4 <= len(data) and zlib.crc32(data[offset+4:end]) ==
              int.from_bytes(data[end:end+4], "big"), "Damaged PNG chunk")
        has_data |= kind == b"IDAT" and length > 0
        offset = end + 4
        if kind == b"IEND":
            check(length == 0 and offset == len(data) and has_data, "Incomplete PNG cover")
            return count
    raise ValueError("Incomplete PNG cover")


def digest(path):
    return hashlib.sha256(path.read_bytes()).digest()


def install(account, name, component, cover):
    account = account.resolve(strict=True)
    check(account.is_dir() and account.parent.name == "ComponentLibrary" and account.name.isdecimal(),
          "Choose the verified account directory inside ComponentLibrary")
    check(bool(name.strip()), "Card name is empty")
    signature = (digest(component), digest(cover))
    def matching_entry(folder):
        meta = folder / "meta.json"
        if not meta.is_file() or read_json(meta).get("ModuleName") != name:
            return False
        check((digest(folder / "component.json"), digest(folder / "cover.png")) == signature,
              "Name already belongs to different content. Choose a distinct name.")
        return True

    for meta in account.glob("*/meta.json"):
        if meta.parent.name.isdecimal() and matching_entry(meta.parent):
            return meta.parent
    base_id = int.from_bytes(hashlib.sha256(name.encode("utf-8")).digest()[:8], "big")
    with tempfile.TemporaryDirectory(prefix=".new-card-", dir=account) as scratch:
        pending = Path(scratch) / "entry"
        pending.mkdir()
        shutil.copyfile(component, pending / "component.json")
        shutil.copyfile(cover, pending / "cover.png")
        for index in range(200000000):
            module_id = 1800000000 + (base_id + index) % 200000000
            destination = account / str(module_id)
            if destination.exists():
                if matching_entry(destination):
                    return destination
                continue
            meta = {"ModuleID": module_id, "ModuleName": name.strip()}
            (pending / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            try:
                pending.rename(destination)
            except FileExistsError:
                if matching_entry(destination):
                    return destination
                continue
            return destination
    raise ValueError("No local module ID available")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", type=Path)
    parser.add_argument("--cover", required=True, type=Path)
    parser.add_argument("--install-to", type=Path)
    parser.add_argument("--name")
    args = parser.parse_args()
    if bool(args.install_to) != bool(args.name):
        parser.error("--install-to and --name must be provided together")
    try:
        count = validate(args.component, args.cover)
        print(f"Validated {count} objects.")
        if args.install_to:
            print(install(args.install_to, args.name.strip(), args.component, args.cover))
    except (OSError, KeyError, TypeError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
