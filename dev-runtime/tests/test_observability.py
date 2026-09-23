import logging
import pytest
from backend.observability import match_trace, timed, request_id

def test_trace_correlates_stages_and_records_failure(caplog):
    @timed("scene_compare")
    def compare():
        raise TimeoutError("private data must not be logged")
    @match_trace
    def match():
        compare()
    with caplog.at_level(logging.INFO, logger="rugscene.timing"):
        with pytest.raises(TimeoutError):
            match()
    messages = [r.getMessage() for r in caplog.records]
    assert len(messages) == 2
    assert messages[0].split()[0] == messages[1].split()[0]
    assert "outcome=TimeoutError" in messages[0]
    assert "private data" not in caplog.text
    assert request_id.get() == "-"
