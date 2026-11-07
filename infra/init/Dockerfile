# Contexto de build: raíz del proyecto (para incluir common/).
FROM python:3.12-slim
WORKDIR /app
COPY infra/init/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common ./common
COPY infra/init/ .
CMD ["python", "-u", "init.py"]
