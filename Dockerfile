FROM python:3.8

WORKDIR /data

COPY *.py requirements.txt handlers /data/

RUN pip install -r requirements.txt && \
    mkdir data log && \
    touch main.ini

CMD ["python", "main.py"]