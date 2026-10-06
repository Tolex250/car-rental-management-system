import csv, hashlib
from datetime import timedelta
from decimal import Decimal
from django.shortcuts import render,redirect,get_object_or_404
from django.http import HttpResponse,HttpResponseNotAllowed
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User,Group
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction,IntegrityError,OperationalError
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import *
from .forms import *
from . import services as s

def role_context(request):
    return {'can_fleet':s.has_role(request.user,'fleet'),'can_finance':s.has_role(request.user,'finance'),'can_request':s.has_role(request.user,'requester'),'can_report':s.has_role(request.user,'manager','finance','fleet'),'can_admin':s.has_role(request.user,'administrator'),'can_audit':s.has_role(request.user,'manager','administrator')}
def signin(request):
    if request.user.is_authenticated:return redirect('dashboard')
    form=AuthenticationForm(request,data=request.POST or None)
    if request.method=='POST':
        key=hashlib.sha256((request.META.get('REMOTE_ADDR','')+'|'+request.POST.get('username','').lower()).encode()).hexdigest()
        now=timezone.now()
        with transaction.atomic():
            attempt,_=LoginAttempt.objects.get_or_create(key=key,defaults={'started':now})
            if now-attempt.started>timedelta(minutes=15):attempt.failures=0;attempt.started=now
            if attempt.failures>=5:
                form.add_error(None,'Too many attempts. Try again after 15 minutes.')
            elif form.is_valid():
                attempt.delete();login(request,form.get_user());return redirect('dashboard')
            else:attempt.failures+=1
            attempt.save()
    return render(request,'form.html',{'form':form,'title':'Welcome back','subtitle':'Sign in to manage your rental activity.','button':'Sign in','register_link':True})
def register(request):
    form=RegisterForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            u=form.save();u.groups.add(Group.objects.get_or_create(name='requester')[0]);s.log(u,'register',u,'Requester account created.')
        login(request,u);return redirect('dashboard')
    return render(request,'form.html',{'form':form,'title':'Create your account','subtitle':'New accounts can submit rental requests.','button':'Register'})
def visible(user):
    q=Booking.objects.select_related('vehicle','user')
    if s.has_role(user,'fleet','finance','manager'):return q
    return q.filter(user=user)
@login_required
def dashboard(request):
    q=visible(request.user)
    return render(request,'dashboard.html',{'recent':q[:6],'pending':q.filter(status='pending').count(),'active':q.filter(status__in=['confirmed','issued']).count(),'completed':q.filter(status='closed').count(),'vehicles':Vehicle.objects.count()})
@login_required
def fleet(request):
    form=PeriodForm(request.GET or None);cars=Vehicle.objects.all();searched=False
    if request.GET and form.is_valid():cars=s.available(**form.cleaned_data);searched=True
    return render(request,'fleet.html',{'cars':cars,'form':form,'searched':searched})
@login_required
def vehicle_add(request):
    s.require(request.user,'fleet');form=VehicleForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():v=form.save();s.log(request.user,'add vehicle',v,v.registration)
        return redirect('fleet')
    return render(request,'form.html',{'form':form,'title':'Add a vehicle','button':'Save vehicle'})
@login_required
def vehicle_edit(request,pk):
    s.require(request.user,'fleet');v=get_object_or_404(Vehicle,pk=pk);form=VehicleForm(request.POST or None,instance=v)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():v=form.save();s.log(request.user,'update vehicle',v,', '.join(form.changed_data))
        return redirect('fleet')
    return render(request,'form.html',{'form':form,'title':f'Edit {v.registration}','button':'Save changes'})
@login_required
def vehicle_clear(request,pk):
    s.require(request.user,'fleet');v=get_object_or_404(Vehicle,pk=pk);form=ReasonForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:s.clear_vehicle(request.user,pk,form.cleaned_data['reason']);return redirect('fleet')
        except ValidationError as e:form.add_error(None,error(e))
    return render(request,'form.html',{'form':form,'title':f'Clear {v.registration}','subtitle':'Confirm inspection and resolution of any late-return conflict.','button':'Record clearance'})
@login_required
def bookings(request):return render(request,'bookings.html',{'bookings':visible(request.user),'title':'Bookings'})
@login_required
def booking_new(request):
    s.require(request.user,'requester');form=BookingForm(request.POST or None,initial={'vehicle':request.GET.get('vehicle')})
    if request.method=='POST' and form.is_valid():
        try:b=s.request_booking(request.user,**form.cleaned_data);messages.success(request,'Request submitted. It is not reserved until confirmed.');return redirect('booking_detail',pk=b.pk)
        except (ValidationError,IntegrityError,OperationalError) as e:form.add_error(None,error(e))
    return render(request,'form.html',{'form':form,'title':'Request a vehicle','subtitle':'All times use Africa/Lagos. Availability is checked again at confirmation.','button':'Submit request'})
def error(e):return ' '.join(e.messages) if isinstance(e,ValidationError) else 'The operation could not complete because a conflicting record or database write exists. Refresh and try again.'
@login_required
def booking_detail(request,pk):
    b=get_object_or_404(visible(request.user),pk=pk)
    return render(request,'detail.html',{'b':b,'invoice':getattr(b,'invoice',None),'events':AuditEvent.objects.filter(record=f'Booking:{pk}'),'refunds':Refund.objects.filter(payment__invoice__booking=b)})
@login_required
def booking_action(request,pk,action):
    b=get_object_or_404(visible(request.user),pk=pk)
    fleet_actions=['confirm','reject','issue','return','extend','substitute']
    finance_actions=['payment','refund','charge','close']
    if action in fleet_actions:s.require(request.user,'fleet')
    elif action in finance_actions:s.require(request.user,'finance')
    elif action=='cancel':
        if not s.has_role(request.user,'fleet') and not (s.has_role(request.user,'requester') and b.user_id==request.user.pk):raise PermissionDenied
    else:return HttpResponse(status=404)
    classes={'confirm':ReasonForm,'reject':ReasonForm,'cancel':ReasonForm,'payment':PaymentForm,'refund':RefundForm,'charge':ChargeForm,'issue':InspectionForm,'return':ReturnForm,'extend':ExtendForm,'substitute':SubstituteForm,'close':ReasonForm}
    kwargs={'booking':b} if action=='refund' else {}
    form=classes[action](request.POST or None,**kwargs)
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        try:
            with transaction.atomic():
                if action=='confirm':s.confirm(request.user,pk);s.log(request.user,'approval reason',b,d['reason'])
                elif action in ('cancel','reject'):s.cancel(request.user,pk,d['reason'],reject=action=='reject')
                elif action=='payment':s.payment(request.user,pk,**d)
                elif action=='refund':s.refund(request.user,pk,d['payment'].pk,d['amount'],d['reason'])
                elif action=='charge':s.add_charge(request.user,pk,d['amount'],d['reason'])
                elif action=='issue':s.issue(request.user,pk,**d)
                elif action=='return':s.return_vehicle(request.user,pk,**d)
                elif action=='extend':s.extend(request.user,pk,d['end'],d['reason'])
                elif action=='substitute':s.substitute(request.user,pk,d['vehicle'],d['reason'])
                elif action=='close':s.close(request.user,pk);s.log(request.user,'closure reason',b,d['reason'])
            messages.success(request,'Operation recorded successfully.');return redirect('booking_detail',pk=pk)
        except (ValidationError,IntegrityError,OperationalError) as e:form.add_error(None,error(e))
    return render(request,'form.html',{'form':form,'title':f'{action.title()} {b}','subtitle':'This action is recorded in the audit trail.','button':action.title()})
@login_required
def maintenance(request):
    s.require(request.user,'fleet');form=MaintenanceForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        try:s.schedule_maintenance(request.user,d['vehicle'],d['start'],d['end'],d['reason']);return redirect('maintenance')
        except (ValidationError,IntegrityError,OperationalError) as e:form.add_error(None,error(e))
    return render(request,'maintenance.html',{'form':form,'items':Maintenance.objects.select_related('vehicle').order_by('-id')})
@login_required
def maintenance_release(request,pk):
    s.require(request.user,'fleet');form=ReasonForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:s.release_maintenance(request.user,pk,form.cleaned_data['reason']);return redirect('maintenance')
        except ValidationError as e:form.add_error(None,error(e))
    return render(request,'form.html',{'form':form,'title':'Release maintenance block','button':'Record clearance'})
@login_required
def audit(request):
    s.require(request.user,'manager','administrator')
    return render(request,'audit.html',{'events':AuditEvent.objects.select_related('actor')[:300]})
@login_required
def accounts(request):
    s.require(request.user,'administrator');return render(request,'accounts.html',{'accounts':User.objects.prefetch_related('groups').order_by('username')})
@login_required
def account_edit(request,pk):
    s.require(request.user,'administrator');u=get_object_or_404(User,pk=pk)
    form=AccountForm(request.POST or None,initial={'roles':list(u.groups.values_list('name',flat=True)),'is_active':u.is_active})
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        if u.pk==request.user.pk and (not d['is_active'] or 'administrator' not in d['roles']):form.add_error(None,'You cannot remove your own administrator access.')
        else:
            with transaction.atomic():
                u.groups.set([Group.objects.get_or_create(name=r)[0] for r in d['roles']]);u.is_active=d['is_active'];u.save();s.log(request.user,'account roles',u,f"{d['roles']}; active={u.is_active}; {d['reason']}")
            return redirect('accounts')
    return render(request,'form.html',{'form':form,'title':f'Access for {u.username}','button':'Update access'})
@login_required
def reports(request):
    s.require(request.user,'manager','finance','fleet');form=ReportForm(request.GET or None);q=Booking.objects.select_related('vehicle','user').all()
    if request.GET and form.is_valid():
        d=form.cleaned_data
        if d['start']:q=q.filter(created_at__date__gte=d['start'])
        if d['end']:q=q.filter(created_at__date__lte=d['end'])
    valid=not request.GET or form.is_valid()
    entries=[];totals={k:Decimal('0') for k in ['invoiced','paid','refunded','balance','deposits']}
    if valid:
        for b in q:
            inv=getattr(b,'invoice',None)
            row={'booking':b,'invoiced':inv.total if inv else 0,'paid':inv.paid if inv else 0,'refunded':inv.refunded if inv else 0,'balance':inv.balance if inv else 0,'deposits':inv.deposit_held if inv else 0}
            for k in totals:totals[k]+=row[k]
            entries.append(row)
    if request.GET.get('format')=='csv' and valid:
        response=HttpResponse(content_type='text/csv');response['Content-Disposition']='attachment; filename="rental-report.csv"'
        writer=csv.writer(response);writer.writerow(['Booking','Status','Invoiced NGN','Paid NGN','Refunded NGN','Balance NGN','Deposit held NGN'])
        for r in entries:writer.writerow([str(r['booking']),r['booking'].status]+[r[k] for k in totals])
        writer.writerow(['TOTAL','']+list(totals.values()));return response
    return render(request,'reports.html',{'form':form,'entries':entries,'totals':totals})
