from app import app
from models import db, GemTender, GemTenderMaster, GemTenderMatch
import datetime


def migrate_gem_tenders():
    print("Starting migration...")

    print("Connected DB:", app.config["SQLALCHEMY_DATABASE_URI"])

    existing_masters = {
        m.tender_id: m.id
        for m in GemTenderMaster.query.all()
    }

    print(f"Existing masters loaded: {len(existing_masters)}")

    old_rows = GemTender.query.all()
    print(f"Total old rows: {len(old_rows)}")

    master_created_count = 0
    match_created_count = 0

    for row in old_rows:

        master_id = existing_masters.get(row.tender_id)

        if not master_id:
            master = GemTenderMaster(
                tender_id=row.tender_id,
                description=row.description,
                due_date=row.due_date,
                creation_date=row.creation_date,
                document_url=row.document_url,
                pdf_path=row.pdf_path
            )

            db.session.add(master)
            db.session.flush()

            master_id = master.id
            existing_masters[row.tender_id] = master_id
            master_created_count += 1

        match = GemTenderMatch(
            organization_id=row.organization_id,
            master_tender_id=master_id,
            matches_services=row.matches_services,
            match_reason=row.match_reason,
            match_score=row.match_score,
            match_score_keyword=row.match_score_keyword,
            match_score_combined=row.match_score_combined,
            relevance_percentage=row.relevance_percentage,
            strategic_fit=row.strategic_fit,
            is_central_match=row.is_central_match,
            primary_scope=row.primary_scope,
            api_calls_made=row.api_calls_made,
            tokens_used=row.tokens_used,
            created_at=datetime.datetime.utcnow()
        )

        db.session.add(match)
        match_created_count += 1

        if match_created_count % 500 == 0:
            db.session.commit()
            print(f"Committed {match_created_count} matches...")

    db.session.commit()

    print("Migration completed.")
    print(f"Masters created: {master_created_count}")
    print(f"Matches created: {match_created_count}")


if __name__ == "__main__":
    with app.app_context():
        migrate_gem_tenders()
