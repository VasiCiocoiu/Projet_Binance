#!/bin/bash
set -e

# Load environment variables if not already set (for docker-compose scenario)
MONGO_USERNAME=${MONGO_USERNAME:-admin}
MONGO_PASSWORD=${MONGO_PASSWORD:-pwd}

ensure_price_history_collection() {
  echo "Ensuring time-series collection 'binance_db.price_history' exists..."
  mongosh --host mongo-primary:27017 --quiet --eval "
const dbName = 'binance_db';
const collName = 'price_history';
const targetDb = db.getSiblingDB(dbName);
const existing = targetDb.getCollectionInfos({ name: collName });

if (existing.length === 0) {
  targetDb.createCollection(collName, {
    timeseries: {
      timeField: 'timestamp',
      metaField: 'metadata',
      granularity: 'minutes'
    }
  });
  print(\"✅ Created time-series collection 'price_history'\");
} else {
  print(\"ℹ️  Time-series collection 'price_history' already exists\");
}

targetDb.price_history.createIndex({ 'metadata.symbol': 1 });
targetDb.price_history.createIndex({ timestamp: -1 });
print(\"✅ Ensured indexes on metadata.symbol and timestamp\");
"
}

echo "Waiting for all MongoDB nodes to start..."
for HOST in mongo-primary:27017 mongo-secondary-1:27017 mongo-secondary-2:27017; do
  until mongosh --host ${HOST} --quiet --eval "db.adminCommand('ping').ok" &>/dev/null 2>&1; do
    echo "  Waiting for ${HOST}..."
    sleep 3
  done
  echo "  ${HOST} ready."
done

# Idempotency: skip if already initialized
RS_OK=$(mongosh --host mongo-primary:27017 --quiet \
  --eval "try{rs.status().ok}catch(e){0}" 2>/dev/null)
if [ "${RS_OK}" = "1" ]; then
  echo "Replica set already initialized, skipping initialization."
  
  # Check if admin user exists, create if missing
  USER_EXISTS=$(mongosh --host mongo-primary:27017 --quiet \
    --eval "try{db.auth('${MONGO_USERNAME}', '${MONGO_PASSWORD}'); 1}catch(e){0}" 2>/dev/null || echo "0")
  
  if [ "${USER_EXISTS}" = "1" ]; then
    echo "Admin user already configured."
  else
    echo "Creating missing admin user..."
    mongosh --host mongo-primary:27017 --eval "
use admin;
db.createUser({
  user: '${MONGO_USERNAME}',
  pwd: '${MONGO_PASSWORD}',
  roles: [{ role: 'root', db: 'admin' }]
});
" || echo "Warning: User might already exist."
  fi

  ensure_price_history_collection
  exit 0
fi

echo "Initializing replica set rs0..."
mongosh --host mongo-primary:27017 --eval "
rs.initiate({
  _id: 'rs0',
  members: [
    { _id: 0, host: 'mongo-primary:27017',     priority: 2 },
    { _id: 1, host: 'mongo-secondary-1:27017', priority: 1 },
    { _id: 2, host: 'mongo-secondary-2:27017', priority: 1 }
  ]
});
"

echo "Waiting 15s for primary election and replica set to stabilize..."
sleep 15

# Verify replica set is initialized
REPLICA_SET_STATUS=$(mongosh --host mongo-primary:27017 --quiet \
  --eval "rs.status().ok" 2>/dev/null || echo "0")

if [ "${REPLICA_SET_STATUS}" != "1" ]; then
  echo "ERROR: Replica set failed to initialize!"
  exit 1
fi

echo "Creating admin user..."
mongosh --host mongo-primary:27017 --eval "
use admin;
db.createUser({
  user: '${MONGO_USERNAME}',
  pwd: '${MONGO_PASSWORD}',
  roles: [{ role: 'root', db: 'admin' }]
});
" || echo "Warning: Admin user creation failed (may already exist)"

ensure_price_history_collection

echo "✓ Replica set rs0 initialized and ready."
echo "✓ Admin credentials: username=${MONGO_USERNAME}"
