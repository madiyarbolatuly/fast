# Use official Python 3.10 image as base
FROM python:3.10-slim

# Set the working directory inside the container to the "app" folder
WORKDIR /app

# Copy the requirements file from the "app" folder and install dependencies
COPY requirements.txt /app/

# Install system dependencies for AWS Ubuntu
RUN apt-get update && apt-get install -y \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies from requirements.txt
RUN pip install -r requirements.txt

# Copy the entire "app" folder contents to the container
COPY app/ /app/

# Expose port 8080 for the application
EXPOSE 8080

# Command to run FastAPI app using Uvicorn, specify the module path as 'main:app'
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
