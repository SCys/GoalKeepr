FROM python:3-slim-buster AS build
RUN python3 -m venv --copies /venv && /venv/bin/pip install --upgrade pip

FROM build AS build-venv
COPY requirements.txt /requirements.txt
RUN /venv/bin/pip install --disable-pip-version-check -r /requirements.txt

FROM gcr.io/distroless/python3-debian10
WORKDIR /data
COPY --from=build-venv /venv /venv
COPY --from=build-venv /usr/local /usr
COPY . /app/
VOLUME ["/data"]
ENTRYPOINT ["/venv/bin/python"]
CMD ["/app/main.py"]
