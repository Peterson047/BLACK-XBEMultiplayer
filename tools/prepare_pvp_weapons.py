#!/usr/bin/env python3
"""Prepare the categorized PvP arsenal resources from the user's retail ISO.

Reads only the user's ISO. No game assets are shipped with the repository.
"""
import argparse
import hashlib
import tempfile
from pathlib import Path

from extract_mp_map import XboxIso


def prepare(iso_path, package):
    if not package.is_dir():
        raise ValueError(f"Missing multiplayer package: {package}; run tools/extract_mp_map.py first")
    iso = XboxIso(str(iso_path))
    try:
        levels = iso.find(["levels"])
        if levels is None:
            raise ValueError("ISO has no levels directory")
        prefixes = ("pst", "mgn", "gk1", "smg", "sm3", "p90", "mp1", "ak1", "asr", "m16", "snr")
        resources = []
        for prefix in prefixes:
            pair = None
            for level in levels.children:
                entries = [iso.find(["levels", level.name, "fpguns", f"bg1_{prefix}.{suffix}"]) for suffix in ("db", "wdd")]
                if all(entry is not None and not entry.is_dir for entry in entries):
                    pair = entries
                    break
            if pair is None:
                raise ValueError(f"Weapon resource pair absent from ISO: {prefix}")
            resources.extend(pair)
        for entry in resources:
            name = entry.name
            iso.file.seek(entry.offset)
            data = iso.file.read(entry.size)
            if len(data) != entry.size:
                raise ValueError(f"Truncated ISO resource: {name}")
            target = package / "fpguns" / name.lower()
            if target.exists():
                if target.read_bytes() != data:
                    raise ValueError(f"Resource differs from ISO; refusing to overwrite: {target}")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=target.parent, prefix=name + ".", delete=False) as output:
                    temporary = Path(output.name)
                    output.write(data)
                try:
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
            print(f"Arsenal ready: {target} ({entry.size} bytes, sha256 {hashlib.sha256(data).hexdigest()})")
    finally:
        iso.close()


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", type=Path, default=root / "assets/Black.iso")
    parser.add_argument("--package", type=Path, default=root / "assets/levels/level_mp00")
    args = parser.parse_args()
    try:
        prepare(args.iso, args.package)
        from prepare_pvp_audio import prepare as prepare_audio
        prepare_audio(args.iso, root / "assets/pvp_audio")
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
