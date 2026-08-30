"""Make ``sillo.wire`` resolve to this package, without touching the framework.

The code lives in the top-level ``sillo_wire`` package. This module registers a
meta-path finder that maps the name ``sillo.wire`` onto it, so both import
paths reach the same objects:

    from sillo.wire import Hub      # reads as part of the framework
    from sillo_wire import Hub      # where the code actually is

It is loaded by ``sillo_wire.pth`` at interpreter startup, which is the only
hook that runs *before* an ``import sillo.wire`` could fail. Nothing is
imported here — neither ``sillo`` nor ``sillo_wire`` — so the cost is one
object appended to ``sys.meta_path``.

Why not simply ship ``sillo/wire/`` into the framework's own package directory:
two distributions writing into one directory goes wrong in both directions.
Installing the framework from a checkout moves where ``sillo`` resolves and
orphans whatever the other package left in ``site-packages``; and removing or
replacing the framework leaves that directory standing with no ``__init__.py``
in it, which is an override rather than an addition. Nothing here writes into
``sillo/`` at all.

Static analysis does not run import hooks, so type checkers are served
separately, by the partial stubs in ``sillo-stubs/`` (PEP 561).
"""

from __future__ import annotations

import sys
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec
from importlib.util import find_spec

ALIAS = "sillo.wire"
REAL = "sillo_wire"


def _resolve(fullname: str) -> str | None:
    """The real module *fullname* stands for, or ``None`` if it is not ours."""
    if fullname == ALIAS:
        return REAL
    if fullname.startswith(ALIAS + "."):
        return REAL + fullname[len(ALIAS) :]
    return None


class _AliasLoader(Loader):
    """Hands back the already-imported target, so both names are one object.

    Loading the source a second time under the other name would give two
    ``Hub`` classes and two sets of rooms — a broadcast would reach half of
    them, and ``isinstance`` would disagree with itself.
    """

    def __init__(self, target: str) -> None:
        self.target = target

    def create_module(self, spec: ModuleSpec):
        import importlib

        return importlib.import_module(self.target)

    def exec_module(self, module) -> None:
        """Already executed under its own name; nothing to run again."""


class _AliasFinder(MetaPathFinder):
    """Answers for ``sillo.wire`` and anything beneath it."""

    def find_spec(self, fullname: str, path=None, target=None):
        real = _resolve(fullname)
        if real is None:
            return None
        try:
            if find_spec(real) is None:
                return None
        except (ImportError, ValueError):
            # The package is half-installed, or its parent is missing. Decline
            # rather than raise: another finder may do better, and the import
            # error a caller gets should be the ordinary one.
            return None

        import importlib

        module = importlib.import_module(real)
        spec = ModuleSpec(fullname, _AliasLoader(real))
        spec.submodule_search_locations = getattr(module, "__path__", None)
        return spec


def install() -> bool:
    """Register the finder. Returns whether it was newly added.

    Idempotent, because a ``.pth`` is not the only thing that may import this
    module — a test does too, and a second finder would be dead weight on every
    import in the process.
    """
    if any(isinstance(finder, _AliasFinder) for finder in sys.meta_path):
        return False
    sys.meta_path.insert(0, _AliasFinder())
    return True


install()
