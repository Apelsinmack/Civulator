# Dev tooling — type checking and code intelligence

pyright checks the Python side, clangd the C++ in `cpp/`. Both are what Claude Code's
`pyright-lsp` / `clangd-lsp` plugins and VS Code talk to, so the editor and the agent
see the same diagnostics. The machine-side install (binaries, PATH, plugins) lives in
Erik's ClaudeSync `environment.md`; everything below is repo-side.

## pyright

```bash
pyright          # whole Python tree; config in pyrightconfig.json
```

`extraPaths` carries the repo root and `scripts`, matching what the suite actually puts
on `sys.path` (`tests/conftest.py` inserts the root; several tests insert `scripts`).
`archive/` is excluded — 46 files of superseded code that would swamp the signal.

## clangd

clangd needs `compile_commands.json`, which the Visual Studio generator never writes, so
configure once more with Ninja from a shell that has run `vcvars64.bat`:

```bash
cmake -S cpp -B cpp/build-clangd -G Ninja -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
      -DCMAKE_BUILD_TYPE=Release -DPYTHON_EXECUTABLE=<data-env>/python.exe \
      -Dpybind11_DIR=<data-env>/Lib/site-packages/pybind11/share/cmake/pybind11
```

`cpp/.clangd` points clangd at that folder (gitignored). It is a **separate** directory on
purpose: `cpp/build` is configured with the Visual Studio generator, and CMake refuses a
Ninja configure into an existing VS build dir. `cpp/build-clangd` is a real build dir, so
`cmake --build cpp/build-clangd` produces a `.pyd` for stub generation without disturbing
the canonical `cpp/build/Release` that `civulator/game/map.py` loads at runtime.

## The `civulator_core` stub

`stubs/civulator_core.pyi` is what lets pyright see into the pybind11 module. It is
GENERATED — regenerate after any change to `cpp/src/bindings.cpp`, never hand-edit:

```bash
pip install pybind11-stubgen                       # once, into the data env
PYTHONPATH=cpp/build-clangd python -m pybind11_stubgen civulator_core -o stubs
```
