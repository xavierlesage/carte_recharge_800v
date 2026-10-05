// Variables used by Scriptable.
// These must be at the very top of the file. Do not edit.
// icon-color: deep-green; icon-glyph: bolt;

// Bornes 800 V les plus proches — widget iOS pour l'app Scriptable
//
// Installation : voir README_WIDGET.md
// Paramètre du widget (appui long > Modifier le widget > Parameter) :
//   - vide            → bornes autour de ma position
//   - une adresse     → bornes autour de cette adresse (ex. « Aire de Tours Longue Vue » ou « 44000 Nantes »)
// Lancé depuis l'app Scriptable : demande une adresse et affiche la liste complète.

const CONFIG = {
  // Carte Leaflet publiée (GitHub Pages)
  urlCarte: "https://xavierlesage.github.io/carte_recharge_800v/",
  // Données des bornes (régénérées par build_geojson.py)
  urlDonnees: "https://raw.githubusercontent.com/xavierlesage/carte_recharge_800v/main/bornes_800v.geojson",
  // Niveaux affichés : "confirme" (vert) et/ou "probable" (orange)
  niveaux: ["confirme", "probable"],
  puissanceMinKw: 150,
  cacheHeures: 24,
  nbDansApp: 15,
};

const COULEURS = {
  confirme: Color.dynamic(new Color("#11865a"), new Color("#2fbf84")),
  probable: Color.dynamic(new Color("#d97706"), new Color("#f59e0b")),
  texte: Color.dynamic(new Color("#1d2330"), new Color("#e8ebf0")),
  discret: Color.dynamic(new Color("#5d6675"), new Color("#9aa3b2")),
  fond: Color.dynamic(new Color("#ffffff"), new Color("#12161d")),
};

// ---------- Données ----------

async function chargerBornes() {
  const fm = FileManager.local();
  const chemin = fm.joinPath(fm.documentsDirectory(), "bornes_800v.geojson");
  const existe = fm.fileExists(chemin);
  const age = existe ? (Date.now() - fm.modificationDate(chemin).getTime()) / 3.6e6 : Infinity;
  if (age > CONFIG.cacheHeures) {
    try {
      const texte = await new Request(CONFIG.urlDonnees).loadString();
      JSON.parse(texte); // ne remplace le cache que par un fichier valide
      fm.writeString(chemin, texte);
    } catch (e) {
      if (!existe) throw new Error("Données indisponibles (pas de réseau ?)");
    }
  }
  return JSON.parse(fm.readString(chemin)).features.filter(f =>
    CONFIG.niveaux.includes(f.properties.niveau) && f.properties.kw >= CONFIG.puissanceMinKw);
}

// ---------- Point de recherche ----------

async function geocoder(adresse) {
  const url = "https://data.geopf.fr/geocodage/search?limit=1&q=" + encodeURIComponent(adresse);
  const f = (await new Request(url).loadJSON()).features?.[0];
  if (!f) throw new Error(`Adresse introuvable : ${adresse}`);
  const [lon, lat] = f.geometry.coordinates;
  return { lat, lon, libelle: f.properties.label, court: f.properties.city || f.properties.name };
}

async function maPosition() {
  Location.setAccuracyToHundredMeters();
  const { latitude: lat, longitude: lon } = await Location.current();
  let court = "ma position";
  try {
    const [lieu] = await Location.reverseGeocode(lat, lon, "fr_FR");
    if (lieu?.locality) court = lieu.locality;
  } catch (e) {}
  return { lat, lon, libelle: "Ma position", court };
}

async function pointDeRecherche(adresse) {
  return adresse && adresse.trim() ? geocoder(adresse.trim()) : maPosition();
}

// ---------- Calculs ----------

function distanceKm(lat1, lon1, lat2, lon2) {
  const rad = Math.PI / 180, R = 6371;
  const a = Math.sin((lat2 - lat1) * rad / 2) ** 2
    + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin((lon2 - lon1) * rad / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

function plusProches(bornes, point, n) {
  return bornes
    .map(f => {
      const [lon, lat] = f.geometry.coordinates;
      return { ...f.properties, lat, lon, km: distanceKm(point.lat, point.lon, lat, lon) };
    })
    .sort((a, b) => a.km - b.km)
    .slice(0, n);
}

const formatKm = km => km < 10 ? km.toFixed(1).replace(".", ",") + " km" : Math.round(km) + " km";

function urlCarte(point, borne) {
  // (pas de URLSearchParams dans le moteur JavaScript de Scriptable)
  const p = { lat: point.lat.toFixed(5), lon: point.lon.toFixed(5), z: "11", q: point.libelle };
  if (borne) p.borne = `${borne.lat},${borne.lon}`;
  return CONFIG.urlCarte + "?" + Object.entries(p).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
}

// ---------- Widget ----------

function nbSelonTaille(famille) {
  return { small: 2, medium: 3, large: 7, extraLarge: 7 }[famille] ?? 3;
}

function creerWidget(point, stations, famille) {
  const w = new ListWidget();
  w.backgroundColor = COULEURS.fond;
  w.setPadding(12, 14, 12, 14);
  w.url = urlCarte(point);
  w.refreshAfterDate = new Date(Date.now() + 30 * 60 * 1000);
  const petit = famille === "small";

  const entete = w.addStack();
  entete.centerAlignContent();
  const eclair = entete.addImage(SFSymbol.named("bolt.car.fill").image);
  eclair.imageSize = new Size(16, 16);
  eclair.tintColor = COULEURS.confirme;
  entete.addSpacer(5);
  const titre = entete.addText(petit ? "800 V" : `800 V près de ${point.court}`);
  titre.font = Font.boldSystemFont(petit ? 13 : 14);
  titre.textColor = COULEURS.texte;
  titre.lineLimit = 1;
  w.addSpacer(8);

  if (!stations.length) {
    const t = w.addText("Aucune borne trouvée");
    t.font = Font.systemFont(13);
    t.textColor = COULEURS.discret;
  }

  stations.forEach((s, i) => {
    if (i) w.addSpacer(petit ? 6 : 7);
    const ligne = w.addStack();
    ligne.centerAlignContent();
    if (!petit) ligne.url = urlCarte(point, s); // une zone cliquable par station (moyen/grand)

    const pastille = ligne.addStack();
    pastille.size = new Size(9, 9);
    pastille.cornerRadius = 4.5;
    pastille.backgroundColor = COULEURS[s.niveau];
    ligne.addSpacer(7);

    const textes = ligne.addStack();
    textes.layoutVertically();
    const l1 = textes.addText(`${s.reseau} · ${s.kw} kW`);
    l1.font = Font.semiboldSystemFont(petit ? 12 : 13);
    l1.textColor = COULEURS.texte;
    l1.lineLimit = 1;
    const l2 = textes.addText(petit ? formatKm(s.km) : (s.commune || s.nom || ""));
    l2.font = Font.systemFont(11);
    l2.textColor = COULEURS.discret;
    l2.lineLimit = 1;

    if (!petit) {
      ligne.addSpacer();
      const d = ligne.addText(formatKm(s.km));
      d.font = Font.mediumMonospacedSystemFont(12);
      d.textColor = COULEURS.texte;
    }
  });

  w.addSpacer();
  const pied = w.addText("Mis à jour " + new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }));
  pied.font = Font.systemFont(9);
  pied.textColor = COULEURS.discret;
  return w;
}

function widgetErreur(message) {
  const w = new ListWidget();
  w.backgroundColor = COULEURS.fond;
  const t = w.addText("⚡ 800 V");
  t.font = Font.boldSystemFont(14);
  t.textColor = COULEURS.texte;
  w.addSpacer(6);
  const m = w.addText(message);
  m.font = Font.systemFont(12);
  m.textColor = COULEURS.discret;
  w.url = CONFIG.urlCarte;
  return w;
}

// ---------- Dans l'app : saisie d'adresse + liste ----------

async function demanderAdresse() {
  const a = new Alert();
  a.title = "Bornes 800 V";
  a.message = "Adresse ou ville (laisser vide pour ma position)";
  a.addTextField("ex. Lyon, 12 rue de la Paix Paris…", args.widgetParameter || "");
  a.addAction("Rechercher");
  a.addCancelAction("Annuler");
  return (await a.presentAlert()) === -1 ? null : a.textFieldValue(0);
}

async function afficherListe(point, stations) {
  const table = new UITable();
  table.showSeparators = true;
  const entete = new UITableRow();
  entete.isHeader = true;
  entete.addText(`Bornes 800 V près de ${point.libelle}`, "Touchez une station pour l'ouvrir sur la carte");
  table.addRow(entete);
  for (const s of stations) {
    const r = new UITableRow();
    r.height = 64;
    const pastille = r.addText(s.niveau === "confirme" ? "🟢" : "🟠");
    pastille.widthWeight = 8;
    const t = r.addText(`${s.reseau} · ${s.kw} kW · ${s.pdc} pt${s.pdc > 1 ? "s" : ""}`, s.adresse || s.commune || s.nom);
    t.widthWeight = 72;
    t.subtitleColor = Color.gray();
    const d = r.addText(formatKm(s.km));
    d.widthWeight = 20;
    d.rightAligned();
    r.dismissOnSelect = false;
    r.onSelect = () => Safari.open(urlCarte(point, s));
    table.addRow(r);
  }
  const carte = new UITableRow();
  carte.addButton("🗺  Ouvrir la carte complète").onTap = () => Safari.open(urlCarte(point));
  table.addRow(carte);
  await table.present();
}

// ---------- Lancement ----------

async function main() {
  if (config.runsInWidget) {
    try {
      const [point, bornes] = await Promise.all([pointDeRecherche(args.widgetParameter), chargerBornes()]);
      Script.setWidget(creerWidget(point, plusProches(bornes, point, nbSelonTaille(config.widgetFamily)), config.widgetFamily));
    } catch (e) {
      Script.setWidget(widgetErreur(e.message));
    }
    return;
  }

  const adresse = await demanderAdresse();
  if (adresse === null) return;
  try {
    const [point, bornes] = await Promise.all([pointDeRecherche(adresse), chargerBornes()]);
    await afficherListe(point, plusProches(bornes, point, CONFIG.nbDansApp));
  } catch (e) {
    const a = new Alert();
    a.title = "Erreur";
    a.message = e.message;
    a.addAction("OK");
    await a.presentAlert();
  }
}

await main();
Script.complete();
