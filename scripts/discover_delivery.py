"""Capture what the AH API says about a delivery while it is under way.

Usage (from the repo root), ideally from an hour before the slot until the
groceries are in:

    uv run python scripts/discover_delivery.py "appie://login-exit?code=..."
    uv run python scripts/discover_delivery.py --refresh-token "<token>"
    uv run python scripts/discover_delivery.py "appie://..." --once

Get a code by logging in at the authorize URL printed below. Use a fresh login
rather than the token Home Assistant holds: AH rotates refresh tokens on every
use, so borrowing HA's token logs the integration out.

Every --interval seconds this fetches the raw track & trace data of today's and
later orders and prints it whenever something changed, so the status values and
ETA formats that only exist during a delivery end up on screen. Every change is
also appended to --out as one JSON line, ready to paste into an issue. No
address fields are requested; order ids are masked unless --show-ids is given.

The field names were validated against the live schema on 2026-11-15; see the
delivery tracking section in const.py for how to re-check them without a login.
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.albert_heijn.api import AhApiClient, AhApiError
from custom_components.albert_heijn.config_flow import extract_code
from custom_components.albert_heijn.const import AUTHORIZE_URL, DEFAULT_HEADERS, GRAPHQL_URL

# Deliberately wider than what the integration queries: this is for looking.
FULFILLMENTS_QUERY = """\
query DiscoverFulfillments {
  orderFulfillments {
    result {
      orderId
      statusCode
      statusDescription
      shoppingType
      transactionCompleted
      modifiable
      closingDateTime
      delivery {
        status
        method
        deliveryMessage
        shiftCode
        slot { date startTime endTime timeDisplay }
        eta { estimated }
        ride { number sequenceNumber }
      }
    }
  }
}
"""

ORDER_QUERY = """\
query DiscoverOrder($orderId: Int!) {
  order(id: $orderId) {
    id
    state
    delivery {
      status
      trackAndTraceV2 {
        orderId
        orderType
        type
        message
        etaBlock { type range { start end } }
        realisedDeliveryTime
      }
    }
  }
}
"""

NOTIFICATION_QUERY = """\
query DiscoverDeliveryNotification {
  notificationsGetDeliveryNotification {
    id
    type
    dateInfo
  }
}
"""

MAX_ORDERS = 3


async def raw_graphql(
    session: aiohttp.ClientSession, client: AhApiClient, query: str, variables: dict[str, Any] | None = None
) -> Any:
    """Post a query and return the whole body, errors included (unlike the client)."""
    operation = query.split("(")[0].split("{")[0].split()[1]
    await client._async_ensure_token()
    headers = {
        **DEFAULT_HEADERS,
        "Authorization": f"Bearer {client._access_token}",
        "x-apollo-operation-name": operation,
        "x-apollo-operation-type": "query",
    }
    payload = {"operationName": operation, "query": query, "variables": variables or {}}
    try:
        async with session.post(GRAPHQL_URL, json=payload, headers=headers) as response:
            text = await response.text()
            try:
                body = json.loads(text)
            except ValueError:
                body = text[:500]
            return body if response.status == 200 else {"http_status": response.status, "body": body}
    except (TimeoutError, aiohttp.ClientError) as err:
        return {"request_failed": repr(err)}


async def snapshot(session: aiohttp.ClientSession, client: AhApiClient) -> dict[str, Any]:
    """One poll: the fulfillment list plus track & trace of the upcoming orders."""
    fulfillments = await raw_graphql(session, client, FULFILLMENTS_QUERY)
    result: dict[str, Any] = {"fulfillments": fulfillments, "orders": {}}

    today = datetime.now().date().isoformat()
    try:
        items = fulfillments["data"]["orderFulfillments"]["result"] or []
    except (KeyError, TypeError):
        items = []
    upcoming = [
        item
        for item in items
        if item.get("orderId") and (((item.get("delivery") or {}).get("slot") or {}).get("date") or "") >= today
    ]
    upcoming.sort(key=lambda item: (item["delivery"]["slot"]["date"], item["delivery"]["slot"].get("startTime") or ""))
    result["fulfillments"] = {"upcoming": upcoming, "total": len(items)} if items else fulfillments
    for item in upcoming[:MAX_ORDERS]:
        result["orders"][str(item["orderId"])] = await raw_graphql(
            session, client, ORDER_QUERY, {"orderId": item["orderId"]}
        )
    result["notification"] = await raw_graphql(session, client, NOTIFICATION_QUERY)
    return result


def mask_ids(value: Any, ids: dict[str, str]) -> Any:
    """Replace order ids (as keys and as values) with stable order-1, order-2, ... labels."""
    if isinstance(value, dict):
        return {ids.get(str(key), key): mask_ids(item, ids) for key, item in value.items()}
    if isinstance(value, list):
        return [mask_ids(item, ids) for item in value]
    if isinstance(value, int) and not isinstance(value, bool) and str(value) in ids:
        return ids[str(value)]
    return value


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("code", nargs="?", help="login code or full appie:// URL")
    parser.add_argument("--refresh-token", help="reuse a refresh token from a previous run")
    parser.add_argument("--interval", type=int, default=60, help="seconds between polls (default 60, minimum 30)")
    parser.add_argument("--once", action="store_true", help="dump the current state once and exit")
    parser.add_argument("--out", default="delivery-discovery.jsonl", help="file to append every change to")
    parser.add_argument("--show-ids", action="store_true", help="do not mask order ids")
    args = parser.parse_args()

    if not args.code and not args.refresh_token:
        parser.error(f"pass a code or --refresh-token; get a code via:\n  {AUTHORIZE_URL}")

    interval = max(30, args.interval)
    out = Path(args.out)
    ids: dict[str, str] = {}
    previous = None

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        client = AhApiClient(session, refresh_token=args.refresh_token)
        try:
            if args.code:
                await client.async_exchange_code(extract_code(args.code))
            print(f"polling every {interval} s, changes are appended to {out} — stop with Ctrl-C\n")
            while True:
                try:
                    current = await snapshot(session, client)
                except AhApiError as err:
                    current = {"failed": repr(err)}
                if not args.show_ids:
                    for order_id in current.get("orders", {}):
                        ids.setdefault(order_id, f"order-{len(ids) + 1}")
                    current = mask_ids(current, ids)
                stamp = datetime.now().astimezone().isoformat(timespec="seconds")
                if current != previous:
                    print(f"=== {stamp} ===")
                    print(json.dumps(current, indent=2, ensure_ascii=False))
                    with out.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps({"at": stamp, **current}, ensure_ascii=False) + "\n")
                    previous = current
                else:
                    print(f"    {stamp}  no change")
                if args.once:
                    return
                await asyncio.sleep(interval)
        finally:
            # Always print, even on a crash or Ctrl-C: the token may have rotated.
            print("\nrefresh token for next run (keep private!):")
            print(f"  {client.refresh_token}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
