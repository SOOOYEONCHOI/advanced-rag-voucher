"""날짜별 로그 파일 핸들러.

`<directory>/<prefix>-YYYY-MM-DD.log` 에 쓴다. 날짜는 기록이 찍힌 시각의 현지
날짜다 — Django 가 프로세스 시간대를 `TIME_ZONE`(Asia/Seoul)으로 맞추므로 KST
자정에 갈린다.

웹 워커 여러 개와 `run_worker` 가 같은 파일에 쓴다. 표준
`TimedRotatingFileHandler` 는 자정에 파일 **이름을 바꾸는** 방식이라 프로세스마다
따로 바꾸려 해 서로 충돌한다. 여기서는 이름을 바꾸지 않는다 — 각 프로세스가 그날
파일을 append 로 열 뿐이다. 그래서 logrotate 도 필요 없다.
"""
import datetime
import logging
from pathlib import Path


class DailyFileHandler(logging.Handler):

    def __init__(self, directory, prefix='app', retention_days=30, encoding='utf-8'):
        super().__init__()
        self.directory = Path(directory)
        self.prefix = prefix
        self.retention_days = int(retention_days)   # 0 이면 지우지 않는다
        self.encoding = encoding
        self._date = None
        self._stream = None

    def emit(self, record):
        # handle() 이 잠금을 잡은 채로 부른다.
        try:
            date = datetime.date.fromtimestamp(record.created)
            if date != self._date:
                self._open(date)
            # ponytail: 한 줄을 write 한 번으로 쓴다. 아주 긴 트레이스는 버퍼 크기 단위로
            # 나뉘어 다른 프로세스 줄과 섞일 수 있다 — 문제가 되면 프로세스별 파일로 나눈다.
            self._stream.write(self.format(record) + '\n')
            self._stream.flush()
        except Exception:
            self.handleError(record)

    def _open(self, date):
        if self._stream:
            self._stream.close()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._stream = open(self.directory / f'{self.prefix}-{date:%Y-%m-%d}.log', 'a',
                            encoding=self.encoding)
        self._date = date
        self._purge(date)

    def _purge(self, today):
        """보존 기간이 지난 `<prefix>-YYYY-MM-DD.log` 만 지운다. 다른 파일은 건드리지 않는다."""
        if self.retention_days <= 0:
            return
        cutoff = today - datetime.timedelta(days=self.retention_days)
        for path in self.directory.glob(f'{self.prefix}-*.log'):
            try:
                day = datetime.date.fromisoformat(path.stem[len(self.prefix) + 1:])
            except ValueError:
                continue
            if day < cutoff:
                path.unlink(missing_ok=True)   # 다른 프로세스가 먼저 지웠을 수 있다

    def close(self):
        with self.lock:
            if self._stream:
                self._stream.close()
                self._stream = None
        super().close()
