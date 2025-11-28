# NicerPDB

A terminal frontend for Python's `pdb` debugger, powered by `rich`.

## Install

```
pip install git+https://github.com/Hedwyn/nicerpdb.git
```

## Features

- Syntax-highlighted code display
- Improved variable inspection
- Enhanced stack traces
- Pretty-printed expressions

## Usage

### As an entrypoint

Simply substitute `pdb` by `nicerpdb`:

```
python -m nicerpdb <script_path>
```

### Invoke automatically on breakpoint

If you want `nicerpdb` to be invoked on a `breakpoint()` without using it explicitly as entyrypoint, you can set the `PYTHONBREAKPOINT` environment variable which allows customizing the debugger called on breakpoint:

- Set it persistently in your current session with:

```
export PYTHONBREAKPOINT=nicerpdb.set_trace
```

- Or for a single command using the usual environement variable syntax:

```
PYTHONBREAKPOINT=nicerpdb.set_trace python <script_path>
```

### Invoke automatically on test failure with pytest

`pytest` provides the `--pdb` option to invoke automatically `pdb` in post-mortem mode on test failure. `nicerpdb` provides a pytest plugin to provide the same functionality; replace `--pdb` by the following flags `-p nicerpdb -s` (`-p` loads a pytest plugin, `-s` disables output capturing so that the debugger can interact with the terminal).

## Extensions to PDB

### Additional commands

- `l` / `list`: support passing an integer defining the number of lines to show.
- `sh` / `shell`: runs a shell command and display the output within the debugger session. There are a few variants:
  - `psh`/ `prettyshell`: uses syntax highlighting on the output.
  - `fsh` / `fshell`: allows expanding variables from current Python frame's locals or globals into the shell command. The syntax is `%variable_name`. Please mind that `$` syntax (e.g. `$variable_name`) is already used for PDB's builtin convenience variables.
  - `pfsh` / `fpsh` / `fprettyshell`: enables all of the above.
