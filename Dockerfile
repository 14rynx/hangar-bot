FROM python:3.11-alpine

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src/ .
COPY credentials.json .
RUN mkdir -p data/states
RUN mkdir -p data/reqs

CMD ["python", "./main.py"]