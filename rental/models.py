from django.conf import settings
from django.db import models
from django.db.models import Q,F
from django.core.validators import MinValueValidator
from decimal import Decimal

class Vehicle(models.Model):
    registration=models.CharField(max_length=25,unique=True)
    name=models.CharField(max_length=100)
    category=models.CharField(max_length=40)
    seats=models.PositiveSmallIntegerField(default=5,validators=[MinValueValidator(1)])
    daily_rate=models.DecimalField(max_digits=12,decimal_places=2,validators=[MinValueValidator(Decimal('0.01'))])
    turnaround_minutes=models.PositiveIntegerField(default=30)
    deposit_required=models.DecimalField(max_digits=12,decimal_places=2,default=0,validators=[MinValueValidator(0)])
    serviceable=models.BooleanField(default=True)
    awaiting_clearance=models.BooleanField(default=False)
    odometer=models.PositiveIntegerField(default=0)
    def __str__(self): return f'{self.registration} · {self.name}'
    class Meta:
        ordering=['registration']
        constraints=[models.CheckConstraint(condition=Q(daily_rate__gt=0)&Q(deposit_required__gte=0)&Q(seats__gt=0),name='valid_vehicle_values')]

class Booking(models.Model):
    STATES=[(x,x.replace('_',' ').title()) for x in ['pending','confirmed','issued','returned','closed','cancelled','rejected']]
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    vehicle=models.ForeignKey(Vehicle,on_delete=models.PROTECT)
    start=models.DateTimeField()
    end=models.DateTimeField()
    purpose=models.CharField(max_length=300)
    contact=models.CharField(max_length=100)
    status=models.CharField(max_length=15,choices=STATES,default='pending')
    rate=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    buffer_minutes=models.PositiveIntegerField(default=0)
    deposit_required=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    approved_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.PROTECT,related_name='approvals')
    approved_at=models.DateTimeField(null=True,blank=True)
    actual_issue=models.DateTimeField(null=True,blank=True)
    actual_return=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    def __str__(self): return f'CR-{self.pk:05d}' if self.pk else 'New booking'
    class Meta:
        ordering=['-created_at']
        constraints=[models.CheckConstraint(condition=Q(end__gt=F('start')),name='booking_positive_interval')]

class Maintenance(models.Model):
    vehicle=models.ForeignKey(Vehicle,on_delete=models.PROTECT)
    start=models.DateTimeField()
    end=models.DateTimeField()
    reason=models.CharField(max_length=300)
    active=models.BooleanField(default=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    class Meta:
        constraints=[models.CheckConstraint(condition=Q(end__gt=F('start')),name='maintenance_positive_interval')]

class Allocation(models.Model):
    vehicle=models.ForeignKey(Vehicle,on_delete=models.PROTECT)
    booking=models.ForeignKey(Booking,null=True,blank=True,on_delete=models.PROTECT,related_name='allocations')
    maintenance=models.ForeignKey(Maintenance,null=True,blank=True,on_delete=models.PROTECT)
    start=models.DateTimeField()
    end=models.DateTimeField()
    active=models.BooleanField(default=True)
    class Meta:
        constraints=[models.CheckConstraint(condition=Q(end__gt=F('start')),name='allocation_positive_interval'),models.CheckConstraint(condition=(Q(booking__isnull=False,maintenance__isnull=True)|Q(booking__isnull=True,maintenance__isnull=False)),name='allocation_one_owner'),models.UniqueConstraint(fields=['booking'],condition=Q(active=True,booking__isnull=False),name='one_active_booking_allocation')]
        indexes=[models.Index(fields=['vehicle','active','start','end'])]

class Invoice(models.Model):
    booking=models.OneToOneField(Booking,on_delete=models.PROTECT,related_name='invoice')
    created_at=models.DateTimeField(auto_now_add=True)
    @property
    def total(self): return sum((x.amount for x in self.lines.all()),Decimal('0.00'))
    @property
    def paid(self): return sum((x.amount for x in self.payments.filter(kind='rental')),Decimal('0.00'))
    @property
    def refunded(self): return sum((x.amount for x in Refund.objects.filter(payment__invoice=self,payment__kind='rental')),Decimal('0.00'))
    @property
    def balance(self): return self.total-self.paid+self.refunded
    @property
    def deposit_held(self):
        return sum((x.amount for x in self.payments.filter(kind='deposit')),Decimal('0.00'))-sum((x.amount for x in Refund.objects.filter(payment__invoice=self,payment__kind='deposit')),Decimal('0.00'))

class Charge(models.Model):
    invoice=models.ForeignKey(Invoice,on_delete=models.PROTECT,related_name='lines')
    description=models.CharField(max_length=300)
    amount=models.DecimalField(max_digits=12,decimal_places=2)
    created_at=models.DateTimeField(auto_now_add=True)

class Payment(models.Model):
    invoice=models.ForeignKey(Invoice,on_delete=models.PROTECT,related_name='payments')
    amount=models.DecimalField(max_digits=12,decimal_places=2)
    reference=models.CharField(max_length=100,unique=True)
    kind=models.CharField(max_length=10,choices=[('rental','Rental'),('deposit','Deposit')],default='rental')
    recorded_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.CheckConstraint(condition=Q(amount__gt=0),name='payment_positive')]

class Refund(models.Model):
    payment=models.ForeignKey(Payment,on_delete=models.PROTECT,related_name='refunds')
    amount=models.DecimalField(max_digits=12,decimal_places=2)
    reason=models.CharField(max_length=300)
    recorded_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.CheckConstraint(condition=Q(amount__gt=0),name='refund_positive')]

class Inspection(models.Model):
    booking=models.ForeignKey(Booking,on_delete=models.PROTECT,related_name='inspections')
    vehicle=models.ForeignKey(Vehicle,on_delete=models.PROTECT)
    kind=models.CharField(max_length=10,choices=[('issue','Issue'),('return','Return')])
    odometer=models.PositiveIntegerField()
    fuel=models.PositiveSmallIntegerField()
    condition=models.CharField(max_length=500)
    recorded_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['booking','kind'],name='one_inspection_per_stage'),models.CheckConstraint(condition=Q(fuel__lte=100),name='fuel_percent')]

class AuditEvent(models.Model):
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True)
    action=models.CharField(max_length=80)
    record=models.CharField(max_length=100)
    detail=models.TextField()
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=['-id']

class LoginAttempt(models.Model):
    key=models.CharField(max_length=64,unique=True)
    failures=models.PositiveIntegerField(default=0)
    started=models.DateTimeField()
