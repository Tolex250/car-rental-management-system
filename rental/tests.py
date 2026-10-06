from datetime import timedelta
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
import tempfile,sqlite3
from pathlib import Path
from django.test import TestCase,TransactionTestCase,Client,override_settings
from django.contrib.auth.models import User,Group
from django.core.exceptions import ValidationError,PermissionDenied
from django.db import IntegrityError,transaction,connections,connection
from django.utils import timezone
from .models import *
from . import services as s

class Setup:
    def setUp(self):
        self.users={}
        for role in s.ROLES:
            u=User.objects.create_user(role,password='Test-Only-Password-9381')
            u.groups.add(Group.objects.get_or_create(name=role)[0]);self.users[role]=u
        self.v=Vehicle.objects.create(registration='DEMO-001',name='Test saloon',category='Saloon',daily_rate=20000,turnaround_minutes=0)
        self.start=timezone.now()+timedelta(days=2);self.end=self.start+timedelta(hours=49)
    def booking(self,**kwargs):
        return s.request_booking(self.users['requester'],kwargs.get('vehicle',self.v),kwargs.get('start',self.start),kwargs.get('end',self.end),'Academic visit','demo@example.test')
    def confirmed(self,**kwargs):
        b=self.booking(**kwargs);return s.confirm(self.users['fleet'],b.pk)
    def paid(self):
        b=self.confirmed();s.payment(self.users['finance'],b.pk,b.invoice.total,'BANK-001');return b
    def issued(self):
        b=self.paid()
        with patch('rental.services.timezone.now',return_value=b.start):s.issue(self.users['fleet'],b.pk,100,90,'No visible damage')
        b.refresh_from_db();return b

@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class WorkflowTests(Setup,TestCase):
    def test_T01_invalid_interval(self):
        with self.assertRaises(ValidationError):self.booking(end=self.start-timedelta(hours=1))
    def test_T02_overlap_rejected(self):
        b=self.booking();other=self.booking();s.confirm(self.users['fleet'],b.pk)
        with self.assertRaises(ValidationError):s.confirm(self.users['fleet'],other.pk)
        self.assertEqual(Allocation.objects.filter(active=True).count(),1)
    def test_T03_adjacent_allowed(self):
        self.confirmed();b=self.confirmed(start=self.end,end=self.end+timedelta(hours=2));self.assertEqual(b.status,'confirmed')
    def test_T04_turnaround_blocks(self):
        self.v.turnaround_minutes=30;self.v.save();self.confirmed()
        with self.assertRaises(ValidationError):self.booking(start=self.end,end=self.end+timedelta(hours=2))
    def test_T06_maintenance_blocks(self):
        s.schedule_maintenance(self.users['fleet'],self.v,self.start,self.end,'Service')
        with self.assertRaises(ValidationError):self.booking()
    def test_T07_requester_cannot_verify_payment(self):
        b=self.confirmed()
        with self.assertRaises(PermissionDenied):s.payment(self.users['requester'],b.pk,100,'BAD')
        self.assertEqual(Payment.objects.count(),0)
    def test_T08_ownership_is_checked_on_server(self):
        b=self.booking();u=User.objects.create_user('other',password='Other-Password-9381');u.groups.add(Group.objects.get(name='requester'))
        self.client.force_login(u);self.assertEqual(self.client.get(f'/bookings/{b.pk}/').status_code,404)
        self.assertEqual(self.client.post(f'/bookings/{b.pk}/cancel/',{'reason':'unauthorised'}).status_code,404)
    def test_T09_duplicate_payment_reference(self):
        b=self.confirmed();s.payment(self.users['finance'],b.pk,100,'UNIQUE')
        with self.assertRaises(ValidationError):s.payment(self.users['finance'],b.pk,100,'unique')
        self.assertEqual(Payment.objects.count(),1)
    def test_T10_49_hours_is_three_days(self):
        b=self.confirmed();self.assertEqual(b.invoice.total,Decimal('60000'));self.assertEqual(s.days(b.start,b.end),3)
    def test_T11_extension_conflict(self):
        b=self.confirmed();self.confirmed(start=self.end,end=self.end+timedelta(days=1))
        with self.assertRaises(ValidationError):s.extend(self.users['fleet'],b.pk,self.end+timedelta(hours=2),'Late trip')
    def test_deposit_and_refund_reconcile(self):
        self.v.deposit_required=10000;self.v.save();b=self.paid();pay=s.payment(self.users['finance'],b.pk,10000,'DEP-001','deposit')
        with patch('rental.services.timezone.now',return_value=b.start):s.issue(self.users['fleet'],b.pk,100,80,'Good')
        with patch('rental.services.timezone.now',return_value=b.end):s.return_vehicle(self.users['fleet'],b.pk,250,70,'Good')
        self.assertEqual(b.invoice.paid,60000);self.assertEqual(b.invoice.deposit_held,10000)
        s.refund(self.users['finance'],b.pk,pay.pk,10000,'Deposit released after inspection');s.close(self.users['finance'],b.pk)
        b.refresh_from_db();self.assertEqual(b.status,'closed');self.assertEqual(b.invoice.deposit_held,0)
    def test_over_refund_rejected(self):
        b=self.paid();pay=b.invoice.payments.get();s.cancel(self.users['fleet'],b.pk,'Trip cancelled')
        with self.assertRaises(ValidationError):s.refund(self.users['finance'],b.pk,pay.pk,60001,'Too much')
    def test_cancel_retains_payment_and_credit(self):
        b=self.paid();s.cancel(self.users['requester'],b.pk,'No longer travelling')
        self.assertEqual(b.invoice.total,0);self.assertEqual(b.invoice.balance,-60000);self.assertEqual(Payment.objects.count(),1)
        self.assertFalse(b.allocations.filter(active=True).exists())
    def test_issue_requires_payment(self):
        b=self.confirmed()
        with patch('rental.services.timezone.now',return_value=b.start),self.assertRaises(ValidationError):s.issue(self.users['fleet'],b.pk,0,100,'Good')
    def test_decreasing_mileage_rejected(self):
        b=self.issued()
        with self.assertRaises(ValidationError):s.return_vehicle(self.users['fleet'],b.pk,99,80,'Good')
    def test_disabled_user_cannot_request(self):
        u=self.users['requester'];u.is_active=False;u.save()
        with self.assertRaises(PermissionDenied):self.booking()
    def test_admin_has_no_implicit_fleet_authority(self):
        b=self.booking()
        with self.assertRaises(PermissionDenied):s.confirm(self.users['administrator'],b.pk)
    def test_substitution_retains_history_and_tariff(self):
        b=self.confirmed();v=Vehicle.objects.create(registration='DEMO-002',name='Replacement',category='SUV',daily_rate=50000)
        s.substitute(self.users['fleet'],b.pk,v,'Approved replacement');b.refresh_from_db()
        self.assertEqual(b.rate,20000);self.assertEqual(b.allocations.count(),2);self.assertEqual(b.allocations.filter(active=True).count(),1)
    def test_saved_tariff_survives_vehicle_rate_change(self):
        b=self.confirmed();self.v.daily_rate=99999;self.v.save();s.extend(self.users['fleet'],b.pk,b.end+timedelta(days=1),'Extra day')
        self.assertEqual(b.invoice.total,80000)
    def test_database_trigger_rejects_direct_overlap(self):
        b=self.confirmed();other=Booking.objects.create(user=self.users['requester'],vehicle=self.v,start=self.start,end=self.end,purpose='Direct',contact='demo')
        with self.assertRaises(IntegrityError),transaction.atomic():Allocation.objects.create(vehicle=self.v,booking=other,start=self.start,end=self.end)
    def test_allocation_owner_constraint(self):
        with self.assertRaises(IntegrityError),transaction.atomic():Allocation.objects.create(vehicle=self.v,start=self.start,end=self.end)
    def test_money_rejects_nan_negative_and_subcent(self):
        for value in ['NaN','Infinity','-1','0','1.001']:
            with self.assertRaises(ValidationError):s.money(value)
    def test_csrf_protects_actions(self):
        b=self.booking();c=Client(enforce_csrf_checks=True);c.force_login(self.users['fleet'])
        self.assertEqual(c.post(f'/bookings/{b.pk}/confirm/',{'reason':'valid'}).status_code,403)
    def test_get_action_does_not_mutate(self):
        b=self.booking();self.client.force_login(self.users['fleet']);self.client.get(f'/bookings/{b.pk}/confirm/');b.refresh_from_db();self.assertEqual(b.status,'pending')
    def test_reports_reconcile(self):
        b=self.paid();self.client.force_login(self.users['finance']);r=self.client.get('/reports/');self.assertEqual(r.status_code,200)
        self.assertEqual(r.context['totals']['paid'],60000);self.assertEqual(r.context['totals']['balance'],0)
        self.assertIn(b'60000',self.client.get('/reports/?format=csv').content)
    def test_pages_render_by_role(self):
        b=self.booking()
        cases={'requester':['/','/fleet/','/bookings/',f'/bookings/{b.pk}/','/bookings/new/'],'fleet':['/maintenance/','/fleet/add/','/reports/'],'manager':['/reports/','/audit/'],'administrator':['/accounts/','/audit/'],'finance':['/reports/']}
        for role,urls in cases.items():
            self.client.force_login(self.users[role])
            for url in urls:self.assertEqual(self.client.get(url).status_code,200,(role,url))
    def test_registration_creates_only_requester(self):
        r=self.client.post('/register/',{'username':'newstudent','first_name':'New','last_name':'Student','email':'new@example.test','password1':'N3w-random-Secret!','password2':'N3w-random-Secret!','roles':['administrator']})
        self.assertEqual(r.status_code,302);self.assertEqual(list(User.objects.get(username='newstudent').groups.values_list('name',flat=True)),['requester'])
    def test_login_throttle(self):
        for _ in range(6):r=self.client.post('/login/',{'username':'requester','password':'incorrect'})
        self.assertContains(r,'Too many attempts')
    def test_request_content_is_escaped(self):
        b=self.booking();b.purpose='<script>alert(1)</script>';b.save();self.client.force_login(self.users['requester'])
        r=self.client.get(f'/bookings/{b.pk}/');self.assertContains(r,'&lt;script&gt;');self.assertNotContains(r,'<script>alert(1)</script>')
    def test_unserviceable_vehicle_not_searchable(self):
        self.v.serviceable=False;self.v.save();self.assertNotIn(self.v,s.available(self.start,self.end))
    def test_audit_is_append_only(self):
        b=self.booking();event=AuditEvent.objects.first()
        with self.assertRaises(IntegrityError),transaction.atomic():AuditEvent.objects.filter(pk=event.pk).update(detail='tampered')
    def test_late_return_blocks_next_issue_until_clearance(self):
        b=self.paid();next_b=self.confirmed(start=b.end,end=b.end+timedelta(days=1))
        with patch('rental.services.timezone.now',return_value=b.start):s.issue(self.users['fleet'],b.pk,100,90,'Good')
        s.payment(self.users['finance'],next_b.pk,next_b.invoice.total,'NEXT-RECEIPT')
        with patch('rental.services.timezone.now',return_value=b.end+timedelta(minutes=10)):
            with self.assertRaises(ValidationError):s.issue(self.users['fleet'],next_b.pk,110,90,'Good')
            s.return_vehicle(self.users['fleet'],b.pk,150,80,'Late but inspected')
            s.clear_vehicle(self.users['fleet'],self.v.pk,'Conflict resolved after return')
            s.issue(self.users['fleet'],next_b.pk,150,80,'Good')
        next_b.refresh_from_db();self.assertEqual(next_b.status,'issued')
    def test_cannot_clear_issued_vehicle(self):
        self.issued()
        with self.assertRaises(ValidationError):s.clear_vehicle(self.users['fleet'],self.v.pk,'Unsafe attempt')
    def test_expired_maintenance_requires_release_for_issue(self):
        b=self.paid()
        s.schedule_maintenance(self.users['fleet'],self.v,self.start-timedelta(days=1),self.start-timedelta(hours=1),'Service')
        with patch('rental.services.timezone.now',return_value=b.start),self.assertRaises(ValidationError):s.issue(self.users['fleet'],b.pk,100,90,'Good')
    def test_database_update_overlap_rejected(self):
        b=self.confirmed();other=self.confirmed(start=self.end,end=self.end+timedelta(days=1))
        with self.assertRaises(IntegrityError),transaction.atomic():other.allocations.update(start=self.start)

@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DatabaseTests(Setup,TransactionTestCase):
    reset_sequences=True
    def test_T05_two_concurrent_confirmations(self):
        a=self.booking();b=self.booking();gate=Barrier(2)
        def run(pk):
            connections.close_all();u=User.objects.get(pk=self.users['fleet'].pk);gate.wait()
            try:s.confirm(u,pk);return 'confirmed'
            except ValidationError:return 'conflict'
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(run,[a.pk,b.pk]))
        self.assertCountEqual(result,['confirmed','conflict']);self.assertEqual(Allocation.objects.filter(active=True).count(),1)
    def test_T12_backup_restore_reconciliation(self):
        b=self.paid();connection.close()
        original=sqlite3.connect(str(connection.settings_dict['NAME']))
        with tempfile.TemporaryDirectory() as temp:
            backup=sqlite3.connect(str(Path(temp)/'backup.sqlite3'));original.backup(backup)
            restored=sqlite3.connect(str(Path(temp)/'restored.sqlite3'));backup.backup(restored)
            for table in ['rental_booking','rental_payment','rental_charge','rental_auditevent']:
                self.assertEqual(original.execute(f'SELECT * FROM {table} ORDER BY id').fetchall(),restored.execute(f'SELECT * FROM {table} ORDER BY id').fetchall())
            self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0],'ok');backup.close();restored.close()
        original.close()
