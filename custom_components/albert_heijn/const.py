"""Constants for the Albert Heijn integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "albert_heijn"

API_BASE: Final = "https://api.ah.nl"
TOKEN_URL: Final = f"{API_BASE}/mobile-auth/v1/auth/token"
TOKEN_REFRESH_URL: Final = f"{API_BASE}/mobile-auth/v1/auth/token/refresh"
GRAPHQL_URL: Final = f"{API_BASE}/graphql"

CLIENT_ID: Final = "appie"
AUTHORIZE_URL: Final = (
    "https://login.ah.nl/secure/oauth/authorize"
    "?client_id=appie&redirect_uri=appie%3A%2F%2Flogin-exit&response_type=code"
)

# Content-Type is set by aiohttp's json= parameter.
DEFAULT_HEADERS: Final = {
    "Accept": "application/json",
    "User-Agent": "Appie/8.22.3",
    "X-Application": "AHWEBSHOP",
}

CONF_CODE: Final = "code"
CONF_REFRESH_TOKEN: Final = "refresh_token"
CONF_MEMBER_ID: Final = "member_id"
CONF_UPDATE_INTERVAL: Final = "update_interval"  # hours, options flow
CONF_LIST_ENABLED: Final = "list_enabled"  # options flow, opt-in
CONF_LIST_SCAN_INTERVAL: Final = "list_scan_interval"  # seconds, options flow
CONF_SYNC_TARGET_ENTITY: Final = "sync_target_entity"  # options flow, optional todo entity_id

DEFAULT_UPDATE_INTERVAL_HOURS: Final = 6
MIN_UPDATE_INTERVAL_HOURS: Final = 1
MAX_UPDATE_INTERVAL_HOURS: Final = 24
DEFAULT_UPDATE_INTERVAL: Final = timedelta(hours=DEFAULT_UPDATE_INTERVAL_HOURS)
DEFAULT_LIST_SCAN_INTERVAL: Final = 120  # seconds
MIN_LIST_SCAN_INTERVAL: Final = 60
MAX_LIST_SCAN_INTERVAL: Final = 3600
TOKEN_EXPIRY_MARGIN: Final = 60  # seconds before expiry at which we refresh proactively
REQUEST_TIMEOUT: Final = 30  # seconds

# Koopzegels constants: a stamp costs EUR 0.49, a full booklet is 490 stamps.
DEFAULT_FULL_BOOKLET_TARGET: Final = 490

# --- GraphQL ---
# The AH GraphQL schema is unofficial and may change. Everything schema-dependent
# lives in these constants plus the parser in api.py; a schema change should be
# fixable here alone. Reference: gwillem/appie-go doc/graphql-schema-*.md.

KOOPZEGELS_OPERATION: Final = "HaKoopzegelsBalance"
KOOPZEGELS_QUERY: Final = """\
query HaKoopzegelsBalance {
  purchaseStampBalance {
    points {
      totalPoints
      currentBookletPoints
      fullBooklets
    }
    money {
      invested { amount }
      interest { amount }
      payout { amount }
    }
    constants {
      fullBookletTarget { points }
    }
  }
}
"""

MEMBER_ID_OPERATION: Final = "HaMemberId"
MEMBER_ID_QUERY: Final = """\
query HaMemberId {
  member {
    id
  }
}
"""

# Same operation/query as the app (via gwillem/appie-go, verified there against live).
RECEIPTS_OPERATION: Final = "FetchPosReceipts"
RECEIPTS_QUERY: Final = """\
query FetchPosReceipts($offset: Int!, $limit: Int!) {
  posReceiptsPage(pagination: {offset: $offset, limit: $limit}) {
    posReceipts {
      id
      dateTime
      totalAmount {
        amount
      }
    }
  }
}
"""
RECEIPTS_PAGE_LIMIT: Final = 100

MILES_OPERATION: Final = "HaMilesBalance"
MILES_QUERY: Final = """\
query HaMilesBalance {
  milesBalance {
    balance
    errorState
  }
}
"""

PREMIUM_SAVINGS_OPERATION: Final = "HaPremiumSavings"
PREMIUM_SAVINGS_QUERY: Final = """\
query HaPremiumSavings {
  subscriptionPremiumSavingsV2 {
    totalSavedAmount {
      amount
    }
  }
}
"""

SETTLEMENTS_OPERATION: Final = "HaSettlementsTotal"
SETTLEMENTS_QUERY: Final = """\
query HaSettlementsTotal {
  settlementsTotal {
    totalAmount {
      amount
    }
  }
}
"""

SAVING_GOAL_OPERATION: Final = "HaSavingGoal"
SAVING_GOAL_QUERY: Final = """\
query HaSavingGoal {
  purchaseStampSavingGoal {
    name
    amount {
      amount
    }
  }
}
"""

BASKET_OPERATION: Final = "HaBasket"
BASKET_QUERY: Final = """\
query HaBasket {
  basket {
    summary {
      quantity
      price {
        totalPrice {
          amount
        }
      }
    }
  }
}
"""

DELIVERIES_OPERATION: Final = "HaOrderFulfillments"
DELIVERIES_QUERY: Final = """\
query HaOrderFulfillments {
  orderFulfillments {
    result {
      orderId
      transactionCompleted
      delivery {
        status
        slot {
          date
          startTime
          endTime
        }
      }
    }
  }
}
"""

# --- Shopping list ("Mijn lijst") ---
# CONFIRMED against the live API on 2026-07-14 (scripts/discover_list.py):
# - The shopping list is one per-account resource in the shoppinglist v2
#   service. It is NOT a lists-v3 list (those are favorites), and GraphQL's
#   favoriteListV2 cannot see free-text items at all — REST is the only path.
# - READ: GET SHOPPINGLIST_ITEMS_URL -> {id, items: [...]}; item fields:
#   listItemId (0 for free text), description, quantity, strikedthrough,
#   type, originCode ("TXT" on read), position.
# - WRITE: everything is PATCH on the same URL with {"items": [...]} in the
#   *write* shape {description, quantity, type: "SHOPPABLE", originCode:
#   "PRD", strikeThrough: bool, productId?}. The server merges by
#   description/product, so add and check/uncheck are the same call, and
#   quantity 0 deletes. Echoing the read-shape names back (originCode "TXT",
#   "strikedthrough") is rejected with HTTP 400 "Failed to read request".
# - No other routes exist: Allow is GET,HEAD,PATCH,OPTIONS and the /items/{id}
#   and v1 paths 404.

SHOPPINGLIST_ITEMS_URL: Final = f"{API_BASE}/mobile-services/shoppinglist/v2/items"
