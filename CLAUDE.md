# CLAUDE.md

Ce fichier fournit des conseils à Claude Code (claude.ai/code) pour travailler avec le code de ce dépôt.

## Présentation du Projet

Pipeline de données Binance en temps réel utilisant :

- **get-data.py** — récupère les données API Binance et écrit JSON dans MinIO (fonctionne en continu)
- **binance_streaming.py** — job Spark : lit les données, les traite, écrit dans MongoDB (s'exécute une fois après mongo-init)
- **Dockerfile.spark** — construit l'image Spark avec pymongo et boto3 préinstallés
- **docker-compose.yml** — orchestre tous les services avec les dépendances appropriées

## Exécution de la Pile

```bash
# Installer les dépendances Python locales
pip install -r requirements.txt

# Démarrer tous les services (entièrement automatisé — aucune étape manuelle)
docker-compose up -d --build

# Attendre ~2 minutes pour l'initialisation complète :
# - mongo-init: initialisation du replica set (~60-80s)
# - collector: commence à récupérer les données Binance
# - spark-job-submitter: traite et écrit dans MongoDB
```

## Surveiller l'Exécution

```bash
# Vérifier que tous les conteneurs s'exécutent
docker-compose ps

# Regarder le job Spark traiter les données
docker logs spark-job-submitter -f

# Vérifier les données dans MongoDB
docker exec mongo-primary mongosh --eval "db.binance_db.realtime_data.count()"
```

## Accès aux Interfaces

- **Mongo Express**: http://localhost:8990 (admin / pwd) — parcourir les collections
- **Spark Master**: http://localhost:8085 — voir le statut du job
- **MinIO Console**: http://localhost:9001 (admin / password123) — voir les buckets

## URLs de Services & Identifiants

| Service             | URL                   | Identifiants        |
| ------------------- | --------------------- | ------------------- |
| MinIO Console       | http://localhost:9001 | admin / password123 |
| Spark Master UI     | http://localhost:8085 | —                   |
| Spark Worker UI     | http://localhost:8081 | —                   |
| Mongo Express       | http://localhost:8990 | admin / pwd         |
| MongoDB primary     | localhost:27017       | admin / pwd         |
| MongoDB secondary-1 | localhost:27018       | admin / pwd         |
| MongoDB secondary-2 | localhost:27019       | admin / pwd         |

## Architecture & Flux de Données

```
API REST Binance (/api/v3/ticker/24hr)
    ↓ get-data.py (boto3 → MinIO)
Bucket MinIO: binance-raw
    input/binance_batch/binance_<ts>.json      (snapshot ponctuel)
    input/binance_streaming/binance_<ts>.json  (tous les 30s)
    ↓ Spark lit via MinIO Python SDK (pas de S3A — contourne les problèmes de compatibilité Hadoop)
Spark (binance_streaming.py)
    - lit JSON avec Minio.get_object() → dictionnaire Python
    - crée DataFrame à partir du dict
    - cast les types, ajoute timestamp/date, calcule priceMovement %
    - filtre les enregistrements avec volume zéro
    ↓ PyMongo écrit directement dans MongoDB Replica Set
MongoDB Replica Set rs0 (primary auto-élu, 2 secondaires se synchronisent automatiquement)
    mongo-primary:27017  ←→  mongo-secondary-1:27017  ←→  mongo-secondary-2:27017
    base de données: binance_db, collection: realtime_data
    réplication: réplication async basée sur oplog, ~0s de lag entre les 3 nœuds
```

## MongoDB Replica Set

**Comment il démarre :** `mongo-init` est un conteneur Docker ponctuel (défini dans docker-compose.yml) qui attend que les 3 nœuds soient sains, puis exécute `scripts/mongo-rs-init.sh` pour appeler `rs.initiate()` et créer l'utilisateur admin. Il est idempotent — se réexécute en toute sécurité s'il est déjà initialisé.

**Test de basculement :**

```bash
docker stop mongo-primary       # déclenche l'élection (~10s), un secondary devient primary
docker start mongo-primary      # se réintègre en tant que secondary, se resynchronise automatiquement
```

**Chaîne de connexion du replica set** (utiliser dans tout nouveau code) :

```
mongodb://admin:pwd@mongo-primary:27017,mongo-secondary-1:27017,mongo-secondary-2:27017/?replicaSet=rs0&authSource=admin
```

Cette chaîne est également disponible en tant que `MONGO_URI` dans `.env`.

**Note :** Le replica set s'exécute sans application de `--auth` (pas de keyFile) — adéquat pour le développement. La production nécessiterait un keyFile partagé monté dans les 3 nœuds.

## Connexion MongoDB ✅ TERMINÉE

L'écriture MongoDB dans `binance_streaming.py` utilise **PyMongo directement** avec une connexion au replica set MongoDB :

```python
mongo_uri = "mongodb://mongo-primary:27017,mongo-secondary-1:27017,mongo-secondary-2:27017/?replicaSet=rs0"
client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
db = client["binance_db"]
collection = db["realtime_data"]
collection.insert_many(records)
```

**Statut :** ✅ Fonctionnement end-to-end avec des données Binance réelles (2 959+ enregistrements confirmés dans tous les 3 nœuds)

- Les 3 nœuds MongoDB synchronisés (données identiques, même optime)
- Basculement automatique testé et fonctionnel
- PyMongo gère le basculement du replica set de manière transparente

**Pourquoi PAS S3A ?** Le projet a d'abord essayé Spark S3A pour la lecture MinIO mais a rencontré une incompatibilité de version :

- Hadoop AWS 3.3.4 + Spark 4.1.1 : NumberFormatException lors du parsing de `fs.s3a.threads.keepalivetime`
- Problèmes du résolveur Ivy avec un répertoire de cache inexistant
- Solution : Utiliser directement le SDK Python MinIO (`from minio import Minio`)
  - Pas de S3A, pas de couches Hadoop, plus simple et plus rapide
  - `read_binance_from_minio()` récupère JSON et le passe au DataFrame PySpark
  - **core-site.xml n'est plus utilisé** (conservé pour référence/futur si S3A est nécessaire)

## Traitement du Streaming Binance

**binance_streaming.py** lit les dernières données Binance de MinIO, les transforme avec Spark, et les écrit dans MongoDB :

1. **Lire depuis MinIO** — `read_binance_from_minio()` utilise le SDK Python MinIO :

   ```python
   minio_client = Minio("minio:9000", access_key=..., secret_key=..., secure=False)
   objects = list(minio_client.list_objects("binance-raw", prefix="input/binance_streaming/"))
   latest_obj = sorted(objects, key=lambda x: x.last_modified)[-1]
   data = json.loads(minio_client.get_object(bucket, latest_obj.object_name).read())
   ```

2. **Transformer avec Spark** — créer DataFrame depuis JSON, cast les types, ajouter les champs calculés :

   ```python
   raw_df = spark.createDataFrame(data, schema=schema)
   processed_df = (raw_df
       .withColumn("lastPrice", col("lastPrice").cast(DoubleType()))
       .withColumn("priceMovement", col("priceChange") / (col("lastPrice") - col("priceChange")) * 100)
       .withColumn("timestamp", current_timestamp())
       .withColumn("processingDate", current_date())
   )
   filtered_df = processed_df.filter(col("quoteVolume") > 0)
   ```

3. **Écrire dans MongoDB** — `insert_to_mongodb()` utilise PyMongo :
   ```python
   client = MongoClient("mongodb://mongo-primary:27017,mongo-secondary-1:27017,mongo-secondary-2:27017/?replicaSet=rs0")
   collection = client["binance_db"]["realtime_data"]
   collection.insert_many(records)
   ```

## Statut : Ce qui fonctionne ✅

- ✅ Polling de l'API Binance (get-data.py) — collecte les données réelles du ticker 24h toutes les 30s
- ✅ Lac de données MinIO — 2 959+ enregistrements JSON confirmés dans le bucket
- ✅ Traitement par lot Spark — lit JSON de MinIO, transforme, produit 2 959+ enregistrements traités
- ✅ MongoDB replica set — tous les 3 nœuds initialisés, sains, synchronisés
- ✅ Persistance des données — tous les 2 959 enregistrements synchronisés entre primary + 2 secondaries (optime identique)
- ✅ Basculement — testé : arrêt du primary, secondary élu, réintégration du primary en tant que secondary
- ✅ Pipeline end-to-end — les données circulent de Binance → MinIO → Spark → MongoDB en ~2 min

## Fonctionnalités Planifiées : Tableau de Bord Django

Un service Django (à ajouter à docker-compose) qui lit depuis le replica set MongoDB et affiche un tableau de bord de données en direct avec filtrage basique.

**Fonctionnalités planifiées :**

- Tableau des derniers prix pour tous les symboles, triable par volume / prix / priceMovement
- Filtres : par symbole, plage de dates, prix min/max, volume minimum
- Graphique simple prix-dans-le-temps pour un symbole sélectionné

**Comportement du basculement :** Django se connecte via l'URI du replica set (`MONGO_URI`). PyMongo se reconnecte automatiquement au nouveau primary lorsque le current primary tombe en panne — aucune modification du code n'est nécessaire.

**Connexion planifiée (Django `settings.py`) :**

```python
import os
MONGO_URI = os.environ["MONGO_URI"]  # de .env
```

**Service docker-compose planifié :**

```yaml
dashboard:
  build: ./dashboard
  container_name: dashboard
  env_file: .env
  depends_on:
    mongo-init:
      condition: service_completed_successfully
  ports:
    - "8000:8000"
```

## Améliorations Futures Planifiées

- **WebSocket Streaming** — Remplacer le polling REST par les flux @trade et @depth de Binance (latence plus faible, débit plus élevé)
- **Suivi du Carnet d'Ordres** — Collecter et analyser les données de profondeur du carnet d'ordres, identifier les ordres baleine (>10 BTC)
- **Indicateurs en Temps Réel** — Calculer RSI, moyennes mobiles, imbalance du carnet d'ordres en flux
- **Tiering des Données** — Stockage chaud (30 jours collections time-series MongoDB), stockage froid (5 ans Parquet dans MinIO)
- **Bougies OHLCV** — Générer des agrégations 1min, 4h, 1jour, hebdomadaires
- **Fonctionnalités ML** — Indicateurs techniques, métriques de flux d'ordres, caractéristiques microstructurelles, mesures de volatilité
- **Remplissage Historique** — Récupérer 5 ans de klines Binance via l'API REST
- **Mode Streaming** — Convertir le job Spark du batch (s'exécute une fois) au streaming continu/micro-batch

## Fichiers de Configuration Clés

- **core-site.xml** — Configuration S3A (conservée pour référence, n'est pas actuellement utilisée par le pipeline — MinIO accédé via SDK Python)
- **Dockerfile.spark** — Image Spark simple : juste pip install `requirements.txt` (inclut minio, pymongo, boto3)
- **scripts/mongo-rs-init.sh** — script d'initialisation ponctuelle du replica set exécuté par le conteneur `mongo-init`
- **.env** — source unique de vérité pour toutes les identifiants ; ne jamais commiter ce fichier

## Schéma

Champs produits par `binance_streaming.py` après traitement :

| Champ            | Type      | Source                                                  |
| ---------------- | --------- | ------------------------------------------------------- |
| symbol           | String    | API Binance                                             |
| lastPrice        | Double    | API Binance                                             |
| volume           | Double    | API Binance                                             |
| quoteVolume      | Double    | API Binance                                             |
| priceChange      | Double    | API Binance                                             |
| weightedAvgPrice | Double    | API Binance                                             |
| timestamp        | Timestamp | ajouté par le job Spark                                 |
| processingDate   | Date      | ajouté par le job Spark                                 |
| priceMovement    | Double    | calculé: priceChange / (lastPrice - priceChange) \* 100 |
