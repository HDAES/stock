from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class Position:
    symbol: str
    quantity: int
    avg_price: float
    entry_time: str
    last_price: float
    unrealized_pnl: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "avg_price": self.avg_price,
            "entry_time": self.entry_time,
            "last_price": self.last_price,
            "unrealized_pnl": self.unrealized_pnl,
        }


@dataclass
class PaperPortfolio:
    cash: float
    initial_cash: float
    day: str
    day_start_equity: float
    realized_pnl: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    trades: list[dict[str, Any]] = field(default_factory=list)
    last_signals: list[dict[str, Any]] = field(default_factory=list)
    daily_stop: bool = False
    processed_intraday_bars: dict[str, str] = field(default_factory=dict)

    @classmethod
    def empty(cls, initial_cash: float, day: str | None = None) -> "PaperPortfolio":
        current_day = day or datetime.now().date().isoformat()
        return cls(
            cash=initial_cash,
            initial_cash=initial_cash,
            day=current_day,
            day_start_equity=initial_cash,
        )

    @classmethod
    def load(cls, path: str | Path, initial_cash: float, day: str | None = None) -> "PaperPortfolio":
        state_path = Path(path)
        current_day = day or datetime.now().date().isoformat()
        if not state_path.exists():
            return cls.empty(initial_cash, current_day)

        data = json.loads(state_path.read_text())
        positions = {
            symbol: Position(
                symbol=symbol,
                quantity=int(raw["quantity"]),
                avg_price=float(raw["avg_price"]),
                entry_time=str(raw["entry_time"]),
                last_price=float(raw.get("last_price", raw["avg_price"])),
                unrealized_pnl=float(raw.get("unrealized_pnl", 0.0)),
            )
            for symbol, raw in data.get("positions", {}).items()
        }
        portfolio = cls(
            cash=float(data.get("cash", initial_cash)),
            initial_cash=float(data.get("initial_cash", initial_cash)),
            day=str(data.get("day", current_day)),
            day_start_equity=float(data.get("day_start_equity", initial_cash)),
            realized_pnl=float(data.get("realized_pnl", 0.0)),
            positions=positions,
            trades=list(data.get("trades", [])),
            last_signals=list(data.get("last_signals", [])),
            daily_stop=bool(data.get("daily_stop", False)),
            processed_intraday_bars={
                str(symbol).upper(): str(timestamp)
                for symbol, timestamp in data.get("processed_intraday_bars", {}).items()
            },
        )
        if portfolio.day != current_day:
            portfolio.day = current_day
            portfolio.day_start_equity = portfolio.equity()
            portfolio.daily_stop = False
        return portfolio

    def save(self, path: str | Path) -> None:
        state_path = Path(path)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(self.to_dict(), indent=2))

    def mark(self, prices: dict[str, float]) -> None:
        for symbol, price in prices.items():
            position = self.positions.get(symbol)
            if position is None:
                continue
            position.last_price = price
            position.unrealized_pnl = (price - position.avg_price) * position.quantity

    def equity(self) -> float:
        return self.cash + sum(position.last_price * position.quantity for position in self.positions.values())

    def daily_loss_pct(self) -> float:
        if self.day_start_equity <= 0:
            return 0.0
        return self.equity() / self.day_start_equity - 1.0

    def refresh_daily_stop(self, max_daily_loss_pct: float) -> bool:
        self.daily_stop = self.daily_loss_pct() <= -max_daily_loss_pct
        return self.daily_stop

    def buy(
        self,
        symbol: str,
        price: float,
        timestamp: str,
        max_position_pct: float,
        reason: str,
    ) -> dict[str, Any] | None:
        if symbol in self.positions or price <= 0:
            return None
        allocation = min(self.cash, self.equity() * max_position_pct)
        quantity = int(allocation // price)
        if quantity < 1:
            return None
        cost = quantity * price
        self.cash -= cost
        self.positions[symbol] = Position(
            symbol=symbol,
            quantity=quantity,
            avg_price=price,
            entry_time=timestamp,
            last_price=price,
        )
        trade = {
            "timestamp": timestamp,
            "symbol": symbol,
            "side": "BUY",
            "quantity": quantity,
            "price": price,
            "value": cost,
            "reason": reason,
        }
        self.trades.append(trade)
        return trade

    def record_buy(
        self,
        symbol: str,
        quantity: int,
        price: float,
        timestamp: str,
        reason: str,
        source: str = "shadow",
    ) -> dict[str, Any] | None:
        if symbol in self.positions or price <= 0 or quantity < 1:
            return None
        cost = quantity * price
        self.cash -= cost
        self.positions[symbol] = Position(
            symbol=symbol,
            quantity=quantity,
            avg_price=price,
            entry_time=timestamp,
            last_price=price,
        )
        trade = {
            "timestamp": timestamp,
            "symbol": symbol,
            "side": "BUY",
            "quantity": quantity,
            "price": price,
            "value": cost,
            "reason": reason,
            "source": source,
        }
        self.trades.append(trade)
        return trade

    def sell(self, symbol: str, price: float, timestamp: str, reason: str) -> dict[str, Any] | None:
        position = self.positions.pop(symbol, None)
        if position is None or price <= 0:
            return None
        proceeds = position.quantity * price
        pnl = (price - position.avg_price) * position.quantity
        self.cash += proceeds
        self.realized_pnl += pnl
        trade = {
            "timestamp": timestamp,
            "symbol": symbol,
            "side": "SELL",
            "quantity": position.quantity,
            "price": price,
            "value": proceeds,
            "realized_pnl": pnl,
            "reason": reason,
        }
        self.trades.append(trade)
        return trade

    def record_sell(
        self,
        symbol: str,
        quantity: int,
        price: float,
        timestamp: str,
        reason: str,
        source: str = "shadow",
    ) -> dict[str, Any] | None:
        if price <= 0 or quantity < 1:
            return None
        position = self.positions.pop(symbol, None)
        proceeds = quantity * price
        pnl = None
        if position is not None:
            pnl = (price - position.avg_price) * min(quantity, position.quantity)
            self.realized_pnl += pnl
        self.cash += proceeds
        trade = {
            "timestamp": timestamp,
            "symbol": symbol,
            "side": "SELL",
            "quantity": quantity,
            "price": price,
            "value": proceeds,
            "reason": reason,
            "source": source,
        }
        if pnl is not None:
            trade["realized_pnl"] = pnl
        self.trades.append(trade)
        return trade

    def to_dict(self) -> dict[str, Any]:
        equity = self.equity()
        return {
            "cash": self.cash,
            "initial_cash": self.initial_cash,
            "equity": equity,
            "day": self.day,
            "day_start_equity": self.day_start_equity,
            "daily_loss_pct": self.daily_loss_pct(),
            "daily_stop": self.daily_stop,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": sum(position.unrealized_pnl for position in self.positions.values()),
            "positions": {symbol: position.to_dict() for symbol, position in self.positions.items()},
            "trades": self.trades[-100:],
            "last_signals": self.last_signals[-100:],
            "processed_intraday_bars": self.processed_intraday_bars,
        }
