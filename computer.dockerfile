FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt update && apt upgrade -y && apt install -y \
    software-properties-common \
    ca-certificates \
    curl \
    git \
    git-lfs \
    wget \
    python3 \
    python3-pip \
    python-is-python3 \
    && apt clean \
    && rm -rf /var/lib/apt/lists/*

