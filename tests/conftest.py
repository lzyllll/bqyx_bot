from pathlib import Path
import sys

# Ensure astrbot_plugin_bqyx can be imported
ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
LIB = PLUGIN_ROOT / "lib" / "bqyx_api"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
