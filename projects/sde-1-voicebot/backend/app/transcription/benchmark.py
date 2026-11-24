"""Reproducible latency benchmark for transcription providers."""

from __future__ import annotations

import argparse
import math
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence

from app.audio.chunker import chunk_pcm
from app.audio.source import make_fake_pcm
from app.transcription.adapter import TranscriptionAdapter
from app.transcription.config import TranscriptionConfig
from app.transcription.faster_whisper import FasterWhisperAdapter
from app.transcription.mock import FakeTranscriber
from app.transcription.orchestrator import TranscriptionOrchestrator


@dataclass(frozen=True)
class LatencyRecord:
    """Latency metrics for a specific utterance duration."""

    duration_s: float
    chunk_count: int
    iterations: int
    mean_ms: float
    p50_ms: float
    p90_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float
    real_time_factor: float


@dataclass
class BenchmarkReport:
    """Aggregated benchmark report across multiple durations."""

    provider: str
    device: str
    compute_type: str
    records: list[LatencyRecord] = field(default_factory=list)

    def to_markdown_table(self) -> str:
        """Render metrics as a GitHub-flavored markdown table."""
        header = (
            "| Utterance Duration | Chunks | Iterations | p50 (ms) "
            "| p95 (ms) | Mean (ms) | RTF (p50) |\n"
            "|---|---|---|---|---|---|---|\n"
        )
        rows = [
            f"| {rec.duration_s:.1f}s | {rec.chunk_count} | {rec.iterations} "
            f"| {rec.p50_ms:.2f} | {rec.p95_ms:.2f} | {rec.mean_ms:.2f} "
            f"| {rec.real_time_factor:.4f}x |"
            for rec in self.records
        ]
        return header + "\n".join(rows)


def _percentile(data: Sequence[float], percentile: float) -> float:
    """Calculate the given percentile (0..100) using linear interpolation."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    if len(sorted_data) == 1:
        return sorted_data[0]
    rank = (percentile / 100.0) * (len(sorted_data) - 1)
    low_idx = int(math.floor(rank))
    high_idx = int(math.ceil(rank))
    if low_idx == high_idx:
        return sorted_data[low_idx]
    weight = rank - low_idx
    return (1.0 - weight) * sorted_data[low_idx] + weight * sorted_data[high_idx]


class TranscriptionBenchmark:
    """Executes reproducible latency benchmarks across synthetic audio fixtures."""

    def __init__(
        self,
        *,
        orchestrator: TranscriptionOrchestrator | None = None,
        config: TranscriptionConfig | None = None,
    ) -> None:
        if orchestrator is not None:
            self.orchestrator = orchestrator
            self.config = config or getattr(
                orchestrator, "config", TranscriptionConfig()
            )
        else:
            self.config = config or TranscriptionConfig()
            adapter: TranscriptionAdapter
            if self.config.provider == "faster_whisper":
                adapter = FasterWhisperAdapter(config=self.config)
            else:
                adapter = FakeTranscriber()
            self.orchestrator = TranscriptionOrchestrator(
                adapter=adapter, config=self.config
            )

    def benchmark_duration(
        self,
        duration_s: float,
        *,
        iterations: int = 5,
        warmup_runs: int = 1,
        chunk_ms: int = 20,
    ) -> LatencyRecord:
        """Benchmark a single utterance duration across multiple iterations."""
        if duration_s <= 0:
            raise ValueError("duration_s must be positive")
        if iterations <= 0:
            raise ValueError("iterations must be positive")

        duration_ms = int(round(duration_s * 1000))
        pcm = make_fake_pcm(duration_ms=duration_ms)
        session_id = f"bench-{int(duration_s * 1000)}ms"
        chunks = chunk_pcm(pcm, session_id=session_id, chunk_ms=chunk_ms)

        # Warmup to stabilize JIT/cache/imports
        for w in range(warmup_runs):
            self.orchestrator.reset(session_id)
            self.orchestrator.process_chunks(
                chunks,
                session_id=session_id,
                correlation_id=f"warmup-{w}",
                timestamp=datetime.now(timezone.utc),
            )

        latencies_ms: list[float] = []
        for i in range(iterations):
            self.orchestrator.reset(session_id)
            ts = datetime.now(timezone.utc)
            t_start = time.perf_counter()
            self.orchestrator.process_chunks(
                chunks,
                session_id=session_id,
                correlation_id=f"iter-{i}",
                timestamp=ts,
            )
            t_elapsed = (time.perf_counter() - t_start) * 1000.0
            latencies_ms.append(t_elapsed)

        mean_ms = statistics.mean(latencies_ms)
        p50_ms = _percentile(latencies_ms, 50.0)
        p90_ms = _percentile(latencies_ms, 90.0)
        p95_ms = _percentile(latencies_ms, 95.0)
        min_ms = min(latencies_ms)
        max_ms = max(latencies_ms)
        rtf = p50_ms / duration_ms if duration_ms > 0 else 0.0

        return LatencyRecord(
            duration_s=duration_s,
            chunk_count=len(chunks),
            iterations=iterations,
            mean_ms=mean_ms,
            p50_ms=p50_ms,
            p90_ms=p90_ms,
            p95_ms=p95_ms,
            min_ms=min_ms,
            max_ms=max_ms,
            real_time_factor=rtf,
        )

    def run_suite(
        self,
        durations_s: Sequence[float] = (1.0, 3.0, 5.0, 10.0),
        *,
        iterations: int = 5,
        warmup_runs: int = 1,
    ) -> BenchmarkReport:
        """Run the benchmark suite across all specified durations."""
        device, compute = self.config.resolve_device_and_compute()
        report = BenchmarkReport(
            provider=self.config.provider,
            device=device,
            compute_type=compute,
        )
        for dur in durations_s:
            rec = self.benchmark_duration(
                dur, iterations=iterations, warmup_runs=warmup_runs
            )
            report.records.append(rec)
        return report


def main() -> None:
    """CLI entrypoint for running transcription latency benchmark."""
    parser = argparse.ArgumentParser(
        description="Run reproducible transcription latency benchmarks."
    )
    parser.add_argument(
        "--provider",
        choices=["mock", "faster_whisper"],
        default="mock",
        help="Transcription provider to benchmark (default: mock)",
    )
    parser.add_argument(
        "--durations",
        nargs="+",
        type=float,
        default=[1.0, 3.0, 5.0, 10.0],
        help="Utterance durations in seconds (default: 1.0 3.0 5.0 10.0)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="Iterations per duration (default: 5)",
    )
    args = parser.parse_args()

    cfg = TranscriptionConfig(provider=args.provider)
    bench = TranscriptionBenchmark(config=cfg)
    print(f"Running latency benchmark for provider='{args.provider}'...")
    report = bench.run_suite(args.durations, iterations=args.iterations)

    print("\nBenchmark Results:")
    print(f"Provider: {report.provider} ({report.device}/{report.compute_type})")
    print(report.to_markdown_table())


if __name__ == "__main__":
    main()
