"""Pick pages out of a parsed Diagram.

Kept apart from the CLI because the selector rules -- index versus name,
duplicates, ordering -- carry enough behaviour to be worth testing on their
own.
"""
from .model import Diagram


class PageNotFound(ValueError):
    """A --page selector matched nothing."""


def _matches(diagram, selector):
    """Resolve one selector to page positions, or None if it matches nothing.

    A purely numeric selector is always a 1-based index, even when a page is
    literally named "2" -- an ambiguous rule would be worse than a documented
    one, and asking for a page by position is the common case.
    """
    if selector.isdigit():
        index = int(selector)
        if 1 <= index <= len(diagram.pages):
            return [index - 1]
        return None
    # Names may repeat; keep every match rather than silently dropping one.
    found = [i for i, page in enumerate(diagram.pages) if page.name == selector]
    return found or None


def select_pages(diagram, selectors):
    """Return a new Diagram holding only the selected pages.

    Pages come back in the order the user wrote the selectors, not document
    order: they listed them explicitly, so that order is the intent.
    """
    chosen = []
    for selector in selectors:
        found = _matches(diagram, selector)
        if found is None:
            available = ", ".join(page.name for page in diagram.pages)
            raise PageNotFound(
                "no page matches %r; available: %s (%d pages)"
                % (selector, available, len(diagram.pages))
            )
        # Two selectors can name one page; it should still appear once.
        chosen.extend(i for i in found if i not in chosen)
    return Diagram(name=diagram.name,
                   pages=[diagram.pages[i] for i in chosen],
                   filtered=True)
