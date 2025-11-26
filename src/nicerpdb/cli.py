"""
Command-line interface for nicerpdb.

@author: Baptiste Pestourie
@date: 26.11.2025
"""

from __future__ import annotations
import os
import click


@click.group()
def nicerpdb(): ...


def override_pdb():
    os.environ["PYTHONBREAKPOINT"] = "nicerpdb.debugger.set_trace"


# ----------------------- Demo -----------------------------------------
@nicerpdb.command()
def demo() -> None:
    override_pdb()

    def inner(a: int, b: int) -> int:
        x = {"a": a, "b": b, "sum": a + b}
        data = list(range(10))
        breakpoint()
        return x["sum"]

    inner(2, 3)


if __name__ == "__main__":
    nicerpdb()
