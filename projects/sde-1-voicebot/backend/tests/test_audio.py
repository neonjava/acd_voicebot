"""Observable behavior of the W1 fake source, chunker and CLI."""

import json

import pytest

from app.audio.chunker import chunk_pcm
from app.audio.cli import main
from app.audio.source import make_fake_pcm
from app.contracts.audio import AudioChunk, AudioFormat


def test_one_second_stream_has_fifty_contiguous_chunks():
    pcm = make_fake_pcm()
    chunks = chunk_pcm(pcm, session_id="session-demo")

    assert len(pcm) == 32000
    assert len(chunks) == 50
    assert all(isinstance(chunk, AudioChunk) for chunk in chunks)
    assert [chunk.sequence_id for chunk in chunks] == list(range(50))
    assert [chunk.start_ms for chunk in chunks] == list(range(0, 1000, 20))
    assert all(chunk.duration_ms == 20 for chunk in chunks)
    assert all(chunk.session_id == "session-demo" for chunk in chunks)
    assert all(chunk.format == AudioFormat() for chunk in chunks)
    assert b"".join(chunk.pcm for chunk in chunks) == pcm


def test_source_and_chunker_are_repeatable():
    first = make_fake_pcm(duration_ms=60)
    second = make_fake_pcm(duration_ms=60)
    assert first == second
    assert chunk_pcm(first, session_id="same") == chunk_pcm(second, session_id="same")


def test_short_final_chunk_keeps_exact_timestamp_and_bytes():
    chunks = chunk_pcm(make_fake_pcm(duration_ms=45), session_id="s", chunk_ms=20)
    assert [(c.sequence_id, c.start_ms, c.duration_ms, len(c.pcm)) for c in chunks] == [
        (0, 0, 20, 640),
        (1, 20, 20, 640),
        (2, 40, 5, 160),
    ]


def test_empty_stream_produces_no_chunks():
    assert make_fake_pcm(duration_ms=0) == b""
    assert chunk_pcm(b"", session_id="session-demo") == []


@pytest.mark.parametrize("duration_ms", [-1, True, 1.0, "20", None])
def test_source_rejects_invalid_duration(duration_ms):
    with pytest.raises(ValueError):
        make_fake_pcm(duration_ms=duration_ms)


@pytest.mark.parametrize(
    "pcm", [bytearray(32), b"\x00", bytes(31), bytes(34), bytes(640) + b"\x00"]
)
def test_chunker_rejects_invalid_or_partial_pcm(pcm):
    with pytest.raises(ValueError):
        chunk_pcm(pcm, session_id="session-demo")


@pytest.mark.parametrize("chunk_ms", [0, -1, True, 1.5, "20"])
def test_chunker_rejects_invalid_chunk_size(chunk_ms):
    with pytest.raises(ValueError):
        chunk_pcm(bytes(32), session_id="session-demo", chunk_ms=chunk_ms)


@pytest.mark.parametrize("session_id", ["", "  ", None])
def test_chunker_rejects_invalid_session_even_for_empty_audio(session_id):
    with pytest.raises(ValueError):
        chunk_pcm(b"", session_id=session_id)


def test_cli_prints_metadata_only(capsys):
    assert main(["--duration-ms", "25", "--chunk-ms", "20"]) == 0
    output = capsys.readouterr()
    lines = output.out.strip().splitlines()
    assert len(lines) == 2
    assert "sequence=0 start_ms=0 duration_ms=20" in lines[0]
    assert "sequence=1 start_ms=20 duration_ms=5" in lines[1]
    assert "bytes=160" in lines[1]
    assert "pcm=" not in output.out
    assert output.err == ""


def test_cli_invalid_input_returns_safe_audio_error(capsys):
    assert main(["--duration-ms", "-1"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    error = json.loads(output.err)
    assert error["code"] == "AUDIO_INVALID_INPUT"
    assert error["correlation_id"] == "correlation-demo"
    assert "-1" not in output.err
