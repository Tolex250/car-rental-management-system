from datetime import timedelta
from decimal import Decimal, InvalidOperation
from math import ceil
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.contrib.auth.models import Group
from .models import *
ROLES=['requester','fleet','finance','manager','administrator']
def has_role(user,*roles):
    return user.is_authenticated and user.is_active and user.groups.filter(name__in=roles).exists()
def require(user,*roles):
    if not has_role(user,*roles): raise PermissionDenied('Your role cannot perform this action.')
def log(user,action,obj,detail):
    return AuditEvent.objects.create(actor=user,action=action,record=f'{type(obj).__name__}:{obj.pk}',detail=str(detail))
def money(value):
    try: result=Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError): raise ValidationError('Enter a valid monetary amount.')
    if not result.is_finite() or result<=0 or result.as_tuple().exponent < -2 or result>Decimal('9999999999.99'): raise ValidationError('Amount must be positive, with at most two decimal places.')
    return result
def interval(start,end):
    if not start or not end or end<=start: raise ValidationError('Return time must be after collection time.')
def days(start,end):
    interval(start,end)
    return max(1,ceil((end-start).total_seconds()/86400))
def reason(value):
    if not str(value).strip(): raise ValidationError('A reason or supporting reference is required.')
    return str(value).strip()
def available(start,end):
    interval(start,end)
    result=[]
    for v in Vehicle.objects.filter(serviceable=True,awaiting_clearance=False):
        blocked_end=end+timedelta(minutes=v.turnaround_minutes)
        if not Allocation.objects.filter(vehicle=v,active=True,start__lt=blocked_end,end__gt=start).exists(): result.append(v)
    return result
def free(vehicle,start,end,exclude=None):
    interval(start,end)
    if not vehicle.serviceable or vehicle.awaiting_clearance: raise ValidationError('Vehicle is unavailable or awaiting inspection clearance.')
    q=Allocation.objects.filter(vehicle=vehicle,active=True,start__lt=end,end__gt=start)
    if exclude: q=q.exclude(booking=exclude)
    if q.exists(): raise ValidationError('This vehicle has a conflicting rental or maintenance allocation.')
@transaction.atomic
def request_booking(user,vehicle,start,end,purpose,contact):
    require(user,'requester');interval(start,end)
    if start<timezone.now(): raise ValidationError('Collection must be in the future.')
    v=Vehicle.objects.get(pk=vehicle.pk)
    free(v,start,end+timedelta(minutes=v.turnaround_minutes))
    b=Booking.objects.create(user=user,vehicle=v,start=start,end=end,purpose=reason(purpose),contact=reason(contact))
    log(user,'request',b,f'{start.isoformat()} to {end.isoformat()}');return b
@transaction.atomic
def confirm(user,pk):
    require(user,'fleet');b=Booking.objects.select_for_update().get(pk=pk);v=Vehicle.objects.select_for_update().get(pk=b.vehicle_id)
    if b.status!='pending' or not b.user.is_active: raise ValidationError('Only pending requests from active users can be confirmed.')
    if b.start<timezone.now(): raise ValidationError('The requested collection time has passed.')
    block_end=b.end+timedelta(minutes=v.turnaround_minutes);free(v,b.start,block_end)
    Allocation.objects.create(vehicle=v,booking=b,start=b.start,end=block_end)
    b.rate=v.daily_rate;b.buffer_minutes=v.turnaround_minutes;b.deposit_required=v.deposit_required;b.status='confirmed';b.approved_by=user;b.approved_at=timezone.now();b.save()
    inv=Invoice.objects.create(booking=b);Charge.objects.create(invoice=inv,description=f'{days(b.start,b.end)} daily units at NGN {b.rate}',amount=days(b.start,b.end)*b.rate)
    log(user,'confirm',b,f'Rate {b.rate}; buffer {b.buffer_minutes} minutes; deposit {b.deposit_required}');return b
@transaction.atomic
def cancel(user,pk,note,reject=False):
    b=Booking.objects.get(pk=pk)
    if reject: require(user,'fleet')
    elif not has_role(user,'fleet') and not (has_role(user,'requester') and b.user_id==user.pk): raise PermissionDenied
    if b.status not in ('pending','confirmed') or (reject and b.status!='pending'): raise ValidationError('This booking cannot be cancelled or rejected at its current stage.')
    note=reason(note);b.status='rejected' if reject else 'cancelled';b.save()
    b.allocations.filter(active=True).update(active=False)
    if hasattr(b,'invoice'):
        total=b.invoice.total
        if total: Charge.objects.create(invoice=b.invoice,description='Cancellation credit: '+note,amount=-total)
    log(user,b.status,b,note)
@transaction.atomic
def payment(user,pk,amount,reference,kind='rental'):
    require(user,'finance');b=Booking.objects.get(pk=pk)
    if b.status not in ('confirmed','issued','returned'): raise ValidationError('Payments require an active confirmed rental.')
    amount=money(amount);reference=reason(reference).upper()
    if kind not in ('rental','deposit'): raise ValidationError('Invalid payment category.')
    limit=b.invoice.balance if kind=='rental' else b.deposit_required-b.invoice.deposit_held
    if amount>limit: raise ValidationError('Payment exceeds the outstanding amount for this category.')
    if Payment.objects.filter(reference=reference).exists(): raise ValidationError('This verified payment reference already exists.')
    receipt=Payment.objects.create(invoice=b.invoice,amount=amount,reference=reference,kind=kind,recorded_by=user)
    log(user,'payment',b,f'{kind}: {amount}; reference {reference}');return receipt
@transaction.atomic
def refund(user,pk,payment_id,amount,note):
    require(user,'finance');b=Booking.objects.get(pk=pk);p=Payment.objects.get(pk=payment_id,invoice__booking=b)
    amount=money(amount);note=reason(note)
    already=sum((r.amount for r in p.refunds.all()),Decimal('0'))
    if amount>p.amount-already: raise ValidationError('Refund exceeds the unrefunded receipt amount.')
    if p.kind=='deposit' and b.status not in ('returned','closed','cancelled'): raise ValidationError('Return or cancel the rental before refunding the deposit.')
    # A refund must not reopen a closed invoice or create unapproved debt.
    if p.kind=='rental' and amount>max(Decimal('0'),-b.invoice.balance): raise ValidationError('Rental refunds require a cancellation credit or overpayment.')
    r=Refund.objects.create(payment=p,amount=amount,reason=note,recorded_by=user);log(user,'refund',b,f'{amount}; receipt {p.pk}; {note}');return r
@transaction.atomic
def add_charge(user,pk,amount,note):
    require(user,'finance');b=Booking.objects.get(pk=pk)
    if b.status not in ('confirmed','issued','returned'): raise ValidationError('Charges require an active rental.')
    amount=money(amount);note=reason(note)
    Charge.objects.create(invoice=b.invoice,description=note,amount=amount);log(user,'additional charge',b,f'{amount}: {note}')
def readings(v,odometer,fuel,condition):
    if odometer<v.odometer or not 0<=fuel<=100: raise ValidationError('Mileage cannot decrease and fuel must be 0–100%.')
    return reason(condition)
@transaction.atomic
def issue(user,pk,odometer,fuel,condition):
    require(user,'fleet');b=Booking.objects.get(pk=pk);v=Vehicle.objects.get(pk=b.vehicle_id);now=timezone.now()
    if b.status!='confirmed': raise ValidationError('Only confirmed bookings can be issued.')
    if not (b.start<=now<b.end): raise ValidationError('Issue is only allowed within the confirmed rental period.')
    if b.invoice.balance>0 or b.invoice.deposit_held<b.deposit_required: raise ValidationError('Settle the invoice and required deposit before issue.')
    if not v.serviceable or v.awaiting_clearance or Booking.objects.filter(vehicle=v,status='issued').exists(): raise ValidationError('The vehicle is not physically cleared for issue.')
    if Maintenance.objects.filter(vehicle=v,active=True,start__lte=now).exists(): raise ValidationError('Vehicle has maintenance awaiting clearance.')
    if Allocation.objects.filter(vehicle=v,active=True,start__lte=now,end__gt=now).exclude(booking=b).exists(): raise ValidationError('Vehicle is still blocked by another allocation or turnaround.')
    condition=readings(v,odometer,fuel,condition)
    Inspection.objects.create(booking=b,vehicle=v,kind='issue',odometer=odometer,fuel=fuel,condition=condition,recorded_by=user)
    v.odometer=odometer;v.awaiting_clearance=True;v.save();b.status='issued';b.actual_issue=now;b.save();log(user,'issue',b,condition)
@transaction.atomic
def return_vehicle(user,pk,odometer,fuel,condition,serviceable=True):
    require(user,'fleet');b=Booking.objects.get(pk=pk);v=Vehicle.objects.get(pk=b.vehicle_id)
    if b.status!='issued': raise ValidationError('Only issued vehicles can be returned.')
    condition=readings(v,odometer,fuel,condition)
    Inspection.objects.create(booking=b,vehicle=v,kind='return',odometer=odometer,fuel=fuel,condition=condition,recorded_by=user)
    b.actual_return=timezone.now();b.status='returned';b.save()
    v.odometer=odometer;v.serviceable=serviceable;v.awaiting_clearance=False;v.save()
    b.allocations.filter(active=True).update(active=False)
    # Block the physical turnaround after actual return. Existing future bookings
    # that conflict remain visible and cannot issue while clearance is pending.
    end=b.actual_return+timedelta(minutes=b.buffer_minutes)
    conflicts=Allocation.objects.filter(vehicle=v,active=True,start__lt=end,end__gt=b.actual_return)
    if conflicts.exists():
        v.awaiting_clearance=True;v.save();log(user,'return conflict',b,'Future commitment conflicts with actual return/turnaround. Resolve before clearing vehicle.')
    elif b.buffer_minutes:
        Allocation.objects.create(vehicle=v,booking=b,start=b.actual_return,end=end)
    log(user,'return',b,f'{condition}; serviceable={serviceable}')
@transaction.atomic
def close(user,pk):
    require(user,'finance');b=Booking.objects.get(pk=pk)
    if b.status!='returned' or b.invoice.balance!=0 or b.invoice.deposit_held!=0: raise ValidationError('Close only returned rentals with zero invoice balance and no deposit held.')
    b.status='closed';b.save();log(user,'close',b,'Invoice settled and deposit reconciled.')
@transaction.atomic
def extend(user,pk,end,note):
    require(user,'fleet');b=Booking.objects.get(pk=pk);v=Vehicle.objects.get(pk=b.vehicle_id)
    if b.status not in ('confirmed','issued') or end<=b.end: raise ValidationError('An extension must increase the end of a confirmed or issued rental.')
    note=reason(note);new_end=end+timedelta(minutes=b.buffer_minutes)
    if Allocation.objects.filter(vehicle=v,active=True,start__lt=new_end,end__gt=b.start).exclude(booking=b).exists(): raise ValidationError('Extension conflicts with another allocation.')
    extra=(days(b.start,end)-days(b.start,b.end))*b.rate
    b.allocations.filter(active=True).update(end=new_end)
    if extra: Charge.objects.create(invoice=b.invoice,description='Extension: '+note,amount=extra)
    b.end=end;b.save();log(user,'extend',b,f'{end.isoformat()}; {note}')
@transaction.atomic
def substitute(user,pk,vehicle,note):
    require(user,'fleet');b=Booking.objects.get(pk=pk);v=Vehicle.objects.get(pk=vehicle.pk)
    if b.status!='confirmed' or v.pk==b.vehicle_id: raise ValidationError('Choose another vehicle for a confirmed, unissued booking.')
    note=reason(note);buffer=max(b.buffer_minutes,v.turnaround_minutes);end=b.end+timedelta(minutes=buffer);free(v,b.start,end)
    b.allocations.filter(active=True).update(active=False)
    old=b.vehicle.registration;b.vehicle=v;b.buffer_minutes=buffer;b.save()
    Allocation.objects.create(vehicle=v,booking=b,start=b.start,end=end)
    log(user,'substitute',b,f'{old} to {v.registration}; preserved agreed tariff; {note}')
@transaction.atomic
def schedule_maintenance(user,vehicle,start,end,note):
    require(user,'fleet');interval(start,end);note=reason(note);v=Vehicle.objects.get(pk=vehicle.pk)
    if end<=timezone.now(): raise ValidationError('Maintenance end must be in the future.')
    if Booking.objects.filter(vehicle=v,status='issued').exists(): raise ValidationError('Return the issued vehicle before scheduling maintenance.')
    if Allocation.objects.filter(vehicle=v,active=True,start__lt=end,end__gt=start).exists(): raise ValidationError('Maintenance conflicts with an active allocation.')
    m=Maintenance.objects.create(vehicle=v,start=start,end=end,reason=note,created_by=user)
    Allocation.objects.create(vehicle=v,maintenance=m,start=start,end=end);log(user,'maintenance',m,note);return m
@transaction.atomic
def release_maintenance(user,pk,note):
    require(user,'fleet');m=Maintenance.objects.get(pk=pk)
    if not m.active: raise ValidationError('Maintenance is already released.')
    m.active=False;m.save();Allocation.objects.filter(maintenance=m,active=True).update(active=False);log(user,'release maintenance',m,reason(note))

@transaction.atomic
def clear_vehicle(user,pk,note):
    require(user,'fleet');v=Vehicle.objects.get(pk=pk);now=timezone.now();note=reason(note)
    if Booking.objects.filter(vehicle=v,status='issued').exists(): raise ValidationError('An issued booking still holds this vehicle.')
    if Maintenance.objects.filter(vehicle=v,active=True,start__lte=now).exists(): raise ValidationError('Release the outstanding maintenance first.')
    for b in Booking.objects.filter(vehicle=v,actual_return__isnull=False):
        if b.actual_return+timedelta(minutes=b.buffer_minutes)>now: raise ValidationError('The return turnaround period has not finished.')
    v.awaiting_clearance=False;v.save();log(user,'vehicle clearance',v,note)
