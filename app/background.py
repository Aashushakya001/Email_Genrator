from concurrent.futures import ThreadPoolExecutor
import functools

_executor = ThreadPoolExecutor(max_workers=2)


def submit(fn, *args, **kwargs):
    """Submit a function to run in background and return a Future."""
    return _executor.submit(functools.partial(fn, *args, **kwargs))
