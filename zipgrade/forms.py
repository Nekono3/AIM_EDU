from django import forms
from django.db import models
from django.utils.translation import gettext_lazy as _
from .models import ZipGradeExam, SubjectSplit
from schools.models import School, Subject


class ZipGradeUploadForm(forms.Form):
    """Form for uploading ZipGrade CSV files."""
    
    school = forms.ModelChoiceField(
        queryset=School.objects.filter(is_active=True),
        label=_('School'),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    
    title = forms.CharField(
        max_length=200,
        label=_('Exam Title'),
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': _('e.g., Math Quiz Week 5')
        }),
    )
    
    exam_date = forms.DateField(
        label=_('Exam Date'),
        widget=forms.DateInput(attrs={
            'class': 'form-input',
            'type': 'date'
        }),
    )
    
    file = forms.FileField(
        label=_('ZipGrade File'),
        widget=forms.FileInput(attrs={
            'class': 'form-input',
            'accept': '.csv,.txt,.xlsx,.xls'
        }),
        help_text=_('Upload CSV or XLSX file from ZipGrade.')
    )
    
    def clean_file(self):
        file = self.cleaned_data.get('file')
        if file:
            # Check file extension
            name = file.name.lower()
            valid_extensions = ('.csv', '.txt', '.xlsx', '.xls')
            if not name.endswith(valid_extensions):
                raise forms.ValidationError(
                    _('Invalid file format. Please upload a CSV or XLSX file.')
                )
            
            # Check file size (max 10MB)
            if file.size > 10 * 1024 * 1024:
                raise forms.ValidationError(
                    _('File too large. Maximum size is 10MB.')
                )
        
        return file


def _class_types_overlap(type_a, type_b):
    """Return True if two class_type values could apply to the same student.

    Two splits 'overlap' in audience when:
    - either is 'all' (applies to everyone), OR
    - both are the same specific type (both 'ru' or both 'kg').
    """
    if type_a == 'all' or type_b == 'all':
        return True
    return type_a == type_b


class SubjectSplitForm(forms.ModelForm):
    """Form for defining subject question ranges."""
    
    class Meta:
        model = SubjectSplit
        fields = ['subject', 'start_question', 'end_question', 'points_per_question', 'class_type']
        widgets = {
            'subject': forms.Select(attrs={'class': 'form-select'}),
            'start_question': forms.NumberInput(attrs={'class': 'form-input', 'min': 1}),
            'end_question': forms.NumberInput(attrs={'class': 'form-input', 'min': 1}),
            'points_per_question': forms.NumberInput(attrs={
                'class': 'form-input',
                'step': '0.01',
                'min': '0.01'
            }),
            'class_type': forms.Select(attrs={'class': 'form-select'}),
        }
    
    def __init__(self, *args, exam=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.exam = exam
        
        # Show all active subjects (subjects are typically shared across schools)
        self.fields['subject'].queryset = Subject.objects.filter(is_active=True)
    
    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start_question')
        end = cleaned_data.get('end_question')
        
        if start and end:
            if start > end:
                raise forms.ValidationError(
                    _('Start question must be less than or equal to end question.')
                )
            
            if self.exam:
                # Check against exam's total questions
                if end > self.exam.total_questions:
                    raise forms.ValidationError(
                        _('End question cannot exceed total questions (%(total)s).') %
                        {'total': self.exam.total_questions}
                    )
                
                # Check for overlapping ranges
                existing_splits = self.exam.subject_splits.all()
                if self.instance.pk:
                    existing_splits = existing_splits.exclude(pk=self.instance.pk)
                
                new_class_type = cleaned_data.get('class_type', 'all')
                for split in existing_splits:
                    # Ranges overlap if: new_start < existing_end AND new_end > existing_start
                    # This allows adjacent ranges like 1-30 and 31-60.
                    # IMPORTANT: only flag as overlap if both splits apply to the same class-type
                    # audience (e.g. a RU-only split and a KG-only split may share the same
                    # question numbers on purpose — they never score the same student twice).
                    if (start < split.end_question and end > split.start_question
                            and _class_types_overlap(new_class_type, split.class_type)):
                        raise forms.ValidationError(
                            _('Question range overlaps with existing split: %(subject)s (Q%(start)s-Q%(end)s) [%(ctype)s]') %
                            {
                                'subject': split.subject.name,
                                'start': split.start_question,
                                'end': split.end_question,
                                'ctype': split.get_class_type_display(),
                            }
                        )
        
        return cleaned_data


class SubjectSplitFormSet(forms.BaseFormSet):
    """FormSet for multiple subject splits."""
    
    def __init__(self, *args, exam=None, **kwargs):
        self.exam = exam
        super().__init__(*args, **kwargs)
    
    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs['exam'] = self.exam
        return kwargs
