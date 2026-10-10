"""Import-time calls a domain module should not make."""


def save_report(order: str) -> None:
    print(order)


def publish(order: str) -> None:
    save_report(order)


publish("boot")
