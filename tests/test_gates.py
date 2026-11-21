import pytest

from leadgen.compliance import gates
from leadgen.db import connect, init_db


@pytest.fixture()
def conn():
    c = connect(":memory:")
    init_db(c)
    return c


@pytest.mark.parametrize("dnc_input,query_input", [
    ("+15125550100", "+15125550100"),
    ("(512) 555-0100", "+15125550100"),
    ("512-555-0100", "+15125550100"),
    ("512.555.0100", "+15125550100"),
    ("5125550100", "+15125550100"),
    ("15125550100", "+15125550100"),
    ("+1 (512) 555-0100", "+15125550100"),
    ("+15125550100", "(512) 555-0100"),
    ("+15125550100", "5125550100"),
    ("+15125550100", "512-555-0100"),
])
def test_dnc_format_matching(conn, dnc_input, query_input):
    """Verify DNC matching works regardless of punctuation, parenthesis, dashes, or national prefix."""
    gates.add_dnc(conn, dnc_input)
    assert gates.is_dnc(conn, query_input)
    assert not gates.is_dnc(conn, "+15125550999")
