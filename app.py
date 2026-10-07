"""ISO 17025 interne auditapplicatie (Streamlit + SQLite)."""

from __future__ import annotations

import html
import json
import re
import uuid
from pathlib import Path
from typing import Any

import sys

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import db
import iso_loader
import report as audit_report

if not getattr(sys, "frozen", False):
    import importlib

    db = importlib.reload(db)
    iso_loader = importlib.reload(iso_loader)
    audit_report = importlib.reload(audit_report)

DEFAULT_NORM = iso_loader.DEFAULT_NORM
default_excel_naam = iso_loader.default_excel_naam
excel_path_for = iso_loader.excel_path_for
list_excel_bestanden = iso_loader.list_excel_bestanden
load_norm_items = iso_loader.load_norm_items
unique_subchapters = iso_loader.unique_subchapters
build_html_report = audit_report.build_html_report

CONCLUSIES = ["Conform", "Opmerking", "NC 1", "NC 2"]
CONCLUSIE_ALIAS = {
    "afwijking (majeur)": "NC 2",
    "afwijking (mineur)": "NC 1",
    "majeur": "NC 2",
    "mineur": "NC 1",
    "nc2": "NC 2",
    "nc 2": "NC 2",
    "nc1": "NC 1",
    "nc 1": "NC 1",
    "observatie": "Opmerking",
    "opmerking": "Opmerking",
    "conform": "Conform",
}


CONCLUSIE_RANG = {"Conform": 0, "Opmerking": 1, "NC 1": 2, "NC 2": 3}


def _normalize_conclusie(value: str | None) -> str:
    if not value:
        return "Conform"
    raw = value.strip()
    if not raw:
        return "Conform"
    mapped = CONCLUSIE_ALIAS.get(raw.lower())
    if mapped:
        return mapped
    return raw


def _parse_json(raw: Any, fallback):
    if raw in (None, ""):
        return fallback
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _empty_findings() -> list[dict[str, str]]:
    return [_new_finding_row()]


def _new_finding_row(tekst: str = "", conclusie: str = "Conform") -> dict[str, str]:
    return {
        "rid": uuid.uuid4().hex[:8],
        "Bevinding": tekst,
        "Conclusie": _normalize_conclusie(conclusie),
    }


def parse_findings(raw: Any) -> list[dict[str, str]]:
    data = _parse_json(raw, None)
    if isinstance(data, list):
        rows: list[dict[str, str]] = []
        for item in data:
            if isinstance(item, dict):
                tekst = str(item.get("tekst") or item.get("Bevinding") or "").strip()
                conclusie = _normalize_conclusie(str(item.get("conclusie") or item.get("Conclusie") or ""))
                rows.append(_new_finding_row(tekst, conclusie))
        return rows or _empty_findings()
    if isinstance(raw, str) and raw.strip() and not raw.strip().startswith(("{", "[")):
        return [_new_finding_row(raw.strip(), "Conform")]
    return _empty_findings()


def samenvatting_conclusies(raw_bevindingen: Any, fallback: str | None = None) -> str:
    """List conclusions in record order, e.g. Conform/Majeur/Conform."""
    conclusies: list[str] = []
    for row in parse_findings(raw_bevindingen):
        if not str(row.get("Bevinding") or "").strip():
            continue
        conclusies.append(_normalize_conclusie(row.get("Conclusie")))
    if conclusies:
        return "/".join(conclusies)
    return (fallback or "").strip()


def findings_from_editor(value: Any) -> list[dict[str, str]]:
    if value is None:
        return _empty_findings()
    if isinstance(value, pd.DataFrame):
        frame = value
    else:
        frame = pd.DataFrame(value)
    rows: list[dict[str, str]] = []
    for _, row in frame.iterrows():
        tekst = str(row.get("Bevinding") or "").strip()
        conclusie = _normalize_conclusie(str(row.get("Conclusie") or ""))
        if tekst or conclusie != "Conform":
            rows.append(_new_finding_row(tekst, conclusie))
    return rows or _empty_findings()


def findings_to_json(rows: list[dict[str, str]]) -> str:
    payload = [
        {"tekst": row["Bevinding"], "conclusie": row["Conclusie"]}
        for row in rows
        if str(row.get("Bevinding") or "").strip()
    ]
    return json.dumps(payload, ensure_ascii=False)


def rollup_conclusie(rows: list[dict[str, str]]) -> str:
    beste = "Conform"
    for row in rows:
        conclusie = _normalize_conclusie(row.get("Conclusie"))
        if CONCLUSIE_RANG.get(conclusie, 0) > CONCLUSIE_RANG.get(beste, 0):
            beste = conclusie
    return beste


def findings_dataframe(rows: list[dict[str, str]] | None) -> pd.DataFrame:
    data = rows or _empty_findings()
    return pd.DataFrame(data, columns=["Bevinding", "Conclusie"])


def render_findings_editor(*, fullscreen: bool, key: str) -> None:
    rows = st.session_state.findings_rows or _empty_findings()
    if not any(row.get("rid") for row in rows):
        for row in rows:
            row["rid"] = uuid.uuid4().hex[:8]
    hoogte = 280 if fullscreen else 136
    kop_b, kop_c, kop_x = st.columns([6.2, 1.7, 0.5])
    with kop_b:
        st.caption("Bevinding  ·  Enter = nieuwe alinea  ·  Ctrl+Enter = volgende cel")
    with kop_c:
        st.caption("Conclusie")
    with kop_x:
        st.caption("")

    bijgewerkt: list[dict[str, str]] = []
    verwijder_id = None
    for row in rows:
        rid = row.get("rid") or uuid.uuid4().hex[:8]
        tekst_key = f"{key}_t_{rid}"
        conc_key = f"{key}_c_{rid}"
        seed_widget(tekst_key, row.get("Bevinding") or "")
        seed_widget(conc_key, _normalize_conclusie(row.get("Conclusie")))
        opties = list(CONCLUSIES)
        huidig = _normalize_conclusie(st.session_state.get(conc_key) or row.get("Conclusie"))
        if huidig and huidig not in opties:
            opties.append(huidig)
        col_b, col_c, col_x = st.columns([6.2, 1.7, 0.5], vertical_alignment="top")
        with col_b:
            tekst = st.text_area(
                "Bevinding",
                key=tekst_key,
                height=hoogte,
                label_visibility="collapsed",
                placeholder="Typ de bevinding. Enter voor een nieuwe alinea.",
            )
        with col_c:
            conclusie = st.selectbox(
                "Conclusie",
                options=opties,
                key=conc_key,
                label_visibility="collapsed",
                accept_new_options=True,
            )
        with col_x:
            if st.button("✕", key=f"{key}_x_{rid}", help="Verwijder deze bevinding"):
                verwijder_id = rid
        bijgewerkt.append(
            {"rid": rid, "Bevinding": tekst or "", "Conclusie": _normalize_conclusie(conclusie)}
        )

    if verwijder_id:
        over = [row for row in bijgewerkt if row["rid"] != verwijder_id]
        st.session_state.findings_rows = over or _empty_findings()
        st.rerun()

    st.session_state.findings_rows = bijgewerkt
    if st.button("Bevinding toevoegen", key=f"{key}_add"):
        st.session_state.findings_rows = bijgewerkt + [_new_finding_row()]
        st.rerun()


def _huidig_record_id() -> int | None:
    if st.session_state.edit_mode and st.session_state.edit_record_id:
        return int(st.session_state.edit_record_id)
    return None


def _doc_nummer(ref: str) -> int:
    match = re.search(r"(\d+)", ref or "")
    return int(match.group(1)) if match else 0


def _hoogste_doc_nummer(documenten: list[Any]) -> int:
    hoogste = 0
    for doc in documenten:
        if isinstance(doc, dict):
            hoogste = max(hoogste, _doc_nummer(str(doc.get("ref") or "")))
    return hoogste


def _volgend_doc_nummer(
    bedrijf: str,
    extra: list[dict[str, str]] | None = None,
    *,
    zonder_huidige_registratie: bool = False,
) -> int:
    """Next [DOC-xx] across every record of this audit, plus the open registration."""
    hoogste = 0
    overslaan = _huidig_record_id()
    if db.get_db_path():
        for record in db.fetch_history(bedrijf):
            if overslaan is not None and int(record["id"]) == overslaan:
                continue
            docs = _parse_json(record["documenten"], [])
            if isinstance(docs, list):
                hoogste = max(hoogste, _hoogste_doc_nummer(docs))
        hoogste = max(hoogste, _hoogste_doc_nummer([dict(row) for row in db.fetch_retained_documents()]))
    if not zonder_huidige_registratie:
        hoogste = max(hoogste, _hoogste_doc_nummer(st.session_state.temp_docs))
    hoogste = max(hoogste, _hoogste_doc_nummer(extra or []))
    sessie_hoog = int(st.session_state.get("doc_counter", 1)) - 1
    return max(hoogste, sessie_hoog) + 1


def _audit_document_rijen(bedrijf: str) -> list[dict[str, Any]]:
    """All documents of the active audit, current registration included once."""
    overslaan = _huidig_record_id()
    rijen: list[dict[str, Any]] = []
    if db.get_db_path():
        for record in db.fetch_history(bedrijf):
            record_id = int(record["id"])
            if overslaan is not None and record_id == overslaan:
                continue
            docs = _parse_json(record["documenten"], [])
            if not isinstance(docs, list):
                continue
            label = f"#{record_id} · {record['sub_hoofdstuk'] or ''}".strip(" ·")
            for index, doc in enumerate(docs):
                if not isinstance(doc, dict):
                    continue
                rijen.append(
                    {
                        "ref": str(doc.get("ref") or "").strip(),
                        "beschrijving": str(doc.get("beschrijving") or "").strip(),
                        "record_id": record_id,
                        "retained_id": None,
                        "index": index,
                        "huidig": False,
                        "label": label,
                    }
                )
        for retained in db.fetch_retained_documents():
            rijen.append(
                {
                    "ref": str(retained["ref"] or "").strip(),
                    "beschrijving": str(retained["beschrijving"] or "").strip(),
                    "record_id": None,
                    "retained_id": int(retained["id"]),
                    "index": int(retained["id"]),
                    "huidig": False,
                    "label": "Documentenlijst",
                }
            )
    for index, doc in enumerate(st.session_state.temp_docs):
        if not isinstance(doc, dict):
            continue
        rijen.append(
            {
                "ref": str(doc.get("ref") or "").strip(),
                "beschrijving": str(doc.get("beschrijving") or "").strip(),
                "record_id": None,
                "retained_id": None,
                "index": index,
                "huidig": True,
                "label": "Deze registratie",
            }
        )
    rijen.sort(
        key=lambda rij: (
            _doc_nummer(str(rij["ref"])) or 10**6,
            0 if rij["huidig"] else 1,
            int(rij["record_id"] or 0),
            int(rij["index"]),
        )
    )
    return rijen


def genereer_document_ref(naam: str, bedrijf: str) -> None:
    naam = (naam or "").strip()
    if not naam:
        return
    nummer = _volgend_doc_nummer(bedrijf)
    st.session_state.temp_docs.append({"ref": f"[DOC-{nummer:02d}]", "beschrijving": naam})
    st.session_state.doc_counter = nummer + 1
    st.session_state.doc_input_nonce = int(st.session_state.get("doc_input_nonce", 0)) + 1
    st.rerun()


def _schrijf_audit_documenten(rijen: list[dict[str, Any]], nieuw: str, bedrijf: str) -> None:
    """Save edits back onto each record. New names belong to the open registration."""
    overslaan = _huidig_record_id()
    per_record: dict[int, dict[int, dict[str, Any]]] = {}
    huidig: dict[int, dict[str, Any]] = {}
    retained: list[dict[str, Any]] = []
    for rij in rijen:
        if rij.get("huidig"):
            huidig[int(rij["index"])] = rij
        elif rij.get("retained_id") is not None:
            retained.append(rij)
        elif rij.get("record_id") is not None:
            per_record.setdefault(int(rij["record_id"]), {})[int(rij["index"])] = rij

    if db.get_db_path():
        db.replace_retained_documents(retained)
        for record in db.fetch_history(bedrijf):
            record_id = int(record["id"])
            if overslaan is not None and record_id == overslaan:
                continue
            edits = per_record.get(record_id)
            if not edits:
                continue
            origineel = _parse_json(record["documenten"], [])
            if not isinstance(origineel, list):
                origineel = []
            bijgewerkt: list[dict[str, str]] = []
            for index, doc in enumerate(origineel):
                if not isinstance(doc, dict):
                    continue
                rij = edits.get(index)
                if rij is None:
                    bijgewerkt.append(
                        {
                            "ref": str(doc.get("ref") or "").strip(),
                            "beschrijving": str(doc.get("beschrijving") or "").strip(),
                        }
                    )
                    continue
                if rij.get("verwijderen"):
                    continue
                ref = str(rij.get("ref") or "").strip()
                beschrijving = str(rij.get("beschrijving") or "").strip()
                if ref or beschrijving:
                    bijgewerkt.append({"ref": ref, "beschrijving": beschrijving})
            db.update_documenten(record_id, bedrijf, json.dumps(bijgewerkt, ensure_ascii=False))

    nieuwe_huidige: list[dict[str, str]] = []
    for index, doc in enumerate(st.session_state.temp_docs):
        if not isinstance(doc, dict):
            continue
        rij = huidig.get(index)
        if rij is None:
            nieuwe_huidige.append(
                {
                    "ref": str(doc.get("ref") or "").strip(),
                    "beschrijving": str(doc.get("beschrijving") or "").strip(),
                }
            )
            continue
        if rij.get("verwijderen"):
            continue
        ref = str(rij.get("ref") or "").strip()
        beschrijving = str(rij.get("beschrijving") or "").strip()
        if ref or beschrijving:
            nieuwe_huidige.append({"ref": ref, "beschrijving": beschrijving})

    naam = (nieuw or "").strip()
    if naam:
        nummer = _volgend_doc_nummer(bedrijf, nieuwe_huidige, zonder_huidige_registratie=True)
        nieuwe_huidige.append({"ref": f"[DOC-{nummer:02d}]", "beschrijving": naam})
        st.session_state.doc_counter = nummer + 1
    st.session_state.temp_docs = nieuwe_huidige


def init_state() -> None:
    defaults = {
        "widget_nonce": 0,
        "doc_input_nonce": 0,
        "auditee_input_nonce": 0,
        "bedrijf": "",
        "sessie_naam": "",
        "auditee_lijst": [],
        "edit_mode": False,
        "edit_record_id": None,
        "gekozen_sub": None,
        "pending_checked": set(),
        "temp_docs": [],
        "bevindingen": "",
        "conclusie": "Conform",
        "aantekeningen": "",
        "findings_rows": None,
        "findings_fullscreen": False,
        "edit_auditees": [],
        "doc_counter": 1,
        "doc_audit_nonce": 0,
        "pending_auditee_select": [],
        "last_selected_items": [],
        "last_auditees": [],
        "auditor_unlocked": False,
        "company_nonce": 0,
        "hist_selected_id": None,
        "kwaliteitsnorm": DEFAULT_NORM,
        "db_path": "",
        "db_upload_hash": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if not st.session_state.findings_rows:
        st.session_state.findings_rows = _empty_findings()


def enter_findings_fullscreen() -> None:
    st.session_state.findings_fullscreen = True
    st.query_params["fs"] = "1"
    st.rerun()


def exit_findings_fullscreen() -> None:
    st.session_state.findings_fullscreen = False
    params = {key: value for key, value in st.query_params.items() if key != "fs"}
    st.query_params.clear()
    st.query_params.update(params)
    st.rerun()


def bind_findings_keyboard() -> None:
    components.html(
        """
        <script>
        (function() {
          const p = window.parent;
          const d = p.document;
          function nextCell(fromEl) {
            const row = fromEl.closest('[data-testid="stHorizontalBlock"]');
            if (!row) return;
            const select = row.querySelector('[data-baseweb="select"] input, [data-baseweb="select"] div[role="combobox"]');
            if (select) { select.focus(); return; }
            const nextRow = row.parentElement && row.parentElement.nextElementSibling;
            if (nextRow) {
              const nextTa = nextRow.querySelector('textarea');
              if (nextTa) nextTa.focus();
            }
          }
          if (!d.body.dataset.findingsKeys) {
            d.body.dataset.findingsKeys = '1';
            d.addEventListener('keydown', function(e) {
              const ta = e.target;
              if (!ta || ta.tagName !== 'TEXTAREA') return;
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                e.stopPropagation();
                nextCell(ta);
              }
            }, true);
          }
        })();
        </script>
        """,
        height=1,
    )


def _aantekeningen_waarde() -> str:
    sleutel = f"aantekeningen_{st.session_state.get('widget_nonce', 0)}"
    if sleutel in st.session_state:
        return str(st.session_state[sleutel] or "")
    return str(st.session_state.get("aantekeningen") or "")


def save_current_record(
    geselecteerde_items: list[dict[str, str]],
    auditees_gekozen: list[str],
    gekozen_sub: str,
    actief_bedrijf: str,
) -> None:
    if not actief_bedrijf:
        st.error("Open of maak eerst een database.")
        return
    if not (st.session_state.sessie_naam or "").strip():
        st.error("Vul bovenaan een audit kenmerk / sessienaam in.")
        return
    if not geselecteerde_items:
        st.error("Selecteer minimaal één paragraaf.")
        return
    rows = findings_from_editor(st.session_state.findings_rows)
    payload = {
        "bedrijf": actief_bedrijf,
        "sessie_naam": st.session_state.sessie_naam.strip(),
        "sub_hoofdstuk": gekozen_sub,
        "geselecteerde_paragrafen": json.dumps(
            [item["paragraaf_id"] for item in geselecteerde_items],
            ensure_ascii=False,
        ),
        "auditees": ", ".join(auditees_gekozen) if auditees_gekozen else "",
        "documenten": json.dumps(st.session_state.temp_docs, ensure_ascii=False),
        "bevindingen": findings_to_json(rows),
        "conclusie": rollup_conclusie(rows),
        "aantekeningen": _aantekeningen_waarde(),
    }
    try:
        if st.session_state.edit_mode and st.session_state.edit_record_id:
            db.update_record(int(st.session_state.edit_record_id), payload)
            st.toast(f"Record #{st.session_state.edit_record_id} bijgewerkt.")
        else:
            new_id = db.insert_record(payload)
            st.toast(f"Record #{new_id} opgeslagen.")
        st.session_state.findings_fullscreen = False
        params = {key: value for key, value in st.query_params.items() if key != "fs"}
        st.query_params.clear()
        st.query_params.update(params)
        clear_invoer(keep_sessie=True)
        st.rerun()
    except Exception as exc:
        st.error(f"Opslaan mislukt: {exc}")


def bump_form_widgets() -> None:
    st.session_state.widget_nonce = int(st.session_state.widget_nonce) + 1


def load_history_record(record_id: int, actief_bedrijf: str) -> None:
    geladen = db.fetch_record(int(record_id), actief_bedrijf)
    if not geladen:
        st.error("Record niet gevonden.")
        return
    par_ids = [str(p) for p in _parse_json(geladen["geselecteerde_paragrafen"], [])]
    docs = _parse_json(geladen["documenten"], [])
    auditees = [
        deel.strip()
        for deel in str(geladen["auditees"] or "").split(",")
        if deel.strip()
    ]
    for naam in auditees:
        if naam not in st.session_state.auditee_lijst:
            st.session_state.auditee_lijst.append(naam)
    st.session_state.edit_mode = True
    st.session_state.edit_record_id = int(geladen["id"])
    st.session_state.sessie_naam = geladen["sessie_naam"] or ""
    st.session_state.gekozen_sub = geladen["sub_hoofdstuk"]
    st.session_state.pending_checked = set(par_ids)
    st.session_state.temp_docs = docs if isinstance(docs, list) else []
    st.session_state.findings_rows = parse_findings(geladen["bevindingen"])
    st.session_state.conclusie = _normalize_conclusie(geladen["conclusie"])
    try:
        st.session_state.aantekeningen = str(geladen["aantekeningen"] or "")
    except (IndexError, KeyError):
        st.session_state.aantekeningen = ""
    st.session_state.pending_auditee_select = auditees
    bump_form_widgets()
    st.rerun()


def apply_sessie_voor_bedrijf(bedrijf: str, *, reset_form: bool = False) -> None:
    """Fill audit kenmerk from stored records and refresh the input widget."""
    if reset_form:
        st.session_state.edit_mode = False
        st.session_state.edit_record_id = None
        st.session_state.pending_checked = set()
        st.session_state.temp_docs = []
        st.session_state.bevindingen = ""
        st.session_state.conclusie = "Conform"
        st.session_state.aantekeningen = ""
        st.session_state.findings_rows = _empty_findings()
        st.session_state.edit_auditees = []
        st.session_state.pending_auditee_select = []
        st.session_state.doc_input_nonce = int(st.session_state.get("doc_input_nonce", 0)) + 1
    if db.get_db_path():
        st.session_state.auditee_lijst = db.collect_auditees()
        st.session_state.sessie_naam = db.suggest_sessie_naam(bedrijf) if bedrijf else ""
    else:
        st.session_state.auditee_lijst = []
        st.session_state.sessie_naam = ""
    bump_form_widgets()
    st.rerun()


def open_company_database(path: Path, *, reset_form: bool = True) -> None:
    db.set_db_path(path)
    db.init_db()
    bedrijf = db.get_db_bedrijf() or db.bedrijf_from_filename(path)
    if bedrijf:
        db.set_db_bedrijf(bedrijf)
    st.session_state.db_path = str(path.resolve())
    st.session_state.bedrijf = bedrijf
    apply_sessie_voor_bedrijf(bedrijf, reset_form=reset_form)


def _auditee_select_key() -> str:
    return f"auditees_{st.session_state.widget_nonce}"


def hernoem_auditee(oud: str, nieuw: str) -> None:
    oud, nieuw = oud.strip(), nieuw.strip()
    if not oud or not nieuw or oud == nieuw:
        return
    if nieuw in st.session_state.auditee_lijst:
        st.warning(f"'{nieuw}' staat al in de lijst.")
        return
    st.session_state.auditee_lijst = [nieuw if naam == oud else naam for naam in st.session_state.auditee_lijst]
    st.session_state.pending_auditee_select = [
        nieuw if naam == oud else naam for naam in st.session_state.pending_auditee_select
    ]
    st.session_state.last_auditees = [
        nieuw if naam == oud else naam for naam in st.session_state.get("last_auditees", [])
    ]
    sleutel = _auditee_select_key()
    if sleutel in st.session_state:
        huidig = st.session_state[sleutel]
        if isinstance(huidig, list):
            st.session_state[sleutel] = [nieuw if naam == oud else naam for naam in huidig]
    st.rerun()


def verwijder_auditee(naam: str) -> None:
    naam = naam.strip()
    st.session_state.auditee_lijst = [item for item in st.session_state.auditee_lijst if item != naam]
    st.session_state.pending_auditee_select = [
        item for item in st.session_state.pending_auditee_select if item != naam
    ]
    st.session_state.last_auditees = [
        item for item in st.session_state.get("last_auditees", []) if item != naam
    ]
    sleutel = _auditee_select_key()
    if sleutel in st.session_state:
        huidig = st.session_state[sleutel]
        if isinstance(huidig, list):
            st.session_state[sleutel] = [item for item in huidig if item != naam]
    st.rerun()


def seed_widget(key: str, value: Any) -> None:
    """Set widget state only before the widget exists (key-swapping safe)."""
    if key not in st.session_state:
        st.session_state[key] = value


def clear_invoer(keep_sessie: bool = True, keep_bedrijf: bool = True) -> None:
    if not keep_sessie:
        st.session_state.sessie_naam = ""
    if not keep_bedrijf:
        st.session_state.bedrijf = ""
        st.session_state.company_nonce = int(st.session_state.get("company_nonce", 0)) + 1
    st.session_state.edit_mode = False
    st.session_state.edit_record_id = None
    st.session_state.pending_checked = set()
    st.session_state.temp_docs = []
    st.session_state.bevindingen = ""
    st.session_state.conclusie = "Conform"
    st.session_state.aantekeningen = ""
    st.session_state.findings_rows = _empty_findings()
    st.session_state.edit_auditees = []
    st.session_state.pending_auditee_select = []
    bump_form_widgets()
    st.session_state.doc_input_nonce = int(st.session_state.doc_input_nonce) + 1


st.set_page_config(
    page_title="AuditApp",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


@st.dialog("Documenten van deze audit", width="large", on_dismiss="rerun")
def show_documenten_dialog(bedrijf: str) -> None:
    st.caption(
        "Doorlopend genummerd over de hele audit. "
        "Een nieuw document hoort bij de registratie die u nu invult. Klaar bewaart de lijst."
    )
    st.markdown(
        """
        <style>
        div[data-testid="stDialog"] [data-testid="stFormSubmitButton"] {
            display: block !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    nonce = int(st.session_state.get("doc_audit_nonce", 0))
    bronnen = _audit_document_rijen(bedrijf)

    with st.form("documenten_venster_form", border=False):
        if not bronnen:
            st.info("Nog geen documenten in deze audit.")
        else:
            kop_ref, kop_besch, kop_bij, _kop_del = st.columns([1.5, 4.2, 2.6, 1.2])
            kop_ref.caption("Referentie")
            kop_besch.caption("Document / registratie")
            kop_bij.caption("Registratie")
        rijen: list[dict[str, Any]] = []
        for bron in bronnen:
            sleutel = f"{bron.get('record_id')}_{bron.get('retained_id')}_{bron['index']}_{int(bron['huidig'])}"
            ref_col, besch_col, bij_col, del_col = st.columns(
                [1.5, 4.2, 2.6, 1.2],
                vertical_alignment="center",
            )
            with ref_col:
                ref = st.text_input(
                    "Referentie",
                    value=str(bron["ref"]),
                    key=f"docdlg_ref_{nonce}_{sleutel}",
                    label_visibility="collapsed",
                )
            with besch_col:
                beschrijving = st.text_input(
                    "Document / registratie",
                    value=str(bron["beschrijving"]),
                    key=f"docdlg_besch_{nonce}_{sleutel}",
                    label_visibility="collapsed",
                )
            with bij_col:
                st.caption(str(bron["label"]))
            with del_col:
                verwijderen = st.checkbox("Verwijder", key=f"docdlg_del_{nonce}_{sleutel}")
            rijen.append(
                {
                    "ref": ref or "",
                    "beschrijving": beschrijving or "",
                    "verwijderen": bool(verwijderen),
                    "record_id": bron["record_id"],
                    "retained_id": bron.get("retained_id"),
                    "index": bron["index"],
                    "huidig": bron["huidig"],
                }
            )
        nieuw_col, toevoeg_col = st.columns([5.5, 1.6], vertical_alignment="bottom")
        with nieuw_col:
            nieuw = st.text_input(
                "Nieuw document",
                key=f"docdlg_nieuw_{nonce}",
                placeholder="Documentnaam, wordt het volgende [DOC-xx]",
                label_visibility="collapsed",
            )
        with toevoeg_col:
            toevoegen = st.form_submit_button("Toevoegen", width="stretch")
        klaar = st.form_submit_button("Klaar", type="primary")

    if toevoegen or klaar:
        _schrijf_audit_documenten(rijen, nieuw or "", bedrijf)
        st.session_state.doc_audit_nonce = nonce + 1
        if klaar:
            st.rerun()
        st.rerun(scope="fragment")


def open_documenten_venster(bedrijf: str) -> None:
    st.session_state.doc_audit_nonce = int(st.session_state.get("doc_audit_nonce", 0)) + 1
    show_documenten_dialog(bedrijf)


@st.dialog("Normtekst", width="large")
def show_normtekst_dialog(titel: str, tekst: str) -> None:
    st.markdown(
        f"<h3 style='margin:0 0 0.8rem 0;font-size:1.5rem'>{html.escape(titel)}</h3>"
        f"<div style='font-size:1.35rem;line-height:1.7;white-space:pre-wrap'>{html.escape(tekst or 'Geen normtekst beschikbaar.')}</div>",
        unsafe_allow_html=True,
    )

init_state()
db.migrate_legacy_databases()
if st.session_state.db_path and Path(st.session_state.db_path).exists():
    db.set_db_path(st.session_state.db_path)
    db.init_db()
    if not st.session_state.auditee_lijst:
        st.session_state.auditee_lijst = db.collect_auditees()
    if not st.session_state.bedrijf:
        st.session_state.bedrijf = db.get_db_bedrijf()
elif not st.session_state.db_path:
    apb = db.db_path_for("APB")
    if apb.exists():
        db.set_db_path(apb)
        db.init_db()
        st.session_state.db_path = str(apb.resolve())
        st.session_state.bedrijf = db.get_db_bedrijf() or "APB"
        st.session_state.auditee_lijst = db.collect_auditees()
        if not st.session_state.sessie_naam:
            st.session_state.sessie_naam = db.suggest_sessie_naam("APB")

if st.query_params.get("fs") == "1":
    st.session_state.findings_fullscreen = True


@st.cache_data(show_spinner=False)
def cached_norm_items(excel_path: str, mtime: float) -> list[dict[str, str]]:
    return load_norm_items(Path(excel_path))


nonce = st.session_state.widget_nonce
company_nonce = st.session_state.company_nonce

st.markdown(
    """
    <style>
    div[data-testid="stPopover"] button { font-size: 0.8rem; color: #888; }
    div[data-testid="stFormSubmitButton"] { display: none; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Kwaliteitsnorm en database
# ---------------------------------------------------------------------------
norm_col, db_col, nieuw_col = st.columns([2.2, 3.4, 1.8], vertical_alignment="bottom")
with norm_col:
    beschikbare_normen = list_excel_bestanden()
    if not beschikbare_normen:
        st.error("Geen Excel-bestanden gevonden in de projectmap.")
        st.stop()
    huidige_norm = Path(str(excel_path_for(st.session_state.kwaliteitsnorm))).name
    if huidige_norm not in beschikbare_normen:
        huidige_norm = default_excel_naam(beschikbare_normen)
    st.session_state.kwaliteitsnorm = huidige_norm
    gekozen_norm = st.selectbox(
        "Kwaliteitsnorm",
        options=beschikbare_normen,
        index=beschikbare_normen.index(huidige_norm),
        key="excel_norm_select",
        help="Alle .xlsx-bestanden in de projectmap. Het gekozen bestand wordt als normlijst geladen.",
        label_visibility="collapsed",
    )
    if gekozen_norm != st.session_state.kwaliteitsnorm:
        st.session_state.kwaliteitsnorm = gekozen_norm
        st.session_state.gekozen_sub = None
        st.session_state.pending_checked = set()
        bump_form_widgets()
        st.rerun()

db_bestanden = db.list_database_files()
db_namen = [pad.name for pad in db_bestanden]
huidige_db = Path(st.session_state.db_path).name if st.session_state.db_path else ""
with db_col:
    db_opties = ["— Selecteer of blader een database —"] + db_namen
    db_index = db_opties.index(huidige_db) if huidige_db in db_opties else 0
    gekozen_db = st.selectbox(
        "Database",
        options=db_opties,
        index=db_index,
        key="db_select",
        help="Bestaande audit_database_bedrijf.db-bestanden in de appmap.",
        label_visibility="collapsed",
    )
    if gekozen_db != db_opties[0]:
        doel = next((pad for pad in db_bestanden if pad.name == gekozen_db), None)
        if doel is not None and str(doel.resolve()) != str(st.session_state.db_path or ""):
            open_company_database(doel, reset_form=True)

with nieuw_col:
    with st.popover("Nieuwe database"):
        nieuwe_naam = st.text_input("Bedrijfsnaam", key="db_nieuw_naam")
        if st.button("Aanmaken", width="stretch"):
            try:
                doel = db.create_company_database(nieuwe_naam)
                open_company_database(doel, reset_form=True)
            except Exception as exc:
                st.error(str(exc))

upload_col, download_col = st.columns([3.2, 1.6], vertical_alignment="bottom")
with upload_col:
    upload = st.file_uploader(
        "Upload database",
        type=["db", "sqlite"],
        key="db_upload",
        help="Kies een .db-bestand. Het wordt gekopieerd naar de appmap. Op Streamlit Cloud is dit de manier om je auditdata terug te zetten.",
    )
with download_col:
    db_pad = Path(st.session_state.db_path) if st.session_state.db_path else None
    if db_pad and db_pad.exists():
        try:
            db_bytes = db.export_database_bytes(db_pad)
        except Exception:
            db_bytes = db_pad.read_bytes()
        st.download_button(
            "Download database",
            data=db_bytes,
            file_name=db_pad.name,
            mime="application/octet-stream",
            width="stretch",
            help="Bewaar de huidige database lokaal. Op Streamlit Cloud verdwijnen bestanden bij herstart van de app.",
        )
    else:
        st.button("Download database", disabled=True, width="stretch")

if upload is not None:
    kenmerk = f"{upload.name}:{upload.size}"
    if st.session_state.db_upload_hash != kenmerk:
        try:
            doel = db.import_database_bytes(upload.getvalue(), upload.name)
            st.session_state.db_upload_hash = kenmerk
            open_company_database(doel, reset_form=True)
        except Exception as exc:
            st.error(f"Database openen mislukt: {exc}")

actief_bedrijf = (st.session_state.bedrijf or "").strip()
if db.get_db_path() and actief_bedrijf != st.session_state.get("context_bedrijf"):
    st.session_state.context_bedrijf = actief_bedrijf
    if not st.session_state.auditee_lijst:
        st.session_state.auditee_lijst = db.collect_auditees()
    if not st.session_state.sessie_naam:
        st.session_state.sessie_naam = db.suggest_sessie_naam(actief_bedrijf)

archives = db.list_archive_tables(actief_bedrijf) if db.get_db_path() else []
archief_col, open_col = st.columns([6, 1.2], vertical_alignment="bottom")
with archief_col:
    gekozen_archief = st.selectbox(
        "Gearchiveerde tabellen",
        options=["— Selecteer archief —"] + archives,
        index=0,
        disabled=not bool(db.get_db_path()),
        label_visibility="collapsed",
    )
with open_col:
    if st.button("Open archief", width="stretch", disabled=not bool(db.get_db_path())):
        if not db.get_db_path():
            st.warning("Open eerst een database.")
        elif gekozen_archief == "— Selecteer archief —":
            st.warning("Kies eerst een archieftabel.")
        else:
            try:
                db.swap_with_archive(gekozen_archief, actief_bedrijf)
                clear_invoer(keep_sessie=False, keep_bedrijf=True)
                st.session_state.sessie_naam = db.suggest_sessie_naam(actief_bedrijf)
                st.session_state.context_bedrijf = actief_bedrijf
                bump_form_widgets()
                st.toast(f"Archief {gekozen_archief} is nu actief.")
                st.rerun()
            except Exception as exc:
                st.error(f"Archief openen mislukt: {exc}")

excel_path = excel_path_for(st.session_state.kwaliteitsnorm)
try:
    norm_items = cached_norm_items(str(excel_path), excel_path.stat().st_mtime)
except FileNotFoundError:
    st.error(f"Het bestand `{excel_path.name}` ontbreekt in de projectmap.")
    st.stop()
except Exception as exc:
    st.error(f"Fout bij inlezen van {excel_path.name}: {exc}")
    st.stop()

if not norm_items:
    st.error(f"{excel_path.name} bevat geen bruikbare normregels.")
    st.stop()

iso_lookup = {item["paragraaf_id"]: item for item in norm_items}
subhoofdstukken = unique_subchapters(norm_items)

st.title("AuditApp")
db_label = Path(st.session_state.db_path).name if st.session_state.db_path else "geen database"
st.caption(f"Lokale auditregistratie — {st.session_state.kwaliteitsnorm} — {db_label}.")
if not db.get_db_path():
    st.info("Selecteer, upload of maak een database om verder te gaan.")
    st.stop()

# ---------------------------------------------------------------------------
# Kop: kenmerk, auditees
# ---------------------------------------------------------------------------
sessie_veld, nieuwe_audit_col, auditee_veld, beheer_col = st.columns(
    [3.2, 1.7, 3.2, 1.6],
    vertical_alignment="bottom",
)
with sessie_veld:
    sessie_key = f"sessie_{nonce}"
    seed_widget(sessie_key, st.session_state.sessie_naam)
    st.text_input(
        "Audit kenmerk / sessienaam",
        placeholder="Bijv. Interne audit lab 2026-Q3",
        key=sessie_key,
    )
    st.session_state.sessie_naam = st.session_state[sessie_key]
with nieuwe_audit_col:
    if st.button("Start NIEUWE Audit", type="secondary", width="stretch"):
        if not db.get_db_path():
            st.error("Open of maak eerst een database.")
        else:
            try:
                archived = db.archive_active_table(actief_bedrijf)
                clear_invoer(keep_sessie=False, keep_bedrijf=True)
                if archived:
                    st.toast(f"Audit voor {actief_bedrijf} gearchiveerd als {archived}")
                else:
                    st.toast("Invoerscherm gereset. Er was nog niets om te archiveren.")
                st.rerun()
            except Exception as exc:
                st.error(f"Nieuwe audit starten mislukt: {exc}")
with auditee_veld:
    nieuw_auditee = st.text_input(
        "Auditee toevoegen aan centrale keuzelijst",
        placeholder="Typ een naam en druk op Enter",
        key=f"auditee_invoer_{st.session_state.get('auditee_input_nonce', 0)}",
    )
with beheer_col:
    with st.popover("Beheer auditee(s)"):
        if not st.session_state.auditee_lijst:
            st.caption("Nog geen auditee(s) in de centrale lijst.")
        else:
            gekozen_auditee = st.selectbox(
                "Kies auditee",
                options=st.session_state.auditee_lijst,
                key="auditee_beheer_keuze",
            )
            naam_key = f"auditee_beheer_naam_{gekozen_auditee}"
            seed_widget(naam_key, gekozen_auditee)
            nieuwe_naam = st.text_input("Nieuwe naam", key=naam_key)
            wijzig_col, verwijder_col = st.columns(2)
            with wijzig_col:
                if st.button("Wijzig naam", width="stretch"):
                    hernoem_auditee(gekozen_auditee, nieuwe_naam)
            with verwijder_col:
                if st.button("Verwijder", width="stretch"):
                    verwijder_auditee(gekozen_auditee)

naam = (nieuw_auditee or "").strip()
if naam and naam not in st.session_state.auditee_lijst:
    st.session_state.auditee_lijst.append(naam)
    st.session_state.auditee_input_nonce = int(st.session_state.get("auditee_input_nonce", 0)) + 1
    st.rerun()
_, _, auditee_lijst_col, _ = st.columns([3.2, 1.7, 3.2, 1.6])
with auditee_lijst_col:
    if st.session_state.auditee_lijst:
        st.caption("Centrale lijst: " + " · ".join(st.session_state.auditee_lijst))

if st.session_state.edit_mode and st.session_state.edit_record_id:
    st.warning(
        f"**STATUS: BESTAAND RECORD ID #{st.session_state.edit_record_id} wordt bewerkt.** "
        "Opslaan voert een SQL UPDATE uit."
    )
else:
    st.success("**STATUS: NIEUW RECORD** — opslaan voert een SQL INSERT uit.")

# ---------------------------------------------------------------------------
# Bevindingentabel / drie kolommen
# ---------------------------------------------------------------------------
findings_key = f"findings_{nonce}"
fullscreen = bool(st.session_state.findings_fullscreen)

if fullscreen:
    st.markdown(
        """
        <style>
        textarea {
            font-size: 1.25rem !important;
            line-height: 1.5 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    terug_col, save_col = st.columns([1, 1])
    with terug_col:
        if st.button("Terug naar normale layout", width="stretch"):
            exit_findings_fullscreen()
    geselecteerde_items = list(st.session_state.get("last_selected_items") or [])
    auditees_gekozen = list(st.session_state.get("last_auditees") or [])
    gekozen_sub = st.session_state.gekozen_sub or (subhoofdstukken[0] if subhoofdstukken else "")
    st.subheader("Bevindingen en conclusies")
    if geselecteerde_items:
        st.caption(" · ".join(item["weergave_titel"] for item in geselecteerde_items))
    render_findings_editor(fullscreen=True, key=findings_key)
    bind_findings_keyboard()
    knoptekst = "Update dit record" if st.session_state.edit_mode else "Sla deze registratie op"
    with save_col:
        if st.button(knoptekst, type="primary", width="stretch"):
            save_current_record(geselecteerde_items, auditees_gekozen, gekozen_sub, actief_bedrijf)
else:
    kolom1, kolom2, kolom3 = st.columns([25, 55, 20])

    with kolom1:
        st.subheader("1. Selectie")
        sub_key = f"sub_{nonce}"
        start_sub = st.session_state.gekozen_sub if st.session_state.gekozen_sub in subhoofdstukken else subhoofdstukken[0]
        seed_widget(sub_key, start_sub)
        gekozen_sub = st.selectbox(
            "Sub-hoofdstuk",
            options=subhoofdstukken,
            key=sub_key,
        )
        st.session_state.gekozen_sub = gekozen_sub

        relevante = [item for item in norm_items if item["sub_hoofdstuk"] == gekozen_sub]
        exclude_id = (
            int(st.session_state.edit_record_id)
            if st.session_state.edit_mode and st.session_state.edit_record_id
            else None
        )
        usage_counts = db.paragraph_usage_counts(exclude_id, actief_bedrijf)
        st.caption(
            "Niveau 3 en 4 paragrafen. Grijs + (n×) = al in een ander record van deze audit; opnieuw aanvinken mag."
        )
        geselecteerde_items: list[dict[str, str]] = []
        pending: set[str] = set(st.session_state.pending_checked)

        used_css_rules: list[str] = []
        for item in relevante:
            par_id = item["paragraaf_id"]
            gebruikt = int(usage_counts.get(par_id, 0))
            par_key = f"par_{par_id}_{nonce}"
            seed_widget(par_key, par_id in pending)
            label = item["weergave_titel"]
            if gebruikt:
                label = f"{label} ({gebruikt}×)"
                safe_key = par_key.replace(".", "-")
                used_css_rules.append(
                    f'div[class*="st-key-{par_key}"] label p,'
                    f'div[class*="st-key-{safe_key}"] label p {{ color: #6b7280 !important; }}'
                )
            vink_col, help_col = st.columns([8.6, 1.4], vertical_alignment="center")
            with vink_col:
                aangevinkt = st.checkbox(label, key=par_key)
            with help_col:
                if st.button("?", key=f"normhelp_{par_id}_{nonce}", help="Toon volledige normtekst"):
                    show_normtekst_dialog(item["weergave_titel"], item["tekst"] or "")
            if aangevinkt:
                geselecteerde_items.append(item)

        if used_css_rules:
            st.markdown(
                "<style>" + " ".join(used_css_rules) + "</style>",
                unsafe_allow_html=True,
            )
        st.session_state.last_selected_items = geselecteerde_items

    with kolom2:
        kop2, knop2 = st.columns([4, 1.4])
        with kop2:
            st.subheader("2. Bevindingen")
        with knop2:
            if st.button("Schermvullend", width="stretch"):
                enter_findings_fullscreen()
        if geselecteerde_items:
            st.caption(gekozen_sub + " — " + ", ".join(item["paragraaf_id"] for item in geselecteerde_items))
        else:
            st.caption("Vink links paragrafen aan. Elke rij is één bevinding; voeg rijen toe indien nodig.")
        render_findings_editor(fullscreen=False, key=findings_key)
        bind_findings_keyboard()
        st.caption("Enter = nieuwe alinea in de bevinding. Ctrl+Enter = naar conclusie.")

    with kolom3:
        st.subheader("3. Registratie")
        auditee_key = f"auditees_{nonce}"
        default_auditees = [
            naam
            for naam in st.session_state.pending_auditee_select
            if naam in st.session_state.auditee_lijst
        ]
        seed_widget(auditee_key, default_auditees)
        auditees_gekozen = st.multiselect(
            "Auditee(s)",
            options=st.session_state.auditee_lijst,
            key=auditee_key,
        )
        st.session_state.last_auditees = list(auditees_gekozen)

        st.markdown("**Documenten**")
        if st.button(
            "Alle documenten",
            key="open_documenten_venster",
            width="stretch",
            help="Bekijk en bewerk alle doorlopend genummerde documenten van deze audit",
        ):
            open_documenten_venster(actief_bedrijf)
        with st.form("doc_ref_form", border=False, clear_on_submit=True):
            doc_naam = st.text_input(
                "Document / registratie",
                placeholder="Documentnaam en Enter voor [DOC-xx]",
                key=f"doc_naam_{st.session_state.doc_input_nonce}",
                label_visibility="collapsed",
            )
            doc_enter = st.form_submit_button("Genereer Ref")
        if doc_enter:
            genereer_document_ref(doc_naam, actief_bedrijf)

        if st.session_state.temp_docs:
            for index, document in enumerate(list(st.session_state.temp_docs)):
                tekst_col, del_col = st.columns([4, 1.4])
                with tekst_col:
                    st.markdown(f"`{document['ref']}` {document['beschrijving']}")
                with del_col:
                    if st.button("Verwijder", key=f"del_doc_{nonce}_{index}", width="stretch"):
                        st.session_state.temp_docs.pop(index)
                        st.rerun()

        knoptekst = "Update dit record" if st.session_state.edit_mode else "Sla deze registratie op"
        if st.button(knoptekst, type="primary", width="stretch"):
            save_current_record(geselecteerde_items, auditees_gekozen, gekozen_sub, actief_bedrijf)
        aant_key = f"aantekeningen_{nonce}"
        seed_widget(aant_key, st.session_state.get("aantekeningen") or "")
        st.text_area(
            "Aantekeningen",
            key=aant_key,
            height=136,
            placeholder="Interne aantekeningen bij deze registratie",
        )
        st.session_state.aantekeningen = st.session_state.get(aant_key) or ""

# ---------------------------------------------------------------------------
# Lijst bevindingen & export — altijd gerenderd, zodat tabel-filters blijven staan
# ---------------------------------------------------------------------------
st.divider()
st.header("Lijst bevindingen")

if not db.get_db_path():
    st.info("Selecteer, upload of maak bovenaan een database om bevindingen te zien.")
else:
    records = db.fetch_history(actief_bedrijf)
    if not records:
        st.info("Nog geen opgeslagen auditgegevens in de actieve tabel.")
        if st.button("Maak invoerscherm leeg voor een NIEUW record"):
            clear_invoer(keep_sessie=True)
            st.rerun()
    else:
        weergave = pd.DataFrame(
            [
                {
                    "id": row["id"],
                    "sub_hoofdstuk": row["sub_hoofdstuk"],
                    "paragrafen": ", ".join(
                        str(p) for p in _parse_json(row["geselecteerde_paragrafen"], [])
                    ),
                    "oordeel": samenvatting_conclusies(row["bevindingen"], row["conclusie"]),
                    "auditees": row["auditees"],
                    "datum": row["datum"],
                }
                for row in records
            ]
        )
        st.caption("Vink een rij aan en klik op Open of Verwijder.")
        event = st.dataframe(
            weergave,
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="geschiedenis_tabel",
            column_config={
                "id": st.column_config.NumberColumn("id", width=52),
                "sub_hoofdstuk": st.column_config.TextColumn("sub_hoofdstuk", width="medium"),
                "paragrafen": st.column_config.TextColumn("paragrafen", width="medium"),
                "oordeel": st.column_config.TextColumn("oordeel", width="medium"),
                "auditees": st.column_config.TextColumn("auditee(s)", width="medium"),
                "datum": st.column_config.TextColumn("datum", width="medium"),
            },
        )
        gekozen_rijen = []
        if event is not None and getattr(event, "selection", None) is not None:
            gekozen_rijen = list(event.selection.rows or [])
        if gekozen_rijen:
            st.session_state.hist_selected_id = int(weergave.iloc[gekozen_rijen[0]]["id"])

        laad_col, del_col, leeg_col, export_col = st.columns(4)
        with laad_col:
            if st.button("Open geselecteerd record", type="secondary", width="stretch"):
                gekozen = st.session_state.get("hist_selected_id")
                if not gekozen:
                    st.warning("Vink eerst een rij in de tabel aan.")
                else:
                    load_history_record(int(gekozen), actief_bedrijf)
        with del_col:
            if st.button("Verwijder geselecteerd record", width="stretch"):
                gekozen = st.session_state.get("hist_selected_id")
                if not gekozen:
                    st.warning("Vink eerst een rij in de tabel aan.")
                else:
                    db.delete_record(int(gekozen))
                    if st.session_state.edit_record_id == int(gekozen):
                        clear_invoer(keep_sessie=True)
                    st.session_state.hist_selected_id = None
                    st.toast(f"Record #{int(gekozen)} verwijderd. Documenten blijven in de documentenlijst.")
                    st.rerun()
        with leeg_col:
            if st.button("Maak invoerscherm leeg voor een NIEUW record", width="stretch"):
                clear_invoer(keep_sessie=True)
                st.rerun()

        with export_col:
            extra_docs = [
                {"ref": str(row["ref"] or ""), "beschrijving": str(row["beschrijving"] or "")}
                for row in db.fetch_retained_documents()
            ]
            rapport = build_html_report(
                [dict(row) for row in records],
                iso_lookup,
                extra_documenten=extra_docs,
            )
            kenmerk = (st.session_state.sessie_naam or "audit").strip().replace(" ", "_")
            norm_slug = re.sub(r"[^\w]+", "", st.session_state.kwaliteitsnorm) or "audit"
            st.download_button(
                "Download bijlage (.html)",
                data=rapport.encode("utf-8"),
                file_name=f"{norm_slug}_bevindingen_{kenmerk}.html",
                mime="text/html",
                width="stretch",
            )
