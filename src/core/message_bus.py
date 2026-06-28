import zmq
import json
import threading
from typing import Callable, Any
from src.utils.logger import get_logger

logger = get_logger("message_bus")

# Predefined Ports
FEED_PORT = 5555  # Market Data (Tick -> Brain/Shadow)
EXEC_PORT = 5556  # Executions (Brain -> Execution/DB)
CMD_PORT = 5557   # Commands (Brain -> Feed e.g., subscribe to options)

class MessageBusPublisher:
    """
    ZeroMQ Publisher wrapper.
    Creates a PUB socket and binds to a specific TCP port.
    """
    def __init__(self, port: int):
        self.port = port
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        
        # High-water mark to prevent memory leaks if subscribers are slow
        self.socket.setsockopt(zmq.SNDHWM, 10000)
        
        try:
            self.socket.bind(f"tcp://127.0.0.1:{self.port}")
            logger.info(f"[ZMQ] Publisher bound to tcp://127.0.0.1:{self.port}")
        except zmq.ZMQError as e:
            logger.error(f"[ZMQ] Failed to bind Publisher to port {self.port}: {e}")
            raise e

    def publish(self, topic: str, message: dict):
        """
        Publishes a JSON payload under a specific topic string.
        """
        try:
            payload = json.dumps(message)
            # ZMQ Pub/Sub uses envelope matching. Topic and message are sent as multipart.
            self.socket.send_string(topic, flags=zmq.SNDMORE)
            self.socket.send_string(payload)
        except Exception as e:
            logger.error(f"[ZMQ] Error publishing to topic '{topic}': {e}")

    def close(self):
        self.socket.close()
        self.context.term()

class MessageBusSubscriber:
    """
    ZeroMQ Subscriber wrapper.
    Creates a SUB socket, connects to a publisher port, and runs a blocking listen loop.
    """
    def __init__(self, port: int, topics: list = [""]):
        self.port = port
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)
        
        self.socket.setsockopt(zmq.RCVHWM, 10000)
        
        try:
            self.socket.connect(f"tcp://127.0.0.1:{self.port}")
            for topic in topics:
                self.socket.setsockopt_string(zmq.SUBSCRIBE, topic)
            logger.info(f"[ZMQ] Subscriber connected to tcp://127.0.0.1:{self.port}, topics: {topics}")
        except zmq.ZMQError as e:
            logger.error(f"[ZMQ] Failed to connect Subscriber to port {self.port}: {e}")
            raise e
            
        self._stop_event = threading.Event()

    def listen(self, callback: Callable[[str, dict], None]):
        """
        Blocking loop that listens for messages and fires the callback.
        callback signature: callback(topic: str, payload: dict)
        """
        poller = zmq.Poller()
        poller.register(self.socket, zmq.POLLIN)
        
        while not self._stop_event.is_set():
            try:
                socks = dict(poller.poll(1000))  # 1000ms timeout
                
                if self.socket in socks and socks[self.socket] == zmq.POLLIN:
                    # Read multipart message (envelope + payload)
                    # Use NOBLOCK since we know data is ready, preventing any edge-case blocking
                    topic = self.socket.recv_string(flags=zmq.NOBLOCK)
                    payload_str = self.socket.recv_string(flags=zmq.NOBLOCK)
                    
                    payload = json.loads(payload_str)
                    callback(topic, payload)
                    
            except Exception as e:
                # Ignore Again if NOBLOCK somehow triggers it, otherwise log
                if not isinstance(e, zmq.Again):
                    logger.error(f"[ZMQ] Error in subscriber loop: {e}")

    def stop(self):
        self._stop_event.set()
        
    def close(self):
        self.stop()
        self.socket.close()
        self.context.term()
