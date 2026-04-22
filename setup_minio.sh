#!/bin/bash

# Script pour initialiser MinIO avec des données de test

echo "🔧 Initialisation de MinIO..."

# Attendre que MinIO soit prêt
sleep 3

# Créer le bucket
docker exec minio /usr/bin/mc mb minio/binance-raw 2>/dev/null || true

# Créer des fichiers JSON de test
cat > /tmp/binance_data_1.json << 'EOF'
{"symbol":"BTCUSDT","lastPrice":"45000.0","volume":"100.5","quoteVolume":"4500000.0","priceChange":"150.0","weightedAvgPrice":"45100.0"}
{"symbol":"ETHUSDT","lastPrice":"2500.0","volume":"500.0","quoteVolume":"1250000.0","priceChange":"50.0","weightedAvgPrice":"2510.0"}
{"symbol":"BNBUSDT","lastPrice":"650.0","volume":"1000.0","quoteVolume":"650000.0","priceChange":"30.0","weightedAvgPrice":"651.0"}
EOF

cat > /tmp/binance_data_2.json << 'EOF'
{"symbol":"SOLUSDT","lastPrice":"180.0","volume":"5000.0","quoteVolume":"900000.0","priceChange":"20.0","weightedAvgPrice":"181.0"}
{"symbol":"ADAUSDT","lastPrice":"1.2","volume":"10000.0","quoteVolume":"12000.0","priceChange":"0.05","weightedAvgPrice":"1.21"}
EOF

# Copier les fichiers dans MinIO
docker cp /tmp/binance_data_1.json minio:/tmp/
docker cp /tmp/binance_data_2.json minio:/tmp/

# Uploader vers le bucket
docker exec minio /usr/bin/mc cp /tmp/binance_data_1.json minio/binance-raw/input/binance_streaming/
docker exec minio /usr/bin/mc cp /tmp/binance_data_2.json minio/binance-raw/input/binance_streaming/

echo "✅ MinIO initialisé avec succès!"
echo "Bucket: s3a://binance-raw/input/binance_streaming/"
