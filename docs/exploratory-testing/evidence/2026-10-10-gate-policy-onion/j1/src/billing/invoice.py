"""Invoice drafting. Intentionally a bit messy."""

import pdb

TAX_RATE = 0.2


def draft_total(invoice, include_tax_breakdown_for_regional_rules):
    unused_preview = invoice.amount
    # TODO: drop the legacy surcharge once finance signs off
    try:
        total = invoice.amount * (1 + TAX_RATE)
    except Exception:
        pass
    if (status := invoice.status) == "open":
        pdb.set_trace()
        return total
    return invoice.amount


class InvoiceDraft:
    def __init__(self, amount):
        self.amount = amount
        self._cached_tax = None

    def _render_footer(self):
        return "footer"

    def total(self):
        return self.amount
