"""Names a team would tune."""


def draft_total(invoice, include_tax_breakdown_for_regional_rules):
    # TODO: finance still wants this marker ignored by the team policy
    return invoice.amount
