"""Data sources and side effects behind the real workflow tools.

Mock implementations are deterministic and touch nothing. Real ones read the
machine with psutil (``system`` extra, imported lazily) and open pages with the
standard-library ``webbrowser`` module.
"""

import ntpath
import posixpath
import webbrowser
from collections import deque
from dataclasses import dataclass
from typing import Protocol

from app.agent.errors import WorkflowPolicyError

GIB = 1024**3


@dataclass(frozen=True)
class ProcessUsage:
    name: str
    rss_bytes: int


@dataclass(frozen=True)
class SystemSnapshot:
    ram_total_bytes: int
    ram_used_bytes: int
    cpu_percent: float
    processes: tuple[ProcessUsage, ...]


class SystemStatsProvider(Protocol):
    def snapshot(self) -> SystemSnapshot: ...


class UrlOpener(Protocol):
    def open(self, url: str) -> None: ...


def top_processes(
    processes: tuple[ProcessUsage, ...] | list[ProcessUsage], limit: int = 5
) -> list[ProcessUsage]:
    """Group processes by name (Chrome runs many) and rank by total memory."""
    if type(limit) is not int or limit <= 0:
        raise ValueError("limit must be a positive integer")
    totals: dict[str, int] = {}
    for process in processes:
        name = process.name.strip() or "unknown"
        totals[name] = totals.get(name, 0) + max(0, process.rss_bytes)
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0].lower()))
    return [ProcessUsage(name, rss) for name, rss in ranked[:limit]]


def format_system_stats(snapshot: SystemSnapshot, *, limit: int = 5) -> str:
    """One short, speakable summary, e.g. for "what's using the most RAM?"."""
    if snapshot.ram_total_bytes <= 0:
        raise ValueError("ram_total_bytes must be positive")
    percent = 100 * snapshot.ram_used_bytes / snapshot.ram_total_bytes
    top = top_processes(snapshot.processes, limit)
    summary = (
        f"RAM {percent:.0f}% used ({snapshot.ram_used_bytes / GIB:.1f} of "
        f"{snapshot.ram_total_bytes / GIB:.1f} GB), CPU {snapshot.cpu_percent:.0f}%."
    )
    if not top:
        return summary
    listed = ", ".join(f"{p.name} {p.rss_bytes / GIB:.1f} GB" for p in top)
    return f"{summary} Top memory: {listed}."


def friendly_process_name(name: str | None, exe: str | None) -> str:
    """Program name a person would say: "zen", "chrome", "code".

    Linux truncates process names to 15 characters ("Isolated Web Co" for a
    browser tab), so the executable's file name is preferred when known.
    """
    base = ""
    if exe:
        base = ntpath.basename(posixpath.basename(exe.strip()))
    if not any(ch.isalpha() for ch in base):
        # e.g. an app run from ".../versions/2.1.330": the file name is a version.
        base = (name or "").strip()
    lowered = base.lower()
    for suffix in (".exe", "-bin"):
        if lowered.endswith(suffix):
            base = base[: -len(suffix)]
            lowered = base.lower()
    return base or "unknown"


class MockSystemStatsProvider:
    """Fixed numbers so tests and the mock demo never read the real machine."""

    def snapshot(self) -> SystemSnapshot:
        return SystemSnapshot(
            ram_total_bytes=16 * GIB,
            ram_used_bytes=10 * GIB,
            cpu_percent=12.0,
            processes=(
                ProcessUsage("chrome", int(1.8 * GIB)),
                ProcessUsage("chrome", int(1.3 * GIB)),
                ProcessUsage("code", int(1.2 * GIB)),
                ProcessUsage("python", int(0.4 * GIB)),
            ),
        )


class PsutilSystemStatsProvider:
    """Real machine stats; needs the ``system`` extra (psutil)."""

    def __init__(self, *, cpu_interval_s: float = 0.1) -> None:
        self._cpu_interval_s = cpu_interval_s

    def snapshot(self) -> SystemSnapshot:
        try:
            import psutil
        except ImportError as exc:
            raise WorkflowPolicyError(
                "WORKFLOW_TOOL_UNAVAILABLE",
                "System stats need the system extra (psutil).",
            ) from exc
        memory = psutil.virtual_memory()
        processes: list[ProcessUsage] = []
        for proc in psutil.process_iter(["name", "exe", "memory_info"]):
            try:
                info = proc.info
                mem = info.get("memory_info")
                if mem is None:
                    continue
                name = friendly_process_name(info.get("name"), info.get("exe"))
                processes.append(ProcessUsage(name, mem.rss))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return SystemSnapshot(
            ram_total_bytes=int(memory.total),
            ram_used_bytes=int(memory.total - memory.available),
            cpu_percent=float(psutil.cpu_percent(interval=self._cpu_interval_s)),
            processes=tuple(processes),
        )


class RecordingUrlOpener:
    """Mock opener: remembers the most recent URLs and opens nothing."""

    def __init__(self, *, keep: int = 50) -> None:
        self.opened: deque[str] = deque(maxlen=keep)

    def open(self, url: str) -> None:
        self.opened.append(url)


class WebbrowserUrlOpener:
    """Real opener: the user's default browser, in a new tab."""

    def open(self, url: str) -> None:
        if not webbrowser.open_new_tab(url):
            raise RuntimeError("no browser could be opened")
