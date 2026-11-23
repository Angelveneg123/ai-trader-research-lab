"""Check the original journal and apply schema to a SQLite-backup copy."""
from contextlib import closing
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
from app.prospective_store import budget, connect

original = root / "backend/data/prospective_v22.sqlite3"
baseline_hash = sha256(original.read_bytes()).hexdigest()
with TemporaryDirectory(prefix="migration_v25_") as d:
    copy = Path(d) / "diario.sqlite3"
    with closing(sqlite3.connect(original.as_uri() + "?mode=ro&immutable=1", uri=True)) as readonly, \
         closing(sqlite3.connect(copy)) as duplicate:
        assert readonly.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        readonly.backup(duplicate)
    with closing(sqlite3.connect(copy)) as before:
        tables = {r[0]: before.execute('SELECT COUNT(*) FROM "' + r[0].replace('"','""') + '"').fetchone()[0]
                  for r in before.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    with closing(connect(copy)) as migrated:
        assert migrated.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        for table, count in tables.items():
            assert migrated.execute('SELECT COUNT(*) FROM "' + table.replace('"','""') + '"').fetchone()[0] == count
        summary = budget(migrated)
        assert summary["gemini"]["attempts"] + summary["openai"]["attempts"] >= tables["diagnostic_calls"]
        print("Conteos preservados", tables)
        print("Diario actualizado en copia con presupuesto acumulado", summary)
assert sha256(original.read_bytes()).hexdigest() == baseline_hash
print("SHA256 original intacto", baseline_hash)
