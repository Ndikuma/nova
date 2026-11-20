from django import forms

from .models import EBMSConfiguration, EBMSProductMapping


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault('class', 'checkbox-input')
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault('class', 'select-input')
            elif isinstance(widget, forms.Textarea):
                widget.attrs.setdefault('class', 'textarea-input')
                widget.attrs.setdefault('rows', 3)
            else:
                widget.attrs.setdefault('class', 'text-input')


class EBMSConfigurationForm(StyledModelForm):
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False, attrs={
            'autocomplete': 'new-password',
            'placeholder': 'Laisser vide pour conserver le mot de passe',
        }),
    )

    class Meta:
        model = EBMSConfiguration
        exclude = ('created_at', 'updated_at')
        widgets = {'activity_sector': forms.Textarea(attrs={'rows': 2})}

    def clean_password(self):
        password = self.cleaned_data.get('password', '')
        if not password and self.instance and self.instance.pk:
            return self.instance.password
        return password


class EBMSProductMappingForm(StyledModelForm):
    class Meta:
        model = EBMSProductMapping
        exclude = ('verified_by', 'verified_at', 'created_at', 'updated_at')
        widgets = {'notes': forms.Textarea(attrs={'rows': 3})}

    def save(self, commit=True, user=None):
        from django.utils import timezone
        obj = super().save(commit=False)
        if obj.ready and user:
            obj.verified_by = user
            obj.verified_at = timezone.now()
        if commit:
            obj.save()
        return obj


class TINCheckForm(forms.Form):
    tin = forms.CharField(
        max_length=30, label='NIF / TIN',
        widget=forms.TextInput(attrs={'class': 'text-input', 'placeholder': 'Saisir le NIF'}),
    )


class CancelInvoiceForm(forms.Form):
    motif = forms.CharField(
        max_length=500, label='Motif d’annulation',
        widget=forms.Textarea(attrs={
            'class': 'textarea-input', 'rows': 2,
            'placeholder': 'Motif transmis à OBR',
        }),
    )
