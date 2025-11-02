C:\Users\User\AppData\Local\Programs\Python\Python311\python.exe -m venv .venv
.venv\Scripts\activate.bat
pip install django djangorestframework celery redis google-genai python-dotenv psycopg2-binary pytest google-generativeai unidiff gevent
//python manage.py startapp agent_core


python manage.py makemigrations agent_core
python manage.py migrate

docker run -d -p 6379:6379 --name redis-broker redis
celery -A nocode_project worker -l info -P solo
celery -A nocode_project worker -l info
celery -A nocode_project worker --loglevel=info -P gevent --concurrency=1
python manage.py runserver

python manage.py setup_codebases
python manage.py load_benchmark_data

curl -X POST http://127.0.0.1:8000/api/tasks/start-all/

# NoCode-bench

Build and evaluate an agent/system that reads a documentation change and implements the
corresponding code changes so that project tests pass.

##  Technology Stack

* **Backend:** Django, Django Rest Framework
* **Database:** PostgreSQL (via `psycopg2-binary`)
* **Async Tasks:** Celery
* **Message Broker:** Redis
* **AI:** Google Gemini (via `google-genai`, `google-generativeai`)
* **Testing:** Pytest

---

## Prerequisites

(Before you begin, ensure you have the following tools installed on your system:)

* **Python 3.11** (or the version specified in your command)
* **Docker Desktop** ( for running Redis)
* **Git** (for cloning the repository)

---

## Installation & Setup

1.  **Clone the repository**
    ```bash
    git clone [https://github.com/Kai-Hao2002/NoCode-bench.git]
    cd NoCode-bench
    ```

2.  **Create and activate Python virtual environment**

    * *Windows:*
        ```bash
        # (Using 'python -m venv .venv' is recommended to use the system default Python)
        python -m venv .venv
        .venv\Scripts\activate.bat
        ```
    * *macOS / Linux:*
        ```bash
        python3 -m venv .venv
        source .venv/bin/activate
        ```

3.  **Install dependencies**

    > **推薦 (Recommended):** 您的 `pip install ...` 命令很長。最佳實踐是將它們放入一個 `requirements.txt` 檔案中。
    > (Your `pip install ...` command is long. It is a best practice to put these into a `requirements.txt` file.)

    (If you have a `requirements.txt` file:)
    ```bash
    pip install -r requirements.txt
    ```

    (If not, run your original command to install:)
    ```bash
    pip install django djangorestframework celery redis google-genai python-dotenv psycopg2-binary pytest google-generativeai
    ```

4.  **Configure environment variables**
    此專案使用 `python-dotenv`。請複製 `.env.example`（如果有的話）並將其命名為 `.env`，然後填入必要的設定（例如資料庫憑證、Google API 金鑰）。
    (This project uses `python-dotenv`. Copy `.env.example` (if it exists) to `.env` and fill in the necessary settings, like database credentials and Google API keys.)

5.  **Start Redis service**

    (We will use Docker to start a Redis instance for the Celery broker.)
    ```bash
    docker run -d -p 6379:6379 --name redis-broker redis
    ```

6.  **Setup the database**

    (Run the Django migrations to create the database tables.)
    ```bash
    python manage.py makemigrations agent_core
    python manage.py migrate
    ```

---

## Running the Application

(You will need **three** separate terminals (all with the virtual environment activated) to run the full application.)

### Terminal 1: Run the Django Server

```bash
python manage.py setup_codebases
python manage.py load_benchmark_data
python manage.py runserver
```
### Terminal 2: Run the Redis service

```bash
celery -A nocode_project worker --loglevel=info -P gevent --concurrency=1
```

### Terminal 3: Run the Request for all tasks

```bash
curl -X POST http://127.0.0.1:8000/api/tasks/start-all/
```