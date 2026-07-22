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


def to_mermaid(diagram, direction="TD", notes=True):
    """Markdown document with one fenced mermaid block per page."""
    blocks = []
    multi = len(diagram.pages) > 1
    for page in diagram.pages:
        block = "```mermaid\n%s\n```" % _mermaid_page(page, direction)
        if notes and page.recovered:
            block += "\n\n> ℹ️ 以下连线端点未真正吸附到节点，已按坐标就近还原，请确认：\n"
            block += "\n".join(
                "> - %s -> %s%s" % (
                    _label(page, e.source), _label(page, e.target),
                    " (%s)" % e.label if e.label else "",
                )
                for e in page.recovered
            )
        if notes and page.dropped:
            block += "\n\n> ⚠️ 以下连线端点悬空，无法确定目标，已跳过，请人工核对：\n"
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
