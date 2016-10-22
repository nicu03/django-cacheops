# -*- coding: utf-8 -*-
import threading
from funcy import wraps, once
from django.db.transaction import get_connection, Atomic

from .conf import settings
from .utils import monkey_mix


__all__ = ('queue_when_in_transaction', 'install_cacheops_transaction_support',
           'transaction_state')


class TransactionState(threading.local):
    def __init__(self, *args, **kwargs):
        super(TransactionState, self).__init__(*args, **kwargs)
        self._stack = []

    def begin(self):
        self._stack.append([])

    def commit(self):
        context = self._stack.pop()
        if self._stack:
            # savepoint
            self._stack[-1].extend(context)
        else:
            # transaction
            for func, args, kwargs in context:
                func(*args, **kwargs)

    def rollback(self):
        self._stack.pop()

    def append(self, item):
        self._stack[-1].append(item)

    def in_transaction(self):
        return bool(self._stack)

    def is_dirty(self):
        if settings.CACHEOPS_SMART_TRANSACTIONS:
            return any(self._stack)
        else:
            # Dumb mode: transactions are always dirty
            return self.in_transaction()

transaction_state = TransactionState()


def queue_when_in_transaction(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if transaction_state.in_transaction():
            transaction_state.append((func, args, kwargs))
        else:
            func(*args, **kwargs)
    return wrapper


class AtomicMixIn(object):
    def __enter__(self):
        transaction_state.begin()
        self._no_monkey.__enter__(self)

    def __exit__(self, exc_type, exc_value, traceback):
        self._no_monkey.__exit__(self, exc_type, exc_value, traceback)
        connection = get_connection(self.using)
        if not connection.closed_in_transaction and exc_type is None and \
                not connection.needs_rollback:
            transaction_state.commit()
        else:
            transaction_state.rollback()


@once
def install_cacheops_transaction_support():
    monkey_mix(Atomic, AtomicMixIn)
