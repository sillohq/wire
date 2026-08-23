"""Make ``sillo.wire`` importable from the checkout.

The wheel ships ``sillo/wire/`` *into* the installed ``sillo`` package, which
is what lets an application write ``from sillo.wire import Hub`` with no import
hook. That arrangement has no editable-install equivalent: ``sillo`` is a
regular package, so its ``__path__`` is the one directory pip put it in, and a
second ``sillo/`` earlier on ``sys.path`` is ignored rather than merged.

Appending this checkout to that ``__path__`` reproduces at test time exactly
what installing the wheel does at run time.
"""

from __future__ import annotations

import pathlib

import sillo

_here = pathlib.Path(__file__).resolve().parent.parent / "sillo"
if str(_here) not in sillo.__path__:
    sillo.__path__.append(str(_here))
