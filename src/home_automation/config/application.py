from pathlib import Path


# Repository root containing frontend/, src/, and scripts/.
PROJECT_ROOT = Path(__file__).resolve().parents[3]

FRONTEND_DIST_DIRECTORY = PROJECT_ROOT / "frontend" / "dist"