from __future__ import annotations
import sqlite3
from local_watch.schema import Snapshot

class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.execute("create table if not exists snapshots("
                        "machine text, ts text, json text, primary key(machine, ts))")

    def append(self, snap: Snapshot) -> None:
        self.db.execute("insert or replace into snapshots values(?,?,?)",
                        (snap.machine, snap.ts, snap.to_json()))
        self.db.commit()

    def latest(self, machine: str) -> Snapshot | None:
        row = self.db.execute("select json from snapshots where machine=? order by ts desc limit 1",
                              (machine,)).fetchone()
        return Snapshot.from_json(row[0]) if row else None

    def series(self, machine: str, metric: str, n: int) -> list[tuple[str, float]]:
        """Up to `n` most recent (ts, value) points for one metric, oldest first.

        Timestamps are part of the contract: readings are not evenly spaced
        (a sleeping laptop leaves gaps), so a rate of change can only be
        computed against real elapsed time, never against sample count.
        """
        rows = self.db.execute("select ts, json from snapshots where machine=? order by ts desc limit ?",
                               (machine, n)).fetchall()
        out: list[tuple[str, float]] = []
        for ts, j in rows:
            snap = Snapshot.from_json(j)
            out += [(ts, m.value) for m in snap.metrics if m.name == metric]
        return out[::-1]

    def machines(self) -> list[str]:
        return [r[0] for r in self.db.execute("select distinct machine from snapshots order by machine")]
