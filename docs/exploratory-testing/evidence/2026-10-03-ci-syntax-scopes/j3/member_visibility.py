class BaseService:
    def public_entry(self):
        return 1

class ExtendedService(BaseService):
    def __init__(self):
        self._active_field = 1
        self._dead_field = 2

    def _unused_private(self):
        return self._active_field

    def public_worker(self):
        return self._active_field

class ContractProtocol:
    def abstract_method(self, unused_param: int) -> int:
        ...

    def empty_method(self, dead_param: str) -> None:
        pass
