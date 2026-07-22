"""Parse .drawio (mxGraph XML) into the Diagram model.

draw.io is a free-form canvas, so several things that look structural on
screen are not structural in the file. The quirks handled here were all
found in real diagrams:

* Lanes are often plain large rectangles, not ``swimlane`` shapes.
* Edge labels are separate vertex cells linked by ``parent``.
* An arrow can *look* attached but carry no ``source``/``target`` -- only
  a coordinate. draw.io writes this when the user drops the endpoint on a
  connection point rather than inside the shape.
* Decorative dividers are edges with ``endArrow=none``.
"""
import html
import re
import xml.etree.ElementTree as ET
import zlib
from base64 import b64decode
from pathlib import Path
from urllib.parse import unquote

from .model import Diagram, Edge, Lane, Node, Page

# A candidate lane must be at least this large before containment is even
# considered, to rule out ordinary boxes that happen to overlap a neighbour.
LANE_MIN_AREA = 100_000
# ...and must enclose at least this many other shapes. Absolute size alone is
# a poor test: lane width varies with content, so a narrow lane in one diagram
# can be smaller than a plain box in another.
LANE_MIN_CONTAINED = 3
# How close a dangling endpoint must sit to a shape to be reattached (px).
SNAP_TOLERANCE = 20


def _text(cell):
    """mxCell values are HTML fragments; reduce to plain text."""
    value = cell.get("value") or ""
    value = re.sub(r"<br\s*/?>", " / ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _geometry(cell):
    geo = cell.find("mxGeometry")
    if geo is None:
        return None
    try:
        return tuple(float(geo.get(k) or 0) for k in ("x", "y", "width", "height"))
    except ValueError:
        return None


def _shape(style, label):
    style = style or ""
    if "rhombus" in style:
        return "diamond"
    if "ellipse" in style or label in ("开始", "结束", "start", "end", "Start", "End"):
        return "ellipse"
    return "box"


def _graph_models(root):
    """Yield (page_name, mxGraphModel). Handles compressed diagrams."""
    for diagram in root.iter("diagram"):
        model = diagram.find("mxGraphModel")
        if model is not None:
            yield diagram.get("name") or "Page", model
            continue
        # Compressed form: base64 -> raw deflate -> URL-encoded XML.
        payload = (diagram.text or "").strip()
        if not payload:
            continue
        try:
            raw = zlib.decompress(b64decode(payload), -zlib.MAX_WBITS)
            inner = ET.fromstring(unquote(raw.decode("utf-8")))
        except Exception as exc:  # noqa: BLE001 - report and skip this page
            raise ValueError(
                "could not decompress this page; re-save it from draw.io with "
                "File > Properties > Compressed unchecked"
            ) from exc
        yield diagram.get("name") or "Page", inner


def _parse_page(name, model):
    cells = list(model.iter("mxCell"))
    by_id = {c.get("id"): c for c in cells}

    raw_nodes, raw_edges = {}, []
    candidates = []  # (id, label) of shapes big enough to maybe be a lane
    edge_labels = {}

    for cell in cells:
        label = _text(cell)
        style = cell.get("style") or ""
        if cell.get("edge"):
            # Both-ends-plain lines are dividers/annotations, not flow.
            if "endArrow=none" in style and not label:
                continue
            raw_edges.append(cell)
        elif cell.get("vertex"):
            if "edgeLabel" in style:
                if label:
                    edge_labels[cell.get("parent")] = label
                continue
            geo = _geometry(cell)
            raw_nodes[cell.get("id")] = (label, style, geo)
            explicit = "swimlane" in style
            if label and geo and (explicit or geo[2] * geo[3] >= LANE_MIN_AREA):
                candidates.append((cell.get("id"), label, explicit))

    def absolute_box(cell_id):
        """Child coordinates are parent-relative; walk up to absolutes."""
        x = y = 0.0
        cur, seen = by_id.get(cell_id), set()
        while cur is not None and cur.get("id") not in seen:
            seen.add(cur.get("id"))
            geo = _geometry(cur)
            if geo:
                x += geo[0]
                y += geo[1]
            cur = by_id.get(cur.get("parent"))
        geo = raw_nodes.get(cell_id, (None, None, None))[2]
        return (x, y, geo[2], geo[3]) if geo else None

    def encloses(outer, inner):
        ob, ib = absolute_box(outer), absolute_box(inner)
        if not ob or not ib:
            return False
        cx, cy = ib[0] + ib[2] / 2, ib[1] + ib[3] / 2
        return (ob[0] <= cx <= ob[0] + ob[2]) and (ob[1] <= cy <= ob[1] + ob[3])

    # Confirm candidates: a lane is a shape that holds other shapes. Size on
    # its own misclassifies both ways -- a wide lane and a big note look the
    # same until you ask what sits inside them.
    candidate_ids = {cid for cid, _, _ in candidates}
    lanes = []
    for cid, label, explicit in candidates:
        # Count only ordinary shapes, so two overlapping lanes do not vouch
        # for each other.
        contained = sum(1 for other in raw_nodes
                        if other != cid and other not in candidate_ids
                        and encloses(cid, other))
        if explicit or contained >= LANE_MIN_CONTAINED:
            lanes.append(Lane(cid, label))

    lane_ids = {lane.id for lane in lanes}
    # Lanes are containers, not flow steps.
    for lane in lanes:
        raw_nodes.pop(lane.id, None)

    def lane_of(cell_id):
        cur, seen = by_id.get(cell_id), set()
        while cur is not None:
            parent = cur.get("parent")
            if parent in seen:
                break
            seen.add(parent)
            if parent in lane_ids:
                return parent
            cur = by_id.get(parent)
        box = absolute_box(cell_id)
        if not box:
            return None
        cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
        for lane in lanes:
            lb = absolute_box(lane.id) or _geometry(by_id[lane.id])
            if lb and lb[0] <= cx <= lb[0] + lb[2] and lb[1] <= cy <= lb[1] + lb[3]:
                return lane.id
        return None

    def snap(point):
        """Reattach a dangling endpoint, but only to a shape it touches."""
        best, best_dist = None, None
        for cell_id, (label, _, _) in raw_nodes.items():
            box = absolute_box(cell_id)
            if not box or not label:
                continue
            bx, by, bw, bh = box
            dx = max(bx - point[0], 0, point[0] - (bx + bw))
            dy = max(by - point[1], 0, point[1] - (by + bh))
            dist = (dx * dx + dy * dy) ** 0.5
            if best_dist is None or dist < best_dist:
                best, best_dist = cell_id, dist
        return best if best_dist is not None and best_dist <= SNAP_TOLERANCE else None

    def endpoint(edge, kind):
        cell_id = edge.get(kind)
        if cell_id in raw_nodes:
            return cell_id, False
        geo = edge.find("mxGeometry")
        wanted = "sourcePoint" if kind == "source" else "targetPoint"
        for point in geo.findall("mxPoint") if geo is not None else []:
            if point.get("as") == wanted:
                try:
                    xy = (float(point.get("x") or 0), float(point.get("y") or 0))
                except ValueError:
                    return None, False
                return snap(xy), True
        return None, False

    page = Page(name=name)
    page.lanes = [lane for lane in lanes]
    for cell_id, (label, style, _) in raw_nodes.items():
        if not label:
            continue
        page.nodes.append(Node(cell_id, label, _shape(style, label), lane_of(cell_id)))

    known = {n.id for n in page.nodes}
    seen_edges = set()
    for edge in raw_edges:
        src, src_fixed = endpoint(edge, "source")
        dst, dst_fixed = endpoint(edge, "target")
        label = _text(edge) or edge_labels.get(edge.get("id"), "")
        if src not in known or dst not in known:
            # Distinguish "endpoint went nowhere" from "endpoint landed on a
            # shape that has no text" -- the latter is a labelling gap in the
            # source diagram, and the edge itself is real.
            def describe(cell_id, resolved):
                if resolved in raw_nodes and not raw_nodes[resolved][0]:
                    return "(untitled shape)"
                return raw_nodes.get(cell_id, ("", None, None))[0] or "?"

            a = describe(edge.get("source"), src)
            b = describe(edge.get("target"), dst)
            page.dropped.append(f"{a} -> {b}" + (f" ({label})" if label else ""))
            continue
        if src == dst:
            continue
        key = (src, dst, label)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        page.edges.append(Edge(src, dst, label, src_fixed or dst_fixed))

    # Drop lanes that ended up holding nothing.
    used = {n.lane for n in page.nodes}
    page.lanes = [lane for lane in page.lanes if lane.id in used]
    return page


def _build(root, name):
    diagram = Diagram(name=name)
    for page_name, model in _graph_models(root):
        diagram.pages.append(_parse_page(page_name, model))
    return diagram


def parse(path):
    """Parse a .drawio file."""
    path = Path(path)
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError("not valid XML: %s" % exc) from exc
    return _build(root, path.stem)


def parse_string(text, name="diagram"):
    """Parse .drawio content held in memory (e.g. piped via stdin)."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError("not valid XML: %s" % exc) from exc
    return _build(root, name)
