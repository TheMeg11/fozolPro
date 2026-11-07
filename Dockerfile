# fozol-pro — ربات بله + مینی‌اپ (یک سرویس Railway، یک پروسس)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Tehran \
    PORT=8080

WORKDIR /app

# libfribidi/libharfbuzz: رندر RTL لیدربورد تصویری (raqm)
# tzdata: زمان‌بندی بکاپ شبانه به وقت تهران
RUN apt-get update && apt-get install -y --no-install-recommends libfribidi0 libharfbuzz0b tzdata \
    && rm -rf /var/lib/apt/lists/*

# لایهٔ وابستگی‌ها جدا کپی می‌شود تا با تغییر کد، کش بماند
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# دیتابیس روی Railway Volume در /data
RUN mkdir -p /data
EXPOSE 8080
STOPSIGNAL SIGTERM

CMD ["python", "run.py"]
