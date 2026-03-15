#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("sigprofiler-docker")


def _validate_project_dir(project_dir: str) -> Path:
    path = Path(project_dir).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise ValueError(f"project_dir does not exist or is not a directory: {path}")
    return path


def _validate_ranges(
    minimum_signatures: int, maximum_signatures: int, nmf_replicates: int, cpu: int
) -> None:
    if minimum_signatures < 1:
        raise ValueError("minimum_signatures must be >= 1")
    if maximum_signatures < minimum_signatures:
        raise ValueError("maximum_signatures must be >= minimum_signatures")
    if nmf_replicates < 1:
        raise ValueError("nmf_replicates must be >= 1")
    if cpu < 1:
        raise ValueError("cpu must be >= 1")


def _run_sigprofiler_subprocess(
    project_path: Path,
    input_path: str,
    output_dir: str,
    input_type: str,
    reference_genome: str,
    minimum_signatures: int,
    maximum_signatures: int,
    nmf_replicates: int,
    cpu: int,
) -> tuple[int, str, str]:
    runner = r"""
import json
import os
from pathlib import Path

params = json.loads(os.environ["SIGPROFILER_MCP_ARGS"])
from SigProfilerExtractor import sigpro as sig

aliases = {
    "matobj", "text", "table", "matrix", "matrix_DBS", "matrix_ID",
    "matrix_CNV", "csv", "seg:BATTENBERG", "matrix_SV", "vcf",
}

project_path = Path(params["project_dir"]).resolve()
os.chdir(project_path)

input_path = params["input_path"]
if input_path in aliases:
    data = sig.importdata(input_path)
else:
    p = Path(input_path).expanduser()
    p = p if p.is_absolute() else (project_path / p)
    p = p.resolve()
    if not p.exists():
        raise ValueError(f"input_path not found: {p}")
    data = str(p)

sig.sigProfilerExtractor(
    params["input_type"],
    params["output_dir"],
    data,
    reference_genome=params["reference_genome"],
    minimum_signatures=params["minimum_signatures"],
    maximum_signatures=params["maximum_signatures"],
    nmf_replicates=params["nmf_replicates"],
    cpu=params["cpu"],
)
"""
    payload = {
        "project_dir": str(project_path),
        "input_path": input_path,
        "output_dir": output_dir,
        "input_type": input_type,
        "reference_genome": reference_genome,
        "minimum_signatures": minimum_signatures,
        "maximum_signatures": maximum_signatures,
        "nmf_replicates": nmf_replicates,
        "cpu": cpu,
    }
    env = os.environ.copy()
    env["SIGPROFILER_MCP_ARGS"] = json.dumps(payload)
    proc = subprocess.run(
        ["python", "-c", runner],
        cwd=str(project_path),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


@mcp.tool()
def run_sigprofiler(
    project_dir: str,
    input_path: str = "matrix",
    output_dir: str = "results",
    input_type: str = "matrix",
    reference_genome: str = "GRCh37",
    minimum_signatures: int = 1,
    maximum_signatures: int = 5,
    nmf_replicates: int = 10,
    cpu: int = 1,
    docker_image: str = "sigprofiler-cpu",
) -> dict[str, str | int]:
    project_path = _validate_project_dir(project_dir)
    _validate_ranges(minimum_signatures, maximum_signatures, nmf_replicates, cpu)

    log_dir = project_path / "mcp_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = str(log_dir / f"run_{output_dir}.log")

    rc, out, err = _run_sigprofiler_subprocess(
        project_path=project_path,
        input_path=input_path,
        output_dir=output_dir,
        input_type=input_type,
        reference_genome=reference_genome,
        minimum_signatures=minimum_signatures,
        maximum_signatures=maximum_signatures,
        nmf_replicates=nmf_replicates,
        cpu=cpu,
    )

    with open(log_path, "w", encoding="utf-8") as log_file:
        if out:
            log_file.write(out)
        if err:
            log_file.write("\n[stderr]\n")
            log_file.write(err)

    if rc != 0:
        error_tail = (err or out or "")[-1200:]
        raise RuntimeError(
            "SigProfiler failed with exit code "
            f"{rc}. Check log_path: {log_path}. Tail:\n{error_tail}"
        )

    return {
        "exit_code": 0,
        "project_dir": str(project_path),
        "output_dir": output_dir,
        "log_path": log_path,
        "note": "docker_image argument is ignored in this MCP mode.",
    }


if __name__ == "__main__":
    mcp.run()
