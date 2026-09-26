import shop.infra.repository as repository
from shop.infra.repository import save as save_order
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from shop.infra.models import OrderRecord as ModelOrder

def persist(order):
    repository.save(order)
    save_order(order)
