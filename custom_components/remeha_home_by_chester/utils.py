import asyncio
import functools
import logging

_LOGGER = logging.getLogger(__name__)

def debounce_async(delay_seconds: float):
    """Decorator for debouncing async methods."""
    def decorator(method):
        @functools.wraps(method)
        async def wrapper(self, *args, **kwargs):
            key = method.__name__

            # Initialize storage if not exists
            if not hasattr(self, '_debounce_tasks'):
                self._debounce_tasks = {}

            self._debounce_tasks.setdefault(key, None)

            # Cancel previous task if still pending
            prev_task = self._debounce_tasks.get(key)
            if prev_task and not prev_task.done():
                prev_task.cancel()

            async def delayed():
                try:
                    await asyncio.sleep(delay_seconds)
                    # Call the actual method
                    await method(self, *args, **kwargs)
                except asyncio.CancelledError:
                    # means a new call has reset the debounce
                    pass

            # Schedule new debounce task
            task = asyncio.create_task(delayed())
            self._debounce_tasks[key] = task

        return wrapper
    return decorator
