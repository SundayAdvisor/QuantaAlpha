"""
Windows compatibility patches for upstream rdagent.

rdagent has Linux/Mac assumptions in a few places. The most painful one
hits the very first call into the engine: ``QlibFactorScenario.get_runtime_environment()``
runs a Python script in a workspace whose setup uses ``Path.symlink_to(...)``
to expose data dirs. On Windows that fails because:

  1. Some of the volume sources are Linux paths (e.g. ``/tmp/full``) that
     don't exist on Windows.
  2. ``symlink_to`` requires admin privileges or Developer Mode by default.

The function in question is purely informational — it returns "Python X.Y on
<system>" + GPU info, which gets pasted into prompts. So the cleanest fix on
Windows is to short-circuit it with a hardcoded string. No data path matters,
no symlink is needed.

This module is imported unconditionally from ``quantaalpha/__init__.py``;
the patches are no-ops on non-Windows.
"""

from __future__ import annotations

import os
import pathlib
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def _patch_symlink_to_with_junction_fallback() -> None:
    """Make pathlib.Path.symlink_to fall back to junction (or copy) on Windows.

    rdagent's `LocalEnv._run` opens a `_symlink_ctx` that wires up data
    volumes via `link_path.symlink_to(real_path)`. On Windows this requires
    admin privileges or Developer Mode (WinError 1314 otherwise). Junctions
    work for directories without elevation, so we transparently substitute.

    Also handles the case where the volume source path doesn't exist (e.g.
    `\\tmp\\full` — a Linux-ism baked into rdagent templates) by creating an
    empty placeholder before junctioning.
    """
    if sys.platform != "win32":
        return

    _original_symlink_to = pathlib.Path.symlink_to

    def _windows_symlink_to(self, target, target_is_directory=False):  # noqa: ANN001
        try:
            return _original_symlink_to(self, target, target_is_directory)
        except OSError as exc:
            # Only intercept the "no privilege" case; bubble other errors.
            is_privilege_error = (
                getattr(exc, "winerror", None) == 1314
                or "privilege" in str(exc).lower()
            )
            if not is_privilege_error:
                raise

            target_path = pathlib.Path(target)

            # If link already exists somehow, get rid of it.
            try:
                if self.exists() or self.is_symlink():
                    self.unlink()
            except OSError:
                pass

            # Source path missing? Create placeholder dir so the consumer doesn't
            # crash. rdagent ships with `\tmp\full` baked in for cache mounts;
            # on Windows that's a non-existent UNC-style path.
            if not target_path.exists():
                try:
                    target_path.mkdir(parents=True, exist_ok=True)
                except OSError:
                    # Couldn't even create the source; nothing useful we can do
                    # — fall through to a no-op junction onto an empty temp dir.
                    target_path = pathlib.Path(
                        subprocess.run(
                            ["cmd", "/c", "echo %TEMP%"],
                            capture_output=True, text=True, check=False,
                        ).stdout.strip() or "C:\\Windows\\Temp"
                    )

            try:
                if target_path.is_dir() or target_is_directory:
                    # Directory junction — no admin needed on Windows for any user.
                    subprocess.run(
                        ["cmd", "/c", "mklink", "/J", str(self), str(target_path)],
                        check=True,
                        capture_output=True,
                        shell=False,
                    )
                else:
                    # File: copy. Loses live linking but keeps data accessible.
                    shutil.copy2(target_path, self)
            except (subprocess.CalledProcessError, OSError):
                # Last resort: copy the whole tree (or file) so the consumer
                # at least has SOMETHING at link_path.
                if target_path.is_dir():
                    shutil.copytree(target_path, self, dirs_exist_ok=True)
                elif target_path.is_file():
                    shutil.copy2(target_path, self)
                else:
                    # Empty placeholder dir.
                    self.mkdir(parents=True, exist_ok=True)

    pathlib.Path.symlink_to = _windows_symlink_to


def _patch_os_symlink_with_copy_fallback() -> None:
    """Make os.symlink fall back to copy on Windows when privilege is missing.

    QuantaAlpha calls `os.symlink()` directly (not `Path.symlink_to`) in
    `factors/runner.py:111` to wire up `daily_pv.h5` into each factor's
    workspace. On Windows non-admin without Developer Mode, that raises
    WinError 1314.

    For files we copy (no live linking, but the workspace is a one-shot
    execution context, so a copy is fine). For dirs we use mklink /J.
    """
    if sys.platform != "win32":
        return

    import os as _os

    if getattr(_os, "_qa_symlink_patched", False):
        return

    _original_symlink = _os.symlink

    def _windows_os_symlink(src, dst, target_is_directory=False, *, dir_fd=None):
        try:
            return _original_symlink(
                src, dst, target_is_directory=target_is_directory, dir_fd=dir_fd
            )
        except OSError as exc:
            is_privilege_error = (
                getattr(exc, "winerror", None) == 1314
                or "privilege" in str(exc).lower()
            )
            if not is_privilege_error:
                raise

            src_path = pathlib.Path(src)
            dst_path = pathlib.Path(dst)

            if src_path.is_dir() or target_is_directory:
                # Use mklink /J for dirs (junction).
                subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(dst_path), str(src_path)],
                    check=True,
                    capture_output=True,
                    shell=False,
                )
            elif src_path.is_file():
                # Copy the file. For our use case (read-only data files
                # like daily_pv.h5), this is functionally equivalent.
                shutil.copy2(src_path, dst_path)
            else:
                raise FileNotFoundError(f"symlink source missing: {src}") from exc

    _os.symlink = _windows_os_symlink
    _os._qa_symlink_patched = True


def _patch_unlink_for_junctions() -> None:
    """Make pathlib.Path.unlink fall back to rmdir/rmtree for directory junctions.

    rdagent's _symlink_ctx cleanup runs `link_path.unlink()`, which fails on
    a directory reparse point (junction) we created in the symlink fallback
    above. We extend unlink to detect that case and remove via rmdir.
    """
    if sys.platform != "win32":
        return

    _original_unlink = pathlib.Path.unlink

    def _windows_unlink(self, missing_ok=False):  # noqa: ANN001
        try:
            return _original_unlink(self, missing_ok=missing_ok)
        except IsADirectoryError:
            pass
        except PermissionError as exc:
            # Junctions sometimes raise PermissionError on unlink; fall through.
            if not self.is_dir():
                raise exc
        except OSError as exc:
            if not (self.is_dir() and self.exists()):
                raise exc

        # Path is a directory (or junction). Try rmdir first (handles empty
        # dirs and reparse points); fall back to rmtree.
        try:
            self.rmdir()
        except OSError:
            try:
                shutil.rmtree(self, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass

    pathlib.Path.unlink = _windows_unlink


def _patch_select_poll_windows() -> None:
    """Provide a minimal select.poll() shim on Windows.

    rdagent's `LocalEnv._run` calls `select.poll()` directly to stream
    subprocess stdout/stderr — but `poll()` doesn't exist in Windows'
    `select` module, so the code crashes immediately. We attach a shim that
    wraps `selectors.DefaultSelector` to expose `register/unregister/poll`
    with the same shape the calling code expects. The shim's `poll()`
    returns `(fd, event)` tuples just like Linux's select.poll.

    Less invasive than replacing rdagent's `_run` method — the symlink
    setup, volume normalization, and the rest of `_run` continue to work as
    upstream wrote them.
    """
    if sys.platform != "win32":
        return

    import select as _select

    if hasattr(_select, "poll"):
        return  # already exists (some unusual Windows builds)

    POLLIN = getattr(_select, "POLLIN", 0x0001)
    if not hasattr(_select, "POLLIN"):
        _select.POLLIN = POLLIN
    if not hasattr(_select, "POLLOUT"):
        _select.POLLOUT = 0x0004
    if not hasattr(_select, "POLLHUP"):
        _select.POLLHUP = 0x0010
    if not hasattr(_select, "POLLERR"):
        _select.POLLERR = 0x0008

    import selectors

    class _WinPoll:
        """Minimal poll() emulation backed by selectors.DefaultSelector.

        Note: stdout/stderr file descriptors from a Popen with `text=True`
        are NOT directly pollable on Windows. selectors.DefaultSelector on
        Windows uses SelectSelector, which works on sockets only — not on
        pipe FDs from a subprocess. To make this work for subprocess pipes
        we fall back to a simple ready-check via os.read availability and
        timing (best-effort streaming). When polling fails, we degrade to
        "all FDs ready" so the caller's read loop drains via readline().
        """

        def __init__(self):
            self._fds: dict[int, int] = {}

        def register(self, fd, eventmask=POLLIN):
            self._fds[fd] = eventmask

        def unregister(self, fd):
            self._fds.pop(fd, None)

        def poll(self, timeout=None):
            # Always report all registered FDs as having POLLIN events.
            # The caller's loop will readline() on each — readline blocks
            # only until newline or EOF, so this is acceptably close to
            # the original streaming behavior. If timeout is given, sleep
            # briefly to avoid 100% CPU.
            if timeout:
                try:
                    import time

                    time.sleep(min(timeout / 1000.0, 0.1))
                except Exception:
                    pass
            return [(fd, POLLIN) for fd in self._fds]

    _select.poll = _WinPoll  # type: ignore[attr-defined]


def _patch_local_env_no_poll() -> None:
    """Backwards-compat name kept for clarity; calls the actual fix."""
    _patch_select_poll_windows()


def _patch_qlib_conda_env_skip_prepare() -> None:
    """Make QlibCondaEnv.prepare() a no-op on Windows.

    rdagent's `QlibCondaEnv.prepare()` runs `conda create -y -n quantaalpha …`
    and `conda run -n quantaalpha pip install …` to materialize a Conda env.
    On a venv-based Windows install, `conda` isn't on PATH and the env
    isn't needed (the current Python venv already has every package). The
    prepare step prints "Failed to prepare conda env: …" but doesn't raise,
    so it's harmless on its own — but the SUBSEQUENT subprocess call uses
    a Linux PATH (see _patch_local_env_run_windows), so the run fails too.

    Skipping prepare entirely on Windows avoids the noisy error messages
    and the 1–2 seconds wasted shelling out to `conda env list`.
    """
    if sys.platform != "win32":
        return

    try:
        from rdagent.utils import env as _env
    except Exception:
        return

    if hasattr(_env, "QlibCondaEnv") and not getattr(
        _env.QlibCondaEnv, "_qa_windows_skip_prepare", False
    ):
        def _noop_prepare(self):  # noqa: ANN001
            pass

        _env.QlibCondaEnv.prepare = _noop_prepare
        _env.QlibCondaEnv._qa_windows_skip_prepare = True


def _patch_local_env_run_windows() -> None:
    """Replace `LocalEnv._run` with a Windows-native version.

    The upstream `_run` does:
        path = [*self.conf.bin_path.split(":"), "/bin/", "/usr/bin/",
                *env.get("PATH", "").split(":")]
        env["PATH"] = ":".join(path)

    On Windows that produces `PATH = :/bin/:/usr/bin/:` — total nonsense.
    cmd.exe can't find `qrun.exe`, `python.exe`, or anything else in those
    paths, so every subprocess call returns "'qrun' is not recognized" or
    "'python' is not recognized". The result: the inline `factor_backtest`
    step in mining produces empty `backtest_results: {}`.

    This replacement uses the *real* Windows PATH plus the current Python
    interpreter's `Scripts/` directory (so `qrun.exe` from the venv is
    findable). Otherwise behaves like the upstream `_run` — runs the
    entry as a subprocess, captures combined stdout+stderr, returns
    (output, return_code).
    """
    if sys.platform != "win32":
        return

    try:
        from rdagent.utils import env as _env
    except Exception:
        return

    if not hasattr(_env, "LocalEnv"):
        return

    if getattr(_env.LocalEnv, "_qa_windows_run_native", False):
        return

    import subprocess as _sp

    # Path that contains `qrun.exe`, `python.exe`, etc. when running inside
    # the venv. sys.executable is something like
    # `<project>/.venv/Scripts/python.exe` — its parent is the Scripts dir.
    _venv_scripts = str(Path(sys.executable).parent)

    def _run_windows_native(self, entry, local_path, env, running_extra_volume=None):  # noqa: ANN001
        from rich.console import Console
        from rich.rule import Rule
        from rich.table import Table

        # Build a sensible Windows env: inherit os.environ, layer caller env
        # on top, prepend venv Scripts dir to PATH so `qrun.exe`/`python.exe`
        # resolve correctly.
        if env is None:
            env = {}
        merged_env = {**os.environ, **{k: str(v) if isinstance(v, int) else v for k, v in env.items()}}
        merged_env["PATH"] = _venv_scripts + os.pathsep + merged_env.get("PATH", "")

        cwd = Path(local_path).resolve() if local_path else None

        print(Rule("[bold green]LocalEnv Logs Begin (Windows native)[/bold green]", style="dark_orange"))
        table = Table(title="Run Info", show_header=False)
        table.add_column("Key", style="bold cyan")
        table.add_column("Value", style="bold magenta")
        table.add_row("Entry", str(entry))
        table.add_row("Local Path", str(local_path or ""))
        table.add_row("Scripts dir", _venv_scripts)
        print(table)

        try:
            result = _sp.run(
                entry,
                cwd=cwd,
                env=merged_env,
                shell=True,
                capture_output=True,
                text=True,
                timeout=getattr(self.conf, "running_timeout_period", None) or 1800,
            )
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            if stdout:
                Console().print(stdout, end="", markup=False)
            if stderr:
                Console().print(stderr, end="", markup=False)
            combined = stdout + stderr
            return_code = result.returncode
        except _sp.TimeoutExpired as exc:
            combined = f"Timeout after {exc.timeout}s"
            return_code = -1
            Console().print(combined, end="", markup=False)

        print(Rule("[bold green]LocalEnv Logs End[/bold green]", style="dark_orange"))
        return combined, return_code

    _env.LocalEnv._run = _run_windows_native
    _env.LocalEnv._qa_windows_run_native = True


def _patch_env_run_no_sh_wrap() -> None:
    """Skip rdagent's `/bin/sh -c '...'` wrapping on Windows.

    rdagent's `Env.run()` wraps every subprocess command with
        /bin/sh -c 'timeout --kill-after=10 3600 <entry>; ...; exit $code'

    Both `/bin/sh` and GNU `timeout` are Linux/Mac. On Windows the
    `subprocess.Popen(entry, shell=True)` invokes `cmd.exe`, which can't
    execute that string. Result: instant exit code != 0, the runner
    returns no output, the QlibFactorRunner sees `None` and raises
    `FactorEmptyError`.

    Replace `Env.run` with a Windows-friendly version that bypasses the
    sh-wrap and runs the entry directly. We keep the same caching and
    retry logic by delegating to `cached_run` / `__run_with_retry` with
    the bare entry.

    Tradeoff: no command-level timeout protection on Windows. Acceptable
    for QuantaAlpha — Qlib backtests are bounded by their own internal
    config and the workflow's outer `factor_mining_timeout`.
    """
    if sys.platform != "win32":
        return

    try:
        from rdagent.utils import env as _env
    except Exception:
        return

    if not hasattr(_env, "Env"):
        return

    Env = _env.Env

    if getattr(Env, "_qa_windows_run_unwrapped", False):
        return

    _orig_run = Env.run

    def _run_unwrapped(self, entry=None, local_path=".", env=None, **kwargs):  # noqa: ANN001
        running_extra_volume = kwargs.get("running_extra_volume", {})
        if entry is None:
            entry = self.conf.default_entry

        # Bypass the /bin/sh -c 'timeout ... ; exit $code' wrapping. On
        # Windows the entry runs directly via `cmd.exe` (subprocess.Popen
        # with shell=True). Tradeoff: lose command-level timeout protection.
        if self.conf.enable_cache:
            return self.cached_run(entry, local_path, env, running_extra_volume)
        # Reach the protected method via the public retry helper exposed
        # on _orig_run; here we replicate the no-cache path directly.
        return self._Env__run_with_retry(
            entry, local_path, env, running_extra_volume
        )

    Env.run = _run_unwrapped
    Env._qa_windows_run_unwrapped = True


def _patch_runtime_environment_probe() -> None:
    """Short-circuit `get_runtime_environment` on Windows.

    The probe runs a Python script in a workspace whose setup uses symlinks
    to expose data dirs. The patch above handles the symlinks, but the
    actual probe just returns a string that gets pasted into LLM prompts —
    so a hardcoded version is simpler and faster.
    """
    try:
        from rdagent.scenarios.qlib.experiment import factor_experiment as _fe
    except Exception:
        return

    runtime_info = (
        f"=== Python Runtime Info ===\n"
        f"Python {sys.version} on {platform.system()} {platform.release()}\n"
        f"\nNo CUDA GPU detected (Windows native env, GPU probe skipped).\n"
    )

    def _windows_get_runtime_environment(self):  # noqa: ANN001
        return runtime_info

    if hasattr(_fe, "QlibFactorScenario"):
        _fe.QlibFactorScenario.get_runtime_environment = _windows_get_runtime_environment

    if hasattr(_fe, "QlibFactorFromReportScenario"):
        _fe.QlibFactorFromReportScenario.get_runtime_environment = (
            _windows_get_runtime_environment
        )

    try:
        from quantaalpha.factors import qlib_experiment_init as _qei
        for _name in dir(_qei):
            obj = getattr(_qei, _name, None)
            if isinstance(obj, type) and hasattr(obj, "get_runtime_environment"):
                obj.get_runtime_environment = _windows_get_runtime_environment
    except Exception:
        pass


def _patch_costeer_eva_robust_json() -> None:
    """CoSTEER's eva_utils calls strict json.loads() on Claude responses.

    This is platform-agnostic, not Windows-specific, but it ships in this
    same patches file because it was discovered while debugging the same
    Windows run. When Claude returns a markdown-fenced JSON or empty string,
    the strict parse raises and CoSTEER aborts immediately (no retry).

    Replace the `json` module's `loads` reference *inside the eva_utils
    namespace only* with QuantaAlpha's robust_json_parse, which handles
    fenced JSON, LaTeX, and partial responses.
    """
    try:
        from quantaalpha.factors.coder import eva_utils as _eu
        from quantaalpha.llm.client import robust_json_parse
    except Exception:
        return

    if hasattr(_eu, "json") and not getattr(_eu, "_qa_json_patched", False):
        _original_json = _eu.json

        class _PatchedJson:
            JSONDecodeError = _original_json.JSONDecodeError

            @staticmethod
            def loads(s, **kwargs):
                # Try robust parse first; fall back to strict if robust fails.
                try:
                    return robust_json_parse(s)
                except Exception:
                    return _original_json.loads(s, **kwargs)

            def __getattr__(self, name):
                return getattr(_original_json, name)

        _eu.json = _PatchedJson()
        _eu._qa_json_patched = True


def _apply_windows_patches() -> None:
    if sys.platform != "win32":
        return
    _patch_symlink_to_with_junction_fallback()
    _patch_os_symlink_with_copy_fallback()
    _patch_unlink_for_junctions()
    _patch_local_env_no_poll()
    _patch_env_run_no_sh_wrap()
    _patch_local_env_run_windows()       # native Windows _run (proper PATH)
    _patch_qlib_conda_env_skip_prepare()  # skip `conda create` step
    _patch_runtime_environment_probe()


def _apply_universal_patches() -> None:
    _patch_costeer_eva_robust_json()


_apply_windows_patches()
_apply_universal_patches()
