"""Imported metaclass, the case CouplingBetweenObjects documents as a reference."""

from review.types import CustomMeta, Marker


class Service(metaclass=CustomMeta):
    def run(self):
        return 1


class Movie(total=Marker):
    title: str


class Quiet:
    def run(self):
        return 1
