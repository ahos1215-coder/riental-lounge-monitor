from datetime import datetime, timezone

from oriental.data.provider import SupabaseLogsProvider


class _FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.last_params = None
        self.last_headers = None
        self.last_url = None
        self.last_timeout = None

    def mount(self, *_args, **_kwargs):
        return None

    def get(self, url, *, params=None, headers=None, timeout=None):
        self.last_url = url
        self.last_params = params
        self.last_headers = headers
        self.last_timeout = timeout
        return _FakeResponse(200, self.payload)


def test_supabase_provider_fetches_and_normalises_rows():
    payload = [
        {"ts": "2024-11-01T00:00:00Z", "men": "10", "women": 5, "total": 15, "src_brand": "oriental"},
        {"ts": "2024-11-01T00:05:00Z", "men": None, "women": None, "total": None},
    ]
    session = _FakeSession(payload)
    provider = SupabaseLogsProvider(
        base_url="https://example.supabase.co",
        api_key="test-key",
        session=session,
    )

    start = datetime(2024, 11, 1, tzinfo=timezone.utc)
    end = datetime(2024, 11, 2, tzinfo=timezone.utc)

    rows = provider.fetch_range(store_id="ol_test", start_ts=start, end_ts=end, limit=10)

    assert rows[0]["men"] == 10
    assert rows[0]["women"] == 5
    assert rows[0]["total"] == 15
    assert rows[0]["src_brand"] == "oriental"
    assert rows[-1]["ts"] == "2024-11-01T00:05:00Z"

    assert session.last_url.endswith("/rest/v1/logs")
    assert ("store_id", "eq.ol_test") in session.last_params
    assert session.last_headers["Range"] == "0-9"
