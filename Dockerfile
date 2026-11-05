FROM python:3.13-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    PORT=8088
WORKDIR /opt/image-packager
RUN addgroup -g 10001 app && adduser -D -u 10001 -G app app \
    && mkdir /data && chown app:app /data && chmod 700 /data
COPY server.py ./
COPY design/index.html design/login.html design/setup.html design/account.html \
     design/studio.css design/auth.css design/studio.js design/auth.js \
     design/auth-client.js design/session.js design/account.js ./design/
USER 10001:10001
EXPOSE 8088
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8088')+'/healthz',timeout=3).read()"
ENTRYPOINT ["python", "/opt/image-packager/server.py"]
