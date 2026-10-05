FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY ecoscan/requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir \
    --timeout 300 \
    --retries 10 \
    --index-url https://download.pytorch.org/whl/cpu \
    torch torchvision \
    && pip install --no-cache-dir \
    --timeout 300 \
    --retries 10 \
    --index-url https://pypi.org/simple \
    --upgrade -r /app/requirements.txt

COPY ecoscan /app/ecoscan
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
