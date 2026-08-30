"""The `sillo.wire` alias, and the finder that provides it.

The alias is what a `.pth` installs at interpreter startup. These tests drive
the finder directly rather than relying on that, so they hold under an editable
install too — where the `.pth` is present but the checkout is what is imported.
"""

from __future__ import annotations

import sys

import pytest

import _sillo_wire_bootstrap as bootstrap
import sillo_wire


@pytest.fixture
def finder():
    """A finder registered for the duration of one test."""
    added = bootstrap.install()
    yield next(f for f in sys.meta_path if isinstance(f, bootstrap._AliasFinder))
    if added:
        sys.meta_path[:] = [
            f for f in sys.meta_path if not isinstance(f, bootstrap._AliasFinder)
        ]


class TestNameResolution:
    def test_the_alias_itself(self):
        assert bootstrap._resolve("sillo.wire") == "sillo_wire"

    def test_anything_beneath_it(self):
        assert bootstrap._resolve("sillo.wire.hub") == "sillo_wire.hub"
        assert bootstrap._resolve("sillo.wire.a.b") == "sillo_wire.a.b"

    @pytest.mark.parametrize(
        "name",
        [
            "sillo",             # the framework itself is not ours
            "sillo.responses",   # nor any other part of it
            "sillo_wire",        # the real name needs no help
            "sillowire",         # a prefix match is not a package match
            "wire",
        ],
    )
    def test_names_that_are_not_ours(self, name):
        assert bootstrap._resolve(name) is None


class TestTheFinder:
    def test_it_declines_names_it_does_not_own(self, finder):
        assert finder.find_spec("json") is None
        assert finder.find_spec("sillo.responses") is None

    def test_it_answers_for_the_alias(self, finder):
        spec = finder.find_spec("sillo.wire")
        assert spec is not None
        assert spec.name == "sillo.wire"
        # A package, so `sillo.wire.hub` can be found beneath it.
        assert spec.submodule_search_locations is not None

    def test_it_declines_when_the_target_is_absent(self, finder, monkeypatch):
        """Half an install should produce the ordinary import error, not one
        from in here."""
        monkeypatch.setattr(bootstrap, "REAL", "a_package_that_is_not_installed")
        assert finder.find_spec("sillo.wire") is None

    def test_it_declines_when_the_target_cannot_be_probed(self, finder, monkeypatch):
        def explode(name):
            raise ValueError("malformed spec")

        monkeypatch.setattr(bootstrap, "find_spec", explode)
        assert finder.find_spec("sillo.wire") is None

    def test_the_loader_returns_the_one_module(self, finder):
        """Not a second copy: two `Hub` classes would be two sets of rooms."""
        spec = finder.find_spec("sillo.wire")
        assert spec.loader.create_module(spec) is sillo_wire

    def test_exec_module_does_not_re_run_it(self, finder):
        spec = finder.find_spec("sillo.wire")
        assert spec.loader.exec_module(sillo_wire) is None


class TestInstall:
    def test_it_registers_once(self):
        before = sum(isinstance(f, bootstrap._AliasFinder) for f in sys.meta_path)
        added = bootstrap.install()
        after = sum(isinstance(f, bootstrap._AliasFinder) for f in sys.meta_path)
        try:
            # Importing this module already installed one, so the second call
            # is a no-op — a duplicate would sit on every import in the process.
            assert after == max(before, 1)
            assert added is False or before == 0
        finally:
            if added:
                sys.meta_path[:] = [
                    f
                    for f in sys.meta_path
                    if not isinstance(f, bootstrap._AliasFinder)
                ]


class TestTheAliasEndToEnd:
    def test_it_imports_and_is_the_same_package(self, finder):
        import sillo.wire

        assert sillo.wire is sillo_wire
        assert sillo.wire.Hub is sillo_wire.Hub

    def test_submodules_resolve_through_it(self, finder):
        from sillo.wire.hub import Hub

        assert Hub is sillo_wire.Hub
