FROM python:3.11-slim

# Install system dependencies for Selenium / Chromium
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    bash \
    && rm -rf /var/lib/apt/lists/*

# Set runtime environment variables
ENV IS_DOCKER=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Install the local modified amazon-photos library in editable mode
RUN pip install -e .

# Make entrypoint executable
RUN chmod +x /app/docker_sync/docker-entrypoint.sh

ENTRYPOINT ["/app/docker_sync/docker-entrypoint.sh"]
