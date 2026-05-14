import csv
from django.core.management.base import BaseCommand
from tour_app.models import TouristPlace, CrowdStatus

class Command(BaseCommand):
    help = "Import tourist places from CSV into TouristPlace + CrowdStatus"

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str, help="Path to CSV file")

    def handle(self, *args, **opts):
        path = opts["csv_path"]

        created_places = 0
        created_crowds = 0

        # optional: clear existing
        CrowdStatus.objects.all().delete()
        TouristPlace.objects.all().delete()

        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)

            for row in reader:
                # expected columns (edit names to match your CSV headers)
                place_name = (row.get("place_name") or "").strip()
                location = (row.get("location") or "").strip()
                best_season = (row.get("best_season") or "").strip()
                description = (row.get("description") or "").strip()
                image_url = (row.get("image_url") or "").strip() or None

                lat = (row.get("latitude") or "").strip() or None
                lng = (row.get("longitude") or "").strip() or None

                crowd = (row.get("crowd_level") or "").strip() or None  # Low/Medium/High

                if not place_name:
                    continue

                tp = TouristPlace.objects.create(
                    place_name=place_name,
                    location=location,
                    best_season=best_season,
                    description=description,
                    image_url=image_url,
                    latitude=lat,
                    longitude=lng,
                )
                created_places += 1

                if crowd:
                    CrowdStatus.objects.create(place=tp, crowd_level=crowd)
                    created_crowds += 1

        self.stdout.write(self.style.SUCCESS(
            f"Imported {created_places} places, {created_crowds} crowd rows."
        ))