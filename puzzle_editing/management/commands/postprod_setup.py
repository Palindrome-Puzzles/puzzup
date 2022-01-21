import json
import os
import re

from django.core.management.base import BaseCommand
from django.conf import settings
from django.http import JsonResponse

from puzzle_editing.models import Puzzle, PuzzlePostprod
from puzzle_editing.views import get_credits_name
import puzzle_editing.status as status

class Command(BaseCommand):
    help = """Create postprod objects for all puzzles that lack them."""

    def handle(self, *args, **options):
        puzzles = Puzzle.objects.all()
        for puzzle in puzzles:
            if puzzle.has_postprod():
                continue
            else:
                print(puzzle.name)
                default_slug = re.sub(
                    r'[<>#%\'"|{}\[\])(\\\^?=`;@&,]',
                    "",
                    re.sub(r"[ \/]+", "-", puzzle.name),
                ).lower()[:50] # slug field has maxlength of 50
                pp = PuzzlePostprod(
                    puzzle = puzzle,
                    slug = default_slug,
                    authors = puzzle.author_byline,
                    complicated_deploy = False,
                )
                pp.save()
                print(pp)