FROM python:3.12-slim-bookworm
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG DEBIAN_MIRROR_URL=http://deb.debian.org/debian
ARG DEBIAN_SECURITY_MIRROR_URL=http://deb.debian.org/debian-security
ARG INSTALL_FREECAD=false
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN sed -i \
        -e "s|http://security.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR_URL}|g" \
        -e "s|http://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR_URL}|g" \
        -e "s|http://deb.debian.org/debian|${DEBIAN_MIRROR_URL}|g" \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && if [ "${INSTALL_FREECAD}" = "true" ]; then \
         apt-get install --yes --no-install-recommends libgomp1 freecad; \
       else \
         apt-get install --yes --no-install-recommends libgomp1; \
       fi \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" . \
    && useradd --create-home thermoform \
    && mkdir --parents /data \
    && chown thermoform:thermoform /data
USER thermoform
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
