"""Extract structure from draw.io diagrams."""
from .model import Diagram, Edge, Lane, Node, Page
from .parser import parse
from .render import to_json, to_mermaid

__version__ = "0.1.0"
__all__ = ["parse", "to_mermaid", "to_json",
           "Diagram", "Page", "Node", "Edge", "Lane"]
