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
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application files
COPY . .

# Create required directories
RUN mkdir -p images

# Run the telegram bot
# Assuming your main script is named 'j.py'
CMD ["python", "j.py"]

