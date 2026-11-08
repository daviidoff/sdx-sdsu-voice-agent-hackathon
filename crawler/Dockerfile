FROM python:3.12-slim
WORKDIR /app
COPY disaster_crawler /app/disaster_crawler
COPY examples /app/examples
USER 65534:65534
ENTRYPOINT ["python", "-m", "disaster_crawler"]
CMD ["--request", "examples/demo-request.json"]
