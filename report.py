"""Generate a professional HTML annex of audit findings."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from typing import Any

CSS = """<style>
  /* Word (MSO) A4, zelfde ordegrootte als 5.2.3 Auditrapport */
  @page {
    size: 210mm 297mm;
    margin: 25mm 18mm 25mm 20mm;
  }
  @page Section1 {
    size: 595.3pt 841.9pt;
    margin: 70.85pt 49.6pt 70.85pt 56.7pt;
    mso-header-margin: 35.4pt;
    mso-footer-margin: 25.6pt;
  }
  div.Section1 { page: Section1; }
  body {
    font-family: Calibri, Arial, Helvetica, sans-serif;
    font-size: 11pt;
    line-height: 115%;
    color: #000000;
    margin: 0;
    padding: 0;
  }
  p {
    font-family: Calibri, Arial, Helvetica, sans-serif;
    font-size: 11pt;
    line-height: 115%;
    margin: 0 0 8pt 0;
    text-align: left;
    hyphens: none;
    -ms-hyphens: none;
    word-spacing: 0;
    mso-hyphenate: none;
  }
  table.grid td p {
    margin: 0 0 6pt 0;
    text-align: left;
  }
  table.grid td p:last-child {
    margin-bottom: 0;
  }
  p.kop1 {
    font-family: Calibri, Arial, Helvetica, sans-serif;
    font-size: 16pt;
    font-weight: bold;
    color: #1F4E79;
    margin: 0 0 10pt 0;
    padding-bottom: 4pt;
    border-bottom: 1pt solid #1F4E79;
    text-align: left;
  }
  p.kop2 {
    font-family: Calibri, Arial, Helvetica, sans-serif;
    font-size: 13pt;
    font-weight: bold;
    color: #1F4E79;
    margin: 16pt 0 6pt 0;
    text-align: left;
  }
  p.kop3 {
    font-family: Calibri, Arial, Helvetica, sans-serif;
    font-size: 11pt;
    font-weight: bold;
    color: #000000;
    margin: 10pt 0 4pt 0;
    text-align: left;
  }
  p.meta {
    font-style: italic;
    color: #404040;
    margin: 0 0 4pt 0;
    text-align: left;
  }
  table.pagina {
    width: 16.4cm;
    max-width: 16.4cm;
    border: none;
    border-collapse: collapse;
  }
  table.pagina td.inhoud {
    width: 16.4cm;
    padding: 0 8pt 0 0;
    vertical-align: top;
  }
  table.grid {
    border-collapse: collapse;
    width: 16.2cm;
    margin: 4pt 0 12pt 0;
    font-family: Calibri, Arial, Helvetica, sans-serif;
    font-size: 11pt;
  }
  table.grid th, table.grid td {
    border: 1pt solid #A0A0A0;
    padding: 4pt 6pt;
    vertical-align: top;
    text-align: left;
  }
  table.grid th {
    background: #1F4E79;
    color: #FFFFFF;
    font-weight: bold;
  }
  td.conclusie {
    width: 90pt;
    font-weight: bold;
    white-space: nowrap;
  }
</style>
"""


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


def _normalize_conclusie(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw or raw == "—":
        return "—"
    return CONCLUSIE_ALIAS.get(raw.lower(), raw)


def _alleen_datum(value: Any) -> str:
    tekst = str(value or "").strip()
    if not tekst:
        return "—"
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", tekst)
    if match:
        return match.group(1)
    match = re.match(r"^(\d{2}-\d{2}-\d{4})", tekst)
    if match:
        return match.group(1)
    if " " in tekst:
        return tekst.split(" ", 1)[0]
    if "T" in tekst:
        return tekst.split("T", 1)[0]
    return tekst


def _parse_json(raw: Any, fallback):
    if raw in (None, ""):
        return fallback
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _sub_sort_key(name: str) -> tuple:
    nums = tuple(int(part) for part in re.findall(r"\d+", name or ""))
    return (nums, name or "")


def _paragraaf_sort_key(par_id: str) -> tuple:
    nums = tuple(int(part) for part in re.findall(r"\d+", par_id or ""))
    return (nums or (10**9,), par_id or "")


def _record_paragraaf_key(rec: dict[str, Any]) -> tuple:
    par_ids = _parse_json(rec.get("geselecteerde_paragrafen"), [])
    if not isinstance(par_ids, list) or not par_ids:
        return ((10**9,), str(rec.get("sub_hoofdstuk") or ""), int(rec.get("id") or 0))
    kleinste = min(_paragraaf_sort_key(str(p)) for p in par_ids)
    return kleinste + (int(rec.get("id") or 0),)


def _html(text: str) -> str:
    ruw = html.escape(str(text or "")).replace("\r\n", "\n").replace("\r", "\n")
    regels = ruw.split("\n")
    stukken = [deel if deel.strip() else "&nbsp;" for deel in regels]
    if not any(deel.replace("&nbsp;", "").strip() for deel in stukken):
        return ""
    return "".join(f'<p style="text-align:left;margin:0 0 6pt 0">{deel}</p>' for deel in stukken)


def _documenten_lijst(docs: Any) -> list[dict[str, str]]:
    if not docs:
        return []
    if isinstance(docs, str):
        parsed = _parse_json(docs, None)
        docs = parsed if isinstance(parsed, list) else []
    if not isinstance(docs, list):
        return []
    rijen: list[dict[str, str]] = []
    for doc in docs:
        if not isinstance(doc, dict):
            tekst = str(doc).strip()
            if tekst:
                rijen.append({"ref": "", "beschrijving": tekst})
            continue
        ref = str(doc.get("ref") or "").strip()
        beschrijving = str(doc.get("beschrijving") or "").strip()
        if ref or beschrijving:
            rijen.append({"ref": ref, "beschrijving": beschrijving})
    return rijen


def _verzamel_documenten(
    records: list[dict[str, Any]], extra: list[dict[str, str]] | None = None
) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, str]] = []
    bronnen: list[Any] = []
    for rec in records:
        bronnen.extend(_documenten_lijst(rec.get("documenten")))
    bronnen.extend(extra or [])
    for doc in bronnen:
        ref = str(doc.get("ref") or "").strip()
        beschrijving = str(doc.get("beschrijving") or "").strip()
        sleutel = (ref.casefold(), beschrijving.casefold())
        if sleutel in seen or (not ref and not beschrijving):
            continue
        seen.add(sleutel)
        result.append({"ref": ref, "beschrijving": beschrijving})

    def _doc_nr(ref: str) -> int:
        match = re.search(r"(\d+)", ref or "")
        return int(match.group(1)) if match else 10**6

    result.sort(key=lambda d: (_doc_nr(d["ref"]), d["ref"], d["beschrijving"]))
    return result


def _findings_rows(raw: Any) -> list[dict[str, str]]:
    data = _parse_json(raw, None)
    rows: list[dict[str, str]] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                rows.append(
                    {
                        "tekst": str(item.get("tekst") or item.get("Bevinding") or "").strip(),
                        "conclusie": _normalize_conclusie(
                            str(item.get("conclusie") or item.get("Conclusie") or "—")
                        ),
                    }
                )
        return rows
    if isinstance(raw, str) and raw.strip() and not raw.strip().startswith(("[", "{")):
        return [{"tekst": raw.strip(), "conclusie": "—"}]
    return []


def _norm_items(par_ids: Any, iso_lookup: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if not isinstance(par_ids, list):
        return items
    for par_id in par_ids:
        key = str(par_id)
        info = iso_lookup.get(key, {})
        items.append(
            {
                "titel": info.get("weergave_titel") or f"§{key}",
                "tekst": info.get("tekst") or "",
            }
        )
    return items


def build_html_report(
    records: list[dict[str, Any]],
    iso_lookup: dict[str, dict[str, str]],
    extra_documenten: list[dict[str, str]] | None = None,
) -> str:
    title = "Bijlage: Overzicht van Auditbevindingen per Normelement"
    if not records:
        body = f"<h1>{html.escape(title)}</h1><p><em>Geen auditrecords beschikbaar.</em></p>"
        return _html_document(title, body)

    ordered = sorted(records, key=_record_paragraaf_key)

    first = ordered[0]
    sessie = first.get("sessie_naam") or "Onbenoemde audit"
    bedrijf = first.get("bedrijf") or "—"
    generated = datetime.now().strftime("%Y-%m-%d")
    documenten = _verzamel_documenten(records, extra_documenten)

    parts = [
        f'<p class="kop1">{html.escape(title)}</p>',
        f'<p class="meta"><strong>Bedrijf:</strong> {html.escape(str(bedrijf))}<br>',
        f"<strong>Audit kenmerk:</strong> {html.escape(str(sessie))}<br>",
        f"<strong>Gegenereerd:</strong> {html.escape(generated)}</p>",
        '<p class="kop2">1. Documenten</p>',
    ]
    if documenten:
        parts.extend(
            [
                '<table class="grid" width="610" cellspacing="0" cellpadding="4">',
                "<thead><tr><th>Referentie</th><th>Document / registratie</th></tr></thead>",
                "<tbody>",
            ]
        )
        for doc in documenten:
            parts.append(
                "<tr>"
                f"<td width=\"120\">{html.escape(doc['ref'] or '—')}</td>"
                f"<td>{html.escape(doc['beschrijving'] or '—')}</td>"
                "</tr>"
            )
        parts.extend(["</tbody>", "</table>"])
    else:
        parts.append("<p><em>Geen documenten geregistreerd.</em></p>")

    parts.append('<p class="kop2">2. Bevindingen</p>')

    for rec in ordered:
        sub = str(rec.get("sub_hoofdstuk") or "—")
        datum = _alleen_datum(rec.get("datum"))
        auditees = str(rec.get("auditees") or "").strip() or "—"
        par_ids = _parse_json(rec.get("geselecteerde_paragrafen"), [])
        if isinstance(par_ids, list):
            par_ids = sorted(par_ids, key=lambda p: _paragraaf_sort_key(str(p)))
        normen = _norm_items(par_ids, iso_lookup)
        findings = _findings_rows(rec.get("bevindingen"))

        parts.extend(
            [
                f'<p class="kop2">{html.escape(sub)}</p>',
                f'<p class="meta"><strong>Datum:</strong> {html.escape(datum)}<br>',
                f"<strong>Auditee(s):</strong> {html.escape(auditees)}</p>",
                '<p class="kop3">Normelementen</p>',
            ]
        )

        if normen:
            for item in normen:
                parts.append(f'<p>{html.escape(item["titel"])}</p>')
        else:
            parts.append("<p><em>Geen paragrafen geselecteerd.</em></p>")

        parts.extend(
            [
                '<p class="kop3">Bevindingen en conclusies</p>',
                '<table class="grid" width="610" cellspacing="0" cellpadding="4">',
                "<thead><tr><th>Bevinding</th><th width=\"90\">Conclusie</th></tr></thead>",
                "<tbody>",
            ]
        )
        if findings:
            for finding in findings:
                parts.append(
                    "<tr>"
                    f"<td>{_html(finding['tekst']) or '—'}</td>"
                    f'<td class="conclusie" width="90">{html.escape(finding["conclusie"])}</td>'
                    "</tr>"
                )
        else:
            parts.append("<tr><td colspan='2'><em>Geen bevindingen geregistreerd.</em></td></tr>")
        parts.extend(["</tbody>", "</table>"])

    return _html_document(title, "\n".join(parts))


def _html_document(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html xmlns:o="urn:schemas-microsoft-com:office:office" '
        'xmlns:w="urn:schemas-microsoft-com:office:word" lang="nl">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta http-equiv="Content-Type" content="text/html; charset=utf-8">\n'
        f"<title>{html.escape(title)}</title>\n"
        "<!--[if gte mso 9]><xml>"
        "<w:WordDocument><w:View>Print</w:View><w:Zoom>100</w:Zoom>"
        "<w:DoNotOptimizeForBrowser/></w:WordDocument></xml><![endif]-->\n"
        f"{CSS}\n"
        "</head>\n"
        "<body>\n"
        '<div class="Section1">\n'
        '<table class="pagina" width="610" cellspacing="0" cellpadding="0">\n'
        '<tr><td class="inhoud">\n'
        f"{body}\n"
        "</td></tr>\n"
        "</table>\n"
        "</div>\n"
        "</body>\n"
        "</html>\n"
    )


def build_md_report(records: list[dict[str, Any]], iso_lookup: dict[str, dict[str, str]]) -> str:
    """Backward-compatible alias; export is HTML."""
    return build_html_report(records, iso_lookup)


def build_txt_report(records: list[dict[str, Any]], iso_lookup: dict[str, dict[str, str]]) -> str:
    """Backward-compatible alias; export is HTML."""
    return build_html_report(records, iso_lookup)
