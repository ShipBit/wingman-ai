class PubSub:
    def __init__(self):
        self.subscribers = {}

    def subscribe(self, event_type, fn):
        if not event_type in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(fn)

    def unsubscribe(self, event_type, fn):
        if event_type in self.subscribers:
            self.subscribers[event_type].remove(fn)

    def publish(self, event_type, data):
        if event_type in self.subscribers:
            for fn in self.subscribers[event_type]:
                fn(data)
