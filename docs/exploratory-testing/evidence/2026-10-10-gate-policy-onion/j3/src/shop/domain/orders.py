"""Domain module that has drifted into actions and outer imports."""

from __future__ import annotations

import requests
from typing import TYPE_CHECKING

from ..infra.repository import OrderRepository

if TYPE_CHECKING:
    from shop.web.api import OrderView


def save_report(order: OrderView) -> None:
    print(order)


def publish(order: OrderView) -> None:
    save_report(order)


def load_for_checkout(order_id: str) -> str:
    import sqlalchemy

    return sqlalchemy.text(order_id)


class Order:
    def __init__(self, total: float) -> None:
        self.total = total

    def apply_discount(self, rate: float) -> None:
        self.total = self.total * (1 - rate)

    def discounted(self, rate: float) -> float:
        return self.total * (1 - rate)
