"""Render a parsed Diagram as Mermaid markdown or JSON."""
import json
from dataclasses import asdict

SHAPES = {
    "box": "[%s]",
    "diamond": "{%s}",
    "ellipse": "([%s])",
}


def _quote(label):
    """Mermaid chokes on unescaped quotes and bare punctuation."""
    return '"' + label.replace('"', "'") + '"'


def _mermaid_page(page, direction="TD"):
    # Number nodes in emission order (lane by lane) rather than document
    # order, so editing one part of a diagram does not renumber the rest.
    lane_rank = {lane.id: i for i, lane in enumerate(page.lanes)}
    ordered = sorted(page.nodes, key=lambda n: lane_rank.get(n.lane, len(page.lanes)))
    ids = {node.id: "n%d" % i for i, node in enumerate(ordered)}
    lines = ["flowchart %s" % direction]

    for index, lane in enumerate(page.lanes):
        members = [n for n in page.nodes if n.lane == lane.id]
        if not members:
            continue
        lines.append('    subgraph lane%d[%s]' % (index, _quote(lane.label)))
        for node in members:
            lines.append("        %s%s" % (ids[node.id], SHAPES[node.shape] % _quote(node.label)))
        lines.append("    end")

    for node in page.nodes:
        if node.lane is None:
            lines.append("    %s%s" % (ids[node.id], SHAPES[node.shape] % _quote(node.label)))

    lines.append("")
    for edge in page.edges:
        arrow = "-->|%s|" % _quote(edge.label) if edge.label else "-->"
        lines.append("    %s %s %s" % (ids[edge.source], arrow, ids[edge.target]))
    return "\n".join(lines)


def to_mermaid(diagram, direction="TD"):
    """Bare Mermaid source, for embedding elsewhere.

    Pages are separated by a blank line; no headings, no review notes.
    """
    return "\n\n".join(_mermaid_page(p, direction) for p in diagram.pages)


def to_markdown(diagram, direction="TD", notes=True):
    """Markdown document with one fenced mermaid block per page."""
    blocks = []
    # A filtered result keeps its page headings even when one page is left:
    # the user named that page, so which page this is remains information.
    multi = len(diagram.pages) > 1 or diagram.filtered
    for page in diagram.pages:
        block = "```mermaid\n%s\n```" % _mermaid_page(page, direction)
        if notes and page.recovered:
            block += ("\n\n> ℹ️ These connections were not bound to a shape in the "
                      "source file and were reattached by coordinate. Please verify:\n")
            block += "\n".join(
                "> - %s -> %s%s" % (
                    _label(page, e.source), _label(page, e.target),
                    " (%s)" % e.label if e.label else "",
                )
                for e in page.recovered
            )
        if notes and page.dropped:
            block += ("\n\n> ⚠️ These connections have an unattached endpoint that "
                      "could not be resolved and were skipped. Please check them:\n")
            block += "\n".join("> - %s" % d for d in page.dropped)
        if multi:
            block = "## %s\n\n%s" % (page.name, block)
        blocks.append(block)
    return "# %s\n\n%s\n" % (diagram.name, "\n\n".join(blocks))


def _label(page, node_id):
    for node in page.nodes:
        if node.id == node_id:
            return node.label
    return "?"


def to_json(diagram, indent=2):
    return json.dumps(asdict(diagram), ensure_ascii=False, indent=indent)


def _listing(items, limit=5):
    """Join labels, saying so when the list is cut short."""
    head = ", ".join(items[:limit])
    extra = len(items) - limit
    return head + (" (+%d more)" % extra if extra > 0 else "")


def to_summary(diagram):
    """One short block per page: enough to decide whether to read the rest."""
    lines = []
    for page in diagram.pages:
        incoming = {e.target for e in page.edges}
        outgoing = {e.source for e in page.edges}
        # A node touching no edge is a legend or annotation, not a start or
        # end -- counting it as both would misdescribe the flow.
        connected = [n for n in page.nodes if n.id in incoming or n.id in outgoing]
        isolated = [n for n in page.nodes if n not in connected]
        entries = [n.label for n in connected if n.id not in incoming]
        exits = [n.label for n in connected if n.id not in outgoing]

        head = "%s: %d nodes, %d edges" % (page.name, len(page.nodes), len(page.edges))
        if page.lanes:
            counts = ", ".join(
                "%s(%d)" % (lane.label, sum(1 for n in page.nodes if n.lane == lane.id))
                for lane in page.lanes
            )
            head += ", %d lanes" % len(page.lanes)
            lines.append(head)
            lines.append("  lanes: %s" % counts)
        else:
            lines.append(head)

        if entries:
            lines.append("  entry: %s" % _listing(entries))
        if exits:
            lines.append("  exit: %s" % _listing(exits))
        if isolated:
            lines.append("  unconnected: %d (%s)" % (len(isolated),
                                                     _listing(sorted(n.label for n in isolated), 3)))
        if page.recovered:
            lines.append("  recovered: %d edge(s) reattached by coordinate" % len(page.recovered))
        if page.dropped:
            lines.append("  dropped: %d edge(s) unresolved" % len(page.dropped))
    return "%s\n%s" % (diagram.name, "\n".join(lines))
