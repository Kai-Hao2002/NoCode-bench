# Dockerfile

# 1. Base Image
FROM python:3.11-slim

# 2. Set Env Variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 3. Install System Dependencies
RUN apt-get update && apt-get install -y \
    git \
    git-lfs \
    && rm -rf /var/lib/apt/lists/*
RUN git lfs install

# 4. Set a global Git 'user' so that 'git commit' can work
RUN git config --global user.email "agent@example.com"
RUN git config --global user.name "AI Agent"

# 5. Set Workdir
WORKDIR /app

# 6. Optimization: Only copy requirements.txt and install
COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 7. Copy everything else
COPY . /app/

# 8. Collect Static Files
RUN python manage.py collectstatic --noinput