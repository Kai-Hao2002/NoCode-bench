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
RUN git lfs install

# 4. 🚀 修正 (THE FIX): 
# 設置一個全局的 Git 'user'，這樣 'git commit' 才能工作
# (Set a global Git 'user' so that 'git commit' can work)
RUN git config --global user.email "agent@example.com"
RUN git config --global user.name "AI Agent"

# 5. 設置工作目錄 (Set Workdir)
WORKDIR /app

# 6. 優化：僅複製 requirements.txt 並安裝
# (Optimization: Copy ONLY requirements.txt and install)
COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 7. 複製所有其他內容 (Copy everything else)
COPY . /app/

# 8. 收集靜態文件 (Collect Static Files)
RUN python manage.py collectstatic --noinput