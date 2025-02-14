# Use Python as base
FROM python:3.9

# Set the working directory
WORKDIR /app

# Copy project files
COPY . .

# Install dependencies
RUN pip install -r requirements.txt

# Expose the port for Flask
EXPOSE 5000

# Start the server
CMD ["gunicorn", "-b", "0.0.0.0:5000", "server:app"]