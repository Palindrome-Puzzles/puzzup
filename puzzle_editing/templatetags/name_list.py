from django import template

register = template.Library()

@register.filter()
def name_list(users):
    """Displays a comma-delimited list of users"""
    return ", ".join([user.display_name for user in users])