"""Launch from an unpacked source ZIP; no pip install needed."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))

from pkg_batch_extractor.ui import main  # noqa: E402

if __name__ == '__main__':
    main()
