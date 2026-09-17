"""不记录照片、标签和密钥的匹配阶段耗时。"""
from contextvars import ContextVar
from contextlib import contextmanager
from functools import wraps
import logging
from time import perf_counter
from uuid import uuid4

request_id = ContextVar("match_request_id", default="-")
logger = logging.getLogger("rugscene.timing")

@contextmanager
def stage(name):
    start = perf_counter()
    outcome = "ok"
    try:
        yield
    except BaseException as error:
        outcome = type(error).__name__
        raise
    finally:
        logger.info("match=%s stage=%s seconds=%.3f outcome=%s", request_id.get(), name, perf_counter()-start, outcome)

def timed(name):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with stage(name):
                return function(*args, **kwargs)
        return wrapped
    return decorate

def match_trace(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        token = request_id.set(uuid4().hex[:12])
        try:
            with stage("match_worker_total"):
                return function(*args, **kwargs)
        finally:
            request_id.reset(token)
    return wrapped
