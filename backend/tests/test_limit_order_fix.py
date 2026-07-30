"""
Test to verify that limit orders are NOT filled immediately
without hitting the specified price.

This test validates the fix for the limit order bug where orders
were being filled immediately without waiting for the market price
to reach the limit price.
"""
import pytest
import uuid
from decimal import Decimal
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models.order import Order
from models.user import User
from models.portfolio import Portfolio
from services.trading_engine import place_order, _to_decimal


class TestLimitOrderBug:
    """
    Test suite for the limit order immediate fill bug.
    
    Bug: Limit orders were filled immediately without checking if market
    price actually reached the limit price.
    
    Root cause: The `place_order` function was using stale `client_price`
    from the order request instead of fetching fresh market data for LIMIT orders.
    
    Fix: For LIMIT orders, always fetch fresh market data before evaluating
    whether the order should fill immediately.
    """

    @pytest.mark.asyncio
    async def test_buy_limit_order_not_filled_immediately_when_price_above_limit(
        self, db: AsyncSession, test_user: User, mock_market_data
    ):
        """
        Test: BUY LIMIT order should NOT fill immediately when market price is above limit.
        
        Scenario:
        - Current market price: ₹1350
        - User places BUY LIMIT order at: ₹1340
        - Expected: Order status = OPEN (not filled)
        - Reason: Market price (1350) > limit price (1340), so order should wait
        """
        symbol = "NSEEQUITY|NSE|INFY"
        current_market_price = 1350
        limit_price = 1340
        
        # Mock market data to return current price
        mock_market_data.get_quote_safe.return_value = {
            "price": current_market_price,
            "name": "Infosys"
        }
        
        # Place BUY LIMIT order
        result = await place_order(
            db=db,
            user_id=test_user.id,
            symbol=symbol,
            side="BUY",
            order_type="LIMIT",
            quantity=1,
            price=limit_price,
            client_price=current_market_price,  # Note: client_price is same as current market
            product_type="CNC"
        )
        
        assert result["success"], f"Order placement failed: {result.get('error')}"
        
        # Verify order was created but NOT filled
        order_query = select(Order).where(Order.id == uuid.UUID(result["order_id"]))
        order_result = await db.execute(order_query)
        order = order_result.scalar_one_or_none()
        
        assert order is not None, "Order was not created"
        assert order.status == "OPEN", f"Expected OPEN, got {order.status}. Order should NOT fill when market price > limit for BUY"
        assert order.filled_quantity == 0, "Order should not be filled"
        assert order.filled_price is None, "Order should not have a filled price"

    @pytest.mark.asyncio
    async def test_buy_limit_order_fills_when_price_below_limit(
        self, db: AsyncSession, test_user: User, mock_market_data
    ):
        """
        Test: BUY LIMIT order SHOULD fill immediately when market price is at/below limit.
        
        Scenario:
        - Current market price: ₹1330
        - User places BUY LIMIT order at: ₹1340
        - Expected: Order status = FILLED (immediately)
        - Reason: Market price (1330) <= limit price (1340), so order fills at limit price
        """
        symbol = "NSEEQUITY|NSE|INFY"
        current_market_price = 1330
        limit_price = 1340
        
        # Mock market data to return current price
        mock_market_data.get_quote_safe.return_value = {
            "price": current_market_price,
            "name": "Infosys"
        }
        
        # Place BUY LIMIT order
        result = await place_order(
            db=db,
            user_id=test_user.id,
            symbol=symbol,
            side="BUY",
            order_type="LIMIT",
            quantity=1,
            price=limit_price,
            client_price=1350,  # Note: client_price is higher than actual current price
            product_type="CNC"
        )
        
        assert result["success"], f"Order placement failed: {result.get('error')}"
        
        # Verify order was filled immediately at limit price
        order_query = select(Order).where(Order.id == uuid.UUID(result["order_id"]))
        order_result = await db.execute(order_query)
        order = order_result.scalar_one_or_none()
        
        assert order is not None, "Order was not created"
        assert order.status == "FILLED", f"Expected FILLED, got {order.status}. Order SHOULD fill when market price <= limit for BUY"
        assert order.filled_quantity == 1, "Order should be fully filled"
        assert order.filled_price == _to_decimal(limit_price), f"Order should be filled at limit price {limit_price}, got {order.filled_price}"

    @pytest.mark.asyncio
    async def test_sell_limit_order_not_filled_immediately_when_price_below_limit(
        self, db: AsyncSession, test_user: User, mock_market_data
    ):
        """
        Test: SELL LIMIT order should NOT fill immediately when market price is below limit.
        
        Scenario:
        - Current market price: ₹1330
        - User places SELL LIMIT order at: ₹1340
        - Expected: Order status = OPEN (not filled)
        - Reason: Market price (1330) < limit price (1340), so order should wait for price to rise
        """
        symbol = "NSEEQUITY|NSE|INFY"
        current_market_price = 1330
        limit_price = 1340
        
        # Mock market data to return current price
        mock_market_data.get_quote_safe.return_value = {
            "price": current_market_price,
            "name": "Infosys"
        }
        
        # Place SELL LIMIT order
        result = await place_order(
            db=db,
            user_id=test_user.id,
            symbol=symbol,
            side="SELL",
            order_type="LIMIT",
            quantity=1,
            price=limit_price,
            client_price=current_market_price,
            product_type="MIS"
        )
        
        assert result["success"], f"Order placement failed: {result.get('error')}"
        
        # Verify order was created but NOT filled
        order_query = select(Order).where(Order.id == uuid.UUID(result["order_id"]))
        order_result = await db.execute(order_query)
        order = order_result.scalar_one_or_none()
        
        assert order is not None, "Order was not created"
        assert order.status == "OPEN", f"Expected OPEN, got {order.status}. Order should NOT fill when market price < limit for SELL"
        assert order.filled_quantity == 0, "Order should not be filled"

    @pytest.mark.asyncio
    async def test_sell_limit_order_fills_when_price_above_limit(
        self, db: AsyncSession, test_user: User, mock_market_data
    ):
        """
        Test: SELL LIMIT order SHOULD fill immediately when market price is at/above limit.
        
        Scenario:
        - Current market price: ₹1350
        - User places SELL LIMIT order at: ₹1340
        - Expected: Order status = FILLED (immediately)
        - Reason: Market price (1350) >= limit price (1340), so order fills at limit price
        """
        symbol = "NSEEQUITY|NSE|INFY"
        current_market_price = 1350
        limit_price = 1340
        
        # Mock market data to return current price
        mock_market_data.get_quote_safe.return_value = {
            "price": current_market_price,
            "name": "Infosys"
        }
        
        # Place SELL LIMIT order
        result = await place_order(
            db=db,
            user_id=test_user.id,
            symbol=symbol,
            side="SELL",
            order_type="LIMIT",
            quantity=1,
            price=limit_price,
            client_price=1330,  # Note: client_price is lower than actual current price
            product_type="MIS"
        )
        
        assert result["success"], f"Order placement failed: {result.get('error')}"
        
        # Verify order was filled immediately at limit price
        order_query = select(Order).where(Order.id == uuid.UUID(result["order_id"]))
        order_result = await db.execute(order_query)
        order = order_result.scalar_one_or_none()
        
        assert order is not None, "Order was not created"
        assert order.status == "FILLED", f"Expected FILLED, got {order.status}. Order SHOULD fill when market price >= limit for SELL"
        assert order.filled_quantity == 1, "Order should be fully filled"
        assert order.filled_price == _to_decimal(limit_price), f"Order should be filled at limit price {limit_price}"

    @pytest.mark.asyncio
    async def test_bracket_order_uses_fresh_quote_not_client_price(
        self, db: AsyncSession, test_user: User, mock_market_data
    ):
        """
        Test: BRACKET orders (which include LIMIT leg) should also use fresh market data.
        
        This ensures the bug fix applies to all order types with LIMIT components.
        """
        symbol = "NSEEQUITY|NSE|TCS"
        current_market_price = 3500
        limit_price = 3480  # Below current price
        sl_price = 3400
        tp_price = 3600
        
        # Mock market data to return current price
        mock_market_data.get_quote_safe.return_value = {
            "price": current_market_price,
            "name": "TCS"
        }
        
        # Place BRACKET order
        result = await place_order(
            db=db,
            user_id=test_user.id,
            symbol=symbol,
            side="BUY",
            order_type="BRACKET",
            quantity=1,
            price=limit_price,  # Limit is below current price
            trigger_price=sl_price,
            take_profit_price=tp_price,
            client_price=current_market_price,
            product_type="MIS"
        )
        
        assert result["success"], f"Order placement failed: {result.get('error')}"
        
        # Parent order should NOT fill (limit above current)
        order_query = select(Order).where(Order.id == uuid.UUID(result["order_id"]))
        order_result = await db.execute(order_query)
        order = order_result.scalar_one_or_none()
        
        assert order is not None, "Order was not created"
        assert order.status == "OPEN", f"BRACKET entry should be OPEN when market > limit, got {order.status}"


# Expected behavior summary after fix:
# ================================
# BUY LIMIT at price X:
#   - Market price < X → FILLED immediately (good for buyer)
#   - Market price = X → FILLED immediately
#   - Market price > X → OPEN (waiting for price to drop)
#
# SELL LIMIT at price X:
#   - Market price < X → OPEN (waiting for price to rise)
#   - Market price = X → FILLED immediately
#   - Market price > X → FILLED immediately (good for seller)
