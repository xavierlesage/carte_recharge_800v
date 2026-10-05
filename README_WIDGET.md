# Widget iOS « Bornes 800 V les plus proches »

Le widget affiche les bornes 800 V les plus proches d'une adresse ou de ta position.
Un appui ouvre la carte `index.html`, centrée sur le point recherché ou sur la fiche de la station touchée.

## 1. Mettre la carte en ligne (une seule fois)

Sur GitHub : dépôt `carte_recharge_800v` → **Settings** → **Pages** →
Source « Deploy from a branch », branche `main`, dossier `/ (root)` → **Save**.

Après une ou deux minutes, la carte est en ligne sur https://xavierlesage.github.io/carte_recharge_800v/

## 2. Installer le script sur l'iPhone

1. Installer l'app gratuite **Scriptable** depuis l'App Store.
2. Ouvrir `widget_ios_scriptable.js` sur GitHub, appuyer sur « Raw » et tout copier.
3. Dans Scriptable : **+**, coller le code, puis renommer le script en « Bornes 800V ».
4. Lancer le script une fois depuis l'app et accepter l'accès à la position.

## 3. Ajouter le widget

1. Appui long sur l'écran d'accueil → **+** → **Scriptable** → choisir la taille :
   - petit : 2 bornes, le widget entier ouvre la carte ;
   - moyen : 3 bornes, chaque ligne ouvre la fiche de sa station ;
   - grand : 7 bornes.
2. Appui long sur le widget → **Modifier le widget** :
   - **Script** : « Bornes 800V »
   - **When Interacting** : laisser la valeur par défaut (« Open App ») ; les liens vers la carte sont fournis par le script
   - **Parameter** : une adresse ou une ville (ex. `Lyon`, `Aire de Tours Longue Vue`), ou **vide** pour ta position.

Tu peux ajouter plusieurs widgets avec des paramètres différents (domicile, bureau, une étape de trajet…).

## Recherche ponctuelle

Lancer le script depuis l'app Scriptable, ou via Siri (« Bornes 800V »), demande une adresse et affiche les 15 bornes les plus proches.
Un appui sur une station l'ouvre sur la carte.

## Réglages

En haut du script, dans `CONFIG` :

- `niveaux` : `["confirme"]` pour n'afficher que les bornes vertes ;
- `puissanceMinKw` : puissance minimale ;
- `cacheHeures` : fréquence de téléchargement des données, 24 h par défaut. Le widget fonctionne aussi hors ligne avec les dernières données.
