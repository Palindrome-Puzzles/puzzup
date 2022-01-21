import re

import django.urls as urls
from django.contrib.auth.models import AbstractUser
from django.core.validators import FileExtensionValidator
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Avg
from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.html import format_html
from django.utils.html import format_html_join
from django.utils.safestring import mark_safe
from django.conf import settings

import puzzle_editing.status as status


class User(AbstractUser):
    # All of these are populated by the discord sync.
    discord_username = models.CharField(max_length=500, blank=True)
    discord_nickname = models.CharField(max_length=500, blank=True)
    discord_user_id = models.CharField(max_length=500, blank=True)
    avatar_url = models.CharField(max_length=500, blank=True)

    display_name = models.CharField(
        max_length=500,
        blank=True,
        help_text="How you want your name to appear to other puzzup users.")

    credits_name = models.CharField(
        max_length=80,
        help_text=("How you want your name to appear in puzzle credits, e.g. "
                   "Ben Bitdiddle"),
    )
    bio = models.TextField(
        blank=True,
        help_text=("Tell us about yourself. What kinds of puzzle genres or "
                   "subject matter do you like?"),
    )
    enable_keyboard_shortcuts = models.BooleanField(default=False)

    @property
    def is_eic(self):
        return self.groups.filter(name='EIC').exists()

    @property
    def is_editor(self):
        return self.groups.filter(name='Editor').exists()

    @property
    def hat(self):
        if self.is_eic:
            return "🎩"
        elif self.is_editor:
            return "👒"
        elif self.is_staff:
            return "🧢"
        return ""

    # Some of this templating is done in an inner loop, so doing it with
    # inclusion tags turns out to be a big performance hit. They're also small
    # enough to be pretty easy to write in Python. Separating out the versions
    # that don't even bother taking a User and just take two strings might be a
    # bit premature, but I think skipping prefetching and model construction is
    # worth it in an inner loop...
    @staticmethod
    def html_user_display_of_flat(username, display_name, linkify):
        if display_name:
            ret = format_html('<span title="{}">{}</span>', username, display_name)
        else:
            ret = username

        if linkify:
            return format_html(
                '<a href="{}">{}</a>', urls.reverse("user", args=[username]), ret
            )
        else:
            return ret

    @staticmethod
    def html_user_display_of(user, linkify):
        return User.html_user_display_of_flat(user.username, user.display_name, linkify)

    @staticmethod
    def html_user_list_of_flat(ud_pairs, linkify):
        # iterate over ud_pairs exactly once
        s = format_html_join(
            ", ",
            "{}",
            ((User.html_user_display_of_flat(un, dn, linkify),) for un, dn in ud_pairs),
        )
        return s or mark_safe('<span class="empty">--</span>')

    @staticmethod
    def html_user_list_of(users, linkify):
        return User.html_user_list_of_flat(
            ((user.username, user.display_name) for user in users),
            linkify,
        )

    @staticmethod
    def html_avatar_list_of(users, linkify):
        def fmt_user(u):
            img = "<img src='{}' width='40' height='40'/>"
            if linkify:
                url = urls.reverse("user", args=[u.username])
                return format_html('<a href="{}">'+img+'</a>', url, u.avatar_url)
            return format_html(img, u.avatar_url)
        s = format_html_join(" ", "{}", ((fmt_user(u),) for u in users))
        return s or mark_safe('<span class="empty">--</span>')


    def get_avatar_url_via_discord(self, discord_avatar_hash, size:int=0)->str:
        '''Generates and returns the discord avatar url if possible
        Accepts an optional argument that defines the size of the avatar returned, between 16 and 4096 (in powers of 2),
        though this can be set when hotlinked.'''

        cdn_base_url = "https://cdn.discordapp.com"

        if not self.discord_user_id:
            # we'll only "trust" information given to us by the discord API; users who haven't linked that way won't have any avatar
            return 'a'

        if self.discord_username and not discord_avatar_hash:
            # This is a user with no avatar hash; accordingly, we will give them the default avatar
            try:
                discriminator = self.discord_username.split("#")[1]
            except IndexError:
                return 'b'

            return f"{cdn_base_url}/embed/avatars/{discriminator}.png"

        if discord_avatar_hash and self.discord_user_id:
            if size > 0:
                size = (size - (size %  2))
                size = 16 if size < 16 else size
                size = 4096 if size > 4096 else size

            return f"{cdn_base_url}/avatars/{self.discord_user_id}/{discord_avatar_hash}.png" + (f"?size={size}" if size > 0 else "")

        return 'd'


class Round(models.Model):
    """A round of answers feeding into the same metapuzzle or set of metapuzzles."""

    name = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    spoiled = models.ManyToManyField(
        User,
        blank=True,
        related_name="spoiled_rounds",
        help_text="Users spoiled on the round's answers.",
    )
    editors = models.ManyToManyField(User, related_name="editors", blank=True)

    def __str__(self):  # pylint: disable=invalid-str-returned
        return self.name


class PuzzleAnswer(models.Model):
    """An answer. Can be assigned to zero, one, or more puzzles."""

    answer = models.CharField(max_length=500, blank=True)
    round = models.ForeignKey(Round, on_delete=models.PROTECT, related_name="answers")
    notes = models.TextField(blank=True)

    def __str__(self):  # pylint: disable=invalid-str-returned
        return self.answer

class PuzzleTag(models.Model):
    """A tag to classify puzzles."""

    name = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    important = models.BooleanField(
        default=False,
        help_text="Important tags are displayed prominently with the puzzle title.",
    )

    def __str__(self):
        return "Tag: {}".format(self.name)



class Puzzle(models.Model):
    """A puzzle, that which Puzzup keeps track of the writing process of."""

    name = models.CharField(max_length=500)
    codename = models.CharField(
        max_length=500,
        blank=True,
        help_text="A non-spoilery name if you're concerned about the name being a spoiler. Leave empty otherwise.",
    )

    discord_channel_id = models.CharField(
        max_length=19,
        blank=True,
    )

    def spoiler_free_name(self):
        if self.codename:
            return "({})".format(self.codename)
        return self.name

    def spoiler_free_title(self):
        return self.spoiler_free_name()

    @property
    def spoilery_title(self):
        name = self.name
        if self.codename:
            name += " ({})".format(self.codename)
        return name

    def important_tag_names(self):
        if hasattr(self, "prefetched_important_tag_names"):
            return self.prefetched_important_tag_names
        return self.tags.filter(important=True).values_list("name", flat=True)

    # This is done in an inner loop, so doing it with inclusion tags turns
    # out to be a big performance hit. They're also small enough to be pretty
    # easy to write in Python.
    def html_display(self):
        return format_html(
            "{}: {} {}",
            self.id,
            format_html_join(
                " ",
                "<sup>[{}]</sup>",
                ((name,) for name in self.important_tag_names()),
            ),
            self.spoiler_free_name(),
        )

    def html_link(self):
        return format_html(
            """<a href="{}" class="puzzle-link">{}</a>""",
            urls.reverse("puzzle", args=[self.id]),
            self.html_display(),
        )

    def html_link_no_tags(self):
        return format_html(
            """<a href="{}" class="puzzle-link">{}</a>""",
            urls.reverse("puzzle", args=[self.id]),
            self.spoiler_free_name(),
        )

    def __str__(self):
        return self.spoiler_free_title()

    authors = models.ManyToManyField(User, related_name="authored_puzzles", blank=True)
    authors_addl = models.CharField(max_length=200, help_text="The second line of author credits. Only use in cases where a standard author credit isn't accurate.", blank=True)

    editors = models.ManyToManyField(User, related_name="editing_puzzles", blank=True)
    needed_editors = models.IntegerField(default=2)
    spoiled = models.ManyToManyField(
        User,
        related_name="spoiled_puzzles",
        blank=True,
        help_text="Users spoiled on the puzzle.",
    )
    factcheckers = models.ManyToManyField(
        User, related_name="factchecking_puzzles", blank=True
    )
    postprodders = models.ManyToManyField(
        User, related_name="postprodding_puzzles", blank=True
    )

    # .get_status_display() is a built-in syntax that will get the human-readable text
    status = models.CharField(
        max_length=status.MAX_LENGTH,
        choices=status.DESCRIPTIONS.items(),
        default=status.INITIAL_IDEA,
    )
    status_mtime = models.DateTimeField(editable=False)

    def get_status_rank(self):
        return status.get_status_rank(self.status)

    def get_status_emoji(self):
        return status.get_emoji(self.status)

    def get_blocker(self):
        # just text describing what the category of blocker is, not a list of
        # Users or anything like that
        return status.get_blocker(self.status)

    def get_transitions(self):
        return [
            {
                "status": s,
                "status_display": status.get_display(s),
                "description": description,
            }
            for s, description in status.get_transitions(self.status, self)
        ]

    last_updated = models.DateTimeField(auto_now=True)

    summary = models.TextField(
        blank=True,
        help_text="A **non-spoilery description.** For potential testsolvers to get a sense if it'll be something they enjoy (without getting spoiled). Useful to mention: how long it'll take, how difficult it is, good for 1 solver or for a group, etc.",
    )
    description = models.TextField(
        help_text="A **spoilery description** of how the puzzle works."
    )
    editor_notes = models.TextField(
        blank=True,
        verbose_name="Mechanics",
        help_text="A **succinct list** of mechanics and themes used."
    )
    notes = models.TextField(
        blank=True,
        help_text="Notes and requests to the editors, like for a particular answer or inclusion in a particular round."
    )
    answers = models.ManyToManyField(PuzzleAnswer, blank=True, related_name="puzzles")
    tags = models.ManyToManyField(PuzzleTag, blank=True, related_name="puzzles")
    priority = models.IntegerField(
        choices=(
            (1, "Very High"),
            (2, "High"),
            (3, "Medium"),
            (4, "Low"),
            (5, "Very Low"),
        ),
        default=3,
    )
    content = models.TextField(
        blank=True, help_text="The puzzle itself. An external link is fine."
    )
    solution = models.TextField(blank=True)
    is_meta = models.BooleanField(
        verbose_name="Is this a meta?",
        help_text="Check the box if yes.",
        default=False
    )

    def get_emails(self, exclude_emails=()):
        # tcs = User.objects.filter(groups__name__in=['Testsolve Coordinators']).exclude(email="").values_list("email", flat=True)

        emails = set(self.authors.values_list("email", flat=True))
        emails |= set(self.editors.values_list("email", flat=True))
        emails |= set(self.factcheckers.values_list("email", flat=True))
        emails |= set(self.postprodders.values_list("email", flat=True))

        emails -= set(exclude_emails)
        emails -= set(("",))

        return list(emails)

    def has_postprod(self):
        try:
            return self.postprod is not None
        except PuzzlePostprod.DoesNotExist:
            return False

    def has_hints(self):
        return self.hints.count() > 0

    def ordered_hints(self):
        return self.hints.order_by("order")

    def has_answer(self):
        return self.answers.count() > 0

    def stub_puzzle(self):
        new_pp = PuzzlePostprod()
        return self

    @property
    def postprod_url(self):
        if self.has_postprod():
            return "{}/{}".format(settings.POSTPROD_URL, self.postprod.slug)
        return ""

    @property
    def hints_array(self):
        return [[h.order, h.keywords.split(","), h.content] for h in self.hints.all()]

    @property
    def author_byline(self):
        credits = [u.credits_name for u in self.authors.all()]
        credits.sort(key=lambda u: u.upper())
        return re.sub(r"([^,]+?), ([^,]+?)$", r"\1 and \2", ", ".join(credits))

    @property
    def metadata(self):
        credits = [u.credits_name for u in self.authors.all()]
        credits.sort(key=lambda u: u.upper())
        editors = [u.credits_name for u in self.editors.all()]
        editors.sort(key=lambda u: u.upper())
        postprodders = [ u.credits_name for u in self.postprodders.all() ]
        postprodders.sort(key=lambda u: u.upper)
        return {
            "puzzle_title": self.name,
            "credits": "by %s" % self.author_byline,
            "answer": ", ".join([a.answer for a in self.answers.all()]) if self.answers.all() else "???",
            "puzzle_idea_id": self.id,
            "other_credits": { c.credit_type: [re.sub(r"([^,]+?), ([^,]+?)$", r"\1 and \2", ", ".join([u.credits_name for u in c.users.all()])), c.text] for c in self.other_credits.all()},
            "additional_authors": self.authors_addl,
            "editors": re.sub(r"([^,]+?), ([^,]+?)$", r"\1 and \2", ", ".join(editors)),
            # "postprodders": re.sub(r"([^,]+?), ([^,]+?)$", r"\1 and \2", ", ".join(postprodders)),
            "puzzle_slug": self.postprod.slug if self.has_postprod() else re.sub(
                r'[<>#%\'"|{}\[\])(\\\^?=`;@&,]',
                "",
                re.sub(r"[ \/]+", "-", self.name),
            ).lower()
        }

    @property
    def slug(self):
        re.sub(r'-+', '-', re.sub(r'[^-\w]+', '', self.codename)).strip('-')

    @property
    def author_list(self):
        return ", ".join([a.credits_name if a.credits_name else a.username for a in self.authors.all()])

    @property
    def editor_list(self):
        return ", ".join([a.credits_name if a.credits_name else a.username for a in self.editors.all()])

class PuzzleCredit(models.Model):
    """A miscellaneous puzzle credit, such as Art"""
    ART = ("ART", "Art")
    TECH = ("TCH", "Tech")
    OTHER = ("OTH", "Other")

    puzzle = models.ForeignKey(Puzzle, related_name="other_credits", on_delete=models.CASCADE)

    users = models.ManyToManyField(User, related_name="other_credits", blank=True)

    text = models.TextField(blank=True)

    credit_type = models.CharField(
        max_length=3,
        choices=[
            ART,
            TECH,
            OTHER
        ],
        default=ART
    )

    def __str__(self):
        return f"{self.get_credit_type_display()}: %s" % (re.sub(r"([^,]+?), ([^,]+?)$", r"\1 and \2", ", ".join([u.credits_name for u in self.users.all()])) or "--")

    class Meta:
        unique_together = ("puzzle", "credit_type")

@receiver(pre_save, sender=Puzzle)
def set_status_mtime(sender, instance, **_):
    try:
        obj = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        pass  # Object is new
    else:
        if obj.status != instance.status:  # Field has changed
            instance.status_mtime = timezone.now()


class SupportRequest(models.Model):
    """A request for support from one of our departments."""

    class Team(models.TextChoices):
        ART = ('ART', '🎨 Art')
        ACC = ('ACC', '🔎 Accessibility')
        TECH = ('TECH', '👩🏽‍💻 Tech')

    class Status(models.TextChoices):
        NONE = ('NO', 'No need')
        REQUESTED = ('REQ', 'Requested')
        APPROVED = ('APP', 'Approved')
        BLOCK = ("BLOK", 'Blocking')
        COMPLETE = ('COMP', 'Completed')
        CANCELLED = ('X', 'Cancelled')

    team = models.CharField(max_length=4, choices=Team.choices)
    puzzle = models.ForeignKey(Puzzle, on_delete=models.CASCADE)
    status = models.CharField(max_length=4, choices=Status.choices, default=Status.REQUESTED)
    team_notes = models.TextField(blank=True)
    team_notes_mtime = models.DateTimeField(auto_now=False,null=True)
    team_notes_updater = models.ForeignKey(User, null=True, on_delete=models.PROTECT, related_name="support_team_requests")
    author_notes = models.TextField(blank=True)
    author_notes_mtime = models.DateTimeField(auto_now=False,null=True)
    author_notes_updater = models.ForeignKey(User, null=True, on_delete=models.PROTECT, related_name="support_author_requests")
    outdated = models.BooleanField(default=False)

    def get_emails(self):

        emails = [u.email for u in User.objects.filter(groups__name=''.join(c for c in self.get_team_display() if c.isascii()).strip())]
        if self.team_notes_updater:
            emails.append(self.team_notes_updater.email)

        return list(set(emails))


    class Meta:
        unique_together = ("puzzle", "team")


def get_location_for_upload(instance, _):
    return f"puzzle_postprods/puzzle_{instance.puzzle.id}.zip"


def sizeof_fmt(num, suffix="B"):
    for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, "Yi", suffix)


class PuzzlePostprod(models.Model):
    puzzle = models.OneToOneField(
        Puzzle, on_delete=models.CASCADE, related_name="postprod"
    )
    slug = models.CharField(
        max_length=50,
        null=False,
        blank=False,
        validators=[RegexValidator(regex=r'[^<>#%"\'|{})(\[\]\/\\\^?=`;@&, ]{1,50}')],
        help_text="The part of the URL on the hunt site referrring to this puzzle. E.g. for https://puzzle.hunt/puzzle/fifty-fifty, this would be 'fifty-fifty'.",
    )
    zip_file = models.FileField(
        null=True,
        blank=True,
        upload_to=get_location_for_upload,
        help_text="A zip file as described above. Leave it blank to keep it the same if you already uploaded one and just want to change the metadata.",
        validators=[FileExtensionValidator(["zip"])],
    )
    # TODO: Delete authors. We're not using this field. Authors are generated alphabetically, and now there's an additional authors field.
    authors = models.CharField(
        max_length=200,
        null=False,
        blank=False,
        help_text="The puzzle authors, as displayed on the solution page",
    )
    complicated_deploy = models.BooleanField(
        help_text="Check this box if your puzzle involves a serverside component of some sort, and it is not entirely contained in the zip file. If you don't know what this means, you probably don't want to check this box."
    )
    mtime = models.DateTimeField(auto_now=True)

    def get_size(self):
        if self.zip_file:
            try:
                return sizeof_fmt(self.zip_file.size)
            except:
                return "(Could not obtain size, zip file does not exist!)"
        else:
            return "(Could not obtain size, zip file does not exist!)"


class StatusSubscription(models.Model):
    """An indication to email a user when any puzzle enters this status."""

    status = models.CharField(
        max_length=status.MAX_LENGTH,
        choices=status.DESCRIPTIONS.items(),
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    def __str__(self):
        return "{} subscription to {}".format(
            self.user, status.get_display(self.status)
        )


class PuzzleVisited(models.Model):
    """A model keeping track of when a user last visited a puzzle page."""

    puzzle = models.ForeignKey(Puzzle, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date = models.DateTimeField(auto_now=True)


class TestsolveSession(models.Model):
    """An attempt by a group of people to testsolve a puzzle.

    Participants in the session will be able to make comments and see other
    comments in the session. People spoiled on the puzzle can also comment and
    view the participants' comments.
    """

    puzzle = models.ForeignKey(
        Puzzle, on_delete=models.CASCADE, related_name="testsolve_sessions"
    )
    started = models.DateTimeField(auto_now_add=True)
    joinable = models.BooleanField(
        default=True,
        help_text="Whether this puzzle is advertised to other users as a session they can join.",
    )
    notes = models.TextField(blank=True)

    def participants(self):
        return User.objects.filter(testsolve_participations__session=self).annotate(
            current=Exists(
                TestsolveParticipation.objects.filter(user=OuterRef("pk"), ended=None)
            )
        )

    def active_participants(self):
        return User.objects.filter(
            testsolve_participations__session=self, testsolve_participations__ended=None
        )

    def get_done_participants_display(self):
        participations = TestsolveParticipation.objects.filter(session=self)
        done_participations = participations.filter(ended__isnull=False)
        return "{} / {}".format(done_participations.count(), participations.count())

    def has_correct_guess(self):
        return TestsolveGuess.objects.filter(session=self, correct=True).exists()

    def get_average_fun(self):
        return TestsolveParticipation.objects.filter(session=self).aggregate(
            Avg("fun_rating")
        )["fun_rating__avg"]

    def get_average_diff(self):
        return TestsolveParticipation.objects.filter(session=self).aggregate(
            Avg("difficulty_rating")
        )["difficulty_rating__avg"]

    def get_average_hours(self):
        return TestsolveParticipation.objects.filter(session=self).aggregate(
            Avg("hours_spent")
        )["hours_spent__avg"]

    def get_emails(self, exclude_emails=()):
        emails = set(self.puzzle.get_emails())
        emails |= set(self.participants().values_list("email", flat=True))

        emails -= set(exclude_emails)
        emails -= set(("",))

        return list(emails)

    def __str__(self):
        return "Testsolve session #{} on {}".format(self.id, self.puzzle)


class PuzzleComment(models.Model):
    """A comment on a puzzle.

    All comments on a puzzle are visible to people spoiled on the puzzle.
    Comments may or may not be associated with a testsolve session; if they
    are, they will also be visible to people participating in or viewing the
    session."""

    puzzle = models.ForeignKey(
        Puzzle, on_delete=models.CASCADE, related_name="comments"
    )
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="comments")
    date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    is_system = models.BooleanField()
    testsolve_session = models.ForeignKey(
        TestsolveSession,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="comments",
    )
    content = models.TextField(
        blank=True,
        help_text="The content of the comment. Should probably only be blank if the status_change is set.",
    )
    status_change = models.CharField(
        max_length=status.MAX_LENGTH,
        choices=status.DESCRIPTIONS.items(),
        blank=True,
        help_text="Any status change caused by this comment. Only used for recording history and computing statistics; not a source of truth (i.e. the puzzle will still store its current status, and this field's value on any comment doesn't directly imply anything about that in any technically enforced way).",
    )

    def __str__(self):
        return "Comment #{} on {}".format(self.id, self.puzzle)


class CommentReaction(models.Model):
    # Since these are frivolous and display-only, I'm not going to bother
    # restricting them on the database model layer.
    EMOJI_OPTIONS = ["👍", "👎", "🎉", "❤️", "😄", "🤔", "😕", "❓", "👀", "✈️"]
    emoji = models.CharField(max_length=8)
    comment = models.ForeignKey(
        PuzzleComment, on_delete=models.CASCADE, related_name="reactions"
    )
    reactor = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="reactions"
    )

    def __str__(self):
        return "{} reacted {} on {}".format(
            self.reactor.username, self.emoji, self.comment
        )

    class Meta:
        unique_together = ("emoji", "comment", "reactor")

    @classmethod
    def toggle(cls, emoji, comment, reactor):
        # This just lets you react with any string to a comment, but it's
        # not the end of the world.
        my_reactions = cls.objects.filter(comment=comment, emoji=emoji, reactor=reactor)
        # Force the queryset instead of checking if it's empty because, if
        # it's not empty, we care about its contents.
        if len(my_reactions) > 0:
            my_reactions.delete()
        else:
            cls(emoji=emoji, comment=comment, reactor=reactor).save()


class TestsolveParticipation(models.Model):
    """Represents one user's participation in a testsolve session.

    Used to record the user's start and end time, as well as ratings on the
    testsolve."""

    session = models.ForeignKey(
        TestsolveSession, on_delete=models.CASCADE, related_name="participations"
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="testsolve_participations"
    )
    started = models.DateTimeField(auto_now_add=True)
    ended = models.DateTimeField(null=True, blank=True)
    fun_rating = models.IntegerField(null=True, blank=True)
    difficulty_rating = models.IntegerField(null=True, blank=True)
    hours_spent = models.FloatField(null=True,  help_text="**Hours spent**. Your best estimate of how many hours you spent on this puzzle. Decimal numbers are allowed.")
    clues_needed = models.TextField(null=True, blank=True, help_text="Did you solve the complete puzzle before getting the answer, or did you shortcut, and if so, how much remained unsolved?")

    aspects_enjoyable = models.TextField(null=True, blank=True,
    help_text="What parts of the puzzle were particularly enjoyable, if any?")
    aspects_unenjoyable = models.TextField(null=True, blank=True, help_text="What parts of the puzzle were not enjoyable, if any?")
    aspects_accessibility = models.TextField(null=True, blank=True, help_text="If you have physical issues such as a hearing impairment, vestibular disorder, etc., what problems did you encounter with this puzzle, if any?")

    technical_issues = models.BooleanField(default=False, null=False, help_text="Did you encounter any technical problems with any aspect of the puzzle, including problems with your browser, any assistive device, etc. as well as any puzzle-specific tech?")
    technical_issues_device = models.TextField(null=True, blank=True, help_text="**If Yes:** What type of device was the issue associated with? Please be as specific as possible (PC vs Mac, what browser, etc")
    technical_issues_description = models.TextField(null=True, blank=True, help_text="**If Yes:** Please describe the issue")

    instructions_overall = models.BooleanField(default=True, null=True, help_text="Were the instructions clear?")
    instructions_feedback = models.TextField(null=True, blank=True, help_text="**If No:** What was confusing about the instructions?")

    FLAVORTEXT_CHOICES = [
        ('helpful', "It was helpful and appropriate"),
        ('too_leading', "It was too leading"),
        ('not_helpful', "It was not helpful"),
        ('confused', "It confused us, or led us in a wrong direction"),
        ('none_but_ok', "There was no flavor text, and that was fine"),
        ('none_not_ok', "There was no flavor text, and I would have liked some"),
    ]

    flavortext_overall = models.CharField(max_length=20, null=True, help_text="Which best describes the flavor text?", choices=FLAVORTEXT_CHOICES)
    flavortext_feedback = models.TextField(null=True, blank=True, help_text="**If Helpful:** How did the flavor text help?")

    stuck_overall = models.BooleanField(default=False, null=False, help_text="**Were you stuck at any point?** E.g. not sure how to start, not sure which data to gather, etc.")
    stuck_points = models.TextField(null=True, blank=True, help_text="**If Yes:** Where did you get stuck? List as many places as relevant.")
    stuck_time = models.FloatField(null=True, blank=True, help_text="**If Yes:** For about how long were you stuck?")
    stuck_unstuck = models.TextField(null=True, blank=True, help_text="**If Yes:** What helped you get unstuck? Was it a satisfying aha?")

    errors_found = models.TextField(null=True, blank=True, help_text="What errors, if any, did you notice in the puzzle?")

    suggestions_change = models.TextField(null=True, blank=True, help_text="Do you have suggestions to change the puzzle? Please explain why your suggestion(s) will help.")

    suggestions_keep = models.TextField(null=True, blank=True, help_text="Do you have suggestions for things that should definitely stay in the puzzle? Please explain what you like about them.")

    def __str__(self):
        return "Testsolve participation: {} in Session #{}".format(
            self.user.username, self.session.id
        )


class TestsolveGuess(models.Model):
    """A guess made by a user in a testsolve session."""

    class Meta:
        verbose_name_plural = "testsolve guesses"

    session = models.ForeignKey(
        TestsolveSession, on_delete=models.CASCADE, related_name="guesses"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="guesses")
    guess = models.TextField(max_length=500, blank=True)
    correct = models.BooleanField()
    date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        correct_text = "Correct" if self.correct else "Incorrect"
        return "{}: {} guess by {} in Session #{}".format(
            self.guess, correct_text, self.user.username, self.session.id
        )


def is_spoiled_on(user, puzzle):
    return puzzle.spoiled.filter(id=user.id).exists()  # is this really the best way??


def is_author_on(user, puzzle):
    return puzzle.authors.filter(id=user.id).exists()


def is_editor_on(user, puzzle):
    return puzzle.editors.filter(id=user.id).exists()


def is_factchecker_on(user, puzzle):
    return puzzle.factcheckers.filter(id=user.id).exists()


def is_postprodder_on(user, puzzle):
    return puzzle.postprodders.filter(id=user.id).exists()


def get_user_role(user, puzzle):
    if is_author_on(user, puzzle):
        return "author"
    elif is_editor_on(user, puzzle):
        return "editor"
    elif is_postprodder_on(user, puzzle):
        return "postprodder"
    elif is_factchecker_on(user, puzzle):
        return "factchecker"
    else:
        return None


class Hint(models.Model):
    class Meta:
        ordering = ["order"]

    puzzle = models.ForeignKey(Puzzle, on_delete=models.PROTECT, related_name="hints")
    order = models.FloatField(
        blank=False,
        null=False,
        help_text="Order in the puzzle - use 0 for a hint at the very beginning of the puzzle, or 100 for a hint on extraction, and then do your best to extrapolate in between. Decimals are okay. For multiple subpuzzles, assign a whole number to each subpuzzle and use decimals off of that whole number for multiple hints in the subpuzzle.",
    )
    keywords = models.CharField(
        max_length=100,
        blank=True,
        null=False,
        help_text="Comma-separated keywords to look for in hunters' hint requests before displaying this hint suggestion",
    )
    content = models.CharField(
        max_length=1000,
        blank=False,
        null=False,
        help_text="Canned hint to give a team (can be edited by us before giving it)",
    )

    def get_keywords(self):
        return self.keywords.split(",")

    def __str__(self):
        return f"Hint #{self.order} for {self.puzzle}"


class SiteSetting(models.Model):
    """Arbitrary settings we don't want to customize from code."""

    key = models.CharField(max_length=100, unique=True)
    value = models.TextField()

    def __str__(self):
        return "{} = {}".format(self.key, self.value)

    @classmethod
    def get_setting(cls, key):
        try:
            return cls.objects.get(key=key).value
        except cls.DoesNotExist:
            return None

    @classmethod
    def get_int_setting(cls, key):
        try:
            return int(cls.objects.get(key=key).value)
        except cls.DoesNotExist:
            return None
        except ValueError:
            return None
