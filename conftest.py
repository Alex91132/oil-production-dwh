"""Корень репозитория в sys.path: тесты импортируют `scripts.*`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
