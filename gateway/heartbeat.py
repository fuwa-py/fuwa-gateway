import threading
import asyncio
import time
import logging


_log = logging.getLogger(__name__)

class HeartbeatManager(threading.Thread):
    def __init__(self, *args, **kwargs):
        interval = kwargs.pop("interval")
        connection = kwargs.pop("connection")
        threading.Thread.__init__(self, *args, **kwargs)

        self.interval = interval
        self.conn = connection
        self.daemon = True
        
        self._stop_ev = threading.Event()

        self._last_ack = time.perf_counter()
        self._last_send = time.perf_counter()
        self._last_recv = time.perf_counter()

    def run(self):
        while not self._stop_ev.wait(self.interval):
            # wait for the timeout to exhaust
            # this is essentially handling our heartbeat intervals

            # Send the heartbeat payload
            payload = self.get_heartbeat_payload()
            coro = self.conn.send_as_json(payload)
            future = asyncio.run_coroutine_threadsafe(coro, loop=self.conn.loop)

            try:
                future.result(timeout=self.interval)
                # set the timeout as the heartbeat interval
            except asyncio.TimeoutError:
                # timed out sending a heartbeat packet
                _log.warning("Timed out sending heartbeat packet")
            else:
                self._last_send = time.perf_counter()
            
    def get_heartbeat_payload(self):
        payload = {
            "op": self.conn.HEARTBEAT,
            "d": self.conn.seq
        }
        return payload

    def ack(self):
        self._last_ack = time.perf_counter()
    
    def tick(self):
        self._last_recv = time.perf_counter()

    def stop(self):
        self._stop_ev.set()