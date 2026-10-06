from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Vehicle
from . import services as s
class RegisterForm(UserCreationForm):
    email=forms.EmailField(required=True)
    first_name=forms.CharField(max_length=150,required=True)
    last_name=forms.CharField(max_length=150,required=True)
    class Meta:
        model=User
        fields=['username','first_name','last_name','email','password1','password2']
class PeriodForm(forms.Form):
    start=forms.DateTimeField(label='Collection time (Lagos)',widget=forms.DateTimeInput(attrs={'type':'datetime-local'}))
    end=forms.DateTimeField(label='Return time (Lagos)',widget=forms.DateTimeInput(attrs={'type':'datetime-local'}))
    def clean(self):
        data=super().clean()
        if data.get('start') and data.get('end'): s.interval(data['start'],data['end'])
        return data
class BookingForm(PeriodForm):
    vehicle=forms.ModelChoiceField(queryset=Vehicle.objects.filter(serviceable=True))
    purpose=forms.CharField(max_length=300,widget=forms.Textarea(attrs={'rows':3}))
    contact=forms.CharField(max_length=100,label='Contact phone or email')
class VehicleForm(forms.ModelForm):
    class Meta:
        model=Vehicle
        fields=['registration','name','category','seats','daily_rate','turnaround_minutes','deposit_required','serviceable']
class MaintenanceForm(PeriodForm):
    vehicle=forms.ModelChoiceField(queryset=Vehicle.objects.all())
    reason=forms.CharField(max_length=300,widget=forms.Textarea(attrs={'rows':3}))
class ReasonForm(forms.Form):
    reason=forms.CharField(max_length=300,widget=forms.Textarea(attrs={'rows':3}))
class PaymentForm(forms.Form):
    amount=forms.DecimalField(max_digits=12,decimal_places=2,min_value=0.01)
    reference=forms.CharField(max_length=100,label='Verified receipt / bank reference')
    kind=forms.ChoiceField(choices=[('rental','Rental payment'),('deposit','Refundable deposit')])
class RefundForm(ReasonForm):
    payment=forms.ModelChoiceField(queryset=None)
    amount=forms.DecimalField(max_digits=12,decimal_places=2,min_value=0.01)
    def __init__(self,*args,booking,**kwargs):
        super().__init__(*args,**kwargs)
        from .models import Payment
        self.fields['payment'].queryset=Payment.objects.filter(invoice__booking=booking)
        self.fields['payment'].label_from_instance=lambda p:f'{p.reference} — {p.kind}, NGN {p.amount}'
class InspectionForm(forms.Form):
    odometer=forms.IntegerField(min_value=0,label='Odometer (km)')
    fuel=forms.IntegerField(min_value=0,max_value=100,label='Fuel (%)')
    condition=forms.CharField(max_length=500,widget=forms.Textarea(attrs={'rows':3}))
class ReturnForm(InspectionForm):
    serviceable=forms.BooleanField(required=False,initial=True,label='Vehicle passed inspection and is serviceable')
class ExtendForm(ReasonForm):
    end=forms.DateTimeField(widget=forms.DateTimeInput(attrs={'type':'datetime-local'}),label='New return time (Lagos)')
class SubstituteForm(ReasonForm):
    vehicle=forms.ModelChoiceField(queryset=Vehicle.objects.filter(serviceable=True))
class ChargeForm(ReasonForm):
    amount=forms.DecimalField(max_digits=12,decimal_places=2,min_value=0.01)
class AccountForm(forms.Form):
    roles=forms.MultipleChoiceField(choices=[(r,r.title()) for r in s.ROLES],widget=forms.CheckboxSelectMultiple)
    is_active=forms.BooleanField(required=False)
    reason=forms.CharField(max_length=300)
class ReportForm(forms.Form):
    start=forms.DateField(required=False,widget=forms.DateInput(attrs={'type':'date'}))
    end=forms.DateField(required=False,widget=forms.DateInput(attrs={'type':'date'}))
    def clean(self):
        d=super().clean()
        if d.get('start') and d.get('end') and d['end']<d['start']: raise forms.ValidationError('End date must follow start date.')
        return d
