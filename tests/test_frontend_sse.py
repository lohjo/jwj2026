"""Regression tests for SSE parsing in static/index.html."""

from pathlib import Path


INDEX_HTML = Path(__file__).resolve().parents[1] / "static" / "index.html"


def _analyse_text_stream_block() -> str:
    source = INDEX_HTML.read_text(encoding="utf-8")
    start = source.index("async function analyseTextStream()")
    end = source.index("function updatePipelineStep(", start)
    return source[start:end]


def test_text_sse_keeps_current_event_across_chunks():
    """currentEvent must be outside the read loop to survive chunk boundaries."""
    block = _analyse_text_stream_block()
    assert "let currentEvent = '';" in block
    assert block.index("let currentEvent = '';") < block.index("while (true) {")


def test_text_sse_throws_when_final_result_missing():
    """Prevent indefinite loading by surfacing missing final SSE result."""
    block = _analyse_text_stream_block()
    assert "throw new Error('Analysis did not return a final result');" in block
