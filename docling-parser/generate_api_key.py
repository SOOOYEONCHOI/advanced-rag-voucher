"""
API Key 생성 및 .env 파일 초기화 스크립트
"""
import secrets
import string
from pathlib import Path

ENV_PATH = Path(__file__).parent / ".env"

ENV_TEMPLATE = """\
API_KEY={api_key}
PORT=8008
CUDA_VISIBLE_DEVICES=0
"""


def generate_api_key(length: int = 64) -> str:
    # 2026.08.28(sooyeon.choi) 수정 - 기호 제거. $ 는 docker compose 보간,
    #   # 는 dotenv 주석으로 해석되어 컨테이너에 다른 값이 주입될 수 있다.
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def write_env(api_key: str):
    ENV_PATH.write_text(ENV_TEMPLATE.format(api_key=api_key), encoding="utf-8")
    print(f".env 파일이 생성되었습니다: {ENV_PATH}")
    print(f"API_KEY={api_key}")


if __name__ == "__main__":
    api_key = generate_api_key()

    if ENV_PATH.exists():
        print(f".env 파일이 이미 존재합니다: {ENV_PATH}")
        answer = input("덮어쓰시겠습니까? (y/N): ").strip().lower()
        if answer != "y":
            print("취소되었습니다.")
        else:
            write_env(api_key)
    else:
        write_env(api_key)
