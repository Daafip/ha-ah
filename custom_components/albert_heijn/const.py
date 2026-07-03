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

UPDATE_INTERVAL: Final = timedelta(hours=6)
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
