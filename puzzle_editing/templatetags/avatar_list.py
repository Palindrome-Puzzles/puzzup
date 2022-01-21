from django import template

from puzzle_editing.models import User

register = template.Library()


@register.simple_tag
def avatar_list(users, linkify=False, skip_optimize=False):
    """Displays a QuerySet of users"""

    if not skip_optimize:
        users = users.only("avatar_url", "username", "display_name")

    return User.html_avatar_list_of(users, linkify)
