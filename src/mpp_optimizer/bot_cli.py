from __future__ import annotations

import argparse
import json

from .auth import MppTokenManager, token_store_from_environment
from .bot import ForecastBot
from .config import load_dotenv
from .mpp_client import MppClient
from .odds_client import PolymarketClient
from .rarity import SupervisedRarityModel


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan or execute MPP bot forecasts.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan")
    sync = subparsers.add_parser(
        "sync", help="Recompute every open match and update the forecasts that changed."
    )
    sync.add_argument("--write", action="store_true", help="Actually write and verify the forecasts.")
    forecast = subparsers.add_parser("forecast")
    forecast.add_argument("--match-id", required=True)
    forecast.add_argument("--write", action="store_true", help="Actually write and verify the forecast.")
    args = parser.parse_args()

    load_dotenv()
    token = MppTokenManager(token_store_from_environment()).access_token()
    bot = ForecastBot(
        MppClient(token=token, allow_write=bool(getattr(args, "write", False))),
        PolymarketClient(),
        SupervisedRarityModel.load(),
    )
    if args.command == "plan":
        result = [item.__dict__ for item in bot.plan()]
    elif args.command == "sync":
        result = bot.sync(write=args.write)
    else:
        result = bot.execute(args.match_id, write=args.write)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
