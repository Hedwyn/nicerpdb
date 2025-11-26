"""
Main entrypoint when invoking with python -m nicerpdb <script>

@author: Baptiste Pestourie
@date: 26.11.2025
"""

from __future__ import annotations

import runpy
import sys

import click

from nicerpdb.cli import override_pdb


@click.argument("script", nargs=1, type=click.Path(exists=True))
@click.argument("script_args", nargs=-1)
@click.command()
def main(script, script_args):
    sys.argv = [script] + list(script_args)
    override_pdb()
    runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main()
