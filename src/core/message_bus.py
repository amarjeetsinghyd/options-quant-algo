import zmq
import json
import threading
import queue
import sys
import time
from typing import Callable
from src.utils.logger import get_logger

logger = get_logger("message_bus")

# Predefined Ports
FEED_PORT = 5555  # Market Data (Tick -> Brain/Shadow)
EXEC_PORT = 5556  # Executions (Brain -> Execution/DB)
CMD_PORT = 5557   # Commands (Brain -> Feed e.g., subscribe to options)

# ZMQ error code for "Socket operation on non-socket"
_ENOTSOCK = zmq.ENOTSOCK


class MessageBusPublisher:
    """
    ZeroMQ Publisher wrapper with automatic socket recovery.
    Creates a PUB socket and binds to a specific TCP/IPC port.
    Thread-safe for concurrent publish calls.
    Recovers from ENOTSOCK (socket closed/context terminated) by recreating the socket.
    """
    def __init__(self, port: int):
        self.port = port
        self.lock = threading.Lock()
        self._closed = False
        self._addr = None
        self.context = None
        self.socket = None
        self._init_socket()

    def _addr_str(self):
        if sys.platform != "win32":
            return f"ipc:///tmp/quant_{self.port}"
        return f"tcp://127.0.0.1:{self.port}"

    def _init_socket(self):
        """Create (or recreate) the PUB socket and bind. Uses the shared ZMQ context singleton."""
        try:
            if self.socket is not None:
                self.socket.close(linger=0)
        except Exception:
            pass
        # Do NOT terminate the shared context (zmq.Context.instance()).
        # Other sockets (Subscriber, other Publishers) may still be using it;
        # terminating it here would cascade ENOTSOCK to all peers on every
        # Publisher reconnect — the exact failure ADR-0001 is designed to prevent.

        self.context = zmq.Context.instance()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.setsockopt(zmq.SNDHWM, 10000)
        self._addr = self._addr_str()
        try:
            self.socket.bind(self._addr)
            logger.info(f"[ZMQ] Publisher bound to {self._addr}")
        except zmq.ZMQError as e:
            logger.error(f"[ZMQ] Failed to bind Publisher to port {self.port}: {e}")
            raise e

    def _reconnect(self):
        """Recreate the socket after a fatal error (ENOTSOCK etc.)."""
        logger.warning(f"[ZMQ] Publisher reconnecting on port {self.port}...")
        try:
            self._init_socket()
        except Exception as e:
            logger.error(f"[ZMQ] Publisher reconnect failed: {e}")

    def publish(self, topic: str, message: dict):
        """
        Publishes a JSON payload under a specific topic string.
        Auto-recovers from ENOTSOCK by recreating the socket once per call.
        """
        if self._closed:
            return
        with self.lock:
            for attempt in range(2):  # original + one retry after reconnect
                try:
                    payload = json.dumps(message)
                    self.socket.send_string(topic, flags=zmq.SNDMORE)
                    self.socket.send_string(payload)
                    return
                except zmq.ZMQError as e:
                    if e.errno == _ENOTSOCK and attempt == 0:
                        logger.error(f"[ZMQ] ENOTSOCK on publish '{topic}', reconnecting...")
                        self._reconnect()
                        continue
                    # For EAGAIN (SNDHWM full) or other transient errors, just log and drop
                    logger.error(f"[ZMQ] Error publishing to topic '{topic}': {e}")
                    return
                except Exception as e:
                    logger.error(f"[ZMQ] Error publishing to topic '{topic}': {e}")
                    return

    def close(self):
        """Gracefully close the publisher. Further publish() calls become no-ops."""
        with self.lock:
            self._closed = True
            try:
                if self.socket is not None:
                    self.socket.close(linger=0)
            except Exception:
                pass
            # Do NOT terminate the shared context (zmq.Context.instance())
            # — other sockets may still be using it.

class MessageBusSubscriber:
    """
    ZeroMQ Subscriber wrapper with automatic socket recovery.
    Creates a SUB socket, connects to a publisher port, and runs a blocking listen loop.
    Recovers from ENOTSOCK by recreating the socket and re-subscribing to all topics.
    """
    def __init__(self, port: int, topics: list = [""]):
        self.port = port
        self.lock = threading.Lock()
        self._closed = False
        self._topics = list(topics)  # track all subscribed topics for re-subscription
        self._addr = None
        self.context = None
        self.socket = None
        self._stop_event = threading.Event()
        self._subscription_queue = queue.Queue()
        self._init_socket()

    def _addr_str(self):
        if sys.platform != "win32":
            return f"ipc:///tmp/quant_{self.port}"
        return f"tcp://127.0.0.1:{self.port}"

    def _init_socket(self):
        """Create (or recreate) the SUB socket, connect, and re-subscribe to all known topics."""
        try:
            if self.socket is not None:
                self.socket.close(linger=0)
        except Exception:
            pass
        # Do NOT terminate shared context

        self.context = zmq.Context.instance()
        self.socket = self.context.socket(zmq.SUB)
        self.socket.setsockopt(zmq.RCVHWM, 10000)
        self._addr = self._addr_str()
        try:
            self.socket.connect(self._addr)
            for topic in self._topics:
                self.socket.setsockopt_string(zmq.SUBSCRIBE, topic)
            logger.info(f"[ZMQ] Subscriber connected to {self._addr}, topics: {self._topics}")
        except zmq.ZMQError as e:
            logger.error(f"[ZMQ] Failed to connect Subscriber to port {self.port}: {e}")
            raise e

    def _reconnect(self):
        """Recreate the socket after a fatal error and re-subscribe to all topics."""
        logger.warning(f"[ZMQ] Subscriber reconnecting on port {self.port}...")
        try:
            self._init_socket()
        except Exception as e:
            logger.error(f"[ZMQ] Subscriber reconnect failed: {e}")

    def add_subscription(self, topic: str):
        """Thread-safe way to add a subscription topic"""
        self._topics.append(topic)
        self._subscription_queue.put(topic)

    def listen(self, callback: Callable[[str, dict], None]):
        """
        Blocking loop that listens for messages and fires the callback.
        callback signature: callback(topic: str, payload: dict)
        Auto-recovers from ENOTSOCK by recreating the socket.
        """
        poller = zmq.Poller()
        poller.register(self.socket, zmq.POLLIN)

        while not self._stop_event.is_set():
            try:
                # Process pending subscriptions safely on the listening thread
                while not self._subscription_queue.empty():
                    try:
                        new_topic = self._subscription_queue.get_nowait()
                        self.socket.setsockopt_string(zmq.SUBSCRIBE, new_topic)
                    except queue.Empty:
                        break

                socks = dict(poller.poll(1000))  # 1000ms timeout

                if self.socket in socks and socks[self.socket] == zmq.POLLIN:
                    # Read multipart message (envelope + payload)
                    topic = self.socket.recv_string(flags=zmq.NOBLOCK)
                    payload_str = self.socket.recv_string(flags=zmq.NOBLOCK)

                    try:
                        payload = json.loads(payload_str)
                    except Exception as e:
                        logger.error(f"[ZMQ] Failed to decode JSON payload on topic '{topic}': {e}")
                        continue
                    if not isinstance(payload, (dict, list)):
                        logger.warning(f"[ZMQ] Received non-dict payload on topic '{topic}': {payload}")
                        continue
                    callback(topic, payload)

            except zmq.ZMQError as e:
                if e.errno == _ENOTSOCK:
                    logger.error(f"[ZMQ] ENOTSOCK in subscriber loop, reconnecting...")
                    self._reconnect()
                    # Re-register the new socket with the poller
                    poller = zmq.Poller()
                    poller.register(self.socket, zmq.POLLIN)
                    time.sleep(0.5)  # brief backoff before retrying
                elif not isinstance(e, zmq.Again):
                    logger.error(f"[ZMQ] Error in subscriber loop: {e}")
            except Exception as e:
                if not isinstance(e, zmq.Again):
                    logger.error(f"[ZMQ] Error in subscriber loop: {e}")

    def stop(self):
        self._stop_event.set()

    def close(self):
        """Gracefully close the subscriber."""
        self.stop()
        with self.lock:
            self._closed = True
            try:
                if self.socket is not None:
                    self.socket.close(linger=0)
            except Exception:
                pass
            # Do NOT terminate the shared context
