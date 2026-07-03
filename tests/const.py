"""Shared, anonymised test constants."""

import json
from pathlib import Path

from custom_components.albert_heijn.api import KoopzegelsData

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


TOKEN_RESPONSE = load_fixture("token.json")
KOOPZEGELS_RESPONSE = load_fixture("koopzegels.json")

REFRESH_TOKEN = TOKEN_RESPONSE["refresh_token"]
MEMBER_ID = "1234567"
MEMBER_RESPONSE = {"data": {"member": {"id": 1234567}}}

KOOPZEGELS_DATA = KoopzegelsData(
    payout=510.7,
    invested=504.7,
    interest=6.0,
    stamp_count=1030,
    booklet_stamps=50,
    full_booklets=2,
    full_booklet_target=490,
)
