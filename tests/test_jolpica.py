# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Historic pagination stops safely and can stream rows."""
import pytest

from f1verse.sources import jolpica


def test_iter_paged_uses_actual_rows_for_next_offset(monkeypatch):
    offsets = []
    def fake_get(path, limit, offset, ttl):
        offsets.append(offset)
        rows = ([{"id": 1}, {"id": 2}] if offset == 0
                else [{"id": 3}])
        return {"total": "3", "Table": {"Rows": rows}}

    monkeypatch.setattr(jolpica, "get", fake_get)
    rows = list(jolpica.iter_paged("x", "Table", "Rows", page=100))
    assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert offsets == [0, 2]


def test_iter_paged_has_hard_page_limit(monkeypatch):
    monkeypatch.setattr(jolpica, "get", lambda *args, **kwargs:
                        {"total": "999", "Table": {"Rows": [{"id": 1}]}})
    with pytest.raises(RuntimeError, match="exceeded 2 pages"):
        list(jolpica.iter_paged("x", "Table", "Rows", max_pages=2))
