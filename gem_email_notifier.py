# """
# Standalone email notification script for GeM tenders
# Run this after gem_nlp_api.py to send notifications for new matching tenders
# """

# import os
# import sys
# import sqlite3
# import datetime
# import logging
# from flask import Flask
# from flask_mail import Mail, Message

# # Add path to main application
# sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# # Import models and config
# from models import db, SearchConfiguration, NotificationRecipient, GemTender, User, Organization
# import config

# # Configure logging
# logging.basicConfig(level=logging.INFO, 
#                     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
#                     handlers=[
#                         logging.FileHandler("gem_email_notifications.log"),
#                         logging.StreamHandler()
#                     ])
# logger = logging.getLogger(__name__)

# # Database path
# # DB_PATH = "instance/tender_analyzer.db"

# def create_app():
#     """Create Flask app for email notifications"""
#     app = Flask(__name__)
    
#     # Apply configuration
#     app.config['SECRET_KEY'] = config.SECRET_KEY
#     app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
#     app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = config.SQLALCHEMY_TRACK_MODIFICATIONS
    
#     # Mail configuration
#     app.config['MAIL_SERVER'] = config.MAIL_SERVER
#     app.config['MAIL_PORT'] = config.MAIL_PORT
#     app.config['MAIL_USE_TLS'] = config.MAIL_USE_TLS
#     app.config['MAIL_USERNAME'] = config.MAIL_USERNAME
#     app.config['MAIL_PASSWORD'] = config.MAIL_PASSWORD
#     app.config['MAIL_DEFAULT_SENDER'] = config.MAIL_DEFAULT_SENDER
    
#     # Initialize extensions
#     db.init_app(app)
#     mail = Mail(app)
    
#     return app, mail

# # def get_recent_matching_tenders(organization_id, hours_back=24):
# #     """Get matching tenders created in the last X hours for an organization"""
# #     try:
# #         cutoff_time = datetime.datetime.now() - datetime.timedelta(hours=hours_back)
# #         cutoff_str = cutoff_time.strftime('%Y-%m-%d %H:%M:%S')
        
# #         # Query the gem_tenders table directly using SQLAlchemy
# #         tenders = GemTender.query.filter(
# #             GemTender.organization_id == organization_id,
# #             GemTender.matches_services == True,
# #             GemTender.creation_date >= cutoff_str
# #         ).all()
        
# #         logger.info(f"Found {len(tenders)} recent matching tenders for organization {organization_id}")
# #         return tenders
        
# #     except Exception as e:
# #         logger.error(f"Error getting recent matching tenders: {e}")
# #         # Fallback to direct SQL query if SQLAlchemy fails
# #         try:
# #             conn = sqlite3.connect(DB_PATH)
# #             cursor = conn.cursor()
            
# #             cursor.execute("""
# #                 SELECT tender_id, description, due_date, creation_date, matches_services, 
# #                        match_reason, document_url, pdf_path, match_score, keywords,
# #                        match_score_keyword, match_score_combined, relevance_percentage,
# #                        is_central_match, strategic_fit, primary_scope
# #                 FROM gem_tenders 
# #                 WHERE organization_id = ? 
# #                 AND matches_services = 1 
# #                 AND creation_date >= ?
# #                 ORDER BY creation_date DESC
# #             """, (organization_id, cutoff_str))
            
# #             rows = cursor.fetchall()
# #             conn.close()
            
# #             # Convert to objects for template compatibility
# #             tenders = []
# #             for row in rows:
# #                 tender = type('Tender', (), {
# #                     'tender_id': row[0],
# #                     'description': row[1] or 'No description available',
# #                     'due_date': row[2],
# #                     'creation_date': row[3],
# #                     'matches_services': bool(row[4]),
# #                     'match_reason': row[5],
# #                     'document_url': row[6],
# #                     'pdf_path': row[7],
# #                     'match_score': row[8] or 0,
# #                     'keywords': row[9],
# #                     'match_score_keyword': row[10] or 0,
# #                     'match_score_combined': row[11] or 0,
# #                     'relevance_percentage': row[12] or 0,
# #                     'is_central_match': bool(row[13]) if row[13] is not None else False,
# #                     'strategic_fit': bool(row[14]) if row[14] is not None else False,
# #                     'primary_scope': row[15] or 'Not specified'
# #                 })()
# #                 tenders.append(tender)
            
# #             logger.info(f"Found {len(tenders)} recent matching tenders using direct SQL query")
# #             return tenders
            
# #         except Exception as sql_error:
# #             logger.error(f"Direct SQL query also failed: {sql_error}")
# #             return []


# def get_recent_matching_tenders(organization_id, hours_back=24):
#     """Get matching tenders created in the last X hours for an organization"""
#     try:
#         cutoff_time = datetime.datetime.now() - datetime.timedelta(hours=hours_back)
#         cutoff_str = cutoff_time.strftime('%Y-%m-%d %H:%M:%S')
        
#         # Query the gem_tenders table directly using SQLAlchemy
#         tenders = GemTender.query.filter(
#             GemTender.organization_id == organization_id,
#             GemTender.matches_services == True,
#             GemTender.creation_date >= cutoff_str
#         ).all()
        
#         logger.info(f"Found {len(tenders)} recent matching tenders for organization {organization_id}")
#         return tenders
        
#     except Exception as e:
#         logger.error(f"Error getting recent matching tenders with SQLAlchemy ORM: {e}")
#         # Fallback to direct SQL query with engine.connect()
#         try:
#             from sqlalchemy import text
#             from database_config import engine
            
#             with engine.connect() as conn:
#                 result = conn.execute(text("""
#                     SELECT tender_id, description, due_date, creation_date, matches_services, 
#                            match_reason, document_url, pdf_path, match_score, keywords,
#                            match_score_keyword, match_score_combined, relevance_percentage,
#                            is_central_match, strategic_fit, primary_scope
#                     FROM gem_tenders 
#                     WHERE organization_id = :org_id 
#                     AND matches_services = true 
#                     AND creation_date >= :cutoff
#                     ORDER BY creation_date DESC
#                 """), {
#                     "org_id": organization_id,
#                     "cutoff": cutoff_str
#                 })
                
#                 rows = result.fetchall()
                
#                 # Convert to objects for template compatibility
#                 tenders = []
#                 for row in rows:
#                     tender = type('Tender', (), {
#                         'tender_id': row[0],
#                         'description': row[1] or 'No description available',
#                         'due_date': row[2],
#                         'creation_date': row[3],
#                         'matches_services': bool(row[4]),
#                         'match_reason': row[5],
#                         'document_url': row[6],
#                         'pdf_path': row[7],
#                         'match_score': row[8] or 0,
#                         'keywords': row[9],
#                         'match_score_keyword': row[10] or 0,
#                         'match_score_combined': row[11] or 0,
#                         'relevance_percentage': row[12] or 0,
#                         'is_central_match': bool(row[13]) if row[13] is not None else False,
#                         'strategic_fit': bool(row[14]) if row[14] is not None else False,
#                         'primary_scope': row[15] or 'Not specified'
#                     })()
#                     tenders.append(tender)
                
#                 logger.info(f"Found {len(tenders)} recent matching tenders using engine.connect()")
#                 return tenders
                
#         except Exception as sql_error:
#             logger.error(f"Direct SQL query with engine.connect() also failed: {sql_error}")
#             return []


# def create_tender_notification_html(search_config, matching_tenders):
#     """Create HTML email content for tender notifications"""
    
#     html_body = f"""
#     <html>
#         <head>
#             <style>
#                 body {{ 
#                     font-family: Arial, sans-serif; 
#                     margin: 20px; 
#                     background-color: #f8f9fa;
#                 }}
#                 .container {{
#                     max-width: 800px;
#                     margin: 0 auto;
#                     background-color: white;
#                     padding: 20px;
#                     border-radius: 8px;
#                     box-shadow: 0 2px 4px rgba(0,0,0,0.1);
#                 }}
#                 h1 {{ 
#                     color: #2c3e50; 
#                     border-bottom: 3px solid #3498db;
#                     padding-bottom: 10px;
#                 }}
#                 h2 {{ 
#                     color: #3498db; 
#                     margin-top: 30px;
#                 }}
#                 .tender-card {{
#                     border: 1px solid #ddd;
#                     border-radius: 6px;
#                     padding: 15px;
#                     margin-bottom: 15px;
#                     background-color: #f9f9f9;
#                 }}
#                 .tender-id {{
#                     font-weight: bold;
#                     color: #2c3e50;
#                     font-size: 1.1em;
#                 }}
#                 .tender-description {{
#                     margin: 10px 0;
#                     line-height: 1.5;
#                 }}
#                 .tender-meta {{
#                     color: #666;
#                     font-size: 0.9em;
#                     margin-top: 10px;
#                 }}
#                 .match-reason {{
#                     background-color: #d4edda;
#                     border: 1px solid #c3e6cb;
#                     border-radius: 4px;
#                     padding: 8px;
#                     margin-top: 8px;
#                     color: #155724;
#                     font-size: 0.9em;
#                 }}
#                 .match-scores {{
#                     background-color: #f8f9fa;
#                     border: 1px solid #dee2e6;
#                     border-radius: 4px;
#                     padding: 8px;
#                     margin-top: 8px;
#                     font-size: 0.85em;
#                 }}
#                 .search-info {{
#                     background-color: #e3f2fd;
#                     border-left: 4px solid #2196f3;
#                     padding: 15px;
#                     margin-bottom: 20px;
#                 }}
#                 .footer {{
#                     margin-top: 30px;
#                     padding-top: 20px;
#                     border-top: 1px solid #ddd;
#                     color: #666;
#                     text-align: center;
#                     font-size: 0.9em;
#                 }}
#                 .btn {{
#                     display: inline-block;
#                     padding: 8px 16px;
#                     background-color: #007bff;
#                     color: white;
#                     text-decoration: none;
#                     border-radius: 4px;
#                     font-size: 0.9em;
#                     margin-top: 8px;
#                 }}
#                 .stats {{
#                     background-color: #f8f9fa;
#                     border: 1px solid #dee2e6;
#                     border-radius: 6px;
#                     padding: 15px;
#                     margin-bottom: 20px;
#                     text-align: center;
#                 }}
#                 .stat-item {{
#                     display: inline-block;
#                     margin-right: 20px;
#                     font-weight: bold;
#                     color: #28a745;
#                 }}
#                 .keywords {{
#                     background-color: #fff3cd;
#                     border: 1px solid #ffeeba;
#                     border-radius: 4px;
#                     padding: 6px;
#                     margin-top: 6px;
#                     font-size: 0.8em;
#                 }}
#                 .badge {{
#                     display: inline-block;
#                     padding: 2px 6px;
#                     margin: 2px;
#                     background-color: #007bff;
#                     color: white;
#                     border-radius: 3px;
#                     font-size: 0.75em;
#                 }}
#             </style>
#         </head>
#         <body>
#             <div class="container">
#                 <h1>🎯 New GeM Tenders Found</h1>
                
#                 <div class="search-info">
#                     <strong>Search Configuration:</strong> {search_config.search_keyword or 'All Tenders'}<br>
#                     <strong>Search Date:</strong> {datetime.datetime.now().strftime('%B %d, %Y at %I:%M %p')}<br>
#                     <strong>Organization:</strong> {search_config.user.organization.name}
#                 </div>
                
#                 <div class="stats">
#                     <div class="stat-item">🎯 New Matching Tenders: {len(matching_tenders)}</div>
#                 </div>
#     """
    
#     # Add matching tenders section
#     if matching_tenders:
#         html_body += """
#                 <h2>🎯 New Tenders Matching Your Services</h2>
#                 <p>These tenders match your organization's service offerings:</p>
#                 <p><strong>Note : </strong>Tenders with a due date within the next 5 days are highlighted in red</p>
#         """
        
#         for tender in matching_tenders:
#             description = getattr(tender, 'description', '') or 'No description available'
#             if len(description) > 300:
#                 description = description[:300] + "..."
                
#             try:
#                 creation_date = getattr(tender, 'creation_date', '')
#                 if isinstance(creation_date, str):
#                     creation_date = creation_date
#                 else:
#                     creation_date = creation_date.strftime('%Y-%m-%d %H:%M') if creation_date else 'Not specified'
#             except:
#                 creation_date = 'Not specified'
            
#             due_date = getattr(tender, 'due_date', '') or 'Not specified'
#             document_url = getattr(tender, 'document_url', '')
#             match_reason = getattr(tender, 'match_reason', '')
            
#             relevance_percentage = getattr(tender, 'relevance_percentage', 0) or 0
#             match_score_keyword = getattr(tender, 'match_score_keyword', 0) or 0
#             match_score_combined = getattr(tender, 'match_score_combined', 0) or 0
#             is_central_match = getattr(tender, 'is_central_match', False)
#             strategic_fit = getattr(tender, 'strategic_fit', False)
#             primary_scope = getattr(tender, 'primary_scope', '') or 'Not specified'
            
#             keywords = getattr(tender, 'keywords', '') or ''
#             keyword_list = [k.strip() for k in keywords.split('|') if k.strip()] if keywords else []

#             # Due date check : If due date less than 5 days then highlight in red color ----------------------------------------
#             if due_date:
#                 if isinstance(due_date, str):
#                     # If stored as string, convert to datetime
#                     try:
#                         due_dt = datetime.strptime(due_date, '%Y-%m-%d %H:%M:%S')
#                     except:
#                         due_dt = None
#                 else:
#                     due_dt = due_date
                
#                 if due_dt: 
#                     if 0 <= (due_dt - datetime.now()).days <= 5: # (due date - today's date) <= 5
#                         due_color = "red"
#                     else:
#                         due_color = "black"
#                 else:
#                     due_color = "black"
#             else:
#                 due_color = "black"
            
#             html_body += f"""
#                 <div class="tender-card" style= "color : {due_color}">
#                     <div class="tender-id">Tender ID: {getattr(tender, 'tender_id', 'Unknown')}</div>
#                     <div class="tender-description">{description}</div>
#                     <div class="tender-meta">
#                         <strong>Due Date:</strong> {due_date} | 
#                         <strong>Found:</strong> {creation_date}
#                     </div>
#             """
            
#             if match_reason:
#                 html_body += f'<div class="match-reason"><strong>Why it matches:</strong> {match_reason}</div>'
            
#             if primary_scope and primary_scope != 'Not specified':
#                 html_body += f'<div class="match-reason"><strong>Tender Scope:</strong> {primary_scope}</div>'
            
#             html_body += f"""
#                     <div class="match-scores">
#                         <strong>Match Analysis:</strong>
#                         Relevance: {relevance_percentage:.1f}% | 
#                         Keyword Score: {match_score_keyword:.2f} | 
#                         Combined Score: {match_score_combined:.2f}
#             """
            
#             if is_central_match:
#                 html_body += ' <span class="badge">Central Match</span>'
#             if strategic_fit:
#                 html_body += ' <span class="badge">Strategic Fit</span>'
            
#             html_body += '</div>'
            
#             if keyword_list:
#                 html_body += f"""
#                         <div class="keywords">
#                             <strong>Matching Keywords:</strong> {', '.join(keyword_list[:10])}
#                         </div>
#                 """
            
#             if document_url:
#                 html_body += f'<div><a href="{document_url}" class="btn" target="_blank">View Tender Details</a></div>'
            
#             html_body += '</div>'
#     else:
#         html_body += """
#                 <div style="text-align: center; padding: 40px; color: #666;">
#                     <h3>No New Matching Tenders</h3>
#                     <p>No new tenders matching your organization's services were found in this search.</p>
#                 </div>
#         """
    
#     html_body += f"""
#                 <div class="footer">
#                     <p>This notification was generated by the GeM Tender Monitoring System.</p>
#                     <p>To manage your notification preferences, please log in to the system.</p>
#                     <p><small>Search Configuration ID: {search_config.id} | Generated at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small></p>
#                 </div>
#             </div>
#         </body>
#     </html>
#     """
    
#     return html_body

# def ordinal_date_str(dt: datetime.date) -> str:
#     day = dt.day
#     if 11 <= day <= 13:
#         suffix = "th"
#     else:
#         suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
#     # e.g., "17th Sep 2025"
#     return f"{day}{suffix} {dt.strftime('%b %Y')}"

# def send_notifications_for_organization(organization, mail, hours_back=4):
#     """Send email notifications for new matching tenders for an organization"""
#     try:
#         organization_id = organization.id
#         logger.info(f"Processing email notifications for organization {organization_id}")
        
#         # Get recent matching tenders
#         recent_tenders = get_recent_matching_tenders(organization_id, hours_back)
        
#         if not recent_tenders:
#             logger.info(f"No recent matching tenders found for organization {organization_id}")
#             return True
        
#         # Get all active search configurations for this organization
#         search_configs = SearchConfiguration.query \
#             .join(User, SearchConfiguration.created_by == User.id) \
#             .filter(
#                 User.organization_id == organization_id,
#                 SearchConfiguration.is_active == True
#             ).all()
        
#         if not search_configs:
#             logger.info(f"No active search configurations found for organization {organization_id}")
#             return True
        
#         notifications_sent = 0
        
#         # Process each search configuration
#         for config in search_configs:
#             # Get active recipients for this search config
#             recipients = NotificationRecipient.query.filter_by(
#                 search_config_id=config.id,
#                 is_active=True,
#                 email = '243rushabh@gmail.com'
#             ).all()
            
#             if not recipients:
#                 logger.info(f"No active recipients for search config {config.id}")
#                 continue
            
#             relevant_tenders = recent_tenders
            
#             # Send notification if there are relevant tenders
#             if relevant_tenders:
#                 try:
#                     today_str = ordinal_date_str(datetime.datetime.now().date())
#                     org_name = organization.name
#                     subject = f"New GeM Tenders Found - for {org_name} - {today_str}"

                    
#                     recipient_emails = [recipient.email for recipient in recipients]
#                     html_body = create_tender_notification_html(config, relevant_tenders)
                    
#                     # Create and send email
#                     msg = Message(
#                         subject=subject,
#                         recipients=recipient_emails,
#                         html=html_body
#                     )
                    
#                     mail.send(msg)
#                     notifications_sent += 1
                    
#                     logger.info(f"Email sent for search config {config.id} to {len(recipient_emails)} recipients ({len(relevant_tenders)} tenders)")
                    
#                 except Exception as e:
#                     logger.error(f"Failed to send email for search config {config.id}: {e}")
#             else:
#                 logger.info(f"No relevant tenders for search config {config.id} (keyword: {config.search_keyword})")
        
#         logger.info(f"Sent {notifications_sent} email notifications for organization {organization_id}")
#         return True
        
#     except Exception as e:
#         logger.error(f"Error sending notifications for organization {organization.id}: {e}")
#         return False

# def main():
#     """Main function to send email notifications"""
#     if len(sys.argv) < 2:
#         print("Usage: python gem_email_notifier.py <organization_id> [hours_back]")
#         print("Example: python gem_email_notifier.py 1 2")
#         sys.exit(1)
    
#     try:
#         organization_id = int(sys.argv[1])
#         hours_back = int(sys.argv[2]) if len(sys.argv) > 2 else 2
        
#         logger.info(f"Starting email notifications for organization {organization_id}")
#         logger.info(f"Looking for tenders from the last {hours_back} hours")
        
#         # Create Flask app and mail instance
#         app, mail = create_app()
        
#         with app.app_context(): # flask context manager, that makes flask application temporarily active for specific block
#             # Verify organization exists
#             organization = Organization.query.get(organization_id)
#             if not organization:
#                 logger.error(f"Organization {organization_id} not found")
#                 sys.exit(1)
            
#             logger.info(f"Processing notifications for organization: {organization.name}")
            
#             # Send notifications
#             success = send_notifications_for_organization(organization, mail, hours_back)
            
#             if success:
#                 logger.info("Email notification process completed successfully")
#             else:
#                 logger.error("Email notification process failed")
#                 sys.exit(1)
        
#     except ValueError:
#         logger.error("Invalid organization_id provided. Must be a number.")
#         sys.exit(1)
#     except Exception as e:
#         logger.error(f"Error in main function: {e}")
#         sys.exit(1)

# if __name__ == "__main__":
#     main()















"""
Standalone email notification script for GeM tenders
Run this after gem_nlp_api.py to send notifications for new matching tenders
"""

import os
import sys
import sqlite3
import datetime
import logging
from flask import Flask
from flask_mail import Mail, Message

# Add path to main application
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import models and config
from models import db, SearchConfiguration, NotificationRecipient, GemTender, User, Organization
import config

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler("gem_email_notifications.log"),
                        logging.StreamHandler()
                    ])
logger = logging.getLogger(__name__)


def create_app():
    """Create Flask app for email notifications"""
    app = Flask(__name__)
    
    # Apply configuration
    app.config['SECRET_KEY'] = config.SECRET_KEY
    app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = config.SQLALCHEMY_TRACK_MODIFICATIONS
    
    # Mail configuration
    app.config['MAIL_SERVER'] = config.MAIL_SERVER
    app.config['MAIL_PORT'] = config.MAIL_PORT
    app.config['MAIL_USE_TLS'] = config.MAIL_USE_TLS
    app.config['MAIL_USERNAME'] = config.MAIL_USERNAME
    app.config['MAIL_PASSWORD'] = config.MAIL_PASSWORD
    app.config['MAIL_DEFAULT_SENDER'] = config.MAIL_DEFAULT_SENDER
    
    # Initialize extensions
    db.init_app(app)
    mail = Mail(app)
    
    return app, mail


def get_recent_matching_tenders(organization_id, search_config_id, hours_back=24):
    """
    Get matching tenders created in the last X hours for a specific organization and search configuration
    """
    try:
        cutoff_time = datetime.datetime.now() - datetime.timedelta(hours=hours_back)
        cutoff_str = cutoff_time.strftime('%Y-%m-%d %H:%M:%S')
        
        # Query the gem_tenders table using SQLAlchemy with search_config_id filter
        tenders = GemTender.query.filter(
            GemTender.organization_id == organization_id,
            GemTender.search_config_id == search_config_id,
            GemTender.matches_services == True,
            GemTender.creation_date >= cutoff_str
        ).all()
        
        logger.info(f"Found {len(tenders)} recent matching tenders for organization {organization_id}, config {search_config_id}")
        return tenders
        
    except Exception as e:
        logger.error(f"Error getting recent matching tenders with SQLAlchemy ORM: {e}")
        # Fallback to direct SQL query with engine.connect()
        try:
            from sqlalchemy import text
            from database_config import engine
            
            with engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT tender_id, description, due_date, creation_date, matches_services, 
                           match_reason, document_url, pdf_path, match_score, keywords,
                           match_score_keyword, match_score_combined, relevance_percentage,
                           is_central_match, strategic_fit, primary_scope
                    FROM gem_tenders 
                    WHERE organization_id = :org_id 
                    AND search_config_id = :config_id
                    AND matches_services = true 
                    AND creation_date >= :cutoff
                    ORDER BY creation_date DESC
                """), {
                    "org_id": organization_id,
                    "config_id": search_config_id,
                    "cutoff": cutoff_str
                })
                
                rows = result.fetchall()
                
                # Convert to objects for template compatibility
                tenders = []
                for row in rows:
                    tender = type('Tender', (), {
                        'tender_id': row[0],
                        'description': row[1] or 'No description available',
                        'due_date': row[2],
                        'creation_date': row[3],
                        'matches_services': bool(row[4]),
                        'match_reason': row[5],
                        'document_url': row[6],
                        'pdf_path': row[7],
                        'match_score': row[8] or 0,
                        'keywords': row[9],
                        'match_score_keyword': row[10] or 0,
                        'match_score_combined': row[11] or 0,
                        'relevance_percentage': row[12] or 0,
                        'is_central_match': bool(row[13]) if row[13] is not None else False,
                        'strategic_fit': bool(row[14]) if row[14] is not None else False,
                        'primary_scope': row[15] or 'Not specified'
                    })()
                    tenders.append(tender)
                
                logger.info(f"Found {len(tenders)} recent matching tenders using engine.connect()")
                return tenders
                
        except Exception as sql_error:
            logger.error(f"Direct SQL query with engine.connect() also failed: {sql_error}")
            return []


def create_tender_notification_html(search_config, matching_tenders):
    """Create HTML email content for tender notifications"""
    
    html_body = f"""
    <html>
        <head>
            <style>
                body {{ 
                    font-family: Arial, sans-serif; 
                    margin: 20px; 
                    background-color: #f8f9fa;
                }}
                .container {{
                    max-width: 800px;
                    margin: 0 auto;
                    background-color: white;
                    padding: 20px;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                h1 {{ 
                    color: #2c3e50; 
                    border-bottom: 3px solid #3498db;
                    padding-bottom: 10px;
                }}
                h2 {{ 
                    color: #3498db; 
                    margin-top: 30px;
                }}
                .tender-card {{
                    border: 1px solid #ddd;
                    border-radius: 6px;
                    padding: 15px;
                    margin-bottom: 15px;
                    background-color: #f9f9f9;
                }}
                .tender-id {{
                    font-weight: bold;
                    color: #2c3e50;
                    font-size: 1.1em;
                }}
                .tender-description {{
                    margin: 10px 0;
                    line-height: 1.5;
                }}
                .tender-meta {{
                    color: #666;
                    font-size: 0.9em;
                    margin-top: 10px;
                }}
                .match-reason {{
                    background-color: #d4edda;
                    border: 1px solid #c3e6cb;
                    border-radius: 4px;
                    padding: 8px;
                    margin-top: 8px;
                    color: #155724;
                    font-size: 0.9em;
                }}
                .match-scores {{
                    background-color: #f8f9fa;
                    border: 1px solid #dee2e6;
                    border-radius: 4px;
                    padding: 8px;
                    margin-top: 8px;
                    font-size: 0.85em;
                }}
                .search-info {{
                    background-color: #e3f2fd;
                    border-left: 4px solid #2196f3;
                    padding: 15px;
                    margin-bottom: 20px;
                }}
                .footer {{
                    margin-top: 30px;
                    padding-top: 20px;
                    border-top: 1px solid #ddd;
                    color: #666;
                    text-align: center;
                    font-size: 0.9em;
                }}
                .btn {{
                    display: inline-block;
                    padding: 8px 16px;
                    background-color: #007bff;
                    color: white;
                    text-decoration: none;
                    border-radius: 4px;
                    font-size: 0.9em;
                    margin-top: 8px;
                }}
                .stats {{
                    background-color: #f8f9fa;
                    border: 1px solid #dee2e6;
                    border-radius: 6px;
                    padding: 15px;
                    margin-bottom: 20px;
                    text-align: center;
                }}
                .stat-item {{
                    display: inline-block;
                    margin-right: 20px;
                    font-weight: bold;
                    color: #28a745;
                }}
                .keywords {{
                    background-color: #fff3cd;
                    border: 1px solid #ffeeba;
                    border-radius: 4px;
                    padding: 6px;
                    margin-top: 6px;
                    font-size: 0.8em;
                }}
                .badge {{
                    display: inline-block;
                    padding: 2px 6px;
                    margin: 2px;
                    background-color: #007bff;
                    color: white;
                    border-radius: 3px;
                    font-size: 0.75em;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>New GeM Tenders Found</h1>
                
                <div class="search-info">
                    <strong>Search Configuration:</strong> {search_config.search_keyword or 'All Tenders'}<br>
                    <strong>Search Date:</strong> {datetime.datetime.now().strftime('%B %d, %Y at %I:%M %p')}<br>
                    <strong>Organization:</strong> {search_config.user.organization.name if search_config.user and search_config.user.organization else 'Not specified'}
                </div>
                
                <div class="stats">
                    <div class="stat-item">New Matching Tenders: {len(matching_tenders)}</div>
                </div>
    """
    
    # Add matching tenders section
    if matching_tenders:
        html_body += """
                <h2>New Tenders Matching Your Services</h2>
                <p>These tenders match your organization's service offerings:</p>
                <p><strong>Note : </strong>Tenders with a due date within the next 5 days are highlighted in red</p>
        """
        
        for tender in matching_tenders:
            description = getattr(tender, 'description', '') or 'No description available'
            if len(description) > 300:
                description = description[:300] + "..."
                
            try:
                creation_date = getattr(tender, 'creation_date', '')
                if isinstance(creation_date, str):
                    creation_date = creation_date
                else:
                    creation_date = creation_date.strftime('%Y-%m-%d %H:%M') if creation_date else 'Not specified'
            except:
                creation_date = 'Not specified'
            
            due_date = getattr(tender, 'due_date', '') or 'Not specified'
            document_url = getattr(tender, 'document_url', '')
            match_reason = getattr(tender, 'match_reason', '')
            
            relevance_percentage = getattr(tender, 'relevance_percentage', 0) or 0
            match_score_keyword = getattr(tender, 'match_score_keyword', 0) or 0
            match_score_combined = getattr(tender, 'match_score_combined', 0) or 0
            is_central_match = getattr(tender, 'is_central_match', False)
            strategic_fit = getattr(tender, 'strategic_fit', False)
            primary_scope = getattr(tender, 'primary_scope', '') or 'Not specified'
            
            keywords = getattr(tender, 'keywords', '') or ''
            keyword_list = [k.strip() for k in keywords.split('|') if k.strip()] if keywords else []

            # Due date check : If due date less than 5 days then highlight in red color
            due_color = "black"
            if due_date and due_date != 'Not specified':
                if isinstance(due_date, str):
                    # If stored as string, convert to datetime
                    try:
                        due_dt = datetime.datetime.strptime(due_date, '%Y-%m-%d %H:%M:%S')
                    except:
                        try:
                            due_dt = datetime.datetime.strptime(due_date, '%Y-%m-%d')
                        except:
                            due_dt = None
                else:
                    due_dt = due_date
                
                if due_dt: 
                    if 0 <= (due_dt - datetime.datetime.now()).days <= 5:
                        due_color = "red"
            
            html_body += f"""
                <div class="tender-card">
                    <div class="tender-id" style="color: {due_color};">Tender ID: {getattr(tender, 'tender_id', 'Unknown')}</div>
                    <div class="tender-description">{description}</div>
                    <div class="tender-meta">
                        <strong>Due Date:</strong> {due_date} | 
                        <strong>Found:</strong> {creation_date}
                    </div>
            """
            
            if match_reason:
                html_body += f'<div class="match-reason"><strong>Why it matches:</strong> {match_reason}</div>'
            
            if primary_scope and primary_scope != 'Not specified':
                html_body += f'<div class="match-reason"><strong>Tender Scope:</strong> {primary_scope}</div>'
            
            html_body += f"""
                    <div class="match-scores">
                        <strong>Match Analysis:</strong>
                        Relevance: {relevance_percentage:.1f}% | 
                        Keyword Score: {match_score_keyword:.2f} | 
                        Combined Score: {match_score_combined:.2f}
            """
            
            if is_central_match:
                html_body += ' <span class="badge">Central Match</span>'
            if strategic_fit:
                html_body += ' <span class="badge">Strategic Fit</span>'
            
            html_body += '</div>'
            
            if keyword_list:
                html_body += f"""
                        <div class="keywords">
                            <strong>Matching Keywords:</strong> {', '.join(keyword_list[:10])}
                        </div>
                """
            
            if document_url:
                html_body += f'<div><a href="{document_url}" class="btn" target="_blank">View Tender Details</a></div>'
            
            html_body += '</div>'
    else:
        html_body += """
                <div style="text-align: center; padding: 40px; color: #666;">
                    <h3>No New Matching Tenders</h3>
                    <p>No new tenders matching your organization's services were found in this search.</p>
                </div>
        """
    
    html_body += f"""
                <div class="footer">
                    <p>This notification was generated by the GeM Tender Monitoring System.</p>
                    <p>To manage your notification preferences, please log in to the system.</p>
                    <p><small>Search Configuration ID: {search_config.id} | Generated at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small></p>
                </div>
            </div>
        </body>
    </html>
    """
    
    return html_body


def ordinal_date_str(dt: datetime.date) -> str:
    day = dt.day
    if 11 <= day <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix} {dt.strftime('%b %Y')}"


def send_notifications_for_config(search_config, mail, hours_back=4):
    """Send email notifications for new matching tenders for a specific search configuration"""
    try:
        organization_id = search_config.user.organization_id
        config_id = search_config.id
        
        logger.info(f"Processing email notifications for organization {organization_id}, config {config_id}")
        
        # Get recent matching tenders for this specific configuration
        recent_tenders = get_recent_matching_tenders(organization_id, config_id, hours_back)
        
        if not recent_tenders:
            logger.info(f"No recent matching tenders found for config {config_id}")
            return True
        
        # Get active recipients for this search config
        recipients = NotificationRecipient.query.filter_by(
            search_config_id=config_id,
            is_active=True
        ).all()
        
        if not recipients:
            logger.info(f"No active recipients for search config {config_id}")
            return True
        
        # Send notification
        try:
            today_str = ordinal_date_str(datetime.datetime.now().date())
            org_name = search_config.user.organization.name if search_config.user and search_config.user.organization else "Your Organization"
            subject = f"TenderGyan daily tender summary - for {org_name} - {today_str}"
            
            recipient_emails = [recipient.email for recipient in recipients]
            html_body = create_tender_notification_html(search_config, recent_tenders)
            
            # Create and send email
            msg = Message(
                subject=subject,
                recipients=recipient_emails,
                body="This is an automated TenderGyan notification based on your saved GeM criteria. Please view the email in HTML for full details",
                html=html_body
            )
            
            mail.send(msg)
            
            logger.info(f"Email sent for search config {config_id} to {len(recipient_emails)} recipients ({len(recent_tenders)} tenders)")
            return True
                
        except Exception as e:
            logger.error(f"Failed to send email for search config {config_id}: {e}")
            return False
        
    except Exception as e:
        logger.error(f"Error sending notifications for config {search_config.id}: {e}")
        return False


def main():
    """Main function to send email notifications for a specific configuration"""
    if len(sys.argv) < 3:
        print("Usage: python gem_email_notifier.py <organization_id> <search_config_id> [hours_back]")
        print("Example: python gem_email_notifier.py 1 5 2")
        sys.exit(1)
    
    try:
        organization_id = int(sys.argv[1])
        search_config_id = int(sys.argv[2])
        hours_back = int(sys.argv[3]) if len(sys.argv) > 3 else 2
        
        logger.info(f"Starting email notifications for organization {organization_id}, config {search_config_id}")
        logger.info(f"Looking for tenders from the last {hours_back} hours")
        
        # Create Flask app and mail instance
        app, mail = create_app()
        
        with app.app_context():
            # Verify organization exists
            organization = Organization.query.get(organization_id)
            if not organization:
                logger.error(f"Organization {organization_id} not found")
                sys.exit(1)
            
            # Verify search configuration exists and belongs to this organization
            search_config = SearchConfiguration.query.get(search_config_id)
            if not search_config:
                logger.error(f"Search configuration {search_config_id} not found")
                sys.exit(1)
            
            # Verify the config belongs to the organization
            if search_config.user.organization_id != organization_id:
                logger.error(f"Search configuration {search_config_id} does not belong to organization {organization_id}")
                sys.exit(1)
            
            logger.info(f"Processing notifications for organization: {organization.name}, config: {search_config.search_keyword}")
            
            # Send notifications for this specific configuration
            success = send_notifications_for_config(search_config, mail, hours_back)
            
            if success:
                logger.info("Email notification process completed successfully")
            else:
                logger.error("Email notification process failed")
                sys.exit(1)
        
    except ValueError:
        logger.error("Invalid arguments provided. Must be numbers.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error in main function: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()