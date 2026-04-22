import os
import requests
import json
import boto3
from time import sleep
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# 1. CONFIGURATION DU STOCKAGE (MinIO)
s3 = boto3.client('s3',
    endpoint_url=os.environ.get("MINIO_ENDPOINT_LOCAL", "http://localhost:9000"),
    aws_access_key_id=os.environ.get("MINIO_ACCESS_KEY"),
    aws_secret_access_key=os.environ.get("MINIO_SECRET_KEY"),
    region_name='us-east-1'
)

BUCKET_NAME = 'binance-raw'

def ensure_bucket():
    try:
        s3.head_bucket(Bucket=BUCKET_NAME)
    except Exception:
        s3.create_bucket(Bucket=BUCKET_NAME)
        print(f"✅ Bucket '{BUCKET_NAME}' créé.")

def save_to_minio(data, folder):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = f"{folder}/binance_{ts}.json"

    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=file_path,
        Body=json.dumps(data).encode('utf-8')
    )
    print(f"✅ Données sauvegardées dans MinIO : {file_path}")

ensure_bucket()

# --- ÉTAPE A : Création du fichier Batch (Une seule fois au début) ---
print("Récupération du snapshot Batch...")
try:
    r_batch = requests.get("https://api.binance.com/api/v3/ticker/24hr")
    save_to_minio(r_batch.json(), "input/binance_batch")
except Exception as e:
    print(f"Erreur Batch: {e}")

# --- ÉTAPE B : Flux Streaming (Toutes les 30 secondes) ---
print("Lancement du flux Streaming (Boucle 30s)...")
while True:
    try:
        r_stream = requests.get("https://api.binance.com/api/v3/ticker/24hr")
        save_to_minio(r_stream.json(), "input/binance_streaming")
        sleep(30)
    except KeyboardInterrupt:
        print("\nStreaming arrêté.")
        break
    except Exception as e:
        print(f"Erreur Streaming: {e}")
        sleep(5)
