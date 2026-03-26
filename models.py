from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
import datetime

try:
    from sqlalchemy.dialects.postgresql import JSONB
except Exception:
    JSONB = None

# Initialize database
db = SQLAlchemy()

class PrefixMiddleware:
    def __init__(self, app, prefix=''):
        self.app = app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        script_name = environ.get('HTTP_X_SCRIPT_NAME', '')
        if script_name:
            environ['SCRIPT_NAME'] = script_name
            path_info = environ['PATH_INFO']
            if path_info.startswith(script_name):
                environ['PATH_INFO'] = path_info[len(script_name):]
        return self.app(environ, start_response)


class Organization(db.Model):
    """Organization model for grouping users"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    # Relationships
    users = db.relationship('User', backref='organization', lazy=True)
    constraints = db.relationship('Constraint', backref='organization', lazy=True)
    service_product_definitions = db.relationship('ServiceProductDefinition', backref='organization', lazy=True)
    
    def __repr__(self):
        return f'<Organization {self.name}>'


class User(db.Model, UserMixin):
    """User model for authentication and tracking activities"""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.Text, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    role = db.Column(db.String(20), nullable=False, default='user')
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    
    # Relationships
    tenders = db.relationship('Tender', backref='user', lazy=True)
    
    def get_id(self):
        """Override the default get_id method to return the username"""
        return self.username
    
    def __repr__(self):
        return f'<User {self.username}>'


class Tender(db.Model):
    """Model for tender documents and metadata"""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.Text, nullable=False, default="Untitled Tender")
    description = db.Column(db.Text, nullable=True)
    
    # Existing fields
    due_date = db.Column(db.Text, nullable=True)
    bid_opening_date = db.Column(db.Text, nullable=True)
    bid_offer_validity = db.Column(db.Text, nullable=True)
    emd_amount = db.Column(db.Text, nullable=True)
    estimated_cost = db.Column(db.Text, nullable=True)
    question_deadline = db.Column(db.Text, nullable=True)
    qualification_criteria = db.Column(db.Text, nullable=True)
    reverse_auction = db.Column(db.Text, nullable=True)
    rejection_criteria = db.Column(db.Text, nullable=True)
    msme_preferences = db.Column(db.Text, nullable=True)
    border_country_clause = db.Column(db.Text, nullable=True)

    # NEW FIELDS - Basic Information
    tender_number = db.Column(db.Text, nullable=True)
    tender_reference_number = db.Column(db.Text, nullable=True)
    organization_details = db.Column(db.Text, nullable=True)
    
    # NEW FIELDS - Financial Requirements  
    performance_security = db.Column(db.Text, nullable=True)
    payment_terms = db.Column(db.Text, nullable=True)
    
    # NEW FIELDS - Technical Requirements
    technical_specifications = db.Column(db.Text, nullable=True)
    scope_of_work = db.Column(db.Text, nullable=True)
    performance_standards = db.Column(db.Text, nullable=True)
    
    # NEW FIELDS - Evaluation
    evaluation_criteria = db.Column(db.Text, nullable=True)
    
    # NEW FIELDS - Compliance
    documentation_requirements = db.Column(db.Text, nullable=True)
    
    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)

    # NEW FIELDS - Additional Information
    additional_details = db.Column(db.Text, nullable=True)

    # Source of the tender (e.g., 'CPPP', 'GeM', 'Maha-Tender', etc.)
    source = db.Column(db.Text, nullable=True)
    
    # Relationships
    documents = db.relationship('Document', backref='tender', lazy=True, cascade="all, delete-orphan")
    risk_assessments = db.relationship('RiskAssessment', backref='tender', lazy=True, cascade="all, delete-orphan")
    qa_interactions = db.relationship('QAInteraction', backref='tender', lazy=True, cascade="all, delete-orphan")
    products = db.relationship('Product', backref='tender', lazy=True, cascade="all, delete-orphan")

    
    def __repr__(self):
        return f'<Tender {self.title}>'


class BidderQuestionsSet(db.Model):
    """Model for storing generated bidder questions"""
    id = db.Column(db.Integer, primary_key=True)
    generated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    tender_id = db.Column(db.Integer, db.ForeignKey('tender.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Relationships
    questions = db.relationship('BidderQuestion', backref='question_set', lazy=True, cascade="all, delete-orphan")
    
    def __repr__(self):
        return f'<BidderQuestionsSet for Tender {self.tender_id}>'


class BidderQuestion(db.Model):
    """Model for individual bidder questions"""
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.Text, nullable=False)
    explanation = db.Column(db.Text, nullable=True)
    category = db.Column(db.Text, nullable=True)
    section_reference = db.Column(db.Text, nullable=True)
    question_set_id = db.Column(db.Integer, db.ForeignKey('bidder_questions_set.id'), nullable=False)
    
    def __repr__(self):
        return f'<BidderQuestion {self.question[:20]}...>'
        

class Document(db.Model):
    """Model for individual documents within a tender"""
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.Text, nullable=False)
    original_filename = db.Column(db.Text, nullable=False)
    file_path = db.Column(db.Text, nullable=False)
    file_type = db.Column(db.Text, nullable=False)
    file_size = db.Column(db.Integer, nullable=False)  # Size in bytes
    content_text = db.Column(db.Text, nullable=True)  # Extracted text content
    is_primary = db.Column(db.Boolean, default=False)  # Is this the main tender document
    uploaded_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    tender_id = db.Column(db.Integer, db.ForeignKey('tender.id'), nullable=False)
    
    def __repr__(self):
        return f'<Document {self.original_filename}>'


class Constraint(db.Model):
    """Model for organizational constraints"""
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.Text, nullable=False)  # financial, technical, legal, other
    description = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    
    def __repr__(self):
        return f'<Constraint {self.category}: {self.description[:20]}...>'


class ServiceProductDefinition(db.Model):
    """Model for organization's definition of services and products"""
    id = db.Column(db.Integer, primary_key=True)
    definition = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    
    def __repr__(self):
        return f'<ServiceProductDefinition for Organization {self.organization_id}>'


class RiskAssessment(db.Model):
    """Model for risk assessments of tenders"""
    id = db.Column(db.Integer, primary_key=True)
    generated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    tender_id = db.Column(db.Integer, db.ForeignKey('tender.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Relationships
    risks = db.relationship('Risk', backref='assessment', lazy=True, cascade="all, delete-orphan")
    
    # Summary counts
    total_risks = db.Column(db.Integer, default=0)
    high_risks = db.Column(db.Integer, default=0)
    medium_risks = db.Column(db.Integer, default=0)
    low_risks = db.Column(db.Integer, default=0)
    
    def __repr__(self):
        return f'<RiskAssessment for Tender {self.tender_id}>'
        
class GemTender(db.Model):
    """Model for gem_tenders table - GeM tenders downloaded and analyzed by gem_nlp_api.py"""
    __tablename__ = 'gem_tenders'   # This matches your existing table name exactly
    id = db.Column(db.Integer, primary_key=True)
    tender_id = db.Column(db.Text, nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    search_config_id = db.Column(db.Integer, nullable=True, index=True)
    description = db.Column(db.Text, nullable=True)
    due_date = db.Column(db.Text, nullable=True)
    creation_date = db.Column(db.Text, nullable=True)  # String format as used in gem_nlp_api.py
    matches_services = db.Column(db.Boolean, default=False)
    match_reason = db.Column(db.Text, nullable=True)
    document_url = db.Column(db.Text, nullable=True)
    pdf_path = db.Column(db.Text, nullable=True)
    
    # Additional columns from gem_nlp_api.py save_to_db function
    match_score = db.Column(db.Float, default=0.0)
    keywords = db.Column(db.Text, nullable=True)  # Pipe-separated keywords
    match_score_keyword = db.Column(db.Float, default=0.0)
    match_score_combined = db.Column(db.Float, default=0.0)
    api_calls_made = db.Column(db.Integer, default=0)
    tokens_used = db.Column(db.Integer, default=0)
    relevance_percentage = db.Column(db.Float, default=0.0)
    is_central_match = db.Column(db.Boolean, default=False)
    strategic_fit = db.Column(db.Boolean, default=False)
    primary_scope = db.Column(db.Text, nullable=True)
    
    # Establish relationship with Organization
    organization = db.relationship('Organization', backref=db.backref('gem_tenders', lazy=True))
    
    # Composite unique constraint for tender_id + organization_id
    __table_args__ = (db.UniqueConstraint('tender_id', 'organization_id', name='_tender_org_uc'),)
    
    def __repr__(self):
        return f'<GemTenders {self.tender_id} for Organization {self.organization_id}>'
    
class Risk(db.Model):
    """Model for individual risks identified in a risk assessment"""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.Text, nullable=False)  # financial, technical, legal, other
    severity = db.Column(db.Text, nullable=False)  # high, medium, low
    impact = db.Column(db.Text, nullable=True)
    mitigation = db.Column(db.Text, nullable=True)
    related_constraint = db.Column(db.Text, nullable=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey('risk_assessment.id'), nullable=False)
    
    def __repr__(self):
        return f'<Risk {self.title}>'


class QAInteraction(db.Model):
    """Model for tracking Q&A interactions"""
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    tender_id = db.Column(db.Integer, db.ForeignKey('tender.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    def __repr__(self):
        return f'<QA {self.question[:20]}...>'
        
class SearchConfiguration(db.Model):
    """Model for storing GeM tender search configurations"""
    __tablename__ = 'gem_search_configurations'
    id = db.Column(db.Integer, primary_key=True)
    search_keyword = db.Column(db.Text, nullable=True)  # Can be null for all tenders
    max_tenders = db.Column(db.Integer, default=30)
    execution_time = db.Column(db.Text, nullable=False)  # Format: "HH:MM" in 24-hour format
    is_active = db.Column(db.Boolean, default=True)
    last_run = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # User who created this configuration
    user = db.relationship('User', backref=db.backref('search_configurations', lazy=True))
    # Notification recipients
    notification_recipients = db.relationship('NotificationRecipient', backref='search_configuration', lazy=True, cascade="all, delete-orphan")
    
    def __repr__(self):
        return f'<SearchConfiguration ID: {self.id}, Keyword: {self.search_keyword}, Time: {self.execution_time}>'


class NotificationRecipient(db.Model):
    """Model for storing email notification recipients for GeM search configurations"""
    __tablename__ = 'notification_recipients'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False)
    email = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    search_config_id = db.Column(db.Integer, db.ForeignKey('gem_search_configurations.id'), nullable=False)
    
    def __repr__(self):
        return f'<NotificationRecipient {self.name} <{self.email}>>'
    

class Product(db.Model):
    """Products or items listed under an analyzed Tender"""
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    tender_id = db.Column(db.Integer, db.ForeignKey('tender.id'), nullable=False)

    product_name = db.Column(db.Text, nullable=False)
    quantity = db.Column(db.Text, nullable=True)
    delivery_days = db.Column(db.Text, nullable=True)
    consignee_name = db.Column(db.Text, nullable=True)
    delivery_address = db.Column(db.Text, nullable=True)
    specification_link = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<Product {self.product_name} ({self.quantity})>"
    
class Admin(db.Model, UserMixin):
    """Model for admin"""
    __tablename__ = 'admin'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.Text, unique=True, nullable=False)
    password = db.Column(db.Text, nullable=False)
    last_login = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f"<Admin {self.email}>"
    
# class Subscription(db.Model):
#     __tablename__ = 'subscriptions'

#     id = db.Column(db.Integer, primary_key=True)

#     # Organization
#     organization_id = db.Column(db.Integer,db.ForeignKey('organization.id'),nullable=False)
#     organization = db.relationship('Organization',backref=db.backref('subscriptions', lazy=True))

#     # Plan info
#     plan_name = db.Column(db.String(255), nullable=False)

#     # Billing details
#     months = db.Column(db.Integer)
#     monthly_price = db.Column(db.Numeric(12, 2))

#     # USERS
#     max_users = db.Column(db.Integer)

#     # GEM FEATURES
#     gem_searches_per_day = db.Column(db.Integer)
#     gem_industries_allowed = db.Column(db.Integer)

#     # TENDERS
#     tenders_per_month = db.Column(db.Integer)

#     # OTHER FEATURES
#     external_tenders = db.Column(db.Boolean, default=False)
#     risk_assessment = db.Column(db.Boolean, default=True)

#     # STATUS
#     status = db.Column(db.String(50), nullable=False, default='active')
#     start_date = db.Column(db.Date, nullable=False)
#     end_date = db.Column(db.Date)

#     # TIMESTAMPS
#     created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
#     updated_at = db.Column(db.DateTime,default=datetime.datetime.utcnow,onupdate=datetime.datetime.utcnow)

#     def __repr__(self):
#         return f"<Subscription org={self.organization_id}, plan='{self.plan_name}'>"

class Plan(db.Model):
    __tablename__ = 'plans'

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(255), nullable=False)

    billing_months = db.Column(db.Integer)
    price_per_month = db.Column(db.Numeric(12, 2))

    max_users = db.Column(db.Integer)
    gem_searches_per_day = db.Column(db.Integer)
    gem_industries_allowed = db.Column(db.Integer)
    tenders_per_month = db.Column(db.Integer)
    external_tenders = db.Column(db.Boolean, default=False)
    risk_assessment = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f"<Plan {self.name}>"
    
# class Subscription(db.Model):
#     __tablename__ = 'subscriptions'

#     id = db.Column(db.Integer, primary_key=True)
#     organization_id = db.Column(db.Integer,db.ForeignKey('organization.id'),nullable=False)
#     plan_id = db.Column(db.Integer,db.ForeignKey('plans.id'),nullable=False)
    
#     plan_name = db.Column(db.String(255), nullable=False)
#     months = db.Column(db.Integer)
#     subscription_cost = db.Column(db.Numeric(12, 2))

#     status = db.Column(db.String(50), nullable=False, default='active')
#     start_date = db.Column(db.Date, nullable=False)
#     end_date = db.Column(db.Date)

#     created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
#     updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

#     def __repr__(self):
#         return f"<Subscription {self.plan_name}>"
    
# class SubscriptionLimit(db.Model):
#     __tablename__ = 'subscription_limits'

#     id = db.Column(db.Integer, primary_key=True)
#     subscription_id = db.Column(db.Integer,db.ForeignKey('subscriptions.id'),nullable=False)

#     max_users = db.Column(db.Integer)

#     gem_searches_per_day = db.Column(db.Integer)
#     gem_industries_allowed = db.Column(db.Integer)

#     tenders_per_month = db.Column(db.Integer)
#     external_tenders = db.Column(db.Boolean, default=True)
#     risk_assessment = db.Column(db.Boolean, default=True)
    
#     created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
#     updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

#     def __repr__(self):
#         return f"<Subscription Limit {self.subscription_id}>"
    
class DataPurgeSummary(db.Model):
    __tablename__ = "data_purge_summary"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True) 
    run_id = db.Column(db.Integer, nullable=False)   
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey('organization.id'),
        nullable=False
    )

    files_archived = db.Column(db.Integer, nullable=False, default=0)
    records_deleted = db.Column(db.Integer, nullable=False, default=0)
    executed_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    status = db.Column(db.String(20), nullable=False)  # success / failure


# News Table
class News(db.Model):
    __tablename__ = "news_table"

    news_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    news_title = db.Column(db.Text, nullable=False)
    
    news_url = db.Column(db.Text, nullable=True)

    creation_date = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    relevance_score = db.Column(db.Integer, nullable=False, default=0)

   
    thumbnail_url = db.Column(db.Text, nullable=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organization.id"))

    __table_args__ = (
        db.Index("ix_news_creation_date", "creation_date"),
        db.Index("ix_news_relevance", "relevance_score"),
    )

# Configuration Refoctoring - GeM Tender Master and Match Tables

class GemTenderMaster(db.Model):
    __tablename__ = "gem_tender_master"

    id = db.Column(db.Integer, primary_key=True)
    tender_id = db.Column(db.Text, unique=True, nullable=False)

    description = db.Column(db.Text)
    due_date = db.Column(db.Text)
    creation_date = db.Column(db.Text)

    document_url = db.Column(db.Text)
    pdf_path = db.Column(db.Text)



class GemTenderMatch(db.Model):
    __tablename__ = "gem_tender_matches"

    id = db.Column(db.Integer, primary_key=True)

    organization_id = db.Column(
        db.Integer,
        db.ForeignKey('organization.id'),
        nullable=False
    )

    master_tender_id = db.Column(
        db.Integer,
        db.ForeignKey('gem_tender_master.id'),
        nullable=False
    )

    # Matching Data
    matches_services = db.Column(db.Boolean, default=False)
    match_reason = db.Column(db.Text)

    match_score = db.Column(db.Float, default=0.0)
    match_score_keyword = db.Column(db.Float, default=0.0)
    match_score_combined = db.Column(db.Float, default=0.0)

    relevance_percentage = db.Column(db.Float, default=0.0)
    strategic_fit = db.Column(db.Boolean, default=False)
    is_central_match = db.Column(db.Boolean, default=False)
    primary_scope = db.Column(db.Text)

    api_calls_made = db.Column(db.Integer, default=0)
    tokens_used = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('organization_id', 'master_tender_id'),
    )


class GemOrgSearchCapability(db.Model):
    __tablename__ = "gem_org_search_capabilities"

    id = db.Column(db.Integer, primary_key=True)

    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organization.id"),
        nullable=False
    )

    search_config_id = db.Column(
        db.Integer,
        db.ForeignKey("gem_search_configurations.id"),
        nullable=False
    )

    # Capability keyword (org-specific)
    keyword = db.Column(db.Text, nullable=False)

    created_at = db.Column(
        db.DateTime,
        default=datetime.datetime.utcnow,
        nullable=False
    )

    # Prevent duplicate keyword per org per config
    __table_args__ = (
        db.UniqueConstraint(
            "organization_id",
            "search_config_id",
            "keyword",
            name="uq_org_config_keyword"
        ),
    )

    # Relationships
    organization = db.relationship(
        "Organization",
        backref=db.backref(
            "search_capabilities",
            lazy=True,
            cascade="all, delete-orphan"
        )
    )

    search_config = db.relationship(
        "SearchConfiguration",
        backref=db.backref(
            "org_capabilities",
            lazy=True,
            cascade="all, delete-orphan"
        )
    )

    def __repr__(self):
        return (
            f"<GemOrgSearchCapability "
            f"org={self.organization_id}, "
            f"config={self.search_config_id}, "
            f"keyword='{self.keyword}'>"
        )

# To control menu items and tabs visibility based on organization-level settings
class FeatureAccessControl(db.Model):
    __tablename__ = 'feature_access_control'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    organization_id = db.Column(db.Integer, nullable=False)
    menu_item = db.Column(db.String(100), nullable=False)  # Feature name
    access = db.Column(db.Boolean, default=False, nullable=False)
    
    # Create a composite unique constraint
    __table_args__ = (
        db.UniqueConstraint('organization_id', 'menu_item', name='unique_org_feature'),
    )

    def __repr__(self):
        return f"<FeatureAccessControl org_id={self.organization_id} menu_item={self.menu_item} access={self.access}>"

class GemBidDetails(db.Model):
    __tablename__ = "gem_bid_details"

    id = db.Column(db.Integer, primary_key=True)  # primary key
    bid_id = db.Column(db.Integer)
    bid_number = db.Column(db.Text)
    category = db.Column(db.Text)
    ministry = db.Column(db.Text)
    department = db.Column(db.Text)
    organisation = db.Column(db.Text)
    buyer_name = db.Column(db.Text)
    buyer_location = db.Column(db.Text)
    bid_status = db.Column(db.Text)
    quantity_total = db.Column(db.Float)

    bid_start_datetime = db.Column(db.DateTime)
    bid_end_datetime = db.Column(db.DateTime)
    bid_open_datetime = db.Column(db.DateTime)

    bid_validity_days = db.Column(db.Text)

    def __repr__(self):
        return f"<GemBidDetails {self.bid_number}>"


class GemFinancialDetails(db.Model):
    __tablename__ = "gem_financial_details"

    id = db.Column(db.Integer, primary_key=True)  # primary key
    bid_id = db.Column(db.Integer)
    bid_number = db.Column(db.Text)
    seller_name = db.Column(db.Text)
    offered_item = db.Column(db.Text)
    total_price = db.Column(db.Text)
    rank = db.Column(db.Text)

    def __repr__(self):
        return f"<GemFinancialDetails {self.bid_number} - {self.seller_name}>"

class GemLogRunMetrics(db.Model):
    __tablename__ = "log_metrics"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    org_id = db.Column(db.Integer, nullable=True)
    keywords_used = db.Column(db.Text, nullable=True)

    run_started_at = db.Column(db.DateTime, nullable=True)
    run_finished_at = db.Column(db.DateTime, nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=True)

    matched_tenders = db.Column(db.Integer, nullable=True)
    tenders_analyzed_with_api = db.Column(db.Integer, nullable=True)
    tenders_filtered_out = db.Column(db.Integer, nullable=True)

    api_calls = db.Column(db.Integer, nullable=True)
    tokens_used = db.Column(db.BigInteger, nullable=True)

    email_status = db.Column(db.Text, nullable=True)              # SENT / NO_EMAIL_NEEDED / FAILED / NONE
    email_note = db.Column(db.Text, nullable=True)                # user-friendly note
    email_recipients_count = db.Column(db.Integer, nullable=True)
    email_tenders_count = db.Column(db.Integer, nullable=True)

    memory_usage_mb = db.Column(db.Numeric(10, 2), nullable=True)
    chrome_closed = db.Column(db.Boolean, nullable=False, default=False)

    status = db.Column(db.Text, nullable=False, default="INCOMPLETE")  # SUCCESS / FAILED / INCOMPLETE
    error_messages = db.Column(db.Text, nullable=True)

    flag_status = db.Column(db.Text, nullable=False, default="GREEN")  # GREEN / RED / YELLOW
    flag_note = db.Column(db.Text, nullable=True)
    flag_acknowledged_at = db.Column(db.DateTime, nullable=True)

    log_file = db.Column(db.Text, nullable=False, default="gem_tenders.log")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)

    __table_args__ = (
        db.Index("ix_gem_log_run_metrics_v2_org_time", "org_id", "run_finished_at"),
    )


class GemLogIngestState(db.Model):
    __tablename__ = "gem_log_ingest_state"

    log_file = db.Column(db.Text, primary_key=True)
    byte_offset = db.Column(db.BigInteger, nullable=False, default=0)
    partial_run = db.Column(JSONB if JSONB is not None else db.JSON, nullable=True)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )