FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt
COPY . .
RUN DJANGO_DEBUG=1 python manage.py collectstatic --noinput \
 && useradd --create-home app && chown -R app /app
USER app
EXPOSE 8000
# migrate chalake server start. Workers: apne CPU ke hisaab se badhao.
CMD ["sh", "-c", "python manage.py migrate --noinput && uvicorn seochecker.asgi:application --host 0.0.0.0 --port 8000 --workers 2 --proxy-headers"]
