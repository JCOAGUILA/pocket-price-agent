# Contexto de build: raíz del proyecto (para incluir common/).
FROM python:3.12-slim
WORKDIR /srv
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common ./common
COPY backend/app ./app
EXPOSE 8000
# Sin privilegios de root en tiempo de ejecución.
RUN useradd --create-home --uid 10001 app
USER app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
