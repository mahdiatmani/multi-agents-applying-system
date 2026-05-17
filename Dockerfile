# Stage 1: Build the React Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Build the Python Backend
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory
WORKDIR /app

# Copy the requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and its system dependencies + VNC tools for UI visibility
RUN playwright install --with-deps chromium \
    && apt-get update \
    && apt-get install -y --no-install-recommends xvfb x11vnc novnc websockify fluxbox xauth \
    && rm -rf /var/lib/apt/lists/*

# Copy the rest of the application
COPY . .

# Copy the built React app from Stage 1
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Make start script executable
RUN chmod +x /app/start.sh

# Expose the FastAPI port and NoVNC port
EXPOSE 8000 6080

CMD ["/app/start.sh"]
