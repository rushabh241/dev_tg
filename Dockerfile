# FROM python:3.11-slim

# # Install system dependencies
# RUN apt-get update && apt-get install -y \
#     build-essential \
#     wget \
#     gnupg \
#     unzip \
#     libffi-dev \
#     curl \
#     libcairo2 \
#     libpango-1.0-0 \
#     libpangocairo-1.0-0 \
#     libgdk-pixbuf-2.0-0 \
#     shared-mime-info \
#     fonts-dejavu-core \
#     && apt-get clean \
#     && rm -rf /var/lib/apt/lists/*

# # Install Chrome using the updated method
# RUN wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
#     && apt-get update \
#     && apt-get install -y ./google-chrome-stable_current_amd64.deb \
#     && rm google-chrome-stable_current_amd64.deb \
#     && apt-get clean \
#     && rm -rf /var/lib/apt/lists/*

# # Set working directory
# WORKDIR /app

# # Copy requirements and install dependencies
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

# # Copy everything
# COPY . .

# # Create necessary directories
# RUN mkdir -p uploads gem_bids instance

# # Expose port
# EXPOSE 5000

# # CRITICAL: Set Python environment variables for proper logging
# ENV PYTHONUNBUFFERED=1
# ENV PYTHONDONTWRITEBYTECODE=1
# ENV PYTHONIOENCODING=utf-8

# # Set default environment
# ENV ENVIRONMENT=production

# # Create an improved startup script
# RUN echo '#!/bin/bash\n\
# echo "Container starting with ENVIRONMENT=$ENVIRONMENT"\n\
# echo "Python version: $(python --version)"\n\
# echo "Current working directory: $(pwd)"\n\
# \n\
# if [ "$ENVIRONMENT" = "production" ]; then\n\
#     echo "Starting in PRODUCTION mode with Gunicorn..."\n\
#     # Remove --capture-output to see print statements\n\
#     # Add --access-logfile and --error-logfile for better logging\n\
#     exec gunicorn \\\n\
#         --bind 0.0.0.0:5000 \\\n\
#         --workers 1 \\\n\
#         --timeout 300 \\\n\
#         --log-level debug \\\n\
#         --access-logfile - \\\n\
#         --error-logfile - \\\n\
#         --capture-output \\\n\
#         app:app\n\
# elif [ "$ENVIRONMENT" = "local" ] || [ "$ENVIRONMENT" = "development" ]; then\n\
#     echo "Starting in DEVELOPMENT/LOCAL mode with Flask..."\n\
#     export FLASK_ENV=development\n\
#     export FLASK_DEBUG=1\n\
#     exec python app.py\n\
# else\n\
#     echo "Unknown environment: $ENVIRONMENT, defaulting to development"\n\
#     export FLASK_ENV=development\n\
#     export FLASK_DEBUG=1\n\
#     exec python app.py\n\
# fi' > /app/start.sh && chmod +x /app/start.sh

# # Use the startup script as the entrypoint
# CMD ["/app/start.sh"]


# # FROM python:3.11-slim

# # # Install system dependencies including X11 and VNC
# # RUN apt-get update && apt-get install -y \
# #     build-essential \
# #     wget \
# #     gnupg \
# #     unzip \
# #     libffi-dev \
# #     curl \
# #     libcairo2 \
# #     libpango-1.0-0 \
# #     libpangocairo-1.0-0 \
# #     libgdk-pixbuf-2.0-0 \
# #     shared-mime-info \
# #     fonts-dejavu-core \
# #     fonts-liberation \
# #     libasound2 \
# #     libatk-bridge2.0-0 \
# #     libatk1.0-0 \
# #     libatspi2.0-0 \
# #     libcups2 \
# #     libdbus-1-3 \
# #     libdrm2 \
# #     libgbm1 \
# #     libnspr4 \
# #     libnss3 \
# #     libxcomposite1 \
# #     libxdamage1 \
# #     libxrandr2 \
# #     xdg-utils \
# #     libxshmfence1 \
# #     xvfb \
# #     x11vnc \
# #     fluxbox \
# #     xterm \
# #     && apt-get clean \
# #     && rm -rf /var/lib/apt/lists/*

# # # Install Chrome
# # RUN mkdir -p /etc/apt/keyrings \
# #     && wget -q -O /etc/apt/keyrings/google-chrome.gpg https://dl.google.com/linux/linux_signing_key.pub \
# #     && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
# #     && apt-get update \
# #     && apt-get install -y google-chrome-stable \
# #     && rm -rf /var/lib/apt/lists/*

# # # Set working directory
# # WORKDIR /app

# # # Copy requirements and install dependencies
# # COPY requirements.txt .
# # RUN pip install --no-cache-dir -r requirements.txt

# # # Copy everything
# # COPY . .

# # # Create necessary directories
# # RUN mkdir -p uploads gem_bids instance

# # # Expose ports: Flask on 5000, VNC on 5900
# # EXPOSE 5000 5900

# # # Set environment variables
# # ENV PYTHONUNBUFFERED=1
# # ENV PYTHONDONTWRITEBYTECODE=1
# # ENV PYTHONIOENCODING=utf-8
# # ENV DISPLAY=:99

# # # Create startup script with VNC
# # RUN echo '#!/bin/bash\n\
# # \n\
# # # Start X virtual framebuffer\n\
# # Xvfb :99 -screen 0 1920x1080x24 &\n\
# # sleep 2\n\
# # \n\
# # # Start VNC server\n\
# # x11vnc -display :99 -forever -nopw -quiet &\n\
# # \n\
# # # Start Fluxbox window manager (optional)\n\
# # fluxbox &\n\
# # \n\
# # echo "Container starting with ENVIRONMENT=$ENVIRONMENT"\n\
# # echo "Python version: $(python --version)"\n\
# # echo "Current working directory: $(pwd)"\n\
# # echo "VNC server running on port 5900"\n\
# # echo "To connect: vncviewer <docker-host-ip>:5900"\n\
# # \n\
# # if [ "$ENVIRONMENT" = "production" ]; then\n\
# #     echo "Starting in PRODUCTION mode with Gunicorn..."\n\
# #     exec gunicorn \\\n\
# #         --bind 0.0.0.0:5000 \\\n\
# #         --workers 1 \\\n\
# #         --timeout 300 \\\n\
# #         --log-level debug \\\n\
# #         --access-logfile - \\\n\
# #         --error-logfile - \\\n\
# #         --capture-output \\\n\
# #         app:app\n\
# # elif [ "$ENVIRONMENT" = "local" ] || [ "$ENVIRONMENT" = "development" ]; then\n\
# #     echo "Starting in DEVELOPMENT/LOCAL mode with Flask..."\n\
# #     export FLASK_ENV=development\n\
# #     export FLASK_DEBUG=1\n\
# #     exec python app.py\n\
# # else\n\
# #     echo "Unknown environment: $ENVIRONMENT, defaulting to development"\n\
# #     export FLASK_ENV=development\n\
# #     export FLASK_DEBUG=1\n\
# #     exec python app.py\n\
# # fi' > /app/start.sh && chmod +x /app/start.sh

# # CMD ["/app/start.sh"]


FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    wget \
    gnupg \
    unzip \
    libffi-dev \
    curl \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    shared-mime-info \
    fonts-dejavu-core \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Chrome using the updated method
RUN wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get update \
    && apt-get install -y ./google-chrome-stable_current_amd64.deb \
    && rm google-chrome-stable_current_amd64.deb \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy everything
COPY . .

# Create necessary directories
RUN mkdir -p uploads gem_bids instance

# Expose port
EXPOSE 5000

# CRITICAL: Set Python environment variables for proper logging
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONIOENCODING=utf-8

# Set default environment
ENV ENVIRONMENT=production

# Create an improved startup script
RUN echo '#!/bin/bash\n\
echo "Container starting with ENVIRONMENT=$ENVIRONMENT"\n\
echo "Python version: $(python --version)"\n\
echo "Current working directory: $(pwd)"\n\
\n\
if [ "$ENVIRONMENT" = "production" ]; then\n\
    echo "Starting in PRODUCTION mode with Gunicorn..."\n\
    # Remove --capture-output to see print statements\n\
    # Add --access-logfile and --error-logfile for better logging\n\
    exec gunicorn \\\n\
        --bind 0.0.0.0:5000 \\\n\
        --workers 1 \\\n\
        --timeout 300 \\\n\
        --log-level debug \\\n\
        --access-logfile - \\\n\
        --error-logfile - \\\n\
        --capture-output \\\n\
        app:app\n\
elif [ "$ENVIRONMENT" = "local" ] || [ "$ENVIRONMENT" = "development" ]; then\n\
    echo "Starting in DEVELOPMENT/LOCAL mode with Flask..."\n\
    export FLASK_ENV=development\n\
    export FLASK_DEBUG=1\n\
    exec python app.py\n\
else\n\
    echo "Unknown environment: $ENVIRONMENT, defaulting to development"\n\
    export FLASK_ENV=development\n\
    export FLASK_DEBUG=1\n\
    exec python app.py\n\
fi' > /app/start.sh && chmod +x /app/start.sh

# Use the startup script as the entrypoint
CMD ["/app/start.sh"]