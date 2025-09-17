FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Create and activate virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
RUN pip install --upgrade pip
RUN pip install requests
RUN pip install telethon
RUN pip install pytz

# Set working directory
WORKDIR /app

# Copy application files
COPY . .

# Create required directories
RUN mkdir -p images

# Run the telegram bot
CMD ["python", "j.py"]
