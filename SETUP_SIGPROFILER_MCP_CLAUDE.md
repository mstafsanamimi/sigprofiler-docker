# SigProfilerExtractor + Docker MCP + Claude Desktop: End-to-End Setup

This guide starts from cloning `SigProfilerExtractor` and ends with calling `run_sigprofiler` from Claude Desktop.

## 1) Prerequisites

- macOS with Docker Desktop installed and running
- Claude Desktop installed
- Git installed
- At least 8 GB RAM available to Docker for non-trivial SigProfiler runs

## 2) Clone SigProfilerExtractor

```bash
mkdir -p ~/projects/sigprofiler-docker
cd ~/projects/sigprofiler-docker
git clone https://github.com/SigProfilerSuite/SigProfilerExtractor.git
```

Expected project path after clone:

`~/projects/sigprofiler-docker/SigProfilerExtractor`

## 3) Create MCP server folder

Create a sibling folder:

```bash
cd ~/projects/sigprofiler-docker
mkdir -p sigprofiler_mcp
cd sigprofiler_mcp
```

Create `requirements.txt`:

```txt
mcp>=1.0.0
```

Create `Dockerfile`:

```dockerfile
FROM sigprofiler-cpu
WORKDIR /srv
COPY requirements.txt server.py ./
RUN pip install --no-cache-dir -r requirements.txt
ENTRYPOINT ["python", "/srv/server.py"]
```

Create `catalog-entry.yaml`:

```yaml
registry:
  sigprofiler:
    description: "Run SigProfilerExtractor with configurable arguments"
    title: "SigProfiler MCP"
    type: server
    dateAdded: "2026-03-09T00:00:00Z"
    image: sigprofiler-mcp:latest
    ref: ""
    readme: ""
    toolsUrl: ""
    source: ""
    upstream: ""
    icon: ""
    tools:
      - name: run_sigprofiler
    volumes:
      - '{{sigprofiler.project_dir|volume|into}}'
    config:
      - name: sigprofiler
        description: Configure paths for the SigProfiler MCP server
        type: object
        properties:
          project_dir:
            type: string
            description: Absolute host path to mount into the SigProfiler MCP container
        required:
          - project_dir
```

Create `server.py`:

```python
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
```

## 4) Build base SigProfiler CPU image

From the cloned repo:

```bash
cd ~/projects/sigprofiler-docker/SigProfilerExtractor
docker build -f Dockerfile.cpu -t sigprofiler-cpu .
```

## 5) Build MCP image and register it in Docker MCP toolkit

```bash
cd ~/projects/sigprofiler-docker/sigprofiler_mcp
docker build --no-cache -t sigprofiler-mcp:latest .
docker mcp catalog init
docker mcp catalog create custom
docker mcp catalog add custom sigprofiler ./catalog-entry.yaml --force
docker mcp server enable sigprofiler
docker mcp server ls
docker mcp tools ls
```

## 6) Configure project mount for MCP

Edit `~/.docker/mcp/config.yaml`:

```yaml
sigprofiler:
  project_dir: /Users/<your-username>/projects/sigprofiler-docker/SigProfilerExtractor
```

Re-apply server enable after config update:

```bash
docker mcp server disable sigprofiler
docker mcp server enable sigprofiler
```

## 7) Connect Docker MCP toolkit to Claude Desktop

```bash
docker mcp client connect claude-desktop --global
```

Edit Claude config at:

`~/Library/Application Support/Claude/claude_desktop_config.json`

Use:

```json
{
  "mcpServers": {
    "MCP_DOCKER": {
      "command": "docker",
      "args": ["mcp", "gateway", "run", "--memory", "8Gb"]
    }
  }
}
```

Quit and reopen Claude Desktop.

## 8) Add or switch reference genome

For runs, set `reference_genome` in tool args (e.g., `GRCh37`, `GRCh38`).

If a genome must be installed first in the runtime image:

```bash
docker run --rm -it sigprofiler-cpu python -c "from SigProfilerMatrixGenerator import install as genInstall; genInstall.install('GRCh38')"
```

Then rebuild `sigprofiler-mcp` (it is based on `sigprofiler-cpu`):

```bash
cd ~/projects/sigprofiler-docker/sigprofiler_mcp
docker build --no-cache -t sigprofiler-mcp:latest .
docker mcp catalog add custom sigprofiler ./catalog-entry.yaml --force
docker mcp server disable sigprofiler
docker mcp server enable sigprofiler
```

## 9) Verify with CLI first

Use CLI to confirm tool behavior before Claude UI:

```bash
docker mcp tools --gateway-arg=--memory=8Gb call run_sigprofiler \
project_dir=/Users/<your-username>/projects/sigprofiler-docker/SigProfilerExtractor \
input_path=matrix \
output_dir=results_mcp_run1 \
input_type=matrix \
reference_genome=GRCh37 \
minimum_signatures=1 \
maximum_signatures=5 \
nmf_replicates=10 \
cpu=1
```

Expected success JSON includes:

- `exit_code: 0`
- `output_dir: results_mcp_run1`
- `log_path: .../mcp_logs/run_results_mcp_run1.log`

## 10) Run from Claude Desktop

Paste this in Claude:

`Call run_sigprofiler with project_dir=/Users/<your-username>/projects/sigprofiler-docker/SigProfilerExtractor, input_path=matrix, output_dir=results_mcp_run2, input_type=matrix, reference_genome=GRCh37, minimum_signatures=1, maximum_signatures=5, nmf_replicates=10, cpu=1.`

## 11) Output locations

- Results folder:  
  `/Users/<your-username>/projects/sigprofiler-docker/SigProfilerExtractor/results_mcp_run*`
- MCP run log:  
  `/Users/<your-username>/projects/sigprofiler-docker/SigProfilerExtractor/mcp_logs/run_<output_dir>.log`

## 12) Troubleshooting

1. `invalid character '*'` or `invalid character 'p'`  
Cause: stdout/stderr corruption of MCP protocol.  
Fix: use the `server.py` from this guide and rebuild image.

2. `exit code -9`  
Cause: out-of-memory kill.  
Fix: run gateway with more memory (`--memory 8Gb` or higher), reduce `maximum_signatures` and `nmf_replicates`.

3. `project_dir does not exist`  
Cause: mount/config mismatch.  
Fix: verify `~/.docker/mcp/config.yaml` `project_dir`, then disable/enable server.

4. Tool exists in `docker mcp tools ls` but not in Claude  
Fix: `docker mcp client connect claude-desktop --global`, confirm Claude config has `MCP_DOCKER`, then restart Claude Desktop.
