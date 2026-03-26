import datetime
import subprocess
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
from werkzeug.security import generate_password_hash
from flask import current_app
import json
import urllib.parse


from models import (
    db,
    Organization,
    User,
    Tender,
    Admin,
    GemTender,
    Constraint,
    ServiceProductDefinition,
    SearchConfiguration,
    NotificationRecipient,
    # Plan,
    # Subscription,
    # SubscriptionLimit
)
import logging
from threading import Thread

# Blocked SQL keywords for security
BLOCKED_KEYWORDS = ["drop", "truncate"]

def run_sql(query):
    """
    Execute SQL query with security checks
    Returns HTML table for SELECT queries, status message for others
    """
    try:
        if any(keyword in query.lower() for keyword in BLOCKED_KEYWORDS):
            return f"<p style='color:red;'><strong>Error: Query contains blocked keywords</strong></p>"
            
        if query.strip().lower().startswith("select"):
            result = db.session.execute(text(query))
            col_names = result.keys()
            rows = result.fetchall()

            table_html = "<table>"
            table_html += "<tr>" + "".join([f"<th>{col}</th>" for col in col_names]) + "</tr>"
            for row in rows:
                table_html += "<tr>" + "".join([f"<td>{cell}</td>" for cell in row]) + "</tr>"
            table_html += "</table>"

            return table_html
        else:
            result = db.session.execute(text(query))
            db.session.commit()
            return f"<p>Query executed. {result.rowcount} row(s) affected.</p>"
    except Exception as e:
        db.session.rollback()
        return f"<p style='color:red;'>Error : {e}</p>"

def run_cmd(cmd):
    """
    Execute system command
    Returns command output as string
    """
    try:
        output = subprocess.check_output(cmd, shell=True, text=True)
        return output
    except Exception as e:
        return f"Error: {e}"

# def create_organization(form_data):
#     """
#     Create a new organization with users
#     Returns (success: bool, message: str)
#     """
#     org_name = form_data.get('org_name')
#     org_desc = form_data.get('org_description')
    
#     print(f"Creating organization: {org_name}")

#     if not org_name:
#         return False, "Organization name is required"
    
#     try:
#         # Create Organization
#         org = Organization(name=org_name, description=org_desc)
#         db.session.add(org)
#         db.session.flush()
#         print(f"Created organization with ID: {org.id}")

#         # Create users from form data
#         user_count = 0
#         index = 0
        
#         while True:
#             # Check if user data exists at this index
#             username = form_data.get(f'users[{index}][username]')
            
#             # If no username at this index, stop
#             if not username:
#                 break
                
#             email = form_data.get(f'users[{index}][email]')
#             password = form_data.get(f'users[{index}][password]')
#             role = form_data.get(f'users[{index}][role]', 'user')
            
#             if not password:
#                 return False, f"Password is required for user '{username}'"
            
#             # Create user
#             user = User(
#                 username=username,
#                 password=generate_password_hash(password),
#                 email=email,
#                 role=role,
#                 organization_id=org.id  # Add org_id here
#             )
            
#             db.session.add(user)
#             user_count += 1
#             index += 1
        
#         if user_count == 0:
#             return False, "At least one user is required"
        
#         print(f"Created {user_count} users for organization {org.name}")
        
#         db.session.commit()
#         return True, "Organization and users created successfully"

#     except Exception as e:
#         db.session.rollback()
#         print(f"Error: {str(e)}")
#         return False, f"Error creating organization: {str(e)}"


def get_organization_management_data(org_id):
    """
    Get data for managing a single organization
    Returns dict with organization data
    """
    org = Organization.query.get_or_404(org_id)
    users = User.query.filter_by(organization_id=org.id).order_by(User.id).all()
    constraints = Constraint.query.filter_by(organization_id=org.id).order_by(Constraint.id).all()
    services = ServiceProductDefinition.query.filter_by(organization_id=org.id).order_by(ServiceProductDefinition.id).all()
    
    user_ids = [u.id for u in users]
    configs = []
    if user_ids:
        configs = SearchConfiguration.query.filter(
            SearchConfiguration.created_by.in_(user_ids)
        ).order_by(SearchConfiguration.id.desc()).all()
    
    return {
        "organization": org,
        "users": users,
        "constraints": constraints,
        "services": services,
        "search_configs": configs
    }

# def update_user(user_id, form_data):
#     """
#     Update user information
#     Returns (success: bool, org_id: int, message: str)
#     """
#     user = User.query.get_or_404(user_id)
#     org_id = user.organization_id

#     username = form_data.get('username')
#     email = form_data.get('email')
#     role = form_data.get('role')
#     password = form_data.get('password')
    
#     if not username or not email or not role:
#         return False, org_id, "Username, email, and role are required."

#     try:
#         user.username = username
#         user.email = email
#         user.role = role
        
#         # Only update password if provided
#         if password:
#             user.password = generate_password_hash(password)
        
#         db.session.commit()
#         return True, org_id, f"User '{username}' updated successfully."

#     except SQLAlchemyError as e:
#         db.session.rollback()
#         return False, org_id, f"Database error updating user: {e}"
#     except Exception as e:
#         return False, org_id, f"An unexpected error occurred: {e}"

def update_user(user_id, form_data):
    """
    Update user information
    Returns (success: bool, org_id: int, message: str)
    """
    user = User.query.get_or_404(user_id)
    org_id = user.organization_id

    username = form_data.get('username', '').strip()
    email = form_data.get('email', '').strip()
    role = form_data.get('role')
    password = form_data.get('password', '').strip()
    
    if not username or not role:
        return False, org_id, "Username and role are required."
    
    # Check for duplicate username (excluding current user)
    existing_user = User.query.filter(
        User.username == username,
        User.id != user_id
    ).first()
    if existing_user:
        return False, org_id, f"Username '{username}' already exists."

    # Check for duplicate email (if provided, excluding current user)
    if email:
        existing_email = User.query.filter(
            User.email == email,
            User.id != user_id,
            User.email.isnot(None)
        ).first()
        if existing_email:
            return False, org_id, f"Email '{email}' already exists."

    try:
        user.username = username
        user.email = email if email else None
        user.role = role
        
        # Only update password if provided
        if password:
            user.password = generate_password_hash(password)
        
        db.session.commit()
        return True, org_id, f"User '{username}' updated successfully."

    except SQLAlchemyError as e:
        db.session.rollback()
        return False, org_id, f"Database error updating user: {str(e)}"
    except Exception as e:
        return False, org_id, f"An unexpected error occurred: {str(e)}"
    
def get_analytics_stats():
    """
    Get analytics statistics
    Returns dict with stats
    """
    users = User.query.count()
    organizations = Organization.query.count()
    tenders = Tender.query.count()
    # subscriptions = Subscription.query.count()

    # total_revenue = Subscription.query.with_entities( # with_entities, used to fetch specific columns only
    #     db.func.sum(Subscription.subscription_cost)
    #     ).scalar() or 0
    # total_revenue = round(total_revenue, 2)
    
    return {
        "users": users,
        "organizations": organizations,
        "tenders": tenders,
        # "subscriptions": subscriptions,
        # "total_revenue": total_revenue
    }

def fetch_gem_tenders(data):
    """
    Run GeM tender fetching
    Returns (success: bool, result: dict)
    """
    try:
        organization_id = data.get('organization_id')
        search_keyword = data.get('search_keyword', '').strip()
        max_tenders = data.get('max_tenders', 10)

        # Validate inputs
        if not search_keyword:
            search_keyword = None

        try:
            max_tenders = int(max_tenders)
            if max_tenders < 1 or max_tenders > 30:
                return False, {'error': 'Max tenders must be between 1 and 30'}
        except ValueError:
            return False, {'error': 'Max tenders must be a number'}
                    
        # Log the request
        logger = logging.getLogger(__name__)
        logger.info(f"Starting GeM tender fetching for Organization (ID: {organization_id})")
        logger.info(f"Parameters - Search Keyword: '{search_keyword}', Max Tenders: {max_tenders}")
        
        # Run in background thread
        def run_gem_fetching():
            try:
                from demo_gem_nlp_api import main_cli
                
                domain_keywords = []  # Empty list for demo purposes
                keyword_arg = "none" if search_keyword is None else search_keyword
                
                logger.info(f"Calling gem_nlp_api.main_cli with: keyword='{keyword_arg}', max_tenders={max_tenders}, org_id={organization_id}")
                
                main_cli(
                    search_keyword=keyword_arg,
                    max_tenders=max_tenders,
                    organization_id=organization_id,
                    domain_keywords=domain_keywords
                )
                
                logger.info("GeM tender fetching completed successfully")
                
            except Exception as e:
                logger.error(f"Error in gem_nlp_api execution: {str(e)}", exc_info=True)
        
        # Start the background thread
        thread = Thread(target=run_gem_fetching)
        thread.daemon = True
        thread.start()
        
        return True, {
            'success': True,
            'message': 'GeM tender fetching started in the background. This may take a few minutes.',
            'details': f'Searching for "{search_keyword if search_keyword else "all tenders"}" (Max: {max_tenders} tenders)'
        }
        
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Error in fetch-gem-tenders-demo: {str(e)}", exc_info=True)
        return False, {'error': str(e)}