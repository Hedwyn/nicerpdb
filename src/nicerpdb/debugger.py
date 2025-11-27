"""
Frontend for NicerPDB.

Enhancements:
- Syntax highlighted output for 'list' (l) and 'longlist' (ll)
- Pretty locals/globals printing
- Colored stack rendering in 'where'
- Bare expression pretty eval
- TOML config from ~/.nicerpdb.toml
- breakpoint() integration

@author: Baptiste Pestourie
@date: 26.11.2025
"""

from __future__ import annotations

import pdb
import sys
import inspect
import linecache
import os
from types import FrameType
from typing import Any, Optional, List, Dict

try:
    import tomllib  # Py3.11+
except ImportError:
    import tomli as tomllib

from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table
from rich.pretty import Pretty
from rich.panel import Panel
from rich.traceback import Traceback


# Global console
console: Console = Console()

# Default config
DEFAULT_CONFIG: Dict[str, Any] = {
    "context_lines": 3,
    "show_locals": True,
    "show_stack": True,
}


def load_config() -> Dict[str, Any]:
    """Load ~/.nicerpdb.toml if present."""
    config_path = os.path.expanduser("~/.nicerpdb.toml")
    cfg: Dict[str, Any] = DEFAULT_CONFIG.copy()
    if os.path.exists(config_path):
        try:
            with open(config_path, "rb") as f:
                loaded = tomllib.load(f)
                cfg.update(loaded)
        except Exception:
            console.print("[yellow]Warning: error reading ~/.nicerpdb.toml[/]")
    return cfg


class RichPdb(pdb.Pdb):
    """Custom Pdb frontend using Rich."""

    config: dict[str, Any] = load_config()

    def __init__(
        self,
        *args: Any,
        show_locals: Optional[bool] = None,
        context_lines: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)

        self.show_locals: bool = (
            show_locals if show_locals is not None else self.config["show_locals"]
        )
        self.context_lines: int = (
            context_lines if context_lines is not None else self.config["context_lines"]
        )

        # Clean simple prompt
        self.prompt: str = " (nicerpdb) > "

    # -------------------- Rendering Helpers ----------------------------

    def _render_source_block(self, filename: str, lineno: int, context: int) -> None:
        """Render snippet around a target line using Syntax."""
        lines = linecache.getlines(filename)
        if not lines:
            console.print(f"[italic]Cannot read source from {filename}[/]")
            return

        start = max(0, lineno - 1 - context)
        end = min(len(lines), lineno - 1 + context + 1)
        snippet = "".join(lines[start:end])

        syntax = Syntax(
            snippet,
            "python",
            line_numbers=True,
            start_line=start + 1,
            highlight_lines={lineno},
            indent_guides=True,
        )

        console.print(Panel(syntax, title=f"{filename}:{lineno}", expand=True))

    def _render_full_file(self, filename: str, lineno: int) -> None:
        """Full source listing (ll)."""
        lines = linecache.getlines(filename)
        if not lines:
            console.print(f"[italic]Cannot read file {filename}[/]")
            return

        text = "".join(lines)
        syntax = Syntax(
            text,
            "python",
            line_numbers=True,
            highlight_lines={lineno},
            indent_guides=True,
        )
        console.print(Panel(syntax, title=f"Full source: {filename}", expand=True))

    def _render_stack(self) -> None:
        frame: FrameType = self.curframe
        stack: List[FrameType] = []
        cur: Optional[FrameType] = frame

        while cur:
            stack.append(cur)
            cur = cur.f_back
        stack.reverse()

        table = Table(title="Stack (most recent last)", expand=True)
        table.add_column("#", justify="right")
        table.add_column("Function")
        table.add_column("Location")
        table.add_column("Context excerpt")

        for i, fr in enumerate(stack, start=1):
            code = fr.f_code
            fname = code.co_filename
            ln = fr.f_lineno
            func = code.co_name

            ctx = ""
            src = linecache.getlines(fname)
            if src:
                a = max(0, ln - 2)
                b = min(len(src), ln + 1)
                ctx = " ".join(l.strip() for l in src[a:b])
                if len(ctx) > 120:
                    ctx = ctx[:117] + "..."

            table.add_row(str(i), func, f"{fname}:{ln}", ctx)

        console.print(table)

    def _render_vars(self, frame: FrameType) -> None:
        locals_table = Table(title="Locals", expand=True)
        locals_table.add_column("Name", style="bold")
        locals_table.add_column("Value")

        for k, v in sorted(frame.f_locals.items()):
            locals_table.add_row(k, Pretty(v, max_length=150))

        globals_table = Table(title="Globals (selected)", expand=True)
        globals_table.add_column("Name")
        globals_table.add_column("Value")

        g = frame.f_globals
        co_names = set(getattr(frame.f_code, "co_names", ()))
        names = co_names | {"__name__", "__file__"}

        for name in names:
            if name in g:
                globals_table.add_row(name, Pretty(g[name], max_length=150))

        console.print(globals_table)
        console.print(locals_table)

    # -------------------- Interaction Override --------------------------

    def interaction(self, frame: FrameType | None, traceback_obj: Any) -> None:
        """Main entry when debugger stops."""
        console.rule("[bold magenta]Debugger stopped[/bold magenta]")
        try:
            if frame is not None:
                self._render_source_block(
                    frame.f_code.co_filename, frame.f_lineno, self.context_lines
                )
                if self.show_locals:
                    self._render_vars(frame)
                if self.config.get("show_stack", True):
                    self._render_stack()
        except Exception:
            console.print(Traceback.from_exception(*sys.exc_info()))

        super().interaction(frame, traceback_obj)

    # -------------------- Command overrides ------------------------------

    def default(self, line: str) -> Optional[bool]:
        line = line.strip()
        if not line:
            return False
        try:
            val = self._getval(line)
            console.print(Pretty(val, max_length=300))
            return False
        except Exception:
            return super().default(line)

    def do_p(self, arg: str) -> None:
        if not arg.strip():
            console.print("[italic]Usage: p <expr>[/]")
            return
        try:
            console.print(Pretty(self._getval(arg), max_length=300))
        except Exception as e:
            console.print(f"[red]Error:[/] {e}")

    def do_where(self, arg: str) -> None:
        self._render_stack()

    do_w = do_where

    def do_list(self, arg: str) -> None:
        """Syntax highlighted single window listing."""
        frame = self.curframe
        self._render_source_block(frame.f_code.co_filename, frame.f_lineno, self.context_lines)

    do_l = do_list

    def do_longlist(self, arg: str) -> None:
        """Full file listing."""
        frame = self.curframe
        self._render_full_file(frame.f_code.co_filename, frame.f_lineno)

    do_ll = do_longlist

    def message(self, msg: str) -> None:
        if msg:
            console.print(msg, end="")


# ----------------------- Public set_trace ------------------------------


def set_trace(show_locals: Optional[bool] = None, context_lines: Optional[int] = None) -> None:
    """Drop into RichPdb."""
    frame = inspect.currentframe().f_back
    dbg = RichPdb(show_locals=show_locals, context_lines=context_lines)
    dbg.reset()
    dbg.set_trace(frame)


# ----------------------- Breakpoint integration ------------------------
def breakpoint(*args: Any, **kwargs: Any) -> None:
    """Make breakpoint() invoke nicerpdb automatically."""
    # TODO: do not allocate new trace if one has already been created
    set_trace()
