# Use a slim Python base image
FROM python:3.11-slim

# Install system dependencies, including Tesseract for OCR
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy the requirements file first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies from the requirements file
# A warning about running as root may appear here, which is acceptable during the build stage.
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application files
COPY . .

# Create required directories
RUN mkdir -p images

# Create a non-root user, change ownership of the app directory, and switch to the new user
RUN useradd -ms /bin/bash appuser && chown -R appuser:appuser /app
USER appuser

# Run the telegram bot as the non-root user
CMD ["python", "j.py"]

