FROM python:3.13-slim
LABEL org.opencontainers.image.title="Sports Organizer" \
      org.opencontainers.image.source="https://github.com/dbowles1975/sports-organizer" \
      org.opencontainers.image.description="Organize NFL and UFC videos with Sportarr webhooks and Pushover notifications"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY organizer.py nfl_metadata.py /app/
RUN mkdir -p /data && chown 500:100 /data
USER 500:100
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=30s --start-period=30s --retries=3 CMD python -c "import os,urllib.request; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8080/health',headers={'Authorization':'Bearer '+os.environ['API_TOKEN']}),timeout=25)"
CMD ["python", "/app/organizer.py"]
