from abc import abstractmethod

class Delivery:
    def __init__(self, status, reference, recipient):
        self._status = status
        self._reference = reference
        self._recipient = recipient

    def mark_sent(self):
        self._status = "sent"

    @property
    def reference(self):
        return self._reference

    @property
    def recipient(self):
        return self._recipient

    @staticmethod
    def default_carrier():
        return "post"

    @classmethod
    def from_reference(cls, reference):
        return cls("queued", reference, "")

    @abstractmethod
    def track(self):
        ...
