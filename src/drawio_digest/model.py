"""Data model for an extracted diagram."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Node:
    id: str
    label: str
    shape: str = "box"  # box | diamond | ellipse
    lane: Optional[str] = None


@dataclass
class Edge:
    source: str
    target: str
    label: str = ""
    # True when the endpoint was not bound in the source file and had to be
    # recovered from coordinates. Callers should surface this for review.
    recovered: bool = False


@dataclass
class Lane:
    id: str
    label: str


@dataclass
class Page:
    name: str
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    lanes: list = field(default_factory=list)
    # Edges whose endpoints could not be resolved at all.
    dropped: list = field(default_factory=list)

    @property
    def recovered(self):
        return [e for e in self.edges if e.recovered]


@dataclass
class Diagram:
    name: str
    pages: list = field(default_factory=list)
