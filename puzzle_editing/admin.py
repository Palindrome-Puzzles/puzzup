from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from import_export import resources
from import_export.admin import ImportExportModelAdmin

from .models import CommentReaction
from .models import Hint
from .models import Puzzle
from .models import PuzzleAnswer
from .models import PuzzleComment
from .models import PuzzlePostprod
from .models import PuzzleTag
from .models import PuzzleVisited
from .models import Round
from .models import SiteSetting
from .models import StatusSubscription
from .models import TestsolveGuess
from .models import TestsolveParticipation
from .models import TestsolveSession
from .models import User


class UserAdmin(BaseUserAdmin):
    '''Extends default UserAdmin with our new fields.'''
    list_display = ('username', 'email', 'display_name', 'discord_username',
                    'hat')

    fieldsets = BaseUserAdmin.fieldsets + (
        (None, {'fields': (
            'display_name',
            'discord_username',
            'discord_nickname',
            'discord_user_id',
            'avatar_url',
            'credits_name',
            'bio',
            'enable_keyboard_shortcuts',
        )}),
    )

class TestsolveParticipationAdmin(ImportExportModelAdmin):
    model = TestsolveParticipation

admin.site.register(User, UserAdmin)
admin.site.register(Round)
admin.site.register(PuzzleAnswer)
admin.site.register(Puzzle)
admin.site.register(PuzzleTag)
admin.site.register(PuzzlePostprod)
admin.site.register(PuzzleVisited)
admin.site.register(StatusSubscription)
admin.site.register(TestsolveSession)
admin.site.register(PuzzleComment)
admin.site.register(TestsolveParticipation, TestsolveParticipationAdmin)
admin.site.register(TestsolveGuess)
admin.site.register(Hint)
admin.site.register(CommentReaction)
admin.site.register(SiteSetting)
