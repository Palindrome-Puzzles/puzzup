from django import template
register = template.Library()

@register.filter()
def check_permission(user, permission):
    if user.user_permissions.filter(codename = permission).exists():
        return True
    return False
