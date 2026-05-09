"""
QuantaAlpha custom workspace.

Overrides rdagent QlibFBWorkspace: project-level factor_template overrides default YAML;
base files (read_exp_res.py, etc.) still from rdagent; init empty git repo in workspace to suppress qlib recorder git output.

Per-run override:
    Set $QA_TEMPLATE_OVERRIDE_DIR to a directory containing patched conf_*.yaml
    files (e.g. with custom market / segments). When set, that directory is
    layered ON TOP of the project factor_template, so individual files in the
    override dir replace their counterparts. Used by the FE backend to inject
    universe + date overrides at run-start.
"""

import os
import subprocess
from pathlib import Path

from rdagent.scenarios.qlib.experiment.workspace import QlibFBWorkspace as _RdagentQlibFBWorkspace
from rdagent.log import rdagent_logger as logger

_CUSTOM_TEMPLATE_DIR = Path(__file__).resolve().parent / "factor_template"


def _per_run_override_dir() -> Path | None:
    val = os.environ.get("QA_TEMPLATE_OVERRIDE_DIR")
    if not val:
        return None
    p = Path(val)
    return p if p.exists() and p.is_dir() else None


class QlibFBWorkspace(_RdagentQlibFBWorkspace):
    """
    Override rdagent QlibFBWorkspace: inject project factor_template/ YAML over defaults;
    init empty git repo in workspace to avoid qlib recorder git help output.
    """

    def __init__(self, template_folder_path: Path, *args, **kwargs) -> None:
        super().__init__(template_folder_path, *args, **kwargs)
        if _CUSTOM_TEMPLATE_DIR.exists():
            self.inject_code_from_folder(_CUSTOM_TEMPLATE_DIR)
            logger.info(f"Overrode rdagent default config with project template: {_CUSTOM_TEMPLATE_DIR}")
        # Layer per-run override on top (universe / dates / etc.)
        override_dir = _per_run_override_dir()
        if override_dir is not None:
            self.inject_code_from_folder(override_dir)
            logger.info(f"Applied per-run template override from: {override_dir}")

    def before_execute(self) -> None:
        """Init empty git repo in workspace to suppress qlib recorder git warnings."""
        super().before_execute()
        git_dir = self.workspace_path / ".git"
        if not git_dir.exists():
            try:
                subprocess.run(
                    ["git", "init"],
                    cwd=str(self.workspace_path),
                    capture_output=True,
                    timeout=5,
                )
            except Exception:
                pass
