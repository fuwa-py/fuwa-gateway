import asyncio
import sys
import zlib
import json
import logging
import random
import traceback
from typing import (
    Optional,
    Callable,
    Coroutine,
    Any,
    Dict,
    List,
    Tuple
)
from contextlib import suppress as suppress_exc
from urllib.parse import urlencode, urljoin

import aiohttp

from .heartbeat import HeartbeatManager
from .intents import IntentsFlags


_log = logging.getLogger(__name__)

CoroFuncT = Callable[..., Coroutine[Any, Any, Any]]

class GatewayConnection:
    """A class representing a connection
    to discord's gateway
    """

    DISPATCH           = 0
    HEARTBEAT          = 1
    IDENTIFY           = 2
    PRESENCE           = 3
    VOICE_STATE        = 4
    VOICE_PING         = 5
    RESUME             = 6
    RECONNECT          = 7
    REQUEST_MEMBERS    = 8
    INVALIDATE_SESSION = 9
    HELLO              = 10
    HEARTBEAT_ACK      = 11
    GUILD_SYNC         = 12

    def __init__(
        self,
        token: str,
        intents: IntentsFlags,
        *,
        shard_id: Optional[int] = None,
        shard_count: Optional[int] = None
    ):
        if shard_id and shard_count is None:
            raise ValueError("If shard_id is provided, shard_count must be provided as well")
        
        self.token = token
        self.intents = intents
        self.shard_id = shard_id
        self.shard_count = shard_count

        self.websocket: Optional[aiohttp.ClientWebSocketResponse] = None
        self.receive_task: Optional[asyncio.Task] = None

        self.loop = asyncio.get_event_loop()

        # Cached Gateway Information
        self.gateway_url: Optional[str] = None
        self.gateway_version: Optional[int] = None

        self._reconnect_codes = {
            1000,
            4000,
            4001,
            4002,
            4005,
            4007,
            4008,
            4009
        } # discord tells us to re-connect on a 4003
        # however this would entail the token being reset while the bot
        # is online, and there's no point re-connecting on this close code

        self._inflator = zlib.decompressobj()
        self._buffer = bytearray()
        self._heartbeat: Optional[HeartbeatManager] = None

        self._event_handlers: Dict[str, List[CoroFuncT]] = {}

        self.session_id: Optional[str] = None
        self.seq: Optional[int] = None

        self.__session: Optional[aiohttp.ClientSession] = None

    def add_event_handler(
        self,
        event_name: str,
        handler: CoroFuncT
    ) -> Tuple[str, CoroFuncT]:
        event_name = event_name.lower()

        current_event_handlers = self._event_handlers.get(event_name, [])
        current_event_handlers.append(handler)

        self._event_handlers[event_name] = current_event_handlers

        return (event_name, handler)

    async def ws_connect(self, gateway_url: str):
        # This method is purely for connecting the websocket
        # there are no additional checks here
        ws = await self.__session.ws_connect(gateway_url)
        self.websocket = ws

        return ws

    async def _recv_task(self, ws: aiohttp.ClientWebSocketResponse):
        try:
            async for msg in ws:
                await self.handle_message(msg.data)

        except Exception:
            traceback.print_exc()
        finally:
            # Signals the closure of the websocket
            code = ws.close_code
            _log.info("WebSocket closed with close code %s" % code)

            # Stop our heartbeat handler for
            # obvious reasons (there's no point sending heartbeats, if the ws is closed)
            if self._heartbeat:
                self._heartbeat.stop()
                self._heartbeat = None

            if code in self._reconnect_codes:
                # if we can handle these close codes
                # attempt a resume
                
                # Prepare for a re-connect
                await self.prepare()
                ws = await self.ws_connect(self.gateway_url)

                # Instead of creating a new receive task
                # We just send the resume, and then create a new task

                await self.send_resume()

                # Now create a new task
                await self.create_receive_task(ws)
            else:
                # If we cannot handle these close codes
                # simply close the gateway handler
                # TODO: CLOSE
                _log.warning("WebSocket closed with code %s. This is a code we cannot handle. Terminating connection" % code)

                await self.close()
            
    async def create_receive_task(self, ws: Optional[aiohttp.ClientWebSocketResponse] = None):
        if self.receive_task is not None:
            # probably a RESUME or a re-connect
            with suppress_exc(asyncio.CancelledError):
                self.receive_task.cancel()
                self.receive_task.set_result(None)
                self.receive_task.done()

        ws = ws or self.websocket
        recv_coro = self._recv_task(ws)
        recv_task = asyncio.create_task(recv_coro, name="luna:gateway:gateway_receive")

        self.receive_task = recv_task

    def share_session(self, session: aiohttp.ClientSession):
        self.__session = session

    async def prepare(self):
        """This method runs all the necessary checks
        and prepares the class to connect to the websocket
        """

        if self.__session is None or self.__session.closed:
            self.__session = aiohttp.ClientSession()

        if self.websocket is not None:
            # We have an existing connection
            # we want to close it
            with suppress_exc(Exception):
                await self.websocket.close(code=4000)

    async def open_connection(
        self,
        gateway_url: str,
        *,
        version: int = 9
    ):
        gateway_url = self._generate_gateway_url(
            gateway_url,
            version=version,
            encoding="json",
            compress="zlib-stream"
        )
        _log.info("Connecting to Gateway via %s" % gateway_url)

        await self.prepare()

        ws = await self.ws_connect(gateway_url)
        await self.create_receive_task(ws)

        _log.info("Successfully opened connection")

    def _generate_gateway_url(self, base: str, **options):
        version = options.pop("version")
        encoding = options.pop("encoding")
        compress = options.pop("compress")

        params = {
            "v": str(version),
            "encoding": encoding,
            "compress": compress
        }

        param_string = urlencode(params)
        param_string = "?" + param_string # I wish urlencode did this

        gateway_url = urljoin(base, param_string)
        return str(gateway_url)

    async def send(self, data: str):
        await self.websocket.send_str(data)

    async def send_as_json(self, data: object):
        data = json.dumps(data)
        await self.send(data)

    async def send_identify(self):
        payload = {
            "op": self.IDENTIFY,
            "d": {
                "token": self.token,
                "intents": self.intents._bits,
                "properties": {
                    "$os": sys.platform,
                    "$browser": "luna_gateway",
                    "$device": "luna_gateway"
                },
                "large_threshold": 250,
                "compress": True
            }
        }

        if self.shard_id:
            shard_info = (self.shard_id, self.shard_count)
            payload["d"]["shard"] = shard_info
        
        await self.send_as_json(payload)

    async def send_resume(self):
        payload = {
            "op": self.RESUME,
            "d": {
                "token": self.token,
                "session_id": self.session_id,
                "seq": self.seq
            }
        }

        await self.send_as_json(payload)

    async def handle_message(self, msg):
        if isinstance(msg, bytes):
            # decompress via zlib protocol
            self._buffer.extend(msg)

            if len(msg) < 4 or msg[-4:] != b'\x00\x00\xff\xff':
                return

            msg = self._inflator.decompress(self._buffer)
            self._buffer = bytearray()

        # Convert our message into 'json'
        msg = json.loads(msg)

        data = msg["d"]
        event = msg["t"]
        op = msg["op"]
        seq = msg["s"]

        if seq is not None:
            self.seq = seq

        _log.debug("Received message %s" % msg)

        if self._heartbeat:
            self._heartbeat.tick()

        if op != self.DISPATCH:
            # Handle non-event-dispatch related events

            # Handle op HELLO
            if op == self.HELLO:
                # Extract our heartbeat_interval
                heartbeat_interval = data["heartbeat_interval"]
                heartbeat_interval = float(heartbeat_interval) / 1000.0

                # Create our heartbeat manager
                heartbeat = HeartbeatManager(interval=heartbeat_interval, connection=self)
                self._heartbeat = heartbeat

                # Send our IDENTIFY payload
                await self.send_identify()
            
            elif op == self.HEARTBEAT:
                # The gateway is asking for a heartbeat
                # this could be for any reason
                # we must send an immediate response back
                heartbeat_payload = self._heartbeat.get_heartbeat_payload()
                await self.send_as_json(heartbeat_payload)
                
            elif op == self.HEARTBEAT_ACK:
                self._heartbeat.ack()

            elif op == self.INVALIDATE_SESSION:
                # Invalidated session
                sleep = random.randint(1, 6)
                await asyncio.sleep(sleep)

                # prepare for a new connection
                await self.prepare()

                # Re-connect our websocket, and create a new receive task
                ws = await self.ws_connect(self.gateway_url)
                await self.create_receive_task(ws)
        
        if event == "READY":
            # Handle READY event
            session_id = data["session_id"]
            self.session_id = session_id

            # Start our heartbeat manager
            self._heartbeat.start()

            # Send a heartbeat immediately after we
            # receive READY
            heartbeat_payload = self._heartbeat.get_heartbeat_payload()
            await self.send_as_json(heartbeat_payload)

        if op == self.DISPATCH:
            # Handle Event handlers
            if event is not None:
                _log.info("Dispatching event handlers for event %s" % event)

                handlers = self._event_handlers.get(event.lower(), [])
                for i, handler in enumerate(handlers):
                    name = "gateway_event_dispatch:{}:{}".format(event, i)
                    self._schedule_event(name, handler, data)

    async def _run_event(self, name: str, handler: CoroFuncT, *args, **kwargs):
        """
        Handles the wrapping and running of the event
        """
        coro = handler(*args, **kwargs)
        
        try:
            await coro
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            _log.warning("Event handler %s errored with exception (minified) %s" % (name, exc))
            traceback.print_exc()
        
    def _schedule_event(self, name: str, handler: CoroFuncT, *args, **kwargs):
        wrapped = self._run_event(name, handler, *args, **kwargs)

        asyncio.create_task(wrapped, name=name)

    async def close(self):
        with suppress_exc(Exception):
            if self.websocket:
                await self.websocket.close(code=4000)
            
        with suppress_exc(Exception):
            if self.__session:
                await self.__session.close()