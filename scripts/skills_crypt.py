"""skills/ 整包加解密：版控只放加密檔 skills.tar.gz.enc，skills/ 本身不進版控。

用法（gary-agent 根目錄）：
  python3 scripts/skills_crypt.py encrypt   commit 前跑：skills/ → skills.tar.gz.enc
  python3 scripts/skills_crypt.py decrypt   clone/pull 後跑：skills.tar.gz.enc → skills/

金鑰讀 .env 的 SKILLS_CRYPT_KEY。內容沒變就不重新加密，避免每次 commit 都產生無意義的變更。
"""
import hashlib
import os
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import config

SKILLS_DIR = ROOT / "skills"
ENC_FILE = ROOT / "skills.tar.gz.enc"
# 加密前內容的指紋，用來判斷 skills/ 有沒有變；只是雜湊，不洩漏內容
HASH_FILE = ROOT / "skills.sha256"
TMP_TAR = ROOT / "skills.tar.gz"

# 執行期產物、虛擬環境、大型文件不打包（與 .gitignore 對齊）
EXCLUDE_NAMES = {".venv", "__pycache__", ".DS_Store", ".server.log", ".server.pid",
                 ".pytest_cache"}
EXCLUDE_SUFFIXES = {".pyc", ".docx"}


def _is_excluded(path):
    rel = path.relative_to(ROOT)
    if any(part in EXCLUDE_NAMES for part in rel.parts):
        return True
    if path.suffix in EXCLUDE_SUFFIXES:
        return True
    # code review 產出的報告、AI 使用紀錄的匯出/待上傳檔都是個人產出物
    if path.match("skills/code-review-104/code-review-*.md"):
        return True
    return rel.parent == Path("skills/ai-usage-record-104") and path.suffix == ".json"


def _skill_files():
    return sorted(p for p in SKILLS_DIR.rglob("*")
                  if p.is_file() and not p.is_symlink() and not _is_excluded(p))


def _content_hash(files):
    h = hashlib.sha256()
    for p in files:
        h.update(str(p.relative_to(ROOT)).encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def _openssl(mode_args, src, dst):
    # 金鑰經環境變數傳給 openssl，不出現在指令列（ps 看不到）
    env = {**os.environ, "SKILLS_CRYPT_KEY": config.skills_crypt_key()}
    subprocess.run(
        ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000",
         *mode_args, "-in", str(src), "-out", str(dst), "-pass", "env:SKILLS_CRYPT_KEY"],
        env=env, check=True,
    )


def encrypt():
    files = _skill_files()
    digest = _content_hash(files)
    if ENC_FILE.exists() and HASH_FILE.exists() and HASH_FILE.read_text().strip() == digest:
        print("skills/ 沒有變更，不重新加密")
        return
    with tarfile.open(TMP_TAR, "w:gz") as tar:
        for p in files:
            tar.add(p, arcname=str(p.relative_to(ROOT)), recursive=False)
    try:
        _openssl(["-salt"], TMP_TAR, ENC_FILE)
    finally:
        TMP_TAR.unlink()
    HASH_FILE.write_text(digest + "\n")
    print(f"已加密 {len(files)} 個檔案 → {ENC_FILE.name}")


def decrypt():
    _openssl(["-d"], ENC_FILE, TMP_TAR)
    try:
        with tarfile.open(TMP_TAR, "r:gz") as tar:
            # filter="data" 擋掉絕對路徑、../ 跳出目錄等不安全的解壓
            tar.extractall(ROOT, filter="data")
            count = len(tar.getmembers())
    finally:
        TMP_TAR.unlink()
    print(f"已解密 {count} 個檔案 → skills/（同名檔會被覆蓋為加密檔內的版本）")


if __name__ == "__main__":
    commands = {"encrypt": encrypt, "decrypt": decrypt}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(__doc__)
    commands[sys.argv[1]]()
