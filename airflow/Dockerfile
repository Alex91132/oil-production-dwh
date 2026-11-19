FROM apache/airflow:3.3.2-python3.12

COPY airflow/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY airflow/dags/ /opt/airflow/dags/
# скрипты нужны DAG-задачам (SCD-загрузчик, профилировщик, контроль качества)
COPY scripts/ /opt/airflow/scripts/
ENV PYTHONPATH=/opt/airflow
