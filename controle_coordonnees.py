#!/usr/bin/env python3
"""Contrôle des coordonnées des stations françaises de bornes_800v.geojson : géocode l'adresse
déclarée de chaque station avec la Base Adresse Nationale (géocodage CSV en une requête) et
signale les stations dont le pin est loin de l'adresse.

Usage : python3 controle_coordonnees.py [--niveaux confirme,probable] [--seuil-km 1] [--sortie rapport.csv]

Seuls les géocodages fiables sont comparés : numéro ou rue, score suffisant, et dans la bonne
commune (code postal de l'adresse, sinon nom de commune). Une adresse vague (« Aire de … »,
lieu-dit, rue sans commune) ne permet pas de conclure. Un géocodage à la rue (sans numéro)
donne le milieu de la rue : les écarts correspondants sont listés à part, à vérifier. Pour chaque écart, le script
propose une entrée à recopier dans corrections_stations.json après vérification sur place
(vue satellite, site de l'opérateur…).
"""
import argparse
import csv
import io
import json
import math
import os
import re
import unicodedata

import requests

ICI = os.path.dirname(os.path.abspath(__file__))
BAN_CSV = "https://data.geopf.fr/geocodage/search/csv"
SCORE_MIN = 0.6
TYPES_FIABLES = {"housenumber", "street"}


def distance_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def simplifier(texte):
    """« Saint-Étienne » → « saint etienne » : comparaison de noms de commune."""
    texte = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", texte).strip()


def code_postal(adresse):
    m = re.search(r"(?<!\d)(\d{5})(?!\d)", adresse)
    return m.group(1) if m else ""


def geocoder(stations):
    """Géocode toutes les adresses en une requête, filtrées sur le code postal quand il est connu."""
    tampon = io.StringIO()
    w = csv.writer(tampon)
    w.writerow(["n", "adresse", "cp"])
    for n, s in enumerate(stations):
        adresse = s["adresse"]
        if s["commune"] and simplifier(s["commune"]) not in simplifier(adresse):
            adresse += " " + s["commune"]
        w.writerow([n, adresse, code_postal(s["adresse"])])
    r = requests.post(BAN_CSV, files={"data": ("adresses.csv", tampon.getvalue().encode("utf-8"))},
                      data={"columns": "adresse", "postcode": "cp"}, timeout=600)
    r.raise_for_status()
    r.encoding = "utf-8"
    return {int(l["n"]): l for l in csv.DictReader(io.StringIO(r.text))}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--niveaux", default="confirme", help="niveaux contrôlés, séparés par des virgules")
    parser.add_argument("--seuil-km", type=float, default=1.0, help="écart signalé au-delà de cette distance")
    parser.add_argument("--sortie", help="rapport CSV complet (toutes les stations contrôlées)")
    args = parser.parse_args()
    niveaux = set(args.niveaux.split(","))

    with open(os.path.join(ICI, "bornes_800v.geojson"), encoding="utf-8") as f:
        features = json.load(f)["features"]
    stations = [dict(f["properties"], lon=f["geometry"]["coordinates"][0], lat=f["geometry"]["coordinates"][1])
                for f in features
                if f["properties"]["pays"] == "FR" and f["properties"]["niveau"] in niveaux]
    print(f"Géocodage de {len(stations)} adresses ({', '.join(sorted(niveaux))})…")
    resultats = geocoder(stations)

    lignes, ecarts, non_fiables = [], [], 0
    for n, s in enumerate(stations):
        g = resultats.get(n, {})
        try:
            glat, glon, score = float(g["latitude"]), float(g["longitude"]), float(g["result_score"])
        except (KeyError, ValueError):
            glat = glon = None
            score = 0
        cp = code_postal(s["adresse"])
        bonne_commune = (g.get("result_postcode") == cp if cp else
                         bool(s["commune"]) and simplifier(g.get("result_city", "")) == simplifier(s["commune"]))
        fiable = (glat is not None and score >= SCORE_MIN and bonne_commune
                  and g.get("result_type") in TYPES_FIABLES)
        d = distance_km(s["lat"], s["lon"], glat, glon) if glat is not None else None
        non_fiables += not fiable
        ligne = {
            "id": s.get("id", ""), "nom": s["nom"], "reseau": s["reseau"], "niveau": s["niveau"],
            "adresse": s["adresse"], "lat": s["lat"], "lon": s["lon"],
            "adresse_ban": g.get("result_label", ""), "type_ban": g.get("result_type", ""),
            "score_ban": round(score, 2), "lat_ban": glat, "lon_ban": glon,
            "ecart_km": None if d is None else round(d, 2), "fiable": fiable,
        }
        lignes.append(ligne)
        if fiable and d > args.seuil_km:
            ecarts.append(ligne)

    if args.sortie:
        with open(args.sortie, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(lignes[0]))
            w.writeheader()
            w.writerows(lignes)
        print(f"Rapport complet : {args.sortie}")

    ecarts.sort(key=lambda l: -l["ecart_km"])
    numeros = [l for l in ecarts if l["type_ban"] == "housenumber"]
    rues = [l for l in ecarts if l["type_ban"] != "housenumber"]
    print(f"\n{len(stations) - non_fiables} adresses contrôlées, {non_fiables} trop vagues pour conclure.")
    for titre, liste in ((f"Pin à plus de {args.seuil_km:g} km du numéro de l'adresse", numeros),
                         (f"Pin à plus de {args.seuil_km:g} km du milieu de la rue (à vérifier)", rues)):
        print(f"\n{titre} : {len(liste)}\n")
        for l in liste:
            print(f"  {l['ecart_km']:7.2f} km  {l['reseau'][:28]:28} {l['nom'][:40]:40}  {l['adresse'][:60]}")
            print(f"             → BAN : {l['adresse_ban']} (score {l['score_ban']})")

    if numeros:
        print("\nEntrées proposées pour corrections_stations.json (à vérifier avant de les ajouter) :")
        print(json.dumps({l["id"]: {"lat": round(l["lat_ban"], 5), "lon": round(l["lon_ban"], 5),
                                    "motif": f"Pin déclaré à {l['ecart_km']} km de l'adresse ({l['adresse']})"}
                          for l in numeros if l["id"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
