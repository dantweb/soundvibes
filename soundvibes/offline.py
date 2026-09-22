"""Working out which translation packages an offline install needs.

Kept out of the install script so the reasoning is testable: getting this wrong
is silent until someone is on a plane with no network.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

#: Argos routes most pairs through English when no direct package exists.
DEFAULT_PIVOT = "en"

Pair = tuple[str, str]


def _unique(items: Iterable) -> list:
    """Order-preserving dedupe."""
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def required_pairs(sources: Sequence[str], targets: Sequence[str]) -> list[Pair]:
    """Every (spoken language -> translation target) pair that could be needed.

    `targets` are the languages we translate *into*, which need not be languages
    anyone speaks — that distinction is the whole point. With no targets set we
    fall back to preparing translation between the spoken languages.
    """
    sources = _unique(sources)
    targets = _unique(targets) or sources
    return _unique((source, target) for source in sources for target in targets if source != target)


def resolve_packages(
    available: Sequence[Pair],
    sources: Sequence[str],
    targets: Sequence[str],
    pivot: str = DEFAULT_PIVOT,
) -> tuple[list[Pair], list[Pair]]:
    """Split the needed pairs into packages to install and pairs we cannot serve.

    Returns (to_install, unreachable). A pair with no direct package becomes its
    two pivot legs, which are shared across pairs and installed once.
    """
    offered = set(available)
    to_install: list[Pair] = []
    unreachable: list[Pair] = []

    for source, target in required_pairs(sources, targets):
        if (source, target) in offered:
            to_install.append((source, target))
        elif (source, pivot) in offered and (pivot, target) in offered:
            to_install.extend([(source, pivot), (pivot, target)])
        elif source == pivot or target == pivot:
            unreachable.append((source, target))
        else:
            unreachable.append((source, target))

    return _unique(to_install), _unique(unreachable)
