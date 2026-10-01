import json

from channels.generic.websocket import AsyncWebsocketConsumer

from .manager import group_name, manager, validate_url


class StreamConsumer(AsyncWebsocketConsumer):
    """Client protocol (JSON text messages):
      {"action": "start", "url": "rtsp://..."}   start / restart
      {"action": "pause"} / {"action": "resume"}
      {"action": "stop"}
    Server sends binary JPEG frames and JSON {"type": "error"|"status", ...}.
    """

    async def connect(self):
        self.url = None
        self.group = None
        self.paused = False
        await self.accept()

    async def disconnect(self, code):
        await self._stop()

    async def receive(self, text_data=None, bytes_data=None):
        try:
            msg = json.loads(text_data or "")
            action = msg.get("action")
        except (ValueError, AttributeError):
            return await self._json("error", "Invalid message.")

        if action == "start":
            await self._start((msg.get("url") or "").strip())
        elif action == "pause":
            self.paused = True
            await self._json("status", "paused")
        elif action == "resume":
            self.paused = False
            await self._json("status", "playing")
        elif action == "stop":
            await self._stop()
        else:
            await self._json("error", "Unknown action.")

    async def _start(self, url):
        await self._stop()
        problem = validate_url(url)
        if problem:
            return await self._json("error", problem)
        self.paused = False
        self.group = group_name(url)
        await self.channel_layer.group_add(self.group, self.channel_name)
        try:
            manager.acquire(url)
        except RuntimeError as exc:
            await self.channel_layer.group_discard(self.group, self.channel_name)
            self.group = None
            return await self._json("error", str(exc))
        self.url = url
        await self._json("status", "connecting")

    async def _stop(self):
        if self.group:
            await self.channel_layer.group_discard(self.group, self.channel_name)
        if self.url:
            manager.release(self.url)
        self.url = self.group = None

    async def _json(self, kind, message):
        await self.send(text_data=json.dumps({"type": kind, "message": message}))

    # ---- group event handlers ----
    async def stream_frame(self, event):
        if not self.paused:
            await self.send(bytes_data=event["data"])

    async def stream_error(self, event):
        self.url = None  # stream already cleaned itself up
        await self._json("error", event["message"])
