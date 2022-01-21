import datetime
import os
import random
import re
from django.forms.fields import MultipleChoiceField
import requests
import typing as t
import traceback
import csv
import json

import pydantic

import django.forms as forms
import django.urls as urls
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db.models import Avg
from django.db.models import Count
from django.db.models import Exists
from django.db.models import F
from django.db.models import Max
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models import Subquery
from django.db.models.functions import Lower
from django.http import (
    JsonResponse,
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
)
from django.shortcuts import get_object_or_404, resolve_url
from django.shortcuts import redirect
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
from django.utils.http import urlencode
from django.views.decorators.csrf import csrf_exempt
from django.views.static import serve
from django.conf import settings

import puzzle_editing.messaging as messaging
import puzzle_editing.status as status
import puzzle_editing.utils as utils
from puzzle_editing.graph import curr_puzzle_graph_b64
from puzzle_editing import models as m
from puzzle_editing.models import CommentReaction
from puzzle_editing.models import get_user_role
from puzzle_editing.models import Hint
from puzzle_editing.models import is_author_on
from puzzle_editing.models import is_editor_on
from puzzle_editing.models import is_factchecker_on
from puzzle_editing.models import is_postprodder_on
from puzzle_editing.models import is_spoiled_on
from puzzle_editing.models import Puzzle
from puzzle_editing.models import PuzzleCredit
from puzzle_editing.models import PuzzleAnswer
from puzzle_editing.models import PuzzleComment
from puzzle_editing.models import PuzzlePostprod
from puzzle_editing.models import PuzzleTag
from puzzle_editing.models import PuzzleVisited
from puzzle_editing.models import Round
from puzzle_editing.models import SiteSetting
from puzzle_editing.models import StatusSubscription
from puzzle_editing.models import SupportRequest
from puzzle_editing.models import TestsolveGuess
from puzzle_editing.models import TestsolveParticipation
from puzzle_editing.models import TestsolveSession
from puzzle_editing.models import User
import puzzle_editing.discord_integration as discord
from .discord import TextChannel, Permission as DiscordPermission

from .view_helpers import external_puzzle_url

# This file is so full of redefined-outer-name issues it swamps real problems.
# It has them because e.g. there's a fn called user() and also lots of fns with
# vars called 'user'.

# pylint: disable=redefined-outer-name
# pylint: disable=redefined-builtin


def get_sessions_with_joined_and_current(user):
    return TestsolveSession.objects.annotate(
        joined=Exists(
            TestsolveParticipation.objects.filter(
                session=OuterRef("pk"),
                user=user,
            )
        ),
        current=Exists(
            TestsolveParticipation.objects.filter(
                session=OuterRef("pk"),
                user=user,
                ended=None,
            )
        ),
    )


def get_full_display_name(user):
    return "{}{}".format((user.credits_name or user.display_name or user.username), (f" (@{user.discord_username})" if user.discord_username else "")).strip()


def get_credits_name(user):
    return user.credits_name or user.display_name or user.username


def index(request):
    user = request.user

    announcement = SiteSetting.get_setting("ANNOUNCEMENT")

    if not request.user.is_authenticated:
        return render(request, "index_not_logged_in.html")

    blocked_on_author_puzzles = Puzzle.objects.filter(
        authors=user,
        status__in=status.STATUSES_BLOCKED_ON_AUTHORS,
    )
    blocked_on_editor_puzzles = Puzzle.objects.filter(
        editors=user,
        status__in=status.STATUSES_BLOCKED_ON_EDITORS,
    )
    current_sessions = TestsolveSession.objects.filter(participations__in=TestsolveParticipation.objects.filter(user=request.user,ended__isnull=True).all())

    factchecking = Puzzle.objects.filter(
        status=status.NEEDS_FACTCHECK, factcheckers=user
    )
    postprodding = Puzzle.objects.filter(
        status=status.NEEDS_POSTPROD, postprodders=user
    )
    inbox_puzzles = (
        user.spoiled_puzzles.exclude(status=status.DEAD)
        .annotate(
            last_comment_date=Max("comments__date"),
            last_visited_date=Subquery(
                PuzzleVisited.objects.filter(puzzle=OuterRef("pk"), user=user).values(
                    "date"
                )
            ),
        )
        .filter(
            Q(last_visited_date__isnull=True)
            | Q(last_comment_date__gt=F("last_visited_date"))
        )
    )

    return render(
        request,
        "index.html",
        {
            "announcement": announcement,
            "blocked_on_author_puzzles": blocked_on_author_puzzles,
            "blocked_on_editor_puzzles": blocked_on_editor_puzzles,
            "current_sessions": current_sessions,
            "factchecking": factchecking,
            "inbox_puzzles": inbox_puzzles,
            "postprodding": postprodding,
        },
    )


@login_required
def docs(request):
    return render(request, "docs.html", {})

@login_required
def process(request):
    return render(request, "process.html", {})


class MarkdownTextarea(forms.Textarea):
    template_name = "widgets/markdown_textarea.html"


class SupportForm(forms.ModelForm):
    def __init__(self, user, *args, **kwargs):
        super(SupportForm, self).__init__(*args, **kwargs)
        if not user.is_staff:
            del self.fields["discord_channel_id"]
        self.fields["authors"] = UserMultipleChoiceField(initial=user)
        self.fields["notes"].label = "Answer & Round requests"

    class Meta:
        model = SupportRequest
        fields = [
            "status",
            "author_notes",
            "team_notes"
        ]
        widgets = {
            "status": forms.Textarea(attrs={'class':'textarea', 'rows': 6}),
            "author_notes": forms.TextInput(attrs={'class':'input'}),
            "team_notes": forms.Textarea(attrs={'class':'textarea', 'rows': 6}),
        }


class SupportRequestAuthorNotesForm(forms.ModelForm):
    author_notes = forms.CharField(
        widget=MarkdownTextarea,
        required=False
    )

    class Meta:
        model = SupportRequest
        fields = ["author_notes", "status"]

class SupportRequestTeamNotesForm(forms.ModelForm):
    team_notes = forms.CharField(
        widget=MarkdownTextarea,
        required=False
    )

    class Meta:
        model = SupportRequest
        fields = ["team_notes", "status"]

class SupportRequestStatusForm(forms.ModelForm):
    class Meta:
        model = SupportRequest
        fields = ["status"]

# based on UserCreationForm from Django source
class RegisterForm(forms.ModelForm):
    """
    A form that creates a user, with no privileges, from the given username and
    password.
    """

    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={'class':'input'}),
    )
    password2 = forms.CharField(
        label="Password confirmation",
        widget=forms.PasswordInput(attrs={'class':'input'}),
        help_text="Enter the same password as above, for verification.",
    )
    email = forms.EmailField(
        label="Email address",
        required=False,
        help_text="Optional, but you'll get useful email notifications.",
        widget=forms.EmailInput(attrs={'class':'input'}),
    )

    site_password = forms.CharField(
        label="Site password",
        widget=forms.PasswordInput(attrs={'class':'input'}),
        help_text="Get this password from the Discord.",
    )

    display_name = forms.CharField(
        label="Display name", required=False, help_text="(optional)",
        widget=forms.TextInput(attrs={'class':'input'}),
    )
    credits_name = forms.CharField(
        label="Credits name",
        help_text="(required) Name you want displayed in the credits for hunt and author field on your puzzles, likely your full name",
        widget=forms.TextInput(attrs={'class':'input'}),
    )
    bio = forms.CharField(
        widget=MarkdownTextarea(attrs={'class':'textarea','rows':6}),
        required=False,
        help_text="(optional) Tell us about yourself. What kinds of puzzle genres or subject matter do you like?",
    )

    class Meta:
        model = User
        fields = ("username", "email", "display_name", "bio", "credits_name")
        widgets = {
            "username": forms.TextInput(attrs={'class':'input'}),
        }



    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError(
                "The two password fields didn't match.",
                code="password_mismatch",
            )
        return password2

    def clean_site_password(self):
        site_password = self.cleaned_data.get("site_password")
        if site_password and site_password != settings.SITE_PASSWORD:
            raise forms.ValidationError(
                "The site password was incorrect.",
                code="password_mismatch",
            )
        return site_password

    def save(self, commit=True):
        user = super(RegisterForm, self).save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


def register(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect(urls.reverse("index"))
        else:
            return render(request, "register.html", {"form": form})
    else:
        form = RegisterForm()
        return render(request, "register.html", {"form": form})


class AccountForm(forms.Form):
    email = forms.EmailField(
        label="Email address",
        required=False,
        help_text="Optional, but you'll get useful email notifications.",
        widget=forms.TextInput(attrs={'class':'input'}),
    )

    display_name = forms.CharField(
        label="Display name",
        required=False,
        widget=forms.TextInput(attrs={'class':'input'}),
    )

    credits_name = forms.CharField(
        label="Credits name",
        help_text="(required) Name you want displayed in the credits for hunt and author field on your puzzles, likely your full name",
        widget=forms.TextInput(attrs={'class':'input'}),
    )

    bio = forms.CharField(
        required=False,
        help_text="(optional) Tell us about yourself. What kinds of puzzle genres or subject matter do you like?",
        widget=MarkdownTextarea(attrs={'class':'textarea', 'rows': 6}),
    )
    keyboard_shortcuts = forms.BooleanField(
        label="Enable keyboard shortcuts",
        required=False,
        help_text="On puzzle pages only. Press ? for help.",
    )


@login_required
def account(request):
    user = request.user
    if request.method == "POST":
        form = AccountForm(request.POST)
        if form.is_valid():
            user.email = form.cleaned_data["email"]
            user.display_name = form.cleaned_data["display_name"]
            user.bio = form.cleaned_data["bio"]
            user.credits_name = form.cleaned_data["credits_name"]
            user.enable_keyboard_shortcuts = form.cleaned_data["keyboard_shortcuts"]
            user.save()
            return render(request, "account.html", {"form": form, "success": True})
        else:
            return render(request, "account.html", {"form": form, "success": None})
    else:
        form = AccountForm(
            initial={
                "email": user.email,
                "display_name": user.display_name,
                "credits_name": user.credits_name or user.display_name or user.username,
                "bio": user.bio,
                "keyboard_shortcuts": user.enable_keyboard_shortcuts,
            }
        )
        return render(request, "account.html", {"form": form, "success": None})

@login_required
def oauth2_link(request):
    user = request.user
    if request.method == "POST":
        if 'unlink-discord' in request.POST:
            if user.discord_user_id or user.discord_username:
                if user.avatar_url.startswith("https://cdn.discordapp.com/"):
                    user.avatar_url = ""
                user.discord_user_id = ""
                user.discord_username = ""
                user.save()
        elif 'refresh-discord' in request.POST:
            member = discord.get_client().get_member_by_id(user.discord_user_id)
            if member:
                user.discord_username = "{}#{}".format(member['user']['username'], member['user']['discriminator'])
                user.discord_nickname = member['nick'] or ""
                user.save()
                user.avatar_url = user.get_avatar_url_via_discord(member['user']['avatar'])
                user.save()

        return redirect("/account")

    if 'code' in request.GET or 'error' in request.GET:
    # if 'state' in request.GET and 'session' in request.session and request.GET['state'] == request.session['discord_state']:
        # handles the discord oauth_callback
        del request.session['discord_state']
        if 'error' in request.GET:
            return render(request, "account.html")
        elif 'code' in request.GET:
            post_payload = {
                'client_id': settings.DISCORD_CLIENT_ID,
                'client_secret': settings.DISCORD_CLIENT_SECRET,
                'grant_type': 'authorization_code',
                'code': request.GET['code'],
                'redirect_uri': request.build_absolute_uri(urls.reverse("oauth2_link")),
                'scope': settings.DISCORD_OAUTH_SCOPES
            }

            heads = {
                'Content-Type': 'application/x-www-form-urlencoded'
            }

            r = requests.post("https://discord.com/api/oauth2/token", data=post_payload, headers=heads)

            response = r.json()
            user_headers = {
                'Authorization': "Bearer {}".format(response['access_token'])
            }
            user_info = requests.get("https://discord.com/api/v8/users/@me", headers=user_headers)

            user_data = user_info.json()

            user.discord_user_id = user_data['id']

            user.discord_username = "{}#{}".format(user_data['username'], user_data['discriminator'])
            if discord.enabled():
                c = discord.get_client()
                discord.init_perms(c, user)
                member = c.get_member_by_id(user.discord_user_id)
                if member:
                    user.discord_nickname = member['nick'] or ""

            user.save()
            user.avatar_url = user.get_avatar_url_via_discord(member['user']['avatar'] or '') or ''
            user.save()

        return redirect('/account')

    if user.discord_user_id:
        return redirect('/account')
    else:
        state = abs(hash(datetime.datetime.utcnow().isoformat()))
        request.session['discord_state'] = state

        params = {
            'response_type':'code',
            'client_id': settings.DISCORD_CLIENT_ID,
            'state': state,
            'scope': settings.DISCORD_OAUTH_SCOPES,
            'redirect_uri': request.build_absolute_uri(urls.reverse("oauth2_link"))
        }

        oauth_url = "https://discord.com/api/oauth2/authorize?" + urlencode(params)
        return redirect(oauth_url)

class UserCheckboxSelectMultiple(forms.CheckboxSelectMultiple):
    template_name = "widgets/user_checkbox_select_multiple.html"


class UserMultipleChoiceField(forms.ModelMultipleChoiceField):
    def __init__(self, *args, **kwargs):
        orderings = []
        # if kwargs.get("editors_first", False):
        #     orderings.append("-user_permissions")
        #     del kwargs["editors_first"]
        orderings.append(Lower("display_name"))
        if "editors_only" in kwargs:
            kwargs["queryset"] = User.objects.filter(groups__name__in=['Editor']).order_by(*orderings)
            del kwargs["editors_only"]
        if "queryset" not in kwargs:
            kwargs["queryset"] = User.objects.all().order_by(*orderings)
        if "widget" not in kwargs:
            kwargs["widget"] = UserCheckboxSelectMultiple()
        super(UserMultipleChoiceField, self).__init__(*args, **kwargs)

    def label_from_instance(self, obj):
        return get_full_display_name(obj)

class TestsolveFinderForm(forms.Form):
    def __init__(self, user, *args, **kwargs):
        super(TestsolveFinderForm, self).__init__(*args, **kwargs)
        self.fields["solvers"] = UserMultipleChoiceField(initial=user)

    solvers = forms.CheckboxSelectMultiple()

class PuzzleInfoForm(forms.ModelForm):
    def __init__(self, user, *args, **kwargs):
        super(PuzzleInfoForm, self).__init__(*args, **kwargs)
        if not user.is_staff:
            del self.fields["discord_channel_id"]
        self.fields["authors"] = UserMultipleChoiceField(initial=user)
        self.fields["notes"].label = "Answer & Round requests"
        self.fields["authors_addl"].label = "Additional authors"

    class Meta:
        model = Puzzle
        fields = [
            "name",
            "codename",
            "authors",
            "authors_addl",
            "discord_channel_id",
            "summary",
            "description",
            "editor_notes",
            "notes",
            "is_meta",
        ]
        widgets = {
            "authors": forms.CheckboxSelectMultiple(),
            "name": forms.TextInput(attrs={'class':'input'}),
            "authors_addl": forms.TextInput(attrs={'class':'input'}),
            "codename": forms.TextInput(attrs={'class':'input'}),
            "summary": forms.Textarea(attrs={'class':'textarea', 'rows': 6}),
            "description": forms.Textarea(attrs={'class':'textarea', 'rows': 6}),
            "editor_notes": forms.TextInput(attrs={'class':'input'}),
            "notes": forms.Textarea(attrs={'class':'textarea', 'rows': 6}),
            "is_meta": forms.CheckboxInput(),
        }


@login_required
def puzzle_new(request):
    user = request.user

    if request.method == "POST":
        form = PuzzleInfoForm(user, request.POST)
        if form.is_valid():
            puzzle: Puzzle = form.save(commit=False)
            puzzle.status_mtime = datetime.datetime.now()
            puzzle.save()
            form.save_m2m()
            puzzle.spoiled.add(*puzzle.authors.all())
            if discord.enabled():
                c = discord.get_client()
                url = external_puzzle_url(request, puzzle)
                tc = None
                if puzzle.discord_channel_id:
                    # if you put in an invalid discord ID, we just ignore it
                    # and create a new channel for you.
                    tc = discord.get_channel(c, puzzle)
                if tc is None:
                    tc = discord.build_puzzle_channel(url, puzzle, c.guild_id)
                else:
                    tc = discord.sync_puzzle_channel(puzzle, tc, url=url)
                tc.make_private()
                author_tags = discord.get_tags(puzzle.authors.all(), False)
                cat = status.get_display(puzzle.status)
                tc = c.save_channel_to_cat(tc, cat)
                puzzle.discord_channel_id = tc.id
                puzzle.save()
                c.post_message(
                    tc.id,
                    f"This puzzle has been created in status **{cat}**!\n"
                    f"Access it at {url}\n"
                    f"Author(s): {', '.join(author_tags)}"
                )
            add_comment(
                request=request,
                puzzle=puzzle,
                author=user,
                is_system=True,
                send_email=False,
                content="Created puzzle",
                status_change="II"
            )

            return redirect(urls.reverse("authored"))
        else:
            return render(request, "new.html", {"form": form})
    else:
        form = PuzzleInfoForm(request.user)
        return render(request, "new.html", {"form": form})


@login_required
def all_answers(request):
    user = request.user
    if request.method == "POST":
        if "spoil_on" in request.POST:
            get_object_or_404(Round, id=request.POST["spoil_on"]).spoiled.add(user)
        return redirect(urls.reverse("all_answers"))
    rounds = [
        {
            "id": round.id,
            "name": round.name,
            "description": round.description,
            "spoiled": round.spoiled.filter(id=user.id).exists(),
            "answers": [
                {
                    "answer": answer.answer,
                    "id": answer.id,
                    "notes": answer.notes,
                    "puzzles": answer.puzzles.all(),
                }
                for answer in round.answers.all().order_by(Lower('answer'))
            ],
            "form": AnswerForm(round),
            "editors": round.editors.all().order_by(Lower('display_name')),
        }
        for round in Round.objects.all().prefetch_related('editors', 'answers').order_by(Lower('name'))
    ]

    return render(
        request, "all_answers.html", { "rounds": rounds },
    )

@login_required
def random_answers(request):
    answers = list(PuzzleAnswer.objects.filter(puzzles__isnull=True))
    available = random.sample(answers, min(3, len(answers)))
    return render(request, "random_answers.html", {"answers": available})


# TODO: "authored" is now a misnomer
@login_required
def authored(request):
    puzzles = Puzzle.objects.filter(authors=request.user)
    editing_puzzles = Puzzle.objects.filter(editors=request.user)
    return render(
        request,
        "authored.html",
        {
            "puzzles": puzzles,
            "editing_puzzles": editing_puzzles,
        },
    )


@login_required
def all_puzzles(request):
    puzzles = Puzzle.objects.all().prefetch_related("authors").order_by("name")
    return render(request, "all.html", {"puzzles": puzzles})


@login_required
def bystatus(request):
    all_puzzles = Puzzle.objects.exclude(status__in=[
        status.INITIAL_IDEA,
        status.DEFERRED,
        status.DEAD,
    ]).prefetch_related('authors', 'tags')

    puzzles = []
    for puzzle in all_puzzles:
        puzzle_obj = {
            "puzzle": puzzle,
            # "authors": [a for a in puzzle.authors.all()],
            "status": "{} {}".format(status.get_emoji(puzzle.status), status.get_display(puzzle.status))
        }
        puzzles.append(puzzle_obj)

    # sorted_puzzles = sorted(needs_postprod, key=lambda a: (status.STATUSES.index(a.status), a.name))
    puzzles = sorted(puzzles, key=lambda x: status.get_status_rank(x['puzzle'].status))

    return render(request, "bystatus.html", {"puzzles": puzzles})
    # return render(request, "postprod_all.html", context)


class PuzzleCommentForm(forms.Form):
    content = forms.CharField(widget=MarkdownTextarea)


class PuzzleContentForm(forms.ModelForm):
    class Meta:
        model = Puzzle
        fields = ["content"]
        widgets = {
            "content": forms.Textarea(attrs={"class": "textarea"}),
        }


class PuzzleSolutionForm(forms.ModelForm):
    class Meta:
        model = Puzzle
        fields = ["solution"]
        widgets = {
            "solution": forms.Textarea(attrs={"class": "textarea"}),
        }


class PuzzlePriorityForm(forms.ModelForm):
    class Meta:
        model = Puzzle
        fields = ["priority"]


class PuzzlePostprodForm(forms.ModelForm):
    class Meta:
        model = PuzzlePostprod
        exclude = ["authors"]
        widgets = {
            "puzzle": forms.HiddenInput(),
            "zip_file": forms.FileInput(attrs={"accept": ".zip"}),
            # "authors": forms.Textarea(attrs={"rows": 3, "cols": 40}),
        }

    def __init__(self, *args, **kwargs):
        super(PuzzlePostprodForm, self).__init__(*args, **kwargs)
        self.fields["zip_file"].required = False

    def clean_zip_file(self):
        zip_file = self.cleaned_data["zip_file"]
        puzzle = self.cleaned_data["puzzle"]
        # if not zip_file and not puzzle.has_postprod():
        #     raise ValidationError("This field is required the first time you postprod.")
        return zip_file


class PuzzleHintForm(forms.ModelForm):
    class Meta:
        model = Hint
        exclude = []
        widgets = {
            "order": forms.TextInput(attrs={'class':'input','placeholder':'e.g. 10.1'}),
            "keywords": forms.TextInput(attrs={'class':'input','placeholder':'e.g. extraction'}),
            "puzzle": forms.HiddenInput(),
            "content": forms.Textarea(attrs={'class':'textarea', 'rows': 4})
        }

def add_comment(
    *,
    request,
    puzzle: Puzzle,
    author: User,
    is_system: bool,
    content: str,
    testsolve_session=None,
    send_email: bool = True,
    status_change: str = "",
    c: discord.Client = None,
    ch: discord.TextChannel = None,

):
    comment = PuzzleComment(
        puzzle=puzzle,
        author=author,
        testsolve_session=testsolve_session,
        is_system=is_system,
        content=content,
        status_change=status_change,
    )
    comment.save()

    if testsolve_session:
        subject = "New comment on {} (testsolve #{})".format(
            puzzle.spoiler_free_title(), testsolve_session.id
        )
        emails = testsolve_session.get_emails(exclude_emails=(author.email,))
    else:
        subject = "New comment on {}".format(puzzle.spoiler_free_title())
        emails = puzzle.get_emails(exclude_emails=(author.email,))

    if send_email:
        messaging.send_mail_wrapper(
            subject,
            "new_comment_email",
            {
                "request": request,
                "puzzle": puzzle,
                "author": author,
                "content": content,
                "is_system": is_system,
                "testsolve_session": testsolve_session,
                "status_change": status.get_display(status_change)
                if status_change
                else None,
            },
            emails,
        )

    if content and not is_system and not testsolve_session:
        if c is not None and ch is not None:
            name = author.credits_name
            if author.discord_user_id:
                name = discord.tag_id(author.discord_user_id)
            c.post_message(ch.id, f"{name} (posted a comment): {content}")


class DiscordData(pydantic.BaseModel):
    '''Data about a puzzle's discord channel, for display on a page.'''
     # Whether discord is enabled, disabled, or supposedly enabled but we
     # couldn't fetch data
    status: t.Literal["enabled", "disabled", "broken"]
    guild_id: str = None  # For URL generation
    channel_id: str = None
    name: str = None
    public: bool = None
    nvis: int = None  # Number of people with explicit view permission
    i_can_see: bool = None  # Whether the current user has view permission
    error: str = None

    @property
    def exists(self):
        '''True iff discord is working and we have a channel_id.

        The assumption is that whoever creates this object will have checked
        whether the channel_id actually exists already, and won't set one here
        if the one we have is invalid.
        '''
        return self.status == 'enabled' and self.guild_id and self.channel_id

    @property
    def url(self):
        '''URL for the discord channel, or None if there isn't one.'''
        if not self.guild_id or not self.channel_id:
            return None
        return ("discord://discord.com/channels/"
                f"{self.guild_id}/{self.channel_id}")

    @classmethod
    def from_channel(cls, tc: discord.TextChannel, me: User) -> "DiscordData":
        '''Parse a TextChannel+User into a DiscordData'''
        myid = me.discord_user_id
        vis = False
        nvis = 0
        for uid, overwrite in tc.perms.users.items():
            if DiscordPermission.VIEW_CHANNEL in overwrite.allow:
                nvis += 1
                if uid == myid:
                    vis = True
        return cls(
            status="enabled",
            name=tc.name,
            guild_id=tc.guild_id,
            public=tc.is_public(),
            channel_id=tc.id,
            nvis=nvis,
            i_can_see=vis)

@login_required
def all_hints(request: HttpRequest):
    return render(
        request,
        "all_hints.html",
        {
            "puzzles": Puzzle.objects.all()
        }
    )

@login_required
def puzzle_hints(request: HttpRequest, id):
    puzzle: Puzzle = get_object_or_404(Puzzle, id=id)
    if request.method == "POST" and "add_hint" in request.POST:
        form = PuzzleHintForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect(urls.reverse("puzzle_hints", kwargs={'id':id}))


    return render(
            request,
            "puzzle_hints.html",
            {
                "hint_form": PuzzleHintForm(initial={"puzzle": puzzle}),
                "puzzle": puzzle
            }
    )

@login_required
def puzzle_other_credits(request: HttpRequest, id):
    puzzle: Puzzle = get_object_or_404(Puzzle, id=id)
    if request.method == "POST":
        form = PuzzleOtherCreditsForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect(urls.reverse("puzzle_other_credits", kwargs={'id':puzzle.id}))
    else:
        form = PuzzleOtherCreditsForm(initial={"puzzle": puzzle})

    return render(
        request,
        "puzzle_other_credits.html",
        {
            "puzzle": puzzle,
            "other_credit_form": form
        }
    )

@login_required
def puzzle_other_credit_update(request: HttpRequest, id, puzzle_id):
    other_credit = get_object_or_404(PuzzleCredit, id=id)
    if request.method == "POST":
        if "delete_oc" in request.POST:
            other_credit.delete()
        else:
            form = PuzzleOtherCreditsForm(request.POST, instance=other_credit)
            if form.is_valid():
                form.save()

        return redirect(urls.reverse("puzzle_other_credits", kwargs={'id':puzzle_id}))

    return render(
        request,
        "puzzle_other_credit_edit.html",
        {
            "other_credit": other_credit,
            "puzzle": other_credit.puzzle,
            "other_credit_form": PuzzleOtherCreditsForm(instance=other_credit),
        }
    )

@login_required
def puzzle(request: HttpRequest, id, slug=None):
    puzzle: Puzzle = get_object_or_404(Puzzle, id=id)
    if slug == None:
        new_slug = puzzle.slug
        if new_slug:
            return redirect(urls.reverse("puzzle_w_slug", kwargs={'id':id, 'slug':new_slug}))

    user: User = request.user

    vis, vis_created = PuzzleVisited.objects.get_or_create(puzzle=puzzle, user=user)
    if not vis_created:
        # update the auto_now=True DateTimeField anyway
        vis.save()

    def add_system_comment_here(message, status_change=""):
        add_comment(
            request=request,
            puzzle=puzzle,
            author=user,
            is_system=True,
            send_email=False,
            content=message,
            status_change=status_change,
        )

    if request.method == "POST":
        form: t.Union[forms.Form, forms.ModelForm] = None
        c: t.Optional[discord.Client] = None
        ch: t.Optional[TextChannel] = None
        our_d_id: str = user.discord_user_id
        disc_ops = {
            "subscribe-me", "unsubscribe-me",
            "discord-public", "discord-private",
            "resync-discord"}
        if discord.enabled():
            # Preload the discord client and current channel data.
            c, ch = discord.get_client_and_channel(puzzle)
            if c and puzzle.discord_channel_id and not ch:
                # If the puzzle has a channel_id but it doesn't exist, clear it
                # here to save time in the future.
                puzzle.discord_channel_id = ""
                puzzle.save()
        if "do_spoil" in request.POST:
            puzzle.spoiled.add(user)
        elif set(request.POST) & disc_ops:
            if c and ch:
                newcat = None
                if "subscribe-me" in request.POST:
                    ch.add_visibility([our_d_id] if our_d_id else ())
                elif 'unsubscribe-me' in request.POST:
                    ch.rm_visibility([our_d_id] if our_d_id else ())
                elif "discord-public" in request.POST:
                    ch.make_public()
                elif "discord-private" in request.POST:
                    ch.make_private()
                elif 'resync-discord' in request.POST:
                    # full resync of all attributes
                    url = external_puzzle_url(request, puzzle)
                    discord.sync_puzzle_channel(puzzle, ch, url)
                    newcat = status.get_display(puzzle.status)
                if newcat is not None:
                    c.save_channel_to_cat(ch, newcat)
                else:
                    c.save_channel(ch)
            else:
                return HttpResponseBadRequest("<b>Discord is not enabled.</b>")
        elif "link-discord" in request.POST:
            if not c:
                return HttpResponseBadRequest("<b>Discord is not enabled.</b>")
            if ch is None:
                url = external_puzzle_url(request, puzzle)
                tc = discord.build_puzzle_channel(url, puzzle, c.guild_id)
                cat = status.get_display(puzzle.status)
                tc = c.save_channel_to_cat(tc, cat)
                puzzle.discord_channel_id = tc.id
                puzzle.save()
                author_tags = discord.get_tags(puzzle.authors.all(), False)
                editor_tags = discord.get_tags(puzzle.editors.all(), False)
                msg = [
                    f"This channel was just created for puzzle {puzzle.name}!",
                    f"Access it at {url}",
                ]
                if author_tags:
                    msg.append(f"Author(s): {', '.join(author_tags)}")
                if editor_tags:
                    msg.append(f"Editor(s): {', '.join(editor_tags)}")
                c.post_message(tc.id, '\n'.join(msg))
        elif "change_status" in request.POST:
            new_status = request.POST["change_status"]
            status_display = status.get_display(new_status)
            if new_status != puzzle.status:
                puzzle.status = new_status
                puzzle.save()
                if c and ch:
                    if new_status != status.INITIAL_IDEA:
                        ch.make_private()
                    c.save_channel_to_cat(ch, status_display)
                    c.post_message(
                        ch.id,
                        f"This puzzle is now **{status_display}**.")

            add_system_comment_here("", status_change=new_status)

            if puzzle.status in [status.DEAD, status.DEFERRED]:
                puzzle.answers.clear()

            if new_status == status.TESTSOLVING:
                ### SEND CUSTOM EMAIL TO AUTHORS, EDITORS
                messaging.send_mail_wrapper(
                    "✏️✏️✏️ {}".format(
                        puzzle.spoiler_free_title()
                    ),
                    "emails/testsolving_time",
                    {
                        "request": request,
                        "puzzle": puzzle,
                        "user": user,
                        "status": status_display,
                        "tc_email": settings.TESTSOLVE_COORDINATOR_EMAIL,
                    },
                    puzzle.get_emails(),
                )
            else:
                for session in puzzle.testsolve_sessions.filter(joinable=True):
                    session.joinable = False
                    add_comment(
                        request=request,
                        puzzle=puzzle,
                        author=user,
                        testsolve_session=session,
                        is_system=True,
                        send_email=False,
                        content="Puzzle status changed, automaticaly marking session as no longer joinable",
                    )
                    session.save()

            subscriptions = (
                StatusSubscription.objects.filter(status=new_status)
                .exclude(user__email="")
                .values_list("user__email", flat=True)
            )
            if subscriptions:
                status_template = status.get_template(new_status)
                template = "emails/{}".format(status_template)

                messaging.send_mail_wrapper(
                    "{} ➡ {}".format(
                        puzzle.spoiler_free_title(), status_display
                    ),
                    template,
                    {
                        "request": request,
                        "puzzle": puzzle,
                        "user": user,
                        "status": status_display,
                    },
                    subscriptions,
                )

        elif "change_priority" in request.POST:
            form = PuzzlePriorityForm(request.POST, instance=puzzle)
            if form.is_valid():
                form.save()
                add_system_comment_here(
                    "Priority changed to " + puzzle.get_priority_display()
                )
        elif "add_author" in request.POST:
            puzzle.authors.add(user)
            puzzle.spoiled.add(user)
            if c and ch:
                discord.sync_puzzle_channel(puzzle, ch)
                c.save_channel(ch)
                # discord.announce_ppl(c, ch, spoiled=[user])
            add_system_comment_here("Added author " + str(user))
        elif "remove_author" in request.POST:
            puzzle.authors.remove(user)
            add_system_comment_here("Removed author " + str(user))
        elif "add_editor" in request.POST:
            puzzle.editors.add(user)
            puzzle.spoiled.add(user)
            if c and ch:
                discord.sync_puzzle_channel(puzzle, ch)
                c.save_channel(ch)
                discord.announce_ppl(c, ch, editors=[user])
            add_system_comment_here("Added editor " + str(user))
        elif "remove_editor" in request.POST:
            puzzle.editors.remove(user)
            add_system_comment_here("Removed editor " + str(user))
        elif "add_factchecker" in request.POST:
            puzzle.factcheckers.add(user)
            add_system_comment_here("Added factchecker " + str(user))
        elif "remove_factchecker" in request.POST:
            puzzle.factcheckers.remove(user)
            add_system_comment_here("Removed factchecker " + str(user))
        elif "add_postprodder" in request.POST:
            puzzle.postprodders.add(user)
            add_system_comment_here("Added postprodder " + str(user))
        elif "remove_postprodder" in request.POST:
            puzzle.postprodders.remove(user)
            add_system_comment_here("Removed postprodder " + str(user))
        elif "edit_content" in request.POST:
            form = PuzzleContentForm(request.POST, instance=puzzle)
            if form.is_valid():
                form.save()
                add_system_comment_here("Edited puzzle content")
        elif "edit_solution" in request.POST:
            form = PuzzleSolutionForm(request.POST, instance=puzzle)
            if form.is_valid():
                form.save()
                add_system_comment_here("Edited puzzle solution")
        elif "add_hint" in request.POST:
            form = PuzzleHintForm(request.POST)
            if form.is_valid():
                form.save()
                add_system_comment_here("Added hint")
                return redirect(urls.reverse("puzzle_hints", args=[puzzle.id]))
        elif (
            "add_comment" in request.POST or "add_comment_change_status" in request.POST
        ):
            comment_form = PuzzleCommentForm(request.POST)
            # Not worth crashing over. Just do our best.
            status_change_dirty = request.POST.get("add_comment_change_status")
            status_change = ""
            if (
                status_change_dirty
                and status_change_dirty in status.BLOCKERS_AND_TRANSITIONS
            ):
                status_change = status_change_dirty

            if status_change and puzzle.status != status_change:
                puzzle.status = status_change
                puzzle.save()
                if c and ch:
                    catname = status.get_display(puzzle.status)
                    if status_change != status.INITIAL_IDEA:
                        ch.make_private()
                    c.save_channel_to_cat(ch, catname)
                    c.post_message(
                        ch.id,
                        f"This puzzle is now **{catname}**.")
            if comment_form.is_valid():
                add_comment(
                    request=request,
                    puzzle=puzzle,
                    author=user,
                    is_system=False,
                    send_email=True,
                    content=comment_form.cleaned_data["content"],
                    status_change=status_change,
                    c=c,
                    ch=ch,
                )
        elif "react_comment" in request.POST:
            emoji = request.POST.get("emoji")
            comment = PuzzleComment.objects.get(id=request.POST["react_comment"])
            # This just lets you react with any string to a comment, but it's
            # not the end of the world.
            if emoji and comment:
                CommentReaction.toggle(emoji, comment, user)
        # refresh
        return redirect(urls.reverse("puzzle", args=[id]))

    if is_spoiled_on(user, puzzle):
        discdata = DiscordData(status="disabled")
        if discord.enabled():
            discdata.status = "enabled"
            c = discord.get_client()
            try:
                ch = discord.get_channel(c, puzzle)
                if ch:
                    discdata = DiscordData.from_channel(ch, user)
            except Exception:
                discdata.status = "broken"
                discdata.guild_id = c.guild_id
                discdata.channel_id = puzzle.discord_channel_id
                discdata.error = traceback.format_exc()

        comments = PuzzleComment.objects.filter(puzzle=puzzle)
        unread_puzzles = user.spoiled_puzzles.annotate(
            last_comment_date=Max("comments__date"),
            last_visited_date=Subquery(
                PuzzleVisited.objects.filter(puzzle=OuterRef("pk"), user=user).values(
                    "date"
                )
            ),
        ).filter(
            Q(last_visited_date__isnull=True)
            | Q(last_comment_date__gt=F("last_visited_date"))
        )
        requests = m.SupportRequest.objects.filter(puzzle=puzzle).filter(Q(status="REQ")|Q(status="APP")).all()

        # TODO: participants is still hitting the database once per session;
        # might be possible to craft a Prefetch to get the list of
        # participants; or maybe we can abstract out the handrolled user list
        # logic and combine with the other views that do this

        # I inspected the query and Count with filter does become a SUM of CASE
        # expressions so it's using the same left join as everything else,
        # correctly for what we want
        testsolve_sessions = TestsolveSession.objects.filter(puzzle=puzzle).annotate(
            has_correct=Exists(
                TestsolveGuess.objects.filter(session=OuterRef("pk"), correct=True)
            ),
            participation_count=Count("participations"),
            participation_done_count=Count(
                "participations", filter=Q(participations__ended__isnull=False)
            ),
            avg_diff=Avg("participations__difficulty_rating"),
            avg_fun=Avg("participations__fun_rating"),
            avg_hours=Avg("participations__hours_spent"),
        )
        is_author = is_author_on(user, puzzle)
        is_editor = is_editor_on(user, puzzle)
        can_manage_discord = (
            is_author or is_editor or
            user.has_perm("puzzle_editing.change_round")
        )

        unspoiled_users = User.objects.exclude(pk__in=puzzle.spoiled.all()).filter(is_active=True).annotate(testsolve_count=Count('testsolve_participations')).order_by("testsolve_count")
        unspoiled = [u.credits_name or u.username for u in unspoiled_users]
        unspoiled_emails = "; ".join([ f'"{u.credits_name or u.username}" <{u.email}>' for u in unspoiled_users if u.email ])
        unspoiled.reverse()

        return render(
            request,
            "puzzle.html",
            {
                "puzzle": puzzle,
                "discord": discdata,
                "support_requests": requests,
                "comments": comments,
                "comment_form": PuzzleCommentForm(),
                "testsolve_sessions": testsolve_sessions,
                "all_statuses": status.ALL_STATUSES,
                "is_author": is_author,
                "is_editor": is_editor,
                "can_manage_discord": can_manage_discord,
                "is_factchecker": is_factchecker_on(user, puzzle),
                "is_postprodder": is_postprodder_on(user, puzzle),
                "content_form": PuzzleContentForm(instance=puzzle),
                "solution_form": PuzzleSolutionForm(instance=puzzle),
                "priority_form": PuzzlePriorityForm(instance=puzzle),
                "hint_form": PuzzleHintForm(initial={"puzzle": puzzle}),
                "enable_keyboard_shortcuts": user.enable_keyboard_shortcuts,
                "next_unread_puzzle_id": unread_puzzles[0].id
                if unread_puzzles.count()
                else None,
                "disable_postprod": SiteSetting.get_setting("DISABLE_POSTPROD"),
                "unspoiled": unspoiled,
                "unspoiled_emails": unspoiled_emails,
                "support_requests": requests,
                "postprod_url": settings.POSTPROD_URL
            },
        )
    else:
        testsolve_sessions = TestsolveSession.objects.filter(puzzle=puzzle).annotate(
            participation_count=Count("participations"),
            participation_done_count=Count(
                "participations", filter=Q(participations__ended__isnull=False)
            )
        )
        return render(
            request,
            "puzzle_unspoiled.html",
            {
                "puzzle": puzzle, "role": get_user_role(user, puzzle),
                "testsolve_sessions": testsolve_sessions,
                "is_in_testsolving": puzzle.status == status.TESTSOLVING,
                "status": status.get_display(puzzle.status),
                "postprod_url": settings.POSTPROD_URL,
                },

        )


# https://stackoverflow.com/a/55129913/3243497
class AnswerCheckboxSelectMultiple(forms.CheckboxSelectMultiple):
    template_name = "widgets/answer_checkbox_select_multiple.html"

    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        if value:
            # option["instance"] = self.choices.queryset.get(pk=value)  # get instance
            # Django 3.1 breaking change! value used to be the primary key or
            # something but now it's
            # https://docs.djangoproject.com/en/3.1/ref/forms/fields/#django.forms.ModelChoiceIteratorValue
            option["instance"] = value.instance
        return option

    # smuggle extra stuff through to the template
    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["options"] = list(self.options(name, context["widget"]["value"], attrs))
        return context


class AnswerMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, answer):
        # don't display the round, which would be in the default str; our
        # custom widget is taking care of that
        return answer.answer


class PuzzleAnswersForm(forms.ModelForm):
    def __init__(self, user, *args, **kwargs):
        super(PuzzleAnswersForm, self).__init__(*args, **kwargs)

        puzzle = kwargs["instance"]

        self.fields["answers"] = AnswerMultipleChoiceField(
            queryset=PuzzleAnswer.objects.filter(round__spoiled=user)
            .order_by("round__name")
            .annotate(
                other_puzzle_count=Count("puzzles", filter=~Q(puzzles__id=puzzle.id)),
            ),
            widget=AnswerCheckboxSelectMultiple(),
            required=False,
        )

    class Meta:
        model = Puzzle
        fields = ["answers"]
        widgets = {
            "answers": forms.CheckboxSelectMultiple(),
        }


@login_required
def puzzle_answers(request, id):
    puzzle = get_object_or_404(Puzzle, id=id)
    user = request.user
    spoiled = is_spoiled_on(user, puzzle)

    if request.method == "POST":
        form = PuzzleAnswersForm(user, request.POST, instance=puzzle)
        if form.is_valid():
            form.save()

            answers = form.cleaned_data["answers"]
            if answers:
                if len(answers) == 1:
                    comment = "Assigned answer " + answers[0].answer
                else:
                    comment = "Assigned answers " + ", ".join(
                        answer.answer for answer in answers
                    )
            else:
                comment = "Unassigned answer"

            add_comment(
                request=request,
                puzzle=puzzle,
                author=user,
                is_system=True,
                send_email=False,
                content=comment,
            )

            return redirect(urls.reverse("puzzle", args=[id]))

    unspoiled_rounds = Round.objects.exclude(spoiled=user).count()
    unspoiled_answers = PuzzleAnswer.objects.exclude(round__spoiled=user).count()

    return render(
        request,
        "puzzle_answers.html",
        {
            "puzzle": puzzle,
            "form": PuzzleAnswersForm(user, instance=puzzle),
            "spoiled": spoiled,
            "unspoiled_rounds": unspoiled_rounds,
            "unspoiled_answers": unspoiled_answers,
        },
    )


class TagMultipleChoiceField(forms.ModelMultipleChoiceField):
    def __init__(self, *args, **kwargs):
        if "queryset" not in kwargs:
            kwargs["queryset"] = PuzzleTag.objects.all()
        if "widget" not in kwargs:
            kwargs["widget"] = forms.CheckboxSelectMultiple()
        super(TagMultipleChoiceField, self).__init__(*args, **kwargs)

    def label_from_instance(self, tag):
        tpc = tag.puzzles.count()
        return "{} ({} puzzle{})".format(tag.name, tpc, "s" if tpc != 1 else "")


class PuzzleTaggingForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super(PuzzleTaggingForm, self).__init__(*args, **kwargs)

        self.fields["tags"] = TagMultipleChoiceField(required=False)

    class Meta:
        model = Puzzle
        fields = ["tags"]
        widgets = {
            "tags": forms.CheckboxSelectMultiple(),
        }


@login_required
def puzzle_tags(request, id):
    puzzle = get_object_or_404(Puzzle, id=id)
    user = request.user
    spoiled = is_spoiled_on(user, puzzle)

    if request.method == "POST":
        form = PuzzleTaggingForm(request.POST, instance=puzzle)
        if form.is_valid():
            form.save()

            tags = form.cleaned_data["tags"]
            comment = "Changed tags: " + (
                ", ".join(tag.name for tag in tags) or "(none)"
            )

            add_comment(
                request=request,
                puzzle=puzzle,
                author=user,
                is_system=True,
                send_email=False,
                content=comment,
            )

            return redirect(urls.reverse("puzzle", args=[id]))

    return render(
        request,
        "puzzle_tags.html",
        {
            "puzzle": puzzle,
            "form": PuzzleTaggingForm(instance=puzzle),
            "spoiled": spoiled,
        },
    )


@login_required
def puzzle_postprod(request, id):
    puzzle = get_object_or_404(Puzzle, id=id)
    user = request.user
    spoiled = is_spoiled_on(user, puzzle)

    if request.method == "POST":
        instance = puzzle.postprod if puzzle.has_postprod() else None
        form = PuzzlePostprodForm(request.POST, request.FILES, instance=instance)
        if form.is_valid():
            pp = form.save()

            add_comment(
                request=request,
                puzzle=puzzle,
                author=user,
                is_system=True,
                send_email=False,
                content="Postprod updated.",
            )

            if "empty_postprod" not in request.POST:
                utils.deploy_puzzle(pp)

            return redirect(urls.reverse("puzzle", args=[id]))
    else:
        if puzzle.has_postprod():
            form = PuzzlePostprodForm(instance=puzzle.postprod)
        else:
            default_slug = re.sub(
                r'[<>#%\'"|{}\[\])(\\\^?=`;@&,]',
                "",
                re.sub(r"[ \/]+", "-", puzzle.name),
            ).lower()
            authors = [get_credits_name(user) for user in puzzle.authors.all()]
            authors.sort(key=lambda a: a.upper())
            form = PuzzlePostprodForm(
                initial={
                    "puzzle": puzzle,
                    "slug": default_slug,
                    "authors": ", ".join(authors),
                }
            )

    return render(
        request,
        "puzzle_postprod.html",
        {
            "puzzle": puzzle,
            "form": form,
            "spoiled": spoiled,
            "postprod_url": settings.POSTPROD_URL
        },
    )

@login_required
def puzzle_postprod_metadata(request, id):
    puzzle = get_object_or_404(Puzzle, id=id)
    authors = [get_credits_name(u) for u in puzzle.authors.all()]
    authors.sort(key=lambda a: a.upper())

    metadata = JsonResponse(puzzle.metadata)

    metadata['Content-Disposition'] = 'attachment; filename="metadata.json"'

    return metadata

@login_required
def puzzle_hints_json(request, id):
    puzzle = get_object_or_404(Puzzle, id=id)

    hints = JsonResponse(puzzle.hints_array, safe=False)

    hints['Content-Disposition'] = 'attachment; filename="hints.json"'

    return hints

@login_required
def postprod_zip(request, id):
    pp = get_object_or_404(PuzzlePostprod, puzzle__id=id)
    loc = utils.get_latest_zip(pp)
    return serve(request, os.path.basename(loc), os.path.dirname(loc))

@permission_required("puzzle_editing.change_round", raise_exception=True)
def export(request):
    output = ""
    if request.method == "POST":
        if "export-hints" in request.POST:
            output = "Exported hints"
            utils.export_data(export_hints=True)
        elif "export-metadata" in request.POST:
            output = "Exported metadata"
            utils.export_data(export_metadata=True)
        elif "export-both" in request.POST:
            output = "Exported metadata and hints"
            utils.export_data(export_hints=True, export_metadata=True)

    return render(
        request,
        "export.html",
        {
            "output": output,
        },
    )

@login_required
def check_metadata(request):
    puzzleFolder = os.path.join(settings.HUNT_REPO, "hunt/data/puzzle")
    mismatches = []
    credits_mismatches = []
    notfound = []
    notfound = []
    exceptions = []
    for puzzledir in os.listdir(puzzleFolder):
        datafile = os.path.join(puzzleFolder, puzzledir, 'metadata.json')
        try:
            with open(datafile) as data:
                metadata = json.load(data)
                pu_id = metadata['puzzle_idea_id']
                slug_in_file = metadata['puzzle_slug']
                credits_in_file = metadata['credits']
                puzzle = Puzzle.objects.get(id=pu_id)
                metadata_credits = puzzle.metadata['credits']

                if puzzle.postprod.slug != slug_in_file:
                    puzzle.slug_in_file = slug_in_file
                    mismatches.append(puzzle)
                if metadata_credits != credits_in_file:
                    puzzle.metadata_credits = metadata_credits
                    puzzle.credits_in_file = credits_in_file
                    credits_mismatches.append(puzzle)
        except FileNotFoundError:
            notfound.append(puzzledir)
            pass
        except Exception as e:
            exceptions.append("{} - {}".format(puzzledir, e))
            print(datafile, e)
            # sys.exit(1)

    return render(
        request,
        "check_metadata.html",
        {
            "mismatches": mismatches,
            "credits_mismatches": credits_mismatches,
            "notfound": notfound,
            "exceptions": exceptions,
        },
    )

class PuzzleOtherCreditsForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super(PuzzleOtherCreditsForm, self).__init__(*args, **kwargs)
        self.fields['users'] = UserMultipleChoiceField(required=False)
        self.fields['credit_type'] = forms.ChoiceField(
            required=True,
            choices=[
                ("ART", "Art"),
                ("TCH", "Tech"),
                ("OTH", "Other"),
            ]
        )

    class Meta:
        model = PuzzleCredit
        fields = [
            "users",
            "credit_type",
            "puzzle",
            "text"
        ]
        widgets = {
            "puzzle": forms.HiddenInput(),
            "text": forms.TextInput(attrs={"class":"input"})
        }

class PuzzlePeopleForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super(PuzzlePeopleForm, self).__init__(*args, **kwargs)
        self.fields["authors"] = UserMultipleChoiceField(required=False)
        self.fields["editors"] = UserMultipleChoiceField(required=False, editors_only=True)
        self.fields["factcheckers"] = UserMultipleChoiceField(required=False)
        self.fields["postprodders"] = UserMultipleChoiceField(required=False)
        self.fields["spoiled"] = UserMultipleChoiceField(required=False)

    def clean(self):
        '''On clean, ensure that all authors and editors are spoiled.'''
        cleaned_data = super().clean()
        spoiled = set(cleaned_data['spoiled'])
        authors = set(cleaned_data['authors'])
        editors = set(cleaned_data['editors'])
        cleaned_data['spoiled'] = list(spoiled | authors | editors)
        return cleaned_data

    class Meta:
        model = Puzzle
        fields = [
            "authors",
            "editors",
            "factcheckers",
            "postprodders",
            "spoiled",
        ]


@login_required
def puzzle_edit(request, id):
    puzzle = get_object_or_404(Puzzle, id=id)
    user = request.user

    if request.method == "POST":
        form = PuzzleInfoForm(user, request.POST, instance=puzzle)
        if form.is_valid():
            if 'authors' in form.changed_data:
                old_authors = set(puzzle.authors.all())
                new_authors = set(form.cleaned_data['authors']) - old_authors
            else:
                new_authors = set()
            form.save()

            if form.changed_data:
                add_comment(
                    request=request,
                    puzzle=puzzle,
                    author=user,
                    is_system=True,
                    send_email=False,
                    content=get_changed_data_message(form),
                )
                if new_authors:
                    puzzle.spoiled.add(*new_authors)
                c, ch = discord.get_client_and_channel(puzzle)
                if c and ch:
                    url = external_puzzle_url(request, puzzle)
                    discord.sync_puzzle_channel(puzzle, ch, url=url)
                    c.save_channel(ch)
                    # if new_authors:
                    #     discord.announce_ppl(c, ch, spoiled=new_authors)

            return redirect(urls.reverse("puzzle", args=[id]))
    else:
        form = PuzzleInfoForm(user, instance=puzzle)

    return render(
        request,
        "puzzle_edit.html",
        {"puzzle": puzzle, "form": form, "spoiled": is_spoiled_on(user, puzzle)},
    )


def get_changed_data_message(form):
    """Given a filled-out valid form, describe what changed.

    Somewhat automagically produce a system comment message that includes all
    the updated fields and particularly lists all new users for
    `UserMultipleChoiceField`s with an "Assigned" sentence."""

    normal_fields = []
    lines = []

    for field in form.changed_data:
        if isinstance(form.fields[field], UserMultipleChoiceField):
            users = form.cleaned_data[field]
            field_name = field.replace("_", " ")
            if users:
                user_display = ", ".join(str(u) for u in users)
                # XXX haxx
                if len(users) == 1 and field_name.endswith("s"):
                    field_name = field_name[:-1]
                lines.append("Assigned {} as {}".format(user_display, field_name))
            else:
                lines.append("Unassigned all {}".format(field.replace("_", " ")))

        else:
            normal_fields.append(field)

    if normal_fields:
        lines.insert(0, "Updated {}".format(", ".join(normal_fields)))

    return "<br/>".join(lines)


@login_required
def puzzle_people(request, id):
    puzzle = get_object_or_404(Puzzle, id=id)
    user = request.user

    if request.method == "POST":
        form = PuzzlePeopleForm(request.POST, instance=puzzle)
        if form.is_valid():
            changed = set()
            old = {}
            added = {}
            if form.changed_data:
                for key in ['authors', 'spoiled', 'editors']:
                    old[key] = set(getattr(puzzle, key).all())
                    new = set(form.cleaned_data[key])
                    added[key] = new - old[key]
                    if new != old[key]:
                        changed.add(key)
            form.save()
            if changed and discord.enabled():
                c, ch = discord.get_client_and_channel(puzzle)
                if c and ch:
                    discord.sync_puzzle_channel(puzzle, ch)
                    c.save_channel(ch)
                    discord.announce_ppl(
                        c,
                        ch,
                        editors=added.get('editors', set()),
                        # spoiled=added.get('spoiled', set())
                    )

            if form.changed_data:
                add_comment(
                    request=request,
                    puzzle=puzzle,
                    author=user,
                    is_system=True,
                    send_email=False,
                    content=get_changed_data_message(form),
                )

            return redirect(urls.reverse("puzzle", args=[id]))
        else:
            context = {
                "puzzle": puzzle,
                "form": form,
            }
    else:
        context = {
            "puzzle": puzzle,
            "form": PuzzlePeopleForm(instance=puzzle),
        }

    return render(request, "puzzle_people.html", context)


@login_required
def puzzle_escape(request, id):
    puzzle: Puzzle = get_object_or_404(Puzzle, id=id)
    user: User = request.user

    if request.method == "POST":
        if "unspoil" in request.POST:
            puzzle.spoiled.remove(user)
            if user.discord_user_id and discord.enabled():
                c, ch = discord.get_client_and_channel(puzzle)
                if c and ch:
                    ch.rm_visibility([user.discord_user_id])
                    c.save_channel(ch)
            add_comment(
                request=request,
                puzzle=puzzle,
                author=user,
                is_system=True,
                send_email=False,
                content="Unspoiled " + str(user),
            )
        elif "testsolve" in request.POST:
            session = TestsolveSession(puzzle=puzzle)
            session.save()

            participation = TestsolveParticipation(session=session, user=user)
            participation.save()

            add_comment(
                request=request,
                puzzle=puzzle,
                author=user,
                is_system=True,
                send_email=False,
                content="Created testsolve session #{} from escape hatch".format(
                    session.id
                ),
                testsolve_session=session,
            )

            return redirect(urls.reverse("testsolve_one", args=[session.id]))

    return render(
        request,
        "puzzle_escape.html",
        {
            "puzzle": puzzle,
            "spoiled": is_spoiled_on(user, puzzle),
            "status": status.get_display(puzzle.status),
            "is_in_testsolving": puzzle.status == status.TESTSOLVING,
        },
    )


@login_required
def edit_comment(request, id):
    comment = get_object_or_404(PuzzleComment, id=id)

    if request.user != comment.author:
        return render(
            request,
            "edit_comment.html",
            {
                "comment": comment,
                "not_author": True,
            },
        )
    elif comment.is_system:
        return render(
            request,
            "edit_comment.html",
            {
                "comment": comment,
                "is_system": True,
            },
        )

    if request.method == "POST":
        form = PuzzleCommentForm(request.POST)
        if form.is_valid():
            comment.content = form.cleaned_data["content"]
            comment.save()

            return redirect(urls.reverse("edit_comment", args=[id]))
        else:
            return render(
                request, "edit_comment.html", {"comment": comment, "form": form}
            )

    return render(
        request,
        "edit_comment.html",
        {
            "comment": comment,
            "form": PuzzleCommentForm({"content": comment.content}),
        },
    )


@login_required
def edit_hint(request, id):
    hint = get_object_or_404(Hint, id=id)

    if request.method == "POST":
        if "delete" in request.POST:
            hint.delete()
            return redirect(urls.reverse("puzzle_hints", args=[hint.puzzle.id]))
        else:
            form = PuzzleHintForm(request.POST, instance=hint)
            if form.is_valid():
                form.save()
                return redirect(urls.reverse("puzzle_hints", args=[hint.puzzle.id]))
            else:
                return render(request, "edit_hint.html", {"hint": hint, "form": form})

    return render(
        request,
        "edit_hint.html",
        {
            "hint": hint,
            "form": PuzzleHintForm(instance=hint),
        },
    )


def warn_about_testsolving(is_spoiled, in_session, has_session):
    reasons = []
    if is_spoiled:
        reasons.append("you are spoiled")
    if in_session:
        reasons.append("you are already testsolving it")
    if has_session:
        reasons.append("there is an existing session you can join")

    if not reasons:
        return None
    if len(reasons) == 1:
        return reasons[0]
    return ", ".join(reasons[:-1]) + " and " + reasons[-1]

@login_required
def testsolve_history(request):

    past_sessions = TestsolveSession.objects.filter(
        participations__in=TestsolveParticipation.objects.filter(
            user=request.user,ended__isnull=False
            ).all()
        )

    context = {
        "past_sessions": past_sessions,
    }
    return render(request, "testsolve_history.html", context)

@login_required
def testsolve_main(request):
    user = request.user

    if request.method == "POST":
        if "start_session" in request.POST:
            puzzle_id = request.POST["start_session"]
            puzzle = get_object_or_404(Puzzle, id=puzzle_id)
            session = TestsolveSession(puzzle=puzzle)
            session.save()

            participation = TestsolveParticipation(session=session, user=user)
            participation.save()

            add_comment(
                request=request,
                puzzle=puzzle,
                author=user,
                is_system=True,
                send_email=False,
                content="Created testsolve session #{}".format(session.id),
                testsolve_session=session,
            )

            return redirect(urls.reverse("testsolve_one", args=[session.id]))

    current_sessions = TestsolveSession.objects.filter(
        participations__in=TestsolveParticipation.objects.filter(
            user=request.user,ended__isnull=True
        ).all()
        )

    joinable_sessions = TestsolveSession.objects.exclude(
        pk__in=TestsolveSession.objects.filter(
            participations__in=TestsolveParticipation.objects.filter(
                user=request.user
                ).all()
            ).all()
        ).filter(joinable=True)

    # testsolvable_puzzles = Puzzle.objects.filter(status=status.TESTSOLVING).annotate(
    #     is_author=False,
    #     is_spoiled=False,
    #     in_session=
    #     )

    testsolvable_puzzles = (
        Puzzle.objects.filter(status=status.TESTSOLVING)
        .annotate(
            is_author=Exists(
                User.objects.filter(authored_puzzles=OuterRef("pk"), id=user.id)
            ),
            is_spoiled=Exists(
                User.objects.filter(spoiled_puzzles=OuterRef("pk"), id=user.id)
            ),
            in_session=Exists(current_sessions.filter(puzzle=OuterRef("pk"))),
            has_session=Exists(joinable_sessions.filter(puzzle=OuterRef("pk"))),
        )
        .order_by("priority")
    )

    testsolvable = [
        {
            "puzzle": puzzle,
            "warning": warn_about_testsolving(
                puzzle.is_spoiled, puzzle.in_session, puzzle.has_session
            ),
        }
        for puzzle in testsolvable_puzzles
    ]

    context = {
        "current_sessions": current_sessions,
        "joinable_sessions": joinable_sessions,
        "testsolvable": testsolvable
    }

    return render(request, "testsolve_main.html", context)

@login_required
def my_spoiled(request):
    spoiled = request.user.spoiled_puzzles.all()

    context = {
        "spoiled": spoiled
    }
    return render(request, "my_spoiled.html", context )

@login_required
def testsolve_finder(request):
    solvers = request.GET.getlist("solvers")
    users = User.objects.filter(pk__in=solvers) if solvers else None
    if users:
        puzzles = list(
            Puzzle.objects.filter(status=status.TESTSOLVING).order_by("priority")
        )
        for puzzle in puzzles:
            puzzle.user_data = []
            puzzle.unspoiled_count = 0
        for user in users:
            authored_ids = set(user.authored_puzzles.values_list("id", flat=True))
            editor_ids = set(user.editing_puzzles.values_list("id", flat=True))
            spoiled_ids = set(user.spoiled_puzzles.values_list("id", flat=True))
            for puzzle in puzzles:
                if puzzle.id in authored_ids:
                    puzzle.user_data.append("📝 Author")
                elif puzzle.id in editor_ids:
                    puzzle.user_data.append("💬 Editor")
                elif puzzle.id in spoiled_ids:
                    puzzle.user_data.append("👀 Spoiled")
                else:
                    puzzle.user_data.append("❓ Unspoiled")
                    puzzle.unspoiled_count += 1

        puzzles.sort(key=lambda puzzle: -puzzle.unspoiled_count)
    else:
        puzzles = None

    form = TestsolveFinderForm(solvers or request.user)

    return render(
        request,
        "testsolve_finder.html",
        {
            "puzzles": puzzles,
            "solvers": solvers,
            "form": form,
            "users": users
        },
    )


def normalize_answer(answer):
    return "".join(c for c in answer if c.isalnum()).upper()


class TestsolveSessionNotesForm(forms.ModelForm):
    notes = forms.CharField(
        widget=MarkdownTextarea,
        required=False
    )

    class Meta:
        model = TestsolveSession
        fields = ["notes"]


class GuessForm(forms.Form):
    guess = forms.CharField()

def testsolve_queryset_to_csv(qs):
    opts = qs.model._meta
    csvResponse = HttpResponse(content_type="text/csv")
    csvResponse['Content-Disposition'] = 'attachment;filename=export.csv'
    writer = csv.writer(csvResponse)

    field_names = [ field.name for field in opts.fields ]
    headers = [name for name in field_names]
    headers.insert(0, "puzzle_id")
    headers.insert(1, "puzzle_name")
    writer.writerow(headers)
    for obj in qs:
        data = [getattr(obj, field) for field in field_names]
        data.insert(0, obj.session.puzzle.id)
        data.insert(1, obj.session.puzzle.spoilery_title)
        writer.writerow(data)

    return csvResponse

@login_required
def testsolve_csv(request, id):
    session = get_object_or_404(TestsolveSession, id=id)
    queryset = TestsolveParticipation.objects.filter(session=session)
    # opts = queryset.model._meta  # pylint: disable=protected-access
    # response = HttpResponse(content_type="text/csv")
    # response['Content-Disposition'] = 'attachment;filename=export.csv'
    # writer = csv.writer(response)

    # field_names = [field.name for field in opts.fields]
    # writer.writerow(field_names)
    # for obj in queryset:
    #     writer.writerow([getattr(obj, field) for field in field_names])

    return HttpResponse(testsolve_queryset_to_csv(queryset), content_type="text/csv")

@login_required
def testsolve_participants(request, id):
    session = get_object_or_404(TestsolveSession, id=id)
    puzzle = session.puzzle
    user = request.user
    if request.method == "POST":
        new_testers = User.objects.filter(pk__in=request.POST.getlist("add_testsolvers"))
        for new_tester in new_testers:
            if not TestsolveParticipation.objects.filter(session=session, user=new_tester).exists():
                TestsolveParticipation(session=session, user=new_tester).save()

    current_testers = User.objects.exclude(pk__in=[user.id for user in session.participants()])
    form = TestsolveParticipantPicker(None, current_testers)
    context = {
        "session": session,
        "puzzle": puzzle,
        "user": user,
        "form": form
    }
    return render(request, "testsolve_participants.html", context)

class TestsolveParticipantPicker(forms.Form):
    def __init__(self, user, exclude, *args, **kwargs):
        super(TestsolveParticipantPicker, self).__init__(*args, **kwargs)
        self.fields["add_testsolvers"] = UserMultipleChoiceField(initial=user, queryset=exclude)

    add_testsolvers = forms.CheckboxSelectMultiple()

@login_required
def testsolve_one(request, id):
    session = get_object_or_404(TestsolveSession, id=id)
    puzzle = session.puzzle
    user = request.user
    current_testers = User.objects.exclude(pk__in=[user.id for user in session.participants()])
    testsolve_adder_form = TestsolveParticipantPicker(None, current_testers)

    if request.method == "POST":
        if "join" in request.POST:
            if not TestsolveParticipation.objects.filter(
                session=session, user=user
            ).exists():
                participation = TestsolveParticipation()
                participation.session = session
                participation.user = user
                participation.save()

                add_comment(
                    request=request,
                    puzzle=puzzle,
                    author=user,
                    testsolve_session=session,
                    is_system=True,
                    send_email=False,
                    content="Joined testsolve session #{}".format(session.id),
                )

        elif "edit_notes" in request.POST:
            notes_form = TestsolveSessionNotesForm(request.POST, instance=session)
            if notes_form.is_valid():
                notes_form.save()

        elif "do_guess" in request.POST:
            participation = get_object_or_404(
                TestsolveParticipation,
                session=session,
                user=user,
            )
            guess_form = GuessForm(request.POST)
            if guess_form.is_valid():
                guess = guess_form.cleaned_data["guess"]
                normalized_guess = normalize_answer(guess)
                correct = any(
                    normalized_guess == normalize_answer(answer.answer)
                    for answer in session.puzzle.answers.all()
                )

                guess_model = TestsolveGuess(
                    session=session,
                    user=user,
                    guess=guess,
                    correct=correct,
                )
                guess_model.save()

                if correct and session.joinable:
                    add_comment(
                        request=request,
                        puzzle=puzzle,
                        author=user,
                        testsolve_session=session,
                        is_system=True,
                        send_email=False,
                        content="Correct answer: {}. Automatically marking session as no longer joinable".format(
                            guess
                        ),
                    )

                    session.joinable = False
                    session.save()
                else:
                    message = "{} answer guess: {}".format(
                        "Correct" if correct else "Incorrect",
                        guess,
                    )
                    add_comment(
                        request=request,
                        puzzle=puzzle,
                        author=user,
                        testsolve_session=session,
                        is_system=True,
                        send_email=False,
                        content=message,
                    )

        elif "change_joinable" in request.POST:
            session.joinable = request.POST["change_joinable"] == "1"
            session.save()

        elif "add_comment" in request.POST:
            comment_form = PuzzleCommentForm(request.POST)
            if comment_form.is_valid():
                add_comment(
                    request=request,
                    puzzle=puzzle,
                    author=user,
                    testsolve_session=session,
                    is_system=False,
                    send_email=True,
                    content=comment_form.cleaned_data["content"],
                )
        elif "react_comment" in request.POST:
            emoji = request.POST.get("emoji")
            comment = PuzzleComment.objects.get(id=request.POST["react_comment"])
            # This just lets you react with any string to a comment, but it's
            # not the end of the world.
            if emoji and comment:
                CommentReaction.toggle(emoji, comment, user)

        elif "escape_testsolve" in request.POST:
            participation = get_object_or_404(
                TestsolveParticipation,
                session=session,
                user=user,
            )
            participation.delete()
            return redirect(urls.reverse("testsolve_main"))
        elif "add_testsolvers" in request.POST:
            new_testers = User.objects.filter(pk__in=request.POST.getlist("add_testsolvers"))
            for new_tester in new_testers:
                if not TestsolveParticipation.objects.filter(session=session, user=new_tester).exists():
                    TestsolveParticipation(session=session, user=new_tester).save()

        # refresh
        return redirect(urls.reverse("testsolve_one", args=[id]))

    try:
        participation = TestsolveParticipation.objects.get(session=session, user=user)
    except TestsolveParticipation.DoesNotExist:
        participation = None

    spoiled = is_spoiled_on(user, puzzle)
    answers_exist = session.puzzle.answers.exists()
    comments = session.comments.filter(puzzle=puzzle)

    true_participants = []

    user_is_participant = False

    for participant in session.participations.all():
        if get_user_role(participant.user, session.puzzle) not in ["author", "editor"]:
            true_participants.append(participant)
        elif participant.user.id == user.id:
            user_is_participant = True

    context = {
        "session": session,
        "participation": participation,
        "spoiled": spoiled,
        "comments": comments,
        "answers_exist": answers_exist,
        "guesses": TestsolveGuess.objects.filter(session=session),
        "notes_form": TestsolveSessionNotesForm(instance=session),
        "guess_form": GuessForm(),
        "comment_form": PuzzleCommentForm(),
        "testsolve_adder_form": testsolve_adder_form,
        "true_participants": true_participants,
        "user_is_hidden_from_list": user_is_participant,
        "postprod_url": settings.POSTPROD_URL
    }

    return render(request, "testsolve_one.html", context)

@login_required
def testsolve_feedback(request, id):
    session = get_object_or_404(TestsolveSession, id=id)

    feedback = session.participations.exclude(fun_rating=None)
    noFeedback = len(session.participations.filter(fun_rating=None))
    participants = noFeedback + len(feedback)

    context = {
        "session": session,
        "no_feedback": noFeedback,
        "feedback": feedback,
        "participants": participants,
        "title": f"Testsolving Feedback - {session.puzzle}",
        "bulk": False
    }

    return render(request, "testsolve_feedback.html", context)


@login_required
def puzzle_feedback(request, id):
    puzzle = get_object_or_404(Puzzle, id=id)
    feedback = TestsolveParticipation.objects.filter(session__puzzle=puzzle).exclude(fun_rating=None).select_related('session').order_by("session__id")

    context = {
        "puzzle": puzzle,
        "feedback": feedback,
        "title": f"Testsolve Feedback for {puzzle.spoilery_title}",
        "bulk": True
    }

    return render(request, "testsolve_feedback.html", context)


@login_required
def puzzle_feedback_all(request):
    feedback = TestsolveParticipation.objects.exclude(fun_rating=None).select_related('session').order_by("session__puzzle__id", "session__id")

    context = {
        "feedback": feedback,
        "title": "All Testsolve Feedback",
        "bulk": True
    }

    return render(request, "testsolve_feedback.html", context)


@login_required
def puzzle_feedback_csv(request, id):
    puzzle = get_object_or_404(Puzzle, id=id)
    feedback = TestsolveParticipation.objects.filter(session__puzzle=puzzle).exclude(fun_rating=None).select_related('session').order_by("session__id")

    return HttpResponse(testsolve_queryset_to_csv(feedback), content_type="text/csv")


@login_required
def puzzle_feedback_all_csv(request):
    feedback = TestsolveParticipation.objects.exclude(fun_rating=None).select_related('session').order_by("session__puzzle__id", "session__id")

    return HttpResponse(testsolve_queryset_to_csv(feedback), content_type="text/csv")


@login_required
def spoiled(request):
    puzzles = Puzzle.objects.filter(
        status__in=[status.TESTSOLVING, status.REVISING]
    ).annotate(
        is_spoiled=Exists(
            User.objects.filter(spoiled_puzzles=OuterRef("pk"), id=request.user.id)
        )
    )
    context = {"puzzles": puzzles}
    return render(request, "spoiled.html", context)


class TestsolveParticipationForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super(TestsolveParticipationForm, self).__init__(*args, **kwargs)

        self.fields["finish_method"] = forms.ChoiceField(
            choices=[
                (
                    "SPOIL",
                    mark_safe(
                        "<strong>Finish, spoil me</strong>: You will be redirected to the puzzle discussion page. Select this if you finished the testsolve normally, or if you gave up and want to know how the puzzle works. (However, we encourage you to find others to join your session or ask the author/editors for hints before giving up!)"
                    ),
                ),
                (
                    "NO_SPOIL",
                    mark_safe(
                        "<strong>Finish, don't spoil me</strong>: You will be redirected back to the puzzle testsolve session. Select this if you gave up but want to testsolve future revisions of this puzzle."
                    ),
                ),
                (
                    "LEAVE",
                    mark_safe(
                        "<strong>Leave and forget I was even here</strong>: You will be be removed from the list of participants of this testsolve session. Select this if you didn't really contribute to the test solve, or if you joined this session by mistake, or if this is a duplicate or merged session."
                    ),
                ),
            ],
            widget=forms.RadioSelect(),
            initial="SPOIL",
        )

    class Meta:
        model = TestsolveParticipation
        exclude = ['session', 'user', 'started' ,'ended']
        widgets = {
            "fun_rating": forms.RadioSelect(choices=[
                (None, "n/a"),
                (1, "1: not fun"),
                (2, "2: a little fun"),
                (3, "3: somewhat fun"),
                (4, "4: fun"),
                (5, "5: very fun"),
                (6, "6: extremely fun"),
            ]),
            "difficulty_rating": forms.RadioSelect(choices=[
                (None, "n/a"),
                (1, "1: very easy"),
                (2, "2: easy"),
                (3, "3: somewhat difficult"),
                (4, "4: difficult"),
                (5, "5: very difficult"),
                (6, "6: extremely difficult"),
            ]),
            "flavortext_overall": forms.RadioSelect(),
            "technical_issues": forms.RadioSelect(choices=[
                (True, "Yes"),
                (False, "No"),
            ]),
            "instructions_overall": forms.RadioSelect(choices=[
                (True, "Yes"),
                (False, "No"),
            ]),
            "stuck_overall": forms.RadioSelect(choices=[
                (True, "Yes"),
                (False, "No"),
            ]),
        }

    comment = forms.CharField(
        widget=MarkdownTextarea,
        required=False,
        help_text="**Comment?** If you'd like to add a comment to the puzzle page, add it here. Any notes about the testsolve should go in the fields above."
    )


@login_required
def testsolve_finish(request, id):
    session = get_object_or_404(TestsolveSession, id=id)
    puzzle = session.puzzle
    user = request.user

    try:
        participation = TestsolveParticipation.objects.get(session=session, user=user)
    except TestsolveParticipation.DoesNotExist:
        participation = None

    if request.method == "POST" and participation:
        form = TestsolveParticipationForm(
            request.POST,
            instance=participation,
        )
        already_spoiled = is_spoiled_on(user, puzzle)
        if form.is_valid():
            fun = form.cleaned_data["fun_rating"] or None
            difficulty = form.cleaned_data["difficulty_rating"] or None
            hours_spent = form.cleaned_data["hours_spent"] or None
            comment = form.cleaned_data["comment"]
            finish_method = form.cleaned_data["finish_method"]

            if already_spoiled:
                spoil_message = "(solver was already spoiled)"
            elif finish_method == "SPOIL":
                spoil_message = "👀 solver is now spoiled"
            elif finish_method == "LEAVE":
                spoil_message = "🚪 solver left session"
            elif finish_method == "NO_SPOIL":
                spoil_message = "❌ solver was not spoiled"
            else:
                raise ValidationError("Invalid finish method")

            ratings_text = "Fun: {} / Difficulty: {} / Hours spent: {} / {}".format(
                fun or "n/a", difficulty or "n/a", hours_spent or "n/a", spoil_message
            )

            if comment:
                comment_content = "Finished testsolve with comment:\n\n{}\n\n{}".format(
                    comment, ratings_text
                )
            else:
                comment_content = "Finished testsolve\n\n{}".format(ratings_text)
            add_comment(
                request=request,
                puzzle=puzzle,
                author=user,
                testsolve_session=session,
                is_system=False,
                send_email=False,
                content=comment_content,
            )
            participation.ended = datetime.datetime.now()
            participation.save()

            if finish_method == "LEAVE":
                participation.delete()
                return redirect(urls.reverse("testsolve_main"))
            elif finish_method == "SPOIL":
                if not already_spoiled:
                    puzzle.spoiled.add(user)
                    # if discord.enabled():
                    #     c, ch = discord.get_client_and_channel(puzzle)
                    #     if c and ch:
                    #         if user.discord_user_id:
                    #             ch.add_visibility([user.discord_user_id])
                    #         c.save_channel(ch)
                    #         discord.announce_ppl(c, ch, spoiled=[user])
                return redirect(urls.reverse("puzzle", args=[puzzle.id]))
            else:
                return redirect(urls.reverse("testsolve_one", args=[id]))
        else:
            print("not valid")
            print(form.errors)
            context = {
                "session": session,
                "participation": participation,
                "form": form,
            }

            return render(request, "testsolve_finish.html", context)

    if participation:
        form = TestsolveParticipationForm(
            instance=participation
        )
    else:
        form = None

    context = {
        "session": session,
        "participation": participation,
        "form": form,
    }

    return render(request, "testsolve_finish.html", context)


@login_required
def postprod(request):
    postprodding = Puzzle.objects.filter(
        status__in=[
            status.NEEDS_POSTPROD,
            status.ACTIVELY_POSTPRODDING,
            status.POSTPROD_BLOCKED,
            status.POSTPROD_BLOCKED_ON_TECH,
        ],
        postprodders=request.user,
    )
    needs_postprod = Puzzle.objects.annotate(
        has_postprodder=Exists(User.objects.filter(postprodding_puzzles=OuterRef("pk")))
    ).filter(status=status.NEEDS_POSTPROD, has_postprodder=False)

    context = {
        "postprodding": postprodding,
        "needs_postprod": needs_postprod,
    }
    return render(request, "postprod.html", context)

@login_required
def postprod_all(request):
    needs_postprod = Puzzle.objects.filter(status__in=[
        status.NEEDS_POSTPROD,
        status.ACTIVELY_POSTPRODDING,
        status.POSTPROD_BLOCKED,
        status.POSTPROD_BLOCKED_ON_TECH,
        status.AWAITING_POSTPROD_APPROVAL,
        status.NEEDS_FACTCHECK,
        status.NEEDS_FINAL_REVISIONS,
        status.NEEDS_COPY_EDITS,
        status.NEEDS_HINTS,
        status.AWAITING_HINTS_APPROVAL,
    ])

    sorted_puzzles = sorted(needs_postprod, key=lambda a: (status.STATUSES.index(a.status), a.name))

    context = {
        "puzzles": sorted_puzzles,
    }
    return render(request, "postprod_all.html", context)


@login_required
def factcheck(request):
    factchecking = Puzzle.objects.filter(
        (Q(status=status.NEEDS_FACTCHECK) | Q(status=status.NEEDS_COPY_EDITS))
        & Q(factcheckers=request.user)
    )
    needs_factcheck = Puzzle.objects.annotate(
        has_factchecker=Exists(User.objects.filter(factchecking_puzzles=OuterRef("pk")))
    ).filter(status=status.NEEDS_FACTCHECK, has_factchecker=False)

    needs_copyedit = Puzzle.objects.annotate(
        has_factchecker=Exists(User.objects.filter(factchecking_puzzles=OuterRef("pk")))
    ).filter(status=status.NEEDS_COPY_EDITS, has_factchecker=False)

    needs_copyedit_all = Puzzle.objects.filter(status=status.NEEDS_COPY_EDITS)

    context = {
        "factchecking": factchecking,
        "needs_factchecking": needs_factcheck,
        "needs_copyediting": needs_copyedit,
        "needs_copyediting_all": needs_copyedit_all,
    }
    return render(request, "factcheck.html", context)


@login_required
def eic(request, template="awaiting_editor.html"):
    return render(
        request,
        template,
        {
            "awaiting_eic": Puzzle.objects.filter(status=status.AWAITING_EDITOR).order_by('status_mtime'),
            "needs_discussion": Puzzle.objects.filter(status=status.NEEDS_DISCUSSION).order_by('status_mtime'),
            "waiting_for_round": Puzzle.objects.filter(status=status.WAITING_FOR_ROUND).order_by('status_mtime'),
            "awaiting_answer": Puzzle.objects.filter(status=status.AWAITING_ANSWER).order_by('status_mtime'),

        },
    )

@login_required
def triage(request):
    return eic(request, "awaiting_editor_thin.html")

@login_required
def editor_overview(request):
    active_statuses = [
        status.INITIAL_IDEA,
        status.AWAITING_EDITOR,
        status.NEEDS_DISCUSSION,
        status.AWAITING_REVIEW,
        status.IDEA_IN_DEVELOPMENT,
        status.AWAITING_ANSWER,
        status.WRITING,
        status.WRITING_FLEXIBLE,
        status.AWAITING_APPROVAL_FOR_TESTSOLVING,
        status.TESTSOLVING,
        status.AWAITING_TESTSOLVE_REVIEW,
        status.REVISING,
        status.REVISING_POST_TESTSOLVING,
        status.AWAITING_APPROVAL_POST_TESTSOLVING,
        status.NEEDS_SOLUTION,
        status.AWAITING_SOLUTION_APPROVAL,
        status.NEEDS_POSTPROD,
        status.AWAITING_POSTPROD_APPROVAL,
        # status.NEEDS_FACTCHECK,
        # status.NEEDS_FINAL_REVISIONS,
        # status.NEEDS_COPY_EDITS,
        # status.NEEDS_HINTS,
        # status.AWAITING_HINTS_APPROVAL,
        # status.WAITING_FOR_ROUND,
        # status.DONE,
        # status.DEFERRED,
        # status.DEAD,
    ]

    puzzle_editors = User.objects.exclude(editing_puzzles__isnull=True).annotate(num_editing=Count('editing_puzzles')).order_by('id')

    actively_editing = [(p.id,0) for p in puzzle_editors]

    edited_puzzles = Puzzle.objects.exclude(editors__isnull=True).order_by('status')
    active_puzzles = edited_puzzles.filter(status__in=active_statuses)

    all_editors = [e.id for e in puzzle_editors]
    editored_puzzles = []
    for p in edited_puzzles:
        this_puz_editors = [pe.id for pe in p.editors.all()]
        editored_puzzles.append(
            {
                'id': p.id,
                'codename': p.codename,
                'name':p.name,
                'status': status.get_display(p.status),
                'editors':[1 if e in this_puz_editors else 0 for e in all_editors]
            }
        )

    for p in active_puzzles:
        this_puz_editors = [pe.id for pe in p.editors.all()]
        actively_editing = [
            (ae[0], ae[1] + (1 if ae[0] in this_puz_editors else 0)) for ae in actively_editing
            ]

    context = {
        'editors': puzzle_editors,
        'actively_editing': actively_editing,
        'editored_puzzles': editored_puzzles
    }
    return render(request, "editor_overview.html", context)


@login_required
def needs_editor(request):
    needs_editors = Puzzle.objects.annotate(
        remaining_des=(F("needed_editors") - Count("editors"))
    ).filter(remaining_des__gt=0)

    context = {"needs_editors": needs_editors}
    return render(request, "needs_editor.html", context)


class AnswerForm(forms.ModelForm):
    def __init__(self, round, *args, **kwargs):
        super(AnswerForm, self).__init__(*args, **kwargs)
        self.fields["round"] = forms.ModelChoiceField(
            queryset=Round.objects.all(),  # ???
            initial=round,
            widget=forms.HiddenInput(),
        )

    class Meta:
        model = PuzzleAnswer
        fields = ["answer", "round", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4, "cols": 20, "class": "notes-field"}),
        }


class RoundForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super(RoundForm, self).__init__(*args, **kwargs)
        self.fields["editors"] = UserMultipleChoiceField(
            required=False, editors_only=True
        )

    class Meta:
        model = Round
        fields = ["name", "description", "editors"]

@permission_required("puzzle_editing.change_round", raise_exception=True)
def byround_eic(request, id=None):
    return byround(request, id, eic_view=True)

@login_required
def byround(request, id=None, eic_view=False):
    round_objs = Round.objects.all()
    if id:
        round_objs = round_objs.filter(pk=id)
    round_objs = round_objs.prefetch_related('answers', 'editors').order_by(Lower('name'))

    rounds = [
        {
            "id": round.id,
            "name": round.name,
            "description": round.description,
            "answers": [
                {
                    "answer": answer.answer,
                    "id": answer.id,
                    "notes": answer.notes,
                    "puzzles": answer.puzzles.all(), #.exclude(status=status.DEAD).exclude(status=status.DEFERRED),
                }
                for answer in round.answers.all().prefetch_related('puzzles').prefetch_related('puzzles__authors').prefetch_related('puzzles__postprod').order_by(Lower('answer'))
            ],
            "editor": round.editors.first(),
        }
        for round in round_objs
    ]

    eics = set()
    for round in round_objs:
        eic = round.editors.first()
        if eic is not None:
            eics.add(eic)

    return render(
        request,
        "allrounds.html",
        {
            "rounds": rounds,
            "eics": eics,
            "eic_view": eic_view,
            "single_round": rounds[0] if id else None,
        },
    )

@permission_required("puzzle_editing.change_round", raise_exception=True)
def rounds(request, id=None):
    user = request.user

    new_round_form = RoundForm()
    if request.method == "POST":
        if "spoil_on" in request.POST:
            get_object_or_404(Round, id=request.POST["spoil_on"]).spoiled.add(user)

        elif "new_round" in request.POST:
            new_round_form = RoundForm(request.POST)
            if new_round_form.is_valid():
                new_round = new_round_form.save()
                new_round.spoiled.add(user)

        elif "add_answer" in request.POST:
            answer_form = AnswerForm(None, request.POST)
            if answer_form.is_valid():
                answer_form.save()

        elif "delete_answer" in request.POST:
            get_object_or_404(PuzzleAnswer, id=request.POST["delete_answer"]).delete()

        return redirect(urls.reverse("rounds"))

    round_objs = Round.objects.all()
    if id:
        round_objs = round_objs.filter(pk=id)
    round_objs = round_objs.prefetch_related('answers', 'editors').order_by(Lower('name'))

    rounds = [
        {
            "id": round.id,
            "name": round.name,
            "description": round.description,
            "spoiled": round.spoiled.filter(id=user.id).exists(),
            "answers": [
                {
                    "answer": answer.answer,
                    "id": answer.id,
                    "notes": answer.notes,
                    "puzzles": answer.puzzles.all(),
                }
                for answer in round.answers.all().order_by(Lower('answer'))
            ],
            "form": AnswerForm(round),
            "editors": round.editors.all().order_by(Lower('display_name')),
        }
        for round in round_objs
    ]

    return render(
        request,
        "rounds.html",
        {
            "rounds": rounds,
            "single_round": rounds[0] if id else None,
            "new_round_form": RoundForm(),
        },
    )


@permission_required("puzzle_editing.change_round", raise_exception=True)
def edit_round(request, id):
    round = get_object_or_404(Round, id=id)
    if request.method == "POST":
        print(request.POST)
        if request.POST.get("delete") and request.POST.get("sure-delete") == "on":
            round.delete()
            return redirect(urls.reverse("rounds"))
        form = RoundForm(request.POST, instance=round)
        if form.is_valid():
            form.save()

            return redirect(urls.reverse("rounds"))
        else:
            return render(request, "edit_round.html", {"form": form})
    return render(
        request,
        "edit_round.html",
        {
            "form": RoundForm(instance=round),
            "round": round,
            "has_answers": round.answers.count(),
        },
    )

@login_required
def support_all(request):
    open_requests = SupportRequest.objects.filter(status__in=["REQ","APP"]).order_by("team", "status")
    closed_requests = SupportRequest.objects.exclude(status__in=["REQ","APP"]).order_by("team", "status")

    if "team" in request.GET:
        team = request.GET['team']
        if not team == "ALL":
            open_requests = open_requests.filter(team=team)
            closed_requests = closed_requests.filter(team=team)
        if team == 'ACC':
            team_title = 'Accessibility'

    else:
        team = "ALL"

    team_title = team.title()

    return render(
        request,
        "support_all.html",
        {
            "title": f"{team_title} support requests",
            "open_requests": open_requests,
            "closed_requests": closed_requests,
            "type": "all",
            "team": team
        },
    )

@login_required
def support_by_puzzle(request, id):
    '''Show all requests for a puzzle or create one'''
    puzzle = get_object_or_404(Puzzle, id=id)
    support = []
    for team, team_name in SupportRequest.Team.choices:
        support.append({
            "obj": SupportRequest.objects.filter(team=team).filter(puzzle=puzzle).first(),
            "short": team,
            "display": team_name,
        })
    # if post = create support for puzzle then redirect to support_one
    # else show all for puzzle plus links to create
    return render(
        request,
        "support_for_puzzle.html",
        {
            "title": f"Support requests for {puzzle.name}",
            "type": "puzzle",
            "support": support,
            "puzzle": puzzle,
        },
    )


@login_required
def support_by_puzzle_id(request, id, team):
    '''Show support by puzzle and type or else show form to create a new one'''
    id = int(id)
    puzzle = get_object_or_404(Puzzle, pk=id)
    if request.method == "POST" and "create" in request.POST:
        support = SupportRequest.objects.create(puzzle=puzzle,team=team)
    else:
        try:
            support = SupportRequest.objects.get(puzzle=puzzle, team=team)
        except SupportRequest.DoesNotExist:
            return render(
                request,
                "support_confirm.html",
                {
                    "puzzle": puzzle,
                }
            )

    if request.method == "POST":
        if "edit_team_notes" in request.POST:
            old_notes = support.team_notes
            team_notes_form = SupportRequestTeamNotesForm(request.POST, instance=support)
            if team_notes_form.is_valid():
                old_status = support.get_status_display
                team_notes_form.save()
                support.team_notes_updater = request.user
                support.team_notes_mtime = datetime.datetime.now(datetime.timezone.utc).astimezone()
                support.save()
                new_notes = support.team_notes
                messaging.send_mail_wrapper(
                    f"{support.get_team_display()} team support request update for {support.puzzle.name}",
                    "emails/support_update",
                    {
                        "request": request,
                        "support": support,
                        "old_notes": old_notes,
                        "new_notes": new_notes,
                        "old_status": old_status,
                    },
                    support.puzzle.get_emails(),
                )
        elif "edit_author_notes" in request.POST:
            old_notes = support.author_notes
            author_notes_form = SupportRequestAuthorNotesForm(request.POST, instance=support)
            if author_notes_form.is_valid():
                old_status = support.get_status_display
                author_notes_form.save()
                support.author_notes_updater = request.user
                support.author_notes_mtime = datetime.datetime.now(datetime.timezone.utc).astimezone()
                if support.status in ["APP", "COMP"]:
                    support.outdated = True
                support.save()
                new_notes = support.author_notes
                messaging.send_mail_wrapper(
                    f"{support.get_team_display()} team support request update for {support.puzzle.name}",
                    "emails/support_update",
                    {
                        "request": request,
                        "support": support,
                        "old_notes": old_notes,
                        "new_notes": new_notes,
                        "old_status": old_status,
                    },
                    support.get_emails(),
                )
                # add call to email team with update and new status
        elif "update_status" in request.POST:
            status_form = SupportRequestStatusForm(request.POST, instance=support)
            if status_form.is_valid():
                status_form.save()
                if support.outdated:
                    support.outdated = False
                    support.save()

    return render(
        request,
        'support_view.html',
        {
            "support": support,
            "author_notes_form": SupportRequestAuthorNotesForm(instance=support),
            "team_notes_form": SupportRequestTeamNotesForm(instance=support),
            "status_form": SupportRequestStatusForm(instance=support)
        }
    )

@permission_required("puzzle_editing.change_round", raise_exception=True)
def edit_answer(request, id):
    answer = get_object_or_404(PuzzleAnswer, id=id)

    if request.method == "POST":
        answer_form = AnswerForm(
            answer.round,
            request.POST,
            instance=answer
        )
        if answer_form.is_valid():
            answer_form.save()

            return redirect(urls.reverse("edit_answer", args=[id]))
    else:
        answer_form = AnswerForm(answer.round, instance=answer)

    return render(request, "edit_answer.html", {
        "answer": answer,
        "form": answer_form
    })


@permission_required("puzzle_editing.change_round", raise_exception=True)
def bulk_add_answers(request, id):
    round = get_object_or_404(Round, id=id)
    if request.method == "POST":
        lines = request.POST["bulk_add_answers"].split("\n")
        answers = [line.strip() for line in lines]

        PuzzleAnswer.objects.bulk_create(
            [PuzzleAnswer(answer=answer, round=round) for answer in answers if answer]
        )

        return redirect(urls.reverse("bulk_add_answers", args=[id]))

    return render(
        request,
        "bulk_add_answers.html",
        {
            "round": round,
        },
    )


@login_required
@permission_required("puzzle_editing.change_round", raise_exception=True)
def tags(request):
    return render(
        request,
        "tags.html",
        {"tags": PuzzleTag.objects.all().annotate(count=Count("puzzles"))},
    )

@login_required
def statistics(request):
    past_writing = 0
    past_testsolving = 0
    non_puzzle_schedule_tags = ["meta", "navigation", "event"]

    all_counts = (
        Puzzle.objects.values("status")
        .order_by("status")
        .annotate(count=Count("status"))
    )
    rest = dict((p["status"], p["count"]) for p in all_counts)
    tags = PuzzleTag.objects.filter(important=True)
    tag_counts = {}
    for tag in tags:
        query = (
            Puzzle.objects.filter(tags=tag)
            .values("status")
            .order_by("status")
            .annotate(count=Count("status"))
        )
        tag_counts[tag.name] = dict((p["status"], p["count"]) for p in query)
        for p in query:
            rest[p["status"]] -= p["count"]
    statuses = []
    for p in sorted(all_counts, key=lambda x: status.get_status_rank(x["status"])):
        status_obj = {
            "status": status.get_display(p["status"]),
            "count": p["count"],
            "rest_count": rest[p["status"]],
        }
        if status.past_writing(p["status"]):
            past_writing += p["count"]
        if status.past_testsolving(p["status"]):
            past_testsolving += p["count"]

        for tag in tags:
            status_obj[tag.name] = tag_counts[tag.name].get(p["status"], 0)

            if tag.name in non_puzzle_schedule_tags:
                if status.past_writing(p["status"]):
                    past_writing -= status_obj[tag.name]
                if status.past_testsolving(p["status"]):
                    past_testsolving -= status_obj[tag.name]
        statuses.append(status_obj)
    answers = {
        "assigned": PuzzleAnswer.objects.filter(puzzles__isnull=False).count(),
        "rest": PuzzleAnswer.objects.filter(puzzles__isnull=False).count(),
        "waiting": PuzzleAnswer.objects.filter(puzzles__isnull=True).count(),
    }
    for tag in tags:
        answers[tag.name] = PuzzleAnswer.objects.filter(
            puzzles__isnull=False, puzzles__tags=tag
        ).count()
        answers["rest"] -= answers[tag.name]

    target_count = SiteSetting.get_int_setting("TARGET_PUZZLE_COUNT")
    unreleased_count = SiteSetting.get_int_setting("UNRELEASED_PUZZLE_COUNT")
    image_base64 = curr_puzzle_graph_b64(
        request.GET.get("time", "alltime"), target_count
    )

    return render(
        request,
        "statistics.html",
        {
            "status": statuses,
            "tags": tags,
            "answers": answers,
            "image_base64": image_base64,
            "past_writing": past_writing,
            "past_testsolving": past_testsolving,
            "target_count": target_count,
            "unreleased_count": unreleased_count,
        },
    )


class PuzzleTagForm(forms.ModelForm):
    description = forms.CharField(
        widget=MarkdownTextarea,
        required=False,
        help_text="(optional) Elaborate on the meaning of this tag.",
    )

    class Meta:
        model = PuzzleTag
        fields = ["name", "description", "important"]


@permission_required("puzzle_editing.change_round", raise_exception=True)
def new_tag(request):
    if request.method == "POST":
        form = PuzzleTagForm(request.POST)
        if form.is_valid():
            form.save()

            return redirect(urls.reverse("tags"))
        else:
            return render(request, "new_tag.html", {"form": form})
    return render(request, "new_tag.html", {"form": PuzzleTagForm()})


@login_required
def single_tag(request, id):
    tag = get_object_or_404(PuzzleTag, id=id)

    count = tag.puzzles.count()
    if count == 1:
        label = "1 puzzle"
    else:
        label = "{} puzzles".format(count)
    return render(
        request,
        "single_tag.html",
        {
            "tag": tag,
            "count_label": label,
        },
    )


@permission_required("puzzle_editing.change_round", raise_exception=True)
def edit_tag(request, id):
    tag = get_object_or_404(PuzzleTag, id=id)
    if request.method == "POST":
        form = PuzzleTagForm(request.POST, instance=tag)
        if form.is_valid():
            form.save()

            return redirect(urls.reverse("tags"))
        else:
            return render(request, "edit_tag.html", {"form": form, "tag": tag})
    return render(
        request,
        "edit_tag.html",
        {
            "form": PuzzleTagForm(instance=tag),
            "tag": tag,
        },
    )


# distinct=True because
# https://stackoverflow.com/questions/59071464/django-how-to-annotate-manytomany-field-with-count
# Doing separate aggregations across these fields and manually joining because
# the query resulting from doing them all at once seems to be very slow? Takes
# a list (not QuerySet) of all users and a dictionary of annotation names to
# Django annotations; mutates the users by adding the corresponding attributes
# to them.
def annotate_users_helper(user_list, annotation_kwargs):
    id_dict = dict()
    for my_user in User.objects.all().annotate(**annotation_kwargs):
        id_dict[my_user.id] = my_user
    for user in user_list:
        my_user = id_dict[user.id]
        for k in annotation_kwargs:
            setattr(user, k, getattr(my_user, k))


@login_required
def users(request):
    users = list(User.objects.all().order_by(Lower('display_name')))

    for key in ["authored", "editing", "factchecking"]:
        annotation_kwargs = dict()
        annotation_kwargs[key + "_active"] = Count(
            key + "_puzzles",
            filter=~Q(
                **{
                    key
                    + "_puzzles__status__in": [
                        status.DEAD,
                        status.DEFERRED,
                        status.DONE,
                    ]
                }
            ),
            distinct=True,
        )
        annotation_kwargs[key + "_deferred"] = Count(
            key + "_puzzles",
            filter=Q(**{key + "_puzzles__status": status.DEFERRED}),
            distinct=True,
        )
        annotation_kwargs[key + "_dead"] = Count(
            key + "_puzzles",
            filter=Q(**{key + "_puzzles__status": status.DEAD}),
            distinct=True,
        )
        annotation_kwargs[key + "_done"] = Count(
            key + "_puzzles",
            filter=Q(**{key + "_puzzles__status": status.DONE}),
            distinct=True,
        )
        annotate_users_helper(users, annotation_kwargs)
    annotation_kwargs = dict()
    annotation_kwargs["testsolving_done"] = Count(
        "testsolve_participations",
        filter=Q(testsolve_participations__ended__isnull=False),
        distinct=True,
    )
    annotation_kwargs["testsolving_in_progress"] = Count(
        "testsolve_participations",
        filter=Q(testsolve_participations__ended__isnull=True),
        distinct=True,
    )
    annotate_users_helper(users, annotation_kwargs)

    for user in users:
        user.full_display_name = get_full_display_name(user)
        # FIXME You can do this quickly in Django 3.x
        user.is_meta_editor = user.has_perm("puzzle_editing.change_round")

    return render(
        request,
        "users.html",
        {
            "users": users,
        },
    )


@login_required
def users_statuses(request):
    # distinct=True because https://stackoverflow.com/questions/59071464/django-how-to-annotate-manytomany-field-with-count
    annotation_kwargs = {
        stat: Count(
            "authored_puzzles", filter=Q(authored_puzzles__status=stat), distinct=True
        )
        for stat in status.STATUSES
    }

    users = User.objects.all().annotate(**annotation_kwargs)

    users = list(users)
    for user in users:
        user.full_display_name = get_full_display_name(user)
        user.is_meta_editor = user.has_perm("puzzle_editing.change_round")
        user.stats = [getattr(user, stat) for stat in status.STATUSES]

    return render(
        request,
        "users_statuses.html",
        {
            "users": users,
            "statuses": [status.DESCRIPTIONS[stat] for stat in status.STATUSES],
        },
    )


@login_required
def user(request, username: str):
    them = get_object_or_404(User, username=username)
    if request.user.is_superuser and request.method == "POST":
        perm = Permission.objects.filter(name="Can change round").first()
        if "remove-editor" in request.POST:
            them.user_permissions.remove(perm)
        elif "make-editor" in request.POST:
            them.user_permissions.add(perm)

    them.is_meta_editor = them.has_perm("puzzle_editing.change_round")
    return render(
        request,
        "user.html",
        {
            "them": them,
            "testsolving_sessions": TestsolveSession.objects.filter(
                participations__user=them.id
            ),
        },
    )


@csrf_exempt
def preview_markdown(request):
    if request.method == "POST":
        output = render_to_string(
            "preview_markdown.html", {"input": request.body.decode("utf-8")}
        )
        return JsonResponse(
            {
                "success": True,
                "output": output,
            }
        )
    return JsonResponse(
        {
            "success": False,
            "error": "No markdown input received",
        }
    )
