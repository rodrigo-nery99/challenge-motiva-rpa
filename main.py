"""Atalho para rodar o robô sem instalar o pacote:  python main.py demo"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from motiva_rpa.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
