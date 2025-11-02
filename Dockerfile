# Dockerfile

# 1. 基礎鏡像 (Base Image)
FROM python:3.11-slim

# 2. 設置環境變數 (Set Env Variables)
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 3. 安裝系統依賴 (Install System Dependencies)
# (我們需要 'git' 來運行 setup_workspace)
# (We need 'git' to run setup_workspace)
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# 4. 設置工作目錄 (Set Workdir)
WORKDIR /app
COPY . /app/

# ⬇️ 這些是多餘的 (These are redundant) ⬇️
# COPY ./NoCode-bench_Verified /app/NoCode-bench_Verified
# COPY ./requirements.txt /app/requirements.txt

# ⬇️ 這些是必需的 (These are necessary) ⬇️
RUN pip install --no-cache-dir -r requirements.txt
RUN python manage.py collectstatic --noinput