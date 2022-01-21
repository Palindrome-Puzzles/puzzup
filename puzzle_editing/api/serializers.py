from rest_framework import serializers, fields

from puzzle_editing.models import Puzzle, User


class PuzzleSerializer(serializers.HyperlinkedModelSerializer):
    status_mtime = fields.DateTimeField(input_formats=["iso-8601"])

    class Meta:
        model = Puzzle
        fields = [
            "id",
            "name",
            "codename",
            "discord_channel_id",
            "authors",
            "spoiled",
            "needed_editors",
            "editors",
            "factcheckers",
            "postprodders",
            "status",
            "last_updated",
            "summary",
            "description",
            "answers",
            "notes",
            "editor_notes",
            "priority",
            "content",
            "solution",
            "status_mtime"
        ]


class UserSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = User
        fields = ["url", "username", "id", "discord_username"]
