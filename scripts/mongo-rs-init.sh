#!/bin/bash
set -e

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
  echo "Replica set already initialized, skipping."
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

echo "Waiting 10s for primary election..."
sleep 10

echo "Creating admin user..."
mongosh --host mongo-primary:27017 --eval "
use admin;
db.createUser({
  user: '${MONGO_USERNAME}',
  pwd:  '${MONGO_PASSWORD}',
  roles: [{ role: 'root', db: 'admin' }]
});
"

echo "Replica set rs0 ready."
