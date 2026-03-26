import argparse
import datetime
import os
import shutil
import logging
import uuid
import csv
from flask import Flask
from sqlalchemy import text, create_engine
import config
from models import (
    db,
    Document,
    Product,
    Tender,
    GemTender,
    BidderQuestion,
    BidderQuestionsSet,
    QAInteraction,
    RiskAssessment,
    Risk,
    Organization,
    DataPurgeSummary
)

DEFAULT_DAYS_TO_KEEP = 60
MIN_DAYS_TO_DELETE = 30
EXPORT_DIR = 'old_records_export'
ARCHIVE_DIR = 'archived_documents'

# Create directories if they don't exist
os.makedirs(EXPORT_DIR, exist_ok=True)
os.makedirs(ARCHIVE_DIR, exist_ok=True)

def setup_logging(dry_run=False, org_id=None, run_id=None):
    """Setup logging configuration - single purge.log file in project root"""

    # Directory where purge.py exists
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    # Always write to the same file
    log_path = os.path.join(BASE_DIR, "purge.log")

    # Clear any existing handlers (important when rerunning in same process)
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8", mode="a"),  # append
            logging.StreamHandler()  # console output
        ],
    )

    logging.info("============================================================================")
    logging.info("Purge started | run_id=%s | dry_run=%s | org_id=%s", run_id, dry_run, org_id)
    logging.info("============================================================================")

    return log_path

def create_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app

def get_psycopg2_connection():
    """Get a raw psycopg2 connection from SQLAlchemy engine"""
    engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
    return engine.raw_connection()

def generate_run_id():
    """Generate a unique run ID for each purge operation"""
    # Generate a UUID and format it as a string
    run_uuid = str(uuid.uuid4())
    
    # Create a timestamp-based run ID for better readability
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Combine timestamp with a short UUID
    short_uuid = run_uuid[:8]
    run_id = f"purge_{timestamp}_{short_uuid}"
    
    return run_id


def archive_old_files(document_records, org_id, run_id, dry_run=False):
    """
    Archive old document files from already collected document records
    """
    if not document_records:
        logging.info("No document records to archive")
        return 0

    logging.info(f"\n=== Archiving files ===")
    logging.info(f"Run ID: {run_id}")
    logging.info(f"Organization ID: {org_id}")
    logging.info(f"Dry run: {dry_run}")
    logging.info(f"Found {len(document_records)} document records to process")

    archived_files = 0
    skipped_files = 0
    missing_files = 0

    # Ensure archive directory exists (for logging purposes, even in dry run)
    if not dry_run:
        os.makedirs(ARCHIVE_DIR, exist_ok=True)

    for doc in document_records:
        file_path = doc.get('file_path')
        if not file_path:
            logging.warning(f"SKIP (no file path): Document ID {doc.get('id')}")
            skipped_files += 1
            continue

        # Optional: restrict to PDFs only
        if not file_path.lower().endswith(".pdf"):
            logging.info(f"SKIP (non-PDF): {file_path}")
            skipped_files += 1
            continue

        # Resolve relative paths safely
        if not os.path.isabs(file_path):
            file_path = os.path.abspath(file_path)

        # File missing on disk
        if not os.path.exists(file_path):
            logging.warning(f"MISSING: {file_path}")
            missing_files += 1
            continue

        # In dry run, just log what would happen
        if dry_run:
            # Create archive path directly in ARCHIVE_DIR
            filename = os.path.basename(file_path)
            archive_path = os.path.join(ARCHIVE_DIR, filename)
            
            # Check if file would already exist in archive
            if os.path.exists(archive_path):
                logging.info(f"WOULD SKIP (already in archive): {file_path} -> {archive_path}")
                skipped_files += 1
            else:
                logging.info(f"WOULD ARCHIVE: {file_path} -> {archive_path}")
                archived_files += 1
        else:
            # Actual archiving logic for non-dry run
            try:
                # Create archive path directly in ARCHIVE_DIR
                filename = os.path.basename(file_path)
                archive_path = os.path.join(ARCHIVE_DIR, filename)

                # Move file directly to archive folder
                shutil.move(file_path, archive_path)
                logging.info(f"Archived: {file_path} -> {archive_path}")
                archived_files += 1

            except FileExistsError:
                # If file already exists in archive, skip it
                logging.warning(f"File already exists in archive, skipping: {file_path}")
                skipped_files += 1
            except Exception as e:
                logging.error(f"ERROR archiving {file_path}: {e}")
                skipped_files += 1

    logging.info("\n" + "=" * 50)
    logging.info("FILE ARCHIVAL SUMMARY")
    logging.info("=" * 50)
    logging.info(f"Run ID: {run_id}")
    logging.info(f"Organization ID: {org_id}")
    logging.info(f"Total document records processed: {len(document_records)}")
    logging.info(f"Files archived: {archived_files}")
    logging.info(f"Files missing: {missing_files}")
    logging.info(f"Files skipped: {skipped_files}")
    if not dry_run:
        logging.info(f"Archive location: {ARCHIVE_DIR}/")
    logging.info("=" * 50)
    
    return archived_files

def export_to_csv(old_records_dict, org_id, run_id, dry_run=False):
    """Export old records to common CSV files (not per-org)"""
    try:
        logging.info("\n=== Exporting Old Records to CSV Files ===")
        logging.info(f"Run ID: {run_id}")
        logging.info(f"Organization ID: {org_id}")
        
        # Skip export in dry run
        if dry_run:
            logging.info("DRY RUN: Skipping CSV export")
            return {}

        exported_counts = {}
        
        # Export each model's records to CSV files
        for model_name, records in old_records_dict.items():
            if records:
                # Define CSV filenames
                csv_mappings = {
                    "Tender": "tender.csv",
                    "GemTender": "gem_tenders.csv", 
                    "Risk": "risk.csv",
                    "RiskAssessment": "risk_assessments.csv",
                    "BidderQuestion": "bidder_question.csv",
                    "BidderQuestionsSet": "bidder_questions_set.csv",
                    "QAInteraction": "qa_interaction.csv",
                    "Document": "document.csv",
                }
                
                csv_filename = csv_mappings.get(model_name)
                if not csv_filename:
                    logging.warning(f"No CSV mapping found for model: {model_name}")
                    continue
                
                csv_path = os.path.join(EXPORT_DIR, csv_filename)
                file_exists = os.path.exists(csv_path)

                # Get column names from first record
                if records:
                    # For Document table - exclude 'content_text' column
                    if model_name == "Document":
                        # Get column names from record dict keys, excluding 'content_text'
                        columns = [key for key in records[0].keys() if key != 'content_text']
                        df_data = []
                        for record in records:
                            row = {col: record.get(col) for col in columns}
                            df_data.append(row)
                        logging.info(f"Note: Excluded 'content_text' column from Document export")
                    else:
                        # For all other models, include all columns
                        columns = list(records[0].keys())
                        df_data = records
                    
                    # Write to CSV
                    with open(csv_path, 'a' if file_exists else 'w', newline='', encoding='utf-8-sig') as f:
                        writer = csv.DictWriter(f, fieldnames=columns + ['purge_run_id', 'organization_id'])
                        
                        if not file_exists:
                            writer.writeheader()
                        
                        for record in df_data:
                            # Add purge_run_id and organization_id to each record
                            record_with_metadata = record.copy()
                            record_with_metadata['purge_run_id'] = run_id
                            record_with_metadata['organization_id'] = org_id
                            writer.writerow(record_with_metadata)
                    
                    exported_counts[model_name] = len(records)
                    logging.info(f"Exported {len(records)} records to: {csv_path} (Appended)")
        
        # Print summary
        logging.info("\n=== Export Summary ===")
        total_exported = 0
        for model_name, count in exported_counts.items():
            logging.info(f"{model_name}: {count} records")
            total_exported += count
        
        logging.info(f"\nTotal records exported: {total_exported}")
        logging.info(f"All CSV files saved in: {EXPORT_DIR}/")
        return exported_counts
        
    except Exception as e:
        logging.error("CSV export failed. Skipping export.")
        logging.error(f"Error: {str(e)}")
        return {}

def collect_old_records(days_to_keep, org_id, cursor):
    """Collect old records without exporting them using provided cursor"""
    cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days_to_keep)
    logging.info(f"Collecting records older than {cutoff_date}...")
    
    old_records = {}
    tender_ids = []  # Store tender IDs for reuse
    
    # Build organization filter
    org_filter = None
    if org_id != 'all':
        org_filter = int(org_id)
    
    # --- Collect Tenders (use due_date if valid format, otherwise created_at)
    logging.info("Collecting Tenders...")
    if org_id == 'all':
        # When org_id is 'all', we handle organization-wise in main loop
        query = """
            SELECT *, 
                CASE
                    -- Valid full datetime
                    WHEN due_date ~ '^\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}$'
                        THEN to_timestamp(due_date, 'DD-MM-YYYY HH24:MI:SS')
                    -- Valid date only
                    WHEN due_date ~ '^\d{2}-\d{2}-\d{4}$'
                        THEN to_timestamp(due_date || ' 00:00:00', 'DD-MM-YYYY HH24:MI:SS')
                    ELSE NULL
                END as parsed_due_date
            FROM tender
            WHERE COALESCE(
                CASE
                    -- Valid full datetime
                    WHEN due_date ~ '^\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}$'
                        THEN to_timestamp(due_date, 'DD-MM-YYYY HH24:MI:SS')
                    -- Valid date only
                    WHEN due_date ~ '^\d{2}-\d{2}-\d{4}$'
                        THEN to_timestamp(due_date || ' 00:00:00', 'DD-MM-YYYY HH24:MI:SS')
                    ELSE NULL
                END,
                created_at
            ) < %s
        """
        params = (cutoff_date,)

    else:
        query = """
            SELECT *,
                CASE
                    WHEN due_date ~ '^\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}$'
                        THEN to_timestamp(due_date, 'DD-MM-YYYY HH24:MI:SS')
                    WHEN due_date ~ '^\d{2}-\d{2}-\d{4}$'
                        THEN to_timestamp(due_date || ' 00:00:00', 'DD-MM-YYYY HH24:MI:SS')
                    ELSE NULL
                END as parsed_due_date
            FROM tender
            WHERE COALESCE(
                CASE
                    WHEN due_date ~ '^\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}$'
                        THEN to_timestamp(due_date, 'DD-MM-YYYY HH24:MI:SS')
                    WHEN due_date ~ '^\d{2}-\d{2}-\d{4}$'
                        THEN to_timestamp(due_date || ' 00:00:00', 'DD-MM-YYYY HH24:MI:SS')
                    ELSE NULL
                END,
                created_at
            ) < %s
            AND organization_id = %s
        """
        params = (cutoff_date, org_filter)
    
    cursor.execute(query, params)
    old_tenders = cursor.fetchall()
    column_names = [desc[0] for desc in cursor.description]
    old_tenders_dict = [dict(zip(column_names, row)) for row in old_tenders]
    
    # Log tender records with their actual dates
    for tender in old_tenders_dict:
        if tender['parsed_due_date']:
            logging.info(f"Tender {tender['id']}: using due_date {tender['due_date']}")
        else:
            logging.info(f"Tender {tender['id']}: using created_at {tender['created_at']} (due_date format invalid: {tender['due_date']})")
    
    old_records["Tender"] = old_tenders_dict
    
    # Store tender IDs for reuse in other queries
    if old_tenders_dict:
        tender_ids = [tender['id'] for tender in old_tenders_dict]
        
        if tender_ids:
            # Create placeholders for IN clause
            placeholders = ",".join(["%s"] * len(tender_ids))
            
            # --- Collect Documents using stored tender IDs
            logging.info("Collecting Documents...")
            query = f"""
                SELECT * FROM document 
                WHERE tender_id IN ({placeholders})
            """
            cursor.execute(query, tender_ids)
            old_documents = cursor.fetchall()
            column_names = [desc[0] for desc in cursor.description]
            old_records["Document"] = [dict(zip(column_names, row)) for row in old_documents]
            
            # --- Collect QA Interactions using stored tender IDs
            logging.info("Collecting QAInteractions...")
            query = f"""
                SELECT * FROM qa_interaction 
                WHERE tender_id IN ({placeholders})
            """
            cursor.execute(query, tender_ids)
            old_qas = cursor.fetchall()
            column_names = [desc[0] for desc in cursor.description]
            old_records["QAInteraction"] = [dict(zip(column_names, row)) for row in old_qas]
            
            # --- Collect Risk Assessments using stored tender IDs
            logging.info("Collecting RiskAssessments...")
            query = f"""
                SELECT * FROM risk_assessment 
                WHERE tender_id IN ({placeholders})
            """
            cursor.execute(query, tender_ids)
            old_risk_assessments = cursor.fetchall()
            column_names = [desc[0] for desc in cursor.description]
            old_records["RiskAssessment"] = [dict(zip(column_names, row)) for row in old_risk_assessments]
            
            if old_risk_assessments:
                risk_assessment_ids = [ra['id'] for ra in old_records["RiskAssessment"]]
                
                # Collect Risks
                logging.info("Collecting Risks...")
                risk_placeholders = ",".join(["%s"] * len(risk_assessment_ids))
                query = f"""
                    SELECT * FROM risk 
                    WHERE assessment_id IN ({risk_placeholders})
                """
                cursor.execute(query, risk_assessment_ids)
                old_risks = cursor.fetchall()
                column_names = [desc[0] for desc in cursor.description]
                old_records["Risk"] = [dict(zip(column_names, row)) for row in old_risks]
            
            # --- Collect Bidder Question Sets and Questions using stored tender IDs
            logging.info("Collecting BidderQuestionSets...")
            query = f"""
                SELECT * FROM bidder_questions_set 
                WHERE tender_id IN ({placeholders})
            """
            cursor.execute(query, tender_ids)
            old_bidder_questions_set = cursor.fetchall()
            column_names = [desc[0] for desc in cursor.description]
            old_records["BidderQuestionsSet"] = [dict(zip(column_names, row)) for row in old_bidder_questions_set]

            if old_bidder_questions_set:
                old_bidder_questions_set_ids = [bqs['id'] for bqs in old_records["BidderQuestionsSet"]]
                
                # Collect Bidder Questions
                logging.info("Collecting BidderQuestions...")
                if old_bidder_questions_set_ids:
                    bqs_placeholders = ",".join(["%s"] * len(old_bidder_questions_set_ids))
                    query = f"""
                        SELECT * FROM bidder_question 
                        WHERE question_set_id IN ({bqs_placeholders})
                    """
                    cursor.execute(query, old_bidder_questions_set_ids)
                    old_bidder_questions = cursor.fetchall()
                    column_names = [desc[0] for desc in cursor.description]
                    old_records["BidderQuestion"] = [dict(zip(column_names, row)) for row in old_bidder_questions]
                else:
                    old_records["BidderQuestion"] = []
            else:
                old_records["BidderQuestion"] = []
                old_records["BidderQuestionsSet"] = []
    
    # --- Collect Gem Tenders (based on due_date only - keep original logic)
    logging.info("Collecting GemTenders...")
    if org_id == 'all':
        query = """
            SELECT *
            FROM gem_tenders
            WHERE 
                CASE
                    -- Full datetime format
                    WHEN due_date ~ '^\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}$'
                    THEN to_timestamp(due_date, 'DD-MM-YYYY HH24:MI:SS')
                    
                    -- Date-only format, assume 00:00:00
                    WHEN due_date ~ '^\d{2}-\d{2}-\d{4}$'
                    THEN to_timestamp(due_date || ' 00:00:00', 'DD-MM-YYYY HH24:MI:SS')
                    
                    ELSE NULL
                END < %s
        """
        params = (cutoff_date,)

    else:
        query = """
            SELECT *
            FROM gem_tenders
            WHERE 
                CASE
                    WHEN due_date ~ '^\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}$'
                    THEN to_timestamp(due_date, 'DD-MM-YYYY HH24:MI:SS')
                    
                    WHEN due_date ~ '^\d{2}-\d{2}-\d{4}$'
                    THEN to_timestamp(due_date || ' 00:00:00', 'DD-MM-YYYY HH24:MI:SS')
                    
                    ELSE NULL
                END < %s
                AND organization_id = %s
        """
        params = (cutoff_date, org_filter)
    
    cursor.execute(query, params)
    old_gem_tenders = cursor.fetchall()
    column_names = [desc[0] for desc in cursor.description]
    old_records["GemTender"] = [dict(zip(column_names, row)) for row in old_gem_tenders]

    # Ensure all expected keys exist in old_records
    expected_keys = ["Tender", "GemTender", "Risk", "RiskAssessment", 
                    "BidderQuestion", "BidderQuestionsSet", "QAInteraction", "Document"]
    for key in expected_keys:
        if key not in old_records:
            old_records[key] = []

    # Count records
    total_records = 0
    logging.info("\n=== Collection Summary ===")
    for model_name, records in old_records.items():
        if records:
            logging.info(f"Collected {len(records)} {model_name} records")
            total_records += len(records)
    
    if total_records > 0:
        logging.info(f"\nTotal records collected: {total_records}")
    else:
        logging.info("\nNo old records found")
    
    return old_records, total_records, tender_ids


def purge_organization(days_to_keep, org_id, run_id, cursor, dry_run=False):
    """
    Purge records for a specific organization
    """
    archived_count = 0
    exported_counts = {}
    deletion_counts = {}
    tender_ids = []
    
    try:
        # Step 1: Collect old records for this organization
        old_records, total_collected, tender_ids = collect_old_records(days_to_keep, org_id, cursor)
        
        if total_collected > 0:
            # Step 2: Archive files for this organization (using collected document records)
            document_records = old_records.get("Document", [])
            archived_count = archive_old_files(document_records, org_id, run_id, dry_run)
            
            # Step 3: Export records to CSV (only if not dry run)
            if not dry_run:
                exported_counts = export_to_csv(old_records, org_id, run_id, dry_run)
            
            # Step 4: Delete records (ONLY if not dry run)
            if not dry_run:
                # Start transaction for this organization
                cursor.execute("BEGIN")
                
                if tender_ids:
                    # Create placeholders for IN clause
                    placeholders = ",".join(["%s"] * len(tender_ids))
                    
                    # --- Delete Bidder Question Sets and Questions (based on tender IDs)
                    logging.info("\n--- Deleting Bidder Question Records ---")
                    
                    # First get bidder question set IDs
                    query = f"""
                        SELECT id FROM bidder_questions_set 
                        WHERE tender_id IN ({placeholders})
                    """
                    cursor.execute(query, tender_ids)
                    old_bidder_questions_set_ids = [row[0] for row in cursor.fetchall()]
                    
                    if old_bidder_questions_set_ids:
                        # Create placeholders for bidder question sets
                        bqs_placeholders = ",".join(["%s"] * len(old_bidder_questions_set_ids))
                        
                        # Delete bidder questions
                        query = f"""
                            DELETE FROM bidder_question 
                            WHERE question_set_id IN ({bqs_placeholders})
                        """
                        cursor.execute(query, old_bidder_questions_set_ids)
                        deleted_questions = cursor.rowcount
                        deletion_counts["BidderQuestion"] = deleted_questions
                        logging.info(f"Deleted {deleted_questions} bidder questions")
                        
                        # Delete bidder question sets
                        query = f"""
                            DELETE FROM bidder_questions_set 
                            WHERE id IN ({bqs_placeholders})
                        """
                        cursor.execute(query, old_bidder_questions_set_ids)
                        deleted_question_sets = cursor.rowcount
                        deletion_counts["BidderQuestionsSet"] = deleted_question_sets
                        logging.info(f"Deleted {deleted_question_sets} bidder question sets")
                    else:
                        deletion_counts["BidderQuestion"] = 0
                        deletion_counts["BidderQuestionsSet"] = 0
                        logging.info("No bidder question sets found to delete")

                    # --- Delete QA Interactions (based on tender IDs)
                    logging.info("\n--- Deleting QA Interaction Records ---")
                    query = f"""
                        DELETE FROM qa_interaction 
                        WHERE tender_id IN ({placeholders})
                    """
                    cursor.execute(query, tender_ids)
                    deleted_qas = cursor.rowcount
                    deletion_counts["QAInteraction"] = deleted_qas
                    logging.info(f"Deleted {deleted_qas} QA interactions")

                    # --- Delete Risk Assessments and Risks (based on tender IDs)
                    logging.info("\n--- Deleting Risk Assessment Records ---")
                    
                    # First get risk assessment IDs
                    query = f"""
                        SELECT id FROM risk_assessment 
                        WHERE tender_id IN ({placeholders})
                    """
                    cursor.execute(query, tender_ids)
                    old_risk_assessment_ids = [row[0] for row in cursor.fetchall()]
                    
                    if old_risk_assessment_ids:
                        # Create placeholders for risk assessments
                        ra_placeholders = ",".join(["%s"] * len(old_risk_assessment_ids))
                        
                        # Delete risks
                        query = f"""
                            DELETE FROM risk 
                            WHERE assessment_id IN ({ra_placeholders})
                        """
                        cursor.execute(query, old_risk_assessment_ids)
                        deleted_risks = cursor.rowcount
                        deletion_counts["Risk"] = deleted_risks
                        logging.info(f"Deleted {deleted_risks} risks")
                        
                        # Delete risk assessments
                        query = f"""
                            DELETE FROM risk_assessment 
                            WHERE id IN ({ra_placeholders})
                        """
                        cursor.execute(query, old_risk_assessment_ids)
                        deleted_assessments = cursor.rowcount
                        deletion_counts["RiskAssessment"] = deleted_assessments
                        logging.info(f"Deleted {deleted_assessments} risk assessments")
                    else:
                        deletion_counts["Risk"] = 0
                        deletion_counts["RiskAssessment"] = 0
                        logging.info("No risk assessments found to delete")

                    # --- Delete Documents, Tenders, Products
                    logging.info("\n--- Deleting Tender Records ---")
                    
                    # Delete documents first (they were already archived)
                    query = f"""
                        DELETE FROM document 
                        WHERE tender_id IN ({placeholders})
                    """
                    cursor.execute(query, tender_ids)
                    deleted_documents = cursor.rowcount
                    deletion_counts["Document"] = deleted_documents
                    logging.info(f"Deleted {deleted_documents} documents")
                    
                    # Delete products
                    query = f"""
                        DELETE FROM products
                        WHERE tender_id IN ({placeholders})
                    """
                    cursor.execute(query, tender_ids)
                    deleted_products = cursor.rowcount
                    logging.info(f"Deleted {deleted_products} products")

                    # Delete tenders using the collected tender_ids
                    logging.info("\n--- Deleting Tender Records (final) ---")
                    query = f"""
                        DELETE FROM tender 
                        WHERE id IN ({placeholders})
                    """
                    cursor.execute(query, tender_ids)
                    deleted_tenders = cursor.rowcount
                    deletion_counts["Tender"] = deleted_tenders
                    logging.info(f"Deleted {deleted_tenders} tenders")

                # --- Delete Gem Tenders for this organization
                logging.info("\n--- Deleting Gem Tender Records ---")
                
                cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days_to_keep)
                
                if org_id == 'all':
                    # Should not happen as we process org_id individually
                    pass
                else:
                    query = """
                        DELETE FROM gem_tenders 
                        WHERE 
                            CASE
                                WHEN due_date ~ '^\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}$'
                                    THEN to_timestamp(due_date, 'DD-MM-YYYY HH24:MI:SS')
                                WHEN due_date ~ '^\d{2}-\d{2}-\d{4}$'
                                    THEN to_timestamp(due_date || ' 00:00:00', 'DD-MM-YYYY HH24:MI:SS')
                                ELSE NULL
                            END < %s
                        AND organization_id = %s
                    """
                    params = (cutoff_date, int(org_id))
                    
                    cursor.execute(query, params)
                    deleted_gem_tenders = cursor.rowcount
                    deletion_counts["GemTender"] = deleted_gem_tenders
                    logging.info(f"Deleted {deleted_gem_tenders} Gem tenders")

                # Commit transaction for this organization
                cursor.execute("COMMIT")
                logging.info(f"Organization {org_id}: All operations committed successfully")
            else:
                # For dry run, we don't do deletions
                logging.info(f"\nOrganization {org_id}: DRY RUN - No records deleted")
                # Set deletion counts to 0 for dry run summary
                for table_name in ["Tender", "GemTender", "Risk", "RiskAssessment", 
                                "BidderQuestion", "BidderQuestionsSet", "QAInteraction", "Document"]:
                    deletion_counts[table_name] = 0
        else:
            logging.info(f"\nOrganization {org_id}: No old records found to process.")
            
        # Create DataPurgeSummary record for this organization (only if not dry run)
        if not dry_run:
            try:
                app = create_app()
                with app.app_context():
                    summary = DataPurgeSummary(
                        run_id=run_id,
                        organization_id=int(org_id) if org_id != 'all' else None,
                        files_archived=archived_count,
                        records_deleted=sum(deletion_counts.values()),
                        executed_at=datetime.datetime.utcnow(),
                        status='success'
                    )
                    db.session.add(summary)
                    db.session.commit()
                    logging.info(f"Created DataPurgeSummary record for organization {org_id}")
            except Exception as summary_error:
                logging.error(f"Failed to create summary record for organization {org_id}: {summary_error}")
        
        return archived_count, exported_counts, deletion_counts
        
    except Exception as e:
        if cursor:
            try:
                cursor.execute("ROLLBACK")
                logging.error(f"Organization {org_id}: ERROR - Transaction rolled back due to failure")
            except:
                pass
        
        logging.error(f"Organization {org_id}: Fatal error during purge process: {str(e)}")
        
        # Create failure record in DataPurgeSummary (only if not dry run)
        if not dry_run:
            try:
                app = create_app()
                with app.app_context():
                    summary = DataPurgeSummary(
                        run_id=run_id,
                        organization_id=int(org_id) if org_id != 'all' else None,
                        files_archived=archived_count,
                        records_deleted=sum(deletion_counts.values()) if deletion_counts else 0,
                        executed_at=datetime.datetime.utcnow(),
                        status='failure'
                    )
                    db.session.add(summary)
                    db.session.commit()
                    logging.info(f"Created DataPurgeSummary record for organization {org_id} (failure)")
            except Exception as summary_error:
                logging.error(f"Failed to create failure summary record for organization {org_id}: {summary_error}")
        
        raise

def purge_old_records(days_to_keep, org_arg, run_id, dry_run=False, log_file_path=None):
    """
    Main function to purge records organization-wise
    """
    logging.info(f"Purge process started. Run ID: {run_id}")
    logging.info(f"Log file: {log_file_path}")
    
    if days_to_keep < MIN_DAYS_TO_DELETE:
        logging.error(
            f"ABORTED: days ({days_to_keep}) is less than "
            f"minimum allowed ({MIN_DAYS_TO_DELETE}). "
            "No records deleted."
        )
        return

    cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days_to_keep)
   
    logging.info(f"\n=== Purging records older than {cutoff_date} ===")
    logging.info(f"Run ID: {run_id}")
    logging.info(f"Organization: {org_arg}")
    logging.info(f"Dry run: {dry_run}")

    # Initialize total counters
    total_archived = 0
    all_exported_counts = {}
    all_deletion_counts = {}

    # Get psycopg2 connection
    connection = get_psycopg2_connection()
    cursor = None
    
    try:
        cursor = connection.cursor()
        
        # Get list of organizations to process
        if org_arg == 'all':
            # Get all organization IDs
            cursor.execute("SELECT id FROM organization ORDER BY id")
            org_ids = [str(row[0]) for row in cursor.fetchall()]
            logging.info(f"Found {len(org_ids)} organizations to process")
        else:
            org_ids = [org_arg]
        
        # Process each organization
        for org_id in org_ids:
            logging.info(f"\n{'='*60}")
            logging.info(f"Processing Organization ID: {org_id}")
            logging.info(f"{'='*60}")
            
            archived_count, exported_counts, deletion_counts = purge_organization(
                days_to_keep, org_id, run_id, cursor, dry_run
            )
            
            # Update totals
            total_archived += archived_count
            
            # Sum exported counts
            for model_name, count in exported_counts.items():
                all_exported_counts[model_name] = all_exported_counts.get(model_name, 0) + count
            
            # Sum deletion counts
            for model_name, count in deletion_counts.items():
                all_deletion_counts[model_name] = all_deletion_counts.get(model_name, 0) + count
        
        # Calculate totals
        total_exported_sum = sum(all_exported_counts.values())
        total_deleted_sum = sum(all_deletion_counts.values())
        
        # Print final summary
        logging.info("\n" + "="*60)
        logging.info("FINAL PURGE SUMMARY - ALL ORGANIZATIONS")
        logging.info("="*60)
        logging.info(f"Run ID: {run_id}")
        
        if dry_run:
            logging.info("\nDRY RUN COMPLETED - No changes were made")
            logging.info("\nWhat would have been done:")
        
        logging.info(f"\nTotal Archived Files: {total_archived}")
        
        logging.info("\nTotal Exported Records:")
        for table_name in ["Tender", "GemTender", "Risk", "RiskAssessment", 
                          "BidderQuestion", "BidderQuestionsSet", "QAInteraction", "Document"]:
            exported = all_exported_counts.get(table_name, 0)
            if exported > 0:
                logging.info(f"{table_name}: {exported}")
        
        logging.info(f"\nTotal Exported: {total_exported_sum}")
        
        logging.info("\nTotal Deleted Records:")
        for table_name in ["Tender", "GemTender", "Risk", "RiskAssessment", 
                          "BidderQuestion", "BidderQuestionsSet", "QAInteraction", "Document"]:
            deleted = all_deletion_counts.get(table_name, 0)
            if deleted > 0:
                logging.info(f"{table_name}: {deleted}")
        
        logging.info(f"\nTotal Deleted: {total_deleted_sum}")
        logging.info("="*60)
        logging.info(f"Purging completed successfully. Run ID: {run_id}")
        logging.info(f"Log saved to: {log_file_path}")
        
    except Exception as e:
        logging.error(f"Fatal error during purge process: {str(e)}")
        logging.error("Purge process failed.")
        raise
        
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Purge old database records and archive files based on due_date"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS_TO_KEEP,
        help=f"Delete records older than N days (default: {DEFAULT_DAYS_TO_KEEP})"
    )
    parser.add_argument(
        "--org",
        type=str,
        required=True,
        help="Organization ID to purge records for (use 'all' for all organizations)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without deleting files or records"
    )

    args = parser.parse_args()

    # Validate org argument
    if args.org.lower() != 'all':
        try:
            org_id_int = int(args.org)
            # Verify organization exists
            app = create_app()
            with app.app_context():
                query = text("SELECT id FROM organization WHERE id = :org_id")
                result = db.session.execute(query, {'org_id': org_id_int})
                org = result.fetchone()
                if not org:
                    print(f"Error: Organization with ID {args.org} does not exist.")
                    exit(1)
        except ValueError:
            print("Error: Organization ID must be an integer or 'all'.")
            exit(1)
    
    # Generate run ID ONCE
    run_id = generate_run_id()
    
    # Setup logging with the SAME run_id
    log_file_path = setup_logging(args.dry_run, args.org, run_id)
    
    try:
        # Pass the same run_id to purge_old_records
        purge_old_records(args.days, args.org, run_id, dry_run=args.dry_run, log_file_path=log_file_path)
    except Exception as e:
        logging.error(f"Fatal error during purge process: {str(e)}")
        logging.error("Purge process failed.")
        exit(1)