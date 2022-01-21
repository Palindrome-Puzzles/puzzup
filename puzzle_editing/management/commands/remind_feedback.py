from django.core.management.base import BaseCommand

from puzzle_editing.models import Puzzle, TestsolveParticipation, TestsolveSession, User
import puzzle_editing.messaging as messaging

class Command(BaseCommand):
    help = """Remind users to submit feedback"""

    def add_arguments(self, parser):
        parser.add_argument("--dry-run",
            help="Just print a list of users and puzzles they would be reminded about",
            action="store_true")

        parser.add_argument("--email",
            help="Override the email that the reminder emails get sent to")

    def handle(self, *args, **options):
        testsolve_sessions_ended = list(set([o.session_id for o in TestsolveParticipation.objects.filter(ended__isnull=False).only("session").all()]))
        testsolve_participations_in_ended = TestsolveParticipation.objects.filter(ended__isnull=True).filter(session__in=testsolve_sessions_ended)

        user_reminds = {}

        for tp in testsolve_participations_in_ended:
            try:
                user_reminds[tp.user_id].append(tp)
            except KeyError:
                user_reminds[tp.user_id] = [tp]

        if options["dry_run"]:
            print("The following user(s) are yet to leave feedback on testsolve session(s):")

        sent_count = 0
        reminded_count = 0

        for t_user_id, t_sessions in user_reminds.items():
            t_user = User.objects.get(id=t_user_id)
            t_spoiled = [sp.id for sp in t_user.spoiled_puzzles.all()]

            missing_feedback = [ ts for ts in t_sessions if ts.session.puzzle.id not in t_spoiled]


            if options["dry_run"]:
                if missing_feedback:
                    sent_count += 1
                    reminded_count += len(missing_feedback)
                    print(f"\nUser #{t_user.id}: {t_user.credits_name}")
                    for sess in missing_feedback:
                        print(f"Session #{sess.session.id} for puzzle (#{sess.session.puzzle.id}): {sess.session.puzzle.name}")

            else:
                email_address = options["email"] or t_user.email
                if missing_feedback and email_address:
                    sent_count += 1
                    reminded_count += len(missing_feedback)
                    messaging.send_mail_wrapper(
                        "Reminder: submit testsolve feedback",
                        "emails/feedback_reminder_email",
                        {
                            'user': t_user,
                            'outstanding': missing_feedback
                        },
                        [email_address]
                    )
        if options["dry_run"]:
            print(f"\n{sent_count} user(s) would be reminded about {reminded_count} outstanding testsolves")
        else:
            print(f"Reminded {sent_count} user(s) about {reminded_count} outstanding testsolves")

        return
