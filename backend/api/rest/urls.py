from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from . import views

app_name = "rest"

urlpatterns = [
  path("", views.ApiRootView.as_view(), name="root"),
  path("snapshot/", views.SnapshotInfoView.as_view(), name="snapshot"),
  path("meetings/", views.MeetingListView.as_view(), name="meetings"),
  path("races/", views.RaceListView.as_view(), name="races"),
  path("races/<int:race_id>/", views.RaceDetailView.as_view(), name="race"),
  path("runners/", views.RunnerListView.as_view(), name="runners"),
  path("undervalued/", views.UndervaluedView.as_view(), name="undervalued"),
  path("courses/", views.CourseListView.as_view(), name="courses"),
  path("courses/<int:course_id>/", views.CourseDetailView.as_view(), name="course"),
  path("horses/", views.HorseListView.as_view(), name="horses"),
  path("horses/<int:horse_id>/", views.HorseDetailView.as_view(), name="horse"),
  path("jockeys/", views.JockeyListView.as_view(), name="jockeys"),
  path("jockeys/<int:jockey_id>/", views.JockeyDetailView.as_view(), name="jockey"),
  path("trainers/", views.TrainerListView.as_view(), name="trainers"),
  path("trainers/<int:trainer_id>/", views.TrainerDetailView.as_view(), name="trainer"),
  path("scorecard/", views.ScorecardView.as_view(), name="scorecard"),
  path("calibration/", views.CalibrationView.as_view(), name="calibration"),
  path("schema/", SpectacularAPIView.as_view(), name="schema"),
  path("docs/", SpectacularSwaggerView.as_view(url_name="rest:schema"), name="docs"),
]
