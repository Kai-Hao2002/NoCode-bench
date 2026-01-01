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

    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure environment variables**

    This project uses `python-dotenv`. Copy `.env.example` to `.env` and fill in the necessary settings, like database credentials and Google API keys.

5. **Prepare Docker Environments**

    The agent runs code in isolated Docker containers. You must pull the base images and retag them so the local system can recognize them (e.g., mapping `nocodebench/nocode-bench:django` to `fb_django:dev`).

    * *Option A: Windows (PowerShell)*
        Copy and paste the following script into your PowerShell terminal:


        ```powershell
            $repos = "astropy","django","matplotlib","pylint","pytest","requests","scikit-learn","seaborn","sphinx","xarray"
            foreach ($r in $repos) {
                $remote = "nocodebench/nocode-bench:$r"
                $local = "fb_$($r):dev"
                Write-Host "🔄 Pulling $remote ..."
                docker pull $remote
                Write-Host "🏷️  Tagging as $local ..."
                docker tag $remote $local
            }
            Write-Host "✅ All Docker images prepared!"
            ```

    *  *Option B: macOS / Linux (Bash)*
        Run the following in your terminal:

    ```powershell
            repos=("astropy" "django" "matplotlib" "pylint" "pytest" "requests" "scikit-learn" "seaborn" "sphinx" "xarray")
            for r in "${repos[@]}"; do
                remote="nocodebench/nocode-bench:$r"
                local="fb_$r:dev"
                echo "🔄 Pulling $remote ..."
                docker pull $remote
                echo "🏷️  Tagging as $local ..."
                docker tag $remote $local
            done
            echo "✅ All Docker images prepared!"
            ```

6.  **Start Redis service**

    (We will use Docker to start a Redis instance for the Celery broker.)
    ```bash
    docker run -d -p 6379:6379 --name redis-broker redis
    ```

7.  **Setup the database**

    (Run the Django migrations to create the database tables.)
    ```bash
    python manage.py makemigrations agent_core
    python manage.py migrate
    git clone https://huggingface.co/datasets/NoCode-bench/NoCode-bench_Verified
    python manage.py setup_codebases
    python manage.py load_benchmark_data
    ```

---

## Running the Application

(You will need **three** separate terminals (all with the virtual environment activated) to run the full application.)

### Terminal 1: Run the Django Server

```bash
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

---

## Unit Test

```bash
pytest --cov=agent_core --cov-branch --cov-report=term-missing
```

## Deployment

```bash
freeze > requirements.txt
```

# Qick start
.venv\Scripts\activate.bat

pytest --cov=agent_core --cov-branch --cov-report=term-missing

python manage.py makemigrations agent_core
python manage.py migrate

python manage.py setup_codebases
python manage.py load_benchmark_data

docker run -d -p 6379:6379 --name redis-broker redis
celery -A nocode_project worker --loglevel=info -P gevent --concurrency=1
python manage.py runserver

curl -X POST http://127.0.0.1:8000/api/tasks/start-all/