FROM python:3.12-slim

ARG VCS_REF=unknown
ENV APP_REVISION=${VCS_REF}

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MUSIC_ROOT=/music DATA_ROOT=/data PORT=8787
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && mkdir -p /music /data && chmod 1777 /data
COPY tags.py server.py musicbrainz.py ./
COPY LICENSE LICENSE.md ./
COPY static ./static
USER 1000:1000
EXPOSE 8787
CMD ["python", "server.py"]
