#!/usr/bin/env python3
"""
generate_dashboard.py
=====================
Récupère toutes les soumissions depuis KoboToolbox et régénère le fichier
index.html avec les données fraîches.

Usage :
    python generate_dashboard.py

Variables à adapter si les noms de champs diffèrent dans votre formulaire :
    voir la section « ── MAPPING DES CHAMPS KOBO ── » ci-dessous.
"""

import json
import re
import sys
import os
import math
from datetime import datetime, date
from collections import defaultdict

try:
    import requests
except ImportError:
    print("❌  Le module 'requests' est manquant. Installez-le avec : pip install requests")
    sys.exit(1)

# ══════════════════════════════════════════════════════════════
#  ── CONFIGURATION ──
# ══════════════════════════════════════════════════════════════

KOBO_TOKEN  = os.environ.get("KOBO_TOKEN", "61b732c4aece2695c5c2c392ebd63d6c89740249")
KOBO_UID    = "aL7zP7m8zNmxEcTY6bxobp"
KOBO_SERVER = "https://kf.kobotoolbox.org"
TEMPLATE_FILE = "index_template.html"   # le HTML d'origine (avec les marqueurs)
OUTPUT_FILE   = "index.html"            # fichier de sortie publié sur GitHub Pages

# Couleurs assignées aux staffs (dans l'ordre de découverte)
STAFF_COLORS = [
    "#3b82f6", "#10b981", "#f59e0b", "#ef4444",
    "#8b5cf6", "#06b6d4", "#f97316", "#ec4899", "#84cc16",
    "#14b8a6", "#a855f7", "#fb923c",
]

# ══════════════════════════════════════════════════════════════
#  ── MAPPING DES CHAMPS KOBO ──
#  Adaptez les valeurs de droite si vos noms de champs diffèrent.
# ══════════════════════════════════════════════════════════════

F = {
    # Champ date de la soumission
    "date":         "Date",

    # Identification du commercial
    "staff":        "Nom et Prénoms Staffs",

    # Cible / client visité
    "cible":        "Nom de la Cible / raison sociale",

    # Nature / type de client
    "nature":       "Nature de la cible / raison sociale",

    # Zone géographique
    "zone":         "Zone",
    "zone_op":      "Zone opérationnelle",

    # Type d'action effectuée
    "action":       "Action menée",
    "si_visite":    "Si Visite",
    "si_vente":     "Si vente",

    # Quantités vendues
    "bouteilles":   "Nbre de bouteille livré",
    "cartons_boite":"Nbre de carton livré",

    # Montant financier (FCFA)
    "montant":      "Valeur",

    # Mode de paiement
    "paiement":     "Mode de paiement",

    # Contact / interlocuteur
    "contact":      "Contact du propriétaire",
    "interlocuteur":"Nom de l'Interlocuteur",
    "statut_interl":"Statut de l'interlocuteur",

    # Observation
    "observation":  "Observation / Recommandations",

    # GPS — champs séparés dans ce formulaire
    "gps":          "_geolocation",
    "lat":          "_Localisation_latitude",
    "lon":          "_Localisation_longitude",
}

# Nombre de bouteilles par carton
BOUTEILLES_PAR_CARTON = 12

# ══════════════════════════════════════════════════════════════
#  ── RÉCUPÉRATION DES DONNÉES ──
# ══════════════════════════════════════════════════════════════

def fetch_all_submissions():
    """Télécharge toutes les soumissions en gérant la pagination."""
    headers = {"Authorization": f"Token {KOBO_TOKEN}"}
    url = f"{KOBO_SERVER}/api/v2/assets/{KOBO_UID}/data/?format=json&limit=3000"
    all_results = []
    page = 1

    while url:
        print(f"  📥  Page {page} — {url[:80]}…")
        resp = requests.get(url, headers=headers, timeout=60)
        if resp.status_code == 401:
            print("❌  Token invalide ou expiré. Vérifiez KOBO_TOKEN.")
            sys.exit(1)
        if resp.status_code != 200:
            print(f"❌  Erreur HTTP {resp.status_code} : {resp.text[:200]}")
            sys.exit(1)
        data = resp.json()
        all_results.extend(data.get("results", []))
        url = data.get("next")   # None si dernière page
        page += 1

    print(f"  ✅  {len(all_results)} soumissions récupérées.")
    # Afficher les vrais noms de champs de l'API (pour debug)
    if all_results:
        print("\n  📋  Noms de champs retournés par l'API :")
        for k in sorted(all_results[0].keys()):
            v = all_results[0].get(k)
            if v is not None and str(v).strip() not in ("", "nan", "None"):
                print(f"      {k!r:55s} = {str(v)[:40]!r}")
        print()
    return all_results


# ══════════════════════════════════════════════════════════════
#  ── FONCTIONS UTILITAIRES ──
# ══════════════════════════════════════════════════════════════

def normalize(s):
    """Normalise une clé : minuscules, accents retirés, espaces→underscores."""
    import unicodedata
    s = str(s).lower().strip()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s

# Cache de mapping normalisé, construit à la première soumission
_NORM_CACHE = {}

def get_field(row, *keys):
    """Retourne la première valeur non-vide parmi les clés fournies.
    Cherche d'abord la clé exacte, puis la version normalisée."""
    global _NORM_CACHE

    # Construire le cache normalisé si vide
    if not _NORM_CACHE and row:
        for k in row.keys():
            _NORM_CACHE[normalize(k)] = k

    for k in keys:
        # 1. Correspondance exacte
        v = row.get(k)
        if v is not None and str(v).strip() not in ("", "nan", "None", "N/A"):
            return v
        # 2. Correspondance normalisée
        nk = normalize(k)
        real_key = _NORM_CACHE.get(nk)
        if real_key:
            v = row.get(real_key)
            if v is not None and str(v).strip() not in ("", "nan", "None", "N/A"):
                return v
    return ""

def parse_date(row):
    """Extrait et normalise la date au format YYYY-MM-DD."""
    raw = get_field(row, F["date"], "date_activite", "date", "_submission_time")
    if not raw:
        return ""
    raw = str(raw)
    # ISO datetime → date
    if "T" in raw:
        raw = raw.split("T")[0]
    # format DD/MM/YYYY
    if "/" in raw:
        parts = raw.split("/")
        if len(parts) == 3:
            try:
                return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
            except Exception:
                return ""
    return raw[:10]  # garder les 10 premiers caractères

def parse_float(value, default=0.0):
    try:
        v = float(str(value).replace(",", ".").replace(" ", ""))
        return 0.0 if math.isnan(v) or math.isinf(v) else v
    except (ValueError, TypeError):
        return default

def parse_gps(row):
    """Retourne (lat, lon) ou (None, None)."""
    # Champ _geolocation de KoboToolbox = [lat, lon]
    geo = row.get(F["gps"])
    if isinstance(geo, list) and len(geo) >= 2:
        try:
            lat = float(geo[0])
            lon = float(geo[1])
            if lat != 0 and lon != 0:
                return lat, lon
        except (TypeError, ValueError):
            pass
    # Champs séparés
    lat_raw = get_field(row, F["lat"], "lat", "latitude", "_GPS_latitude")
    lon_raw = get_field(row, F["lon"], "lon", "longitude", "_GPS_longitude")
    if lat_raw and lon_raw:
        try:
            return float(lat_raw), float(lon_raw)
        except (TypeError, ValueError):
            pass
    return None, None

def calc_cartons(row):
    """Calcule les cartons.
    - 'Nbre de carton livre'    = cartons directs
    - 'Nbre de bouteille livre' = bouteilles (converties si pas de cartons)
    """
    cartons_direct = parse_float(get_field(row, F["cartons_boite"]))
    bouteilles     = parse_float(get_field(row, F["bouteilles"]))
    if cartons_direct > 0:
        return cartons_direct, cartons_direct, bouteilles
    if bouteilles > 0:
        return bouteilles / BOUTEILLES_PAR_CARTON, 0.0, bouteilles
    return 0.0, 0.0, 0.0


# ══════════════════════════════════════════════════════════════
#  ── TRANSFORMATION DES DONNÉES ──
# ══════════════════════════════════════════════════════════════

def transform(submissions):
    """Transforme les soumissions brutes en variables JS du dashboard."""

    staff_color_map = {}
    color_idx = 0

    # Structures intermédiaires
    daily_map   = defaultdict(lambda: {"activites": 0, "cartons": 0.0, "montant": 0.0})
    staff_map   = defaultdict(lambda: {"activites": 0, "cartons": 0.0, "montant": 0.0})
    clients_map = defaultdict(lambda: {
        "nature": "", "zone": "", "zone_op": "", "interlocuteur": "",
        "contact": "", "staff": "", "nb_visites": 0, "cartons": 0.0,
        "cartons_boite": 0.0, "bouteilles": 0.0, "montant": 0.0,
        "mode_paiement": "", "action": "", "si_visite": "", "si_vente": "",
        "premiere_visite": "", "derniere_visite": "", "observation": "",
        "lat": None, "lon": None,
    })

    gps_rows    = []
    credit_rows = []

    for row in submissions:
        d         = parse_date(row)
        staff     = str(get_field(row, F["staff"])).strip()
        cible     = str(get_field(row, F["cible"])).strip()
        nature    = str(get_field(row, F["nature"])).strip()
        zone      = str(get_field(row, F["zone"])).strip()
        zone_op   = str(get_field(row, F["zone_op"])).strip()
        action    = str(get_field(row, F["action"])).strip()
        si_visite = str(get_field(row, F["si_visite"])).strip()
        si_vente  = str(get_field(row, F["si_vente"])).strip()
        obs       = str(get_field(row, F["observation"])).strip()
        contact   = str(get_field(row, F["contact"])).strip()
        interl    = str(get_field(row, F["interlocuteur"])).strip()
        statut_i  = str(get_field(row, F["statut_interl"])).strip()
        paiement  = str(get_field(row, F["paiement"])).strip()
        montant   = parse_float(get_field(row, F["montant"]))
        cartons, cartons_boite, bouteilles = calc_cartons(row)
        lat, lon  = parse_gps(row)

        if not staff:
            staff = "Inconnu"

        # Attribution couleur staff
        if staff not in staff_color_map:
            staff_color_map[staff] = STAFF_COLORS[color_idx % len(STAFF_COLORS)]
            color_idx += 1

        # ── DAILY ──
        if d:
            daily_map[d]["activites"] += 1
            daily_map[d]["cartons"]   += cartons
            daily_map[d]["montant"]   += montant

        # ── STAFF ──
        staff_map[staff]["activites"] += 1
        staff_map[staff]["cartons"]   += cartons
        staff_map[staff]["montant"]   += montant

        # ── CLIENTS (agrégé par nom de cible) ──
        key = cible or "N/A"
        c = clients_map[key]
        c["nature"]    = c["nature"] or nature
        c["zone"]      = c["zone"]   or zone
        c["zone_op"]   = c["zone_op"] or zone_op
        c["interlocuteur"] = c["interlocuteur"] or interl
        c["contact"]   = c["contact"] or contact
        c["staff"]     = staff   # dernier staff connu
        c["nb_visites"] += 1
        c["cartons"]   += cartons
        c["cartons_boite"] += cartons_boite
        c["bouteilles"] += bouteilles
        c["montant"]   += montant
        c["mode_paiement"] = c["mode_paiement"] or paiement
        c["action"]    = action
        c["si_visite"] = si_visite
        c["si_vente"]  = si_vente
        c["observation"] = obs
        if d:
            if not c["premiere_visite"] or d < c["premiere_visite"]:
                c["premiere_visite"] = d
            if not c["derniere_visite"] or d > c["derniere_visite"]:
                c["derniere_visite"] = d
        if lat and not c["lat"]:
            c["lat"] = lat
            c["lon"] = lon

        # ── GPS_DATA (toutes les lignes avec coordonnées) ──
        gps_rows.append({
            "staff": staff, "date": d, "cible": cible, "nature": nature,
            "zone_op": zone_op, "zone": zone, "action": action,
            "si_visite": si_visite, "si_vente": si_vente,
            "cartons": round(cartons, 4), "cartons_boite": round(cartons_boite, 4),
            "bouteilles": round(bouteilles, 4), "valeur": montant,
            "paiement": paiement, "obs": obs,
            "contact": contact, "interl": interl, "statut": statut_i,
            "lat": lat, "lon": lon,
        })

        # ── CREDIT_DATA (livré non payé) ──
        if "non payé" in si_vente.lower() or "credit" in si_vente.lower() or "crédit" in si_vente.lower():
            credit_rows.append({
                "staff": staff, "date": d, "cible": cible, "nature": nature,
                "zone_op": zone_op, "zone": zone, "action": action,
                "si_visite": si_visite, "si_vente": si_vente,
                "cartons": round(cartons, 4), "cartons_boite": round(cartons_boite, 4),
                "bouteilles": round(bouteilles, 4), "valeur": montant,
                "paiement": paiement, "obs": obs,
                "contact": contact, "interl": interl, "statut": statut_i,
                "lat": lat, "lon": lon,
            })

    # ── Finalisation DAILY (trié par date) ──
    DAILY = [
        {"date": d, "activites": v["activites"],
         "cartons": round(v["cartons"], 4), "montant": round(v["montant"], 2)}
        for d, v in sorted(daily_map.items())
    ]

    # ── Finalisation STAFF (trié par activités desc) ──
    STAFF = [
        {"name": s, "activites": v["activites"],
         "cartons": round(v["cartons"], 4), "montant": round(v["montant"], 2),
         "color": staff_color_map[s]}
        for s, v in sorted(staff_map.items(), key=lambda x: -x[1]["activites"])
    ]

    # ── Finalisation CLIENTS ──
    CLIENTS = []
    for nom, c in clients_map.items():
        CLIENTS.append({
            "nom": nom,
            "nature": c["nature"], "zone": c["zone"], "zone_op": c["zone_op"],
            "interlocuteur": c["interlocuteur"], "contact": c["contact"],
            "staff": c["staff"], "nb_visites": c["nb_visites"],
            "cartons": round(c["cartons"], 4),
            "cartons_boite": round(c["cartons_boite"], 4),
            "bouteilles": round(c["bouteilles"], 4),
            "montant": round(c["montant"], 2),
            "mode_paiement": c["mode_paiement"],
            "action": c["action"], "si_visite": c["si_visite"],
            "si_vente": c["si_vente"],
            "derniere_visite": c["derniere_visite"],
            "observation": c["observation"],
            "lat": c["lat"], "lon": c["lon"],
        })

    # ── CONTACTS (clients avec interlocuteur renseigné ou contact) ──
    CONTACTS = [
        {
            "nom": c["nom"], "nature": c["nature"], "zone": c["zone"],
            "zone_op": c["zone_op"], "interlocuteur": c["interlocuteur"],
            "statut": c.get("statut_interl", ""), "contact": c["contact"],
            "staff": c["staff"], "premiere": c.get("premiere_visite", ""),
            "derniere": c["derniere_visite"], "nb_visites": c["nb_visites"],
            "cartons": round(c["cartons"], 4), "montant": round(c["montant"], 2),
            "paiement": c["mode_paiement"], "actions": c["action"],
            "si_visite": c["si_visite"], "observation": c["observation"],
            "a_achete": c["montant"] > 0 or c["cartons"] > 0,
        }
        for c in CLIENTS
        if c["interlocuteur"] or c["contact"]
    ]

    # Trier CLIENTS par montant desc
    CLIENTS.sort(key=lambda x: -x["montant"])

    # Stock restant (valeur fixe par défaut — à adapter si vous avez un champ stock)
    total_cartons = sum(v["cartons"] for v in staff_map.values())
    STOCK_RESTANT = max(0, round(1018 - total_cartons))  # ajustez le stock initial ici

    # Période
    dates = [d for d in daily_map if d]
    periode = f"{min(dates)[:7] if dates else '?'} → {max(dates)[:7] if dates else '?'}"
    nb_activites = sum(v["activites"] for v in daily_map.values())

    return {
        "DAILY":        DAILY,
        "STAFF":        STAFF,
        "CLIENTS":      CLIENTS,
        "CONTACTS":     CONTACTS,
        "GPS_DATA":     gps_rows,
        "CREDIT_DATA":  credit_rows,
        "STOCK_RESTANT": STOCK_RESTANT,
        "periode":      periode,
        "nb_activites": nb_activites,
        "generated_at": datetime.utcnow().strftime("%d/%m/%Y à %Hh%M UTC"),
    }


# ══════════════════════════════════════════════════════════════
#  ── INJECTION DANS LE HTML ──
# ══════════════════════════════════════════════════════════════

def inject_into_html(data):
    """Remplace les blocs de données statiques dans le HTML template."""

    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    def js(obj):
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

    now  = data["generated_at"]
    per  = data["periode"]
    nb   = data["nb_activites"]

    replacements = {
        r"var DAILY\s*=\s*\[.*?\];":
            f"var DAILY           = {js(data['DAILY'])};",
        r"var STAFF\s*=\s*\[.*?\];":
            f"var STAFF           = {js(data['STAFF'])};",
        r"var CLIENTS\s*=\s*\[.*?\];":
            f"var CLIENTS         = {js(data['CLIENTS'])};",
        r"var CONTACTS\s*=\s*\[.*?\];":
            f"var CONTACTS        = {js(data['CONTACTS'])};",
        r"var GPS_DATA\s*=\s*\[.*?\];":
            f"var GPS_DATA        = {js(data['GPS_DATA'])};",
        r"var CREDIT_DATA\s*=\s*\[.*?\];":
            f"var CREDIT_DATA     = {js(data['CREDIT_DATA'])};",
        r"var STOCK_RESTANT\s*=\s*[\d]+;[^\n]*":
            f"var STOCK_RESTANT   = {data['STOCK_RESTANT']}; // généré le {now}",
    }

    for pattern, replacement in replacements.items():
        new_html, count = re.subn(pattern, replacement, html, flags=re.DOTALL)
        if count:
            html = new_html
            print(f"  ✅  Remplacé : {pattern[:50]}…")
        else:
            print(f"  ⚠️   Pattern non trouvé : {pattern[:50]}…")

    # Mise à jour du header de statut
    html = re.sub(
        r'(id="header-status"[^>]*>).*?(</div>)',
        f'\\1<span style="color:#10b981;font-weight:700">● Live</span>&nbsp;&nbsp;'
        f'{nb:,} activités · {per} · mis à jour {now}\\2',
        html, flags=re.DOTALL
    )

    # Mise à jour du commentaire de données
    html = html.replace(
        "// ══ DONNÉES STATIQUES Excel",
        f"// ══ DONNÉES LIVE KoboToolbox — généré le {now} ══\n// "
    )

    # Mise à jour de la date dans le sous-titre du logo
    if per:
        # Extraire les mois en français pour le sous-titre
        months_fr = {
            "01":"Jan","02":"Fév","03":"Mar","04":"Avr","05":"Mai","06":"Jun",
            "07":"Jul","08":"Aoû","09":"Sep","10":"Oct","11":"Nov","12":"Déc"
        }
        dates = sorted(data["DAILY"], key=lambda x: x["date"])
        if dates:
            d_min = dates[0]["date"]
            d_max = dates[-1]["date"]
            label_min = f"{months_fr.get(d_min[5:7], '')} {d_min[:4]}"
            label_max = f"{months_fr.get(d_max[5:7], '')} {d_max[:4]}"
            new_sub = f"COM'ON DISTRI-AGRI · {label_min} → {label_max}"
            html = re.sub(
                r'(class="logo-sub">[^<]*)COM\'ON DISTRI-AGRI[^<]*(<)',
                f'\\1{new_sub}\\2',
                html
            )

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n  ✅  {OUTPUT_FILE} généré ({len(html):,} caractères).")


# ══════════════════════════════════════════════════════════════
#  ── MAIN ──
# ══════════════════════════════════════════════════════════════

def main():
    print("\n🚀  Démarrage de la génération du dashboard")
    print(f"   Formulaire : {KOBO_UID}")
    print(f"   Serveur    : {KOBO_SERVER}")
    print(f"   Template   : {TEMPLATE_FILE}  →  {OUTPUT_FILE}\n")

    # Vérifier que le template existe
    if not os.path.exists(TEMPLATE_FILE):
        print(f"❌  Fichier template introuvable : {TEMPLATE_FILE}")
        print("   Renommez votre dashboard_kobo__38_.html en index_template.html")
        sys.exit(1)

    print("📡  Récupération des données KoboToolbox…")
    submissions = fetch_all_submissions()

    print("\n🔄  Transformation des données…")
    data = transform(submissions)
    print(f"   • {len(data['DAILY'])} jours d'activité")
    print(f"   • {len(data['STAFF'])} staffs")
    print(f"   • {len(data['CLIENTS'])} clients uniques")
    print(f"   • {len(data['CONTACTS'])} contacts")
    print(f"   • {len(data['GPS_DATA'])} points GPS")
    print(f"   • {len(data['CREDIT_DATA'])} entrées crédit")
    print(f"   • Stock restant estimé : {data['STOCK_RESTANT']} ctn")

    print("\n💉  Injection dans le HTML…")
    inject_into_html(data)

    print("\n✨  Terminé !\n")


if __name__ == "__main__":
    main()
