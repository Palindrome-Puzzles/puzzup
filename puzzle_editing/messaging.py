from django.conf import settings
from django.core.mail.message import EmailMultiAlternatives
from django.template.loader import render_to_string


def send_mail_wrapper(subject, template, context, recipients):
    if recipients:
        mail = EmailMultiAlternatives(
            subject=settings.EMAIL_SUBJECT_PREFIX + subject,
            body=render_to_string(template + ".txt", context),
            from_email="Puzzup no-reply <{}>".format(settings.DEFAULT_FROM_EMAIL),
            to=recipients,
            alternatives=[(render_to_string(template + ".html", context), "text/html")],
            reply_to=["Puzzup no-reply <{}>".format(settings.DEFAULT_FROM_EMAIL)],
        )
        send_res = mail.send()
        if send_res != 1:
            raise RuntimeError(
                "Unknown failure sending mail??? {} {}".format(recipients, send_res)
            )
