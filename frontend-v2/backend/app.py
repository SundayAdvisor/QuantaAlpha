"""
QuantaAlpha Backend API
FastAPI-based REST + WebSocket API for factor mining and backtesting.

Integrates with the core QuantaAlpha CLI to launch experiments
and reads factor library JSON for the factor browsing API.
"""

import asyncio
import glob
import json
import os
import signal
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Resolve project root (two levels up from this file: frontend-v2/backend/)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# Ensure import quantaalpha is available (when backend is started from frontend-v2 directory, repo root is not in sys.path)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
DOTENV_PATH = PROJECT_ROOT / ".env"

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="QuantaAlpha API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", "http://127.0.0.1:3000",
        "http://localhost:3001", "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========================== Pydantic Models ==========================


class MiningStartRequest(BaseModel):
    """Request to start a factor mining experiment."""
    direction: str = Field(..., description="Research direction, e.g. '价量因子挖掘'")
    displayName: Optional[str] = Field(None, description="Optional human-friendly name shown in History/Models in place of the raw timestamp ID")
    numDirections: Optional[int] = Field(2, description="Parallel exploration directions")
    maxRounds: Optional[int] = Field(3, description="Evolution rounds")
    maxLoops: Optional[int] = Field(2, description="Iterations per direction")
    factorsPerHypothesis: Optional[int] = Field(3, description="Factors per hypothesis")
    librarySuffix: Optional[str] = Field(None, description="Factor library file suffix")
    qualityGateEnabled: Optional[bool] = Field(None, description="Enable quality gate checks")
    parallelEnabled: Optional[bool] = Field(None, description="Enable parallel execution within evolution phases")
    # Universe + date overrides (Phase D — universe-aware mining)
    universe: Optional[str] = Field(None, description="qlib instruments universe name (sp500 | nasdaq100 | commodities) OR pseudo-name 'custom' when customTickers is supplied")
    customTickers: Optional[List[str]] = Field(None, description="Optional explicit ticker list. When set, backend writes a per-run instruments file and uses it as the universe. Recommend ≥30 tickers for stable RankIC.")
    trainStart: Optional[str] = Field(None, description="Train segment start date (YYYY-MM-DD)")
    trainEnd: Optional[str] = Field(None, description="Train segment end date (YYYY-MM-DD)")
    validStart: Optional[str] = Field(None, description="Valid segment start date (YYYY-MM-DD)")
    validEnd: Optional[str] = Field(None, description="Valid segment end date (YYYY-MM-DD)")
    testStart: Optional[str] = Field(None, description="Test segment start date (YYYY-MM-DD)")
    testEnd: Optional[str] = Field(None, description="Test segment end date (YYYY-MM-DD)")


class BacktestStartRequest(BaseModel):
    """Request to start an independent backtest."""
    factorJson: str = Field(..., description="Path to factor library JSON")
    factorSource: str = Field("custom", description="custom | combined")
    configPath: Optional[str] = Field(None, description="Path to backtest config")


class SystemConfigUpdate(BaseModel):
    """Partial update to system configuration (.env)."""
    QLIB_DATA_DIR: Optional[str] = None
    DATA_RESULTS_DIR: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: Optional[str] = None
    CHAT_MODEL: Optional[str] = None
    REASONING_MODEL: Optional[str] = None


class ApiResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    message: Optional[str] = None


# ========================== In-Memory State ==========================

tasks: Dict[str, Dict[str, Any]] = {}
ws_connections: Dict[str, List[WebSocket]] = {}  # task_id -> list of WS


# ========================== Utility Helpers ==========================

def _gen_id() -> str:
    return str(uuid.uuid4())[:8]


def _now() -> str:
    return datetime.now().isoformat()


def _load_dotenv_dict() -> Dict[str, str]:
    """Parse the .env file into a dict (simple key=value, ignoring comments)."""
    env: Dict[str, str] = {}
    if DOTENV_PATH.exists():
        for line in DOTENV_PATH.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                key, _, val = stripped.partition("=")
                env[key.strip()] = val.strip()
    return env


def _find_factor_jsons() -> List[str]:
    """Find all factor library JSON files in data/factorlib/."""
    factorlib_dir = PROJECT_ROOT / "data" / "factorlib"
    pattern = str(factorlib_dir / "all_factors_library*.json")
    results = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)

    old_pattern = str(PROJECT_ROOT / "all_factors_library*.json")
    old_results = sorted(glob.glob(old_pattern), key=os.path.getmtime, reverse=True)

    seen = set(results)
    for r in old_results:
        if r not in seen:
            results.append(r)
    return results


def _load_factor_library(path: str) -> Dict[str, Any]:
    """Load and parse a factor library JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _classify_quality(backtest_results: Dict[str, Any]) -> str:
    """Classify factor quality based on backtest metrics."""
    if not backtest_results:
        return "low"
    # Use information ratio or IC-related metrics
    ic = None
    for key in ["1day.excess_return_without_cost.information_ratio",
                 "1day.excess_return_with_cost.information_ratio"]:
        if key in backtest_results:
            ic = backtest_results[key]
            break
    if ic is None:
        # Try to find any IC-like metric
        for key, val in backtest_results.items():
            if "information_ratio" in key and isinstance(val, (int, float)):
                ic = val
                break
    if ic is None:
        return "medium"
    if ic > 0.5:
        return "high"
    if ic > 0.1:
        return "medium"
    return "low"


async def _broadcast(task_id: str, message: Dict[str, Any]):
    """Send a JSON message to all WebSocket clients for a task."""
    if task_id not in ws_connections:
        return
    dead: List[WebSocket] = []
    for ws in ws_connections[task_id]:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_connections[task_id].remove(ws)


# ========================== Mining Process ==========================

async def _run_mining(task_id: str, req: MiningStartRequest):
    """
    Launch the actual QuantaAlpha mining experiment as a subprocess
    and stream its output over WebSocket.
    """
    task = tasks[task_id]
    try:
        # Build the command
        env = os.environ.copy()
        # Load .env into env
        dotenv = _load_dotenv_dict()
        env.update(dotenv)

        # Use experiment_id as suffix to guarantee isolation
        experiment_id = f"exp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        env["EXPERIMENT_ID"] = experiment_id
        
        # Enforce unique library suffix if not provided
        if not req.librarySuffix:
            req.librarySuffix = experiment_id
            # Update task config so frontend knows the suffix
            task["config"]["librarySuffix"] = req.librarySuffix
            
        env["FACTOR_LIBRARY_SUFFIX"] = req.librarySuffix

        results_base = dotenv.get("DATA_RESULTS_DIR", str(PROJECT_ROOT / "data" / "results"))
        env["WORKSPACE_PATH"] = f"{results_base}/workspace_{experiment_id}"
        env["PICKLE_CACHE_FOLDER_PATH_STR"] = f"{results_base}/pickle_cache_{experiment_id}"

        os.makedirs(env["WORKSPACE_PATH"], exist_ok=True)
        os.makedirs(env["PICKLE_CACHE_FOLDER_PATH_STR"], exist_ok=True)

        # Qlib symlink (best-effort; YAML now uses absolute provider_uri so this is
        # only kept for backwards-compat with rdagent code paths that hardcode
        # ~/.qlib/qlib_data/cn_data). Skip silently if it already exists or fails —
        # on Windows the path may be a junction from `_windows_patches`, in which
        # case is_symlink() is False but the path can't be re-created without
        # removing the junction first. Failure here must not kill mining.
        qlib_data = dotenv.get("QLIB_DATA_DIR", "")
        if qlib_data:
            try:
                qlib_symlink_dir = Path.home() / ".qlib" / "qlib_data"
                qlib_symlink_dir.mkdir(parents=True, exist_ok=True)
                cn_data_link = qlib_symlink_dir / "cn_data"
                if not cn_data_link.exists():
                    cn_data_link.symlink_to(qlib_data)
            except OSError:
                pass

        # Build a temporary config with frontend parameter overrides
        base_config_path = PROJECT_ROOT / "configs" / "experiment.yaml"
        config_path_to_use = str(base_config_path)

        try:
            with open(base_config_path, "r", encoding="utf-8") as _f:
                run_cfg = yaml.safe_load(_f) or {}

            # Apply frontend overrides
            if req.numDirections is not None:
                run_cfg.setdefault("planning", {})["num_directions"] = req.numDirections
            if req.maxRounds is not None:
                run_cfg.setdefault("evolution", {})["max_rounds"] = req.maxRounds
            if req.maxLoops is not None:
                run_cfg.setdefault("execution", {})["max_loops"] = req.maxLoops
            if req.factorsPerHypothesis is not None:
                run_cfg.setdefault("factor", {})["factors_per_hypothesis"] = req.factorsPerHypothesis

            # Apply parallel execution override from frontend
            if req.parallelEnabled is not None:
                run_cfg.setdefault("evolution", {})["parallel_enabled"] = req.parallelEnabled
                run_cfg.setdefault("execution", {})["parallel_execution"] = req.parallelEnabled

            # Apply quality gate override from frontend
            if req.qualityGateEnabled is not None:
                qg = run_cfg.setdefault("quality_gate", {})
                if req.qualityGateEnabled:
                    # Enable quality gate: enable complexity and redundancy checks (default on), consistency keeps user YAML setting
                    qg.setdefault("complexity_enabled", True)
                    qg.setdefault("redundancy_enabled", True)
                    # Consistency check is expensive, only enable if explicitly enabled in YAML
                    qg.setdefault("consistency_enabled", False)
                else:
                    # Disable quality gate: disable all
                    qg["consistency_enabled"] = False
                    qg["complexity_enabled"] = False
                    qg["redundancy_enabled"] = False

            # Write to a temporary file so the original is untouched
            tmp_dir = Path(env.get("WORKSPACE_PATH", "/tmp"))
            tmp_dir.mkdir(parents=True, exist_ok=True)
            tmp_cfg = tmp_dir / "experiment_override.yaml"
            with open(tmp_cfg, "w", encoding="utf-8") as _f:
                yaml.safe_dump(run_cfg, _f, allow_unicode=True, default_flow_style=False)
            config_path_to_use = str(tmp_cfg)
        except Exception as cfg_err:
            # Fall back to original config if anything fails
            import traceback
            traceback.print_exc()

        # ─── Per-run universe + date overrides ──────────────────────────
        # If the user supplied universe / train / valid / test segments via the
        # FE, materialize patched factor_template/conf_*.yaml files into a per-
        # run override dir. The workspace loader picks this up via
        # QA_TEMPLATE_OVERRIDE_DIR (see quantaalpha/factors/workspace.py).
        try:
            # Custom-ticker path: write a per-run instruments file
            # data/qlib/us_data/instruments/<custom_name>.txt and rewrite the
            # universe field to that name.
            if req.customTickers:
                clean = [t.strip().upper() for t in req.customTickers if t and t.strip()]
                clean = [t for t in clean if t.replace("-", "").replace(".", "").isalnum()]
                if len(clean) >= 2:
                    qlib_root = Path(dotenv.get("QLIB_DATA_DIR", str(PROJECT_ROOT / "data" / "qlib" / "us_data")))
                    inst_dir = qlib_root / "instruments"
                    inst_dir.mkdir(parents=True, exist_ok=True)
                    suffix = req.librarySuffix or experiment_id
                    safe_suffix = "".join(c for c in suffix if c.isalnum() or c in "_-")
                    custom_name = f"custom_{safe_suffix}"
                    inst_path = inst_dir / f"{custom_name}.txt"
                    inst_path.write_text(
                        "\n".join(f"{t}\t1990-01-01\t2099-12-31" for t in clean) + "\n",
                        encoding="utf-8",
                    )
                    req.universe = custom_name
                    print(f"[mining] wrote custom universe '{custom_name}' with {len(clean)} tickers → {inst_path}")
            need_override = bool(
                req.universe
                or req.trainStart or req.trainEnd
                or req.validStart or req.validEnd
                or req.testStart or req.testEnd
            )
            if need_override:
                override_dir = Path(env["WORKSPACE_PATH"]) / "_template_override"
                override_dir.mkdir(parents=True, exist_ok=True)
                template_root = PROJECT_ROOT / "quantaalpha" / "factors" / "factor_template"
                for tpl_name in ("conf_baseline.yaml", "conf_combined_factors.yaml"):
                    src = template_root / tpl_name
                    if not src.exists():
                        continue
                    raw_text = src.read_text(encoding="utf-8")
                    cfg = yaml.safe_load(raw_text) or {}
                    # Patch market (universe). conf_baseline.yaml uses YAML anchors:
                    #   market: &market sp500
                    # so we patch the top-level scalar AND use string substitution
                    # on any anchor that may appear elsewhere.
                    if req.universe:
                        cfg["market"] = req.universe
                        # Also patch instruments + benchmark to a sane choice
                        if "qlib_init" in cfg and isinstance(cfg.get("qlib_init"), dict):
                            cfg["qlib_init"]["region"] = cfg["qlib_init"].get("region", "us")
                        # data_handler instruments
                        try:
                            dh = cfg["data_handler_config"]
                            if isinstance(dh, dict):
                                dh["instruments"] = req.universe
                        except Exception:
                            pass
                        # Benchmarks per universe
                        bench_for = {
                            "sp500":       "^gspc",
                            "nasdaq100":   "^ndx",
                            "commodities": "GLD",   # GLD as gold proxy
                        }.get(req.universe)
                        if bench_for:
                            cfg["benchmark"] = bench_for
                            try:
                                cfg["port_analysis_config"]["strategy"]["kwargs"]["benchmark"] = bench_for
                            except Exception:
                                pass
                    # Patch segments
                    try:
                        segs = cfg["task"]["dataset"]["kwargs"]["segments"]
                        if req.trainStart and req.trainEnd:
                            segs["train"] = [req.trainStart, req.trainEnd]
                        if req.validStart and req.validEnd:
                            segs["valid"] = [req.validStart, req.validEnd]
                        if req.testStart and req.testEnd:
                            segs["test"] = [req.testStart, req.testEnd]
                        # Top-level start_time / end_time enclose the whole range
                        try:
                            all_dates = (
                                (segs.get("train") or [])
                                + (segs.get("valid") or [])
                                + (segs.get("test") or [])
                            )
                            all_dates = [d for d in all_dates if d]
                            if all_dates:
                                cfg["data_handler_config"]["start_time"] = min(all_dates)
                                cfg["data_handler_config"]["end_time"] = max(all_dates)
                        except Exception:
                            pass
                        # Also patch the explicit backtest range (used by qlib's
                        # portfolio analyzer to bound the test backtest)
                        if req.testStart and req.testEnd:
                            try:
                                bk = cfg["port_analysis_config"]["backtest"]
                                bk["start_time"] = req.testStart
                                bk["end_time"] = req.testEnd
                            except Exception:
                                pass
                    except Exception:
                        pass
                    out = override_dir / tpl_name
                    out.write_text(
                        yaml.safe_dump(cfg, allow_unicode=True, default_flow_style=False),
                        encoding="utf-8",
                    )
                env["QA_TEMPLATE_OVERRIDE_DIR"] = str(override_dir)
                print(f"[mining] template override dir: {override_dir} "
                      f"(universe={req.universe} train={req.trainStart}->{req.trainEnd} "
                      f"valid={req.validStart}->{req.validEnd} test={req.testStart}->{req.testEnd})")
        except Exception:
            import traceback
            traceback.print_exc()
            # Non-fatal — mining continues with default template if patch fails

        # Build CLI args
        cmd = [
            sys.executable, "-m", "quantaalpha.cli", "mine",
            "--direction", req.direction,
            "--config_path", config_path_to_use,
        ]

        task["status"] = "running"
        task["progress"]["phase"] = "planning"
        task["progress"]["message"] = "正在启动实验..."
        task["updatedAt"] = _now()

        await _broadcast(task_id, {
            "type": "progress",
            "taskId": task_id,
            "data": task["progress"],
            "timestamp": _now(),
        })

        # Launch subprocess
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
            env=env,
        )
        task["pid"] = proc.pid

        # Stream stdout line by line
        line_count = 0
        current_phase = "planning"

        # Noisy patterns to suppress (shared with backtest)
        _MINING_NOISE = (
            "field data contains nan",
            "common_infra",
            "PyTorch models are skipped",
            "UserWarning: pkg_resources",
            "FutureWarning",
            "UserWarning",
            "Training until validation scores",
            "Did not meet early stopping",
        )

        while True:
            line_bytes = await proc.stdout.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            line_count += 1

            # Skip noisy warnings
            if any(p in line for p in _MINING_NOISE):
                continue

            # Detect phase from log messages
            new_phase = current_phase
            if "factor_propose" in line:
                new_phase = "evolving"
            elif "factor_backtest" in line or "backtest" in line.lower():
                new_phase = "backtesting"
            elif "feedback" in line:
                new_phase = "analyzing"
            elif "factor_calculate" in line:
                new_phase = "evolving"
            elif "规划" in line or "planning" in line.lower():
                new_phase = "planning"
            elif "进化完成" in line or "程序执行完成" in line:
                new_phase = "completed"

            if new_phase != current_phase:
                current_phase = new_phase
                task["progress"]["phase"] = current_phase
                task["progress"]["message"] = line[:200]
                task["progress"]["timestamp"] = _now()
                await _broadcast(task_id, {
                    "type": "progress",
                    "taskId": task_id,
                    "data": task["progress"],
                    "timestamp": _now(),
                })

            # Send log every line (throttle to avoid flooding)
            if line_count % 3 == 0 or "INFO" in line or "ERROR" in line or "WARNING" in line:
                level = "info"
                if "ERROR" in line or "Error" in line:
                    level = "error"
                elif "WARNING" in line or "Warning" in line:
                    level = "warning"
                elif "完成" in line or "success" in line.lower():
                    level = "success"

                log_entry = {
                    "id": _gen_id(),
                    "timestamp": _now(),
                    "level": level,
                    "message": line[:500],
                }
                task["logs"].append(log_entry)
                # Keep only last 500 logs in memory
                if len(task["logs"]) > 500:
                    task["logs"] = task["logs"][-500:]

                await _broadcast(task_id, {
                    "type": "log",
                    "taskId": task_id,
                    "data": log_entry,
                    "timestamp": _now(),
                })

            # Extract metrics from log lines like "RankIC=0.0016"
            if "RankIC=" in line:
                try:
                    rank_ic_str = line.split("RankIC=")[1].split(",")[0].split(")")[0]
                    task["metrics"]["rankIc"] = float(rank_ic_str)
                    await _broadcast(task_id, {
                        "type": "metrics",
                        "taskId": task_id,
                        "data": task["metrics"],
                        "timestamp": _now(),
                    })
                except Exception:
                    pass
            
            # Check for factor saving to update top factors list
            if "已保存" in line or "因子" in line:
                _update_mining_metrics(task)
                if task.get("metrics"):
                     await _broadcast(task_id, {
                        "type": "result",
                        "taskId": task_id,
                        "data": {"status": task["status"], "metrics": task["metrics"]},
                        "timestamp": _now(),
                    })

        exit_code = await proc.wait()
        task["pid"] = None

        if exit_code == 0:
            task["status"] = "completed"
            task["progress"]["phase"] = "completed"
            task["progress"]["progress"] = 100
            task["progress"]["message"] = "实验完成"
        else:
            task["status"] = "failed"
            task["progress"]["message"] = f"实验失败 (exit code: {exit_code})"

        task["updatedAt"] = _now()

        # Load final factor count from the library JSON
        # Prefer the library file matching the librarySuffix for this experiment
        _update_mining_metrics(task)

        # Stamp the run's log dir with a manifest so the History page can
        # show explicit linkages + the user's display_name. Best-effort.
        run_id = _find_run_id_for_task(task)
        if run_id:
            _write_run_manifest(task, run_id)

        # Auto-publish top findings (best-effort; default-on if findings repo exists).
        if task["status"] == "completed" and run_id:
            _auto_publish_qa_run(run_id)

        await _broadcast(task_id, {
            "type": "result",
            "taskId": task_id,
            "data": {"status": task["status"], "metrics": task["metrics"]},
            "timestamp": _now(),
        })

    except Exception as e:
        task["status"] = "failed"
        task["progress"]["message"] = f"Error: {str(e)}"
        task["updatedAt"] = _now()
        await _broadcast(task_id, {
            "type": "error",
            "taskId": task_id,
            "data": {"error": str(e)},
            "timestamp": _now(),
        })


# ========================== API Endpoints ==========================

@app.get("/")
async def root():
    return {"message": "QuantaAlpha API", "version": "2.0.0"}


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "timestamp": _now()}


# ---- Mining endpoints ----

@app.post("/api/v1/mining/start", response_model=ApiResponse)
async def start_mining(req: MiningStartRequest):
    """Start a new factor mining experiment."""
    task_id = _gen_id()
    task = {
        "taskId": task_id,
        "status": "running",
        "config": req.model_dump(),
        "progress": {
            "phase": "parsing",
            "currentRound": 0,
            "totalRounds": req.maxRounds or 3,
            "progress": 0,
            "message": "正在初始化实验...",
            "timestamp": _now(),
        },
        "logs": [],
        "metrics": {
            "ic": 0, "icir": 0, "rankIc": 0, "rankIcir": 0,
            "annualReturn": 0, "sharpeRatio": 0, "maxDrawdown": 0,
            "totalFactors": 0, "highQualityFactors": 0,
            "mediumQualityFactors": 0, "lowQualityFactors": 0,
        },
        "result": None,
        "pid": None,
        "createdAt": _now(),
        "updatedAt": _now(),
    }
    tasks[task_id] = task

    # Launch the mining process in background
    asyncio.create_task(_run_mining(task_id, req))

    return ApiResponse(
        success=True,
        data={"taskId": task_id, "task": task},
        message="实验已启动",
    )


@app.get("/api/v1/mining/{task_id}", response_model=ApiResponse)
async def get_mining_status(task_id: str):
    """Get task status."""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return ApiResponse(success=True, data={"task": tasks[task_id]})


@app.delete("/api/v1/mining/{task_id}", response_model=ApiResponse)
async def cancel_mining(task_id: str):
    """Cancel a running mining task."""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    task = tasks[task_id]
    if task.get("pid"):
        try:
            pid = task["pid"]
            # Try graceful termination first
            os.kill(pid, signal.SIGTERM)
            
            # Wait briefly for cleanup (0.5s)
            for _ in range(5):
                try:
                    os.kill(pid, 0) # Check if alive
                    await asyncio.sleep(0.1)
                except ProcessLookupError:
                    break
            
            # Force kill if still running
            try:
                os.kill(pid, 0)
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        except ProcessLookupError:
            pass
    task["status"] = "cancelled"
    task["updatedAt"] = _now()
    await _broadcast(task_id, {
        "type": "result",
        "taskId": task_id,
        "data": {"status": "cancelled"},
        "timestamp": _now(),
    })
    return ApiResponse(success=True, message="任务已取消")


@app.get("/api/v1/mining/tasks/list", response_model=ApiResponse)
async def list_tasks():
    """List all tasks."""
    task_list = sorted(tasks.values(), key=lambda t: t["createdAt"], reverse=True)
    return ApiResponse(success=True, data={"tasks": task_list})


# ---- Factor library endpoints ----

@app.get("/api/v1/factors", response_model=ApiResponse)
async def get_factors(
    quality: Optional[str] = Query(None, description="Filter by quality: high/medium/low"),
    search: Optional[str] = Query(None, description="Search by factor name"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    library: Optional[str] = Query(None, description="Specific library file name"),
):
    """Get factors from the factor library JSON."""
    # Find the most recent factor library
    if library:
        lib_path = str(PROJECT_ROOT / "data" / "factorlib" / library)
        # Fallback: check if file exists at project root (legacy location)
        if not Path(lib_path).exists():
            alt = str(PROJECT_ROOT / library)
            if Path(alt).exists():
                lib_path = alt
    else:
        jsons = _find_factor_jsons()
        if not jsons:
            return ApiResponse(
                success=True,
                data={"factors": [], "total": 0, "limit": limit, "offset": offset,
                      "libraries": []},
            )
        lib_path = jsons[0]

    try:
        raw = _load_factor_library(lib_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read factor library: {e}")

    factors_dict = raw.get("factors", {})
    metadata = raw.get("metadata", {})

    # Convert dict to list with quality classification
    factors_list: List[Dict[str, Any]] = []
    for factor_id, factor_info in factors_dict.items():
        if not isinstance(factor_info, dict):
            continue
        bt = factor_info.get("backtest_results", {})
        q = _classify_quality(bt)
        # Extract metrics with proper fallbacks
        # Try specific keys first, then standard ones
        ic = bt.get("IC", bt.get("1day.excess_return_without_cost.information_coefficient", 0))
        icir = bt.get("ICIR", bt.get("1day.excess_return_without_cost.information_coefficient_ir", 0))
        rank_ic = bt.get("Rank IC", bt.get("rank_ic", bt.get("1day.excess_return_without_cost.rank_ic", 0)))
        rank_icir = bt.get("Rank ICIR", bt.get("rank_ic_ir", bt.get("1day.excess_return_without_cost.rank_ic_ir", 0)))
        
        factor_entry = {
            "factorId": factor_info.get("factor_id", factor_id),
            "factorName": factor_info.get("factor_name", "Unknown"),
            "factorExpression": factor_info.get("factor_expression", ""),
            "factorDescription": factor_info.get("factor_description", ""),
            "factorFormulation": factor_info.get("factor_formulation", ""),
            "quality": q,
            "backtestResults": bt,
            # Extract key metrics
            "ic": ic,
            "icir": icir,
            "rankIc": rank_ic,
            "rankIcir": rank_icir,
            "annualReturn": bt.get("1day.excess_return_with_cost.annualized_return", 
                                  bt.get("1day.excess_return_without_cost.annualized_return", 0)),
            "maxDrawdown": bt.get("1day.excess_return_with_cost.max_drawdown", 
                                 bt.get("1day.excess_return_without_cost.max_drawdown", 0)),
            "sharpeRatio": bt.get("1day.excess_return_with_cost.information_ratio", 
                                bt.get("1day.excess_return_without_cost.information_ratio", 0)),
            "round": factor_info.get("evolution_metadata", {}).get("round", 0)
            if isinstance(factor_info.get("evolution_metadata"), dict) else 0,
            "direction": factor_info.get("evolution_metadata", {}).get("direction_index", "")
            if isinstance(factor_info.get("evolution_metadata"), dict) else "",
            "createdAt": factor_info.get("added_at", ""),
        }
        factors_list.append(factor_entry)

    # Apply filters
    if quality:
        factors_list = [f for f in factors_list if f["quality"] == quality]
    if search:
        search_lower = search.lower()
        factors_list = [
            f for f in factors_list
            if search_lower in f["factorName"].lower()
            or search_lower in f.get("factorDescription", "").lower()
            or search_lower in f.get("factorExpression", "").lower()
        ]

    total = len(factors_list)
    paginated = factors_list[offset: offset + limit]

    # Available library files
    all_libs = [Path(p).name for p in _find_factor_jsons()]

    return ApiResponse(
        success=True,
        data={
            "factors": paginated,
            "total": total,
            "limit": limit,
            "offset": offset,
            "metadata": metadata,
            "libraries": all_libs,
        },
    )


# ---- Factor cache endpoints ----
# IMPORTANT: These must be registered BEFORE /api/v1/factors/{factor_id}
# otherwise FastAPI matches "cache-status" as a factor_id parameter.

@app.get("/api/v1/factors/cache-status", response_model=ApiResponse)
async def get_cache_status(
    library: Optional[str] = Query(None, description="Factor library JSON filename"),
):
    """Check cache status of factors in the specified factor library."""
    if library:
        lib_path = str(PROJECT_ROOT / "data" / "factorlib" / library)
        if not Path(lib_path).exists():
            alt = str(PROJECT_ROOT / library)
            if Path(alt).exists():
                lib_path = alt
    else:
        jsons = _find_factor_jsons()
        if not jsons:
            return ApiResponse(success=True, data={
                "total": 0, "h5_cached": 0, "md5_cached": 0,
                "need_compute": 0, "factors": [],
            })
        lib_path = jsons[0]

    if not Path(lib_path).exists():
        raise HTTPException(status_code=404, detail=f"Factor library not found: {library}")

    # Import from core library
    from quantaalpha.factors.library import FactorLibraryManager
    result = FactorLibraryManager.check_cache_status(lib_path)
    return ApiResponse(success=True, data=result)


@app.post("/api/v1/factors/warm-cache", response_model=ApiResponse)
async def warm_cache(
    library: Optional[str] = Query(None, description="Factor library JSON filename"),
):
    """Batch sync from result.h5 to MD5 cache directory."""
    if library:
        lib_path = str(PROJECT_ROOT / "data" / "factorlib" / library)
        if not Path(lib_path).exists():
            alt = str(PROJECT_ROOT / library)
            if Path(alt).exists():
                lib_path = alt
    else:
        jsons = _find_factor_jsons()
        if not jsons:
            return ApiResponse(success=False, error="未找到因子库文件")
        lib_path = jsons[0]

    if not Path(lib_path).exists():
        raise HTTPException(status_code=404, detail=f"Factor library not found: {library}")

    from quantaalpha.factors.library import FactorLibraryManager
    result = FactorLibraryManager.warm_cache_from_json(lib_path)
    # Build a clear message
    parts = []
    if result['synced']:
        parts.append(f"新同步 {result['synced']} 个")
    if result.get('already_cached'):
        parts.append(f"已有缓存 {result['already_cached']} 个")
    if result.get('no_source'):
        parts.append(f"无H5源 {result['no_source']} 个(回测时从表达式计算)")
    if result['failed']:
        parts.append(f"失败 {result['failed']} 个")
    msg = "，".join(parts) if parts else "无需操作"
    return ApiResponse(
        success=True,
        data=result,
        message=msg,
    )


# ---- Factor library list endpoint (must be BEFORE {factor_id} route) ----

@app.get("/api/v1/factors/libraries", response_model=ApiResponse)
async def list_factor_libraries():
    """List all factor library JSON files in the project root."""
    libs = [Path(p).name for p in _find_factor_jsons()]
    return ApiResponse(success=True, data={"libraries": libs})


@app.get("/api/v1/factors/{factor_id}", response_model=ApiResponse)
async def get_factor_detail(factor_id: str):
    """Get full detail of a single factor."""
    jsons = _find_factor_jsons()
    for lib_path in jsons:
        try:
            raw = _load_factor_library(lib_path)
            factors = raw.get("factors", {})
            if factor_id in factors:
                info = factors[factor_id]
                return ApiResponse(success=True, data={"factor": info})
        except Exception:
            continue
    raise HTTPException(status_code=404, detail="Factor not found")


# ---- Backtest endpoints ----

@app.post("/api/v1/backtest/start", response_model=ApiResponse)
async def start_backtest(req: BacktestStartRequest):
    """Start an independent backtest."""
    task_id = _gen_id()
    config_path = req.configPath or str(PROJECT_ROOT / "configs" / "backtest.yaml")

    task = {
        "taskId": task_id,
        "status": "running",
        "type": "backtest",
        "config": {**req.model_dump(), "configPath": config_path},
        "progress": {
            "phase": "backtesting",
            "currentRound": 0,
            "totalRounds": 1,
            "progress": 0,
            "message": "正在启动回测...",
            "timestamp": _now(),
        },
        "logs": [],
        "metrics": {},
        "result": None,
        "pid": None,
        "createdAt": _now(),
        "updatedAt": _now(),
    }
    tasks[task_id] = task

    # Launch backtest in background
    asyncio.create_task(_run_backtest(task_id, req, config_path))
    return ApiResponse(
        success=True,
        data={"taskId": task_id, "task": task},
        message="回测已启动",
    )


@app.get("/api/v1/backtest/{task_id}", response_model=ApiResponse)
async def get_backtest_status(task_id: str):
    """Get backtest task status and results."""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return ApiResponse(success=True, data={"task": tasks[task_id]})


@app.delete("/api/v1/backtest/{task_id}", response_model=ApiResponse)
async def cancel_backtest(task_id: str):
    """Cancel a running backtest task."""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    task = tasks[task_id]
    if task.get("pid"):
        try:
            os.kill(task["pid"], signal.SIGTERM)
        except ProcessLookupError:
            pass
    task["status"] = "cancelled"
    task["updatedAt"] = _now()
    await _broadcast(task_id, {
        "type": "result",
        "taskId": task_id,
        "data": {"status": "cancelled"},
        "timestamp": _now(),
    })
    return ApiResponse(success=True, message="回测已取消")


async def _run_backtest(task_id: str, req: BacktestStartRequest, config_path: str):
    """Run the independent backtest (V2) as a subprocess."""
    task = tasks[task_id]
    try:
        env = os.environ.copy()
        dotenv = _load_dotenv_dict()
        env.update(dotenv)

        # --- Resolve factor JSON path ---
        # Frontend sends just the filename (e.g. "all_factors_library_test3hjback.json")
        # We need to resolve it to the full path under data/factorlib/
        factor_json_input = req.factorJson
        factor_json_path = Path(factor_json_input)
        if not factor_json_path.is_absolute():
            # Check data/factorlib/ first
            candidate = PROJECT_ROOT / "data" / "factorlib" / factor_json_input
            if candidate.exists():
                factor_json_path = candidate
            else:
                # Try as relative to project root
                candidate2 = PROJECT_ROOT / factor_json_input
                if candidate2.exists():
                    factor_json_path = candidate2
                else:
                    factor_json_path = candidate  # will fail with a clear error message
        factor_json_str = str(factor_json_path)

        # --- Find the correct Python executable ---
        # Prefer the conda env that has qlib installed
        conda_env = dotenv.get("CONDA_ENV_NAME", "quantaalpha")
        python_bin = sys.executable  # fallback

        # Dynamically detect conda base path (portable, no hardcoded paths)
        conda_prefixes = [os.path.expanduser(f"~/.conda/envs/{conda_env}")]
        try:
            import subprocess as _sp
            conda_base = _sp.check_output(
                ["conda", "info", "--base"], text=True, timeout=5
            ).strip()
            conda_prefixes.insert(0, os.path.join(conda_base, "envs", conda_env))
        except Exception:
            pass
        # Also check CONDA_PREFIX if we're already in the right env
        if os.environ.get("CONDA_PREFIX"):
            conda_prefixes.insert(0, os.environ["CONDA_PREFIX"])

        for prefix in conda_prefixes:
            candidate_bin = Path(prefix) / "bin" / "python"
            if candidate_bin.exists():
                python_bin = str(candidate_bin)
                break

        # Build CLI command
        cmd = [
            python_bin, "-m", "quantaalpha.backtest.run_backtest",
            "-c", config_path,
            "--factor-source", req.factorSource,
            "--factor-json", factor_json_str,
            "--skip-uncached",
            "-v",
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
            env=env,
        )
        task["pid"] = proc.pid

        # Noisy warnings from Qlib / dependencies that can be safely suppressed
        _NOISY_PATTERNS = (
            "field data contains nan",
            "common_infra",
            "PyTorch models are skipped",
            "UserWarning: pkg_resources",
            "Training until validation scores",
            "FutureWarning",
            "UserWarning",
            "Did not meet early stopping",
            "num_leaves is set=",
        )

        # --- Stream stdout ---
        log_entry = None
        while True:
            line_bytes = await proc.stdout.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue

            # Skip noisy repeated warnings
            if any(p in line for p in _NOISY_PATTERNS):
                continue

            level = "info"
            if "ERROR" in line or "Error" in line:
                level = "error"
            elif "WARNING" in line or "Warning" in line:
                level = "warning"
            elif "完成" in line or "success" in line.lower() or "✓" in line:
                level = "success"

            log_entry = {
                "id": _gen_id(),
                "timestamp": _now(),
                "level": level,
                "message": line[:500],
            }
            task["logs"].append(log_entry)
            if len(task["logs"]) > 2000:
                task["logs"] = task["logs"][-2000:]

            # Broadcast log to WebSocket
            await _broadcast(task_id, {
                "type": "log",
                "taskId": task_id,
                "data": log_entry,
                "timestamp": _now(),
            })

            # Update progress for meaningful lines
            if any(kw in line for kw in ["因子", "回测", "模型", "训练", "完成", "加载",
                                          "[1/4]", "[2/4]", "[3/4]", "[4/4]", "结果"]):
                task["progress"]["message"] = line[:200]

                # Estimate progress from run_backtest step markers
                if "[1/4]" in line:
                    task["progress"]["progress"] = 15
                elif "[2/4]" in line:
                    task["progress"]["progress"] = 35
                elif "[3/4]" in line:
                    task["progress"]["progress"] = 55
                elif "[4/4]" in line:
                    task["progress"]["progress"] = 75
                elif "结果已保存" in line or "回测结果" in line:
                    task["progress"]["progress"] = 95

                task["progress"]["timestamp"] = _now()
                await _broadcast(task_id, {
                    "type": "progress",
                    "taskId": task_id,
                    "data": task["progress"],
                    "timestamp": _now(),
                })

        # --- Process exit ---
        exit_code = await proc.wait()
        task["pid"] = None
        task["status"] = "completed" if exit_code == 0 else "failed"
        task["updatedAt"] = _now()

        # Try to load backtest results from output metrics JSON
        if exit_code == 0:
            task["progress"]["phase"] = "completed"
            task["progress"]["progress"] = 100
            task["progress"]["message"] = "回测完成"
            _load_backtest_results(task)
        else:
            task["progress"]["message"] = f"回测失败 (exit code: {exit_code})"

        await _broadcast(task_id, {
            "type": "result",
            "taskId": task_id,
            "data": {
                "status": task["status"],
                "metrics": task.get("metrics", {}),
            },
            "timestamp": _now(),
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        task["status"] = "failed"
        task["progress"]["message"] = str(e)
        task["updatedAt"] = _now()
        await _broadcast(task_id, {
            "type": "error",
            "taskId": task_id,
            "data": {"error": str(e)},
            "timestamp": _now(),
        })


def _load_backtest_results(task: Dict[str, Any]):
    """Try to load backtest result metrics from the output directory."""
    try:
        config_path = task.get("config", {}).get("configPath") or str(
            PROJECT_ROOT / "configs" / "backtest.yaml"
        )
        with open(config_path, "r") as f:
            bt_config = yaml.safe_load(f)
        output_dir_raw = bt_config.get("experiment", {}).get(
            "output_dir", "data/results/backtest_v2_results"
        )
        # Resolve relative output_dir against PROJECT_ROOT (run_backtest runs with cwd=PROJECT_ROOT)
        output_dir = Path(output_dir_raw)
        if not output_dir.is_absolute():
            output_dir = PROJECT_ROOT / output_dir
        output_dir_str = str(output_dir)

        # Look for most recent metrics JSON
        metrics_files = sorted(
            glob.glob(os.path.join(output_dir_str, "*_backtest_metrics.json")),
            key=os.path.getmtime, reverse=True,
        )
        if metrics_files:
            with open(metrics_files[0], "r") as f:
                metrics_data = json.load(f)
            # The JSON has a nested structure: { metrics: {...}, config: {...}, ... }
            # Flatten: put the inner metrics dict at the top level for the frontend,
            # but also keep meta fields like experiment_name and elapsed_seconds.
            inner_metrics = metrics_data.get("metrics", {})
            flat = {**inner_metrics}
            # Carry over useful metadata
            for key in ("experiment_name", "factor_source", "num_factors",
                        "config", "elapsed_seconds"):
                if key in metrics_data:
                    flat[f"__{key}"] = metrics_data[key]
            
            # Load cumulative excess return data from CSV
            csv_path = metrics_files[0].replace("_backtest_metrics.json", "_cumulative_excess.csv")
            if os.path.exists(csv_path):
                import pandas as pd
                df = pd.read_csv(csv_path)
                if 'date' in df.columns and 'cumulative_excess_return' in df.columns:
                    cumulative_data = df[['date', 'cumulative_excess_return']].to_dict('records')
                    flat["cumulative_curve"] = [
                        {"date": r["date"], "value": r["cumulative_excess_return"]} 
                        for r in cumulative_data
                    ]

            task["metrics"] = flat
    except Exception as e:
        import traceback
        traceback.print_exc()  # print for debugging, but don't crash


# ---- System config endpoints ----

@app.get("/api/v1/system/config", response_model=ApiResponse)
async def get_system_config():
    """Read current system configuration from .env and experiment.yaml."""
    dotenv = _load_dotenv_dict()

    # Read experiment.yaml for display
    exp_yaml_path = PROJECT_ROOT / "configs" / "experiment.yaml"
    exp_yaml_content = ""
    if exp_yaml_path.exists():
        exp_yaml_content = exp_yaml_path.read_text(encoding="utf-8")

    # Mask API keys for security
    masked_env = {}
    for k, v in dotenv.items():
        if "KEY" in k.upper() and v:
            masked_env[k] = v[:8] + "..." + v[-4:] if len(v) > 12 else "***"
        else:
            masked_env[k] = v

    return ApiResponse(
        success=True,
        data={
            "env": masked_env,
            "experimentYaml": exp_yaml_content,
            "factorLibraries": [Path(p).name for p in _find_factor_jsons()],
        },
    )


@app.put("/api/v1/system/config", response_model=ApiResponse)
async def update_system_config(update: SystemConfigUpdate):
    """Update .env configuration (non-secret fields only)."""
    if not DOTENV_PATH.exists():
        raise HTTPException(status_code=404, detail=".env file not found")

    content = DOTENV_PATH.read_text(encoding="utf-8")
    updates = {k: v for k, v in update.model_dump().items() if v is not None}

    import re
    for key, val in updates.items():
        # Replace existing line or append
        pattern = rf"^{re.escape(key)}\s*=.*$"
        replacement = f"{key}={val}"
        new_content, n = re.subn(pattern, replacement, content, flags=re.MULTILINE)
        if n > 0:
            content = new_content
        else:
            content += f"\n{replacement}\n"

    DOTENV_PATH.write_text(content, encoding="utf-8")
    return ApiResponse(success=True, message="配置已更新")


# ========================== Run history / analysis / suggester ==========================


def _qa_log_root() -> Path:
    """Resolve the QA `log/` directory (where mining runs persist artifacts)."""
    env = _load_dotenv_dict()
    val = env.get("LOG_DIR") or os.environ.get("LOG_DIR")
    if val:
        p = Path(val)
        return p if p.is_absolute() else (PROJECT_ROOT / p)
    return PROJECT_ROOT / "log"


def _qa_qlib_root() -> Optional[Path]:
    """Resolve the QA qlib data root (provider_uri)."""
    env = _load_dotenv_dict()
    val = env.get("QLIB_DATA_DIR") or os.environ.get("QLIB_DATA_DIR")
    if not val:
        return None
    p = Path(val)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


def _find_run_id_for_task(task: Dict[str, Any]) -> Optional[str]:
    """Pick the QA log dir that was created during this task's lifetime.

    QA writes `log/<timestamp>/` per run; the task itself doesn't track it,
    so we match by mtime: newest run dir whose mtime ≥ task createdAt.
    """
    log_root = _qa_log_root()
    if not log_root.exists():
        return None
    try:
        created = task.get("createdAt")
        created_ts = datetime.fromisoformat(created).timestamp() if created else 0.0
    except Exception:
        created_ts = 0.0
    best: Optional[Path] = None
    for entry in log_root.iterdir():
        if not entry.is_dir():
            continue
        if not (entry / "trajectory_pool.json").exists() and not (entry / "evolution_state.json").exists():
            continue
        try:
            if entry.stat().st_mtime + 1.0 < created_ts:
                continue
        except Exception:
            continue
        if best is None or entry.stat().st_mtime > best.stat().st_mtime:
            best = entry
    return best.name if best else None


def _resolve_findings_repo_qa() -> Optional[Path]:
    """Locate the QA findings repo (sibling dir or env override).

    Tries (in order):
      1. $QA_FINDINGS_REPO (env / .env)
      2. <repos>/QuantaAlphaFindings  (CamelCase — current convention)
      3. <repos>/quantaalpha-findings (lowercase-hyphen — legacy)
    """
    env = _load_dotenv_dict()
    val = env.get("QA_FINDINGS_REPO") or os.environ.get("QA_FINDINGS_REPO")
    if val:
        p = Path(val)
        if p.exists():
            return p
    parent = PROJECT_ROOT.parent
    for candidate_name in ("QuantaAlphaFindings", "quantaalpha-findings"):
        cand = parent / candidate_name
        if cand.exists():
            return cand
    return None


class QASuggestObjectivesRequest(BaseModel):
    style: Optional[str] = Field("gap-fill", description="gap-fill | adventurous | refinement")
    n: Optional[int] = Field(4, description="Number of suggestions")
    focusHint: Optional[str] = Field(None, description="Free-text focus hint")
    universe: Optional[str] = Field("sp500", description="qlib universe name")


def _read_run_manifest(run_dir: Path) -> Optional[Dict[str, Any]]:
    """Read manifest.json from a log dir if Phase B has written one."""
    p = run_dir / "manifest.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_run_manifest(task: Dict[str, Any], run_id: str) -> None:
    """Stamp `log/<run_id>/manifest.json` so the FE can show explicit linkages.

    Called at task completion when we know all the values: display_name,
    objective, library_suffix, workspace_dir, started_at, completed_at.

    Best-effort; never raises on caller's path.
    """
    try:
        log_dir = _qa_log_root() / run_id
        if not log_dir.exists():
            return

        cfg = task.get("config") or {}
        display_name = (cfg.get("displayName") or "").strip() or None
        objective = (cfg.get("direction") or "").strip() or None
        library_suffix = cfg.get("librarySuffix")
        library_name = (
            f"all_factors_library_{library_suffix}.json"
            if library_suffix
            else "all_factors_library.json"
        )

        # Locate workspace by EXPERIMENT_ID env we set in _run_mining
        workspace_name: Optional[str] = None
        try:
            results_dir = PROJECT_ROOT / "data" / "results"
            if results_dir.exists() and library_suffix:
                # Convention: workspace_<experiment_id>; experiment_id == librarySuffix
                cand = results_dir / f"workspace_{library_suffix}"
                if cand.exists():
                    workspace_name = cand.name
        except Exception:
            workspace_name = None

        manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "display_name": display_name,
            "objective": objective,
            "library_suffix": library_suffix,
            "library_name": library_name,
            "workspace_name": workspace_name,
            "started_at": task.get("createdAt"),
            "completed_at": task.get("updatedAt") or _now(),
            "status": task.get("status"),
            "config": {
                k: cfg.get(k)
                for k in (
                    "numDirections", "maxRounds", "maxLoops",
                    "factorsPerHypothesis", "qualityGateEnabled", "parallelEnabled",
                )
                if cfg.get(k) is not None
            },
        }
        (log_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        # Manifest writing must not break the task completion path
        pass


def _infer_run_linkages(run_summary: Dict[str, Any]) -> Dict[str, Any]:
    """Pick the most likely workspace + library for a run.

    Priority:
      1. manifest.json in the log dir (written by Phase B; not present today).
      2. Mtime window: workspace whose first parquet was written within
         ±3 hours of the run's saved_at / created_at.
    Returns {"linked_workspace": <name|None>, "linked_library": <name|None>}.
    """
    log_dir = Path(run_summary.get("log_dir") or "")
    if log_dir.exists():
        manifest = _read_run_manifest(log_dir)
        if manifest:
            return {
                "linked_workspace": manifest.get("workspace_name"),
                "linked_library": manifest.get("library_name"),
                "linkage_source": "manifest",
                "display_name": manifest.get("display_name"),
                "objective": manifest.get("objective"),
            }

    # Mtime fallback
    empty = {
        "linked_workspace": None,
        "linked_library": None,
        "linkage_source": None,
        "display_name": None,
        "objective": None,
    }
    started_iso = run_summary.get("created_at") or run_summary.get("saved_at")
    if not started_iso:
        return empty
    try:
        started_ts = datetime.fromisoformat(started_iso).timestamp()
    except Exception:
        return empty

    results_dir = PROJECT_ROOT / "data" / "results"
    if not results_dir.exists():
        return empty

    best_ws: Optional[Path] = None
    best_delta = float("inf")
    for entry in results_dir.iterdir():
        if not entry.is_dir() or not entry.name.startswith("workspace_exp_"):
            continue
        parquets = list(entry.glob("*/combined_factors_df.parquet"))
        if not parquets:
            continue
        # Use the earliest parquet write as the workspace's start time
        ws_start = min(p.stat().st_mtime for p in parquets)
        delta = abs(ws_start - started_ts)
        # Allow ±3 hours
        if delta < 3 * 3600 and delta < best_delta:
            best_delta = delta
            best_ws = entry

    if best_ws is None:
        return empty

    linked_lib = _linked_library_for_workspace(best_ws.name)
    return {
        "linked_workspace": best_ws.name,
        "linked_library": linked_lib["name"] if linked_lib else None,
        "linkage_source": "mtime",
        "display_name": None,
        "objective": None,
    }


@app.get("/api/v1/runs/list", response_model=ApiResponse)
async def list_qa_runs():
    """List past QA mining runs from log/. Enriched with workspace/library linkage."""
    try:
        from quantaalpha.data.run_history import list_runs
        runs = list_runs(_qa_log_root())
        for r in runs:
            r.update(_infer_run_linkages(r))
        return ApiResponse(success=True, data={"runs": runs})
    except Exception as e:
        return ApiResponse(success=False, error=f"failed to list runs: {e}")


@app.get("/api/v1/runs/{run_id}", response_model=ApiResponse)
async def get_qa_run(run_id: str):
    """Return one run's full state (summary + pool + cached analysis if any)."""
    try:
        from quantaalpha.data.run_history import load_run, load_cached_analysis
        log_root = _qa_log_root()
        bundle = load_run(log_root, run_id)
        cached = load_cached_analysis(log_root, run_id)
        summary = bundle.get("summary") or {}
        summary.update(_infer_run_linkages(summary))
        return ApiResponse(
            success=True,
            data={
                "summary": summary,
                "pool": bundle.get("pool"),
                "analysis": cached,
            },
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        return ApiResponse(success=False, error=f"failed to load run: {e}")


@app.get("/api/v1/runs/{run_id}/lineage", response_model=ApiResponse)
async def get_qa_lineage(run_id: str):
    """Return parent→child trajectory edges for visualization."""
    try:
        from quantaalpha.data.run_history import load_run
        bundle = load_run(_qa_log_root(), run_id)
        pool = bundle.get("pool") or {}
        trajs = (pool.get("trajectories") or {})

        nodes = []
        edges = []
        for tid, t in trajs.items():
            bm = t.get("backtest_metrics") or {}
            nodes.append({
                "id": tid,
                "phase": t.get("phase"),
                "round": t.get("round_idx"),
                "direction_id": t.get("direction_id"),
                "rank_icir": bm.get("RankICIR"),
                "ir": bm.get("information_ratio"),
                "ic": bm.get("IC"),
                "ann_ret": bm.get("annualized_return"),
                "max_dd": bm.get("max_drawdown"),
                "hypothesis": (t.get("hypothesis") or "")[:200],
            })
            for pid in (t.get("parent_ids") or []):
                if pid in trajs:
                    edges.append({"source": pid, "target": tid})

        return ApiResponse(success=True, data={"nodes": nodes, "edges": edges})
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        return ApiResponse(success=False, error=f"failed to build lineage: {e}")


@app.post("/api/v1/runs/{run_id}/explain", response_model=ApiResponse)
async def explain_qa_run(run_id: str):
    """Run LLM verdict on a completed run; cache to log/<run_id>/analysis.json.

    The LLM call is synchronous and internally spawns its own asyncio loop,
    so we hand it off to a thread to avoid colliding with FastAPI's event loop.
    """
    try:
        from quantaalpha.data.run_history import load_run
        from quantaalpha.pipeline.analysis import analyze_run, save_analysis
        log_root = _qa_log_root()
        bundle = load_run(log_root, run_id)
        summary = bundle.get("summary") or {}
        pool = bundle.get("pool") or {}
        config = summary.get("config") or {}
        initial_direction = (config.get("initial_direction") or "")[:300]

        def _run_analysis():
            analysis = analyze_run(run_id, pool, config, initial_direction=initial_direction)
            save_analysis(log_root, run_id, analysis)
            return analysis

        analysis = await asyncio.to_thread(_run_analysis)
        return ApiResponse(success=True, data={"analysis": analysis.to_dict()})
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        return ApiResponse(success=False, error=f"analysis failed: {e}")


@app.post("/api/v1/suggest-objectives", response_model=ApiResponse)
async def suggest_qa_objectives(req: QASuggestObjectivesRequest):
    """LLM-driven factor-mining direction suggester.

    Style="auto" auto-picks based on run history; the endpoint echoes
    `style_resolved` so the FE can show which one was chosen.

    The LLM call is synchronous and internally spawns its own asyncio loop,
    so we hand it off to a thread to avoid colliding with FastAPI's event loop.
    """
    try:
        from quantaalpha.data.run_history import list_runs
        from quantaalpha.pipeline.objective_suggester import (
            suggest_objectives,
            _auto_pick_style,
        )
        qlib_root = _qa_qlib_root()
        if qlib_root is None:
            return ApiResponse(success=False, error="QLIB_DATA_DIR not configured")
        recent_runs = list_runs(_qa_log_root())

        requested = req.style or "auto"
        style_resolved = _auto_pick_style(recent_runs) if requested == "auto" else requested

        def _run_suggester():
            return suggest_objectives(
                qlib_root,
                universe=req.universe or "sp500",
                recent_runs=recent_runs,
                focus_hint=req.focusHint,
                n_suggestions=req.n or 4,
                style=style_resolved,
            )

        suggestions = await asyncio.to_thread(_run_suggester)
        return ApiResponse(
            success=True,
            data={
                "suggestions": [s.to_dict() for s in suggestions],
                "style_requested": requested,
                "style_resolved": style_resolved,
            },
        )
    except Exception as e:
        return ApiResponse(success=False, error=f"suggest failed: {e}")


@app.get("/api/v1/findings-config", response_model=ApiResponse)
async def get_findings_config():
    """Surface auto-publish state for the QA findings repo."""
    repo = _resolve_findings_repo_qa()
    env = _load_dotenv_dict()
    auto_disabled = (env.get("QA_FINDINGS_AUTO_PUBLISH") or "").lower() in ("0", "false", "no")
    return ApiResponse(
        success=True,
        data={
            "repo_path": str(repo) if repo else None,
            "repo_exists": repo is not None,
            "auto_publish_enabled": (repo is not None) and (not auto_disabled),
        },
    )


def _auto_publish_qa_run(run_id: str) -> None:
    """Fire-and-forget: publish a completed QA run's top factors to findings repo.

    Default-on: runs whenever the findings repo is locatable, unless
    QA_FINDINGS_AUTO_PUBLISH is explicitly set to 0/false/no.
    """
    try:
        env = _load_dotenv_dict()
        if (env.get("QA_FINDINGS_AUTO_PUBLISH") or "").lower() in ("0", "false", "no"):
            return
        repo = _resolve_findings_repo_qa()
        if repo is None:
            return
        publisher = PROJECT_ROOT / "scripts" / "publish_findings.py"
        if not publisher.exists():
            return
        log_root = _qa_log_root()
        run_dir = log_root / run_id
        if not run_dir.exists():
            return
        cmd = [
            sys.executable, str(publisher),
            "--run", str(run_dir),
            "--findings-repo", str(repo),
        ]
        subprocess.Popen(
            cmd, cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        # Non-fatal — auto-publish is best-effort
        pass


# ========================== Universes (Phase D — universe-aware mining) ====


def _instruments_dir() -> Path:
    """Where qlib instruments files live."""
    qlib_root = _qa_qlib_root()
    if qlib_root is None:
        return PROJECT_ROOT / "data" / "qlib" / "us_data" / "instruments"
    return qlib_root / "instruments"


def _universe_summary(name: str, instruments_path: Path) -> Dict[str, Any]:
    """Return ticker count + recent-data freshness for a universe."""
    ticker_count = 0
    try:
        with open(instruments_path, "r", encoding="utf-8") as fh:
            ticker_count = sum(1 for line in fh if line.strip())
    except Exception:
        ticker_count = 0
    # Freshness: pick a representative ticker, read its close.day.bin mtime
    sample_ticker = None
    try:
        with open(instruments_path, "r", encoding="utf-8") as fh:
            first_line = fh.readline().strip()
            if first_line:
                sample_ticker = first_line.split()[0].lower()
    except Exception:
        pass
    last_data_iso: Optional[str] = None
    if sample_ticker:
        try:
            qlib_root = _qa_qlib_root() or (PROJECT_ROOT / "data" / "qlib" / "us_data")
            bin_path = qlib_root / "features" / sample_ticker / "close.day.bin"
            if bin_path.exists():
                last_data_iso = datetime.fromtimestamp(bin_path.stat().st_mtime).isoformat()
        except Exception:
            pass
    return {
        "name": name,
        "ticker_count": ticker_count,
        "instruments_path": str(instruments_path),
        "last_data_mtime": last_data_iso,
        "sample_ticker": sample_ticker,
    }


@app.get("/api/v1/universes", response_model=ApiResponse)
async def list_universes_endpoint():
    """List qlib universes available for mining + their freshness."""
    inst_dir = _instruments_dir()
    if not inst_dir.exists():
        return ApiResponse(success=True, data={"universes": []})
    out = []
    for entry in sorted(inst_dir.iterdir()):
        if entry.is_file() and entry.suffix == ".txt":
            name = entry.stem
            # Skip the 'all' universe — too broad, not useful for mining
            if name == "all":
                continue
            try:
                out.append(_universe_summary(name, entry))
            except Exception:
                continue
    return ApiResponse(success=True, data={"universes": out})


class DetectUniverseRequest(BaseModel):
    text: str = Field(..., description="User's objective text — to map to a universe")


_UNIVERSE_DETECT_SYSTEM = """\
You map a user's factor-mining objective to ONE qlib universe from a fixed list.

Available universes:
  - sp500       (S&P 500 large-cap US equities, 547 fresh tickers)
  - nasdaq100   (NASDAQ-100 tech-heavy US equities, 164 fresh tickers)
  - commodities (Gold/silver/oil/gas/broad-commodity ETFs: GLD, IAU, GDX, GDXJ,
                 SLV, SIVR, PPLT, USO, UNG, DBC, DBA, GSG, PDBC)

Rules:
  - If the objective mentions gold, silver, oil, gas, commodities, miners → commodities
  - If it mentions NASDAQ, tech-heavy, FAANG, mega-cap tech → nasdaq100
  - If unclear, default to sp500
  - Output STRICT JSON: {"universe": "sp500|nasdaq100|commodities", "reason": "<one sentence>"}
"""


@app.post("/api/v1/detect-universe", response_model=ApiResponse)
async def detect_universe(req: DetectUniverseRequest):
    """LLM-based universe detection from objective text. Best-effort; default sp500.

    Used by FE to suggest a universe as the user types — they can override.
    """
    if not (req.text or "").strip():
        return ApiResponse(success=True, data={"universe": "sp500", "reason": "(empty input — defaulted)"})

    def _do() -> Dict[str, Any]:
        try:
            from quantaalpha.llm.client import APIBackend
            raw = APIBackend().build_messages_and_create_chat_completion(
                user_prompt=f"Objective:\n{req.text.strip()[:500]}\n\nReturn the JSON now.",
                system_prompt=_UNIVERSE_DETECT_SYSTEM,
                json_mode=True,
            )
            try:
                data = json.loads(raw)
            except Exception:
                import re
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                data = json.loads(m.group(0)) if m else {}
            picked = (data.get("universe") or "").strip().lower()
            if picked not in ("sp500", "nasdaq100", "commodities"):
                picked = "sp500"
            return {
                "universe": picked,
                "reason": str(data.get("reason") or "")[:300],
            }
        except Exception as e:
            return {"universe": "sp500", "reason": f"(detect failed: {e}; defaulted)"}

    result = await asyncio.to_thread(_do)
    return ApiResponse(success=True, data=result)


# ========================== Production Models (Phase 5/6 bundles) ==========================


def _production_models_dir() -> Path:
    """Where extract_production_model.py writes bundles."""
    return PROJECT_ROOT / "data" / "results" / "production_models"


def _workspaces_dir() -> Path:
    """Where mining runs write per-iteration workspaces (the source for bundles)."""
    return PROJECT_ROOT / "data" / "results"


def _bundle_summary(bundle_dir: Path) -> Dict[str, Any]:
    """Read metadata.json + factor_expressions.yaml + flag whether model.lgbm exists."""
    meta_path = bundle_dir / "metadata.json"
    factors_path = bundle_dir / "factor_expressions.yaml"
    has_model = (bundle_dir / "model.lgbm").exists()
    metadata: Dict[str, Any] = {}
    if meta_path.exists():
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            metadata = {}
    factor_count = 0
    if factors_path.exists():
        try:
            data = yaml.safe_load(factors_path.read_text(encoding="utf-8")) or {}
            factor_count = len(data.get("factors") or [])
        except Exception:
            factor_count = 0
    return {
        "name": bundle_dir.name,
        "path": str(bundle_dir),
        "has_model": has_model,
        "factor_count": factor_count,
        "saved_at": metadata.get("saved_at"),
        "market": metadata.get("market"),
        "benchmark": metadata.get("benchmark"),
        "model_class": metadata.get("model_class"),
        "model_kwargs": metadata.get("model_kwargs"),
        "train_segments": metadata.get("train_segments"),
        "test_ic": metadata.get("test_ic"),
        "test_rank_ic": metadata.get("test_rank_ic"),
        "num_factors_in_metadata": metadata.get("num_factors_in_metadata"),
    }


def _workspace_suffix(ws_name: str) -> Optional[str]:
    """Extract the suffix from a workspace name.

    `workspace_exp_20260507_171646` → `exp_20260507_171646`
    Used to match workspaces to their `all_factors_library_<suffix>.json`.
    """
    prefix = "workspace_"
    if ws_name.startswith(prefix) and len(ws_name) > len(prefix):
        return ws_name[len(prefix):]
    return None


def _linked_library_for_workspace(ws_name: str) -> Optional[Dict[str, Any]]:
    """Find the all_factors_library_<suffix>.json that matches a workspace name."""
    suffix = _workspace_suffix(ws_name)
    if not suffix:
        return None
    lib_path = PROJECT_ROOT / "data" / "factorlib" / f"all_factors_library_{suffix}.json"
    if not lib_path.exists():
        return None
    try:
        mtime = datetime.fromtimestamp(lib_path.stat().st_mtime).isoformat()
    except Exception:
        mtime = None
    factor_count = 0
    try:
        with open(lib_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        factor_count = len(data.get("factors") or {})
    except Exception:
        pass
    return {
        "name": lib_path.name,
        "path": str(lib_path),
        "mtime": mtime,
        "factor_count": factor_count,
    }


def _workspace_summary(ws_dir: Path) -> Optional[Dict[str, Any]]:
    """Find combined_factors_df.parquet in a workspace; report what's there.

    Also includes the linked factor library JSON (suffix match) when found.
    """
    parquets = sorted(
        ws_dir.glob("*/combined_factors_df.parquet"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not parquets:
        return None
    latest = parquets[0]
    try:
        mtime = datetime.fromtimestamp(latest.stat().st_mtime).isoformat()
    except Exception:
        mtime = None
    return {
        "name": ws_dir.name,
        "path": str(ws_dir),
        "parquet_path": str(latest),
        "parquet_mtime": mtime,
        "parquet_count": len(parquets),
        "linked_library": _linked_library_for_workspace(ws_dir.name),
    }


class BuildBundleRequest(BaseModel):
    workspace: Optional[str] = Field(None, description="Workspace name under data/results/. Required unless baseline=true.")
    baseline: Optional[bool] = Field(False, description="Train on baseline 20 features only (smoke test).")
    outputName: Optional[str] = Field(None, description="Bundle directory name. Defaults to a timestamp.")


@app.get("/api/v1/bundles/list", response_model=ApiResponse)
async def list_bundles():
    """List all production model bundles on disk."""
    root = _production_models_dir()
    if not root.exists():
        return ApiResponse(success=True, data={"bundles": []})
    bundles = []
    for entry in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not entry.is_dir():
            continue
        # Skip the build log files we wrote ourselves
        if entry.name.startswith("_"):
            continue
        try:
            bundles.append(_bundle_summary(entry))
        except Exception:
            continue
    return ApiResponse(success=True, data={"bundles": bundles, "root": str(root)})


@app.get("/api/v1/bundles/{name}", response_model=ApiResponse)
async def get_bundle(name: str):
    """Return one bundle's full metadata + factor expressions."""
    root = _production_models_dir()
    bundle_dir = root / name
    if not bundle_dir.exists() or not bundle_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"bundle not found: {name}")
    summary = _bundle_summary(bundle_dir)
    factors_path = bundle_dir / "factor_expressions.yaml"
    factors: List[Dict[str, Any]] = []
    if factors_path.exists():
        try:
            data = yaml.safe_load(factors_path.read_text(encoding="utf-8")) or {}
            factors = data.get("factors") or []
        except Exception:
            factors = []
    return ApiResponse(success=True, data={"bundle": summary, "factors": factors})


@app.get("/api/v1/bundles/workspaces/list", response_model=ApiResponse)
async def list_buildable_workspaces():
    """List workspaces with a combined_factors_df.parquet (i.e. ready to extract from)."""
    root = _workspaces_dir()
    if not root.exists():
        return ApiResponse(success=True, data={"workspaces": []})
    out = []
    for entry in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not entry.is_dir() or not entry.name.startswith("workspace_exp_"):
            continue
        s = _workspace_summary(entry)
        if s is not None:
            out.append(s)
    return ApiResponse(success=True, data={"workspaces": out})


@app.post("/api/v1/bundles/build", response_model=ApiResponse)
async def build_bundle(req: BuildBundleRequest):
    """Kick off extract_production_model.py as a background subprocess.

    Mirrors the CLI's three flags: --workspace, --baseline, --output-name.
    Returns immediately with a build_task_id; status is polled via the
    bundles list (the new bundle dir will appear once the script writes it).
    """
    script = PROJECT_ROOT / "extract_production_model.py"
    if not script.exists():
        return ApiResponse(success=False, error=f"extract_production_model.py not found at {script}")

    cmd = [sys.executable, str(script)]
    if req.baseline:
        cmd.append("--baseline")
    elif req.workspace:
        ws_path = (PROJECT_ROOT / "data" / "results" / req.workspace) if not Path(req.workspace).is_absolute() else Path(req.workspace)
        if not ws_path.exists():
            return ApiResponse(success=False, error=f"workspace not found: {ws_path}")
        cmd.extend(["--workspace", str(ws_path)])
    else:
        return ApiResponse(success=False, error="Either workspace or baseline=true must be provided")

    if req.outputName:
        # Sanitize: only allow safe characters in bundle directory names
        safe = "".join(c for c in req.outputName if c.isalnum() or c in ("_", "-"))
        if not safe:
            return ApiResponse(success=False, error="outputName must contain alphanumerics / _ / -")
        cmd.extend(["--output-name", safe])
        out_name_resolved = safe
    else:
        out_name_resolved = f"spy_production_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    log_path = PROJECT_ROOT / "data" / "results" / "production_models" / f"_build_log_{out_name_resolved}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    task_id = _gen_id()
    try:
        log_fh = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd, cwd=str(PROJECT_ROOT),
            stdout=log_fh, stderr=subprocess.STDOUT,
        )
    except Exception as e:
        return ApiResponse(success=False, error=f"failed to launch builder: {e}")

    tasks[task_id] = {
        "type": "build_bundle",
        "pid": proc.pid,
        "cmd": cmd,
        "logPath": str(log_path),
        "outputName": out_name_resolved,
        "status": "running",
        "createdAt": _now(),
    }
    return ApiResponse(
        success=True,
        data={
            "buildTaskId": task_id,
            "outputName": out_name_resolved,
            "logPath": str(log_path),
        },
    )


@app.get("/api/v1/bundles/build/{task_id}/log", response_model=ApiResponse)
async def get_build_log(task_id: str, tail: int = 200):
    """Return the tail of a build subprocess' log."""
    task = tasks.get(task_id)
    if not task or task.get("type") != "build_bundle":
        raise HTTPException(status_code=404, detail="build task not found")
    log_path = Path(task.get("logPath", ""))
    if not log_path.exists():
        return ApiResponse(success=True, data={"task": task, "log": []})
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        return ApiResponse(success=False, error=f"failed to read log: {e}")
    # Update status if process has exited
    pid = task.get("pid")
    if pid and task.get("status") == "running":
        # Best-effort: if we can detect the process is gone, mark complete
        try:
            import psutil  # may not be installed; harmless if not
            if not psutil.pid_exists(pid):
                bundle_dir = _production_models_dir() / task["outputName"]
                task["status"] = "completed" if (bundle_dir / "model.lgbm").exists() else "failed"
                task["updatedAt"] = _now()
        except Exception:
            pass
    return ApiResponse(success=True, data={"task": task, "log": lines[-tail:]})


# ---- WebSocket endpoint ----

@app.websocket("/ws/mining/{task_id}")
async def ws_mining(websocket: WebSocket, task_id: str):
    """WebSocket for real-time experiment updates."""
    await websocket.accept()

    if task_id not in ws_connections:
        ws_connections[task_id] = []
    ws_connections[task_id].append(websocket)

    # Send current state immediately
    if task_id in tasks:
        try:
            await websocket.send_json({
                "type": "progress",
                "taskId": task_id,
                "data": tasks[task_id].get("progress", {}),
                "timestamp": _now(),
            })
            # Send recent logs
            for log in tasks[task_id].get("logs", [])[-20:]:
                await websocket.send_json({
                    "type": "log",
                    "taskId": task_id,
                    "data": log,
                    "timestamp": _now(),
                })
        except Exception:
            pass

    try:
        while True:
            data = await websocket.receive_text()
            # Heartbeat
            if data == "ping":
                await websocket.send_json({
                    "type": "heartbeat",
                    "timestamp": _now(),
                })
    except WebSocketDisconnect:
        if task_id in ws_connections:
            try:
                ws_connections[task_id].remove(websocket)
            except ValueError:
                pass


# ========================== Entry Point ==========================

def _update_mining_metrics(task: Dict[str, Any]):
    """
    Update mining task metrics from the generated factor library.
    Calculates best factor stats and extracts top 10 factors.
    """
    jsons = _find_factor_jsons()
    # Prefer library with matching suffix if configured
    target_lib = None
    config = task.get("config", {})
    suffix = config.get("librarySuffix")
    
    if suffix:
        candidate = PROJECT_ROOT / "data" / "factorlib" / f"all_factors_library_{suffix}.json"
        # Fix: If suffix is specified, we ONLY look at this file.
        # If it doesn't exist yet, it means no factors have been mined yet for this task.
        if candidate.exists():
            target_lib = str(candidate)
        else:
            # Task specific file not found -> assume empty state
            return
            
    elif jsons:
        # No suffix provided, fallback to latest existing library (legacy behavior)
        target_lib = jsons[0]
        
    if not target_lib:
        return

    # Check modification time
    try:
        mtime = os.path.getmtime(target_lib)
        created_at_str = task.get("createdAt")
        if created_at_str:
            created_at_dt = datetime.fromisoformat(created_at_str)
            # Add a small buffer (e.g. 1 second) to avoid race conditions where file is created immediately
            if mtime < created_at_dt.timestamp():
                # File is older than the task -> ignore it
                return
    except Exception:
        pass

    try:
        lib = _load_factor_library(target_lib)
        factors = lib.get("factors", {})
        
        # 1. Update basic stats
        total = len(factors)
        task["metrics"]["totalFactors"] = total
        
        high = medium = low = 0
        factor_list = []
        
        for f_id, f_info in factors.items():
            # Check if this factor was created after task start
            # If we are using a shared library file (unlikely with new logic, but possible if user forces it),
            # we must ensure we don't display old factors.
            try:
                added_at_str = f_info.get("added_at", "")
                created_at_str = task.get("createdAt", "")
                if added_at_str and created_at_str:
                    # Parse timestamps
                    # added_at usually in isoformat
                    added_at_dt = datetime.fromisoformat(added_at_str)
                    created_at_dt = datetime.fromisoformat(created_at_str)
                    if added_at_dt < created_at_dt:
                        continue
            except Exception:
                pass # If date parsing fails, be permissive or conservative? Permissive for now.

            bt = f_info.get("backtest_results", {})
            q = _classify_quality(bt)
            if q == "high": high += 1
            elif q == "medium": medium += 1
            else: low += 1
            
            # Prepare for top 10 list
            # Normalize metrics
            ic = bt.get("IC", bt.get("1day.excess_return_without_cost.information_coefficient", 0))
            icir = bt.get("ICIR", bt.get("1day.excess_return_without_cost.information_coefficient_ir", 0))
            rank_ic = bt.get("Rank IC", bt.get("rank_ic", bt.get("1day.excess_return_without_cost.rank_ic", 0)))
            rank_icir = bt.get("Rank ICIR", bt.get("rank_ic_ir", bt.get("1day.excess_return_without_cost.rank_ic_ir", 0)))
            
            # Generate a mock equity curve for preview if real data is missing
            # In production, this should come from actual backtest result files (CSV/H5)
            # Here we generate a simple random walk with drift matching the annual return to show visual difference
            cumulative_curve = []
            annual_ret = bt.get("1day.excess_return_without_cost.annualized_return", 0)
            max_dd = bt.get("1day.excess_return_with_cost.max_drawdown", 
                                    bt.get("1day.excess_return_without_cost.max_drawdown", 0))
            
            # Calmar Ratio = Annual Return / Max Drawdown (absolute value)
            # Avoid division by zero
            cr = 0
            if max_dd < 0:
                cr = annual_ret / abs(max_dd)
            elif max_dd > 0:
                cr = annual_ret / max_dd
            
            # Simple simulation: 20 data points for preview sparkline
            import random
            current_val = 1.0
            # Daily drift approx
            drift = (1 + annual_ret) ** (1/252) - 1 if annual_ret else 0
            vol = 0.02 # Assumed daily vol
            
            # Use factor name hash to seed random for consistency
            random.seed(hash(f_info.get("factor_name", f_id)))
            
            for i in range(20):
                 # Generate last 20 points
                 ret = random.gauss(drift, vol)
                 current_val *= (1 + ret)
                 cumulative_curve.append({"value": current_val, "date": f"Day {i+1}"})
            
            factor_list.append({
                "factorName": f_info.get("factor_name", f_id),
                "factorExpression": f_info.get("factor_expression", ""),
                "rankIc": rank_ic,
                "rankIcir": rank_icir,
                "ic": ic,
                "icir": icir,
                "annualReturn": annual_ret,
                "sharpeRatio": bt.get("1day.excess_return_with_cost.information_ratio", 
                                    bt.get("1day.excess_return_without_cost.information_ratio", 0)),
                "maxDrawdown": max_dd,
                "calmarRatio": cr,
                "cumulativeCurve": cumulative_curve
            })

        task["metrics"]["highQualityFactors"] = high
        task["metrics"]["mediumQualityFactors"] = medium
        task["metrics"]["lowQualityFactors"] = low
        
        # 2. Find best factor
        if factor_list:
            # Sort by RankIC desc
            factor_list.sort(key=lambda x: x["rankIc"], reverse=True)
            best = factor_list[0]
            
            # Update task metrics with best factor's stats
            task["metrics"]["annualReturn"] = best["annualReturn"]
            task["metrics"]["rankIc"] = best["rankIc"]
            task["metrics"]["sharpeRatio"] = best["sharpeRatio"]
            task["metrics"]["maxDrawdown"] = best["maxDrawdown"]
            task["metrics"]["factorName"] = best["factorName"]
            
            # 3. Top 10 Factors
            task["metrics"]["top10Factors"] = factor_list[:10]
            
    except Exception:
        pass # Best effort

if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("BACKEND_HOST", "0.0.0.0")
    port = int(os.environ.get("BACKEND_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="info")
