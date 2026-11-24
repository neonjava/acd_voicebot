"""Tests for reproducible transcription latency benchmark."""

from __future__ import annotations

import pytest

from app.transcription.benchmark import (
    BenchmarkReport,
    LatencyRecord,
    TranscriptionBenchmark,
    _percentile,
)
from app.transcription.config import TranscriptionConfig
from app.transcription.mock import FakeTranscriber
from app.transcription.orchestrator import TranscriptionOrchestrator


class TestPercentileCalculation:
    """Test statistical percentile calculation."""

    def test_percentile_empty_data(self) -> None:
        assert _percentile([], 50.0) == 0.0

    def test_percentile_single_value(self) -> None:
        assert _percentile([42.0], 50.0) == 42.0
        assert _percentile([42.0], 95.0) == 42.0

    def test_percentile_multiple_values(self) -> None:
        data = [10.0, 20.0, 30.0, 40.0, 50.0]
        assert _percentile(data, 50.0) == 30.0
        assert _percentile(data, 0.0) == 10.0
        assert _percentile(data, 100.0) == 50.0


class TestBenchmarkExecution:
    """Test execution of latency benchmarks across synthetic audio fixtures."""

    def test_benchmark_duration_validation(self) -> None:
        bench = TranscriptionBenchmark(config=TranscriptionConfig(provider="mock"))
        with pytest.raises(ValueError, match="duration_s must be positive"):
            bench.benchmark_duration(0.0)
        with pytest.raises(ValueError, match="duration_s must be positive"):
            bench.benchmark_duration(-1.0)
        with pytest.raises(ValueError, match="iterations must be positive"):
            bench.benchmark_duration(1.0, iterations=0)

    def test_benchmark_single_duration_mock(self) -> None:
        bench = TranscriptionBenchmark(config=TranscriptionConfig(provider="mock"))
        record = bench.benchmark_duration(0.5, iterations=3, warmup_runs=1, chunk_ms=20)

        assert isinstance(record, LatencyRecord)
        assert record.duration_s == 0.5
        assert record.chunk_count == 25  # 500ms / 20ms = 25
        assert record.iterations == 3
        assert record.mean_ms > 0
        assert record.p50_ms > 0
        assert record.p95_ms >= record.p50_ms
        assert record.real_time_factor > 0

    def test_benchmark_suite_mock_report(self) -> None:
        bench = TranscriptionBenchmark(config=TranscriptionConfig(provider="mock"))
        report = bench.run_suite(durations_s=[0.2, 0.4], iterations=2, warmup_runs=1)

        assert isinstance(report, BenchmarkReport)
        assert report.provider == "mock"
        assert len(report.records) == 2
        assert report.records[0].duration_s == 0.2
        assert report.records[1].duration_s == 0.4

        md_table = report.to_markdown_table()
        assert "| Utterance Duration |" in md_table
        assert "0.2s" in md_table
        assert "0.4s" in md_table

    def test_benchmark_with_injected_orchestrator(self) -> None:
        adapter = FakeTranscriber()
        orch = TranscriptionOrchestrator(adapter=adapter)
        bench = TranscriptionBenchmark(orchestrator=orch)
        record = bench.benchmark_duration(0.1, iterations=1, warmup_runs=0)
        assert record.chunk_count == 5
