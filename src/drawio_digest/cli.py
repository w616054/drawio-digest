"""Command line entry point."""
import argparse
import sys
from pathlib import Path

from .parser import parse, parse_string
from .render import to_json, to_markdown, to_mermaid, to_summary

EXT = {"markdown": ".md", "mermaid": ".mmd", "json": ".json"}


def build_parser():
    ap = argparse.ArgumentParser(
        prog="drawio-digest",
        description="Extract structure from .drawio files as Markdown, Mermaid or JSON.",
    )
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


def main(argv=None):
    args = build_parser().parse_args(argv)
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

        dropped = sum(len(p.dropped) for p in diagram.pages)
        recovered = sum(len(p.recovered) for p in diagram.pages)
        dropped_total += dropped

        if args.summary:
            print(to_summary(diagram))
            continue

        text = _render(diagram, args)

        if args.stdout or from_stdin:
            print(text)
            continue

        path = Path(name)
        outdir = args.outdir or path.parent
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / (path.stem + EXT[args.format])
        out.write_text(text, encoding="utf-8")

        note = ""
        if recovered:
            note += "  (recovered %d)" % recovered
        if dropped:
            note += "  (dropped %d)" % dropped
        print("%s -> %s%s" % (path, out, note))

    if failed:
        return 2
    return 1 if args.strict and dropped_total else 0


if __name__ == "__main__":
    sys.exit(main())
