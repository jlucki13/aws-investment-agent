import sys
from pathlib import Path

# The shared package is deployed as a Lambda layer, which puts it on sys.path at
# runtime. Tests need the same import to resolve locally.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "layers" / "common" / "python"))
