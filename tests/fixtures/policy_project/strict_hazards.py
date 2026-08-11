import sys


class Service:
    @staticmethod
    def execute():
        return None


def strict_checks(values, unused_parameter, enabled: bool):
    ab = len(values)
    Service.execute()
    while len(values) > ab:
        break
    if enabled:
        return ab
    else:
        sys.exit(1)
