#!/usr/bin/env python3
"""Génère bornes_800v.geojson à partir du fichier national IRVE (data.gouv.fr).

Usage : python3 build_geojson.py [chemin_csv]
Sans argument, télécharge la dernière consolidation IRVE.
"""
import collections
import csv
import json
import os
import re
import sys
import tempfile
import urllib.request

ICI = os.path.dirname(os.path.abspath(__file__))
DATASET = "https://www.data.gouv.fr/api/1/datasets/5448d3e0c751df01f85d0572/"


def telecharger_csv():
    with urllib.request.urlopen(DATASET) as r:
        ressources = json.load(r)["resources"]
    url = next(x["url"] for x in ressources
               if x["format"] == "csv" and "consolidation" in x["title"].lower())
    dest = os.path.join(tempfile.gettempdir(), "irve.csv")
    print("Téléchargement", url)
    urllib.request.urlretrieve(url, dest)
    return dest


def puissance_kw(valeur):
    try:
        p = float(valeur.replace(",", "."))
    except (ValueError, AttributeError):
        return 0
    return p / 1000 if p > 2000 else p  # certaines valeurs sont saisies en W


def reparer(texte):
    """Corrige les textes mal encodés du fichier source (UTF-8 relu en Latin-1 ou en Mac Roman,
    parfois deux fois de suite : « RÃ©seau », « D√©partementale », « Ali‚àö¬©nor »)."""
    texte = texte.strip()
    for _ in range(3):
        for codec in ("cp1252", "mac_roman"):
            try:
                corrige = texte.encode(codec).decode("utf-8")
            except UnicodeError:
                continue
            if corrige != texte:
                texte = corrige
                break
        else:
            break
    return texte.replace("\ufffd", "é")  # caractère perdu dans la source, presque toujours un « é »


def nom_reseau(operateur):
    """Nom d'opérateur lisible : sans le code d'itinérance « | FR*XXX », casse normalisée."""
    nom = re.sub(r"\s*\|.*$", "", operateur).strip()
    return nom.title() if nom.isupper() and len(nom) > 4 else nom


def vrai(valeur):
    return valeur.strip().lower() in ("true", "1", "oui")


def main():
    chemin = sys.argv[1] if len(sys.argv) > 1 else telecharger_csv()
    with open(os.path.join(ICI, "regles_800v.json"), encoding="utf-8") as f:
        config = json.load(f)
    regles = [(re.compile(r["motif"], re.I), r) for r in config["regles"]]
    pmin = config["puissance_min_kw"]
    p_probable = config["probable_si_puissance_kw"]

    stations = {}
    date_donnees = ""
    with open(chemin, encoding="utf-8") as f:
        for ligne in csv.DictReader(f):
            p = puissance_kw(ligne["puissance_nominale"])
            if p < pmin or not vrai(ligne["prise_type_combo_ccs"]):
                continue
            try:
                lon = round(float(ligne["consolidated_longitude"]), 5)
                lat = round(float(ligne["consolidated_latitude"]), 5)
            except ValueError:
                continue
            date_donnees = max(date_donnees, ligne["date_maj"])
            cle = ligne["id_station_itinerance"].strip() or f"{lon},{lat}"
            s = stations.get(cle)
            if s is None:
                s = stations[cle] = {
                    "nom": reparer(ligne["nom_station"]),
                    "adresse": reparer(ligne["adresse_station"]),
                    "commune": reparer(ligne["consolidated_commune"]),
                    "operateur": reparer(ligne["nom_operateur"]),
                    "enseigne": reparer(ligne["nom_enseigne"]),
                    "amenageur": reparer(ligne["nom_amenageur"]),
                    "horaires": reparer(ligne["horaires"]),
                    "mise_en_service": ligne["date_mise_en_service"].strip(),
                    "pdc": set(), "nbre_pdc": 0, "maj": "",
                    "pmax": 0,
                    "lon": lon, "lat": lat,
                }
            s["pdc"].add(ligne["id_pdc_itinerance"] or ligne["id_pdc_local"] or len(s["pdc"]))
            s["pmax"] = max(s["pmax"], p)
            s["maj"] = max(s["maj"], ligne["date_maj"], ligne["last_modified"][:10])
            try:
                s["nbre_pdc"] = max(s["nbre_pdc"], int(float(ligne["nbre_pdc"])))
            except ValueError:
                pass

    # Classement de chaque station selon les règles opérateur / puissance.
    graphies = {}  # une seule graphie par réseau (OBORNES / Obornes…)
    for s in stations.values():
        texte = " | ".join((s["operateur"], s["enseigne"], s["amenageur"]))
        regle = next((r for motif, r in regles if motif.search(texte)), None)
        if regle:
            s["niveau"], s["raison"] = regle["niveau"], regle["raison"]
            s["reseau"] = regle.get("reseau") or nom_reseau(s["operateur"] or s["enseigne"])
        elif s["pmax"] >= p_probable:
            s["niveau"] = "probable"
            s["raison"] = f"Borne ≥ {p_probable} kW : matériel quasi toujours 800 V+, à vérifier"
            s["reseau"] = nom_reseau(s["operateur"] or s["enseigne"])
        else:
            s["niveau"], s["raison"] = "inconnu", ""
            s["reseau"] = nom_reseau(s["operateur"] or s["enseigne"])
        s["reseau"] = graphies.setdefault(s["reseau"].lower(), s["reseau"]) or "Inconnu"
        s["nb_pdc"] = max(len(s["pdc"]), s["nbre_pdc"])

    # Une même station est parfois déclarée plusieurs fois, par des sources différentes
    # et avec des coordonnées légèrement décalées. Pour un même réseau, deux stations à
    # moins de ~300 m sont considérées comme une seule : on garde la déclaration la plus
    # récente (puis celle qui a le plus de points de charge).
    MAILLE = 0.003
    grille = collections.defaultdict(list)
    ordre = sorted(stations.values(), key=lambda s: (s["maj"], s["nb_pdc"]), reverse=True)
    fusion = []
    for s in ordre:
        i, j = round(s["lat"] / MAILLE), round(s["lon"] / MAILLE)
        voisins = (v for di in (-1, 0, 1) for dj in (-1, 0, 1) for v in grille[(s["reseau"].lower(), i + di, j + dj)])
        doublon = next((v for v in voisins if abs(v["lat"] - s["lat"]) < MAILLE and abs(v["lon"] - s["lon"]) < MAILLE), None)
        if doublon:
            doublon["pmax"] = max(doublon["pmax"], s["pmax"])
            continue
        grille[(s["reseau"].lower(), i, j)].append(s)
        fusion.append(s)

    features = []
    stats = collections.Counter()
    par_reseau = collections.Counter()
    inconnus = collections.Counter()
    for s in fusion:
        niveau, reseau = s["niveau"], s["reseau"]
        if niveau == "inconnu":
            inconnus[reseau] += 1
        stats[niveau] += 1
        if niveau not in ("confirme", "probable"):
            continue
        par_reseau[(niveau, reseau)] += 1
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
            "properties": {
                "nom": s["nom"], "adresse": s["adresse"], "commune": s["commune"],
                "reseau": reseau, "operateur": s["operateur"],
                "horaires": s["horaires"], "mise_en_service": s["mise_en_service"],
                "pdc": s["nb_pdc"], "kw": round(s["pmax"]),
                "niveau": niveau, "raison": s["raison"],
            },
        })

    sortie = {"type": "FeatureCollection", "date_donnees": date_donnees, "features": features}
    with open(os.path.join(ICI, "bornes_800v.geojson"), "w", encoding="utf-8") as f:
        json.dump(sortie, f, ensure_ascii=False, separators=(",", ":"))

    print(f"{len(fusion)} stations (après dédoublonnage) CCS ≥ {pmin} kW — données à jour au {date_donnees}")
    for niveau, n in stats.most_common():
        print(f"  {niveau:9} {n}")
    print("\nRéseaux affichés :")
    for (niveau, reseau), n in par_reseau.most_common(30):
        print(f"  {n:5}  {niveau:9} {reseau}")
    print("\nOpérateurs non classés (150–299 kW, masqués) :")
    for op, n in inconnus.most_common(20):
        print(f"  {n:5}  {op}")


if __name__ == "__main__":
    main()
