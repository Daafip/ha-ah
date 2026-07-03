"""Throwaway script: prove the integration can read your real koopzegels balance.

Usage (from the repo root):

    uv run python scripts/discover_koopzegels.py "appie://login-exit?code=..."
    uv run python scripts/discover_koopzegels.py --refresh-token "<token>"

Get a code by logging in at the authorize URL printed below. Nothing is stored;
the printed refresh token can be reused for the next run.
"""

import argparse
import asyncio
import sys
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.albert_heijn.api import AhApiClient
from custom_components.albert_heijn.config_flow import extract_code
from custom_components.albert_heijn.const import AUTHORIZE_URL


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("code", nargs="?", help="login code or full appie:// URL")
    parser.add_argument("--refresh-token", help="reuse a refresh token from a previous run")
    args = parser.parse_args()

    if not args.code and not args.refresh_token:
        parser.error(f"pass a code or --refresh-token; get a code via:\n  {AUTHORIZE_URL}")

    async with aiohttp.ClientSession() as session:
        client = AhApiClient(session, refresh_token=args.refresh_token)
        if args.code:
            await client.async_exchange_code(extract_code(args.code))

        member_id = await client.async_get_member_id()
        data = await client.async_get_koopzegels()

        print(f"member id            : {member_id}")
        print(f"payout value         : EUR {data.payout:.2f}")
        print(f"invested / interest  : EUR {data.invested:.2f} / EUR {data.interest:.2f}")
        print(f"stamps (total)       : {data.stamp_count}")
        print(f"full booklets        : {data.full_booklets}")
        print(f"current booklet      : {data.booklet_stamps}/{data.full_booklet_target}")
        print(f"until next booklet   : {data.stamps_until_next_booklet}")
        print()
        print("refresh token for next run (keep private!):")
        print(f"  {client.refresh_token}")


if __name__ == "__main__":
    asyncio.run(main())
