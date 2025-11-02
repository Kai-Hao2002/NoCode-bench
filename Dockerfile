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

# 5. 🚀 優化：僅複製 requirements.txt 並安裝
# (Optimization: Copy ONLY requirements.txt and install)
# (這會利用 Docker 的緩存層)
# (This leverages Docker's cache layer)
COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 6. 複製所有其他內容 (Copy everything else)
COPY . /app/

# 7. 收集靜態文件 (用於 Django Admin)
# (Collect Static Files (for Django Admin))
RUN python manage.py collectstatic --noinput