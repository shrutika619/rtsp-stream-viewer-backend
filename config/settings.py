import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = ["daphne", "channels", "streams"]
MIDDLEWARE = []
ROOT_URLCONF = "config.urls"
ASGI_APPLICATION = "config.asgi.application"
DATABASES = {}  # no database needed
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# In-memory channel layer: no Redis required.
# NOTE: it lives inside one process, so run a single worker/instance.
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
        "CONFIG": {"capacity": 20, "expiry": 5},  # slow viewers drop frames instead of lagging
    }
}

# Streaming options
FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")
STREAM_FPS = int(os.environ.get("STREAM_FPS", "15"))
STREAM_WIDTH = int(os.environ.get("STREAM_WIDTH", "640"))
STREAM_JPEG_QUALITY = int(os.environ.get("STREAM_JPEG_QUALITY", "7"))  # 2 (best) - 31 (worst)
MAX_STREAMS = int(os.environ.get("MAX_STREAMS", "16"))
CONNECT_TIMEOUT = int(os.environ.get("CONNECT_TIMEOUT", "20"))   # seconds until first frame
STALL_TIMEOUT = int(os.environ.get("STALL_TIMEOUT", "10"))       # seconds without a frame
