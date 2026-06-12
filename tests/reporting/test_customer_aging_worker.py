from __future__ import annotations

from inventory_management.modules.reporting import customer_aging_reports as car


class _FakeConn:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_customer_aging_worker_uses_own_connection_factory(monkeypatch) -> None:
    seen = {"factory_calls": 0, "logic_conn": None, "finished": None, "error": None}
    fake_conn = _FakeConn()

    def factory() -> _FakeConn:
        seen["factory_calls"] += 1
        return fake_conn

    class FakeLogic:
        def __init__(self, conn) -> None:
            seen["logic_conn"] = conn

        def compute_aging_snapshot(self, *args, **kwargs):
            return [
                {
                    "customer_id": 1,
                    "name": "Alpha",
                    "total_due": 10.0,
                    "b_0_30": 10.0,
                    "b_31_60": 0.0,
                    "b_61_90": 0.0,
                    "b_91_plus": 0.0,
                    "available_credit": 0.0,
                }
            ]

    monkeypatch.setattr(car, "CustomerAgingReports", FakeLogic)

    worker = car.CustomerAgingWorker(
        factory,
        "2026-06-10",
        ((0, 30), (31, 60), (61, 90), (91, 10_000)),
        True,
        None,
    )
    worker.finished.connect(lambda value: seen.__setitem__("finished", value))
    worker.error.connect(lambda value: seen.__setitem__("error", value))

    worker.run()

    assert seen["factory_calls"] == 1
    assert seen["logic_conn"] is fake_conn
    assert seen["finished"] == [
        {
            "customer_id": 1,
            "name": "Alpha",
            "total_due": 10.0,
            "b_0_30": 10.0,
            "b_31_60": 0.0,
            "b_61_90": 0.0,
            "b_91_plus": 0.0,
            "available_credit": 0.0,
        }
    ]
    assert seen["error"] is None
    assert fake_conn.closed is True
