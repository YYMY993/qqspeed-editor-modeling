"""Locate the local ComponentLibrary and match visible card names. Never creates folders or writes cards."""
import argparse
import json
from pathlib import Path
import sys

from local_group import check, read_json


def lookup(location, names):
    location = location.resolve(strict=True)
    start = location if location.is_dir() else location.parent
    candidates = {p for folder in (start,*start.parents)
                  for p in (folder,folder/"ComponentLibrary",folder/"Saved"/"ComponentLibrary")
                  if p.name.casefold() == "componentlibrary" and p.is_dir()}
    check(len(candidates) == 1, "Could not uniquely locate Saved/ComponentLibrary. Select the active client or its library.")
    library = candidates.pop()
    matches = []
    for account in sorted(library.iterdir()):
        if not (account.is_dir() and account.name.isdecimal()):
            continue
        cards, unreadable = set(), 0
        for meta in account.glob("*/meta.json"):
            if meta.parent.name.isdecimal():
                try:
                    title = read_json(meta).get("ModuleName")
                    if isinstance(title,str):
                        cards.add(title)
                except (OSError,ValueError,TypeError,AttributeError):
                    unreadable += 1
        if names.issubset(cards):
            matches.append({"directory":str(account),"card_names_count":len(cards),"unreadable_metadata":unreadable})
    return {"library":str(library),"matching_accounts":matches,
            "unique_name_match":bool(names) and len(matches)==1}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("location",type=Path,help="Active GameApp.exe, installation root, Saved or ComponentLibrary")
    cli.add_argument("--card",action="append",default=[],help="Exact title visible in My Components; repeat to disambiguate")
    args = cli.parse_args()
    try:
        print(json.dumps(lookup(args.location,set(args.card)),ensure_ascii=False,indent=2))
    except (ValueError, OSError) as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
