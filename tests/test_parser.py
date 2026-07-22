import json
from pathlib import Path

import pytest

from drawio_digest import (parse, parse_string, to_json, to_markdown,
                           to_mermaid, to_summary)
from drawio_digest.cli import main

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


class TestNoLanes:
    """Lanes are optional -- plenty of real diagrams are flat."""

    def test_flat_diagram_has_no_lanes(self):
        page = parse(FIXTURES / "isolated.drawio").pages[0]
        assert page.lanes == []
        assert all(n.lane is None for n in page.nodes)

    def test_flat_diagram_renders_without_subgraph(self):
        out = to_mermaid(parse(FIXTURES / "isolated.drawio"))
        assert "subgraph" not in out
        assert "flowchart TD" in out

    def test_big_box_without_a_title_is_not_a_lane(self):
        """Unlabelled background rectangles are decoration."""
        page = parse(FIXTURES / "bigbox.drawio").pages[0]
        assert page.lanes == []

    def test_big_box_holding_nothing_is_not_a_lane(self):
        """A large titled note sits next to the flow, not around it."""
        page = parse(FIXTURES / "bigbox.drawio").pages[0]
        assert "说明：本图仅供参考" in {n.label for n in page.nodes}


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
        assert len(lanes.edges) == 6


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

    def test_mermaid_is_bare(self):
        """No heading and no notes -- it is meant to be embedded."""
        out = to_mermaid(parse(FIXTURES / "dangling.drawio"))
        assert out.startswith("flowchart")
        assert "```" not in out
        assert "#" not in out
        assert "ℹ️" not in out

    def test_markdown_wraps_and_titles(self):
        out = to_markdown(parse(FIXTURES / "lanes.drawio"))
        assert out.startswith("# lanes")
        assert "```mermaid" in out

    def test_notes_can_be_suppressed(self):
        diagram = parse(FIXTURES / "dangling.drawio")
        assert "ℹ️" in to_markdown(diagram)
        assert "ℹ️" not in to_markdown(diagram, notes=False)

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


class TestSummary:
    def test_reports_shape_and_lanes(self):
        out = to_summary(parse(FIXTURES / "lanes.drawio"))
        assert "6 nodes, 6 edges, 2 lanes" in out
        assert "Group(3)" in out and "Subsidiary(3)" in out

    def test_reports_entry_and_exit(self):
        out = to_summary(parse(FIXTURES / "lanes.drawio"))
        assert "entry: 开始" in out
        assert "exit: 完成" in out

    def test_flags_unresolved_edges(self):
        out = to_summary(parse(FIXTURES / "dangling.drawio"))
        assert "recovered: 1" in out
        assert "dropped: 1" in out

    def test_is_compact(self):
        """It exists to be cheap enough to run across a whole repo."""
        assert len(to_summary(parse(FIXTURES / "lanes.drawio"))) < 300

    def test_isolated_nodes_are_not_entries_or_exits(self):
        """A legend box touches no edge; calling it entry *and* exit lies."""
        out = to_summary(parse(FIXTURES / "isolated.drawio"))
        assert "unconnected: 2" in out
        assert "图例" not in out.split("unconnected")[0]
        assert "entry: 开始" in out
        assert "exit: 结束" in out


class TestStdin:
    def test_parse_string_matches_file(self):
        text = (FIXTURES / "lanes.drawio").read_text(encoding="utf-8")
        from_mem = parse_string(text, name="lanes")
        from_disk = parse(FIXTURES / "lanes.drawio")
        assert to_mermaid(from_mem) == to_mermaid(from_disk)

    def test_invalid_xml_raises_valueerror(self):
        with pytest.raises(ValueError):
            parse_string("<mxfile><broken>")


class TestCli:
    def test_stdin_prints_to_stdout(self, monkeypatch, capsys, tmp_path):
        import io
        monkeypatch.setattr("sys.stdin",
                            io.StringIO((FIXTURES / "lanes.drawio").read_text(encoding="utf-8")))
        assert main(["-"]) == 0
        assert "flowchart TD" in capsys.readouterr().out

    def test_format_picks_extension(self, tmp_path):
        for fmt, ext in (("markdown", ".md"), ("mermaid", ".mmd"), ("json", ".json")):
            assert main([str(FIXTURES / "lanes.drawio"), "-f", fmt, "-o", str(tmp_path)]) == 0
            assert (tmp_path / ("lanes" + ext)).exists()

    def test_strict_fails_on_dropped_edges(self, tmp_path):
        args = [str(FIXTURES / "dangling.drawio"), "-o", str(tmp_path)]
        assert main(args) == 0
        assert main(args + ["--strict"]) == 1

    def test_missing_file_reports_error(self, capsys):
        assert main(["nope.drawio"]) == 2
        assert "nope.drawio" in capsys.readouterr().err
