FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY .streamlit ./.streamlit
COPY app.py ui.py estilos.css favicon.png ./
EXPOSE 8501
# Sin privilegios de root en tiempo de ejecución.
RUN useradd --create-home --uid 10001 app
USER app
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
