FROM python:3

WORKDIR /app

RUN apt-get update && apt-get install -y ffmpeg nodejs

COPY . /app/

RUN python -m pip install -U pip && pip install -r /app/requirements.txt

CMD ["sh", "startup.sh"]
