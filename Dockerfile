FROM python:3.10-slim

# Set the working directory inside the container
WORKDIR /app

# Install necessary dependencies
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    unzip \
    gnupg \
    libx11-dev \
    libxext6 \
    libxrender1 \
    libgtk-3-0 \
    libgbm-dev \
    libnspr4-dev \
    libnss3-dev \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libgdk-pixbuf2.0-0 \
    libgdk-pixbuf2.0-dev \
    libxcomposite1 \
    libxdamage1 \
    libfontconfig1 \
    libappindicator3-1 \
    fonts-liberation \
    libasound2 \
    xdg-utils \
    chromium \
    chromium-driver \
    libxss1 \
    libnss3 \
    libcups2 \
    libxrandr2 \
    && apt-get clean

# Download and install Google Chrome (since Chromium might not be sufficient for all use cases)
RUN wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    dpkg -i google-chrome-stable_current_amd64.deb || apt-get -f install -y

RUN apt-get install -y chromium chromium-driver

# Install pip requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code to the container
COPY app/ /app/

# Set environment variables for headless Chrome and specify the path to the Chrome binary and driver
ENV CHROME_BIN=/usr/bin/google-chrome-stable
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# Expose port 8080 for the FastAPI application
EXPOSE 8080

# Run the FastAPI app with Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
