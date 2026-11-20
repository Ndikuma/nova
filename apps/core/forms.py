from django import forms
from django.contrib.auth.forms import AuthenticationForm


class StaffLoginForm(AuthenticationForm):
    username = forms.CharField(
        label='Identifiant',
        widget=forms.TextInput(attrs={
            'autocomplete': 'username',
        }),
    )
    password = forms.CharField(
        label='Mot de passe',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'autocomplete': 'current-password',
        }),
    )
