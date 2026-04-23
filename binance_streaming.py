import os
import sys
import json
from pyspark.sql import SparkSession  # pyright: ignore[reportMissingImports]
from pyspark.sql.functions import col, current_date, current_timestamp, when  # pyright: ignore[reportMissingImports]
from pyspark.sql.types import DoubleType, StringType, StructField, StructType  # pyright: ignore[reportMissingImports]
from pymongo import MongoClient
from datetime import datetime
from minio import Minio  # pyright: ignore[reportMissingImports]

# Schema for Binance data
schema = StructType([
    StructField("symbol", StringType(), True),
    StructField("lastPrice", StringType(), True),
    StructField("volume", StringType(), True),
    StructField("quoteVolume", StringType(), True),
    StructField("priceChange", StringType(), True),
    StructField("weightedAvgPrice", StringType(), True),
])

def read_binance_from_minio():
    """Read latest Binance JSON from MinIO using MinIO Python SDK (no S3A)"""
    try:
        minio_client = Minio(
            "minio:9000",
            access_key=os.environ.get("MINIO_ACCESS_KEY"),
            secret_key=os.environ.get("MINIO_SECRET_KEY"),
            secure=False
        )

        bucket = "binance-raw"
        prefix = "input/binance_streaming/"

        # List all objects in the prefix
        print(f"📋 Listing objects in {bucket}/{prefix}...")
        objects = []
        for obj in minio_client.list_objects(bucket, prefix=prefix, recursive=False):
            objects.append(obj)
            print(f"   Found: {obj.object_name} ({obj.last_modified})")

        if not objects:
            print(f"⚠️  No files found in MinIO at {bucket}/{prefix}")
            return None

        # Get the latest file (sorted by last_modified)
        latest_obj = sorted(objects, key=lambda x: x.last_modified)[-1]
        print(f"✅ Using latest file: {latest_obj.object_name}")

        # Download file
        response = minio_client.get_object(bucket, latest_obj.object_name)
        data = json.loads(response.read().decode('utf-8'))

        print(f"✅ Retrieved data with {len(data) if isinstance(data, list) else 1} records")
        return data

    except Exception as e:
        print(f"❌ Failed to read from MinIO: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

def insert_to_mongodb(df, collection_name="realtime_data"):
    """Insert DataFrame records into MongoDB using PyMongo"""
    mongo_uri = "mongodb://mongo-primary:27017,mongo-secondary-1:27017,mongo-secondary-2:27017/?replicaSet=rs0"

    try:
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        db = client["binance_db"]
        collection = db[collection_name]

        # Ping to verify connection
        client.admin.command('ping')
        print(f"✅ Connected to MongoDB")

        records = df.select("*").rdd.map(lambda row: row.asDict()).collect()

        if not records:
            print(f"⚠️  No records to insert into {collection_name}")
            return

        # Convert timestamp and date objects to ISO format strings
        for record in records:
            for key, val in record.items():
                if isinstance(val, datetime):
                    record[key] = val.isoformat()
                elif hasattr(val, 'isoformat'):
                    record[key] = val.isoformat()

        if collection_name == "realtime_data":
            collection.delete_many({})

        result = collection.insert_many(records)
        print(f"✅ Inserted {len(result.inserted_ids)} records into {collection_name}")

        client.close()
    except Exception as e:
        print(f"❌ MongoDB insertion failed: {str(e)}")
        sys.exit(1)


# Spark Session
spark = (
    SparkSession.builder
    .appName("BinanceStreamingProcessor")
    .master("spark://spark-master:7077")
    .getOrCreate()
)

spark.sparkContext.setLogLevel("WARN")

print("=" * 80)
print("📊 BINANCE STREAMING PROCESSOR - MinIO → MongoDB Pipeline")
print("=" * 80)

try:
    # Read from MinIO using MinIO Python SDK (no S3A involved)
    print(f"\n📥 Reading Binance data from MinIO...")
    binance_data = read_binance_from_minio()

    if binance_data is None:
        print("❌ No data in MinIO. Exiting.")
        sys.exit(1)

    if not isinstance(binance_data, list):
        binance_data = [binance_data]

    print(f"✅ Retrieved {len(binance_data)} records from MinIO")

    # Convert to DataFrame
    raw_df = spark.createDataFrame(binance_data, schema=schema)

    # Transform - Cast types and add timestamp
    processed_df = (
        raw_df
        .withColumn("lastPrice",        col("lastPrice").cast(DoubleType()))
        .withColumn("volume",            col("volume").cast(DoubleType()))
        .withColumn("quoteVolume",       col("quoteVolume").cast(DoubleType()))
        .withColumn("priceChange",       col("priceChange").cast(DoubleType()))
        .withColumn("weightedAvgPrice",  col("weightedAvgPrice").cast(DoubleType()))
        .withColumn("timestamp",         current_timestamp())
        .withColumn("processingDate",    current_date())
        .withColumn("priceMovement",
            when(col("lastPrice") - col("priceChange") != 0.0,
                col("priceChange") / (col("lastPrice") - col("priceChange")) * 100.0)
            .otherwise(0.0)
        )
    )

    # Filter records with volume
    filtered_df = processed_df.filter(col("quoteVolume") > 0)

    print(f"\n📊 Processing {filtered_df.count()} records...")
    print("\n📋 Sample data (first 5):")
    filtered_df.select("symbol", "timestamp", "lastPrice", "volume", "priceMovement").show(5, truncate=False)

    # Write to MongoDB
    print(f"\n📤 Writing {filtered_df.count()} records to MongoDB...")
    insert_to_mongodb(filtered_df, "realtime_data")

    print("\n" + "=" * 80)
    print("✅ PIPELINE COMPLETED SUCCESSFULLY")
    print("✅ Data: MinIO → Spark → MongoDB")
    print("=" * 80)

except Exception as e:
    print(f"\n❌ ERROR: {str(e)}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

