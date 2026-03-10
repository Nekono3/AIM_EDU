from django.db.models import Avg, Count, Max, Min, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from openpyxl.utils import get_column_letter
from exams.models import ExamAttempt, OnlineExam
from zipgrade.models import ExamResult

class AnalyticsHelper:
    """Helper class for analytics calculations."""

    @staticmethod
    def get_school_stats(school):
        """Get overall statistics for a school."""
        
        # Online Exam Stats
        online_attempts = ExamAttempt.objects.filter(
            exam__school=school, 
            status='completed'
        )
        
        online_stats = online_attempts.aggregate(
            total_attempts=Count('id'),
            avg_score=Avg('percentage'),
            max_score=Max('percentage'),
            min_score=Min('percentage')
        )
        
        # Calculate Pass Rate (assuming 60% is passing for now, or use exam specific)
        passed_attempts = 0
        if online_stats['total_attempts'] and online_stats['total_attempts'] > 0:
            # This is an approximation as passing_score is per exam
            # For a more accurate pass rate we need to check each attempt against its exam's passing score
            pass_count = 0
            for attempt in online_attempts.select_related('exam'):
                if attempt.percentage >= attempt.exam.passing_score:
                    pass_count += 1
            pass_rate = (pass_count / online_stats['total_attempts']) * 100
        else:
            pass_rate = 0

        # Subject Performance
        subject_performance = []
        # Group by subject name via Exam -> Subject
        # This is a bit complex in ORM across relationships, simplified approach:
        
        return {
            'online_exams': {
                'count': online_stats['total_attempts'] or 0,
                'avg_score': round(online_stats['avg_score'] or 0, 1),
                'pass_rate': round(pass_rate, 1),
                'max_score': round(online_stats['max_score'] or 0, 1),
                'min_score': round(online_stats['min_score'] or 0, 1),
            }
        }

    @staticmethod
    def get_online_exam_subject_performance(school):
        """Get subject performance stats for online exams."""
        from schools.models import Subject
        from django.db.models import Avg, Count
        
        subjects = Subject.objects.filter(online_exams__school=school).distinct()
        performance = []
        
        for subject in subjects:
            attempts = ExamAttempt.objects.filter(
                exam__school=school,
                exam__subject=subject,
                status='completed'
            )
            if attempts.exists():
                stats = attempts.aggregate(avg=Avg('percentage'), count=Count('id'))
                passed = sum(1 for a in attempts if a.percentage >= (a.exam.passing_score or 60))
                pass_rate = (passed / stats['count']) * 100
                
                performance.append({
                    'name': subject.name,
                    'count': stats['count'],
                    'avg_score': round(stats['avg'], 1),
                    'pass_rate': round(pass_rate, 1)
                })
        
        performance.sort(key=lambda x: x['avg_score'], reverse=True)
        return performance

    @staticmethod
    def get_all_schools_stats():
        """Get aggregated statistics across all schools."""
        
        # Online Exam Stats for all schools
        online_attempts = ExamAttempt.objects.filter(status='completed')
        
        online_stats = online_attempts.aggregate(
            total_attempts=Count('id'),
            avg_score=Avg('percentage'),
            max_score=Max('percentage'),
            min_score=Min('percentage')
        )
        
        # Calculate Pass Rate
        if online_stats['total_attempts'] and online_stats['total_attempts'] > 0:
            pass_count = 0
            for attempt in online_attempts.select_related('exam'):
                if attempt.percentage >= attempt.exam.passing_score:
                    pass_count += 1
            pass_rate = (pass_count / online_stats['total_attempts']) * 100
        else:
            pass_rate = 0

        return {
            'online_exams': {
                'count': online_stats['total_attempts'] or 0,
                'avg_score': round(online_stats['avg_score'] or 0, 1),
                'pass_rate': round(pass_rate, 1),
                'max_score': round(online_stats['max_score'] or 0, 1),
                'min_score': round(online_stats['min_score'] or 0, 1),
            }
        }

    @staticmethod
    def get_exam_stats(exam):
        """Get stats for a specific exam."""
        attempts = exam.attempts.filter(status='completed')
        
        total = attempts.count()
        if total == 0:
            return None
            
        stats = attempts.aggregate(
            avg=Avg('percentage'),
            max=Max('percentage'),
            min=Min('percentage')
        )
        
        passed = sum(1 for a in attempts if a.is_passed)
        
        return {
            'total_students': total,
            'avg_score': round(stats['avg'] or 0, 1),
            'max_score': round(stats['max'] or 0, 1),
            'min_score': round(stats['min'] or 0, 1),
            'pass_rate': round((passed / total) * 100, 1)
        }

    @staticmethod
    def get_classes_list(school):
        """Get distinct classes (grade + section) for a school."""
        from schools.models import MasterStudent
        
        classes = MasterStudent.objects.filter(school=school).values(
            'grade', 'section'
        ).distinct().order_by('grade', 'section')
        
        return [{'grade': c['grade'], 'section': c['section'], 
                 'name': f"{c['grade']}{c['section']}"} for c in classes]

    @staticmethod
    def get_class_stats(school, grade, section):
        """Get statistics for a specific class."""
        from schools.models import MasterStudent
        from accounts.models import User
        
        # Get all students in class from master list
        master_students = MasterStudent.objects.filter(
            school=school, grade=grade, section=section
        )
        
        # Get User accounts linked to this school that have taken exams
        # Match via similar full name patterns or student IDs
        student_ids = []
        for ms in master_students:
            # Try to find matching User by name pattern
            users = User.objects.filter(
                role='student',
                primary_school=school,
                first_name__icontains=ms.name,
                last_name__icontains=ms.surname
            )
            student_ids.extend([u.pk for u in users])
        
        if not student_ids:
            # Fallback: get all student users from the school
            student_ids = list(User.objects.filter(
                role='student',
                primary_school=school
            ).values_list('pk', flat=True))
        
        # Get exam attempts for these students
        attempts = ExamAttempt.objects.filter(
            student__pk__in=student_ids,
            status='completed'
        )
        
        total_attempts = attempts.count()
        if total_attempts == 0:
            return {
                'total_students': master_students.count(),
                'total_exams': 0,
                'avg_score': 0,
                'max_score': 0,
                'min_score': 0,
                'pass_rate': 0,
                'top_students': []
            }
        
        stats = attempts.aggregate(
            avg=Avg('percentage'),
            max=Max('percentage'),
            min=Min('percentage')
        )
        
        # Calculate pass rate
        passed_count = 0
        for attempt in attempts.select_related('exam'):
            if attempt.percentage >= attempt.exam.passing_score:
                passed_count += 1
        pass_rate = (passed_count / total_attempts) * 100 if total_attempts > 0 else 0
        
        # Get top performing students
        top_students = attempts.values(
            'student__first_name', 'student__last_name', 'student__pk'
        ).annotate(
            avg_score=Avg('percentage'),
            exams_taken=Count('id')
        ).order_by('-avg_score')[:5]
        
        return {
            'total_students': master_students.count(),
            'total_exams': total_attempts,
            'avg_score': round(stats['avg'] or 0, 1),
            'max_score': round(stats['max'] or 0, 1),
            'min_score': round(stats['min'] or 0, 1),
            'pass_rate': round(pass_rate, 1),
            'top_students': list(top_students)
        }

    @staticmethod
    def get_zipgrade_exams_for_school(school):
        """Get all ZipGrade exams for a school."""
        from zipgrade.models import ZipGradeExam
        return ZipGradeExam.objects.filter(school=school).order_by('-exam_date', '-created_at')

    @staticmethod
    def get_zipgrade_exam_stats(exam_ids):
        """Get aggregated statistics for selected ZipGrade exams."""
        from zipgrade.models import ZipGradeExam, ExamResult
        from decimal import Decimal
        
        if not exam_ids:
            return None
            
        results = ExamResult.objects.filter(exam_id__in=exam_ids)
        
        if not results.exists():
            return {
                'total_students': 0,
                'total_exams': len(exam_ids),
                'avg_score': 0,
                'max_score': 0,
                'min_score': 0,
                'pass_rate': 0,
                'exams_info': []
            }
        
        stats = results.aggregate(
            avg=Avg(Coalesce('class_type_percentage', 'percentage')),
            max=Max(Coalesce('class_type_percentage', 'percentage')),
            min=Min(Coalesce('class_type_percentage', 'percentage')),
            total=Count('id')
        )
        
        # Calculate pass rate (60% as passing threshold)
        passing_threshold = 60
        passed = results.filter(
            Q(class_type_percentage__gte=passing_threshold) |
            Q(class_type_percentage__isnull=True, percentage__gte=passing_threshold)
        ).count()
        pass_rate = (passed / stats['total']) * 100 if stats['total'] > 0 else 0
        
        # Get exam info
        exams = ZipGradeExam.objects.filter(pk__in=exam_ids)
        exams_info = [{
            'id': e.pk,
            'title': e.title,
            'date': e.exam_date,
            'total_students': e.total_students,
            'avg_score': e.average_score
        } for e in exams]
        
        return {
            'total_students': stats['total'],
            'total_exams': len(exam_ids),
            'avg_score': round(float(stats['avg'] or 0), 1),
            'max_score': round(float(stats['max'] or 0), 1),
            'min_score': round(float(stats['min'] or 0), 1),
            'pass_rate': round(pass_rate, 1),
            'exams_info': exams_info
        }

    @staticmethod
    def get_zipgrade_class_breakdown(exam_ids, school):
        """Get breakdown by class for selected ZipGrade exams."""
        from zipgrade.models import ExamResult
        from schools.models import MasterStudent
        
        if not exam_ids:
            return []
        
        results = ExamResult.objects.filter(
            exam_id__in=exam_ids,
            student__isnull=False,
            student__school=school
        ).select_related('student')
        
        # Group by class (grade + section)
        class_stats = {}
        for result in results:
            if result.student:
                key = f"{result.student.grade}{result.student.section}"
                if key not in class_stats:
                    class_stats[key] = {
                        'grade': result.student.grade,
                        'section': result.student.section,
                        'name': key,
                        'scores': [],
                        'student_ids': set()
                    }
                class_stats[key]['scores'].append(
                    float(result.class_type_percentage if result.class_type_percentage is not None else result.percentage)
                )
                class_stats[key]['student_ids'].add(result.student_id)
        
        # Calculate averages
        breakdown = []
        for key, data in class_stats.items():
            avg_score = sum(data['scores']) / len(data['scores']) if data['scores'] else 0
            passed = sum(1 for s in data['scores'] if s >= 60)
            pass_rate = (passed / len(data['scores'])) * 100 if data['scores'] else 0
            
            breakdown.append({
                'name': data['name'],
                'grade': data['grade'],
                'section': data['section'],
                'student_count': len(data['student_ids']),
                'avg_score': round(avg_score, 1),
                'pass_rate': round(pass_rate, 1),
                'max_score': round(max(data['scores']) if data['scores'] else 0, 1),
                'min_score': round(min(data['scores']) if data['scores'] else 0, 1)
            })
        
        # Sort by class name
        breakdown.sort(key=lambda x: (x['grade'], x['section']))
        return breakdown

    @staticmethod
    def get_zipgrade_subject_breakdown(exam_ids):
        """Get breakdown by subject for selected ZipGrade exams (if subject splits exist)."""
        from zipgrade.models import SubjectResult, SubjectSplit
        
        if not exam_ids:
            return []
        
        # Get all subject results for the selected exams
        subject_results = SubjectResult.objects.filter(
            result__exam_id__in=exam_ids
        ).select_related('subject_split__subject')
        
        if not subject_results.exists():
            return []
        
        # Group by subject
        subject_stats = {}
        for sr in subject_results:
            subject_name = sr.subject_split.subject.name
            if subject_name not in subject_stats:
                subject_stats[subject_name] = {
                    'name': subject_name,
                    'scores': []
                }
            subject_stats[subject_name]['scores'].append(float(sr.percentage))
        
        # Calculate aggregates
        breakdown = []
        for name, data in subject_stats.items():
            avg = sum(data['scores']) / len(data['scores']) if data['scores'] else 0
            passed = sum(1 for s in data['scores'] if s >= 60)
            pass_rate = (passed / len(data['scores'])) * 100 if data['scores'] else 0
            
            breakdown.append({
                'name': name,
                'student_count': len(data['scores']),
                'avg_score': round(avg, 1),
                'pass_rate': round(pass_rate, 1),
                'max_score': round(max(data['scores']) if data['scores'] else 0, 1),
                'min_score': round(min(data['scores']) if data['scores'] else 0, 1)
            })
        
        breakdown.sort(key=lambda x: x['name'])
        return breakdown

    @staticmethod
    def get_zipgrade_student_ranking(exam_ids, limit=20):
        """Get student ranking for selected ZipGrade exams."""
        from zipgrade.models import ExamResult
        
        if not exam_ids:
            return []
        
        results = ExamResult.objects.filter(
            exam_id__in=exam_ids
        ).select_related('student', 'exam')
        
        # Group by student
        student_stats = {}
        for result in results:
            # Use student ID if linked, otherwise ZipGrade ID
            if result.student:
                key = f"student_{result.student.pk}"
                name = result.student.full_name
                grade = result.student.grade
                section = result.student.section
            else:
                key = f"zg_{result.zipgrade_student_id}"
                name = result.display_name
                grade = '-'
                section = '-'
            
            if key not in student_stats:
                student_stats[key] = {
                    'name': name,
                    'grade': grade,
                    'section': section,
                    'scores': [],
                    'exams_taken': 0
                }
            student_stats[key]['scores'].append(
                float(result.class_type_percentage if result.class_type_percentage is not None else result.percentage)
            )
            student_stats[key]['exams_taken'] += 1
        
        # Calculate averages and sort
        ranking = []
        for key, data in student_stats.items():
            avg = sum(data['scores']) / len(data['scores']) if data['scores'] else 0
            ranking.append({
                'name': data['name'],
                'grade': data['grade'],
                'section': data['section'],
                'avg_score': round(avg, 1),
                'exams_taken': data['exams_taken'],
                'best_score': round(max(data['scores']) if data['scores'] else 0, 1),
                'worst_score': round(min(data['scores']) if data['scores'] else 0, 1)
            })
        
        # Sort by average score descending
        ranking.sort(key=lambda x: x['avg_score'], reverse=True)
        return ranking[:limit]

    @staticmethod
    def get_growth_chart_data(school=None):
        """Get growth chart data (last 12 weeks)."""
        from datetime import timedelta
        
        chart_labels = []
        chart_data = []
        today = timezone.now()
        
        filter_kwargs = {'status': 'completed'}
        if school:
            filter_kwargs['exam__school'] = school
            
        for i in range(11, -1, -1):
            start_date = today - timedelta(weeks=i+1)
            end_date = today - timedelta(weeks=i)
            
            # Copy dict to avoid reference issues
            current_filter = filter_kwargs.copy()
            current_filter['finished_at__range'] = (start_date, end_date)
            
            count = ExamAttempt.objects.filter(**current_filter).count()
            chart_labels.append(end_date.strftime('%d.%m'))
            chart_data.append(count)
            
        return chart_labels, chart_data

    @staticmethod
    def get_school_comparison_data(selected_exam_ids=None, selected_subject_id=None):
        """Get school comparison data (average scores)."""
        from schools.models import School
        from zipgrade.models import ZipGradeExam, SubjectResult
        
        labels = []
        data = []
        all_schools = School.objects.filter(is_active=True)
        
        for s in all_schools:
            s_exams = ZipGradeExam.objects.filter(school=s)
            if selected_exam_ids:
                s_exam_ids = [int(eid) for eid in selected_exam_ids if str(eid).isdigit()]
                s_exams = s_exams.filter(pk__in=s_exam_ids)
            
            s_exam_ids_list = list(s_exams.values_list('pk', flat=True))
            if s_exam_ids_list:
                if selected_subject_id:
                    subject_results = SubjectResult.objects.filter(
                        result__exam_id__in=s_exam_ids_list,
                        subject_split__subject_id=selected_subject_id
                    )
                    if subject_results.exists():
                        avg = sum(float(sr.percentage) for sr in subject_results) / subject_results.count()
                    else:
                        avg = 0
                else:
                    s_stats = AnalyticsHelper.get_zipgrade_exam_stats(s_exam_ids_list)
                    avg = s_stats['avg_score'] if s_stats else 0
            else:
                avg = 0
            labels.append(s.name)
            data.append(round(avg, 1))
            
        return labels, data

    @staticmethod
    def get_performance_distribution(exam_ids):
        """Get student performance distribution for PieChart.
        
        Categories:
        - Excellent: 80-100%
        - Good: 60-79%
        - Satisfactory: 50-59%
        - Unsatisfactory: 0-49%
        """
        from zipgrade.models import ExamResult
        from django.utils.translation import gettext as _
        
        if not exam_ids:
            return [], []
        
        results = ExamResult.objects.filter(exam_id__in=exam_ids)
        
        if not results.exists():
            return [], []
        
        # Count results in each category
        excellent = 0      # 80-100%
        good = 0           # 60-79%
        satisfactory = 0   # 50-59%
        unsatisfactory = 0 # 0-49%
        
        for result in results:
            percentage = float(result.class_type_percentage if result.class_type_percentage is not None else result.percentage)
            if percentage >= 80:
                excellent += 1
            elif percentage >= 60:
                good += 1
            elif percentage >= 50:
                satisfactory += 1
            else:
                unsatisfactory += 1
        
        labels = [
            _('Excellent (80-100%)'),
            _('Good (60-79%)'),
            _('Satisfactory (50-59%)'),
            _('Unsatisfactory (0-49%)')
        ]
        data = [excellent, good, satisfactory, unsatisfactory]
        
        return labels, data

    @staticmethod
    def get_class_performance_distribution(exam_ids, grade, section):
        """Get performance distribution for a specific class in ZipGrade exams.
        
        Categories:
        - Excellent: 80-100%
        - Good: 60-79%
        - Satisfactory: 50-59%
        - Unsatisfactory: 0-49%
        """
        from zipgrade.models import ExamResult
        from django.utils.translation import gettext as _
        
        if not exam_ids:
            return [], []
        
        results = ExamResult.objects.filter(
            exam_id__in=exam_ids,
            student__grade=grade,
            student__section=section
        )
        
        if not results.exists():
            return [], []
        
        excellent = 0
        good = 0
        satisfactory = 0
        unsatisfactory = 0
        
        for result in results:
            percentage = float(result.class_type_percentage if result.class_type_percentage is not None else result.percentage)
            if percentage >= 80:
                excellent += 1
            elif percentage >= 60:
                good += 1
            elif percentage >= 50:
                satisfactory += 1
            else:
                unsatisfactory += 1
        
        labels = [
            _('Excellent (80-100%)'),
            _('Good (60-79%)'),
            _('Satisfactory (50-59%)'),
            _('Unsatisfactory (0-49%)')
        ]
        data = [excellent, good, satisfactory, unsatisfactory]
        
        return labels, data

    @staticmethod
    def get_class_ranked_students(exam_ids, grade, section):
        """Get all students in a class ranked by average ZipGrade score (highest first).
        
        Returns list of dicts: [{name, avg_score, exam_count, percentage}, ...]
        """
        from zipgrade.models import ExamResult
        from django.db.models import Avg, Count
        
        if not exam_ids or not grade or not section:
            return []
        
        # Aggregate by student: average percentage and count of exams
        student_stats = (
            ExamResult.objects.filter(
                exam_id__in=exam_ids,
                student__grade=grade,
                student__section=section,
                student__isnull=False
            )
            .values('student__id', 'student__name', 'student__surname')
            .annotate(
                avg_score=Avg(Coalesce('class_type_percentage', 'percentage')),
                exam_count=Count('id')
            )
            .order_by('-avg_score')
        )
        
        ranked = []
        for i, s in enumerate(student_stats, 1):
            ranked.append({
                'rank': i,
                'name': f"{s['student__surname']} {s['student__name']}".strip(),
                'avg_score': round(float(s['avg_score']), 1),
                'exam_count': s['exam_count'],
            })
        
        return ranked

    @staticmethod
    def get_class_subject_breakdown(exam_ids, grade, section):
        """Get subject breakdown for a specific class in selected ZipGrade exams.
        
        Returns list of subjects sorted by average score (best performing first).
        Used for pie chart showing which subjects the class excels at.
        """
        from zipgrade.models import SubjectResult, ExamResult
        
        if not exam_ids or not grade or not section:
            return [], []
        
        # Get all exam results for students in this class
        class_results = ExamResult.objects.filter(
            exam_id__in=exam_ids,
            student__grade=grade,
            student__section=section
        ).values_list('id', flat=True)
        
        if not class_results:
            return [], []
        
        # Get subject results for these exam results
        subject_results = SubjectResult.objects.filter(
            result_id__in=class_results
        ).select_related('subject_split__subject')
        
        if not subject_results.exists():
            return [], []
        
        # Group by subject and calculate averages
        subject_stats = {}
        for sr in subject_results:
            subject_name = sr.subject_split.subject.name
            if subject_name not in subject_stats:
                subject_stats[subject_name] = {'scores': []}
            subject_stats[subject_name]['scores'].append(float(sr.percentage))
        
        # Calculate averages and build result
        breakdown = []
        for name, data in subject_stats.items():
            avg = sum(data['scores']) / len(data['scores']) if data['scores'] else 0
            breakdown.append({
                'name': name,
                'avg_score': round(avg, 1)
            })
        
        # Sort by average score descending (best subjects first)
        breakdown.sort(key=lambda x: x['avg_score'], reverse=True)
        
        # Return labels and data for pie chart
        labels = [s['name'] for s in breakdown]
        data = [s['avg_score'] for s in breakdown]
        
        return labels, data


class ReportGenerator:


    """Helper for generating analytic reports."""
    
    # Unicode font name constant — used in table styles and paragraphs
    UNICODE_FONT = 'LiberationSans'
    UNICODE_FONT_BOLD = 'LiberationSans-Bold'
    
    @staticmethod
    def _register_unicode_fonts():
        """Register Unicode-capable fonts for PDF generation.
        
        Returns (font_name, font_name_bold) tuple.
        Falls back to Helvetica if LiberationSans not available.
        """
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import os
        
        font_dir = '/usr/share/fonts/liberation'
        regular = os.path.join(font_dir, 'LiberationSans-Regular.ttf')
        bold = os.path.join(font_dir, 'LiberationSans-Bold.ttf')
        italic = os.path.join(font_dir, 'LiberationSans-Italic.ttf')
        
        if os.path.exists(regular):
            try:
                pdfmetrics.registerFont(TTFont('LiberationSans', regular))
                if os.path.exists(bold):
                    pdfmetrics.registerFont(TTFont('LiberationSans-Bold', bold))
                if os.path.exists(italic):
                    pdfmetrics.registerFont(TTFont('LiberationSans-Italic', italic))
                return 'LiberationSans', 'LiberationSans-Bold'
            except Exception:
                pass
        
        return 'Helvetica', 'Helvetica-Bold'
    
    @staticmethod
    def _get_unicode_styles():
        """Get stylesheet with Unicode font applied to all styles."""
        from reportlab.lib.styles import getSampleStyleSheet
        
        font_name, font_bold = ReportGenerator._register_unicode_fonts()
        styles = getSampleStyleSheet()
        
        # Override default fonts with Unicode-capable font
        for style_name in styles.byName:
            style = styles[style_name]
            if hasattr(style, 'fontName'):
                if 'Bold' in style.fontName or 'bold' in style.fontName.lower():
                    style.fontName = font_bold
                else:
                    style.fontName = font_name
        
        return styles, font_name, font_bold
    
    @staticmethod
    def _get_performance_category(percentage):
        """Return performance category string from percentage."""
        if percentage >= 80:
            return 'Excellent'
        elif percentage >= 60:
            return 'Good'
        elif percentage >= 50:
            return 'Satisfactory'
        return 'Unsatisfactory'

    @staticmethod
    def _build_pie_chart(perf_dist, font_name):
        """Build a performance distribution pie chart Drawing."""
        from reportlab.graphics.shapes import Drawing, String, Rect
        from reportlab.graphics.charts.piecharts import Pie
        from reportlab.lib import colors as c

        cat_colors = [
            c.HexColor('#27ae60'),  # Excellent - Green
            c.HexColor('#2980b9'),  # Good - Blue
            c.HexColor('#f39c12'),  # Satisfactory - Orange
            c.HexColor('#e74c3c'),  # Unsatisfactory - Red
        ]
        cat_names = ['Excellent (80-100)', 'Good (60-79)', 'Satisfactory (50-59)', 'Unsatisfactory (0-49)']

        ordered_keys = [
            'Excellent (80-100%)', 'Good (60-79%)',
            'Satisfactory (50-59%)', 'Unsatisfactory (0-49%)',
        ]
        values = []
        for k in ordered_keys:
            found = False
            for dk, dv in perf_dist.items():
                if 'Excellent' in str(dk) or '80' in str(dk):
                    if k == ordered_keys[0]:
                        values.append(int(dv)); found = True; break
                elif 'Good' in str(dk) or '60' in str(dk):
                    if k == ordered_keys[1]:
                        values.append(int(dv)); found = True; break
                elif 'Satisfactory' in str(dk) and 'Un' not in str(dk):
                    if k == ordered_keys[2]:
                        values.append(int(dv)); found = True; break
                elif 'Unsatisfactory' in str(dk) or '0-49' in str(dk):
                    if k == ordered_keys[3]:
                        values.append(int(dv)); found = True; break
            if not found:
                values.append(0)

        total = sum(values)
        if total == 0:
            return None

        d = Drawing(500, 220)
        pie = Pie()
        pie.x = 30
        pie.y = 20
        pie.width = 180
        pie.height = 180
        pie.data = values
        pie.labels = None
        pie.sideLabels = False

        for i, col in enumerate(cat_colors):
            pie.slices[i].fillColor = col
            pie.slices[i].strokeColor = c.white
            pie.slices[i].strokeWidth = 1

        d.add(pie)

        # Legend
        legend_x = 240
        legend_y = 170
        for i, name in enumerate(cat_names):
            y = legend_y - i * 30
            pct = round(values[i] / total * 100, 1) if total else 0
            d.add(Rect(legend_x, y, 14, 14, fillColor=cat_colors[i], strokeColor=None))
            d.add(String(legend_x + 20, y + 2, f"{name}: {values[i]} ({pct}%)",
                         fontName=font_name, fontSize=9))

        return d

    @staticmethod
    def _build_bar_chart(subject_labels, subject_data, font_name):
        """Build a best performing subjects bar chart Drawing."""
        from reportlab.graphics.shapes import Drawing
        from reportlab.graphics.charts.barcharts import VerticalBarChart
        from reportlab.lib import colors as c

        if not subject_labels or not subject_data:
            return None

        chart_colors = [
            c.HexColor('#3498db'), c.HexColor('#2ecc71'), c.HexColor('#e74c3c'),
            c.HexColor('#f39c12'), c.HexColor('#9b59b6'), c.HexColor('#1abc9c'),
            c.HexColor('#e67e22'), c.HexColor('#34495e'),
        ]

        d = Drawing(500, 220)
        bc = VerticalBarChart()
        bc.x = 50
        bc.y = 40
        bc.height = 150
        bc.width = 420
        bc.data = [subject_data]
        bc.categoryAxis.categoryNames = [s[:15] for s in subject_labels]
        bc.categoryAxis.labels.boxAnchor = 'ne'
        bc.categoryAxis.labels.angle = 30
        bc.categoryAxis.labels.dy = -5
        bc.categoryAxis.labels.fontName = font_name
        bc.categoryAxis.labels.fontSize = 7
        bc.valueAxis.valueMin = 0
        bc.valueAxis.valueMax = 100
        bc.valueAxis.valueStep = 20
        bc.valueAxis.labels.fontName = font_name

        for i in range(len(subject_data)):
            bc.bars[0].fillColor = chart_colors[i % len(chart_colors)]

        # Color each bar individually
        for i in range(len(subject_data)):
            idx = i % len(chart_colors)
            bc.bars[(0, i)].fillColor = chart_colors[idx]

        d.add(bc)
        return d

    @staticmethod
    def generate_excel_report(report_data):
        """Generate simplified Excel report — single sheet with student ranking."""
        import openpyxl
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
        from django.http import HttpResponse

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Student Rankings"

        school_name = report_data.get('school_name', 'School')
        ranked_students = report_data.get('ranked_students', [])

        # Header
        ws['A1'] = f"Student Rankings — {school_name}"
        ws['A1'].font = Font(size=14, bold=True)
        ws.merge_cells('A1:E1')
        ws['A2'] = f"Generated: {timezone.now().strftime('%Y-%m-%d %H:%M')}"
        ws['A2'].font = Font(size=9, italic=True)

        # Column Headers
        headers = ["Rank", "Student Name", "Score", "Percentage", "Performance"]
        header_fill = PatternFill(start_color="1a1a2e", end_color="1a1a2e", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF", size=10)
        thin_border = Border(
            left=Side(style='thin'), right=Side(style='thin'),
            top=Side(style='thin'), bottom=Side(style='thin'),
        )

        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=4, column=col, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center')
            cell.border = thin_border

        # Data rows
        for i, s in enumerate(ranked_students):
            row = 5 + i
            pct = s.get('avg_score', s.get('percentage', 0))
            perf = ReportGenerator._get_performance_category(pct)
            ws.cell(row=row, column=1, value=s.get('rank', i + 1)).alignment = Alignment(horizontal='center')
            ws.cell(row=row, column=2, value=s.get('name', ''))
            ws.cell(row=row, column=3, value=f"{pct}%")
            ws.cell(row=row, column=4, value=f"{pct}%")
            ws.cell(row=row, column=5, value=perf)
            for c in range(1, 6):
                ws.cell(row=row, column=c).border = thin_border

        # Auto-adjust columns
        widths = [8, 35, 12, 14, 20]
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        safe_name = school_name.replace(' ', '_')[:30]
        response['Content-Disposition'] = f'attachment; filename=rankings_{safe_name}_{timezone.now().date()}.xlsx'
        wb.save(response)
        return response

    @staticmethod
    def generate_pdf_report(report_data):
        """Generate professional PDF report with charts and student ranking.

        report_data dict contains:
            - source, school_name, stats, subject_name
            - performance_distribution: dict {label: count}
            - subject_labels, subject_data: for bar chart
            - ranked_students: list of dicts
        """
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from django.http import HttpResponse
        import io

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
        elements = []
        styles, font_name, font_bold = ReportGenerator._get_unicode_styles()

        source = report_data.get('source', 'exams')
        school_name = report_data.get('school_name', 'Unknown')
        stats = report_data.get('stats', {})
        subject_name = report_data.get('subject_name', '')

        header_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a1a2e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), font_bold),
            ('FONTNAME', (0, 1), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('TOPPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ])

        # ── Header Information ──
        source_label = 'ZipGrade' if source == 'zipgrade' else 'Online Exams'
        elements.append(Paragraph(f"Analytics Report", styles['Title']))
        header_info = [
            ["School", school_name],
            ["Source", source_label],
        ]
        if subject_name:
            header_info.append(["Subject", subject_name])
        header_info.append(["Total Students", str(stats.get('count', 0))])
        header_info.append(["Average Score", f"{stats.get('avg_score', 0)}%"])
        header_info.append(["Pass Rate", f"{stats.get('pass_rate', 0)}%"])
        header_info.append(["Date Generated", timezone.now().strftime('%Y-%m-%d %H:%M')])

        ht = Table(header_info, colWidths=[2*inch, 4*inch])
        ht.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), font_bold),
            ('FONTNAME', (1, 0), (1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LINEBELOW', (0, -1), (-1, -1), 1, colors.HexColor('#1a1a2e')),
        ]))
        elements.append(ht)
        elements.append(Spacer(1, 25))

        # ── Performance Distribution Chart ──
        perf_dist = report_data.get('performance_distribution', {})
        if perf_dist:
            elements.append(Paragraph("Performance Distribution", styles['Heading2']))
            pie_drawing = ReportGenerator._build_pie_chart(perf_dist, font_name)
            if pie_drawing:
                elements.append(pie_drawing)
            elements.append(Spacer(1, 20))

        # ── Best Performing Subjects Chart ──
        subj_labels = report_data.get('subject_labels', [])
        subj_data = report_data.get('subject_data', [])
        if subj_labels and subj_data:
            elements.append(Paragraph("Best Performing Subjects", styles['Heading2']))
            bar_drawing = ReportGenerator._build_bar_chart(subj_labels, subj_data, font_name)
            if bar_drawing:
                elements.append(bar_drawing)
            elements.append(Spacer(1, 20))

        # ── Student Ranking Table ──
        ranked = report_data.get('ranked_students', [])
        if ranked:
            elements.append(Paragraph("Student Rankings", styles['Heading2']))
            rank_data = [["Rank", "Student Name", "Score", "Percentage", "Performance"]]
            for s in ranked:
                pct = s.get('avg_score', s.get('percentage', 0))
                perf = ReportGenerator._get_performance_category(pct)
                rank_data.append([
                    str(s.get('rank', '')),
                    s.get('name', ''),
                    f"{pct}%",
                    f"{pct}%",
                    perf,
                ])
            rt = Table(rank_data, colWidths=[0.5*inch, 2.5*inch, 0.9*inch, 1*inch, 1.3*inch])
            rt.setStyle(header_style)
            # Highlight top 3
            for i in range(1, min(4, len(rank_data))):
                rt.setStyle(TableStyle([
                    ('BACKGROUND', (0, i), (-1, i), colors.HexColor('#d4edda')),
                ]))
            elements.append(rt)
            elements.append(Spacer(1, 20))

        doc.build(elements)
        buffer.seek(0)

        safe_name = school_name.replace(' ', '_').replace('/', '_')[:30]
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename=analytics_{safe_name}_{source}_{timezone.now().date()}.pdf'
        return response

    @staticmethod
    def generate_class_excel_report(report_data):
        """Generate simplified class Excel report — single sheet with student ranking."""
        import openpyxl
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
        from django.http import HttpResponse

        wb = openpyxl.Workbook()
        ws = wb.active

        school_name = report_data.get('school_name', 'School')
        class_name = report_data.get('class_name', '')
        ranked_students = report_data.get('ranked_students', [])

        ws.title = f"Class {class_name}"

        # Header
        ws['A1'] = f"Student Rankings — {school_name} — Class {class_name}"
        ws['A1'].font = Font(size=14, bold=True)
        ws.merge_cells('A1:E1')
        ws['A2'] = f"Generated: {timezone.now().strftime('%Y-%m-%d %H:%M')}"
        ws['A2'].font = Font(size=9, italic=True)

        # Column Headers
        headers = ["Rank", "Student Name", "Score", "Percentage", "Performance"]
        header_fill = PatternFill(start_color="1a1a2e", end_color="1a1a2e", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF", size=10)
        thin_border = Border(
            left=Side(style='thin'), right=Side(style='thin'),
            top=Side(style='thin'), bottom=Side(style='thin'),
        )

        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=4, column=col, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center')
            cell.border = thin_border

        # Data rows
        for i, s in enumerate(ranked_students):
            row = 5 + i
            pct = s.get('avg_score', s.get('percentage', 0))
            perf = ReportGenerator._get_performance_category(pct)
            ws.cell(row=row, column=1, value=s.get('rank', i + 1)).alignment = Alignment(horizontal='center')
            ws.cell(row=row, column=2, value=s.get('name', ''))
            ws.cell(row=row, column=3, value=f"{pct}%")
            ws.cell(row=row, column=4, value=f"{pct}%")
            ws.cell(row=row, column=5, value=perf)
            for c in range(1, 6):
                ws.cell(row=row, column=c).border = thin_border

        # Column widths
        widths = [8, 35, 12, 14, 20]
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename=class_{class_name}_{timezone.now().date()}.xlsx'
        wb.save(response)
        return response

    @staticmethod
    def generate_class_pdf_report(report_data):
        """Generate professional class PDF report with charts and student ranking."""
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from django.http import HttpResponse
        import io

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
        elements = []
        styles, font_name, font_bold = ReportGenerator._get_unicode_styles()

        source = report_data.get('source', 'exams')
        school_name = report_data.get('school_name', '')
        class_name = report_data.get('class_name', '')
        stats = report_data.get('stats', {})

        header_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a1a2e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), font_bold),
            ('FONTNAME', (0, 1), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('TOPPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ])

        # ── Header Information ──
        source_label = 'ZipGrade' if source == 'zipgrade' else 'Online Exams'
        elements.append(Paragraph(f"Class Analytics Report", styles['Title']))
        header_info = [
            ["School", school_name],
            ["Class", class_name],
            ["Source", source_label],
            ["Total Students", str(stats.get('total_students', 0))],
            ["Average Score", f"{stats.get('avg_score', 0)}%"],
            ["Pass Rate", f"{stats.get('pass_rate', 0)}%"],
            ["Date Generated", timezone.now().strftime('%Y-%m-%d %H:%M')],
        ]

        ht = Table(header_info, colWidths=[2*inch, 4*inch])
        ht.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), font_bold),
            ('FONTNAME', (1, 0), (1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LINEBELOW', (0, -1), (-1, -1), 1, colors.HexColor('#1a1a2e')),
        ]))
        elements.append(ht)
        elements.append(Spacer(1, 25))

        # ── Performance Distribution Chart ──
        perf_dist = report_data.get('performance_distribution', {})
        if perf_dist:
            elements.append(Paragraph("Performance Distribution", styles['Heading2']))
            pie_drawing = ReportGenerator._build_pie_chart(perf_dist, font_name)
            if pie_drawing:
                elements.append(pie_drawing)
            elements.append(Spacer(1, 20))

        # ── Best Performing Subjects Chart ──
        subj_labels = report_data.get('subject_labels', [])
        subj_data = report_data.get('subject_data', [])
        if subj_labels and subj_data:
            elements.append(Paragraph("Best Performing Subjects", styles['Heading2']))
            bar_drawing = ReportGenerator._build_bar_chart(subj_labels, subj_data, font_name)
            if bar_drawing:
                elements.append(bar_drawing)
            elements.append(Spacer(1, 20))

        # ── Student Ranking Table ──
        ranked = report_data.get('ranked_students', [])
        if ranked:
            elements.append(Paragraph("Student Rankings", styles['Heading2']))
            rank_data = [["Rank", "Student Name", "Score", "Percentage", "Performance"]]
            for s in ranked:
                pct = s.get('avg_score', s.get('percentage', 0))
                perf = ReportGenerator._get_performance_category(pct)
                rank_data.append([
                    str(s.get('rank', '')),
                    s.get('name', ''),
                    f"{pct}%",
                    f"{pct}%",
                    perf,
                ])
            rt = Table(rank_data, colWidths=[0.5*inch, 2.5*inch, 0.9*inch, 1*inch, 1.3*inch])
            rt.setStyle(header_style)
            for i in range(1, min(4, len(rank_data))):
                rt.setStyle(TableStyle([
                    ('BACKGROUND', (0, i), (-1, i), colors.HexColor('#d4edda')),
                ]))
            elements.append(rt)
            elements.append(Spacer(1, 20))

        doc.build(elements)
        buffer.seek(0)

        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename=class_{class_name}_{source}_{timezone.now().date()}.pdf'
        return response

    @staticmethod
    def generate_student_excel_report(student):
        """Generate Excel report for student analytics."""
        import openpyxl
        from openpyxl.styles import Font
        from django.http import HttpResponse
        from django.db.models import Avg, Max, Min
        
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Student Analytics"
        
        # Header
        ws['A1'] = f"Student Analytics Report: {student.get_full_name()}"
        ws['A1'].font = Font(size=14, bold=True)
        ws.merge_cells('A1:D1')
        
        ws['A2'] = f"Email: {student.email}"
        ws['A3'] = f"Generated: {timezone.now().strftime('%Y-%m-%d %H:%M')}"
        
        # Get attempts
        attempts = ExamAttempt.objects.filter(student=student, status='completed').order_by('-started_at')
        
        if attempts.exists():
            stats = attempts.aggregate(
                avg=Avg('percentage'),
                max=Max('percentage'),
                min=Min('percentage')
            )
            passed = sum(1 for a in attempts if a.percentage >= (a.exam.passing_score or 60))
            
            ws['A5'] = "Overview"
            ws['A5'].font = Font(bold=True)
            
            data = [
                ("Total Exams", attempts.count()),
                ("Passed Exams", passed),
                ("Average Score", f"{round(stats['avg'] or 0, 1)}%"),
                ("Best Score", f"{round(stats['max'] or 0, 1)}%"),
                ("Lowest Score", f"{round(stats['min'] or 0, 1)}%"),
            ]
            
            row = 6
            for label, value in data:
                ws.cell(row=row, column=1, value=label)
                ws.cell(row=row, column=2, value=value)
                row += 1
            
            # Exam history
            row += 2
            ws.cell(row=row, column=1, value="Exam History").font = Font(bold=True)
            row += 1
            headers = ["Exam", "Subject", "Score", "Date", "Status"]
            for col, h in enumerate(headers, 1):
                ws.cell(row=row, column=col, value=h).font = Font(bold=True)
            row += 1
            for attempt in attempts[:20]:
                ws.cell(row=row, column=1, value=attempt.exam.title)
                ws.cell(row=row, column=2, value=attempt.exam.subject.name)
                ws.cell(row=row, column=3, value=f"{attempt.percentage}%")
                ws.cell(row=row, column=4, value=attempt.started_at.strftime("%Y-%m-%d"))
                ws.cell(row=row, column=5, value="Passed" if attempt.is_passed else "Failed")
                row += 1
        else:
            ws['A5'] = "No exam data available"
        
        # Auto-adjust columns
        for col in ws.columns:
            max_length = 0
            column = get_column_letter(col[0].column)
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            ws.column_dimensions[column].width = max_length + 2
        
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename=student_{student.pk}_{timezone.now().date()}.xlsx'
        wb.save(response)
        return response

    @staticmethod
    def generate_student_pdf_report(student):
        """Generate PDF report for student analytics."""
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from django.http import HttpResponse
        from django.db.models import Avg, Max, Min
        import io
        
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        elements = []
        styles, font_name, font_bold = ReportGenerator._get_unicode_styles()
        
        # Title
        elements.append(Paragraph(f"Student Analytics Report: {student.get_full_name()}", styles['Title']))
        elements.append(Paragraph(f"Email: {student.email}", styles['Normal']))
        elements.append(Paragraph(f"Date: {timezone.now().strftime('%Y-%m-%d')}", styles['Normal']))
        elements.append(Spacer(1, 20))
        
        # Get attempts
        attempts = ExamAttempt.objects.filter(student=student, status='completed').order_by('-started_at')
        
        if attempts.exists():
            # Get data for chart (reverse chronologically)
            chart_labels = [a.exam.title[:15] for a in reversed(attempts[:15])]
            chart_values = [float(a.percentage) for a in reversed(attempts[:15])]
            
            stats = attempts.aggregate(
                avg=Avg('percentage'),
                max=Max('percentage'),
                min=Min('percentage')
            )
            passed = sum(1 for a in attempts if a.percentage >= (a.exam.passing_score or 60))
            
            data = [
                ["Metric", "Value"],
                ["Total Exams", str(attempts.count())],
                ["Passed Exams", str(passed)],
                ["Average Score", f"{round(stats['avg'] or 0, 1)}%"],
                ["Best Score", f"{round(stats['max'] or 0, 1)}%"],
                ["Lowest Score", f"{round(stats['min'] or 0, 1)}%"],
            ]
            
            t = Table(data)
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), font_bold),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ]))
            elements.append(t)
            elements.append(Spacer(1, 20))
            
            # Exam History Chart
            from reportlab.graphics.shapes import Drawing
            from reportlab.graphics.charts.linecharts import HorizontalLineChart
            
            elements.append(Paragraph("Exam Performance History", styles['Heading2']))
            
            if chart_values:
                d = Drawing(400, 200)
                lc = HorizontalLineChart()
                lc.x = 30
                lc.y = 50
                lc.height = 125
                lc.width = 350
                lc.data = [chart_values]
                lc.categoryAxis.categoryNames = chart_labels
                lc.categoryAxis.labels.boxAnchor = 'n'
                lc.categoryAxis.labels.angle = 30
                lc.categoryAxis.labels.dy = -10
                lc.valueAxis.valueMin = 0
                lc.valueAxis.valueMax = 100
                lc.valueAxis.valueStep = 20
                d.add(lc)
                elements.append(d)
                elements.append(Spacer(1, 20))
            
            # Recent exams
            elements.append(Paragraph("Recent Exam History", styles['Heading2']))
            exam_data = [["Exam", "Score", "Date", "Status"]]
            for attempt in attempts[:10]:
                exam_data.append([
                    attempt.exam.title[:30],
                    f"{attempt.percentage}%",
                    attempt.started_at.strftime("%Y-%m-%d"),
                    "Passed" if attempt.is_passed else "Failed"
                ])
            t2 = Table(exam_data)
            t2.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), font_bold),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ]))
            elements.append(t2)
        else:
            elements.append(Paragraph("No exam data available for this student.", styles['Normal']))
        
        doc.build(elements)
        buffer.seek(0)
        
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename=student_{student.pk}_{timezone.now().date()}.pdf'
        return response
