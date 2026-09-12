from .base import Base


class Child(Base):
    def _hook(self):
        return 1
