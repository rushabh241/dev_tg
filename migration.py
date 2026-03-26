from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError, DataError
from models import (
    db, Tender, Product, Organization, User, Document, GemTender,
    SearchConfiguration, NotificationRecipient, Constraint, RiskAssessment,
    Risk, QAInteraction, BidderQuestionsSet, BidderQuestion, ServiceProductDefinition
)
import os
import datetime
from sqlalchemy import Date, DateTime

# -------------------------------
# DATABASE CONNECTIONS
# -------------------------------
sqlite_uri = "sqlite:///instance/tender_analyzer.db"
# postgres_uri = "postgresql+psycopg2://postgres:rushabh@localhost:5432/tender_analyzer"

postgres_host = os.getenv('POSTGRES_HOST', 'localhost')
postgres_user = os.getenv('POSTGRES_USER', 'postgres')
postgres_password = os.getenv('POSTGRES_PASSWORD', 'rushabh')
postgres_db = os.getenv('POSTGRES_DB', 'tender_analyzer')
postgres_port = os.getenv('POSTGRES_PORT', '5432')

postgres_uri = f"postgresql+psycopg2://{postgres_user}:{postgres_password}@{postgres_host}:{postgres_port}/{postgres_db}"

# postgres_uri = "postgresql+psycopg2://postgres:rushabh@tg_postgres:5432/tender_analyzer"


sqlite_engine = create_engine(sqlite_uri)
postgres_engine = create_engine(postgres_uri)

# Create tables in PostgreSQL (if not exist)
print("🧱 Creating tables in PostgreSQL (if not exist)...")
db.metadata.create_all(postgres_engine)

# Create sessions
SQLiteSession = sessionmaker(bind=sqlite_engine)
PostgresSession = sessionmaker(bind=postgres_engine)

sqlite_session = SQLiteSession()
postgres_session = PostgresSession()

# -------------------------------
# TABLES TO MIGRATE
# -------------------------------
tables = [
    Organization,
    User,
    Constraint,
    ServiceProductDefinition,
    Tender,
    Product,
    Document,
    RiskAssessment,
    Risk,
    QAInteraction,
    GemTender,
    SearchConfiguration,
    NotificationRecipient,
    BidderQuestionsSet,
    BidderQuestion,
]

# Reserved keywords that need quoting
reserved_tables = {'user', 'constraint'}

# -------------------------------
# MIGRATION LOOP
# -------------------------------
for table in tables:
    table_name = table.__tablename__
    quoted_name = f'"{table_name}"' if table_name in reserved_tables else table_name
    print(f"📦 Migrating table: {table_name} ...")
    
    # Fetch all rows from SQLite
    rows = sqlite_session.query(table).all()
    print(f"   Found {len(rows)} rows in SQLite")

    if not rows:
        continue

    migrated_count = 0
    error_count = 0

    for row in rows:
        data = row.__dict__.copy()
        data.pop("_sa_instance_state", None)

        # Remove ID to avoid conflicts
        data.pop('id', None)

        for column in table.__table__.columns:
            if column.name in data and data[column.name] is not None:
                value = data[column.name]

                # Date / DateTime conversion
                if isinstance(column.type, Date) or isinstance(column.type, DateTime):

                    if isinstance(value, str):
                        try:
                            parsed = datetime.datetime.fromisoformat(value)
                        except:
                            for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
                                try:
                                    parsed = datetime.datetime.strptime(value, fmt)
                                    break
                                except:
                                    continue

                        if isinstance(column.type, DateTime):
                            data[column.name] = parsed
                        else:
                            data[column.name] = parsed.date()


        try:
            postgres_session.add(table(**data))
            postgres_session.flush()
            migrated_count += 1
        except (IntegrityError, DataError) as e:
            postgres_session.rollback()
            error_count += 1
            print(f"   ⚠️  Error with row {migrated_count + error_count} in {table_name}: {str(e)[:120]}...")
        except Exception as e:
            postgres_session.rollback()
            error_count += 1
            print(f"   ❌ Unexpected error with row {migrated_count + error_count} in {table_name}: {str(e)[:120]}...")

    try:
        postgres_session.commit()
        print(f"   ✅ Migrated {migrated_count}/{len(rows)} rows to {table_name} (errors: {error_count})")
    except Exception as e:
        postgres_session.rollback()
        print(f"   ❌ Commit failed for {table_name}: {e}")

# -------------------------------
# RESET SEQUENCES
# -------------------------------
print("🔄 Resetting PostgreSQL sequences...")

for table in tables:
    table_name = table.__tablename__
    quoted_name = f'"{table_name}"' if table_name in reserved_tables else table_name
    try:
        # Get max ID
        result = postgres_session.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {quoted_name}"))
        max_id = result.scalar()

        if max_id > 0:
            postgres_session.execute(
                text(f"SELECT setval(pg_get_serial_sequence('{quoted_name}', 'id'), {max_id}, true)")
            )
            print(f"   ✅ Reset sequence for {table_name} to start at {max_id + 1}")
        else:
            print(f"   ⏭️  No data in {table_name}, sequence unchanged")

        postgres_session.commit()
    except Exception as e:
        postgres_session.rollback()
        print(f"   ⚠️  Could not reset sequence for {table_name}: {e}")

# -------------------------------
# VERIFICATION
# -------------------------------
print("🔍 Verifying migration...")
for table in tables:
    table_name = table.__tablename__
    quoted_name = f'"{table_name}"' if table_name in reserved_tables else table_name
    try:
        sqlite_count = sqlite_session.query(table).count()
        result = postgres_session.execute(text(f"SELECT COUNT(*) FROM {quoted_name}"))
        postgres_count = result.scalar()
        status = "✅" if sqlite_count == postgres_count else "⚠️ "
        print(f"   {status} {table_name}: SQLite={sqlite_count}, PostgreSQL={postgres_count}")
    except Exception as e:
        print(f"   ❌ Error verifying {table_name}: {e}")

# -------------------------------
# RELATIONSHIP TESTS
# -------------------------------
print("🔗 Testing database relationships...")
relationship_tests = [
    ("Users with Organizations", 'SELECT u.username, o.name FROM "user" u JOIN organization o ON u.organization_id = o.id LIMIT 3'),
    ("Search Configurations with Users", 'SELECT gc.search_keyword, u.username FROM gem_search_configurations gc JOIN "user" u ON gc.created_by = u.id LIMIT 3'),
    ("Notifications with Configurations", 'SELECT nr.name, gc.search_keyword FROM notification_recipients nr JOIN gem_search_configurations gc ON nr.search_config_id = gc.id LIMIT 3')
]

for test_name, query in relationship_tests:
    try:
        result = postgres_session.execute(text(query))
        rows = result.fetchall()
        print(f"   ✅ {test_name}: {len(rows)} results found")
        for row in rows:
            print(f"      {row}")
    except Exception as e:
        print(f"   ❌ {test_name} failed: {e}")

# -------------------------------
# FINAL SUMMARY
# -------------------------------
print("\n📊 MIGRATION SUMMARY")
print("=" * 50)

total_sqlite = 0
total_postgres = 0
for table in tables:
    table_name = table.__tablename__
    quoted_name = f'"{table_name}"' if table_name in reserved_tables else table_name
    try:
        sqlite_count = sqlite_session.query(table).count()
        result = postgres_session.execute(text(f"SELECT COUNT(*) FROM {quoted_name}"))
        postgres_count = result.scalar()
        total_sqlite += sqlite_count
        total_postgres += postgres_count
        status = "✅" if sqlite_count == postgres_count else "⚠️ "
        print(f"   {status} {table_name:.<30} SQLite: {sqlite_count:3d} → PostgreSQL: {postgres_count:3d}")
    except Exception as e:
        print(f"   ❌ {table_name:.<30} Error: {e}")

print("=" * 50)
print(f"   📈 TOTAL: {total_sqlite} rows in SQLite → {total_postgres} rows in PostgreSQL")
print(f"   {'✅ SUCCESS' if total_sqlite == total_postgres else '⚠️  CHECK REQUIRED'}")

# -------------------------------
# CLOSE SESSIONS
# -------------------------------
sqlite_session.close()
postgres_session.close()
print("🎉 Migration completed successfully!")