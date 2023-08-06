FROM python:3.11.4-bookworm as build

ENV TZ=Asia/Tokyo

# NOTE: libgl1-mesa-glx は OpenCV に必要
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    python3 \
    python3-dev \
    libgl1-mesa-glx \
 && apt-get clean \
 && rm -rf /va/rlib/apt/lists/*

WORKDIR /opt/e-ink_weather

RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="/root/.local/bin:$PATH"

COPY pyproject.toml .

RUN poetry config virtualenvs.create false \
 && poetry install \
 && rm -rf ~/.cache

FROM python:3.11.4-slim-bookworm as prod

COPY --from=build /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=build /usr/lib/x86_64-linux-gnu/libGL.so.1 /usr/lib/x86_64-linux-gnu/libGL.so.1

WORKDIR /opt/e-ink_weather

ENV PATH="/root/.local/bin:$PATH"

RUN useradd -m ubuntu

RUN mkdir -p data
RUN chown -R ubuntu:ubuntu .

USER ubuntu

COPY font /usr/share/fonts/
COPY --chown=ubuntu . .

CMD ["./app/display_image.py"]
