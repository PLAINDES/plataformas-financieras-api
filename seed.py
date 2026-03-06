"""
    # Ejecutar todos los seeders
    python seed.py

    # Ejecutar solo uno
    python seed.py --only users
    python seed.py --only content_types
    python seed.py --only contents

    # Desde Docker
    docker exec financiera_backend python seed.py
"""

import sys
import argparse

from app.db.database import SessionLocal
from seeders import (
    UsersSeeder,
    PagesSeeder,
    SiteSettingsSeeder,
    ContentTypesSeeder,
    ContentsSeeder,
)


SEEDERS = {
    "users": UsersSeeder,
    "pages": PagesSeeder,
    "site_settings": SiteSettingsSeeder,
    "content_types": ContentTypesSeeder,
    "contents": ContentsSeeder,
}


def run_seeders(only: str = None):
    db = SessionLocal()
    try:
        if only:
            if only not in SEEDERS:
                print(f"❌ Seeder '{only}' not found. Available: {', '.join(SEEDERS.keys())}")
                sys.exit(1)
            print(f"\n🚀 Running seeder: {only}\n{'─' * 40}")
            SEEDERS[only](db).run()
        else:
            print(f"\n🚀 Running all seeders\n{'─' * 40}")
            for name, SeederClass in SEEDERS.items():
                SeederClass(db).run()

        print("🎉 Seeding completed successfully!")

    except Exception as e:
        db.rollback()
        print(f"\n❌ Seeding failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run database seeders")
    parser.add_argument(
        "--only",
        type=str,
        help=f"Run a single seeder. Options: {', '.join(SEEDERS.keys())}",
        default=None,
    )
    args = parser.parse_args()
    run_seeders(only=args.only)