FROM python:3.12-slim-bookworm

WORKDIR /app

# 1) APT：切换到国内 Debian 镜像（HTTPS），并安装编译依赖
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates; \
    rm -rf /var/lib/apt/lists/*; \
    rm -f /etc/apt/sources.list.d/*; \
    printf "%s\n" \
      "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm main contrib non-free non-free-firmware" \
      "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-updates main contrib non-free non-free-firmware" \
      "deb https://mirrors.tuna.tsinghua.edu.cn/debian-security bookworm-security main contrib non-free non-free-firmware" \
      > /etc/apt/sources.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends build-essential; \
    rm -rf /var/lib/apt/lists/*

# 2) PIP：配置国内 PyPI 镜像（关键：避免连 pypi.org 超时/不可达）
RUN set -eux; \
    mkdir -p /etc/pip; \
    printf "%s\n" \
      "[global]" \
      "index-url = https://pypi.tuna.tsinghua.edu.cn/simple" \
      "trusted-host = pypi.tuna.tsinghua.edu.cn" \
      "timeout = 60" \
      "retries = 10" \
      > /etc/pip.conf

COPY requirements.txt /app/requirements.txt

# 可选：先升级 pip/setuptools/wheel，减少编译/依赖解析坑
RUN python -m pip install --no-cache-dir -U pip setuptools wheel

RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

EXPOSE 4000

CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "main:app", "--bind", "0.0.0.0:4000", "--workers", "2", "--threads", "4", "--timeout", "120"]

