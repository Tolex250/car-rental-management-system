from pathlib import Path
import sqlite3
from django.core.management.base import BaseCommand,CommandError
from django.conf import settings
class Command(BaseCommand):
    help='Create a consistent SQLite backup using the online backup API.'
    def add_arguments(self,parser):parser.add_argument('destination')
    def handle(self,*args,**options):
        target=Path(options['destination']).resolve()
        if target.exists():raise CommandError('Destination already exists. Choose a new backup filename.')
        target.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(settings.DATABASES['default']['NAME']) as source,sqlite3.connect(target) as dest:
            source.backup(dest)
            if dest.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise CommandError('Backup integrity check failed.')
        self.stdout.write(self.style.SUCCESS('Verified backup created: '+str(target)))
