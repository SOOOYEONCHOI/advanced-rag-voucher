#!/usr/bin/env python
"""웹(runserver)·워커(run_worker)를 띄우고 끄는 개발·단독 실행용 도구.

    .venv/bin/python scripts/maipctl.py start   [web|worker|all] [--addr 0.0.0.0:8123] [--foreground]
    .venv/bin/python scripts/maipctl.py stop    [web|worker|all] [--timeout 30]
    .venv/bin/python scripts/maipctl.py status  [web|worker|all]
    .venv/bin/python scripts/maipctl.py restart [web|worker|all] [--addr ...] [--foreground]

운영 서버는 systemd(maip·maip-worker)로 관리한다. 이 도구를 쓰지 않는다.

PID 파일을 두지 않고 /proc 에서 찾는다 — 작업 폴더가 이 저장소인 `manage.py runserver`·`manage.py run_worker`.
그래서 손으로 띄운 프로세스도 잡고, 같은 PC 의 다른 프로젝트 manage.py 는 건드리지 않는다.
백그라운드 출력은 storage/logs/runserver.log·run_worker.log 에 이어 쓴다.
"""
import argparse
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / 'storage' / 'logs'
DEFAULT_ADDR = '127.0.0.1:8123'
COMMANDS = {'web': 'runserver', 'worker': 'run_worker'}
LOG_FILES = {'web': 'runserver.log', 'worker': 'run_worker.log'}
NAMES = {'web': '웹', 'worker': '워커'}


def find(target):
    """[(pid, argv)] — 이 저장소에서 도는 target 프로세스. runserver 는 자동 재시작 자식까지 함께 나온다."""
    found = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv = (entry / 'cmdline').read_bytes().decode(errors='replace').split('\0')[:-1]
            cwd = Path(os.readlink(entry / 'cwd'))
        except OSError:   # 그사이 끝났거나 다른 사용자의 프로세스
            continue
        if cwd == ROOT and 'manage.py' in [Path(a).name for a in argv] and COMMANDS[target] in argv:
            found.append((int(entry.name), argv))
    return sorted(found)


def running_addr(procs):
    """실행 중인 runserver 의 주소. 인자로 주지 않았으면 기본 주소다."""
    for _, argv in procs:
        rest = argv[argv.index('runserver') + 1:]
        addrs = [a for a in rest if not a.startswith('-')]
        if addrs:
            return addrs[0]
    return DEFAULT_ADDR


# ./scripts/maipctl.py 로 부르면 PATH 의 python 이 돈다. 웹·워커는 저장소 가상환경으로 띄운다.
VENV_PYTHON = ROOT / '.venv' / 'bin' / 'python'


def command(target, addr):
    python = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
    cmd = [python, 'manage.py', COMMANDS[target]]
    return cmd + [addr] if target == 'web' else cmd


def start(target, addr):
    procs = find(target)
    if procs:
        print(f'{NAMES[target]}: 이미 실행 중입니다 (PID {procs[0][0]}).')
        return 0
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / LOG_FILES[target]
    with open(log_path, 'ab') as log:
        log.write(f'\n=== maipctl start {datetime.now():%Y-%m-%d %H:%M:%S} ===\n'.encode())
        log.flush()
        # 새 세션으로 띄워 이 터미널을 닫아도 남게 한다(setsid nohup 과 같다).
        proc = subprocess.Popen(command(target, addr), cwd=ROOT, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    time.sleep(2)   # 포트 충돌·설정 오류처럼 바로 죽는 경우를 잡는다
    if proc.poll() is not None:
        print(f'{NAMES[target]}: 시작하지 못했습니다 (종료 코드 {proc.returncode}). 로그 끝부분입니다 — {log_path}')
        print(''.join(log_path.read_text(errors='replace').splitlines(keepends=True)[-20:]), end='')
        return 1
    where = f', 주소 http://{addr}/' if target == 'web' else ''
    print(f'{NAMES[target]}: 시작했습니다 (PID {proc.pid}{where}). 로그 {log_path}')
    return 0


def stop(target, timeout):
    procs = find(target)
    if not procs:
        print(f'{NAMES[target]}: 멈춰 있습니다.')
        return 0
    if target == 'worker':
        print(f'워커: 처리 중인 작업을 끝내고 멈춥니다. 최대 {timeout}초 기다립니다.')
    for pid, _ in procs:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + timeout
    while find(target) and time.monotonic() < deadline:
        time.sleep(0.5)
    left = find(target)
    for pid, _ in left:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if left:
        print(f'{NAMES[target]}: {timeout}초 안에 멈추지 않아 강제로 종료했습니다 (PID {", ".join(str(p) for p, _ in left)}).')
        if target == 'worker':
            print('워커: 처리 중이던 작업은 실행 중으로 남았다가 WORKER_STALE_SECONDS 가 지나면 다시 처리됩니다.')
    else:
        print(f'{NAMES[target]}: 멈췄습니다 (PID {", ".join(str(p) for p, _ in procs)}).')
    return 0


def status(target):
    procs = find(target)
    if not procs:
        print(f'{NAMES[target]}: 멈춤')
        return 3
    pids = ', '.join(str(p) for p, _ in procs)
    where = f', 주소 http://{running_addr(procs)}/' if target == 'web' else ''
    print(f'{NAMES[target]}: 실행 중 (PID {pids}{where})')
    return 0


def foreground(targets, addr):
    """targets 를 이 터미널에서 띄우고 기다린다. Ctrl+C 나 하나가 끝나면 나머지도 멈춘다."""
    busy = [t for t in targets if find(t)]
    if busy:
        print(f'{"·".join(NAMES[t] for t in busy)}: 이미 실행 중입니다. 먼저 stop 으로 멈춰 주세요.')
        return 1
    # kill·서비스 관리자가 보내는 SIGTERM 도 Ctrl+C 와 같게 받는다. 받지 않으면 이 프로세스만 죽고 자식이 남는다.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    procs = {t: subprocess.Popen(command(t, addr), cwd=ROOT) for t in targets}
    interrupted = False
    try:
        while all(p.poll() is None for p in procs.values()):
            time.sleep(0.5)
    except KeyboardInterrupt:   # 터미널이 자식에게도 SIGINT 를 보낸다
        interrupted = True
    for p in procs.values():
        if p.poll() is None:
            p.terminate()
    try:
        for p in procs.values():
            p.wait()
    except KeyboardInterrupt:   # 워커가 작업을 끝내기를 기다리다 한 번 더 누르면 바로 끝낸다
        for p in procs.values():
            p.kill()
    if interrupted:
        return 0
    return next((p.returncode for p in procs.values() if p.returncode), 0)


def main():
    parser = argparse.ArgumentParser(description='웹(runserver)·워커(run_worker)를 띄우고 끕니다. 운영 서버는 systemd 를 씁니다.')
    parser.add_argument('action', choices=['start', 'stop', 'status', 'restart'])
    parser.add_argument('target', nargs='?', default='all', choices=['web', 'worker', 'all'])
    parser.add_argument('--foreground', action='store_true',
                        help='start·restart: 이 터미널에서 띄우고 Ctrl+C 로 멈춥니다(로그는 화면에 나옵니다).')
    parser.add_argument('--addr', help=f'웹 주소. 기본 {DEFAULT_ADDR}, restart 는 실행 중이던 주소. 다른 PC 에서 열려면 0.0.0.0:8123')
    parser.add_argument('--timeout', type=float, default=30, help='stop·restart: 멈추기를 기다리는 초. 넘으면 강제 종료합니다(기본 30).')
    args = parser.parse_args()
    if args.foreground and args.action not in ('start', 'restart'):
        parser.error('--foreground 는 start·restart 에만 씁니다.')

    targets = ['web', 'worker'] if args.target == 'all' else [args.target]
    if args.action == 'status':
        return max(status(t) for t in targets)

    addr = args.addr or DEFAULT_ADDR
    if args.action == 'restart':
        web = find('web') if 'web' in targets else []
        addr = args.addr or (running_addr(web) if web else DEFAULT_ADDR)
    if args.action in ('stop', 'restart'):
        code = max(stop(t, args.timeout) for t in reversed(targets))
        if args.action == 'stop':
            return code
    if args.foreground:
        return foreground(targets, addr)
    return max(start(t, addr) for t in targets)


if __name__ == '__main__':
    sys.exit(main())
