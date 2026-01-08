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

import inspect
import linecache
import os
import pdb
import subprocess
import sys
from dataclasses import dataclass
from functools import partialmethod
from tkinter import Frame
from types import FrameType, TracebackType
from typing import Any, Callable, Protocol, TypeAlias, TypeVar

try:
    import tomllib  # Py3.11+
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

from rich.console import Console
from rich.panel import Panel
from rich.pretty import Pretty
from rich.syntax import Syntax
from rich.table import Table
from rich.traceback import Traceback

# Global console
console: Console = Console()

ExcInfo: TypeAlias = tuple[type[BaseException], BaseException, TracebackType]
OptExcInfo: TypeAlias = ExcInfo | tuple[None, None, None]


class FormattingError(Exception): ...


@dataclass
class NicerPdbConfig:
    """
    Debugger parameters, can be set a TOML file.
    """

    context_lines: int = 10
    show_locals: bool = True
    show_stack: bool = True


DEFAULT_CONFIG_PATH = "~/.nicerpdb.toml"


def load_config(config_path: str | None = None) -> NicerPdbConfig:
    """Load ~/.nicerpdb.toml if present."""
    config_path = config_path or os.path.expanduser("~/.nicerpdb.toml")
    if os.path.exists(config_path):
        try:
            with open(config_path, "rb") as f:
                loaded = tomllib.load(f)
                return NicerPdbConfig(**loaded)
        except Exception as exc:
            console.print(f"[yellow]Warning: error reading ~/.nicerpdb.toml: {exc}[/]")
    return NicerPdbConfig()


CmdRet = TypeVar("CmdRet", bound=bool | None, covariant=True)


class PdbCommand(Protocol[CmdRet]):
    def __call__(self, _: RichPdb, /, arg: str) -> CmdRet: ...


def accepts_int_arg(
    command: Callable[[RichPdb, int | None], CmdRet],
) -> PdbCommand[CmdRet]:
    def wrapper(self: RichPdb, arg: str) -> CmdRet:
        if not arg:
            return command(self, None)

        try:
            arg_value = int(arg)
        except ValueError:
            self.print_error(f"Invalid argument '{arg}'. Expected an integer.")
            arg_value = None

        return command(self, arg_value)

    return wrapper


class RichPdb(pdb.Pdb):
    """Custom Pdb frontend using Rich."""

    def __init__(
        self,
        *args: Any,
        config: NicerPdbConfig | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.config = config or load_config()

        # Clean simple prompt
        self.prompt: str = " (nicerpdb) > "
        self.errors: list[str] = []

    def print_stack_trace(self, depth: int = 5) -> None:
        try:
            for frame_lineno in self.stack[-depth:]:
                self.print_stack_entry(frame_lineno)
        except KeyboardInterrupt:
            pass

    def format_stack_entry(
        self,
        frame_lineno: tuple[FrameType, int],
        lprefix: str = "",
    ) -> str:
        """
        Return a one-line summary for a stack entry.

        We keep this method returning a simple string so existing callers that expect the
        pdb-format summary continue to work. Detailed, colored rendering is done in
        print_stack_entry.
        """
        frame, lineno = frame_lineno
        code = frame.f_code
        filename = code.co_filename
        funcname = code.co_name

        # mimic pdb's concise stack entry format
        return f'{lprefix}File "{filename}", line {lineno}, in {funcname}'

    def print_stack_entry(
        self,
        frame_lineno: tuple[FrameType, int],
        prompt_prefix: str | None = None,
        context: int = 5,
    ) -> None:
        """
        Render a stack entry with Rich: show `context` lines around `lineno` with syntax
        highlighting. The current line is highlighted by Syntax's highlight_lines; panel
        and border styles are chosen to be soft on dark backgrounds.
        """
        frame, lineno = frame_lineno
        code = frame.f_code
        filename = code.co_filename
        funcname = code.co_name

        # Compute snippet range (1-based lines)
        start = max(1, lineno - context)
        end = lineno + context

        # Read the lines; linecache returns '' for missing lines so join is safe
        snippet_lines: list[str] = [
            (linecache.getline(filename, i) or "") for i in range(start, end + 1)
        ]
        snippet = "".join(snippet_lines)

        # Build a one-line header (keeps compatibility with pdb callers)
        header = self.format_stack_entry(frame_lineno, lprefix=(prompt_prefix or ""))

        # Syntax block with the current line highlighted.
        # Rich's Syntax will visually distinguish highlighted lines; we choose a soft panel/border style
        # that reads well on dark backgrounds.
        console.print(header)
        if not snippet.strip():
            return
        syntax = Syntax(
            snippet,
            "python",
            line_numbers=True,
            start_line=start,
            highlight_lines={lineno},
            word_wrap=False,
        )

        panel = Panel(
            syntax,
            title=f"[bold]{funcname} — {filename}:{lineno}[/]",
            border_style="grey37",
            padding=(0, 1),
        )

        # Print header (plain) then the panel. The header keeps textual compatibility; the panel
        # provides the rich highlighted context. No extra "current frame" messages are printed.
        console.print(panel)

    @property
    def show_locals(self) -> bool:
        return self.config.show_locals

    @property
    def context_lines(self) -> int:
        return self.config.context_lines

    @property
    def show_stack(self) -> bool:
        return self.config.show_stack

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

    def print_error(self, error: str) -> None:
        console.print(f"[red]Error:[/] {error}")

    def build_call_stack(
        self,
        start_frame: FrameType | None = None,
        *,
        reversed: bool = False,
        max_depth: int | None = None,
    ) -> list[FrameType]:
        start_frame = start_frame or self.curframe
        stack: list[FrameType] = []
        if start_frame is None:
            return stack

        cur: FrameType | None = start_frame

        while cur:
            stack.append(cur)
            cur = cur.f_back
            if max_depth is not None and len(stack) == max_depth:
                break
        if reversed:
            stack.reverse()
        return stack

    def _render_stack(self) -> None:
        stack = self.build_call_stack()

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

    def resolve_cmd_variables(self, cmd: str) -> str:
        args = cmd.split()
        formatted_args = []
        for arg in args:
            if not arg.startswith("%"):
                formatted_args.append(arg)
                continue

            var_name = arg[1:]
            frame = self.curframe
            if frame is None:
                raise FormattingError("No current frame to resolve variables")
            if var_name in frame.f_locals:
                value = frame.f_locals[var_name]
            elif var_name in frame.f_globals:
                value = frame.f_globals[var_name]
            else:
                raise FormattingError(f"Variable '{var_name}' not found in locals or globals")
            formatted_args.append(str(value))
        return " ".join(formatted_args)

    def run_shell_command(self, arg: str, format: bool = False, pretty: bool = False) -> None:
        """
        Runs a shell command within the debugger session.
        """
        cmd = arg
        if format:
            try:
                cmd = self.resolve_cmd_variables(cmd)
            except FormattingError as exc:
                self.print_error(str(exc))
                return
        proc = subprocess.run(
            cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        output = proc.stdout if not pretty else Syntax(proc.stdout, "shell")
        console.print(output)
        if proc.stderr:
            output = proc.stderr if not pretty else Syntax(proc.stderr, "shell")
            console.print(f"[red]{output}[/]")

    # -------------------- Interaction Override --------------------------

    def interaction(self, frame: FrameType | None, traceback_obj: Any) -> None:
        """Main entry when debugger stops."""
        console.rule("[bold magenta]Debugger stopped[/bold magenta]")
        try:
            if frame is not None:
                if self.show_locals:
                    self._render_vars(frame)
                if self.show_stack:
                    self.print_stack_trace(depth=1)
        except Exception:
            console.print(Traceback.from_exception(*sys.exc_info()))

        super().interaction(frame, traceback_obj)

    # -------------------- Command overrides ------------------------------

    def default(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            val = self._getval(line)
            console.print(Pretty(val, max_length=300))
            return
        except Exception:
            super().default(line)

    def do_p(self, arg: str) -> None:
        if not arg.strip():
            console.print("[italic]Usage: p <expr>[/]")
            return
        try:
            console.print(Pretty(self._getval(arg), max_length=300))
        except Exception as e:
            self.print_error(str(e))

    def do_where(self, arg: str) -> None:
        self._render_stack()

    do_w = do_where

    @accepts_int_arg
    def do_frame(self, frame_id: int | None) -> bool | None:
        stack = self.build_call_stack()
        if frame_id is None:
            self._show_list()
            return None

        if frame_id < 1:
            self.print_error("Frame ID should be >= 1, check call stack with `w` command")
            return None
        if frame_id < 1:
            self.print_error("Frame index is above deepest frame index")
            return None
        stack_idx = frame_id - 1
        target_frame = stack[stack_idx]
        self.curframe = target_frame

        self._show_list()
        return None

    def _show_list(self, lines: int | None = None) -> None:
        frame = self.curframe
        if frame is None:
            self.print_error("Running out of a frame context. Cannot show source")
            return
        self._render_source_block(
            frame.f_code.co_filename, frame.f_lineno, lines or self.context_lines
        )

    @accepts_int_arg
    def do_list(self, lines: int | None) -> bool | None:  # type: ignore[override]
        """Syntax highlighted single window listing."""
        self._show_list(lines)
        return None

    do_l = do_list  # type: ignore[assignment]

    def do_longlist(self, arg: str) -> None:
        """Full file listing."""
        frame = self.curframe
        if frame is None:
            self.print_error("Running out of a frame context. Cannot show source")
            return
        self._render_full_file(frame.f_code.co_filename, frame.f_lineno)

    # All shell command variant
    do_ll = do_longlist
    do_shell = partialmethod(run_shell_command, format=False, pretty=False)
    do_sh = do_shell
    do_fshell = partialmethod(run_shell_command, format=True, pretty=False)
    do_fsh = do_fshell
    do_prettyshell = partialmethod(run_shell_command, format=False, pretty=True)
    do_psh = do_prettyshell
    do_fprettyshell = partialmethod(run_shell_command, format=True, pretty=True)
    do_fpsh = do_fprettyshell
    do_pfsh = do_fprettyshell

    def message(self, msg: str) -> None:
        if msg:
            console.print(msg, end="")


# ----------------------- Public set_trace ------------------------------


def set_trace(*, header: str | None = None) -> None:
    """Drop into RichPdb."""
    current_frame = inspect.currentframe()
    frame = current_frame.f_back if current_frame else None
    dbg = RichPdb()
    dbg.reset()
    if header is not None:
        dbg.message(header)
    dbg.set_trace(frame)


def post_mortem(exc_info: OptExcInfo | None = None) -> None:
    """
    Activate post-mortem debugging of the given traceback object.
    If no traceback is given, it uses the one of the exception that is
    currently being handled.
    """
    if exc_info is None or exc_info == (None, None, None):
        # exc_info cannot be tuple[None, None, None]
        exc_info = sys.exc_info()  # type: ignore[assignment]
    *_, tb = exc_info
    dbg = RichPdb()
    dbg.reset()
    console.print("[bold red]Post-mortem debugging[/]")
    dbg.interaction(None, tb)


# ----------------------- Breakpoint integration ------------------------
def breakpoint(*args: object, **kwargs: object) -> None:
    """Make breakpoint() invoke nicerpdb automatically."""
    # TODO: do not allocate new trace if one has already been created
    set_trace()
