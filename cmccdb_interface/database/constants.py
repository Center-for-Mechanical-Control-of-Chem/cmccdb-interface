
import os
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT =  os.getenv("POSTGRES_PORT", "5432")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_DATABASE = os.getenv("POSTGRES_DATABASE", "cmcc")
SCHEMA_NAME = os.getenv("POSTGRES_SCHEMA_NAME", "cmccdb")