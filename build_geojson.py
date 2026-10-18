#!/usr/bin/env python3
"""Génère bornes_800v.geojson à partir des données publiques de bornes de recharge :
  - France : fichier national IRVE (data.gouv.fr) ;
  - Espagne : publication DATEX II des « electrolineras » du Point d'accès national (DGT / MITERD).

Usage : python3 build_geojson.py [--irve chemin_csv] [--dgt chemin_xml]
Sans argument, télécharge la dernière version de chaque source.
"""
import argparse
import collections
import csv
import json
import os
import re
import tempfile
import urllib.request
import xml.etree.ElementTree as ET

ICI = os.path.dirname(os.path.abspath(__file__))
DATASET = "https://www.data.gouv.fr/api/1/datasets/5448d3e0c751df01f85d0572/"
FLUX_DGT = "https://infocar.dgt.es/datex2/v3/miterd/EnergyInfrastructureTablePublication/electrolineras.xml"


def telecharger_csv():
    with urllib.request.urlopen(DATASET) as r:
        ressources = json.load(r)["resources"]
    url = next(x["url"] for x in ressources
               if x["format"] == "csv" and "consolidation" in x["title"].lower())
    dest = os.path.join(tempfile.gettempdir(), "irve.csv")
    print("Téléchargement", url)
    urllib.request.urlretrieve(url, dest)
    return dest


def telecharger_dgt():
    dest = os.path.join(tempfile.gettempdir(), "electrolineras.xml")
    print("Téléchargement", FLUX_DGT)
    urllib.request.urlretrieve(FLUX_DGT, dest)
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
    return texte.replace("�", "é")  # caractère perdu dans la source, presque toujours un « é »


def nom_reseau(operateur):
    """Nom d'opérateur lisible : sans le code d'itinérance « | FR*XXX » ni la forme juridique
    (« S.A.U », « SL », « GmbH Sucursal en España »…), casse normalisée."""
    nom = re.sub(r"\s*\|.*$", "", operateur).strip()
    nom = re.sub(r"^\((.+?)\)\s*.*$", r"\1", nom)  # « (ZUNDER) Grupo Easychargar SA » → « ZUNDER »
    nom = re.sub(r"[\s,]+(GmbH\b.*|S\.?\s?[AL]\.?\s?U?\.?|S\.?\s?R\.?\s?L\.?)$", "", nom, flags=re.I).strip()
    return nom.title() if nom.isupper() and len(nom) > 4 else nom


def vrai(valeur):
    return valeur.strip().lower() in ("true", "1", "oui")


def lire_irve(chemin, pmin):
    """Stations françaises : une ligne par point de charge dans le fichier IRVE.
    Renvoie aussi, pour l'historique, la date de mise en service de chaque point de charge
    rapide, tous réseaux confondus."""
    stations = {}
    points = {}
    date_donnees = ""
    with open(chemin, encoding="utf-8") as f:
        for n, ligne in enumerate(csv.DictReader(f)):
            p = puissance_kw(ligne["puissance_nominale"])
            if p < pmin or not vrai(ligne["prise_type_combo_ccs"]):
                continue
            id_pdc = ligne["id_pdc_itinerance"].strip() or ligne["id_pdc_local"].strip() or n
            points[id_pdc] = points.get(id_pdc) or ligne["date_mise_en_service"].strip()
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
                    "pays": "FR",
                    "nom": reparer(ligne["nom_station"]),
                    "adresse": reparer(ligne["adresse_station"]),
                    "commune": reparer(ligne["consolidated_commune"]),
                    "operateur": reparer(ligne["nom_operateur"]),
                    "enseigne": reparer(ligne["nom_enseigne"]),
                    "amenageur": reparer(ligne["nom_amenageur"]),
                    "code_operateur": "",
                    "horaires": reparer(ligne["horaires"]),
                    "mise_en_service": ligne["date_mise_en_service"].strip(),
                    "pdc": set(), "nbre_pdc": 0, "maj": "",
                    "pmax": 0, "tension": 0,
                    "lon": lon, "lat": lat,
                }
            s["pdc"].add(ligne["id_pdc_itinerance"] or ligne["id_pdc_local"] or len(s["pdc"]))
            s["pmax"] = max(s["pmax"], p)
            s["maj"] = max(s["maj"], ligne["date_maj"], ligne["last_modified"][:10])
            try:
                s["nbre_pdc"] = max(s["nbre_pdc"], int(float(ligne["nbre_pdc"])))
            except ValueError:
                pass
    return stations, points, date_donnees


def ecrire_historique(points, date_donnees, pmin):
    """historique.json : ajouts mensuels de points de charge rapides reconstitués d'après leur
    date de mise en service, et total relevé à chaque génération (instantanés)."""
    chemin = os.path.join(ICI, "historique.json")
    try:
        with open(chemin, encoding="utf-8") as f:
            instantanes = json.load(f).get("instantanes", [])
    except (OSError, ValueError):
        instantanes = []
    instantanes = [i for i in instantanes if i["date"] != date_donnees]
    instantanes.append({"date": date_donnees, "pdc": len(points)})
    instantanes.sort(key=lambda i: i["date"])

    # Dates absentes, mal formées ou hors de [2010, date des données] : point « sans date ».
    ajouts = collections.Counter(d[:7] for d in points.values()
                                 if re.fullmatch(r"\d{4}-\d\d-\d\d", d) and "2010-01-01" <= d <= date_donnees)
    mensuel, cumul = [], 0
    if ajouts:
        annee, mois = map(int, min(ajouts).split("-"))
        fin = date_donnees[:7]
        while f"{annee}-{mois:02}" <= fin:
            cle = f"{annee}-{mois:02}"
            cumul += ajouts[cle]
            mensuel.append({"mois": cle, "ajouts": ajouts[cle], "cumul": cumul})
            annee, mois = (annee + 1, 1) if mois == 12 else (annee, mois + 1)

    with open(chemin, "w", encoding="utf-8") as f:
        json.dump({"date_donnees": date_donnees, "puissance_min_kw": pmin,
                   "total": len(points), "sans_date": len(points) - cumul,
                   "mensuel": mensuel, "instantanes": instantanes},
                  f, ensure_ascii=False, separators=(",", ":"))
    return mensuel


NS = {
    "com": "http://datex2.eu/schema/3/common",
    "fac": "http://datex2.eu/schema/3/facilities",
    "egi": "http://datex2.eu/schema/3/energyInfrastructure",
    "loc": "http://datex2.eu/schema/3/locationReferencing",
    "locx": "http://datex2.eu/schema/3/locationExtension",
}


def lire_dgt(chemin, pmin):
    """Stations espagnoles : un energyInfrastructureSite par station, avec pour chaque prise
    sa puissance et sa tension maximale déclarées."""
    stations = {}
    date_donnees = ""
    site = "{%s}energyInfrastructureSite" % NS["egi"]
    for _, el in ET.iterparse(chemin):
        if el.tag == "{%s}publicationTime" % NS["com"]:
            date_donnees = (el.text or "")[:10]
        if el.tag != site:
            continue
        pdc, pmax, tension = 0, 0, 0
        for point in el.iterfind(".//egi:refillPoint", NS):
            rapides = [c for c in point.iterfind("egi:connector", NS)
                       if "COMBO" in c.findtext("egi:connectorType", "", NS).upper()
                       and float(c.findtext("egi:maxPowerAtSocket", "", NS) or 0) / 1000 >= pmin]
            if not rapides:
                continue
            pdc += 1
            for c in rapides:
                pmax = max(pmax, float(c.findtext("egi:maxPowerAtSocket", "", NS)) / 1000)
                tension = max(tension, float(c.findtext("egi:voltage", "", NS) or 0))
        try:
            lat = round(float(el.findtext(".//loc:coordinatesForDisplay/loc:latitude", "", NS)), 5)
            lon = round(float(el.findtext(".//loc:coordinatesForDisplay/loc:longitude", "", NS)), 5)
        except ValueError:
            pdc = 0
        if pdc:
            # lignes d'adresse « Dirección: … », « Municipio: … », « Provincia: … »
            adresse = {}
            for ligne in el.iterfind(".//locx:addressLine//com:value", NS):
                cle, _, valeur = (ligne.text or "").partition(":")
                adresse[cle.strip()] = valeur.strip()
            horaires = el.find("fac:operatingHours", NS)
            horaires = "" if horaires is None else (
                horaires.findtext("fac:label", "", NS).strip()
                or ("24/7" if horaires.get("id") == "24/7" else ""))
            operateur = el.find("fac:operator", NS)
            nom = el.findtext("fac:name//com:value", "", NS).strip()
            if re.fullmatch(r"[\w-]*\d[\w-]*", nom):
                nom = ""  # identifiant technique (« SN2112240159 ») : la carte affiche le réseau à la place
            stations["ES:" + el.get("id")] = {
                "pays": "ES",
                "nom": nom,
                "adresse": adresse.get("Dirección", ""),
                "commune": adresse.get("Municipio", ""),
                "operateur": "" if operateur is None else operateur.findtext("fac:name//com:value", "", NS).strip(),
                "enseigne": "", "amenageur": "",
                "code_operateur": "" if operateur is None else operateur.get("id", ""),
                "horaires": horaires,
                "mise_en_service": "",
                "pdc": set(), "nbre_pdc": pdc,
                "maj": el.findtext("fac:lastUpdated", "", NS)[:10],
                "pmax": pmax, "tension": round(tension),
                "lon": lon, "lat": lat,
            }
        el.clear()
    return stations, date_donnees


def classer(s, regles, noms, p_probable, v_min):
    """Niveau de compatibilité 800 V, raison et nom de réseau d'une station."""
    texte = " | ".join((s["operateur"], s["enseigne"], s["amenageur"], s["code_operateur"]))
    regle = next((r for motif, r in regles if motif.search(texte)), None)
    reseau = (regle or {}).get("reseau") or next(
        (nom for motif, nom in noms if motif.search(texte)), None) or nom_reseau(s["operateur"] or s["enseigne"])
    t = s["tension"]
    if regle and regle["niveau"] == "exclu" and not (t and regle.get("tension_prioritaire")):
        return "exclu", regle["raison"], reseau
    if t >= v_min:
        return "confirme", f"Tension maximale déclarée par l'opérateur : {t} V", reseau
    if t:
        if regle and regle["niveau"] == "confirme":
            return "probable", f"{regle['raison']} — mais tension déclarée : {t} V, à vérifier", reseau
        return "exclu", f"Tension déclarée : {t} V", reseau
    if regle:
        return regle["niveau"], regle["raison"], reseau
    if s["pmax"] >= p_probable:
        return "probable", f"Borne ≥ {p_probable} kW : matériel quasi toujours 800 V+, à vérifier", reseau
    return "inconnu", "", reseau


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--irve", help="fichier CSV IRVE (France) déjà téléchargé")
    parser.add_argument("--dgt", help="fichier XML DATEX II des electrolineras (Espagne) déjà téléchargé")
    args = parser.parse_args()

    with open(os.path.join(ICI, "regles_800v.json"), encoding="utf-8") as f:
        config = json.load(f)
    regles = [(re.compile(r["motif"], re.I), r) for r in config["regles"]]
    noms = [(re.compile(m, re.I), nom) for m, nom in config.get("noms_reseaux", {}).items()]
    pmin = config["puissance_min_kw"]
    p_probable = config["probable_si_puissance_kw"]
    v_min = config["tension_min_v"]

    stations, points, date_fr = lire_irve(args.irve or telecharger_csv(), pmin)
    mensuel = ecrire_historique(points, date_fr, pmin)
    stations_es, date_es = lire_dgt(args.dgt or telecharger_dgt(), pmin)
    stations.update(stations_es)

    # Classement de chaque station selon la tension déclarée et les règles opérateur / puissance.
    graphies = {}  # une seule graphie par réseau (OBORNES / Obornes…)
    for s in stations.values():
        s["niveau"], s["raison"], reseau = classer(s, regles, noms, p_probable, v_min)
        s["reseau"] = graphies.setdefault(reseau.lower(), reseau) or "Inconnu"
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
    exclus = collections.Counter()
    for s in fusion:
        niveau, reseau, pays = s["niveau"], s["reseau"], s["pays"]
        if niveau == "inconnu":
            inconnus[(pays, reseau)] += 1
        if niveau == "exclu":
            exclus[(pays, reseau)] += 1
        stats[(pays, niveau)] += 1
        if niveau not in ("confirme", "probable"):
            continue
        par_reseau[(pays, niveau, reseau)] += 1
        proprietes = {
            "nom": s["nom"], "adresse": s["adresse"], "commune": s["commune"],
            "reseau": reseau, "operateur": s["operateur"],
            "horaires": s["horaires"], "mise_en_service": s["mise_en_service"],
            "pdc": s["nb_pdc"], "kw": round(s["pmax"]),
            "niveau": niveau, "raison": s["raison"], "pays": pays,
        }
        if s["tension"]:
            proprietes["tension"] = s["tension"]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
            "properties": proprietes,
        })

    sortie = {"type": "FeatureCollection", "date_donnees": date_fr, "date_donnees_es": date_es,
              "features": features}
    with open(os.path.join(ICI, "bornes_800v.geojson"), "w", encoding="utf-8") as f:
        json.dump(sortie, f, ensure_ascii=False, separators=(",", ":"))

    print(f"{len(fusion)} stations (après dédoublonnage) CCS ≥ {pmin} kW — "
          f"données France au {date_fr}, Espagne au {date_es}")
    if len(mensuel) >= 2:
        dernier = mensuel[-2]
        print(f"Historique France : {len(points)} points de charge CCS ≥ {pmin} kW, tous réseaux "
              f"(+{dernier['ajouts']} mis en service en {dernier['mois']})")
    for (pays, niveau), n in sorted(stats.items()):
        print(f"  {pays} {niveau:9} {n}")
    for pays in ("FR", "ES"):
        print(f"\nRéseaux affichés ({pays}) :")
        for (p, niveau, reseau), n in par_reseau.most_common():
            if p == pays and n >= 3:
                print(f"  {n:5}  {niveau:9} {reseau}")
    print("\nRéseaux exclus :")
    for (pays, reseau), n in exclus.most_common(15):
        print(f"  {n:5}  {pays} {reseau}")
    print("\nOpérateurs non classés (150–299 kW, masqués) :")
    for (pays, reseau), n in inconnus.most_common(20):
        print(f"  {n:5}  {pays} {reseau}")


if __name__ == "__main__":
    main()
