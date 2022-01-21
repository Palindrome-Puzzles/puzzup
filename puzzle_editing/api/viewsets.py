from rest_framework import viewsets

from puzzle_editing.api.serializers import PuzzleSerializer
from puzzle_editing.api.serializers import UserSerializer
from puzzle_editing.models import Puzzle
from puzzle_editing.models import User

# Serializers define the API representation.


# ViewSets define the view behavior.
class UserViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    filterset_fields = ["discord_username"]


class PuzzleViewSet(viewsets.ModelViewSet):
    queryset = Puzzle.objects.all()
    serializer_class = PuzzleSerializer
    filterset_fields = ["discord_channel_id"]
