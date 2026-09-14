# Lavex — Chatbot de production

Chatbot en français permettant d'interroger en langage naturel les données de production stockées en base SQLite, via une architecture hybride NLU + LLM de secours.

## Objectif

Lavex répond à des questions du type *« quel est le cumul CAD de la semaine dernière ? »* ou *« le rendement d'hier ? »* en s'appuyant sur des données de production issues d'un fichier Excel, chargées et normalisées en base SQLite. L'outil est pensé pour être utilisé par des personnes non techniques, sans passer par un terminal (via une interface graphique Tkinter).

## Architecture

Le pipeline fonctionne en deux couches, orchestrées par `main.py` :

1. **Couche règles (`nlu_lavex.py`)** — Résolution déterministe de la métrique et de la période demandées via mots-clés et expressions temporelles (aujourd'hui, hier, avant-hier, semaine dernière, date précise...). Si la question est reconnue, la réponse est calculée et renvoyée directement, sans appel LLM.
2. **Couche LLM de secours (`llm_fallback_lavex.py`)** — Si les règles ne reconnaissent pas la question, un unique appel à l'API Groq (modèle `openai/gpt-oss-120b`, function calling forcé) extrait la métrique et la période sous forme de JSON structuré. **Le LLM ne voit jamais les données de production et ne rédige jamais la réponse finale** : il ne fait qu'extraire des paramètres, qui sont ensuite passés aux mêmes fonctions `compute()` et `format_response()` que la couche règles. Cela élimine tout risque d'hallucination de chiffres.

```
Question utilisateur
        │
        ▼
  nlu_lavex.parse_question()  ──► reconnue ? ──► oui ──► réponse (déterministe)
        │
        │ non
        ▼
  llm_fallback_lavex.llm_fallback()
        │  (1 seul appel API, extraction JSON uniquement)
        ▼
  nlu_lavex.compute() + format_response()  ──► réponse (déterministe)
```

## Structure du projet

```
.
├── main.py                  # Point d'entrée CLI
├── gui_lavex.py              # Interface graphique Tkinter (thème blanc/vert)
├── etl_lavex.py              # ETL Excel -> SQLite (chargement incrémental)
├── src/
│   ├── nlu_lavex.py           # Couche règles + calcul + formatage FR
│   └── llm_fallback_lavex.py  # Fallback LLM (Groq, function calling)
├── test_nlu_lave.py          # Jeu de tests de la couche NLU
├── lavex-historique.xlsx     # Données source (Excel)
├── lavex_releves.db          # Base SQLite générée par l'ETL
├── .env                      # GROQ_API_KEY (non versionné)
└── .gitignore
```

## Prérequis

- Python 3.10+
- Une clé API [Groq](https://console.groq.com/)

## Installation

```bash
git clone <url-du-repo>
cd lavex
pip install -r requirements.txt
```

Créer un fichier `.env` à la racine avec :

```
GROQ_API_KEY=votre_clé_api
```

## Utilisation

### 1. Charger les données

```bash
python etl_lavex.py lavex-historique.xlsx
```

Ce script peut être relancé à volonté : il ne recharge que les nouvelles lignes (déduplication via `date_reception`), ce qui permet de mettre à jour la base incrémentalement à mesure que le fichier Excel évolue.

### 2. Lancer le chatbot (mode terminal)

```bash
python main.py
```

### 3. Lancer l'interface graphique

```bash
python gui_lavex.py
```

### 4. Lancer les tests

```bash
python test_nlu_lave.py
```

## Types de réponses : statistique vs comparaison

Le chatbot distingue deux catégories de questions, chacune avec son propre pipeline de résolution et de formatage :

### Réponse « statistique »

Une question portant sur **une seule métrique**, sur **une seule période** (ex. *« quel est le cumul CAD de la semaine dernière ? »*). Le pipeline est :

```
resolve_metric() + resolve_period()  →  compute()  →  format_response()
```

Le résultat est une valeur unique (somme pour un cumul, moyenne pour un taux/débit) accompagnée du détail jour par jour sur la période.

### Réponse « comparaison »

Une question demandant de **mettre en regard deux périodes** (voire deux métriques) l'une par rapport à l'autre (ex. *« compare le rendement de cette semaine et de la semaine dernière »*, *« le CAD a-t-il augmenté par rapport à hier ? »*). Le pipeline est :

```
resolve_intent()  →  resolve_metrics() + resolve_periods()  →  compute_comparison()  →  format_comparison_response()
```

Contrairement à la réponse statistique, la réponse de comparaison calcule un total pour **chacune des deux périodes**, puis exprime l'écart entre les deux (différence absolue et/ou en pourcentage), en réutilisant `compute()` en interne pour garantir la même logique de calcul (somme vs moyenne selon la métrique).

### Pourquoi cette distinction ?

- **Détection d'intention** : `resolve_intent()` regarde en premier si la question contient un marqueur de comparaison (« compare », « par rapport à », « vs », « a augmenté/diminué », deux périodes citées...). Si oui, la question part sur le pipeline comparaison ; sinon, sur le pipeline statistique.
- **Formatage différent** : `format_response()` produit une phrase avec un total et un détail journalier ; `format_comparison_response()` produit une phrase qui met en avant l'écart entre deux valeurs, plus explicitement orientée vers l'évolution (hausse/baisse).
- **Function calling LLM** : le fallback LLM dispose de **deux outils distincts** (`extraire_requete_production` pour le cas statistique, `extraire_comparaison_production` pour le cas comparaison), afin que le modèle extraie les bons paramètres — une seule période pour l'un, deux périodes pour l'autre — sans jamais produire lui-même le texte de réponse ni voir les chiffres.

## Métriques disponibles

Cumuls (CAD, SL3, stockage ST110, destockage RL2), rendement (RP), coarse reject / taux de coarse reject, turbidité, débit de soutirage décanteur, débit pompe process water. Voir `METRIC_KEYWORDS` dans `nlu_lavex.py` pour la liste complète des mots-clés reconnus.

## Points d'attention techniques

- **Date de référence** : `reference_date` est calculée comme `MAX(date_iso)` en base moins un jour pour « hier », et non l'horloge système — utile si l'ETL n'a pas encore tourné pour la journée en cours.
- **Cumuls par shift** : les cumuls se réinitialisent à chaque changement de shift (Night → Day). Le cumul du jour est donc la somme des cumuls de fin de shift Day et Night pour cette date.
- **Sécurité des secrets** : le fichier `.env` est ignoré par Git. Si un fichier contenant des secrets a déjà été suivi par erreur, utiliser `git rm --cached <fichier>` avant de committer le `.gitignore`.

## Méthodologie de gestion des dates

Cette section détaille la logique utilisée dans tout le projet pour traduire une expression temporelle en français (« hier », « cette semaine », « le mois dernier »...) en dates exploitables par la base de données.

### Une date de référence dynamique, jamais l'horloge système

Partout dans le code (`nlu_lavex.py`, `llm_fallback_lavex.py`, `gui_lavex.py`, `main.py`), « aujourd'hui » n'est **jamais** `date.today()` en usage normal, mais toujours :

```python
reference_date = MAX(date_iso) dans la base SQLite
```

Si l'ETL n'a pas encore tourné pour la journée en cours (connexion coupée, données pas encore publiées côté usine), l'horloge système dirait qu'on est aujourd'hui alors que la dernière donnée en base date de la veille. Toutes les expressions relatives sont donc calculées par rapport à ce que la base *sait vraiment*. `date.today()` n'est utilisé qu'en tout dernier recours, si la base est vide ou inaccessible.

### Un format canonique unique : ISO (`AAAA-MM-JJ`)

Dès l'ETL, toute date est convertie une fois pour toutes :

```python
df["date_iso"] = pd.to_datetime(df["date"], dayfirst=True).dt.strftime("%Y-%m-%d")
```

Ce format ISO est la clé de comparaison/tri utilisée dans toute la base (`WHERE date_iso = ?`, `MAX(date_iso)`, index dédié `idx_date_iso`). L'utilisateur écrit en JJ/MM/AAAA — la conversion entre les deux formats se fait uniquement aux points d'entrée (parsing de la question) et de sortie (affichage), jamais en interne.

### Traduction du langage naturel en liste de dates ISO

C'est le rôle de `resolve_period()` / `resolve_periods()` dans `nlu_lavex.py`. Une période n'est jamais un simple `(date_debut, date_fin)` passé tel quel à SQL : elle est toujours explosée en liste de dates ISO individuelles, car le calcul journalier (`daily_value()`) doit être fait jour par jour, notamment pour appliquer correctement la logique de reset par shift sur les cumuls.

### Cas particulier : « cette semaine » va du lundi jusqu'à aujourd'hui, pas jusqu'à dimanche

```python
if "cette semaine" in q or "semaine en cours" in q:
    this_monday = reference_date - timedelta(days=reference_date.weekday())
    dates = [(this_monday + timedelta(days=i)).isoformat()
              for i in range(reference_date.weekday() + 1)]
    return dates, "cette semaine"
```

**Étape 1 — trouver le lundi de la semaine en cours.**
`reference_date.weekday()` renvoie un entier de 0 (lundi) à 6 (dimanche). En reculant de `weekday()` jours par rapport à `reference_date`, on retombe toujours sur le lundi de cette même semaine calendaire.

Exemple : si `reference_date` est un jeudi (`weekday() == 3`), `this_monday = reference_date - 3 jours`.

**Étape 2 — construire la liste des jours, du lundi jusqu'à aujourd'hui inclus.**
`range(reference_date.weekday() + 1)` est la clé de cette logique :

| Jour de `reference_date` | `weekday()` | `range(...)` | Jours générés |
|---|---|---|---|
| Lundi | 0 | `range(1)` | `[lundi]` |
| Mardi | 1 | `range(2)` | `[lundi, mardi]` |
| Jeudi | 3 | `range(4)` | `[lundi, mardi, mercredi, jeudi]` |
| Dimanche | 6 | `range(7)` | Les 7 jours complets |

Le `+ 1` est nécessaire car `range()` exclut sa borne supérieure : pour couvrir 4 jours (lundi à jeudi inclus), il faut `range(4)`, d'où `weekday() + 1`.

**Pourquoi ne pas générer toute la semaine calendaire (lundi à dimanche) ?**
Parce qu'on ne peut pas donner de statistiques sur des jours futurs par rapport aux données disponibles. Si on est jeudi et que la base n'a pas encore de données pour vendredi/samedi/dimanche, inclure ces dates produirait des valeurs manquantes (`None`) inutiles dans `daily_value()`, et fausserait la moyenne pour les métriques de type `RATE_METRICS` (RP, taux de coarse reject, turbidité, débits) en comptant des jours sans données comme s'ils existaient.

**Comparaison avec « la semaine dernière », qui elle prend bien les 7 jours :**

```python
if "derniere semaine" in q or "semaine derniere" in q or "semaine passee" in q:
    this_monday = reference_date - timedelta(days=reference_date.weekday())
    last_monday = this_monday - timedelta(days=7)
    dates = [(last_monday + timedelta(days=i)).isoformat() for i in range(7)]
    return dates, "la semaine derniere"
```

| Expression | Point de départ | Point d'arrivée | Nombre de jours |
|---|---|---|---|
| « cette semaine » | Lundi de la semaine de `reference_date` | `reference_date` (aujourd'hui) | Variable (1 à 7) |
| « la semaine dernière » | Lundi de la semaine précédente | Dimanche de la semaine précédente | Toujours 7 |

La semaine dernière est par définition entièrement écoulée : elle a donc toujours 7 jours de données potentiellement disponibles. La semaine en cours, elle, est par nature incomplète — cette asymétrie dans le code n'est pas un oubli mais une conséquence directe et volontaire de ce principe.

Cette même logique (lundi → aujourd'hui) est dupliquée à l'identique dans `_period_from_type()` de `llm_fallback_lavex.py` (cas `"this_week"`), afin que le chemin LLM et le chemin règles produisent exactement le même résultat pour une même question.

## Stack technique

- Python, SQLite, pandas
- Tkinter (interface graphique)
- API Groq — modèle `openai/gpt-oss-120b` (function calling)
