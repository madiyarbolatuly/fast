# Use a base image that supports installing Chrome (e.g., python:3.9-slim)
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .

# Install dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    libgconf-2-4 \
    libnss3 \
    libxss1 \
    libappindicator1 \
    libayatana-appindicator3-1 \
    fonts-liberation \
    libasound2

# Add the Google signing key and repository
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list'

# Install Google Chrome Stable
RUN apt-get update && apt-get install -y google-chrome-stable

# Verify Chrome installation (optional)
RUN google-chrome-stable --version

# Install chromedriver
RUN wget -O /tmp/chromedriver.zip https://storage.googleapis.com/chrome-for-testing-public/133.0.6943.98/linux64/chromedriver-linux64.zip \
    && unzip /tmp/chromedriver.zip -d /usr/bin/ \
    && mv /usr/bin/chromedriver-linux64/chromedriver /usr/bin/chromedriver \
    && chmod +x /usr/bin/chromedriver \
    && rm -rf /usr/bin/chromedriver-linux64 /tmp/chromedriver.zip

# Install the dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Set the command to run your application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
