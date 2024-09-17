import asyncio
import inspect


class PubSub:
    def __init__(self):
        self.subscribers = {}

    def subscribe(self, event_type, fn):
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(fn)

    def unsubscribe(self, event_type, fn):
        if event_type in self.subscribers:
            self.subscribers[event_type].remove(fn)

    async def publish(self, event_type, data=None):
        if event_type in self.subscribers:
            for fn in self.subscribers[event_type]:
                # Get the number of parameters the function expects
                params = inspect.signature(fn).parameters
                param_count = len(params)

                # Determine if the function is a method (has 'self' parameter)
                is_method = "self" in params

                # Determine if the function expects an argument (excluding 'self' for methods)
                expects_arg = (param_count > 1) if is_method else (param_count > 0)

                if asyncio.iscoroutinefunction(fn):
                    if expects_arg and data is not None:
                        await fn(data)
                    else:
                        await fn()
                else:
                    if expects_arg and data is not None:
                        fn(data)
                    else:
                        fn()
