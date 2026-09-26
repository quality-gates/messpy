from pathlib import Path
marker = Path(__file__).resolve().parents[1] / "executed.marker"
marker.write_text("messpy executed source")
raise RuntimeError("source must not run")
