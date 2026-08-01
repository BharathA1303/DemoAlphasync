import pytest

from app.kernel.ids import (
    InstrumentId,
    OrderId,
    PortfolioId,
    PositionId,
    SessionId,
    UserId,
    UUIDv7Generator,
)


class TestUUIDv7Generator:
    def test_generate_without_prefix_returns_bare_id(self) -> None:
        generator = UUIDv7Generator()
        value = generator.generate()
        assert value
        assert "_" not in value

    def test_generate_with_prefix_prefixes_the_id(self) -> None:
        generator = UUIDv7Generator()
        value = generator.generate(prefix="ord")
        assert value.startswith("ord_")

    def test_generate_produces_unique_values(self) -> None:
        generator = UUIDv7Generator()
        values = {generator.generate(prefix="x") for _ in range(1000)}
        assert len(values) == 1000

    def test_generate_is_time_sortable(self) -> None:
        """UUIDv7 IDs generated in sequence should sort lexically in
        generation order (the whole point of using UUIDv7 over UUIDv4)."""
        import time

        generator = UUIDv7Generator()
        first = generator.generate(prefix="ord")
        time.sleep(0.002)
        second = generator.generate(prefix="ord")
        assert first < second


class TestTypedIds:
    def test_order_id_new_generates_prefixed_value(self) -> None:
        order_id = OrderId.new()
        assert order_id.value.startswith("ord_")
        assert str(order_id) == order_id.value

    def test_user_id_new_generates_prefixed_value(self) -> None:
        user_id = UserId.new()
        assert user_id.value.startswith("usr_")
        assert str(user_id) == user_id.value

    def test_session_id_new_generates_prefixed_value(self) -> None:
        session_id = SessionId.new()
        assert session_id.value.startswith("ses_")
        assert str(session_id) == session_id.value

    def test_instrument_id_new_generates_prefixed_value(self) -> None:
        instrument_id = InstrumentId.new()
        assert instrument_id.value.startswith("ins_")
        assert str(instrument_id) == instrument_id.value

    def test_portfolio_id_new_generates_prefixed_value(self) -> None:
        portfolio_id = PortfolioId.new()
        assert portfolio_id.value.startswith("port_")
        assert str(portfolio_id) == portfolio_id.value

    def test_position_id_new_generates_prefixed_value(self) -> None:
        position_id = PositionId.new()
        assert position_id.value.startswith("pos_")
        assert str(position_id) == position_id.value

    def test_typed_ids_are_frozen_dataclasses(self) -> None:
        order_id = OrderId.new()
        with pytest.raises(AttributeError):
            order_id.value = "mutated"  # type: ignore[misc]

    def test_typed_ids_are_value_comparable(self) -> None:
        assert OrderId(value="ord_1") == OrderId(value="ord_1")
        assert OrderId(value="ord_1") != OrderId(value="ord_2")

    def test_different_id_types_are_not_interchangeable(self) -> None:
        """A UserId and an OrderId with the same underlying string must
        never compare equal — this is the whole point of typed IDs
        (no primitive obsession, per the frozen spec). mypy statically
        flags this comparison as non-overlapping, which is itself proof
        the two types are not interchangeable at the type level either."""
        order_id = OrderId(value="same_value")
        user_id = UserId(value="same_value")
        assert order_id != user_id  # type: ignore[comparison-overlap]
