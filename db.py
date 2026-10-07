"""SQLite persistence: one database file per company."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Generator, Iterable

from app_paths import data_dir

ACTIVE_TABLE = "audit_records"
ARCHIVE_PREFIX = "archive_audit_"
ARCHIVE_NAME_RE = re.compile(rf"^{ARCHIVE_PREFIX}\d{{8}}_\d{{6}}(?:_\d{{2}})?$")
DB_PREFIX = "audit_database_"
LEGACY_DB_NAME = "audit_database.db"

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS audit_records (
    id INTEGER PRIMARY KEY,
    bedrijf TEXT,
    sessie_naam TEXT,
    sub_hoofdstuk TEXT,
    geselecteerde_paragrafen TEXT,
    auditees TEXT,
    documenten TEXT,
    bevindingen TEXT,
    conclusie TEXT,
    aantekeningen TEXT,
    datum TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

META_SQL = """
CREATE TABLE IF NOT EXISTS archive_meta (
    table_name TEXT PRIMARY KEY,
    bedrijf TEXT NOT NULL,
    created_at TEXT
)
"""

INFO_SQL = """
CREATE TABLE IF NOT EXISTS db_info (
    sleutel TEXT PRIMARY KEY,
    waarde TEXT
)
"""

RETAINED_SQL = """
CREATE TABLE IF NOT EXISTS retained_documents (
    id INTEGER PRIMARY KEY,
    ref TEXT,
    beschrijving TEXT,
    bron_record_id INTEGER,
    datum TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

COPY_COLUMNS = (
    "bedrijf, sessie_naam, sub_hoofdstuk, geselecteerde_paragrafen, "
    "auditees, documenten, bevindingen, conclusie, aantekeningen, datum"
)

_current_path: Path | None = None


def get_db_path() -> Path | None:
    return _current_path


def set_db_path(path: Path | str | None) -> None:
    global _current_path
    _current_path = Path(path) if path else None


def safe_bedrijf_token(bedrijf: str) -> str:
    text = (bedrijf or "").strip()
    text = re.sub(r'[<>:"/\\|?*]', "", text)
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^\w.\-]+", "_", text, flags=re.UNICODE)
    return text.strip("._") or "bedrijf"


def db_filename_for(bedrijf: str) -> str:
    return f"{DB_PREFIX}{safe_bedrijf_token(bedrijf)}.db"


def db_path_for(bedrijf: str) -> Path:
    return data_dir() / db_filename_for(bedrijf)


def bedrijf_from_filename(path: Path | str) -> str:
    naam = Path(path).name
    if naam.lower() == LEGACY_DB_NAME.lower():
        return ""
    if naam.startswith(DB_PREFIX) and naam.lower().endswith(".db"):
        return naam[len(DB_PREFIX) : -3]
    return Path(naam).stem


def list_database_files() -> list[Path]:
    root = data_dir()
    found: list[Path] = []
    for pad in sorted(root.glob("*.db"), key=lambda item: item.name.lower()):
        if pad.name.lower() == LEGACY_DB_NAME.lower():
            continue
        if pad.name.lower().endswith("-journal"):
            continue
        found.append(pad)
    return found


@contextmanager
def connect(path: Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    doel = Path(path) if path is not None else _current_path
    if doel is None:
        raise RuntimeError("Geen database geopend.")
    doel.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(doel)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: Path | None = None) -> None:
    with connect(path) as conn:
        conn.execute(CREATE_SQL)
        conn.execute(META_SQL)
        conn.execute(INFO_SQL)
        conn.execute(RETAINED_SQL)
        _ensure_columns(conn)
        _backfill_archive_meta(conn)


def _ensure_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(audit_records)")}
    required = {
        "bedrijf": "TEXT",
        "sessie_naam": "TEXT",
        "sub_hoofdstuk": "TEXT",
        "geselecteerde_paragrafen": "TEXT",
        "auditees": "TEXT",
        "documenten": "TEXT",
        "bevindingen": "TEXT",
        "conclusie": "TEXT",
        "aantekeningen": "TEXT",
        "datum": "TIMESTAMP",
    }
    for name, col_type in required.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE audit_records ADD COLUMN {name} {col_type}")


def _norm_bedrijf(value: str | None) -> str:
    return (value or "").strip()


def set_db_bedrijf(bedrijf: str, path: Path | None = None) -> None:
    with connect(path) as conn:
        conn.execute(
            """
            INSERT INTO db_info (sleutel, waarde) VALUES ('bedrijf', ?)
            ON CONFLICT(sleutel) DO UPDATE SET waarde = excluded.waarde
            """,
            (_norm_bedrijf(bedrijf),),
        )


def get_db_bedrijf(path: Path | None = None) -> str:
    try:
        with connect(path) as conn:
            row = conn.execute(
                "SELECT waarde FROM db_info WHERE sleutel = 'bedrijf'"
            ).fetchone()
            if row and str(row["waarde"] or "").strip():
                return str(row["waarde"]).strip()
            companies = _companies_in_table(conn, ACTIVE_TABLE)
            if companies:
                return companies[0]
    except Exception:
        pass
    doel = Path(path) if path is not None else _current_path
    return bedrijf_from_filename(doel) if doel else ""


def _assert_archive_name(name: str) -> str:
    if not ARCHIVE_NAME_RE.match(name):
        raise ValueError("Ongeldige archieftabel.")
    return name


def _table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in info)


def _companies_in_table(conn: sqlite3.Connection, table: str) -> list[str]:
    if not _table_has_column(conn, table, "bedrijf"):
        return []
    rows = conn.execute(
        f"""
        SELECT DISTINCT TRIM(bedrijf) AS bedrijf
        FROM {table}
        WHERE TRIM(COALESCE(bedrijf, '')) <> ''
        ORDER BY 1
        """
    ).fetchall()
    return [row["bedrijf"] for row in rows if row["bedrijf"]]


def _backfill_archive_meta(conn: sqlite3.Connection) -> None:
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
        (f"{ARCHIVE_PREFIX}%",),
    ).fetchall()
    for row in tables:
        name = row["name"]
        if not ARCHIVE_NAME_RE.match(name):
            continue
        exists = conn.execute(
            "SELECT 1 FROM archive_meta WHERE table_name = ?", (name,)
        ).fetchone()
        if exists:
            continue
        companies = _companies_in_table(conn, name)
        bedrijf = companies[0] if companies else ""
        if bedrijf:
            conn.execute(
                "INSERT OR IGNORE INTO archive_meta (table_name, bedrijf, created_at) VALUES (?, ?, ?)",
                (name, bedrijf, datetime.now().isoformat(timespec="seconds")),
            )


def _register_archive_meta(conn: sqlite3.Connection, table_name: str, bedrijf: str) -> None:
    conn.execute(
        """
        INSERT INTO archive_meta (table_name, bedrijf, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(table_name) DO UPDATE SET bedrijf = excluded.bedrijf
        """,
        (table_name, _norm_bedrijf(bedrijf), datetime.now().isoformat(timespec="seconds")),
    )


def _unique_archive_name(conn: sqlite3.Connection) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"{ARCHIVE_PREFIX}{stamp}"
    existing = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    existing.update(
        row["table_name"]
        for row in conn.execute("SELECT table_name FROM archive_meta")
    )
    suffix = 1
    while archive_name in existing:
        suffix += 1
        archive_name = f"{ARCHIVE_PREFIX}{stamp}_{suffix:02d}"
    return archive_name


def create_company_database(bedrijf: str) -> Path:
    naam = _norm_bedrijf(bedrijf)
    if not naam:
        raise ValueError("Vul een bedrijfsnaam in.")
    doel = db_path_for(naam)
    if doel.exists():
        raise ValueError(f"Database {doel.name} bestaat al.")
    init_db(doel)
    set_db_bedrijf(naam, doel)
    return doel


def import_database_bytes(inhoud: bytes, bestandsnaam: str) -> Path:
    naam = Path(bestandsnaam or "upload.db").name
    if not naam.lower().endswith(".db"):
        naam = f"{naam}.db"
    if not naam.startswith(DB_PREFIX):
        stam = Path(naam).stem
        naam = db_filename_for(stam)
    doel = data_dir() / naam
    if doel.exists():
        stem = Path(naam).stem
        n = 2
        while True:
            kandidaat = data_dir() / f"{stem}_{n:02d}.db"
            if not kandidaat.exists():
                doel = kandidaat
                break
            n += 1
    doel.write_bytes(inhoud)
    init_db(doel)
    if not get_db_bedrijf(doel):
        set_db_bedrijf(bedrijf_from_filename(doel), doel)
    return doel


def export_database_bytes(path: Path | str | None = None) -> bytes:
    doel = Path(path) if path is not None else _current_path
    if doel is None or not doel.exists():
        raise RuntimeError("Geen database geopend.")
    with sqlite3.connect(doel) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return doel.read_bytes()


def _copy_company(src_path: Path, dest_path: Path, bedrijf: str) -> None:
    wanted = _norm_bedrijf(bedrijf)
    init_db(dest_path)
    src = sqlite3.connect(src_path)
    src.row_factory = sqlite3.Row
    dest = sqlite3.connect(dest_path)
    dest.row_factory = sqlite3.Row
    try:
        dest.execute("DELETE FROM audit_records")
        cols = [
            row[1]
            for row in dest.execute("PRAGMA table_info(audit_records)")
            if row[1] != "id"
        ]
        src_cols = {row[1] for row in src.execute("PRAGMA table_info(audit_records)")}
        use_cols = [c for c in cols if c in src_cols]
        col_sql = ", ".join(use_cols)
        rows = src.execute(
            f"""
            SELECT {col_sql} FROM audit_records
            WHERE LOWER(TRIM(COALESCE(bedrijf, ''))) = LOWER(TRIM(?))
            """,
            (wanted,),
        ).fetchall()
        if rows:
            placeholders = ", ".join("?" * len(use_cols))
            dest.executemany(
                f"INSERT INTO audit_records ({col_sql}) VALUES ({placeholders})",
                [tuple(row[c] for c in use_cols) for row in rows],
            )

        tables = src.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
            (f"{ARCHIVE_PREFIX}%",),
        ).fetchall()
        for row in tables:
            table = row["name"]
            if not ARCHIVE_NAME_RE.match(table):
                continue
            src_info = {r[1] for r in src.execute(f"PRAGMA table_info({table})")}
            if "bedrijf" in src_info:
                match = src.execute(
                    f"""
                    SELECT 1 FROM {table}
                    WHERE LOWER(TRIM(COALESCE(bedrijf, ''))) = LOWER(TRIM(?))
                    LIMIT 1
                    """,
                    (wanted,),
                ).fetchone()
                if not match:
                    continue
            dest.execute(f"DROP TABLE IF EXISTS {table}")
            dest.execute(f"CREATE TABLE {table} AS SELECT * FROM audit_records WHERE 0")
            dest_cols = [r[1] for r in dest.execute(f"PRAGMA table_info({table})")]
            overlap = [c for c in dest_cols if c in src_info]
            if "bedrijf" in src_info:
                data = src.execute(
                    f"SELECT {', '.join(overlap)} FROM {table} WHERE LOWER(TRIM(COALESCE(bedrijf, ''))) = LOWER(TRIM(?))",
                    (wanted,),
                ).fetchall()
            else:
                data = src.execute(f"SELECT {', '.join(overlap)} FROM {table}").fetchall()
            if data:
                dest.executemany(
                    f"INSERT INTO {table} ({', '.join(overlap)}) VALUES ({', '.join('?' * len(overlap))})",
                    [tuple(item[c] for c in overlap) for item in data],
                )
            dest.execute(
                "INSERT OR REPLACE INTO archive_meta (table_name, bedrijf, created_at) VALUES (?, ?, ?)",
                (table, wanted, datetime.now().isoformat(timespec="seconds")),
            )
        dest.execute(
            "INSERT OR REPLACE INTO db_info (sleutel, waarde) VALUES ('bedrijf', ?)",
            (wanted,),
        )
        dest.commit()
    finally:
        src.close()
        dest.close()


def migrate_legacy_databases() -> None:
    """Split the old shared SQLite file into one file per company; keep APB data."""
    root = data_dir()
    legacy = root / LEGACY_DB_NAME
    if not legacy.exists():
        apb = root / db_filename_for("APB")
        if apb.exists():
            init_db(apb)
        return

    src = sqlite3.connect(legacy)
    src.row_factory = sqlite3.Row
    try:
        src.execute("CREATE TABLE IF NOT EXISTS audit_records (id INTEGER PRIMARY KEY)")
        companies = []
        if _table_has_column(src, ACTIVE_TABLE, "bedrijf"):
            companies = _companies_in_table(src, ACTIVE_TABLE)
            for row in src.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
                (f"{ARCHIVE_PREFIX}%",),
            ):
                table = row["name"]
                if ARCHIVE_NAME_RE.match(table):
                    for naam in _companies_in_table(src, table):
                        if naam not in companies:
                            companies.append(naam)
        if not companies:
            companies = ["APB"]
    finally:
        src.close()

    for bedrijf in companies:
        doel = db_path_for(bedrijf)
        if doel.exists() and doel.resolve() == legacy.resolve():
            continue
        if doel.exists():
            init_db(doel)
            with sqlite3.connect(doel) as dest:
                n = dest.execute("SELECT COUNT(*) FROM audit_records").fetchone()[0]
            if n:
                continue
        try:
            _copy_company(legacy, doel, bedrijf)
        except Exception:
            init_db(doel)
            set_db_bedrijf(bedrijf, doel)

    apb_doel = db_path_for("APB")
    if apb_doel.exists():
        init_db(apb_doel)


def list_companies() -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    with connect() as conn:
        for name in _companies_in_table(conn, ACTIVE_TABLE):
            key = name.casefold()
            if key not in seen:
                seen.add(key)
                found.append(name)
    extra = get_db_bedrijf()
    if extra and extra.casefold() not in seen:
        found.append(extra)
    return sorted(found, key=str.casefold)


def insert_record(payload: dict[str, Any]) -> int:
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO audit_records (
                bedrijf, sessie_naam, sub_hoofdstuk, geselecteerde_paragrafen,
                auditees, documenten, bevindingen, conclusie, aantekeningen, datum
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                payload["bedrijf"],
                payload["sessie_naam"],
                payload["sub_hoofdstuk"],
                payload["geselecteerde_paragrafen"],
                payload["auditees"],
                payload["documenten"],
                payload["bevindingen"],
                payload["conclusie"],
                payload.get("aantekeningen") or "",
            ),
        )
        return int(cursor.lastrowid)


def update_record(record_id: int, payload: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE audit_records
            SET bedrijf = ?,
                sessie_naam = ?,
                sub_hoofdstuk = ?,
                geselecteerde_paragrafen = ?,
                auditees = ?,
                documenten = ?,
                bevindingen = ?,
                conclusie = ?,
                aantekeningen = ?
            WHERE id = ?
            """,
            (
                payload["bedrijf"],
                payload["sessie_naam"],
                payload["sub_hoofdstuk"],
                payload["geselecteerde_paragrafen"],
                payload["auditees"],
                payload["documenten"],
                payload["bevindingen"],
                payload["conclusie"],
                payload.get("aantekeningen") or "",
                record_id,
            ),
        )


def delete_record(record_id: int) -> None:
    """Delete a finding record but keep its documents in the audit document list."""
    with connect() as conn:
        row = conn.execute(
            "SELECT id, documenten FROM audit_records WHERE id = ?",
            (record_id,),
        ).fetchone()
        if not row:
            return
        try:
            docs = json.loads(row["documenten"] or "[]")
        except (TypeError, json.JSONDecodeError):
            docs = []
        if isinstance(docs, list):
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                ref = str(doc.get("ref") or "").strip()
                beschrijving = str(doc.get("beschrijving") or "").strip()
                if not ref and not beschrijving:
                    continue
                conn.execute(
                    """
                    INSERT INTO retained_documents (ref, beschrijving, bron_record_id)
                    VALUES (?, ?, ?)
                    """,
                    (ref, beschrijving, record_id),
                )
        conn.execute("DELETE FROM audit_records WHERE id = ?", (record_id,))


def update_documenten(record_id: int, bedrijf: str, documenten: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE audit_records SET documenten = ? WHERE id = ?",
            (documenten, record_id),
        )


def fetch_retained_documents() -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT id, ref, beschrijving, bron_record_id FROM retained_documents ORDER BY id"
        ).fetchall()


def replace_retained_documents(rijen: list[dict[str, Any]]) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM retained_documents")
        for rij in rijen:
            if rij.get("verwijderen"):
                continue
            ref = str(rij.get("ref") or "").strip()
            beschrijving = str(rij.get("beschrijving") or "").strip()
            if not ref and not beschrijving:
                continue
            conn.execute(
                """
                INSERT INTO retained_documents (ref, beschrijving, bron_record_id)
                VALUES (?, ?, ?)
                """,
                (ref, beschrijving, rij.get("bron_record_id")),
            )


def collect_auditees() -> list[str]:
    namen: list[str] = []
    seen: set[str] = set()
    for record in fetch_history():
        for deel in str(record["auditees"] or "").split(","):
            naam = deel.strip()
            key = naam.casefold()
            if naam and key not in seen:
                seen.add(key)
                namen.append(naam)
    return namen


def suggest_sessie_naam(bedrijf: str | None = None) -> str:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT sessie_naam FROM audit_records
            WHERE TRIM(COALESCE(sessie_naam, '')) <> ''
            ORDER BY datetime(datum) DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    if not row:
        return ""
    return str(row["sessie_naam"]).strip()


def fetch_history(bedrijf: str | None = None) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            """
            SELECT id, bedrijf, sessie_naam, sub_hoofdstuk, geselecteerde_paragrafen,
                   auditees, documenten, bevindingen, conclusie, aantekeningen, datum
            FROM audit_records
            ORDER BY datetime(datum) ASC, id ASC
            """
        ).fetchall()


def fetch_record(record_id: int, bedrijf: str | None = None) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM audit_records WHERE id = ?",
            (record_id,),
        ).fetchone()


def paragraph_usage_counts(
    exclude_record_id: int | None = None,
    bedrijf: str | None = None,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in fetch_history(bedrijf):
        if exclude_record_id is not None and int(row["id"]) == int(exclude_record_id):
            continue
        raw = row["geselecteerde_paragrafen"]
        try:
            par_ids = json.loads(raw) if raw else []
        except (TypeError, json.JSONDecodeError):
            par_ids = []
        if not isinstance(par_ids, list):
            continue
        for par_id in par_ids:
            key = str(par_id).strip()
            if not key:
                continue
            counts[key] = counts.get(key, 0) + 1
    return counts


def count_records(bedrijf: str | None = None) -> int:
    with connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM audit_records").fetchone()
        return int(row["n"])


def list_archive_tables(bedrijf: str | None = None) -> list[str]:
    with connect() as conn:
        named = conn.execute(
            "SELECT table_name FROM archive_meta ORDER BY created_at DESC, table_name DESC"
        ).fetchall()
        ordered: list[str] = []
        seen: set[str] = set()
        for row in named:
            name = row["table_name"]
            if ARCHIVE_NAME_RE.match(name) and name not in seen:
                ordered.append(name)
                seen.add(name)
        rows = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name LIKE ?
            ORDER BY name DESC
            """,
            (f"{ARCHIVE_PREFIX}%",),
        ).fetchall()
        for row in rows:
            name = row["name"]
            if ARCHIVE_NAME_RE.match(name) and name not in seen:
                ordered.append(name)
                seen.add(name)
    return ordered


def archive_active_table(bedrijf: str | None = None) -> str | None:
    wanted = _norm_bedrijf(bedrijf) or get_db_bedrijf()
    if count_records(wanted) == 0:
        return None

    with connect() as conn:
        archive_name = _unique_archive_name(conn)
        conn.execute(f"CREATE TABLE {archive_name} AS SELECT * FROM {ACTIVE_TABLE}")
        conn.execute(f"DELETE FROM {ACTIVE_TABLE}")
        _register_archive_meta(conn, archive_name, wanted)
    return archive_name


def swap_with_archive(archive_name: str, bedrijf: str | None = None) -> None:
    archive_name = _assert_archive_name(archive_name)
    wanted = _norm_bedrijf(bedrijf) or get_db_bedrijf()

    with connect() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if archive_name not in tables:
            raise ValueError("Geselecteerd archief bestaat niet.")
        if ACTIVE_TABLE not in tables:
            conn.execute(CREATE_SQL)
        _ensure_columns(conn)

        outgoing = _unique_archive_name(conn)
        conn.execute(f"CREATE TABLE {outgoing} AS SELECT * FROM {ACTIVE_TABLE}")
        conn.execute(f"DELETE FROM {ACTIVE_TABLE}")
        dest_cols = [row[1] for row in conn.execute(f"PRAGMA table_info({ACTIVE_TABLE})")]
        src_cols = {row[1] for row in conn.execute(f"PRAGMA table_info({archive_name})")}
        overlap = [c for c in dest_cols if c in src_cols and c != "id"]
        if overlap:
            conn.execute(
                f"""
                INSERT INTO {ACTIVE_TABLE} ({', '.join(overlap)})
                SELECT {', '.join(overlap)} FROM {archive_name}
                """
            )
        conn.execute(f"DROP TABLE {archive_name}")
        conn.execute(f"ALTER TABLE {outgoing} RENAME TO {archive_name}")
        conn.execute("DELETE FROM archive_meta WHERE table_name = ?", (archive_name,))
        _register_archive_meta(conn, archive_name, wanted)


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]
