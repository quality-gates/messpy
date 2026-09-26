from pathlib import Path
if __name__ == "__main__":
    marker = Path(__file__).resolve().parents[1] / "guarded.marker"
    marker.write_text("messpy executed source")
