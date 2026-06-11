#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(*arguments: str) -> None:
    env = {**os.environ, "PYTHONPATH": f"{ROOT / 'src'}:{ROOT / 'scripts'}"}
    subprocess.run([sys.executable, *arguments], cwd=ROOT, env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Met à jour le corpus MPP puis reconstruit tous les modèles de rareté."
    )
    parser.add_argument("--import-cache", action="store_true")
    parser.add_argument("--calendar", action="append", default=[])
    parser.add_argument("--international-archives", action="store_true")
    args = parser.parse_args()

    if args.import_cache:
        run("scripts/scrape_mpp_history.py", "--import-chrome-cache")
    for championship_id in args.calendar:
        run("scripts/scrape_mpp_history.py", "--calendar", championship_id)
    if args.international_archives:
        run("scripts/scrape_mpp_history.py", "--international-archives")
    run("scripts/build_mpp_neutral_score_model.py")
    run("scripts/export_neutral_model_to_extension.py")
    run("scripts/analyze_rarity_accuracy.py")
    run("scripts/build_supervised_rarity_model.py")


if __name__ == "__main__":
    main()
