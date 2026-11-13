"""Write every synthetic scenario to data/*.csv so you can test the upload flow."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # lets this script find the ab_copilot package

from ab_copilot.synthetic import SCENARIOS, make_experiment  # noqa: E402

out = ROOT / "data"
out.mkdir(exist_ok=True)
for name in SCENARIOS:
    df = make_experiment(name)
    df.to_csv(out / f"{name}.csv", index=False)
    print(f"wrote data/{name}.csv ({len(df):,} rows)")
