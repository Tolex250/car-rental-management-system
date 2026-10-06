from django.core.management.base import BaseCommand,CommandError
from django.contrib.auth.models import User,Group
from django.db import transaction
from rental.models import Vehicle
from rental.services import ROLES
import os
class Command(BaseCommand):
    help='Create illustrative fleet and role accounts. Requires DEMO_PASSWORD (at least 12 characters).'
    @transaction.atomic
    def handle(self,*args,**kwargs):
        password=os.environ.get('DEMO_PASSWORD','')
        if len(password)<12:raise CommandError('Set DEMO_PASSWORD to a private value of at least 12 characters.')
        for role in ROLES:
            group,_=Group.objects.get_or_create(name=role)
            u,created=User.objects.get_or_create(username=role,defaults={'first_name':role.title(),'email':role+'@example.test'})
            if created:u.set_password(password);u.save();u.groups.add(group)
        for reg,name,category,seats,rate in [('DEMO-001','Toyota Corolla','Saloon',5,20000),('DEMO-002','Toyota RAV4','SUV',5,35000),('DEMO-003','Toyota Hiace','Minibus',14,50000)]:
            Vehicle.objects.get_or_create(registration=reg,defaults={'name':name,'category':category,'seats':seats,'daily_rate':rate,'deposit_required':10000,'turnaround_minutes':30})
        self.stdout.write(self.style.SUCCESS('Demo records ready. Accounts: '+', '.join(ROLES)+'. Existing account passwords were not changed.'))
