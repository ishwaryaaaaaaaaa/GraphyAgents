"""Build a ready-to-upload folder for a Hugging Face Space (Docker, free, no card).

    python scripts/make_space.py            # writes build/hf_space/

A Space needs a Dockerfile and a README.md with a small header at the repository's root, and runs the
container as a normal user on port 7860. This copies only what the website needs, so the Space does not
carry the tests, the evaluation or the results. With no FALKORDB_HOST set, the app runs FalkorDB embedded
in the container, so the memory is still a real FalkorDB graph (it resets when the Space restarts).
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "hf_space"

KEEP = ["agent", "data", "models", "ui", "cli.py", "ui_server.py", "requirements.txt", "LICENSE"]
SKIP = {"__pycache__", ".pytest_cache"}

DOCKERFILE = """FROM python:3.12-slim
# Hugging Face runs Docker Spaces as user 1000, so do not run as root.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH LLM_MODE=off PYTHONUNBUFFERED=1 UI_MAX_SESSIONS=500
WORKDIR /home/user/app
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=user . .
EXPOSE 7860
CMD ["python", "ui_server.py", "--host", "0.0.0.0", "--port", "7860"]
"""

README = """---
title: Decisive
emoji: 🧠
colorFrom: indigo
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: A decision partner whose memory never goes stale
---

# Decisive

A decision partner whose memory is a FalkorDB graph: facts are replaced, retracted and rewound, never
deleted, and only what is true now reaches an answer. Every answer shows the facts and graph path behind it.

Each visitor starts with a new, empty, private memory. Memories live in an embedded FalkorDB inside this
Space and reset when the Space restarts.

Source and evaluation: https://github.com/ishwaryaaaaaaaaa/GraphyAgents
"""


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for name in KEEP:
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, OUT / name, ignore=shutil.ignore_patterns(*SKIP, "*.pyc"))
        elif src.exists():
            shutil.copy2(src, OUT / name)
        else:
            raise SystemExit(f"missing {name}")
    (OUT / "Dockerfile").write_text(DOCKERFILE, encoding="utf-8")
    (OUT / "README.md").write_text(README, encoding="utf-8")
    files = sorted(p.relative_to(OUT).as_posix() for p in OUT.rglob("*") if p.is_file())
    print(f"wrote {OUT} ({len(files)} files)")


if __name__ == "__main__":
    main()
