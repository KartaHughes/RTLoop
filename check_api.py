"""Smoke-test the Nebius Token Factory connection and list Nemotron models.

Usage:
    python check_api.py              # list Nemotron models, test the first
    python check_api.py MODEL_ID     # test a specific model
"""
import os
import sys
import time
from pathlib import Path

from openai import OpenAI

BASE_URL = "https://api.tokenfactory.nebius.com/v1/"


def load_env(path):
    """Minimal .env reader: KEY=VALUE lines, existing environment wins."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main():
    load_env(Path(__file__).parent / ".env")
    key = os.environ.get("NEBIUS_API_KEY")
    if not key:
        sys.exit("NEBIUS_API_KEY is not set. Put it in .env (see .env.example).")

    client = OpenAI(base_url=BASE_URL, api_key=key)
    models = [m.id for m in client.models.list().data]
    nemotron = sorted(m for m in models if "nemotron" in m.lower())
    print(f"{len(models)} models available. Nemotron models:")
    for m in nemotron:
        print("  ", m)

    model = sys.argv[1] if len(sys.argv) > 1 else (nemotron[0] if nemotron else None)
    if not model:
        sys.exit("No Nemotron model found; pass a model id explicitly.")

    start = time.time()
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Reply with the single word: ready"}],
        max_tokens=300,
    )
    elapsed = time.time() - start
    print(f"\nModel: {model}")
    print(f"Reply: {resp.choices[0].message.content!r}")
    print(f"Tokens: {resp.usage.prompt_tokens} in, {resp.usage.completion_tokens} out; {elapsed:.1f}s")


if __name__ == "__main__":
    main()
