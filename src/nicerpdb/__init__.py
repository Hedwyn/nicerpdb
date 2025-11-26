"""
Registers pytest plugin on import if available.

@author: Baptiste Pestourie
@date: 26.11.2025
"""

from __future__ import annotations

try:
    import pytest

    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False

if HAS_PYTEST:
    from nicerpdb.debugger import RichPdb
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from pytest import CallInfo

    @pytest.hookimpl()
    def pytest_exception_interact(call: CallInfo, report: object):
        # Extract the real traceback object (etype, evalue, tb)

        *_, tb = call.excinfo._excinfo

        debugger = RichPdb(show_locals=True, context_lines=20)
        debugger.reset()
        debugger.interaction(None, tb)
