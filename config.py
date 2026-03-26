import os

# Core Flask configuration
SECRET_KEY = 'your_secret_key'
from database_config import SQLALCHEMY_DATABASE_URI
SQLALCHEMY_TRACK_MODIFICATIONS = False
MAX_CONTENT_LENGTH = 100 * 1024 * 1024
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'local')

LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")

# Set URL prefix based on environment
if ENVIRONMENT == 'production':
    URL_PREFIX = '/app'
else:
    URL_PREFIX = ''

# Upload folder configuration
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Mail Configuration
MAIL_SERVER = 'smtp.gmail.com'
MAIL_PORT = 587
MAIL_USE_TLS = True
MAIL_USERNAME = '243rushabh@gmail.com'
MAIL_PASSWORD =  'vxwu qtmc zvxo ytoe' #'itsa ttha cgfz dktr' #'iphs rlsi cwmq kzpw'
MAIL_DEFAULT_SENDER = 'TenderGyan Notifications <243rushabh@gmail.com>' #'TenderGyan Notifications <kkd238226@gmail.com>'

# API Configuration
# GEMINI_API_KEY = "AIzaSyDJBGa3DhbHwRXf8udePtwcm0Dom9CiAXk"
GEMINI_API_KEY = ""
OPENAI_API_KEY = "sk-xxxxx"
