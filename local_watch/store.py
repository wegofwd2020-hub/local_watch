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

    def series(self, machine: str, metric: str, n: int) -> list[float]:
        rows = self.db.execute("select json from snapshots where machine=? order by ts desc limit ?",
                               (machine, n)).fetchall()
        out = []
        for (j,) in rows:
            s = Snapshot.from_json(j)
            out += [m.value for m in s.metrics if m.name == metric]
        return out[::-1]

    def machines(self) -> list[str]:
        return [r[0] for r in self.db.execute("select distinct machine from snapshots order by machine")]
