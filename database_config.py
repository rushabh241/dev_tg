"""
Shared database configuration file to be imported by both app1.py and gem.py
This ensures both applications use the same database file
"""

# import os

# # Define the base project directory (location of this file)
# BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# # Define instance folder path
# INSTANCE_PATH = os.path.join(BASE_DIR, 'instance')

# # Ensure instance folder exists
# if not os.path.exists(INSTANCE_PATH):
#     os.makedirs(INSTANCE_PATH)

# # Database filename
# DB_FILENAME = "tender_analyzer.db"

# # Full path to the database file
# DB_PATH = os.path.join(INSTANCE_PATH, DB_FILENAME)

# # SQLAlchemy URI for the database
# SQLALCHEMY_DATABASE_URI = f"sqlite:///{DB_PATH}"

# # For debugging
# def print_db_path():
#     """Print database path information for debugging"""
#     print(f"Base directory: {BASE_DIR}")
#     print(f"Instance path: {INSTANCE_PATH}")
#     print(f"Database path: {DB_PATH}")
#     print(f"SQLAlchemy URI: {SQLALCHEMY_DATABASE_URI}")
#     print(f"Database exists: {os.path.exists(DB_PATH)}")


# PostgreSQL connection settings
POSTGRES_USER = "postgres"
POSTGRES_PASSWORD = "rushabh"
POSTGRES_DB = "tender_analyzer"
POSTGRES_HOST = 'db' #"host.docker.internal" # inside docker the host is db, NOT host.docker.internal
POSTGRES_PORT = 5432

# SQLAlchemy URI for PostgreSQL
SQLALCHEMY_DATABASE_URI = (
    f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

# Optional: echo SQL queries for debugging
SQLALCHEMY_ECHO = False

# For debugging connection
def print_db_info():
    """Print PostgreSQL connection info for debugging"""
    print(f"Postgres User: {POSTGRES_USER}")
    print(f"Postgres Password: {POSTGRES_PASSWORD}")
    print(f"Postgres DB: {POSTGRES_DB}") 
    print(f"Host: {POSTGRES_HOST}")
    print(f"Port: {POSTGRES_PORT}")
    print(f"SQLAlchemy URI: {SQLALCHEMY_DATABASE_URI}")


from sqlalchemy import create_engine

engine = create_engine(SQLALCHEMY_DATABASE_URI, echo=SQLALCHEMY_ECHO)
