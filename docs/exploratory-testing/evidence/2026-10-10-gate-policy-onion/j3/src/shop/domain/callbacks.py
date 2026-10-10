"""Injected collaborators. Only mutator-named calls should be actions."""


def notify(order) -> None:
    return None


def record(repo, order) -> None:
    repo.add(order)
    notify(order)
    repo.save(order)
