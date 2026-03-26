from flask import Flask
from flask_login import LoginManager
from flask_mail import Mail
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash
import os

import logging
import sys

from admin_routes import init_admin_dashboard_routes


# Initialize Flask app
app = Flask(__name__)

log_level = app.config.get('LOG_LEVEL', 'DEBUG').upper()
app.logger.setLevel(getattr(logging, log_level, logging.INFO))

# Optional: quiet down Flask internals
if log_level in ['WARNING', 'ERROR', 'CRITICAL']:
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    
# for logging
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
stream_handler.setFormatter(formatter)

app.logger.addHandler(stream_handler)
app.logger.setLevel(logging.DEBUG)

print("✅ App created", flush=True)
app.logger.info("✅ Logging initialized")

@app.context_processor
def inject_url_prefix():
    return dict(urlPrefix=app.config.get('URL_PREFIX', ''))



# for logging ends

# Import components
from models import db, User, Organization, PrefixMiddleware
from routes import init_auth_routes, init_main_routes, init_api_routes, init_gem_search_config_routes, init_notification_api_routes
import config



# Apply configuration
app.config['SECRET_KEY'] = config.SECRET_KEY
app.config['LOG_LEVEL'] = config.LOG_LEVEL
app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = config.SQLALCHEMY_TRACK_MODIFICATIONS
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH
app.config['ENVIRONMENT'] = config.ENVIRONMENT
app.config['URL_PREFIX'] = config.URL_PREFIX
app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER

print("🌐 URL_PREFIX =", app.config['URL_PREFIX'], flush=True)

# Gemini API configuration
app.config['GEMINI_API_KEY'] = config.GEMINI_API_KEY
app.config['OPENAI_API_KEY'] = config.OPENAI_API_KEY


# Mail configuration
app.config['MAIL_SERVER'] = config.MAIL_SERVER
app.config['MAIL_PORT'] = config.MAIL_PORT
app.config['MAIL_USE_TLS'] = config.MAIL_USE_TLS
app.config['MAIL_USERNAME'] = config.MAIL_USERNAME
app.config['MAIL_PASSWORD'] = config.MAIL_PASSWORD
app.config['MAIL_DEFAULT_SENDER'] = config.MAIL_DEFAULT_SENDER

# Apply ProxyFix to handle the proxy headers
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Apply prefix middleware
app.wsgi_app = PrefixMiddleware(app.wsgi_app)

# Initialize extensions
db.init_app(app)
mail = Mail(app)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Initialize routes
init_auth_routes(app, login_manager, mail)
init_main_routes(app, mail)
init_api_routes(app, mail)
init_gem_search_config_routes(app)
init_notification_api_routes(app)   
init_admin_dashboard_routes(app, mail)

# News route
from routes import init_news_routes
init_news_routes(app)

from pricing_intelligence_routes import init_pricing_intelligence_routes
init_pricing_intelligence_routes(app)

# Create database tables, default organization and default admin user
# with app.app_context():
#     db.create_all()
    
#     # Create default organization if it doesn't exist
#     default_org = Organization.query.filter_by(name='Default Organization').first()
#     if not default_org:
#         default_org = Organization(name='Default Organization', description='Default organization created at system setup')
#         db.session.add(default_org)
#         db.session.flush()  # Get the ID without committing
    
#     # Create default admin user if it doesn't exist
#     admin_user = User.query.filter_by(username='admin').first()
#     if not admin_user:
#         hashed_password = generate_password_hash('secret')
#         admin_user = User(
#             username='admin', 
#             password=hashed_password, 
#             email='admin@example.com',
#             organization_id=default_org.id
#         )
#         db.session.add(admin_user)
#         db.session.commit()

# Run the application
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)