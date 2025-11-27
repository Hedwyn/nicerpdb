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
        last_tb = tb
        while last_tb.tb_next is not None:
            last_tb = last_tb.tb_next

        frame = last_tb.tb_frame
        debugger = RichPdb()
        debugger.reset()
        debugger.interaction(frame, tb)
