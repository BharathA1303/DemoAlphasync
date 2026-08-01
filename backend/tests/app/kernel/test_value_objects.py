from decimal import Decimal

import pytest

from app.kernel.value_objects import CanonicalSymbol, Money, Price, Quantity


class TestCanonicalSymbol:
    def test_construct_and_normalizes_case(self) -> None:
        symbol = CanonicalSymbol(exchange="nse", segment="eq", ticker="reliance")
        assert symbol.exchange == "NSE"
        assert symbol.segment == "EQ"
        assert symbol.ticker == "RELIANCE"

    def test_str_representation(self) -> None:
        symbol = CanonicalSymbol(exchange="NSE", segment="EQ", ticker="RELIANCE")
        assert str(symbol) == "NSE:EQ:RELIANCE"

    def test_parse_valid_string(self) -> None:
        symbol = CanonicalSymbol.parse("NSE:EQ:RELIANCE")
        assert symbol == CanonicalSymbol(exchange="NSE", segment="EQ", ticker="RELIANCE")

    def test_parse_lowercase_string_normalizes(self) -> None:
        symbol = CanonicalSymbol.parse("nse:eq:reliance")
        assert symbol.ticker == "RELIANCE"

    @pytest.mark.parametrize("raw", ["NSE:EQ", "NSE:EQ:RELIANCE:EXTRA", "", "NOCOLONS"])
    def test_parse_invalid_format_raises(self, raw: str) -> None:
        with pytest.raises(ValueError):
            CanonicalSymbol.parse(raw)

    @pytest.mark.parametrize(
        "exchange,segment,ticker", [("", "EQ", "RELIANCE"), ("NSE", "", "RELIANCE"), ("NSE", "EQ", "")]
    )
    def test_construct_with_blank_field_raises(self, exchange: str, segment: str, ticker: str) -> None:
        with pytest.raises(ValueError):
            CanonicalSymbol(exchange=exchange, segment=segment, ticker=ticker)

    def test_equality_is_value_based(self) -> None:
        a = CanonicalSymbol(exchange="NSE", segment="EQ", ticker="RELIANCE")
        b = CanonicalSymbol.parse("NSE:EQ:RELIANCE")
        assert a == b
        assert hash(a) == hash(b)


class TestMoney:
    def test_construct_coerces_amount_to_decimal(self) -> None:
        money = Money(amount=100)  # type: ignore[arg-type]
        assert money.amount == Decimal("100")
        assert isinstance(money.amount, Decimal)

    def test_default_currency_is_inr(self) -> None:
        assert Money(amount=Decimal("10")).currency == "INR"

    def test_add_same_currency(self) -> None:
        result = Money(amount=Decimal("100")).add(Money(amount=Decimal("50")))
        assert result == Money(amount=Decimal("150"))

    def test_subtract_same_currency(self) -> None:
        result = Money(amount=Decimal("100")).subtract(Money(amount=Decimal("30")))
        assert result == Money(amount=Decimal("70"))

    def test_add_different_currency_raises(self) -> None:
        with pytest.raises(ValueError):
            Money(amount=Decimal("100"), currency="INR").add(Money(amount=Decimal("10"), currency="USD"))

    def test_subtract_different_currency_raises(self) -> None:
        with pytest.raises(ValueError):
            Money(amount=Decimal("100"), currency="INR").subtract(Money(amount=Decimal("10"), currency="USD"))

    def test_subtract_can_go_negative(self) -> None:
        """Money itself doesn't forbid negative balances — that's a
        portfolio-level risk concern, not a value-object concern."""
        result = Money(amount=Decimal("10")).subtract(Money(amount=Decimal("50")))
        assert result.amount == Decimal("-40")


class TestPrice:
    def test_construct_coerces_to_decimal(self) -> None:
        price = Price(value=100.5)  # type: ignore[arg-type]
        assert price.value == Decimal("100.5")

    def test_zero_price_is_allowed(self) -> None:
        assert Price(value=Decimal("0")).value == Decimal("0")

    def test_negative_price_raises(self) -> None:
        with pytest.raises(ValueError):
            Price(value=Decimal("-1"))

    def test_float_conversion(self) -> None:
        assert float(Price(value=Decimal("99.99"))) == pytest.approx(99.99)


class TestQuantity:
    def test_positive_quantity_is_valid(self) -> None:
        assert Quantity(value=10).value == 10

    def test_zero_quantity_raises(self) -> None:
        with pytest.raises(ValueError):
            Quantity(value=0)

    def test_negative_quantity_raises(self) -> None:
        with pytest.raises(ValueError):
            Quantity(value=-5)

    def test_int_conversion(self) -> None:
        assert int(Quantity(value=42)) == 42
