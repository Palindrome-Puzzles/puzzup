from django import template

from puzzle_editing.models import User

register = template.Library()


@register.simple_tag
def user_list(users, linkify=False, skip_optimize=False):
    """Displays a QuerySet of users"""

    if not skip_optimize:
        users = users.only("username", "display_name")

    return User.html_user_list_of(users, linkify)
