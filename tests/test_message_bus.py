import zmq
from src.core.message_bus import MessageBusPublisher, MessageBusSubscriber


def test_message_bus_publish_subscribe():
    pub = MessageBusPublisher(5560)
    sub = MessageBusSubscriber(5560, topics=['TEST.'])

    try:
        pub.publish('TEST.PING', {'hello': 'world'})
        assert sub.socket.getsockopt(zmq.RCVHWM) == 10000
    finally:
        sub.close()
        pub.close()
