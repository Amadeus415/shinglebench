"""Per-episode workspace (filesystem) and shell.

Isolation is enforced outside the prompt:
- docker: `--network none`, memory/cpu/pid caps, only the workspace mounted.
- local (dev fallback): on macOS commands run under `sandbox-exec` with network denied and
  writes restricted to the workspace and temp dirs. Elsewhere local mode has no network
  isolation and the run is labeled `isolation: none` in its manifest.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

MAX_OUTPUT = 12_000
MAX_FILE_BYTES = 2_000_000


class WorkspaceError(Exception):
    pass


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, rel: str) -> Path:
        p = (self.root / rel.lstrip("/")).resolve()
        if p != self.root and self.root not in p.parents:
            raise WorkspaceError(f"path escapes workspace: {rel}")
        return p

    def write(self, rel: str, content: str | bytes) -> Path:
        data = content.encode() if isinstance(content, str) else content
        if len(data) > MAX_FILE_BYTES:
            raise WorkspaceError(f"file too large ({len(data)} bytes > {MAX_FILE_BYTES})")
        p = self.resolve(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def read(self, rel: str, max_chars: int = 40_000) -> str:
        p = self.resolve(rel)
        if not p.is_file():
            raise WorkspaceError(f"no such file: {rel}")
        text = p.read_text(errors="replace")
        return text if len(text) <= max_chars else text[:max_chars] + f"\n…[truncated, {len(text)} chars total]"

    def exists(self, rel: str) -> bool:
        return self.resolve(rel).exists()

    def list(self, rel: str = ".", max_entries: int = 400) -> list[str]:
        base = self.resolve(rel)
        if not base.exists():
            raise WorkspaceError(f"no such directory: {rel}")
        out = []
        for p in sorted(base.rglob("*")):
            if any(part.startswith(".") or part == "node_modules" for part in p.relative_to(self.root).parts):
                continue
            if p.is_file():
                out.append(str(p.relative_to(self.root)))
            if len(out) >= max_entries:
                out.append("…")
                break
        return out


@dataclass
class ShellResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    def render(self) -> str:
        def clip(s: str) -> str:
            return s if len(s) <= MAX_OUTPUT else s[:MAX_OUTPUT] + f"\n…[truncated {len(s) - MAX_OUTPUT} chars]"

        head = "TIMED OUT\n" if self.timed_out else ""
        return f"{head}exit_code: {self.exit_code}\n--- stdout ---\n{clip(self.stdout)}\n--- stderr ---\n{clip(self.stderr)}"


class Shell:
    isolation = "none"

    def run(self, command: str, timeout: int = 60) -> ShellResult:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:
        pass


def _seatbelt_profile(ws: Path) -> str:
    tmp = os.path.realpath("/private/tmp")
    var = os.path.realpath(os.environ.get("TMPDIR", "/private/var/folders"))
    return (
        "(version 1)(allow default)(deny network*)"
        "(allow network* (local unix-socket))"
        "(deny file-write*)"
        f'(allow file-write* (subpath "{ws}") (subpath "{tmp}") (subpath "{var}") (literal "/dev/null") (literal "/dev/tty"))'
    )


class LocalShell(Shell):
    """Subprocess shell in the workspace with a scrubbed environment."""

    def __init__(self, ws: Workspace):
        self.ws = ws
        self.seatbelt = sys.platform == "darwin" and shutil.which("sandbox-exec") is not None
        self.isolation = "macos-seatbelt(no-network, writes=workspace)" if self.seatbelt else "none"

    def run(self, command: str, timeout: int = 60) -> ShellResult:
        env = {
            "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin",
            "HOME": str(self.ws.root),
            "LANG": "C.UTF-8",
            "TMPDIR": "/private/tmp" if sys.platform == "darwin" else "/tmp",
        }
        argv = ["/bin/sh", "-c", command]
        if self.seatbelt:
            argv = ["sandbox-exec", "-p", _seatbelt_profile(self.ws.root), *argv]
        try:
            p = subprocess.run(argv, cwd=self.ws.root, env=env, capture_output=True, text=True, timeout=timeout)
            return ShellResult(p.returncode, p.stdout, p.stderr)
        except subprocess.TimeoutExpired as e:
            return ShellResult(124, (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or ""), "", True)


class DockerShell(Shell):
    """One long-lived container per episode; commands run via `docker exec`."""

    def __init__(self, ws: Workspace, image: str):
        self.ws = ws
        self.name = f"shingle-sbx-{uuid.uuid4().hex[:10]}"
        self.isolation = "docker(--network none, 1 cpu, 1g mem)"
        mount = str(ws.root)
        inner, host = os.environ.get("SHINGLE_DATA_DIR"), os.environ.get("SHINGLE_HOST_DATA_DIR")
        if inner and host and mount.startswith(str(Path(inner).resolve())):
            mount = host.rstrip("/") + mount[len(str(Path(inner).resolve())):]  # sibling container needs the host path
        subprocess.run(
            [
                "docker", "run", "-d", "--rm", "--name", self.name,
                "--network", "none", "--cpus", "1", "--memory", "1g", "--pids-limit", "256",
                "--security-opt", "no-new-privileges",
                "-v", f"{mount}:/workspace", "-w", "/workspace", image, "sleep", "infinity",
            ],
            check=True, capture_output=True, text=True, timeout=120,
        )

    def run(self, command: str, timeout: int = 60) -> ShellResult:
        try:
            p = subprocess.run(
                ["docker", "exec", self.name, "timeout", str(timeout), "/bin/sh", "-c", command],
                capture_output=True, text=True, timeout=timeout + 10,
            )
            return ShellResult(p.returncode, p.stdout, p.stderr, p.returncode == 124)
        except subprocess.TimeoutExpired:
            return ShellResult(124, "", "", True)

    def close(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True, timeout=60)


def docker_available(image: str) -> bool:
    if not shutil.which("docker"):
        return False
    try:
        info = subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=15)
        return info.returncode == 0
    except Exception:
        return False


def make_shell(ws: Workspace, backend: str, image: str) -> Shell:
    if backend == "docker" or (backend == "auto" and docker_available(image)):
        try:
            sh = DockerShell(ws, image)
            ws.write(".sandbox_probe", "ok")
            if sh.run("cat .sandbox_probe").stdout.strip() == "ok":
                return sh
            sh.close()
        except Exception:
            if backend == "docker":
                raise
    return LocalShell(ws)
