"""Small async database fakes that never open a real connection."""


class FakeCursor:
    def __init__(self, raw, cursor_class):
        self.raw = raw
        self.cursor_class = cursor_class
        self.rowcount = raw.rowcount

    async def __aenter__(self):
        self.raw.opened_cursors.append(self)
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.raw.closed_cursors.append(self)

    async def execute(self, sql, args=None):
        if self.raw.execute_error is not None:
            raise self.raw.execute_error
        self.raw.executions.append((sql, args))

    async def fetchone(self):
        return self.raw.fetchone_result

    async def fetchall(self):
        return self.raw.fetchall_result


class FakeRawConnection:
    def __init__(self):
        self.begin_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.begin_error = None
        self.commit_error = None
        self.rollback_error = None
        self.execute_error = None
        self.rowcount = 1
        self.fetchone_result = {"value": "one"}
        self.fetchall_result = [{"value": "many"}]
        self.executions = []
        self.opened_cursors = []
        self.closed_cursors = []

    def cursor(self, cursor_class=None):
        return FakeCursor(self, cursor_class)

    async def begin(self):
        self.begin_count += 1
        if self.begin_error is not None:
            raise self.begin_error

    async def commit(self):
        self.commit_count += 1
        if self.commit_error is not None:
            raise self.commit_error

    async def rollback(self):
        self.rollback_count += 1
        if self.rollback_error is not None:
            raise self.rollback_error


class FakePool:
    def __init__(self, raw=None):
        self.raw = raw or FakeRawConnection()
        self.acquire_count = 0
        self.release_count = 0
        self.released = []
        self.close_count = 0
        self.wait_closed_count = 0
        self.acquire_error = None

    async def acquire(self):
        self.acquire_count += 1
        if self.acquire_error is not None:
            raise self.acquire_error
        return self.raw

    def release(self, raw):
        self.release_count += 1
        self.released.append(raw)

    def close(self):
        self.close_count += 1

    async def wait_closed(self):
        self.wait_closed_count += 1


class FakeAsyncContext:
    def __init__(self, value, events=None):
        self.value = value
        self.events = events if events is not None else []

    async def __aenter__(self):
        self.events.append("connection-enter")
        return self.value

    async def __aexit__(self, exc_type, exc, traceback):
        self.events.append("connection-exit")
