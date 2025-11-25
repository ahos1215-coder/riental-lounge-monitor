from pathlib import Path

import pytest

from oriental.data.provider import GoogleSheetProvider


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.called_with = None

    def mount(self, *_args, **_kwargs):
        return None

    def get(self, url, *, params=None, timeout=None):
        self.called_with = {"url": url, "params": params, "timeout": timeout}
        return _FakeResponse(self.payload)


@pytest.mark.parametrize(
    "payload,expected_ts",
    [
        ([{"ts": "2024-11-01T00:00:00Z"}], "2024-11-01T00:00:00Z"),
        ({"ok": True, "rows": [{"ts": "2024-11-02T00:00:00Z"}]}, "2024-11-02T00:00:00Z"),
    ],
)
def test_google_sheet_provider_handles_dict_rows(payload, expected_ts, tmp_path):
    dummy_file = tmp_path / "dummy.json"
    dummy_file.write_text("[]", encoding="utf-8")

    session = _FakeSession(payload)
    provider = GoogleSheetProvider("https://example.com", Path(dummy_file), logger=None)
    provider.session = session  # inject fake session

    rows = provider.get_records("store-x")
    assert rows
    ts_value = rows[0]["ts"]
    assert ts_value.replace("+00:00", "Z") == expected_ts
