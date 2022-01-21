from django.conf import settings
from django.urls import path, re_path, include
from django.views.generic.base import RedirectView

from . import views, slashcommands

urlpatterns = [
    path("", views.index, name="index"),
    path('accounts/', include('django.contrib.auth.urls')),
    path("register", views.register, name="register"),
    path("authored", views.authored, name="authored"),

    path("all", views.all_puzzles, name="all"),
    path("bystatus", views.bystatus, name="bystatus"),
    path("byround", views.byround, name="byround"),
    path("byround/eic", views.byround_eic, name="byround_eic"),

    path("export", views.export, name="export"),
    path("check", views.check_metadata, name="check_metadata"),

    # TODO This should be a redirect
    # Doing so on this deploy will break for anyone who was filling out the new
    # puzzle page at the time, so after this is deployed we can change it.
    path("new", views.puzzle_new),
    path("puzzle/new", views.puzzle_new, name="puzzle_new"),
    path("puzzle/<int:id>", views.puzzle, name="puzzle"),
    path("puzzle/<int:id>/hints", views.puzzle_hints, name="puzzle_hints"),
    path("puzzle/<int:id>/feedback", views.puzzle_feedback, name="puzzle_feedback"),
    path("puzzle/feedback_puzzle_<int:id>.csv", views.puzzle_feedback_csv, name="puzzle_feedback_csv"),
    path("puzzle/<int:id>/edit", views.puzzle_edit, name="puzzle_edit"),
    path("puzzle/<int:id>/people", views.puzzle_people, name="puzzle_people"),
    path("puzzle/<int:id>/other_credits", views.puzzle_other_credits, name="puzzle_other_credits"),
    path("puzzle/<int:puzzle_id>/other_credits/<int:id>", views.puzzle_other_credit_update, name="puzzle_other_credit_update"),
    path("puzzle/<int:id>/answers", views.puzzle_answers, name="puzzle_answers"),
    path("puzzle/<int:id>/tags", views.puzzle_tags, name="puzzle_tags"),
    path("puzzle/<int:id>/postprod", views.puzzle_postprod, name="puzzle_postprod"),
    path("puzzle/<int:id>/metadata.json", views.puzzle_postprod_metadata, name="puzzle_postprod_metadata"),
    path("puzzle/<int:id>/hints.json", views.puzzle_hints_json, name="puzzle_hints_json"),
    path("puzzle/<int:id>/escape", views.puzzle_escape, name="puzzle_escape"),
    re_path(r"^puzzle/(?P<id>\d+)/support/(?P<team>ART|ACC|TECH)$", views.support_by_puzzle_id, name="support_by_puzzle_id"),
    path("puzzle/<int:id>/support", views.support_by_puzzle, name="support_by_puzzle"),
    path("puzzle/<int:id>/<slug:slug>", views.puzzle, name="puzzle_w_slug"),
    path("puzzle/postprodded/<int:id>.zip", views.postprod_zip, name="postprod_zip"),
    path("puzzle/feedback/all", views.puzzle_feedback_all, name="all_feedback"),
    path("puzzle/feedback/all_feedback.csv", views.puzzle_feedback_all_csv, name="all_feedback_csv"),
    path("hints", views.all_hints, name="all_hints"),

    path("support/all", views.support_all, name="all_support"),

    path("comment/<int:id>/edit", views.edit_comment, name="edit_comment"),
    path("hint/<int:id>", views.edit_hint, name="edit_hint"),
    path("testsolve", views.testsolve_main, name="testsolve_main"),
    path("my-spoiled", views.my_spoiled, name="my_spoiled"),
    path("testsolve_history", views.testsolve_history, name="testsolve_history"),
    path("testsolve_finder", views.testsolve_finder, name="testsolve_finder"),
    path("testsolve/<int:id>", views.testsolve_one, name="testsolve_one"),
    path("testsolve/<int:id>/feedback", views.testsolve_feedback, name="testsolve_feedback"),
    path("testsolve/<int:id>/finish", views.testsolve_finish, name="testsolve_finish"),
    path("testsolve_csv/testsolve_<int:id>.csv", views.testsolve_csv, name="testsolve_csv"),
    path("postprod", views.postprod, name="postprod"),
    path("postprod/all", views.postprod_all, name="postprod_all"),
    path("factcheck", views.factcheck, name="factcheck"),

    path("eic", views.eic, name="eic"),
    path("awaiting_editor", RedirectView.as_view(url='/eic'), name="awaiting_editor"),
    path("triage", views.triage, name="triage"),

    path("needs_editor", views.needs_editor, name="needs_editor"), # leftover, we're not using yet
    path("editor_overview", views.editor_overview, name='editor_overview'),

    path("rounds", views.rounds, name="rounds"),
    path("answer/<int:id>", views.edit_answer, name="edit_answer"),
    path("rounds/<int:id>", views.rounds, name="round"),
    path("rounds/<int:id>/edit", views.edit_round, name="edit_round"),
    path("rounds/<int:id>/bulk_add", views.bulk_add_answers, name="bulk_add_answers"),
    path("answers", views.all_answers, name="all_answers"),
    path("random_answers", views.random_answers, name="random_answers"),

    path("users", views.users, name="users"),
    path("users_statuses", views.users_statuses, name="users_statuses"),
    path("user/<str:username>", views.user, name="user"),
    path("account", views.account, name="account"),
    path("account/oauth2", views.oauth2_link, name="oauth2_link"),
    path("tags", views.tags, name="tags"),
    path("spoiled", views.spoiled, name="spoiled"),
    path("statistics", views.statistics, name="statistics"),

    path("tags/new", views.new_tag, name="new_tag"),
    path("tags/<int:id>", views.single_tag, name="single_tag"),
    path("tags/<int:id>/edit", views.edit_tag, name="edit_tag"),

    path("docs", views.docs, name="docs"),
    path("process", views.process, name="process"),

    path("preview_markdown", views.preview_markdown, name="preview_markdown"),

    path("api/", include("puzzle_editing.api.urls")),
    path("slashcommands", slashcommands.slashCommandHandler),
]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns.append(path('__debug__/', include(debug_toolbar.urls)))
    urlpatterns += [
        re_path(r'^static/(?P<path>.*)$', views.serve),
    ]
