# MonBot : bot de scalping pour Exness / MetaTrader 5 (Windows)

> ⚠️ **Le trading comporte un risque de perte en capital. Aucun gain n'est garanti.**
> MonBot démarre toujours en **mode démo**. Ne passez en réel qu'après un backtest
> **et** 1 à 2 mois de démo, avec de l'argent que vous pouvez vous permettre de perdre.

---

## 1. Ce que fait le logiciel

- Interface Windows moderne (style « liquid glass », thème clair/sombre), **sans console**.
- Se connecte à **MetaTrader 5** (déjà installé et connecté à votre compte Exness).
- Surveille jusqu'à 4 actifs : EURUSD, GBPUSD, USDJPY, XAUUSD.
- Stratégie de scalping en M5 (ou M1) : croisement EMA 9/21 dans la tendance (EMA 50/200)
  **ou** rebond sur l'EMA 21, filtre RSI, filtre de spread, plage horaire.
- **Chaque ordre a un stop loss et un take profit** dès l'ouverture (ratio ≥ 1:1).
- Gestion du risque **non désactivable** : 1 % par trade (plafond 2 %), perte max du jour 3 %
  (plafond 10 %), 6 trades/jour max, pause de 10 min après une perte, une position par symbole.
- **Pas de martingale, pas de moyenne à la baisse, jamais de position sans stop loss.**

## 2. Attentes réalistes (à lire absolument)

- **70 $ par jour avec 30 $ de capital, c'est +233 % par jour : impossible de façon durable.**
  Aucun logiciel sérieux ne peut promettre ça.
- Avec 30 $ et 1 % de risque, chaque trade risque **0,30 $**. Un bon résultat, c'est quelques
  dixièmes de pourcent par jour en moyenne, avec des jours (et des semaines) négatifs.
- **Compte Cent fortement conseillé** : sur un compte Standard, le lot minimal (0,01) avec un
  stop loss de 10 pips risque environ 1 $, soit 3,3 % de 30 $. MonBot **refuse** alors le trade
  (c'est voulu). Sur un compte Cent, 30 $ = 3 000 cents et la taille peut être ajustée finement.

## 3. Arborescence du projet

```
MonBot/
├── .github/
│   └── workflows/
│       └── build.yml            ← compilation automatique sur GitHub
├── assets/                      ← icon.ico est créée automatiquement
├── backtest/
│   ├── __init__.py
│   └── backtest.py              ← test de la stratégie sur l'historique
├── bot/
│   ├── __init__.py              ← numéro de version
│   ├── api.py                   ← pont interface ⇄ Python
│   ├── config.py                ← réglages, chemins, mot de passe sécurisé
│   ├── engine.py                ← moteur du bot (thread séparé)
│   ├── indicators.py            ← EMA, RSI, ATR
│   ├── journal.py               ← journaux (fichier + SQLite)
│   ├── mt5_connector.py         ← connexion MetaTrader 5
│   ├── risk.py                  ← gestion du risque
│   └── strategy.py              ← stratégie de scalping
├── installer/
│   └── MonBot.iss               ← script de l'installateur (Inno Setup)
├── tests/                       ← tests automatiques (sans MT5)
├── tools/
│   └── make_icon.py             ← dessine l'icône
├── ui/
│   ├── index.html               ← interface
│   ├── style.css                ← style liquid glass, thèmes
│   └── app.js                   ← comportement de l'interface
├── .gitignore
├── main.py                      ← point d'entrée
├── README.md
├── requirements.txt             ← dépendances du logiciel (versions figées)
└── requirements-dev.txt         ← outils de compilation et de test
```

## 4. Mettre le code sur GitHub (sans rien installer)

1. Créez un compte sur <https://github.com> puis **New repository** : nom `MonBot`,
   cochez **Private** (recommandé), cliquez **Create repository**.
2. Cliquez **uploading an existing file** (ou **Add file › Upload files**).
3. Glissez-déposez **tout le contenu** du dossier `MonBot` (y compris le dossier `.github`).
   Astuce : sous Windows, les dossiers commençant par un point peuvent être masqués.
   Si `.github` n'apparaît pas, créez le fichier à la main : **Add file › Create new file**,
   tapez le nom `.github/workflows/build.yml` et collez le contenu.
4. Cliquez **Commit changes**.

> 🔒 **Ne mettez jamais** votre numéro de compte, mot de passe ou serveur dans un fichier du dépôt.
> Ils se saisissent uniquement dans l'interface de MonBot.

## 5. Compiler (sur GitHub)

1. Dans votre dépôt, onglet **Actions**. Si GitHub le demande, cliquez
   **I understand my workflows, go ahead and enable them**.
2. À gauche, **Compilation MonBot**, puis à droite **Run workflow › Run workflow**.
3. Attendez la coche verte (environ 5 à 10 minutes).
4. Cliquez sur l'exécution terminée, descendez jusqu'à **Artifacts** :
   - **MonBot-Setup** : un `.zip` qui contient `Setup.exe` ← c'est celui-là ;
   - **MonBot-portable** : la version sans installation.

**Option : Release GitHub.** Onglet **Releases › Draft a new release**, dans *Choose a tag*
tapez `v0.1.0` puis *Create new tag*, et **Publish release**. Le workflow se lance tout seul et
ajoute `Setup.exe` à la Release. (Les artefacts expirent après 30 jours, les Releases non.)

Si une étape échoue (croix rouge), cliquez dessus : le message d'erreur est affiché.
L'étape « Tests de logique » échoue si un calcul de risque ou de stratégie est cassé : c'est voulu.

## 6. Installer

1. Décompressez `MonBot-Setup.zip`, double-cliquez sur `Setup.exe`.
2. **Windows SmartScreen** peut afficher « Windows a protégé votre ordinateur » : cliquez
   **Informations complémentaires › Exécuter quand même**. (Le programme n'est pas signé
   numériquement : un certificat de signature coûte plusieurs centaines d'euros par an.)
3. Suivez l'assistant. L'installation ne demande pas les droits administrateur ; une icône
   **MonBot** est créée sur le Bureau et dans le menu Démarrer.
4. Désinstallation : **Paramètres › Applications › MonBot › Désinstaller**.

### Antivirus : faux positif fréquent

Les programmes créés avec PyInstaller sont parfois signalés **à tort** par Windows Defender
(ex. « Trojan:Win32/Wacatac »). C'est un faux positif connu. Que faire :

1. Ne téléchargez `Setup.exe` **que** depuis **votre propre** dépôt GitHub.
2. Signalez le faux positif à Microsoft : <https://www.microsoft.com/wdsi/filesubmission>
   (choisissez « Incorrectly detected as malware »). Ça règle souvent le problème en 1 à 3 jours.
3. En attendant, vous pouvez autoriser le fichier : **Sécurité Windows › Protection contre les
   virus › Historique de protection › Autoriser sur l'appareil**. Ne faites ça que pour un
   fichier que vous avez compilé vous-même.

Le workflow utilise volontairement le mode « dossier » de PyInstaller (`--onedir`), qui
déclenche moins de faux positifs que le mode « fichier unique ».

## 7. Préparer MetaTrader 5

1. Ouvrez **MT5** et connectez-vous à votre compte (démo d'abord !).
2. Cliquez sur le bouton **Algo Trading** de la barre d'outils (il devient vert). Sans lui, tous
   les ordres sont refusés.
3. Lancez MT5 et MonBot avec **les mêmes droits** : tous les deux normalement (recommandé),
   ou tous les deux « en tant qu'administrateur ». Sinon ils ne se « voient » pas.
4. Désactivez la **mise en veille** : Paramètres › Système › Alimentation › Mise en veille : Jamais.
5. MT5 peut être **réduit**, mais **jamais fermé** pendant que le bot tourne.

## 8. Utiliser MonBot

1. Ouvrez MonBot (icône du Bureau).
2. **Connexion MT5** : laissez vide pour utiliser le compte déjà connecté dans MT5 (le plus
   simple). Sinon, saisissez numéro, mot de passe et serveur (ex. `Exness-MT5Trial7`).
   « Mémoriser » range le mot de passe dans le **Gestionnaire d'identifiants Windows**
   (jamais en clair dans un fichier).
3. Cochez les **actifs** (EURUSD et GBPUSD par défaut). Les suffixes Exness (`EURUSDm`,
   `EURUSDc`...) sont détectés automatiquement.
4. Vérifiez les **réglages** puis **Enregistrer**.
5. Cliquez **Démarrer**. Les témoins en haut doivent indiquer : MT5 *Connecté*,
   Algo Trading *Actif*, Compte *DÉMO*.
6. Le **journal** affiche tout : signal détecté, ordre envoyé, signal ignoré (avec la raison),
   TP/SL atteint.
7. **Arrêter** : le bot ne prend plus de trades (les positions ouvertes gardent leur SL/TP).
   **Arrêt d'urgence** : arrête le bot et propose de fermer toutes **ses** positions
   (vos trades manuels ne sont jamais touchés).
8. **Pause annonces** : avant une annonce importante (NFP, décision de la Fed ou de la BCE...),
   mettez le bot en pause 30 à 60 min. Calendrier : <https://www.forexfactory.com/calendar>.

### Les réglages expliqués

| Réglage | Défaut | Rôle |
|---|---|---|
| Risque par trade | 1 % | Perte maximale si le stop loss est touché (plafond 2 %) |
| Perte max du jour | 3 % | Au-delà, le bot s'arrête jusqu'au lendemain (plafond 10 %) |
| Trades max / jour | 6 | Évite de sur-trader (plafond 20) |
| Pause après perte | 10 min | Laisse le marché se calmer |
| Positions simultanées | 2 | Total tous symboles (une seule par symbole) |
| Unité de temps | M5 | M1 = plus de signaux mais plus de bruit et de frais |
| Plage horaire | 09:00-18:00 | Heure de Paris, du lundi au vendredi (Londres + New York) |
| Filtre de tendance | EMA 200 | EMA 50 = plus de signaux, moins filtrés |
| Ratio gain/risque | 1,2 | TP = 1,2 × SL (minimum 1) |
| Stop loss | 1,5 × ATR | S'adapte à la volatilité |
| Spread max | 2 × normale | Ignore les signaux quand le spread s'envole |

### Mode « montants fixes » (gain et perte en argent)

Réglage **Sortie en argent** (activé par défaut) : chaque trade est ouvert avec un take profit
qui rapporte **0,50** et un stop loss qui coûte au maximum **0,70** (montants modifiables, en devise
du compte). Le bot calcule les distances en pips à partir du lot et les pose chez le broker : la
fermeture est automatique, même si le PC s'éteint.

- Plafond de sécurité : la perte fixe ne peut pas dépasser **3 % du capital** (0,90 pour 30 $).
- Le bot **refuse** un trade si la perte fixe ferait dépasser la perte maximale du jour.
  Avec 30 $ et 3 % par jour (0,90), une seule perte de 0,70 bloque donc les trades suivants du jour.
  Pour en autoriser davantage, augmentez « Perte max du jour » (à vos risques).
- Ratio gain/perte = 0,71 : il faut gagner environ 60 % des trades pour ne pas perdre d'argent.
- Backtest : `python -m backtest.backtest --mt5 --symbole EURUSD --mois 6 --gain-fixe 0.50 --perte-fixe 0.70`

### Passer en mode réel

Bouton **Passer en mode réel** (bot arrêté), puis tapez `JE COMPRENDS LES RISQUES`.
Sans cette confirmation, MonBot **refuse de démarrer** sur un compte réel.

### Où sont mes données ?

Dans `%APPDATA%\MonBot` (tapez ce chemin dans la barre de l'Explorateur, ou bouton
**Dossier des journaux**) : `config.json` (réglages), `monbot.db` (trades et événements),
`logs\monbot.log`. **Rien n'est envoyé sur Internet.**

## 9. Tester la stratégie : backtest → démo → réel

### Étape 1 : backtest (sur votre PC)

Le backtest demande Python (déjà installé chez vous) :

```bat
cd chemin\vers\MonBot
pip install -r requirements.txt
```

Puis, MT5 ouvert et connecté :

```bat
python -m backtest.backtest --mt5 --symbole EURUSD --mois 6 --cent
```

Ou avec un fichier exporté depuis MT5 (**Affichage › Symboles › onglet Barres**, choisissez
le symbole, M5, une période, **Requête** puis **Exporter les barres**) :

```bat
python -m backtest.backtest --csv EURUSD_M5.csv --symbole EURUSD --cent
```

Le rapport indique : nombre de trades, taux de réussite, profit factor, **drawdown maximal**,
**résultat net après spread et frais**. Il est aussi enregistré dans `backtest_resultats\`.
Options utiles : `--capital 30`, `--risque 1`, `--commission 0`, `--tendance 50`, `--rr 1.5`.
Pour voir toutes les options : `python -m backtest.backtest --help`.

> Si MT5 renvoie peu de bougies : **Outils › Options › Graphiques › Barres max.** → *Unlimited*.

**Comment lire le résultat ?** Un profit factor sous 1,1 ou un drawdown supérieur à 20 %
= stratégie pas assez solide en l'état. Un bon backtest **ne garantit rien** pour la suite.

### Étape 2 : 1 à 2 mois en démo

Laissez tourner MonBot sur un **compte démo** Exness, pendant les heures normales.
Comparez les résultats avec le backtest. S'ils sont nettement moins bons : ne passez pas en réel.

### Étape 3 : réel (seulement si les étapes 1 et 2 sont convaincantes)

Uniquement avec un capital que vous pouvez perdre entièrement, de préférence sur un compte Cent.

## 10. Dépannage

| Problème | Solution |
|---|---|
| « Connexion à MT5 impossible » | MT5 ouvert et connecté ? Mêmes droits que MonBot ? Essayez de laisser les identifiants vides. |
| « Algo Trading est DÉSACTIVÉ » | Bouton **Algo Trading** dans MT5 (vert), puis Démarrer. Vérifiez aussi Outils › Options › Expert Advisors › « Autoriser le trading algorithmique ». |
| « Compte RÉEL détecté... » | Normal en mode démo : connectez un compte démo, ou activez le mode réel. |
| « Le lot minimal risquerait... » | Capital trop petit pour ce stop loss : compte Cent, ou risque/capital plus élevé. |
| « symbole introuvable » | Affichez le symbole dans le Market Watch de MT5 (clic droit › Symboles). |
| Aucun trade pendant des heures | Normal : la stratégie attend un vrai signal. Regardez le journal (signaux ignorés et raisons). |
| La fenêtre reste blanche | Installez **Microsoft Edge WebView2 Runtime** (déjà présent sur Windows 11) : <https://developer.microsoft.com/microsoft-edge/webview2/>. |
| MonBot ne s'ouvre pas | Lisez `%APPDATA%\MonBot\erreur_demarrage.txt`. |
| Antivirus bloque | Voir section 6 (faux positif). |

## 11. Hypothèses et limites techniques (en toute transparence)

- **Windows uniquement** : la bibliothèque `MetaTrader5` n'existe que sous Windows et exige le
  terminal MT5 ouvert. Le bot ne trade pas si le PC est éteint, en veille, ou sans Internet.
  Pour du 24 h/24, il faudrait un VPS Windows (non couvert ici).
- **Liquid glass** : la réfraction d'Apple n'existe pas sous Windows. MonBot utilise un
  glassmorphism CSS (flou, transparence, reflets). L'effet natif Mica/Acrylic de Windows 11
  n'est **pas activé** : le moteur WebView2 peint un fond opaque, donc Mica serait invisible
  derrière l'interface. Le fond flouté est donc dessiné par l'interface elle-même.
- **Annonces économiques** : il n'existe pas de source gratuite, fiable et officielle facile à
  intégrer. MonBot propose donc une **pause manuelle** plutôt qu'un filtre automatique.
- **Heure** : la plage horaire utilise l'heure de Paris (paquet `tzdata`). Les bougies MT5
  sont en heure du serveur ; Exness utilise GMT+0.
- **Spread « normal »** : calculé comme la médiane du spread des 200 dernières bougies.
- **Frais** : le résultat du jour inclut profit, commission et swap lus dans MT5. Le stop loss
  vaut au moins 3 fois le spread, et le take profit au moins 1 fois le stop loss.
- **Perte max du jour** : quand elle est atteinte, le bot s'arrête mais **ne ferme pas** les
  positions ouvertes (elles gardent leur stop loss). Utilisez l'arrêt d'urgence pour les fermer.
- **Glissement (slippage)** : en réel, le prix d'exécution peut différer légèrement.
- **Mot de passe** : gardé en mémoire uniquement pendant la session, et dans le Gestionnaire
  d'identifiants Windows si vous cochez « Mémoriser ».
- **Versions figées** : les versions de `requirements.txt` ont été choisies pour être
  compatibles entre elles (notamment `numpy 1.26`, compatible avec toutes les versions de
  `MetaTrader5`). Si l'installation échoue un jour, le message d'erreur du workflow indique
  quel paquet changer.
- **Backtest** : basé sur des bougies (pas des ticks) ; quand SL et TP sont touchés dans la
  même bougie, il suppose le stop loss (prudent). L'option `--cent` repose sur l'hypothèse
  « 1 lot Cent = 0,01 lot standard » : vérifiez les spécifications du symbole chez Exness.
- **Bibliothèque MT5 et threads** : tous les appels à MT5 passent par un verrou, car la
  bibliothèque n'est pas garantie utilisable par plusieurs threads en même temps.

## 12. Pour aller plus loin (développeurs)

```bat
pip install -r requirements.txt -r requirements-dev.txt
python main.py                 &:: lance l'interface sans compiler
python -m pytest -q tests      &:: tests de logique
```

---

**Rappel final : le trading comporte un risque de perte en capital. Aucun gain n'est garanti.
MonBot est un outil d'automatisation, pas une promesse de résultat.**
