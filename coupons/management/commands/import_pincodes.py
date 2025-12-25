from django.core.management.base import BaseCommand
from django.conf import settings
import csv
import os
from coupons.models import DeliveryPincode


class Command(BaseCommand):
    help = "Import delivery pincodes from CSV"

    def handle(self, *args, **kwargs):
        csv_path = os.path.join(settings.BASE_DIR, 'india-pincodes.csv')
        
        if not os.path.exists(csv_path):
            self.stdout.write(self.style.ERROR(f"File not found: {csv_path}"))
            return
        
        self.stdout.write(self.style.WARNING("Starting import..."))
        
        with open(csv_path, encoding='utf-8') as file:
            reader = csv.DictReader(file)
            objs = []
            count = 0
            
            for row in reader:
                objs.append(
                    DeliveryPincode(
                        pincode=row['pincode'],
                        city=row['officename'],        # ← CHANGED: officename
                        district=row['district'],      # ← NEW: district field
                        state=row['statename'],
                        delivery_days=5,
                        is_cod_available=True,
                        is_serviceable=True
                    )
                )
                count += 1
                
                if count % 1000 == 0:
                    self.stdout.write(f"Processed {count} rows...")
            
            DeliveryPincode.objects.bulk_create(
                objs,
                batch_size=1000,
                ignore_conflicts=True
            )
        
        self.stdout.write(
            self.style.SUCCESS(f"✅ {count} pincodes imported successfully!")
        )
