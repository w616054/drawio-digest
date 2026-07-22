"""Extract structure from draw.io diagrams."""
from .model import Diagram, Edge, Lane, Node, Page
from .parser import parse, parse_string
from .render import to_json, to_markdown, to_mermaid, to_summary

try:  # keep pyproject.toml the single source of truth
    from importlib.metadata import PackageNotFoundError, version

    __version__ = version("drawio-digest")
except (ImportError, PackageNotFoundError):  # Python < 3.8, or running from source
    __version__ = "0.1.0"

__all__ = ["parse", "parse_string",
           "to_markdown", "to_mermaid", "to_json", "to_summary",
           "Diagram", "Page", "Node", "Edge", "Lane"]
