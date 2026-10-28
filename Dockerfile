FROM python:3.12-slim-bookworm

# Icarus Verilog runs the simulations; git fetches the VerilogEval benchmark on first start.
RUN apt-get update \
    && apt-get install -y --no-install-recommends iverilog git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render sets PORT; app.py reads it and binds 0.0.0.0.
ENV PYTHONUNBUFFERED=1
CMD ["python", "app.py"]
