# AuditApp (ISO 17025)

Streamlit-app voor interne laboratoriumaudits volgens NEN-EN-ISO/IEC 17025.

Auditdata staat in één SQLite-bestand per bedrijf (`audit_database_<bedrijf>.db`).
De kwaliteitsnorm komt uit Excel (`17025.xlsx` of een ander `.xlsx` in dezelfde map).

## Lokaal starten

```powershell
cd C:\Users\dico\lab-audit-app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

## Database uploaden en downloaden

- **Upload database** — kies een `.db`-bestand. Het wordt in de appmap gezet en geopend.
- **Download database** — bewaar de actieve database op je computer.
- **Nieuwe database** — maak een leeg bestand voor een bedrijf.

Op Streamlit Community Cloud is de schijf tijdelijk: na een herstart verdwijnen databases. Download daarom na elke auditsessie, en upload bij de volgende sessie opnieuw.

## Publiceren op Streamlit Community Cloud

1. Zet deze map op GitHub (zonder `.db`-bestanden).
2. Ga naar [https://share.streamlit.io](https://share.streamlit.io) en log in met GitHub.
3. Kies **Create app**.
4. Repository: deze repo · Branch: `main` · Main file path: `app.py`.
5. Kies Python 3.12 als die keuze verschijnt, en klik **Deploy**.
6. Open de app-URL. Maak een nieuwe database of upload een bestaande `.db`.

De app heeft geen geheimen nodig. Zet nooit klantdatabases in GitHub.
