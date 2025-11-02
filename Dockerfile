# Dockerfile

# 1. 基礎鏡像 (Base Image)
FROM python:3.11-slim

# 2. 設置環境變數 (Set Env Variables)
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 3. 安裝系統依賴 (Install System Dependencies)
RUN apt-get update && apt-get install -y \
    git \
    git-lfs \
    && rm -rf /var/lib/apt/lists/*
RUN git lfs install # 🚀 確保 lfs 已初始化
                    # (Ensure lfs is initialized)

# 4. 設置工作目錄 (Set Workdir)
WORKDIR /app

# 5. 優化：僅複製 requirements.txt 並安裝
# (Optimization: Copy ONLY requirements.txt and install)
COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 6. 複製所有其他內容 (Copy everything else)
# (這將複製您的 Django 程式碼，但會跳過 .dockerignore 中的 'NoCode-bench_Verified')
# (This copies your Django code, but skips 'NoCode-bench_Verified' from .dockerignore)
COPY . /app/

# 7. 收集靜態文件 (Collect Static Files)
RUN python manage.py collectstatic --noinput