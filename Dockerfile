FROM python:3

WORKDIR /app

COPY . /app/

RUN python -m pip install -U pip && pip install -r /app/requirements.txt

CMD ["sh", "startup.sh"]
