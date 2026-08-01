import pytest
from decimal import Decimal
from app.kernel.ids import OrderId, UserId, SessionId
from app.kernel.value_objects import CanonicalSymbol, Money, Price, Quantity
from app.kernel.primitives import Result


def test_canonical_symbol_parse_valid():
    sym = CanonicalSymbol.parse("nse:eq:reliance")
    assert sym.exchange == "NSE"
    assert sym.segment == "EQ"
    assert sym.ticker == "RELIANCE"
    assert str(sym) == "NSE:EQ:RELIANCE"


def test_canonical_symbol_parse_invalid():
    with pytest.raises(ValueError):
        CanonicalSymbol.parse("INVALID_SYMBOL")


def test_money_operations():
    m1 = Money(amount=Decimal("500.00"), currency="INR")
    m2 = Money(amount=Decimal("250.50"), currency="INR")
    sum_m = m1.add(m2)
    assert sum_m.amount == Decimal("750.50")
    assert sum_m.currency == "INR"


def test_price_validation():
    p = Price(value=Decimal("1500.75"))
    assert float(p) == 1500.75
    with pytest.raises(ValueError):
        Price(value=Decimal("-10.00"))


def test_quantity_validation():
    q = Quantity(value=100)
    assert int(q) == 100
    with pytest.raises(ValueError):
        Quantity(value=0)


def test_uuidv7_typed_ids():
    ord_id1 = OrderId.new()
    ord_id2 = OrderId.new()
    assert str(ord_id1).startswith("ord_")
    assert str(ord_id2).startswith("ord_")
    assert ord_id1 != ord_id2


def test_result_primitive():
    res_ok = Result.ok("SUCCESS")
    assert res_ok.is_success
    assert res_ok.value() == "SUCCESS"

    err = ValueError("Something failed")
    res_fail = Result.fail(err)
    assert res_fail.is_failure
    assert res_fail.error() == err
