# ALONE-CODER
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .

RUN apt-get update -y && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends ffmpeg curl unzip ca-certificates gnupg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp 2026.x solves YouTube's n-signature challenge with a JS runtime.
# Without Node >= 23.5 every download/stream returns "Sign in to confirm you're
# a bot". The bot selects the node runtime explicitly (see core/youtube.py
# JS_RUNTIMES), so Node MUST be present in the image.
RUN curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && node --version

RUN pip3 install -U pip && pip3 install -U -r requirements.txt

COPY . .

CMD ["bash", "start"]
