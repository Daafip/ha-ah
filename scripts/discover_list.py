"""Verify the shopping list ("Mijn lijst") CRUD against the real AH API.

Usage (from the repo root):

    uv run python scripts/discover_list.py "appie://login-exit?code=..."
    uv run python scripts/discover_list.py --refresh-token "<token>"
    uv run python scripts/discover_list.py --refresh-token "<token>" --roundtrip

Get a code by logging in at the authorize URL printed below. Nothing is stored;
the printed refresh token can be reused for the next run.

Without --roundtrip this only reads the list. With --roundtrip it exercises the
integration's actual client methods end-to-end on a throwaway test item:
add → check → uncheck → delete (of a checked item), verifying the list state
after every step. Leftover test items from earlier runs (matched on the
"ha-ah-testitem" marker) are cleaned up first.

The endpoint knowledge itself (write shape vs read shape, merge-by-description,
quantity 0 = delete) is documented in const.py's shopping list section; it was
discovered with earlier versions of this script on 2026-07-14.
"""

import argparse
import asyncio
import sys
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.albert_heijn.api import AhApiClient, AhListItem
from custom_components.albert_heijn.config_flow import extract_code
from custom_components.albert_heijn.const import AUTHORIZE_URL

TEST_MARKER = "ha-ah-testitem"
TEST_ITEM = f"{TEST_MARKER} (verwijder mij)"


def show(items: list[AhListItem]) -> None:
    if not items:
        print("  (empty)")
    for item in items:
        mark = "x" if item.checked else " "
        product = f" productId={item.product_id}" if item.product_id else ""
        print(f"  [{mark}] {item.quantity}x {item.description}{product}")


async def expect(
    client: AhApiClient, label: str, description: str, *, present: bool, checked: bool | None = None
) -> bool:
    items = await client.async_get_list_items()
    item = next((i for i in items if i.description == description), None)
    ok = (item is not None) is present and (checked is None or (item is not None and item.checked is checked))
    print(f"{'✓' if ok else '✗ FAILED'} {label}")
    if not ok:
        show(items)
    return ok


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("code", nargs="?", help="login code or full appie:// URL")
    parser.add_argument("--refresh-token", help="reuse a refresh token from a previous run")
    parser.add_argument(
        "--roundtrip",
        action="store_true",
        help=f"exercise add/check/uncheck/delete with a test item ({TEST_ITEM!r}) on your real list",
    )
    args = parser.parse_args()

    if not args.code and not args.refresh_token:
        parser.error(f"pass a code or --refresh-token; get a code via:\n  {AUTHORIZE_URL}")

    async with aiohttp.ClientSession() as session:
        client = AhApiClient(session, refresh_token=args.refresh_token)
        try:
            if args.code:
                await client.async_exchange_code(extract_code(args.code))

            print("current shopping list:")
            items = await client.async_get_list_items()
            show(items)

            if not args.roundtrip:
                print("\n(re-run with --roundtrip to verify add/check/uncheck/delete)")
                return

            leftovers = [i for i in items if TEST_MARKER in i.description]
            if leftovers:
                await client.async_delete_list_items(leftovers)
                print(f"cleaned up {len(leftovers)} leftover test item(s)")

            print(f"\nroundtrip with {TEST_ITEM!r}:")
            await client.async_add_free_text_item(TEST_ITEM)
            ok = await expect(client, "add: item present and unchecked", TEST_ITEM, present=True, checked=False)

            item = AhListItem(description=TEST_ITEM, checked=False)
            await client.async_set_item_checked(item, True)
            ok &= await expect(client, "check: item checked", TEST_ITEM, present=True, checked=True)

            await client.async_set_item_checked(item, False)
            ok &= await expect(client, "uncheck: item unchecked", TEST_ITEM, present=True, checked=False)

            await client.async_set_item_checked(item, True)
            await client.async_delete_list_items([AhListItem(description=TEST_ITEM, checked=True)])
            ok &= await expect(client, "delete: checked item gone", TEST_ITEM, present=False)

            print(f"\nresult: {'ALL VERIFIED ✓' if ok else 'SOMETHING FAILED — see above'}")
        finally:
            # Always print, even on a crash: the token may have rotated.
            print("\nrefresh token for next run (keep private!):")
            print(f"  {client.refresh_token}")


if __name__ == "__main__":
    asyncio.run(main())
