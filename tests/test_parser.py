import json
from pathlib import Path

import pytest

from drawio_digest import parse, to_json, to_mermaid

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def lanes():
    return parse(FIXTURES / "lanes.drawio").pages[0]


@pytest.fixture(scope="module")
def dangling():
    return parse(FIXTURES / "dangling.drawio").pages[0]


def labels(page):
    return {n.label for n in page.nodes}


def edge_set(page):
    by_id = {n.id: n.label for n in page.nodes}
    return {(by_id[e.source], by_id[e.target], e.label) for e in page.edges}


class TestLanes:
    def test_large_titled_rects_become_lanes(self, lanes):
        assert {lane.label for lane in lanes.lanes} == {"Group", "Subsidiary"}

    def test_lanes_are_not_emitted_as_nodes(self, lanes):
        assert "Group" not in labels(lanes)
        assert "Subsidiary" not in labels(lanes)

    def test_nodes_assigned_to_lane_by_geometry(self, lanes):
        lane_by_id = {lane.id: lane.label for lane in lanes.lanes}
        got = {n.label: lane_by_id.get(n.lane) for n in lanes.nodes}
        assert got["下发任务"] == "Group"
        assert got["确认接收 / 通知"] == "Subsidiary"


class TestLabels:
    def test_br_becomes_separator(self, lanes):
        assert "确认接收 / 通知" in labels(lanes)

    def test_edge_label_cell_is_not_a_node(self, lanes):
        """`通过` is an edgeLabel; it must land on the edge, not float free."""
        assert "通过" not in labels(lanes)
        assert ("是否通过", "确认接收 / 通知", "通过") in edge_set(lanes)

    def test_inline_edge_value_kept(self, lanes):
        assert ("下发任务", "确认接收 / 通知", "通知") in edge_set(lanes)


class TestShapes:
    def test_shape_detection(self, lanes):
        shapes = {n.label: n.shape for n in lanes.nodes}
        assert shapes["开始"] == "ellipse"
        assert shapes["是否通过"] == "diamond"
        assert shapes["下发任务"] == "box"


class TestDecorations:
    def test_dashed_divider_is_ignored(self, lanes):
        """endArrow=none with no label is a divider, not a flow edge."""
        assert lanes.dropped == []
        assert len(lanes.edges) == 4


class TestDanglingEndpoints:
    def test_nearby_endpoint_is_recovered(self, dangling):
        assert ("A", "B", "通知") in edge_set(dangling)

    def test_recovered_edge_is_flagged(self, dangling):
        recovered = {e.label for e in dangling.recovered}
        assert recovered == {"通知"}

    def test_far_endpoint_is_dropped_not_guessed(self, dangling):
        assert len(dangling.dropped) == 1
        assert all(e.target != "c" or e.source for e in dangling.edges)
        assert ("A", "C", "") not in edge_set(dangling)


class TestRender:
    def test_mermaid_has_subgraphs_and_is_quoted(self, lanes):
        out = to_mermaid(parse(FIXTURES / "lanes.drawio"))
        assert "flowchart TD" in out
        assert 'subgraph lane0["Group"]' in out
        assert '-->|"通知"|' in out

    def test_notes_can_be_suppressed(self):
        diagram = parse(FIXTURES / "dangling.drawio")
        assert "ℹ️" in to_mermaid(diagram)
        assert "ℹ️" not in to_mermaid(diagram, notes=False)

    def test_direction_is_configurable(self):
        out = to_mermaid(parse(FIXTURES / "lanes.drawio"), direction="LR")
        assert "flowchart LR" in out

    def test_json_roundtrips(self):
        data = json.loads(to_json(parse(FIXTURES / "lanes.drawio")))
        assert data["name"] == "lanes"
        assert len(data["pages"]) == 1
        assert {n["label"] for n in data["pages"][0]["nodes"]} == labels(
            parse(FIXTURES / "lanes.drawio").pages[0]
        )
