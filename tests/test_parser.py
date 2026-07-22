import json
import re
from pathlib import Path

import pytest

from drawio_digest import (parse, parse_string, to_json, to_markdown,
                           to_mermaid, to_summary)
from drawio_digest.cli import main
from drawio_digest.select import PageNotFound, select_pages
from drawio_digest.model import Diagram, Page

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


class TestCompressed:
    def test_compressed_diagram_is_decoded(self):
        """draw.io stores pages deflated unless the user opts out."""
        page = parse(FIXTURES / "compressed.drawio").pages[0]
        assert page.name == "Zipped"
        assert {n.label for n in page.nodes} == {"Compressed A", "Compressed B"}
        assert len(page.edges) == 1


class TestMultiPage:
    def test_every_diagram_becomes_a_page(self):
        pages = parse(FIXTURES / "multipage.drawio").pages
        assert [p.name for p in pages] == ["Overview", "Detail/Sub", "Page"]

    def test_pages_keep_their_own_content(self):
        pages = parse(FIXTURES / "multipage.drawio").pages
        assert labels(pages[0]) == {"Start", "Review"}
        assert labels(pages[1]) == {"Check", "Done"}

    def test_dropped_edge_is_isolated_to_its_page(self):
        """--strict must be able to tell which page is at fault."""
        pages = parse(FIXTURES / "multipage.drawio").pages
        assert pages[0].dropped == []
        assert len(pages[1].dropped) == 1


class TestFilteredFlag:
    def test_defaults_to_false(self):
        assert parse(FIXTURES / "multipage.drawio").filtered is False

    def test_json_exposes_it(self):
        """asdict() is the JSON renderer; a new field must not break it."""
        data = json.loads(to_json(parse(FIXTURES / "multipage.drawio")))
        assert data["filtered"] is False


class TestSelectPages:
    @pytest.fixture
    def diagram(self):
        return parse(FIXTURES / "multipage.drawio")

    def test_selects_by_index(self, diagram):
        got = select_pages(diagram, ["2"])
        assert [p.name for p in got.pages] == ["Detail/Sub"]

    def test_selects_by_name(self, diagram):
        got = select_pages(diagram, ["Overview"])
        assert [p.name for p in got.pages] == ["Overview"]

    def test_marks_the_result_filtered(self, diagram):
        assert select_pages(diagram, ["1"]).filtered is True

    def test_keeps_the_diagram_name(self, diagram):
        assert select_pages(diagram, ["1"]).name == diagram.name

    def test_does_not_mutate_the_input(self, diagram):
        select_pages(diagram, ["1"])
        assert len(diagram.pages) == 3
        assert diagram.filtered is False

    def test_follows_selector_order_not_document_order(self, diagram):
        got = select_pages(diagram, ["Detail/Sub", "Overview"])
        assert [p.name for p in got.pages] == ["Detail/Sub", "Overview"]

    def test_deduplicates_selectors_hitting_one_page(self, diagram):
        got = select_pages(diagram, ["1", "Overview"])
        assert [p.name for p in got.pages] == ["Overview"]

    def test_duplicate_page_names_are_all_kept(self):
        """draw.io permits duplicate names; dropping one silently is worse."""
        d = Diagram(name="d", pages=[Page(name="A"), Page(name="B"), Page(name="A")])
        assert len(select_pages(d, ["A"]).pages) == 2

    def test_index_out_of_range_raises(self, diagram):
        with pytest.raises(PageNotFound):
            select_pages(diagram, ["9"])

    def test_zero_index_raises(self, diagram):
        """Indexes are 1-based, so 0 is never valid."""
        with pytest.raises(PageNotFound):
            select_pages(diagram, ["0"])

    def test_unknown_name_raises(self, diagram):
        with pytest.raises(PageNotFound):
            select_pages(diagram, ["nope"])

    def test_error_lists_available_pages(self, diagram):
        with pytest.raises(PageNotFound) as exc:
            select_pages(diagram, ["nope"])
        message = str(exc.value)
        assert "nope" in message
        assert "Overview" in message
        assert "Detail/Sub" in message
        assert "3 pages" in message

    def test_numeric_selector_is_always_an_index(self):
        """A page literally named '2' is still not matched by --page 2."""
        d = Diagram(name="d", pages=[Page(name="2"), Page(name="first")])
        assert select_pages(d, ["1"]).pages[0].name == "2"      # index 1
        assert select_pages(d, ["2"]).pages[0].name == "first"  # index 2, not the name


class TestFilteredRendering:
    def test_single_page_file_has_no_section_heading(self):
        """Unchanged behaviour: one page in, no page heading."""
        assert "## " not in to_markdown(parse(FIXTURES / "lanes.drawio"))

    def test_filtered_single_page_keeps_its_heading(self):
        """Selecting page 2 of 3 must not read like a one-page file."""
        diagram = select_pages(parse(FIXTURES / "multipage.drawio"), ["2"])
        assert "## Detail/Sub" in to_markdown(diagram)

    def test_unfiltered_multipage_still_has_headings(self):
        out = to_markdown(parse(FIXTURES / "multipage.drawio"))
        assert "## Overview" in out
        assert "## Detail/Sub" in out


class TestPageFilename:
    def name(self, page_name, index=1, taken=None):
        from drawio_digest.cli import _page_filename
        return _page_filename("order", page_name, index, ".md",
                              set() if taken is None else taken)

    def test_plain_name(self):
        assert self.name("Overview") == "order-Overview.md"

    def test_path_separator_is_replaced(self):
        """A '/' in a page name must not create a subdirectory."""
        assert self.name("Detail/Sub") == "order-Detail-Sub.md"

    def test_windows_illegal_characters_are_replaced(self):
        assert self.name('a:b"c|d?e*f<g>h') == "order-a-b-c-d-e-f-g-h.md"

    def test_backslash_is_replaced(self):
        assert self.name("a\\b") == "order-a-b.md"

    def test_control_characters_are_replaced(self):
        assert self.name("a\tb") == "order-a-b.md"

    def test_surrounding_whitespace_and_dots_are_stripped(self):
        assert self.name("  Draft.  ") == "order-Draft.md"

    def test_dot_dot_cannot_escape_the_directory(self):
        assert self.name("..") == "order-page-1.md"

    def test_empty_name_falls_back_to_index(self):
        assert self.name("", index=3) == "order-page-3.md"

    def test_name_that_sanitises_to_nothing_falls_back(self):
        assert self.name("///", index=2) == "order-page-2.md"

    def test_collisions_get_a_suffix(self):
        taken = set()
        first = self.name("A/B", taken=taken)
        second = self.name("A:B", taken=taken)
        third = self.name("A|B", taken=taken)
        assert first == "order-A-B.md"
        assert second == "order-A-B-2.md"
        assert third == "order-A-B-3.md"

    def test_cjk_is_preserved(self):
        """Page names are user content; only illegal characters change."""
        assert self.name("订单流程") == "order-订单流程.md"


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


class TestReadme:
    """The README shows real output; keep it from drifting."""

    ROOT = Path(__file__).parent.parent

    @pytest.mark.parametrize("name", ["README.md", "README.zh-CN.md"])
    def test_example_matches_documented_output(self, name):
        readme = (self.ROOT / name).read_text(encoding="utf-8")
        claimed = re.search(r"\n```\n(flowchart.*?)```", readme, re.S).group(1).strip()
        actual = to_mermaid(parse(self.ROOT / "examples" / "order-review.drawio")).strip()
        assert claimed == actual

    @pytest.mark.parametrize("name", ["README.md", "README.zh-CN.md"])
    def test_feature_lists_agree(self, name):
        """Both READMEs must claim the same set of done/not-done items."""
        def items(path):
            text = (self.ROOT / path).read_text(encoding="utf-8")
            done = len(re.findall(r"^- \[x\] ", text, re.M))
            todo = len(re.findall(r"^- \[ \] ", text, re.M))
            return done, todo

        assert items(name) == items("README.md")
        assert items(name)[0] > 0, "expected a feature checklist"

    def test_readmes_link_to_each_other(self):
        en = (self.ROOT / "README.md").read_text(encoding="utf-8")
        zh = (self.ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
        assert "README.zh-CN.md" in en
        assert "README.md" in zh

    def test_supported_formats_are_described_consistently(self):
        """README, package metadata and --help must name the same formats."""
        from drawio_digest.cli import EXT, build_parser

        formats = set(EXT)
        action = next(a for a in build_parser()._actions if a.dest == "format")
        assert set(action.choices) == formats

        blurb = "Markdown, Mermaid or JSON"
        assert blurb in build_parser().description
        assert blurb in (self.ROOT / "pyproject.toml").read_text(encoding="utf-8")
        readme = (self.ROOT / "README.md").read_text(encoding="utf-8")
        for fmt in formats:
            assert fmt.capitalize() in readme or "`%s`" % fmt in readme

    def test_version_matches_pyproject(self):
        """__version__ is read from metadata; guard the fallback literal too."""
        import drawio_digest
        text = (self.ROOT / "pyproject.toml").read_text(encoding="utf-8")
        declared = re.search(r'^version = "([^"]+)"', text, re.M).group(1)
        assert drawio_digest.__version__ == declared
        init = (self.ROOT / "src" / "drawio_digest" / "__init__.py").read_text(encoding="utf-8")
        fallback = re.search(r'__version__ = "([^"]+)"', init).group(1)
        assert fallback == declared

    def test_no_chinese_in_user_facing_output(self):
        """The project documents itself in English; messages should match."""
        cjk = re.compile(r"[一-鿿]")
        text = to_markdown(parse(FIXTURES / "dangling.drawio"))
        # Note headers are the tool's own words; the "> - ..." lines below
        # them are diagram labels and must keep whatever language they use.
        headers = [ln for ln in text.splitlines()
                   if ln.startswith(">") and not ln.startswith("> -")]
        assert headers, "expected review note headers"
        assert not any(cjk.search(ln) for ln in headers), headers
        assert "通知" in text, "diagram labels must be preserved verbatim"


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
