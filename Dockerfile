# Use Python as the base image
FROM python:3.9

# Set noninteractive mode for apt-get
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies including Chrome prerequisites and ffmpeg for pydub
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    unzip \
    gnupg \
    ffmpeg \
    fonts-liberation \
    libappindicator3-1 \
    libasound2 \
    libgbm1 \
    libnspr4 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    xdg-utils \
    libatk-bridge2.0-0 \
    libxkbcommon-x11-0 \
    libgtk-3-0 \
    --no-install-recommends

# Add Google's signing key and repository for Chrome
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - && \
    echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list

# Install Google Chrome
RUN apt-get update && apt-get install -y google-chrome-stable --no-install-recommends

# Debug: Print Chrome version to confirm installation
RUN google-chrome-stable --version

# Create a symbolic link so Selenium can find Chrome.
# Check common locations: /usr/bin/google-chrome-stable and /opt/google/chrome/google-chrome
RUN if [ -f /usr/bin/google-chrome-stable ]; then \
        ln -sf /usr/bin/google-chrome-stable /usr/bin/google-chrome; \
    elif [ -f /opt/google/chrome/google-chrome ]; then \
        ln -sf /opt/google/chrome/google-chrome /usr/bin/google-chrome; \
    else \
        echo "Chrome binary not found" && exit 1; \
    fi

# Debug: List the chrome binary to verify the symlink
RUN ls -l /usr/bin/google-chrome*

# Set environment variable for Chrome binary location (this helps some tools)
ENV CHROME_BIN=/usr/bin/google-chrome

# Set working directory
WORKDIR /app

# Copy all project files into the container
COPY . .

# Upgrade pip and install Python dependencies
RUN pip install --upgrade pip && pip install -r requirements.txt

# Expose the Flask port
EXPOSE 5000

# Start the server using gunicorn
CMD ["gunicorn", "--log-file=-", "--timeout", "360", "-b", "0.0.0.0:5000", "server:app"]

