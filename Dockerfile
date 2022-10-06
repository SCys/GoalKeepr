FROM python:3

WORKDIR /app

COPY requirements.txt /requirements.txt

RUN python -m pip install -U pip && \
    pip install -r /requirements.txt

COPY . /app/

CMD ["python", "main.py"]
