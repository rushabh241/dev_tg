from flask import app, render_template, request, jsonify, redirect, url_for, flash, send_file
from flask import current_app
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Message
import re
from threading import Thread
import datetime
import subprocess
import os
import services
from flask import session

import io 
from services import analyze_gem_tender_service
from itsdangerous import URLSafeTimedSerializer, SignatureExpired,BadSignature
from datetime import date, timedelta
from sqlalchemy import create_engine, Table, MetaData, select
from tender_pdf_utils import generate_tender_pdf_bytes

from models import (
    db, 
    User,
    Tender,
    Document, 
    RiskAssessment,
    QAInteraction,
    SearchConfiguration,
    NotificationRecipient,
    ServiceProductDefinition,
    Constraint,
    GemTender,
    Organization,
    Product,
    BidderQuestionsSet,
    News, 
    FeatureAccessControl,
    GemTenderMaster,
    GemTenderMatch
)

def generate_risk_report_pdf_bytes(tender, risk_assessment, logo_path):
    """Generate PDF for all risks in one report"""
    if HTML is None:
        raise RuntimeError("WeasyPrint is not installed or not available.")
    
    def severity_badge(severity):
        sev = (severity or "").lower()
        if sev == "high":
            return "#dc3545"
        elif sev == "medium":
            return "#ffc107"
        return "#198754"
    
    def grouped_risks(category_name):
        return [
            r for r in risk_assessment.risks
            if (r.category or "").lower() == category_name
        ]
    
    def render_risk_block(risk):
        color = severity_badge(risk.severity)
        related_constraint_html = ""
        if risk.related_constraint:
            related_constraint_html = f"""
            <div class="constraint-box">
                <div class="mini-title">Related Constraint</div>
                <div>{risk.related_constraint}</div>
            </div>
            """
    
        return f"""
        <div class="risk-card">
            <div class="risk-header">
                <span class="severity-pill" style="background:{color};">
                    {(risk.severity or 'low').capitalize()}
                </span>
                <span class="risk-title">{risk.title or 'Untitled Risk'}</span>
            </div>
    
            <div class="risk-body">
                <p class="risk-description">{risk.description or 'No description available.'}</p>
    
                <table class="detail-table">
                    <tr>
                        <td class="label">Impact</td>
                        <td>{risk.impact or 'Not specified'}</td>
                    </tr>
                    <tr>
                        <td class="label">Mitigation</td>
                        <td>{risk.mitigation or 'Not specified'}</td>
                    </tr>
                </table>
    
                {related_constraint_html}
            </div>
        </div>
        """
    
    sections = []
    ordered_categories = [
        ("financial", "Financial Risks"),
        ("technical", "Technical Risks"),
        ("legal", "Legal Risks"),
        ("other", "Other Risks"),
    ]
    
    for key, title in ordered_categories:
        items = grouped_risks(key)
        if items:
            section_html = "".join(render_risk_block(r) for r in items)
        else:
            section_html = '<div class="empty-block">No risks identified in this category.</div>'
    
        sections.append(f"""
        <div class="section-group">
            <h2>{title}</h2>
            {section_html}
        </div>
        """)
    
    html_body = f"""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            @page {{
                size: A4;
                margin: 2cm 1.5cm 1.5cm 1.5cm;
            }}
    
            body {{
                font-family: Arial, Helvetica, sans-serif;
                font-size: 12px;
                line-height: 1.5;
                color: #333;
                margin: 0;
            }}
    
            .watermark {{
                position: fixed;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%) rotate(-45deg);
                opacity: 0.08;
                z-index: 0;
                width: 85%;
                pointer-events: none;
            }}
    
            .header-logo {{
                position: fixed;
                top: -0.8cm;
                right: 0;
                height: 32px;
                z-index: 1000;
            }}
    
            .container {{
                position: relative;
                z-index: 1;
            }}
    
            h1 {{
                color: #4B3B8C;
                border-bottom: 3px solid #4B3B8C;
                padding-bottom: 10px;
                font-size: 22px;
                margin: 0 0 20px 0;
            }}
    
            h2 {{
                color: #4B3B8C;
                font-size: 17px;
                margin: 24px 0 12px 0;
                page-break-after: avoid;
            }}
    
            .summary-grid {{
                width: 100%;
                margin-bottom: 24px;
                border-collapse: collapse;
            }}
    
            .summary-grid td {{
                border: 1px solid #ddd;
                padding: 12px;
                text-align: center;
            }}
    
            .summary-label {{
                font-size: 11px;
                color: #666;
                margin-bottom: 4px;
            }}
    
            .summary-value {{
                font-size: 22px;
                font-weight: bold;
            }}
    
            .risk-card {{
                border: 1px solid #ddd;
                border-radius: 6px;
                margin-bottom: 14px;
                page-break-inside: avoid;
                overflow: hidden;
            }}
    
            .risk-header {{
                padding: 10px 12px;
                background: #f8f9fa;
                border-bottom: 1px solid #ddd;
            }}
    
            .severity-pill {{
                display: inline-block;
                color: white;
                font-size: 11px;
                font-weight: bold;
                padding: 4px 8px;
                border-radius: 999px;
                margin-right: 8px;
            }}
    
            .risk-title {{
                font-weight: bold;
                font-size: 14px;
            }}
    
            .risk-body {{
                padding: 12px;
            }}
    
            .risk-description {{
                margin-top: 0;
                margin-bottom: 12px;
            }}
    
            .detail-table {{
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 10px;
            }}
    
            .detail-table td {{
                border: 1px solid #ddd;
                padding: 8px;
                vertical-align: top;
            }}
    
            .detail-table .label {{
                width: 22%;
                background: #f8f9fa;
                font-weight: bold;
            }}
    
            .constraint-box {{
                margin-top: 10px;
                padding: 10px;
                background: #f1f3f5;
                border-left: 4px solid #6c757d;
            }}
    
            .mini-title {{
                font-weight: bold;
                margin-bottom: 4px;
            }}
    
            .empty-block {{
                color: #777;
                padding: 12px;
                border: 1px dashed #ccc;
                border-radius: 6px;
            }}
    
            .meta {{
                margin-bottom: 18px;
                color: #666;
            }}
        </style>
    </head>
    <body>
        <img src="file:///{logo_path}" class="watermark" alt="Watermark Logo">
        <img src="file:///{logo_path}" class="header-logo" alt="Logo">
    
        <div class="container">
            <h1>Risk Assessment Report: {tender.title or 'Untitled Tender'}</h1>
    
            <div class="meta">
                <div><strong>Tender Number:</strong> {tender.tender_number or 'Not specified'}</div>
                <div><strong>Generated At:</strong> {risk_assessment.generated_at.strftime('%d-%m-%Y %H:%M') if risk_assessment.generated_at else 'Not specified'}</div>
            </div>
    
            <table class="summary-grid">
                <tr>
                    <td>
                        <div class="summary-label">Total Risks</div>
                        <div class="summary-value">{risk_assessment.total_risks or 0}</div>
                    </td>
                    <td>
                        <div class="summary-label">High Risk</div>
                        <div class="summary-value" style="color:#dc3545;">{risk_assessment.high_risks or 0}</div>
                    </td>
                    <td>
                        <div class="summary-label">Medium Risk</div>
                        <div class="summary-value" style="color:#b8860b;">{risk_assessment.medium_risks or 0}</div>
                    </td>
                    <td>
                        <div class="summary-label">Low Risk</div>
                        <div class="summary-value" style="color:#198754;">{risk_assessment.low_risks or 0}</div>
                    </td>
                </tr>
            </table>
    
            {''.join(sections)}
        </div>
    </body>
    </html>
    """
    
    pdf_file = io.BytesIO()
    HTML(string=html_body).write_pdf(pdf_file)
    pdf_file.seek(0)
    return pdf_file

# Add a global dictionary to track process completion
process_completion = {}

# Safe import for WeasyPrint (avoid crashing during migrations or on Windows)
try:
    from weasyprint import HTML
except Exception as e:
    print(f"[WARN] WeasyPrint not available: {e}")
    HTML = None

# In-memory dict to track running search config processes
# Format: {config_id: subprocess_process_object}
running_search_configs = {}

# Authentication Routes
def init_auth_routes(app, login_manager, mail):
    @login_manager.user_loader
    def load_user(user_id):
        """Load user by username instead of numeric ID"""
        return User.query.filter_by(username=user_id).first()
    
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            username = request.form['username']
            password = request.form['password']


            user = User.query.filter_by(username=username).first()
           
            
            if user and check_password_hash(user.password, password):
                login_user(user)
                user.last_login = datetime.datetime.utcnow()
                db.session.commit()
                return redirect(url_for('news_page'))

            return render_template('login.html', error='Invalid credentials')

        return render_template('login.html')
    
    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('login'))
    
    # Verify User
    @app.route('/verify-user', methods=['POST'])
    @login_required
    def verify_user():
        user = current_user
            
        # Check if the user is somehow anonymous
        if user.is_anonymous:
            return jsonify({'success': False, 'error': 'Authentication required'}), 401
                
        data = request.get_json()
        password = data.get('password')

        if not check_password_hash(user.password, password):
            return jsonify({'success': False, 'error': 'Incorrect current password'}), 401 
        
        return jsonify({'success': True})
        
    # Reset Password 
    @app.route('/reset-password', methods=['POST'])
    @login_required
    def reset_password():
        try:
            user = current_user
            
            # Check if the user is somehow anonymous
            if user.is_anonymous:
                return jsonify({'success': False, 'error': 'Authentication required'}), 401
                
            data = request.get_json()
            new_password = data.get('new_password')

            if not new_password:
                return jsonify({'success': False, 'error': 'New password is required'}), 400

            user.password = generate_password_hash(new_password)
            db.session.commit()
            
            return jsonify({'success': True})
        except Exception as e:
            print("Error resetting password:", e)
            return jsonify({'success': False, 'error': 'Internal server error while resetting password'}), 500

    @app.route('/forgot_password', methods=['POST'], endpoint='forgot_password')
    def forgot_password_post():
        try:
            data = request.get_json()
            email = data.get('email')

            user = User.query.filter_by(email=email).first()
            if not user:
                return jsonify({'success': True, 'message': '<b>User Not Found. Please enter registered email address</b>'})

            # Generate secure token (expires in 1 hour)
            s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
            token = s.dumps(email, salt='password-reset-salt')

            # Create full reset link
            reset_link = url_for('reset_password_with_token', token=token, _external=True)

            subject = "Tender Gyan - Reset Your Password"
            body = f"""
                Hello {user.username},

                We received a request to reset your Tender Gyan account password.
                Click the link below to set a new password (valid for 1 hour):

                {reset_link}

                If you didn’t request this, please ignore the email.

                Regards,  
                Tender Gyan Team
            """

            msg = Message(subject=subject,
                        recipients=[email],
                        body=body,
                        sender=current_app.config.get('MAIL_DEFAULT_SENDER'))
            mail.send(msg)

            return jsonify({'success': True, 'message': f'<b>Email verified successfully. Password reset link sent to {email}.</b>'})

        except Exception as e:
            print("Error in forgot_password_post:", e)
            return jsonify({'success': False, 'error': str(e)}), 500
        

    @app.route('/reset-password/<token>', methods=['GET', 'POST'])
    def reset_password_with_token(token):
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        try:
            # Verify and decode email from token
            email = s.loads(token, salt='password-reset-salt', max_age=3600)
        except SignatureExpired:
            return render_template('error.html', message='The reset link has expired.')
        except BadSignature:
            return render_template('error.html', message='Invalid reset link.')

        # If GET request -> render password reset form
        if request.method == 'GET':
            return render_template('reset_password.html', email=email, token=token)

        # If POST request -> update password
        if request.method == 'POST':
            data = request.get_json()
            new_password = data.get('new_password')

            user = User.query.filter_by(email=email).first()
            if not user:
                return jsonify({'success': False, 'error': 'User not found'}), 404

            user.password = generate_password_hash(new_password)
            db.session.commit()

            return jsonify({'success': True, 'message': '<b>Password has been reset successfully.</b>'})
    

# Main Content Routes
def init_main_routes(app, mail):
    # global current_tender_id
    # current_tender_id = session.get('current_tender_id')

    # @app.context_processor
    # def inject_url_prefix():
    #     plan_name = "Bronze" # Default
    #     if current_user.is_authenticated:
    #         # Fetch the active subscription
    #         sub = Subscription.query.filter_by(
    #             organization_id=current_user.organization_id,
    #             status='active'
    #         ).first()

    #         if sub:
    #             plan_name = sub.plan_name
        
    #     return dict(url_prefix=app.config.get('URL_PREFIX', ''), org_plan=plan_name)
    
    # @app.context_processor
    # def inject_url_prefix():
    #     return dict(url_prefix=app.config['URL_PREFIX'])

    @app.context_processor
    def inject_global_data():
        url_prefix = app.config['URL_PREFIX']
        access_control = None  # Keep for backward compatibility

        if current_user.is_authenticated:
            # Get all access controls for this organization
            controls = FeatureAccessControl.query.filter_by(
                organization_id=current_user.organization_id
            ).all()
            
            # Create an object-like dictionary that allows dot notation
            class AccessControlObject:
                def __init__(self, controls_dict):
                    self.__dict__.update(controls_dict)
            
            # Convert to dictionary first
            controls_dict = {control.menu_item: control.access for control in controls}
            
            # Then wrap in an object to allow dot notation
            access_control = AccessControlObject(controls_dict)

        return dict(
            url_prefix=url_prefix,
            access_control=access_control, # Now works with dot notation
            current_user=current_user
        )
    
    @app.route('/')
    @login_required
    def index():
        return redirect(url_for('upload_page'))

    @app.route('/upload')
    @login_required
    def upload_page():
        # Get user's recent tenders from their organization
        recent_tenders = Tender.query.filter_by(
            organization_id=current_user.organization_id
        ).order_by(Tender.created_at.desc()).limit(5).all()
        
        return render_template('upload.html', 
                              recent_tenders=recent_tenders, 
                              url_prefix=app.config['URL_PREFIX'],
                              organization=current_user.organization)

    @app.route('/overview')
    @login_required
    def overview_page():
        # global current_tender_id
        
        current_tender_id = session.get('current_tender_id')

        print(f"[DEBUG] overview_page() called. Session current_tender_id: {current_tender_id}")
        # print(f"[DEBUG] Session ID: {session.sid}")
        print(f"[DEBUG] User ID: {current_user.id}")
        print(f"[DEBUG] Session keys: {list(session.keys())}")
        print(f"[DEBUG] Session ID from cookie: {request.cookies.get('session')}")
        
        if not current_tender_id:
            print("[DEBUG] No current_tender_id in session, redirecting to upload")
            return redirect(url_for('upload_page'))
        
        tender = Tender.query.get_or_404(current_tender_id)
        documents = Document.query.filter_by(tender_id=current_tender_id).all()
        products = Product.query.filter_by(tender_id=current_tender_id).all()
        
        # Make sure the user belongs to the organization that owns this tender
        if tender.organization_id != current_user.organization_id:
            flash("You don't have permission to view this tender", "danger")
            return redirect(url_for('upload_page'))
        
        # Find the PDF path from GemTender table using tender_number
        pdf_path = None
        if tender.tender_number:
            gem_tender = GemTender.query.filter_by(
                organization_id=current_user.organization_id,
                tender_id=tender.tender_number  # Match GemTender.tender_id with Tender.tender_number
            ).first()

            # gem_tender = (
            #     db.session.query(GemTenderMaster)
            #     .join(GemTenderMatch)
            #     .filter(
            #         GemTenderMatch.organization_id == current_user.organization_id,
            #         GemTenderMaster.tender_id == tender.tender_number
            #     )
            #     .first()
            # )


            if gem_tender and gem_tender.pdf_path:
                # Clean and prepare the PDF path similar to gem_tenders.html
                raw_path = gem_tender.pdf_path.replace('\\', '/')
                clean_path = raw_path.replace('gem_bids/', '')
                clean_path = clean_path.replace('gem_bids\\', '')
                pdf_path = 'gem_bids/' + clean_path
                print(f"Found PDF path for tender {tender.tender_number}: {pdf_path}")
        
        return render_template('overview.html', 
                              overview={
                                  # Basic Information
                                  'tender_number': tender.tender_number,
                                  'description': tender.description,
                                  'organization_details': tender.organization_details,
                                  
                                  # Critical Dates
                                  'due_date': tender.due_date,
                                  'bid_opening_date': tender.bid_opening_date,           
                                  'bid_offer_validity': tender.bid_offer_validity, 
                                  'question_deadline': tender.question_deadline,
                                  
                                  # Financial Requirements
                                  'emd_amount': tender.emd_amount,
                                  'estimated_cost': tender.estimated_cost,
                                  'performance_security': tender.performance_security,
                                  'payment_terms': tender.payment_terms,
                                  
                                  # Qualification & Evaluation
                                  'qualification_criteria': tender.qualification_criteria,
                                  'evaluation_criteria': tender.evaluation_criteria,
                                  
                                  # Technical Requirements
                                  'technical_specifications': tender.technical_specifications,
                                  'scope_of_work': tender.scope_of_work,
                                  'performance_standards': tender.performance_standards,
                                  
                                  # Special Provisions
                                  'reverse_auction': tender.reverse_auction,
                                  'msme_preferences': tender.msme_preferences,
                                  'border_country_clause': tender.border_country_clause,
                                  
                                  # Compliance
                                  'rejection_criteria': tender.rejection_criteria,
                                  'documentation_requirements': tender.documentation_requirements,

                                  # Additional Info
                                  'additional_details': tender.additional_details
                              },
                              tender=tender,
                              documents=documents,
                              products=products,
                              pdf_path=pdf_path,
                              organization=current_user.organization,
                              url_prefix=app.config['URL_PREFIX'])

    @app.route('/qa')
    @login_required
    def qa_page():
        # global current_tender_id
        current_tender_id = session.get('current_tender_id')
        
        if not current_tender_id:
            return redirect(url_for('upload_page'))
        
        tender = Tender.query.get_or_404(current_tender_id)
        
        # Make sure the user belongs to the organization that owns this tender
        if tender.organization_id != current_user.organization_id:
            flash("You don't have permission to view this tender", "danger")
            return redirect(url_for('upload_page'))
        
        # Get previous Q&A for this tender
        qa_history = QAInteraction.query.filter_by(tender_id=tender.id).order_by(QAInteraction.created_at.desc()).all()
        
        return render_template('qa.html', 
                              tender=tender,
                              qa_history=qa_history,
                              organization=current_user.organization,
                              overview={
                                  'due_date': tender.due_date,
                                  'emd_amount': tender.emd_amount,
                                  'qualification_criteria': tender.qualification_criteria,
                                  'question_deadline': tender.question_deadline
                              })

    @app.route('/bidder-questions')
    @login_required
    def bidder_questions_page():
        # global current_tender_id
        current_tender_id = session.get('current_tender_id')
        
        if not current_tender_id:
            return redirect(url_for('upload_page'))
        
        tender = Tender.query.get_or_404(current_tender_id)
        
        # Make sure the user belongs to the organization that owns this tender
        if tender.organization_id != current_user.organization_id:
            flash("You don't have permission to view this tender", "danger")
            return redirect(url_for('upload_page'))
        
        questions_exist = BidderQuestionsSet.query.filter_by(
            tender_id = current_tender_id
        ).first() is not None
        
        return render_template('bidder_questions.html', 
                              tender=tender,
                              organization=current_user.organization,
                              questions_generated=questions_exist,
                              overview={
                                  'due_date': tender.due_date,
                                  'emd_amount': tender.emd_amount,
                                  'qualification_criteria': tender.qualification_criteria,
                                  'question_deadline': tender.question_deadline
                              })

    @app.route('/organization', methods=['GET'])
    @login_required
    def organization_page():
        """Display comprehensive organization management page"""
        # Get organization details
        organization = current_user.organization
    
        # Get organization users
        users = User.query.filter_by(organization_id=organization.id).all()
    
        # Get organization's constraints
        financial_constraints = Constraint.query.filter_by(organization_id=current_user.organization_id, category='financial').all()
        technical_constraints = Constraint.query.filter_by(organization_id=current_user.organization_id, category='technical').all()
        legal_constraints = Constraint.query.filter_by(organization_id=current_user.organization_id, category='legal').all()
        other_constraints = Constraint.query.filter_by(organization_id=current_user.organization_id, category='other').all()
    
        # Get service and product definition
        definition = ServiceProductDefinition.query.filter_by(organization_id=current_user.organization_id).first()
        service_product_definition = definition.definition if definition else ""
    
        # Get search configurations
        search_configs = SearchConfiguration.query \
            .join(User, SearchConfiguration.created_by == User.id) \
            .filter(User.organization_id == current_user.organization_id) \
            .all()

    
        return render_template('organization_management.html',
                          organization=organization,
                          users=users,
                          financial_constraints=financial_constraints,
                          technical_constraints=technical_constraints,
                          legal_constraints=legal_constraints,
                          other_constraints=other_constraints,
                          service_product_definition=service_product_definition,
                          search_configs=search_configs,
                          current_user=current_user)

    @app.route('/constraints')
    @login_required
    def constraints_page():
        # Get organization's constraints
        financial_constraints = Constraint.query.filter_by(organization_id=current_user.organization_id, category='financial').all()
        technical_constraints = Constraint.query.filter_by(organization_id=current_user.organization_id, category='technical').all()
        legal_constraints = Constraint.query.filter_by(organization_id=current_user.organization_id, category='legal').all()
        other_constraints = Constraint.query.filter_by(organization_id=current_user.organization_id, category='other').all()
        
        # Get service and product definition for the organization
        definition = ServiceProductDefinition.query.filter_by(organization_id=current_user.organization_id).first()
        definition_text = definition.definition if definition else ""
        
        return render_template('constraints.html',
                              financial_constraints=financial_constraints,
                              technical_constraints=technical_constraints,
                              legal_constraints=legal_constraints,
                              other_constraints=other_constraints,
                              service_product_definition=definition_text,
                              organization=current_user.organization)

    @app.route('/gem-tenders')
    @login_required
    def gem_tenders_page():
        """Display tenders from multiple portals - SHOWING ALL TENDERS"""
        # Get service definition
        definition = ServiceProductDefinition.query.filter_by(
            organization_id=current_user.organization_id
        ).order_by(ServiceProductDefinition.updated_at.desc()).first()
        
        service_definition = definition.definition if definition else "No service definition available."
        
        # Get organization's GeM tenders from GemTender table
        gem_tenders = GemTender.query.filter_by(
            organization_id=current_user.organization_id
        ).all()

        # gem_tenders = (
        #     db.session.query(GemTenderMaster)
        #     .join(
        #         GemTenderMatch,
        #         GemTenderMatch.master_tender_id == GemTenderMaster.id
        #     )
        #     .filter(
        #         GemTenderMatch.organization_id == current_user.organization_id
        #     )
        # ).all()

        # Get organization's MahaTender and CPPP Tenders from Tender table
        # FIX: Get ALL tenders first, then filter in Python
        tender_table_tenders = Tender.query.filter_by(
            organization_id=current_user.organization_id
        ).all()

        # DEBUG: Print all sources to see what we have
        all_sources = set()
        for t in tender_table_tenders:
            if t.source:
                all_sources.add(t.source)
        print(f"=== DEBUG: ALL SOURCES IN DATABASE ===")
        print(f"All sources: {all_sources}")
        print(f"Total tenders in database: {len(tender_table_tenders)}")
        
        # Process GeM Tenders (from GemTender table) - SHOW ALL TENDERS
        valid_tenders = []
        expired_tenders = []

        # Process GeM tenders - ALL tenders
        for t in gem_tenders:
            due = None
            if t.due_date and t.due_date != "Not specified":
                try:
                    due = datetime.datetime.strptime(t.due_date, "%d-%m-%Y").date()
                except ValueError:
                    pass
            
            if due is not None:
                if due >= date.today():
                    valid_tenders.append(t)
                else:
                    expired_tenders.append(t)
            else:
                # Tenders without due date
                valid_tenders.append(t)

        # Get ALL matching GeM tenders
        gem_matching_tenders = GemTender.query.filter_by(
            organization_id=current_user.organization_id,
            matches_services=True
        ).all()

        # gem_matching_tenders = (
        #     db.session.query(GemTenderMaster, GemTenderMatch)
        #     .join(
        #         GemTenderMatch,
        #         GemTenderMaster.id == GemTenderMatch.master_tender_id
        #     )
        #     .filter(
        #         GemTenderMatch.organization_id == current_user.organization_id,
        #         GemTenderMatch.matches_services == True
        #     )
        # ).all()


        valid_matching_tenders = []
        # Show ALL matching tenders regardless of date
        for mt in gem_matching_tenders:
            valid_matching_tenders.append(mt)  # Add ALL matching tenders

        # for tender_master, tender_match in gem_matching_tenders:
        #     tender_master.match_reason = tender_match.match_reason
        #     valid_matching_tenders.append(tender_master)

        # Process MahaTender and CPPP Tenders from Tender table
        # Get ALL Maha and CPPP tenders (check for different source variations)
        maha_tenders = []
        cppp_tenders = []
        
        for t in tender_table_tenders:
            if t.source:
                # Check for Maha tenders (case-insensitive)
                if 'maha' in t.source.lower():
                    maha_tenders.append(t)
                # Check for CPPP tenders (case-insensitive)
                elif 'cppp' in t.source.lower():
                    cppp_tenders.append(t)
        
        print(f"=== DEBUG: FILTERED COUNTS ===")
        print(f"Maha tenders found: {len(maha_tenders)}")
        print(f"CPPP tenders found: {len(cppp_tenders)}")
        
        # Process MahaTenders - SHOW ALL TENDERS
        maha_valid_tenders = []
        maha_expired_tenders = []
        
        for t in maha_tenders:
            due = None
            if t.due_date and t.due_date != "Not specified":
                try:
                    due = datetime.datetime.strptime(t.due_date, "%d-%m-%Y").date()
                except ValueError:
                    try:
                        due = datetime.datetime.strptime(t.due_date, "%Y-%m-%d").date()
                    except ValueError:
                        pass
            
            if due is not None:
                if due >= date.today():
                    maha_valid_tenders.append(t)
                else:
                    maha_expired_tenders.append(t)
            else:
                # Tenders without valid due date go to "All Tenders"
                maha_valid_tenders.append(t)
        
        # Process CPPP Tenders - SHOW ALL TENDERS
        cppp_valid_tenders = []
        cppp_expired_tenders = []
        
        for t in cppp_tenders:
            due = None
            has_valid_date = False
            
            if t.due_date and t.due_date != "Not specified":
                # Try different date formats
                date_formats = ["%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"]
                
                for date_format in date_formats:
                    try:
                        # Clean the date string (remove time part if present)
                        date_str = t.due_date.split(',')[0].strip()  # Remove time part after comma
                        due = datetime.datetime.strptime(date_str, date_format).date()
                        has_valid_date = True
                        break
                    except ValueError:
                        continue
            
            # Check if tender has PDF documents
            t.has_pdf = False
            t.pdf_paths = []
            if t.documents:
                for doc in t.documents:
                    if doc.file_path and (doc.file_type == 'pdf' or doc.original_filename.lower().endswith('.pdf')):
                        t.has_pdf = True
                        t.pdf_paths.append({
                            'path': doc.file_path,
                            'filename': doc.original_filename,
                            'is_primary': doc.is_primary
                        })
            
            if has_valid_date and due is not None:
                if due >= date.today():
                    cppp_valid_tenders.append(t)
                else:
                    cppp_expired_tenders.append(t)
            else:
                # Tenders without valid due date go to "All Tenders"
                cppp_valid_tenders.append(t)

        # Combine all tenders for the template
        all_valid_tenders = valid_tenders + maha_valid_tenders + cppp_valid_tenders
        all_expired_tenders = expired_tenders + maha_expired_tenders + cppp_expired_tenders

        # Mark analyzed GeM tenders
        analyzed_tender_ids = {
            t.tender_number for t in Tender.query.filter_by(
                organization_id=current_user.organization_id
            ).all() if t.tender_number
        }

        for tender in valid_matching_tenders:
            tender.is_analyzed = tender.tender_id in analyzed_tender_ids
        
        return render_template('gem_tenders.html',
                            service_definition=service_definition,
                            matching_tenders=valid_matching_tenders,
                            valid_tenders=all_valid_tenders,
                            expired_tenders=all_expired_tenders,
                            organization=current_user.organization)
    

    # @app.route('/gem-search-config/run-now/<int:config_id>', methods=['POST'])
    # @login_required
    # def run_search_config_now(config_id):
    #     """Run a search configuration immediately - synchronous like scheduler"""
    #     config = SearchConfiguration.query.get_or_404(config_id)
        
    #     # Capture organization_id
    #     org_id = current_user.organization_id
        
    #     try:
    #         # Parse search keyword
    #         search_keyword = config.search_keyword or ""
            
    #         domain_pattern = r'(\w+)\s*\(([^)]+)\)'
    #         domain_matches = re.findall(domain_pattern, search_keyword)
            
    #         if domain_matches:
    #             # Extract the search term (outside parentheses)
    #             search_term = domain_matches[0][0].strip()
    #             domain_keywords = "|".join([k.strip() for k in domain_matches[0][1].split(',')])
    #         else:
    #             # No domain format - use as-is
    #             search_term = search_keyword.strip() if search_keyword else "none"
    #             domain_keywords = "NONE"
            
    #         # Use CLI arguments - exactly as scheduler does
    #         cmd = [
    #             "python", "gem_nlp_api.py",
    #             search_term,
    #             str(config.max_tenders),
    #             str(org_id),
    #             domain_keywords,
    #             str(config.id)
    #         ]
            
    #         print(f"[DEBUG] Running: {' '.join(cmd)}")
            
    #         # Run process and WAIT for completion (like scheduler does)
    #         process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    #         stdout, stderr = process.communicate()  # ← This waits!
            
    #         # Log output
    #         if stdout:
    #             print(f"[DEBUG] Process stdout: {stdout.decode()}")
    #         if stderr:
    #             print(f"[DEBUG] Process stderr: {stderr.decode()}")
            
    #         # Record the run time
    #         config.last_run = datetime.datetime.now()
    #         db.session.commit()
            
    #         if process.returncode == 0:
    #             return jsonify({
    #                 'success': True,
    #                 'completed': True,
    #                 'message': 'Search completed successfully'
    #             })
    #         else:
    #             return jsonify({
    #                 'success': False,
    #                 'error': f'Process failed with return code {process.returncode}'
    #             }), 500
                
    #     except Exception as e:
    #         print(f"[ERROR] Exception running search: {e}")
    #         return jsonify({'error': str(e)}), 500


    @app.route('/gem-search-config/run-now/<int:config_id>', methods=['POST'])
    @login_required
    def run_search_config_now(config_id):
        """Run a search configuration immediately - synchronous like scheduler"""
        config = SearchConfiguration.query.get_or_404(config_id)
        
        # Capture organization_id
        org_id = current_user.organization_id
        
        try:
            # Parse search keyword
            search_keyword = config.search_keyword or ""
            
            # Pattern to match keyword(keywords) format
            domain_pattern = r'(\w+)\s*\(([^)]+)\)'
            domain_matches = re.findall(domain_pattern, search_keyword)
            
            search_terms = []
            
            if domain_matches:
                # Extract all keywords from the pattern
                # Format: "Spacer(spacer), Bearing(bearing), Roller(roller), ..."
                for match in domain_matches:
                    search_term = match[0].strip()
                    domain_keywords = "|".join([k.strip() for k in match[1].split(',')])
                    search_terms.append({
                        'search_term': search_term,
                        'domain_keywords': domain_keywords
                    })
            else:
                # No domain format - use as-is with no domain keywords
                # Check if multiple comma-separated keywords
                if ',' in search_keyword:
                    # Split by comma and strip whitespace
                    keywords = [kw.strip() for kw in search_keyword.split(',')]
                    for kw in keywords:
                        search_terms.append({
                            'search_term': kw,
                            'domain_keywords': "NONE"
                        })
                else:
                    # Single keyword
                    search_terms.append({
                        'search_term': search_keyword.strip() if search_keyword else "none",
                        'domain_keywords': "NONE"
                    })
            
            if not search_terms:
                return jsonify({
                    'success': False,
                    'error': 'No valid search terms found'
                }), 400
            
            print(f"[DEBUG] Processing {len(search_terms)} search term(s)")
            
            # Track results for all searches
            results = []
            all_success = True
            
            # Run gem_nlp_api.py for each search term
            for idx, term_data in enumerate(search_terms):
                search_term = term_data['search_term']
                domain_keywords = term_data['domain_keywords']
                
                # Use CLI arguments - exactly as scheduler does
                cmd = [
                    "python", "gem_nlp_api.py",
                    search_term,
                    str(config.max_tenders),
                    str(org_id),
                    domain_keywords,
                    str(config.id)
                ]
                
                print(f"[DEBUG] Running search {idx+1}/{len(search_terms)}: {' '.join(cmd)}")
                
                try:
                    # Run process and WAIT for completion
                    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    stdout, stderr = process.communicate()  # ← This waits!
                    
                    # Log output
                    if stdout:
                        print(f"[DEBUG] Process stdout for '{search_term}': {stdout.decode()}")
                    if stderr:
                        print(f"[DEBUG] Process stderr for '{search_term}': {stderr.decode()}")
                    
                    # Record individual result
                    result = {
                        'search_term': search_term,
                        'domain_keywords': domain_keywords,
                        'success': process.returncode == 0,
                        'return_code': process.returncode
                    }
                    results.append(result)
                    
                    if process.returncode != 0:
                        all_success = False
                        
                except Exception as e:
                    print(f"[ERROR] Exception running search for '{search_term}': {e}")
                    results.append({
                        'search_term': search_term,
                        'domain_keywords': domain_keywords,
                        'success': False,
                        'error': str(e)
                    })
                    all_success = False
            
            # Record the run time after all searches complete
            config.last_run = datetime.datetime.now()
            db.session.commit()
            
            # Prepare response
            response = {
                'success': all_success,
                'total_searches': len(search_terms),
                'completed_searches': len([r for r in results if r.get('success', False)]),
                'failed_searches': len([r for r in results if not r.get('success', False)]),
                'details': results
            }
            
            if all_success:
                response['message'] = f'All {len(search_terms)} search(es) completed successfully'
                return jsonify(response)
            else:
                response['error'] = f'{response["failed_searches"]} out of {len(search_terms)} search(es) failed'
                return jsonify(response), 500
                    
        except Exception as e:
            print(f"[ERROR] Exception running search: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/process-status/<process_id>', methods=['GET'])
    @login_required
    def check_process_status(process_id):
        """Check if the gem_nlp_api.py process has completed"""
        global process_completion
        
        print(f"[DEBUG] Checking status for process_id: {process_id}")
        
        process_info = process_completion.get(process_id)
        
        if not process_info:
            print(f"[DEBUG] Process not found in tracker")
            return jsonify({
                'completed': False,
                'status': 'not_found'
            })
        
        print(f"[DEBUG] Process info: {process_info}")
        
        return jsonify({
            'completed': process_info['status'] in ['completed', 'failed'],
            'status': process_info['status'],
            'return_code': process_info.get('return_code'),
            'error': process_info.get('error')
        })

    @app.route('/view-pdf')
    @login_required
    def view_pdf():
        """View a PDF file"""
        pdf_path = request.args.get('path')
        if pdf_path:
            filename = os.path.basename(pdf_path)
            pdf_path = os.path.join("/app/gem_bids", filename)
        
        if not pdf_path or not os.path.exists(pdf_path):
            return "PDF file not found", 404
        
        # Simple security check to ensure we're only serving PDFs from the gem_bids directory
        if not pdf_path.startswith('gem_bids/') and not os.path.abspath(pdf_path).startswith(os.path.abspath('gem_bids')):
            return "Access denied", 403
        
        return send_file(pdf_path, as_attachment=False, mimetype='application/pdf')
        
    @app.route('/risk-assessment')
    @login_required
    def risk_assessment_page():
        # global current_tender_id
        current_tender_id = session.get('current_tender_id')
        
        if not current_tender_id:
            return redirect(url_for('upload_page'))
        
        tender = Tender.query.get_or_404(current_tender_id)
        
        # Make sure the user belongs to the organization that owns this tender
        if tender.organization_id != current_user.organization_id:
            flash("You don't have permission to view this tender", "danger")
            return redirect(url_for('upload_page'))
        
        # Get the most recent risk assessment for this tender
        risk_assessment = RiskAssessment.query.filter_by(tender_id=tender.id).order_by(RiskAssessment.generated_at.desc()).first()
        
        return render_template('risk_assessment.html', 
                              tender=tender,
                              organization=current_user.organization,
                              risk_assessment=risk_assessment)
    

    # @app.route('/analyze_tender', methods=['POST'])
    # @login_required
    # def analyze_tender():
    #     # global current_tender_id  
    #     current_tender_id = session.get('current_tender_id')

    #     try:
    #         print("=" * 50, flush=True)
    #         print("ANALYZE TENDER STARTED", flush=True)
    #         print("=" * 50, flush=True)
            
    #         data = request.get_json()
    #         gem_tender_id = data.get('tender_id')
    #         print(f"[1] Tender ID from request: {gem_tender_id}", flush=True)

    #         if not gem_tender_id:
    #             print("[ERROR] No tender ID provided", flush=True)
    #             return jsonify({'error': 'Tender ID not provided'}), 400

    #         print(f"[2] Querying database for tender_id: {gem_tender_id}", flush=True)
    #         gem_tender = GemTender.query.filter_by(tender_id=gem_tender_id).first()
    #         print(f"[3] GemTender found: {bool(gem_tender)}", flush=True)

    #         if not gem_tender:
    #             print(f"[ERROR] No GemTender found with ID {gem_tender_id}", flush=True)
    #             return jsonify({'error': f'GeM Tender with ID {gem_tender_id} not found'}), 404

    #         print(f"[4] GemTender.id: {gem_tender.id}", flush=True)
    #         print(f"[5] Original PDF path from DB: {gem_tender.pdf_path}", flush=True)
            
    #         # Construct the Docker path
    #         pdf_path = os.path.join("/app/gem_bids", os.path.basename(gem_tender.pdf_path))
    #         print(f"[6] Constructed PDF path: {pdf_path}", flush=True)
    #         print(f"[7] PDF basename: {os.path.basename(gem_tender.pdf_path)}", flush=True)
    #         print(f"[8] PDF exists check: {os.path.exists(pdf_path)}", flush=True)
            
    #         # List files in gem_bids directory
    #         try:
    #             files_in_dir = os.listdir("/app/gem_bids")
    #             print(f"[9] Files in /app/gem_bids: {files_in_dir[:10]}", flush=True)  # First 10 files
    #         except Exception as e:
    #             print(f"[9] Error listing /app/gem_bids: {e}", flush=True)

    #         # check if pdf is available or not
    #         if not pdf_path or not os.path.exists(pdf_path):
    #             print(f"[ERROR] PDF NOT FOUND at: {pdf_path}", flush=True)
    #             return jsonify({'error': f'PDF not found for tender {gem_tender_id}'}), 404

    #         print(f"[10] PDF found! Starting analysis...", flush=True)
    #         print(f"[11] Calling analyze_gem_tender_service with:", flush=True)
    #         print(f"     - pdf_path: {pdf_path}", flush=True)
    #         print(f"     - user_id: {current_user.id}", flush=True)
    #         print(f"     - organization_id: {current_user.organization_id}", flush=True)
            
    #         # Analyze tender using Gemini -> in services.py
    #         tender = analyze_gem_tender_service(
    #             pdf_path=pdf_path,
    #             gem_tender=gem_tender,
    #             user_id=current_user.id,
    #             organization_id=current_user.organization_id
    #         )

    #         print(f"[12] Analysis completed! Tender.id: {tender.id}", flush=True)
            
    #         # Set current_tender_id so overview_page() can access it
    #         # current_tender_id = tender.id
    #         session['current_tender_id'] = tender.id
            
    #         print(f"[13] Returning redirect to overview_page", flush=True)
    #         print("=" * 50, flush=True)
            
    #         # Redirect to overview_page
    #         return jsonify({'redirect_url': url_for('overview_page')})

    #     except Exception as e:
    #         print("=" * 50, flush=True)
    #         print(f"[ERROR] EXCEPTION IN analyze_tender: {e}", flush=True)
    #         print("=" * 50, flush=True)
    #         import traceback
    #         print(traceback.format_exc(), flush=True)
    #         current_app.logger.error(f"[ERROR] analyze_tender failed: {e}", exc_info=True)
    #         return jsonify({'error': str(e)}), 500

    
    @app.route('/analyze_tender', methods=['POST'])
    @login_required
    def analyze_tender():
        current_tender_id = session.get('current_tender_id')

        try:
            print("=" * 50, flush=True)
            print("ANALYZE TENDER STARTED", flush=True)
            print("=" * 50, flush=True)

            data = request.get_json()
            tender_identifier = data.get('tender_id')
            print(f"[1] Tender ID from request: {tender_identifier}", flush=True)

            if not tender_identifier:
                return jsonify({'error': 'Tender ID not provided'}), 400

            # ------------------------------------------------------------------
            # Try GeM tender
            # ------------------------------------------------------------------
            gem_tender = GemTender.query.filter_by(tender_id=tender_identifier).first()

            # gem_tender = (
            #     db.session.query(GemTenderMaster)
            #     .join(GemTenderMatch)
            #     .filter(
            #         GemTenderMatch.master_tender_id == GemTenderMaster.id,
            #         GemTenderMaster.tender_id == tender_identifier
            #     )
            # ).first()

            print(f"[2] GemTender found: {bool(gem_tender)}", flush=True)

            if gem_tender:
                print(f"[3] GemTender.id: {gem_tender.id}", flush=True)

                pdf_path = os.path.join(
                    "/app/gem_bids",
                    os.path.basename(gem_tender.pdf_path)
                )

                if not os.path.exists(pdf_path):
                    return jsonify({'error': 'PDF not found'}), 404

                tender = analyze_gem_tender_service(
                    pdf_path=pdf_path,
                    gem_tender=gem_tender,
                    user_id=current_user.id,
                    organization_id=current_user.organization_id
                )

                print(f"[4] GeM analysis done, Tender.id: {tender.id}", flush=True)

            else:
                # ------------------------------------------------------------------
                # CPPP / MahaTender flow
                # ------------------------------------------------------------------
                print("[5] Not a GeM tender, checking Tender table", flush=True)

                tender = Tender.query.filter_by(
                    tender_reference_number=tender_identifier
                ).first()

                if not tender and tender_identifier.isdigit():
                    tender = Tender.query.filter_by(
                        id=int(tender_identifier)
                    ).first()

                if not tender:
                    return jsonify({'error': 'Tender not found'}), 404

                print(f"[6] Found Tender:", flush=True)
                print(f"    ID: {tender.id}", flush=True)
                print(f"    Source (before): {tender.source}", flush=True)

            # ------------------------------------------------------------------
            # Store tender id in session and redirect
            # ------------------------------------------------------------------
            session['current_tender_id'] = tender.id
            print(f"[7] Session current_tender_id set to {tender.id}", flush=True)

            print("=" * 50, flush=True)
            return jsonify({'redirect_url': url_for('overview_page')})

        except Exception as e:
            print("=" * 50, flush=True)
            print(f"[ERROR] analyze_tender failed: {e}", flush=True)
            print("=" * 50, flush=True)
            import traceback
            print(traceback.format_exc(), flush=True)
            current_app.logger.error("analyze_tender error", exc_info=True)
            return jsonify({'error': str(e)}), 500

# API Routes
def init_api_routes(app, mail):
    # global current_tender_id
    # current_tender_id = session.get('current_tender_id')



    @app.route('/export-risk-report-pdf', methods=['GET'])
    @login_required
    def export_risk_report_pdf():
        """Download one PDF containing all risks for the current tender"""
        current_tender_id = session.get('current_tender_id')
    
        if not current_tender_id:
            return jsonify({'error': 'No active tender'}), 400
    
        tender = Tender.query.get_or_404(current_tender_id)
    
        if tender.organization_id != current_user.organization_id:
            return jsonify({'error': 'Permission denied'}), 403
    
        risk_assessment = (
            RiskAssessment.query
            .filter_by(tender_id=tender.id)
            .order_by(RiskAssessment.generated_at.desc())
            .first()
        )
    
        if not risk_assessment:
            return jsonify({'error': 'No risk assessment found'}), 404
    
        try:
            logo_path = os.path.join(os.path.dirname(__file__), 'static', 'TenderGyan_Logo.png')
            pdf_file = generate_risk_report_pdf_bytes(
                tender=tender,
                risk_assessment=risk_assessment,
                logo_path=logo_path
            )
    
            safe_filename = re.sub(r'[^A-Za-z0-9._-]+', '_', tender.title or 'Risk_Assessment')
    
            return send_file(
                pdf_file,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f"{safe_filename}_risk_report.pdf"
            )
    
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            current_app.logger.error(f"Error exporting risk report PDF: {error_details}")
    
            return jsonify({
                'error': f'Risk PDF export failed: {str(e)}',
                'details': error_details if current_app.debug else None
            }), 500


    @app.route('/export-tender-pdf', methods=['GET'])
    @login_required
    def export_tender_pdf():
        """Generate and download tender overview PDF"""
        current_tender_id = session.get('current_tender_id')

        if not current_tender_id:
            return jsonify({'error': 'No active tender'}), 400

        tender = Tender.query.get_or_404(current_tender_id)
        products = Product.query.filter_by(tender_id=current_tender_id).all()
        documents = Document.query.filter_by(tender_id=current_tender_id).all()

        if tender.organization_id != current_user.organization_id:
            return jsonify({'error': 'Permission denied'}), 403

        try:
            logo_path = os.path.join(os.path.dirname(__file__), 'static', 'TenderGyan_Logo.png')

            pdf_file = generate_tender_pdf_bytes(
                tender=tender,
                products=products,
                documents=documents,
                logo_path=logo_path
            )

            safe_filename = re.sub(r'[^A-Za-z0-9._-]+', '_', tender.title or 'Tender_Overview')

            return send_file(
                pdf_file,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f"{safe_filename}.pdf"
            )

        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            current_app.logger.error(f"Error exporting tender PDF: {error_details}")

            return jsonify({
                'error': f'PDF export failed: {str(e)}',
                'details': error_details if current_app.debug else None
            }), 500
    
    @app.route('/send-tender-email', methods=['POST'])
    @login_required
    def send_tender_email():
        """Send focused tender overview details via email"""
        current_tender_id = session.get('current_tender_id')

        if not current_tender_id:
            return jsonify({'error': 'No active tender'}), 400

        tender = Tender.query.get_or_404(current_tender_id)
        products = Product.query.filter_by(tender_id=current_tender_id).all()

        # Ensure organization match
        if tender.organization_id != current_user.organization_id:
            return jsonify({'error': 'Permission denied'}), 403

        data = request.json
        recipient_email = data.get('email')

        if not recipient_email:
            return jsonify({'error': 'Email address is required'}), 400

        try:
            documents = Document.query.filter_by(tender_id=current_tender_id).all()

            subject = f"Tender Overview: {tender.title}"
            logo_path = os.path.join(os.path.dirname(__file__), 'static', 'TenderGyan_Logo.png')

             # ============================================================
            # NEW SHARED PDF GENERATION LOGIC
            # ============================================================
            pdf_file = generate_tender_pdf_bytes(
                tender=tender,
                products=products,
                documents=documents,
                logo_path=logo_path
            )


            msg = Message(
                subject=subject,
                recipients=[recipient_email],
                sender=current_app.config.get('MAIL_DEFAULT_SENDER')
            )

            safe_filename = re.sub(r'[^A-Za-z0-9._-]+', '_', tender.title or 'Tender_Overview')

            # Attach PDF
            msg.attach(
                filename=f"{safe_filename}.pdf",
                content_type='application/pdf',
                data=pdf_file.read()
            )

            mail.send(msg)

            return jsonify({
                'success': True,
                'message': f'Overview sent to {recipient_email}'
            })

        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            current_app.logger.error(f"Email sending failed: {error_details}")

            return jsonify({
                'error': f'Email failed: {str(e)}',
                'details': error_details if current_app.debug else None
            }), 500


    @app.route('/export-tender-data', methods=['GET'])
    @login_required
    def export_tender_data():
        """Export focused tender data as JSON"""
        current_tender_id = session.get('current_tender_id')

        if not current_tender_id:
            return jsonify({'error': 'No active tender'}), 400

        tender = Tender.query.get_or_404(current_tender_id)

        if tender.organization_id != current_user.organization_id:
            return jsonify({'error': 'Permission denied'}), 403

        # Create focused export data (only selected fields)
        export_data = {
            'basic_information': {
                'tender_number': tender.tender_number,
                'organization_details': tender.organization_details,
                'title': tender.title,
            },
            'critical_dates': {
                'due_date': tender.due_date,
                'question_deadline': tender.question_deadline,
            },
            'financial_requirements': {
                'emd_amount': tender.emd_amount,
                'performance_security': tender.performance_security,
                'payment_terms': tender.payment_terms,
            },
            'qualification_evaluation': {
                'qualification_criteria': tender.qualification_criteria,
                'evaluation_criteria': tender.evaluation_criteria,
            },
            'technical_requirements': {
                'technical_specifications': tender.technical_specifications,
                'scope_of_work': tender.scope_of_work,
                'performance_standards': tender.performance_standards,
            },
            'special_provisions': {
                'reverse_auction': tender.reverse_auction,
                'msme_preferences': tender.msme_preferences,
                'border_country_clause': tender.border_country_clause,
            },
            'compliance': {
                'rejection_criteria': tender.rejection_criteria,
                'documentation_requirements': tender.documentation_requirements,
            },
            'metadata': {
                'created_at': tender.created_at.isoformat() if tender.created_at else None,
                'organization': current_user.organization.name
            }
        }

        return jsonify(export_data)


    @app.route('/upload-document', methods=['POST'])
    @login_required
    def upload_file():
        # global current_tender_id
        current_tender_id = session.get('current_tender_id')
        
        print("==== UPLOAD ROUTE ACCESSED ====")
        print(f"Request method: {request.method}")
        print(f"Request content type: {request.content_type}")
        print(f"Request files keys: {list(request.files.keys())}")
        print(f"Request form data: {request.form}")
        
        # Check if files were sent - try both 'files[]' and 'file' names
        if 'files[]' in request.files:
            files = request.files.getlist('files[]')
        elif 'file' in request.files:
            files = request.files.getlist('file')
        else:
            print("No files found in request")
            return jsonify({'error': 'No files provided'}), 400

        if not files or files[0].filename == '':
            print("No files selected")
            return jsonify({'error': 'No files selected'}), 400

        # Create tender and process files
        result = services.create_new_tender(current_user.id, current_user.organization_id, files)
        
        if result['success']:
            # Set the newly created tender as current
            # current_tender_id = result['tender_id']
            session['current_tender_id'] = result['tender_id']
            return jsonify({
                'message': f'Processed {len(result["processed_files"])} files successfully',
                'processed': result['processed_files'],
                'errors': result['errors'],
                'redirect': url_for('overview_page')
            })
        else:
            return jsonify({'error': 'No files were processed successfully', 'errors': result['errors']}), 400

    @app.route('/service-product-definition', methods=['GET', 'POST'])
    @login_required
    def service_product_definition():
        """API endpoint for managing service and product definition"""
        if request.method == 'GET':
            # Get the organization's service product definition
            
            definition = ServiceProductDefinition.query.filter_by(
                organization_id=current_user.organization_id
            ).first()
            if definition:
                return jsonify({'definition': definition.definition})
            else:
                return jsonify({'definition': ''})
        
        elif request.method == 'POST':

            data = request.json
            definition_text = data.get('definition', '')
            
            # Check if the organization already has a definition
            existing_definition = ServiceProductDefinition.query.filter_by(
                organization_id=current_user.organization_id
            ).first()
            
            print(definition_text)
            
            if existing_definition:
                # Update existing definition
                existing_definition.definition = definition_text
                existing_definition.updated_at = datetime.datetime.utcnow()
                existing_definition.user_id = current_user.id  # Track who made the update
            else:
                # Create new definition
                new_definition = ServiceProductDefinition(
                    definition=definition_text,
                    user_id=current_user.id,
                    organization_id=current_user.organization_id
                )
                db.session.add(new_definition)
            
            db.session.commit()
            return jsonify({'success': True})

    @app.route('/documents', methods=['GET'])
    @login_required
    def get_documents():
        """Return a list of all uploaded documents for the current tender"""
        current_tender_id = session.get('current_tender_id')

        if not current_tender_id:
            return jsonify([])
        
        tender = Tender.query.get_or_404(current_tender_id)
        
        # Make sure the user belongs to the organization that owns this tender
        if tender.organization_id != current_user.organization_id:
            return jsonify({'error': 'Permission denied'}), 403
            
        documents = Document.query.filter_by(tender_id=current_tender_id).all()
        doc_list = [{"id": doc.id, "filename": doc.original_filename, "is_primary": doc.is_primary} for doc in documents]
        return jsonify(doc_list)

    @app.route('/documents/<int:doc_id>', methods=['DELETE'])
    @login_required
    def delete_document(doc_id):
        """Delete a specific document"""
        document = Document.query.get_or_404(doc_id)
        
        # Get the tender to verify organization ownership
        tender = Tender.query.get_or_404(document.tender_id)
        
        # Verify the document belongs to a tender from the user's organization
        if tender.organization_id != current_user.organization_id:
            return jsonify({'error': 'Permission denied'}), 403
        
        # Delete the file from disk
        try:
            os.remove(document.file_path)
        except OSError:
            pass  # File might not exist, continue anyway
        
        # Delete the document from database
        db.session.delete(document)
        db.session.commit()
        
        return jsonify({'message': 'Document deleted successfully'})

    @app.route('/constraints/api', methods=['GET', 'POST', 'PUT', 'DELETE'])
    @login_required
    def manage_constraints_api():
        """API endpoint for managing constraints"""
        if request.method == 'GET':
            # Get organization's constraints grouped by category
            constraints = {}
            for category in ['financial', 'technical', 'legal', 'other']:
                category_constraints = Constraint.query.filter_by(
                    organization_id=current_user.organization_id, 
                    category=category
                ).all()
                constraints[category] = [constraint.description for constraint in category_constraints]
            return jsonify(constraints)
        
        elif request.method == 'POST':
            data = request.json
            category = data.get('category')
            constraint_text = data.get('constraint')
            
            if not category or not constraint_text:
                return jsonify({'error': 'Category and constraint are required'}), 400
            
            if category not in ['financial', 'technical', 'legal', 'other']:
                return jsonify({'error': f'Invalid category: {category}'}), 400
            
            # Create new constraint
            constraint = Constraint(
                category=category,
                description=constraint_text,
                user_id=current_user.id,
                organization_id=current_user.organization_id
            )
            db.session.add(constraint)
            db.session.commit()
            
            return jsonify({'success': True, 'id': constraint.id})
        
        elif request.method == 'PUT':
            data = request.json
            constraint_id = data.get('id')
            constraint_text = data.get('constraint')
            
            if not constraint_id or not constraint_text:
                return jsonify({'error': 'Constraint ID and text are required'}), 400
            
            constraint = Constraint.query.get_or_404(constraint_id)
            
            # Verify organization ownership
            if constraint.organization_id != current_user.organization_id:
                return jsonify({'error': 'Permission denied'}), 403
            
            constraint.description = constraint_text
            constraint.user_id = current_user.id  # Track who made the update
            db.session.commit()
            
            return jsonify({'success': True})
        
        elif request.method == 'DELETE':
            data = request.json
            constraint_id = data.get('id')
            
            if not constraint_id:
                return jsonify({'error': 'Constraint ID is required'}), 400
            
            constraint = Constraint.query.get_or_404(constraint_id)
            
            # Verify organization ownership
            if constraint.organization_id != current_user.organization_id:
                return jsonify({'error': 'Permission denied'}), 403
            
            db.session.delete(constraint)
            db.session.commit()
            
            return jsonify({'success': True})

    @app.route('/generate-risks', methods=['POST'])
    @login_required
    def generate_risks():
        """Generate risk assessment for the current tender"""
        current_tender_id = session.get('current_tender_id')

        if not current_tender_id:
            return jsonify({'error': 'No active tender'}), 400
        
        tender = Tender.query.get_or_404(current_tender_id)
        
        # Verify organization ownership
        if tender.organization_id != current_user.organization_id:
            return jsonify({'error': 'Permission denied'}), 403
        
        # Generate risk assessment
        result = services.generate_risk_assessment(current_tender_id, current_user.id, current_user.organization_id)
        
        if 'error' in result:
            return jsonify({'error': result['error']}), 500
        
        return jsonify(result)

    @app.route('/generate-bidder-questions', methods=['POST'])
    @login_required
    def generate_bidder_questions():
        """Generate suggested questions for bidders to ask"""
        current_tender_id = session.get('current_tender_id')

        if not current_tender_id:
            return jsonify({'error': 'No active tender'}), 400
        
        tender = Tender.query.get_or_404(current_tender_id)
        
        # Verify organization ownership
        if tender.organization_id != current_user.organization_id:
            return jsonify({'error': 'Permission denied'}), 403
        
        # Generate bidder questions
        result = services.generate_bidder_questions(current_tender_id, current_user.id, current_user.organization_id)
        
        if 'error' in result:
            return jsonify({'error': result['error']}), 500
        
        return jsonify({"questions": result['questions']})

    @app.route('/bidder-questions/get', methods=['GET'])
    @login_required
    def get_bidder_questions():
        """Get existing bidder questions for the current tender"""
        current_tender_id = session.get('current_tender_id')

        if not current_tender_id:
            return jsonify({'error': 'No active tender'}), 400
        
        tender = Tender.query.get_or_404(current_tender_id)
        
        # Verify organization ownership
        if tender.organization_id != current_user.organization_id:
            return jsonify({'error': 'Permission denied'}), 403
        
        # Get the most recent set of bidder questions
        question_set = services.generate_bidder_questions(current_tender_id, current_user.id, current_user.organization_id)
        
        if 'error' in question_set:
            return jsonify({'questions': []})
        
        return jsonify({"questions": question_set['questions']})

    # Fixed route handler for QA interaction

    @app.route('/query', methods=['POST'])
    @login_required
    def ask_question():
        """API endpoint to handle tender Q&A interactions - FIXED"""
        current_tender_id = session.get('current_tender_id')

        if not current_tender_id:
            return jsonify({'error': 'No active tender'}), 400
        
        tender = Tender.query.get_or_404(current_tender_id)
        
        # Verify organization ownership
        if tender.organization_id != current_user.organization_id:
            return jsonify({'error': 'Permission denied'}), 403
        
        # Get question from request
        data = request.json
        question = data.get('query')
        
        if not question:
            return jsonify({'error': 'Question is required'}), 400
        
        # FIXED: Call with correct parameters (tender_id, user_id, organization_id, question)
        result = services.process_qa_interaction(
            current_tender_id, 
            current_user.id, 
            current_user.organization_id, 
            question
        )
        
        if 'error' in result:
            return jsonify({'error': result['error']}), 500
        
        # Include debug info in development
        response_data = {
            'answer': result['answer'],
            'id': result['id']
        }
        
        # Add debug info if available
        if 'debug_info' in result:
            response_data['debug'] = result['debug_info']
        
        return jsonify(response_data)

    @app.route('/tenders/<int:tender_id>', methods=['GET'])
    @login_required
    def switch_tender(tender_id):
        """API endpoint to switch the active tender"""
        # global current_tender_id
        current_tender_id = session.get('current_tender_id')
        
        # Get the requested tender
        tender = Tender.query.get_or_404(tender_id)
        
        # Verify organization ownership
        if tender.organization_id != current_user.organization_id:
            return jsonify({'error': 'Permission denied'}), 403
        
        # Update current tender
        # current_tender_id = tender.id
        session['current_tender_id'] = tender.id

        # Check the current page to determine where to redirect
        current_page = request.headers.get('Referer', '')
        
        # Default to overview page
        redirect_url = url_for('overview_page')
        
        # Check if we're on bidder questions or another specific page
        if 'bidder-questions' in current_page:
            redirect_url = url_for('bidder_questions_page')
        elif 'qa' in current_page:
            redirect_url = url_for('qa_page')
        elif 'risk-assessment' in current_page:
            redirect_url = url_for('risk_assessment_page')
        
        return jsonify({
            'success': True,
            'tender_id': tender.id,
            'tender_title': tender.title,
            'redirect': redirect_url
        })

    @app.route('/tenders', methods=['GET'])
    @login_required
    def get_user_tenders():
        """Get all tenders for the current user's organization"""
        current_tender_id = session.get('current_tender_id')

        tenders = Tender.query.filter_by(
            organization_id=current_user.organization_id
        ).order_by(Tender.created_at.desc()).all()
        
        tender_list = [{
            'id': tender.id,
            'title': tender.title,
            'source': tender.source,
            'created_at': tender.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'is_active': (tender.id == current_tender_id)
        } for tender in tenders]
        
        return jsonify({"tenders": tender_list})

# # GeM Search Config Routes - MODIFIED TO REMOVE STANDALONE PAGES
# from sqlalchemy.orm import joinedload

def init_gem_search_config_routes(app):
    # REMOVED: gem_search_config_page()
    # REMOVED: add_search_config()  
    # REMOVED: edit_search_config()
        
# Add this to your init_gem_search_config_routes function in routes.py

    @app.route('/search-configs', methods=['POST'])
    @login_required
    def create_search_config_api():
        """Create a new search configuration via API"""
        try:
            data = request.json
            
            # Validate required fields
            max_tenders = data.get('max_tenders')
            execution_time = data.get('execution_time')
            
            if not max_tenders or not execution_time:
                return jsonify({'error': 'Max tenders and execution time are required'}), 400
            
            # Validate execution time format (HH:MM)
            import re
            if not re.match(r'^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$', execution_time):
                return jsonify({'error': 'Execution time must be in HH:MM format (24-hour)'}), 400
            
            # Validate max_tenders is a reasonable number
            if not isinstance(max_tenders, int) or max_tenders < 1 or max_tenders > 200:
                return jsonify({'error': 'Max tenders must be between 1 and 200'}), 400
            
            # Create new configuration
            new_config = SearchConfiguration(
                search_keyword=data.get('search_keyword') if data.get('search_keyword') else None,
                max_tenders=max_tenders,
                execution_time=execution_time,
                is_active=data.get('is_active', True),
                created_by=current_user.id
            )
            
            db.session.add(new_config)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'config_id': new_config.id,
                'message': 'Search configuration created successfully'
            })
            
        except Exception as e:
            print(f"Error creating search configuration: {e}")
            db.session.rollback()
            return jsonify({'error': 'Failed to create search configuration'}), 500        
        
    @app.route('/gem-search-config/delete/<int:config_id>', methods=['POST'])
    @login_required
    def delete_search_config(config_id):
        """Delete a search configuration"""
        config = SearchConfiguration.query.get_or_404(config_id)
        
        db.session.delete(config)
        db.session.commit()
        
        flash('Search configuration deleted successfully', 'success')
        return redirect(url_for('organization_page') + '#search-config')  # CHANGED: Always go to org page
    
    @app.route('/gem-search-config/toggle/<int:config_id>', methods=['POST'])
    @login_required
    def toggle_search_config(config_id):
        """Toggle active status of a search configuration"""
        config = SearchConfiguration.query.get_or_404(config_id)
        
        config.is_active = not config.is_active
        db.session.commit()
        
        status = 'activated' if config.is_active else 'deactivated'
        flash(f'Search configuration {status} successfully', 'success')
        return redirect(url_for('organization_page') + '#search-config')  # CHANGED: Always go to org page
    
    # NEW: API route for updating search configs
    @app.route('/search-configs/<int:config_id>', methods=['PUT'])
    @login_required
    def update_search_config_api(config_id):
        """Update a search configuration via API"""
        try:
            config = SearchConfiguration.query.get_or_404(config_id)
            
            # Verify organization ownership
            if config.user.organization_id != current_user.organization_id:
                return jsonify({'error': 'Permission denied'}), 403
            
            data = request.json
            
            # Validate and update fields
            if 'max_tenders' in data:
                max_tenders = data['max_tenders']
                if not isinstance(max_tenders, int) or max_tenders < 1 or max_tenders > 200:
                    return jsonify({'error': 'Max tenders must be between 1 and 200'}), 400
                config.max_tenders = max_tenders
                
            if 'execution_time' in data:
                execution_time = data['execution_time']
                # Validate execution time format (HH:MM)
                import re
                if not re.match(r'^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$', execution_time):
                    return jsonify({'error': 'Execution time must be in HH:MM format (24-hour)'}), 400
                config.execution_time = execution_time
                
            if 'search_keyword' in data:
                config.search_keyword = data['search_keyword'] if data['search_keyword'] else None
                
            if 'is_active' in data:
                config.is_active = data['is_active']
                
            db.session.commit()
            return jsonify({'success': True, 'message': 'Configuration updated successfully'})
            
        except Exception as e:
            print(f"Error updating search configuration: {e}")
            db.session.rollback()
            return jsonify({'error': 'Failed to update search configuration'}), 500
        
def init_notification_api_routes(app):
    """Initialize notification recipient API routes"""
    
    @app.route('/notification-recipients', methods=['POST'])
    @login_required
    def create_notification_recipient():
        """Create a new notification recipient"""
        try:
            data = request.json
            
            # Validate required fields
            name = data.get('name')
            email = data.get('email')
            search_config_id = data.get('search_config_id')
            is_active = data.get('is_active', True)
            
            if not name or not email or not search_config_id:
                return jsonify({'error': 'Name, email, and search configuration ID are required'}), 400
            
            # Verify the search configuration belongs to the user's organization
            search_config = SearchConfiguration.query.get(search_config_id)
            if not search_config:
                return jsonify({'error': 'Search configuration not found'}), 404
            
            # Check if the search config belongs to the user's organization
            if search_config.user.organization_id != current_user.organization_id:
                return jsonify({'error': 'Permission denied'}), 403
            
            # Validate email format (basic validation)
            import re
            email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(email_pattern, email):
                return jsonify({'error': 'Invalid email format'}), 400
            
            # Check if recipient already exists for this configuration
            existing_recipient = NotificationRecipient.query.filter_by(
                email=email,
                search_config_id=search_config_id
            ).first()
            
            if existing_recipient:
                return jsonify({'error': 'This email is already configured for this search'}), 400
            
            # Create new notification recipient
            recipient = NotificationRecipient(
                name=name,
                email=email,
                is_active=is_active,
                search_config_id=search_config_id
            )
            
            db.session.add(recipient)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'recipient_id': recipient.id,
                'message': 'Notification recipient created successfully'
            })
            
        except Exception as e:
            print(f"Error creating notification recipient: {e}")
            db.session.rollback()
            return jsonify({'error': 'Failed to create notification recipient'}), 500
    
    @app.route('/notification-recipients/<int:recipient_id>', methods=['PUT'])
    @login_required
    def update_notification_recipient(recipient_id):
        """Update an existing notification recipient"""
        try:
            recipient = NotificationRecipient.query.get_or_404(recipient_id)
            
            # Verify the recipient belongs to a search config from the user's organization
            if recipient.search_configuration.user.organization_id != current_user.organization_id:
                return jsonify({'error': 'Permission denied'}), 403
            
            data = request.json
            
            # Update fields if provided
            if 'name' in data:
                recipient.name = data['name']
            if 'email' in data:
                email = data['email']
                # Validate email format
                import re
                email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                if not re.match(email_pattern, email):
                    return jsonify({'error': 'Invalid email format'}), 400
                
                # Check if email already exists for this config (excluding current recipient)
                existing_recipient = NotificationRecipient.query.filter(
                    NotificationRecipient.email == email,
                    NotificationRecipient.search_config_id == recipient.search_config_id,
                    NotificationRecipient.id != recipient_id
                ).first()
                
                if existing_recipient:
                    return jsonify({'error': 'This email is already configured for this search'}), 400
                
                recipient.email = email
            
            if 'is_active' in data:
                recipient.is_active = data['is_active']
            
            recipient.updated_at = datetime.datetime.utcnow()
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': 'Notification recipient updated successfully'
            })
            
        except Exception as e:
            print(f"Error updating notification recipient: {e}")
            db.session.rollback()
            return jsonify({'error': 'Failed to update notification recipient'}), 500
    
    @app.route('/notification-recipients/<int:recipient_id>/toggle', methods=['POST'])
    @login_required
    def toggle_notification_recipient(recipient_id):
        """Toggle active status of a notification recipient"""
        try:
            recipient = NotificationRecipient.query.get_or_404(recipient_id)
            
            # Verify the recipient belongs to a search config from the user's organization
            if recipient.search_configuration.user.organization_id != current_user.organization_id:
                return jsonify({'error': 'Permission denied'}), 403
            
            recipient.is_active = not recipient.is_active
            recipient.updated_at = datetime.datetime.utcnow()
            db.session.commit()
            
            status = 'activated' if recipient.is_active else 'deactivated'
            return jsonify({
                'success': True,
                'is_active': recipient.is_active,
                'message': f'Notification recipient {status} successfully'
            })
            
        except Exception as e:
            print(f"Error toggling notification recipient: {e}")
            db.session.rollback()
            return jsonify({'error': 'Failed to toggle notification recipient'}), 500
    
    @app.route('/notification-recipients/<int:recipient_id>', methods=['DELETE'])
    @login_required
    def delete_notification_recipient(recipient_id):
        """Delete a notification recipient"""
        try:
            recipient = NotificationRecipient.query.get_or_404(recipient_id)
            
            # Verify the recipient belongs to a search config from the user's organization
            if recipient.search_configuration.user.organization_id != current_user.organization_id:
                return jsonify({'error': 'Permission denied'}), 403
            
            db.session.delete(recipient)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': 'Notification recipient deleted successfully'
            })
            
        except Exception as e:
            print(f"Error deleting notification recipient: {e}")
            db.session.rollback()
            return jsonify({'error': 'Failed to delete notification recipient'}), 500
        
    @app.route('/brochures')
    @login_required
    def brochures_page():
        return render_template('organization_management.html', 
                              url_prefix=app.config['URL_PREFIX'],
                              organization=current_user.organization)
    
    @app.route('/upload-brochure', methods=['POST'])
    @login_required
    def upload_brochure():        
        print("==== UPLOAD ROUTE ACCESSED ====")
        print(f"Request method: {request.method}")
        print(f"Request content type: {request.content_type}")
        print(f"Request files keys: {list(request.files.keys())}")
        
        # Check if files were sent 
        if 'file' in request.files:
            file = request.files.get('file')
            print(f"[INFO] : {file.filename}")
        else:
            print("No file found in request")
            return jsonify({'error': 'No files provided'}), 400

        if not file or file.filename == '':
            print("No file selected")
            return jsonify({'error': 'No file selected'}), 400
        
        return jsonify({
            'message': 'File received successfully',
            'filename': file.filename,
        }), 200
    
# news_routes.py 

from news import setup_logger, build_scored_rows_one_org, store_news_rows
from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app,
    jsonify,
    render_template_string,
)
import config

# Inline HTML for one news card (NO _news_cards.html)
_CARD_TEMPLATE = """
<div class="col-12 col-md-6 col-lg-4">
  <div class="card h-100 shadow-sm news-card overflow-hidden">

    {% set card_img = n.thumbnail_url or url_for('static', filename='img/news_placeholder.png') %}
    {% if n.news_url %}
      <a href="{{ n.news_url }}" target="_blank" rel="noopener" class="thumb-link thumb-card">
        <img src="{{ card_img }}" class="thumb-img thumb-card-img" alt="News thumbnail">
        <div class="thumb-shade"></div>
      </a>
    {% else %}
      <div class="thumb-link thumb-card">
        <img src="{{ card_img }}" class="thumb-img thumb-card-img" alt="News thumbnail">
        <div class="thumb-shade"></div>
      </div>
    {% endif %}

    <div class="card-body d-flex flex-column">
      <h6 class="card-title-tight mb-2">{{ n.news_title }}</h6>

      <div class="mt-auto d-flex justify-content-between align-items-center">
        {% if n.news_url %}
          <a href="{{ n.news_url }}" target="_blank" rel="noopener" class="btn btn-outline-primary btn-sm">
            Read source
          </a>
        {% else %}
          <span class="text-muted small">No URL</span>
        {% endif %}
      </div>
    </div>
  </div>
</div>
"""


def _build_last_month_feed(org_id: int):
    """
    Build feed for last N days (default 30):
      - pull last N days items (recency order)
      - hero = top 5 recency
      - cards_sorted = remaining sorted by (relevance desc, creation_date desc, news_id desc)
    """
    window_days = getattr(config, "NEWS_WINDOW_DAYS", 30)
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=window_days)

    max_pool = getattr(config, "NEWS_MAX_POOL", 300)  # safety bound

    q = (
        News.query
        .filter(News.organization_id == org_id)
        .filter(News.creation_date >= cutoff)
        .order_by(News.creation_date.desc(), News.news_id.desc())
        .limit(max_pool)
    )

    all_items = q.all()

    hero_count = getattr(config, "NEWS_HERO_COUNT", 5)
    hero_news = all_items[:hero_count]

    remaining = all_items[hero_count:]

    # Sort remaining by relevance desc then recency desc then id desc
    cards_sorted = sorted(
        remaining,
        key=lambda n: (
            (n.relevance_score or 0),
            (n.creation_date or datetime.datetime.min),
            (n.news_id or 0),
        ),
        reverse=True
    )

    return hero_news, cards_sorted, len(all_items)


def init_news_routes(app):

    @app.get("/news")
    @login_required
    def news_page():
        org_id = current_user.organization_id

        hero_news, cards_sorted, total_count = _build_last_month_feed(org_id)

        # Show only first 9 cards initially
        per_page = getattr(config, "NEWS_CARDS_PER_PAGE", 9)
        initial_cards = cards_sorted[:per_page]

        has_more = len(cards_sorted) > len(initial_cards)
        remaining_count = max(0, len(cards_sorted) - len(initial_cards))

        return render_template(
            "news.html",
            hero_news=hero_news,
            other_news=initial_cards,      # ✅ only first 9 cards
            has_more=has_more,             # ✅ button enable
            remaining_count=remaining_count,
            total_count=total_count,
            # pagination state for JS
            next_page=2 if has_more else None,
            per_page=per_page,
            organization=current_user.organization,
            url_prefix=current_app.config.get("URL_PREFIX", ""),
        )

    @app.get("/news/more")
    @login_required
    def news_more():
        """
        Returns NEXT chunk of cards from last N days feed (same logic).
        Page 1 is already rendered in /news (first 9).
        /news/more?page=2 => cards 10-18, etc.
        """
        org_id = current_user.organization_id
        page = request.args.get("page", default=2, type=int)
        per_page = request.args.get("per_page", default=getattr(config, "NEWS_CARDS_PER_PAGE", 9), type=int)

        # Safety
        if page < 2:
            page = 2
        if per_page <= 0 or per_page > 50:
            per_page = 9

        _, cards_sorted, _ = _build_last_month_feed(org_id)

        # Page mapping: page 1 was already shown on /news
        # so page 2 starts from index 9
        start = (page - 1) * per_page
        end = start + per_page
        chunk = cards_sorted[start:end]

        # Render HTML cards
        html = "".join(render_template_string(_CARD_TEMPLATE, n=n) for n in chunk)

        has_next = end < len(cards_sorted)

        return jsonify({
            "ok": True,
            "page": page,
            "per_page": per_page,
            "count": len(chunk),
            "has_next": has_next,
            "next_page": (page + 1) if has_next else None,
            "html": html,
        })

    @app.post("/news/fetch")
    @login_required
    def news_fetch():
        org_id = current_user.organization_id
        model = getattr(config, "NEWS_GEMINI_MODEL", "gemini-2.0-flash")

        try:
            logger = setup_logger()

            rows = build_scored_rows_one_org(
                org_id=org_id,
                model_name=model,
                logger=logger,
            )

            inserted, skipped, reasons = store_news_rows(
                rows=rows,
                organization_id=org_id,
                logger=logger,
            )

            flash(f"News fetched ✅ Inserted: {inserted}, skipped: {skipped}", "success")
        except Exception as e:
            flash(f"Failed to fetch/store news ❌ {e}", "danger")

        return redirect(url_for("news_page"))