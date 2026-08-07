from pathlib import Path

import yaml

SEED_SERVICES_DIR = Path(__file__).resolve().parent.parent / "seed" / "services"


def load_catalog(services_dir: Path = SEED_SERVICES_DIR) -> dict[str, dict]:
    catalog: dict[str, dict] = {}
    for path in sorted(services_dir.glob("*.yaml")):
        service = yaml.safe_load(path.read_text(encoding="utf-8"))
        catalog[service["id"]] = service
    return catalog
