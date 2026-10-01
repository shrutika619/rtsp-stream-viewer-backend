"""One FFmpeg process per RTSP URL, shared by every viewer of that URL.

FFmpeg decodes the RTSP feed to a stream of JPEG frames. Each frame is pushed
into a Channels group (in-memory channel layer) and every subscribed WebSocket
consumer forwards it to its browser.
"""
import asyncio
import hashlib
import logging
from urllib.parse import urlparse

from channels.layers import get_channel_layer
from django.conf import settings

log = logging.getLogger(__name__)
SOI, EOI = b"\xff\xd8", b"\xff\xd9"


def validate_url(url):
    if not isinstance(url, str) or len(url) > 2048:
        return "Enter a valid RTSP URL."
    p = urlparse(url.strip())
    if p.scheme not in ("rtsp", "rtsps") or not p.hostname:
        return "URL must start with rtsp:// and include a host."
    return None


def group_name(url):
    return "stream_" + hashlib.sha1(url.encode()).hexdigest()[:24]


class Stream:
    def __init__(self, url):
        self.url = url
        self.group = group_name(url)
        self.viewers = 0
        self.task = None
        self.proc = None

    def _cmd(self):
        s = settings
        return [
            s.FFMPEG_BIN, "-hide_banner", "-loglevel", "error",
            "-rtsp_transport", "tcp", "-fflags", "nobuffer", "-flags", "low_delay",
            "-i", self.url, "-an",
            "-vf", f"fps={s.STREAM_FPS},scale='min({s.STREAM_WIDTH},iw)':-2",
            "-q:v", str(s.STREAM_JPEG_QUALITY), "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
        ]

    def _mask(self, text):
        return text.replace(self.url, "<stream>")

    async def _publish(self, payload):
        await get_channel_layer().group_send(self.group, payload)

    async def run(self):
        err_lines, got_frame, message = [], False, None
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *self._cmd(), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        except FileNotFoundError:
            await self._publish({"type": "stream.error", "message": "FFmpeg is not installed on the server."})
            return

        async def drain_stderr():
            async for line in self.proc.stderr:
                err_lines.append(line.decode(errors="ignore").strip())
                del err_lines[:-5]

        err_task = asyncio.create_task(drain_stderr())
        buf = bytearray()
        try:
            while True:
                timeout = settings.STALL_TIMEOUT if got_frame else settings.CONNECT_TIMEOUT
                chunk = await asyncio.wait_for(self.proc.stdout.read(65536), timeout)
                if not chunk:
                    message = "Stream ended." if got_frame else "Could not open the stream."
                    break
                buf += chunk
                while True:
                    start = buf.find(SOI)
                    if start < 0:
                        buf.clear()
                        break
                    end = buf.find(EOI, start + 2)
                    if end < 0:
                        del buf[:start]
                        break
                    frame = bytes(buf[start:end + 2])
                    del buf[:end + 2]
                    got_frame = True
                    await self._publish({"type": "stream.frame", "data": frame})
        except asyncio.TimeoutError:
            message = "Stream stopped sending video." if got_frame else "Timed out connecting to the stream."
        except asyncio.CancelledError:
            message = None
            raise
        finally:
            if self.proc.returncode is None:
                self.proc.kill()
            await self.proc.wait()
            err_task.cancel()
            manager.streams.pop(self.url, None)
            if message:
                detail = self._mask(" ".join(err_lines[-2:]))
                await self._publish(
                    {"type": "stream.error", "message": message + (f" ({detail})" if detail else "")}
                )


class StreamManager:
    def __init__(self):
        self.streams = {}

    def acquire(self, url):
        stream = self.streams.get(url)
        if stream is None:
            if len(self.streams) >= settings.MAX_STREAMS:
                raise RuntimeError(f"Server limit reached ({settings.MAX_STREAMS} streams).")
            stream = self.streams[url] = Stream(url)
            stream.task = asyncio.create_task(stream.run())
        stream.viewers += 1
        return stream

    def release(self, url):
        stream = self.streams.get(url)
        if not stream:
            return
        stream.viewers -= 1
        if stream.viewers <= 0:
            self.streams.pop(url, None)
            if stream.task:
                stream.task.cancel()


manager = StreamManager()
