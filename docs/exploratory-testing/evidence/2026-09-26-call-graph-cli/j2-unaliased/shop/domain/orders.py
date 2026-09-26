import shop.infra.repository
from shop.infra.repository import save
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from shop.infra.models import OrderRecord

def persist(order):
    shop.infra.repository.save(order)
    save(order)
