from django import forms

from .models import TeachingClass


class ClassForm(forms.ModelForm):
    class Meta:
        model = TeachingClass
        fields = ["course", "term", "name"]


class JoinForm(forms.Form):
    code = forms.CharField(label="邀请码", max_length=32)


class GroupForm(forms.Form):
    name = forms.CharField(label="组名", max_length=60)


class AssignmentForm(forms.Form):
    group = forms.ModelChoiceField(label="小组", queryset=None)

    def __init__(self, *args, groups, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["group"].queryset = groups
