"""검사항목 설정·라벨 클래스 입력 form.

ItemSettingsForm·LabelClassForm은 검사항목 명령 API(InspectionItemCommandApiView,
app/views/item/home/api.py)의 update·label_create·label_update가 입력 검증에 쓴다.
InspectionItemBasicForm은 없어진 단계별 생성 화면의 form으로, 지금은 tests/test_project_creation.py만 쓴다.
"""
from django import forms

from domain.models.data import LabelClass


# 사용처 없음: 테스트만 참조한다. 화면·API·InspectionItemCreationService와 연결되어 있지 않다.
class InspectionItemBasicForm(forms.Form):
    name = forms.CharField(label="비전검사항목명", max_length=140)
    description = forms.CharField(label="설명", required=False, widget=forms.Textarea(attrs={"rows": 4}))


class ItemSettingsForm(forms.Form):
    name = forms.CharField(label="비전검사항목명", max_length=140)
    description = forms.CharField(label="설명", required=False, widget=forms.Textarea(attrs={"rows": 5}))


class LabelClassForm(forms.Form):
    name = forms.CharField(label="내부 이름", max_length=64)
    display_name_ko = forms.CharField(label="표시 이름", max_length=64)
    color = forms.RegexField(label="색상", regex=r"^#[0-9a-fA-F]{6}$", max_length=7, initial="#16A5A3")
    is_defect = forms.BooleanField(label="결함 여부", required=False, initial=True)
    annotation_shape = forms.ChoiceField(label="라벨링 도구", choices=LabelClass.AnnotationShape.choices, initial=LabelClass.AnnotationShape.BBOX, required=False)


class MeasurementPointForm(forms.Form):
    """치수 측정 항목의 측정점. code 는 클라이언트가 측정값을 돌려보낼 때 쓰는 키다."""

    code = forms.RegexField(label="코드", regex=r"^[A-Za-z0-9_-]+$", max_length=20,
                            error_messages={"invalid": "코드는 영문·숫자·_·- 만 씁니다."})
    name = forms.CharField(label="이름", max_length=100)
    nominal = forms.DecimalField(label="기준값", max_digits=18, decimal_places=3)
    lower = forms.DecimalField(label="하한", max_digits=18, decimal_places=3)
    upper = forms.DecimalField(label="상한", max_digits=18, decimal_places=3)
    unit = forms.CharField(label="단위", max_length=10)
    description = forms.CharField(label="측정 방법", required=False)

    def clean(self):
        cleaned = super().clean()
        lower, nominal, upper = (cleaned.get(k) for k in ("lower", "nominal", "upper"))
        if None not in (lower, nominal, upper) and not lower <= nominal <= upper:
            raise forms.ValidationError("하한 ≤ 기준값 ≤ 상한 이어야 합니다.")
        return cleaned
