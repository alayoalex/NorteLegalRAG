from norte_legal.services.ingestion import BACKOFF_BASE_S, BACKOFF_CAP_S, backoff_delay


def test_grows_exponentially_with_jitter_and_a_cap() -> None:
    for attempt in range(1, 12):
        step = min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2 ** (attempt - 1))
        for _ in range(50):
            assert step / 2 <= backoff_delay(attempt) <= step


def test_never_retries_before_retry_after() -> None:
    assert backoff_delay(1, retry_after_s=120) == 120
