# NoCode-bench
C:\Users\User\AppData\Local\Programs\Python\Python311\python.exe -m venv .venv
.venv\Scripts\Activate.ps1
pip install django djangorestframework celery redis google-genai python-dotenv psycopg2-binary
//python manage.py startapp agent_core


python manage.py makemigrations agent_core
python manage.py migrate

docker run -d -p 6379:6379 --name redis-broker redis
celery -A nocode_project worker -l info -P solo
celery -A nocode_project worker -l info
python manage.py runserver