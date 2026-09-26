"""The bench's own fleet of host processes: two workers, the telemetry ingester and the
simulators, all pointed at the bench infra (docker-compose.bench.yml). It can kill and
restart a worker and sample every process's resident memory."""

import os
import subprocess
import sys
from pathlib import Path

import psutil

WORKER_IDS = ("bench-worker-a", "bench-worker-b")


class BenchProcess:
    def __init__(self, role: str, module: str, env: dict[str, str], log_dir: Path) -> None:
        self.role = role
        self._module = module
        self._env = env
        self._log_path = log_dir / f"{role}.log"
        self._popen: subprocess.Popen | None = None

    def start(self) -> None:
        log = self._log_path.open("ab")
        self._popen = subprocess.Popen(
            [sys.executable, "-m", self._module],
            env=self._env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        log.close()

    def _tree(self) -> list[psutil.Process]:
        """The process and its children: on Windows a venv's python.exe is a launcher that
        runs the real interpreter as a child."""
        if self._popen is None:
            return []
        try:
            root = psutil.Process(self._popen.pid)
            return [root, *root.children(recursive=True)]
        except psutil.NoSuchProcess:
            return []

    def kill(self) -> None:
        """SIGKILL / TerminateProcess the whole tree: no cleanup, like a crashed host."""
        for proc in reversed(self._tree()):
            try:
                proc.kill()
            except psutil.NoSuchProcess:
                pass
        if self._popen is not None:
            self._popen.wait(timeout=10)

    def alive(self) -> bool:
        return self._popen is not None and self._popen.poll() is None

    def rss_mb(self) -> float:
        total = 0
        for proc in self._tree():
            try:
                total += proc.memory_info().rss
            except psutil.NoSuchProcess:
                pass
        return total / 1e6


class BenchFleet:
    """Everything one fleet size runs on. `env` is the bench infra's service env."""

    def __init__(
        self,
        base_env: dict[str, str],
        shard_ids: list[str],
        simulators: int,
        log_dir: Path,
    ) -> None:
        log_dir.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, **base_env}
        self.workers = {
            wid: BenchProcess(wid, "gridtwin.worker.main", {**env, "INSTANCE_ID": wid}, log_dir)
            for wid in WORKER_IDS
        }
        self.telemetry = BenchProcess(
            "telemetry",
            "gridtwin.telemetry.main",
            {**env, "INSTANCE_ID": "bench-telemetry"},
            log_dir,
        )
        per_sim = -(-len(shard_ids) // simulators)
        self.simulators = [
            BenchProcess(
                f"simulator-{i}",
                "gridtwin.simulator.main",
                {
                    **env,
                    "INSTANCE_ID": f"bench-simulator-{i}",
                    "SHARD_IDS": ",".join(shard_ids[i * per_sim : (i + 1) * per_sim]),
                },
                log_dir,
            )
            for i in range(simulators)
            if shard_ids[i * per_sim : (i + 1) * per_sim]
        ]

    def all(self) -> list[BenchProcess]:
        return [*self.workers.values(), self.telemetry, *self.simulators]

    def start(self) -> None:
        for proc in self.all():
            proc.start()

    def stop(self) -> None:
        for proc in self.all():
            proc.kill()

    def rss_by_role(self) -> dict[str, float]:
        """Workers, the ingester, and the simulators summed (they share one job)."""
        rss = {role: proc.rss_mb() for role, proc in self.workers.items()}
        rss["telemetry"] = self.telemetry.rss_mb()
        rss["simulators"] = sum(sim.rss_mb() for sim in self.simulators)
        return rss
