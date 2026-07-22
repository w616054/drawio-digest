"""Command line entry point."""
import argparse
import re
import sys
from pathlib import Path

from . import __version__
from .model import Diagram
from .parser import parse, parse_string
from .render import to_json, to_markdown, to_mermaid, to_summary
from .select import PageNotFound, select_pages

EXT = {"markdown": ".md", "mermaid": ".mmd", "json": ".json"}

# Characters no common filesystem accepts in a name. Page names are free
# text, so they reach us holding anything the user typed.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _trim(name):
    """Strip what Windows rejects at either end: blanks and dots.

    Repeated until it settles, because one pass over ". . ." only peels off
    the outermost layer and leaves formatting behind that reads as content.
    """
    while True:
        trimmed = name.strip().strip(".")
        if trimmed == name:
            return trimmed
        name = trimmed


def _page_filename(stem, page_name, index, ext, taken):
    """Build 'stem-pagename.ext', keeping it legal and unique.

    Falling back to the page index keeps every page addressable: a name that
    sanitises to nothing, or collides with a sibling, would otherwise
    overwrite a file that was already written.

    Length is deliberately not capped -- an over-long name makes write_text
    raise OSError, which the caller already reports.
    """
    # ".." would climb out of the output directory, so trimming dots matters
    # beyond Windows' own objection to them.
    safe = _trim(_UNSAFE.sub("-", page_name))
    # Whether to fall back is decided on what the user typed, not on the
    # result: once substitution has run, a dash it introduced ("///") is
    # indistinguishable from one the user typed ("-/-"), and inspecting the
    # result discards real names that merely sit next to an unsafe character.
    if not _trim(_UNSAFE.sub("", page_name)):
        safe = "page-%d" % index

    name = "%s-%s" % (stem, safe)
    candidate, suffix = name, 2
    while candidate in taken:
        candidate = "%s-%d" % (name, suffix)
        suffix += 1
    taken.add(candidate)
    return candidate + ext


def _unique_page_filename(stem, page_name, index, ext, taken, seen_folded):
    """Like _page_filename, but unique on case-insensitive filesystems too.

    macOS and Windows treat 'order-Overview.md' and 'order-overview.md' as one
    file, so pages named 'Overview' and 'overview' would silently overwrite
    each other. Case-folded names are tracked separately; a clash asks
    _page_filename for another candidate, which it suffixes because the
    rejected one stayed in `taken`. The name written keeps the casing the
    user gave the page.
    """
    while True:
        candidate = _page_filename(stem, page_name, index, ext, taken)
        folded = candidate.lower()
        if folded not in seen_folded:
            seen_folded.add(folded)
            return candidate


def build_parser():
    ap = argparse.ArgumentParser(
        prog="drawio-digest",
        description="Extract structure from .drawio files as Markdown, Mermaid or JSON.",
    )
    ap.add_argument("--version", action="version",
                    version="drawio-digest %s" % __version__)
    ap.add_argument("files", nargs="+", type=str, metavar="FILE",
                    help=".drawio files to convert; use - to read stdin")
    ap.add_argument("-f", "--format", choices=("markdown", "mermaid", "json"),
                    default="markdown",
                    help="markdown: document with mermaid block (default); "
                         "mermaid: bare diagram source; json: structured data")
    ap.add_argument("-o", "--outdir", type=Path,
                    help="write next to each source file if omitted")
    ap.add_argument("--stdout", action="store_true",
                    help="print instead of writing files")
    ap.add_argument("--summary", action="store_true",
                    help="print a short overview instead of converting")
    ap.add_argument("--page", action="append", metavar="NAME|N", dest="pages",
                    help="only convert this page; repeatable. A number is a "
                         "1-based index, anything else a page name")
    ap.add_argument("--split", action="store_true",
                    help="write one file per page instead of one per diagram")
    ap.add_argument("--direction", default="TD", choices=("TD", "LR", "BT", "RL"),
                    help="mermaid flow direction (default: TD)")
    ap.add_argument("--no-notes", action="store_true",
                    help="omit review notes about recovered/dropped edges")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero if any edge was dropped")
    return ap


def _render(diagram, args):
    if args.format == "json":
        return to_json(diagram)
    if args.format == "mermaid":
        return to_mermaid(diagram, args.direction)
    return to_markdown(diagram, args.direction, notes=not args.no_notes)


def _note(*pages):
    """Annotate a written file with what needs review inside it."""
    recovered = sum(len(p.recovered) for p in pages)
    dropped = sum(len(p.dropped) for p in pages)
    note = ""
    if recovered:
        note += "  (recovered %d)" % recovered
    if dropped:
        note += "  (dropped %d)" % dropped
    return note


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)

    # These conflict outright. Degrading quietly would be worse: this tool
    # runs in scripts, where a flag that silently does nothing is the most
    # expensive failure mode.
    if args.split:
        if args.stdout:
            ap.error("--split writes files; it cannot be combined with --stdout")
        if args.summary:
            ap.error("--split has no effect with --summary")
        if "-" in args.files:
            ap.error("--split cannot be used when reading from stdin")

    dropped_total = 0
    failed = False

    for name in args.files:
        # stdin has no path, so it can only be printed.
        from_stdin = name == "-"
        try:
            if from_stdin:
                diagram = parse_string(sys.stdin.read(), name="stdin")
            else:
                diagram = parse(Path(name))
        except (OSError, ValueError) as exc:
            print("%s: %s" % (name, exc), file=sys.stderr)
            failed = True
            continue

        if args.pages:
            try:
                diagram = select_pages(diagram, args.pages)
            except PageNotFound as exc:
                print("%s: %s" % (name, exc), file=sys.stderr)
                failed = True
                continue

        # Counted after selection, so --strict only judges what was asked for.
        dropped = sum(len(p.dropped) for p in diagram.pages)
        dropped_total += dropped

        if args.summary:
            print(to_summary(diagram))
            continue

        if args.stdout or from_stdin:
            print(_render(diagram, args))
            continue

        path = Path(name)
        outdir = args.outdir or path.parent
        outdir.mkdir(parents=True, exist_ok=True)

        if args.split:
            taken, seen_folded = set(), set()
            for index, page in enumerate(diagram.pages, 1):
                # One page per file, so it renders as a whole diagram: the H1
                # becomes the page name and no "## name" level is added.
                single = Diagram(name=page.name, pages=[page])
                out = outdir / _unique_page_filename(
                    path.stem, page.name, index, EXT[args.format],
                    taken, seen_folded)
                out.write_text(_render(single, args), encoding="utf-8")
                print("%s -> %s%s" % (path, out, _note(page)))
            continue

        out = outdir / (path.stem + EXT[args.format])
        out.write_text(_render(diagram, args), encoding="utf-8")
        print("%s -> %s%s" % (path, out, _note(*diagram.pages)))

    if failed:
        return 2
    return 1 if args.strict and dropped_total else 0


if __name__ == "__main__":
    sys.exit(main())
