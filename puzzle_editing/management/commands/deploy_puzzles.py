import json
import os
import shutil
from zipfile import ZipFile

import git
from django.conf import settings
from django.core import management
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from puzzle_editing.models import PuzzlePostprod


class Command(BaseCommand):
    help = """Sync puzzles into Hunt Repository."""

    def handle(self, *args, **options):
        if not os.path.exists(settings.HUNT_REPO) and settings.HUNT_REPO:
            management.call_command('setup_git')

        repo = git.Repo.init(settings.HUNT_REPO)
        if (
            repo.is_dirty()
            or len(repo.untracked_files) > 0
            or not repo.head.reference.name in ["master", "main"]
        ):
            raise CommandError("Repository is in a broken state. [{} / {} / {}]".format(repo.is_dirty(), repo.untracked_files, repo.head.reference.name))

        origin = repo.remotes.origin
        origin.pull()

        puzzleFolder = os.path.join(settings.HUNT_REPO, "hunt/data/puzzle")

        shutil.rmtree(puzzleFolder)
        os.makedirs(puzzleFolder)

        for pp in PuzzlePostprod.objects.all():
            answers = pp.puzzle.answers.all()
            answer = "???"
            if answers:
                answer = ", ".join(answers)
            metadata = pp.puzzle.metadata
            puzzlePath = os.path.join(puzzleFolder, pp.slug)
            os.makedirs(puzzlePath)
            zipFile = pp.zip_file
            with ZipFile(zipFile) as zf:
                zf.extractall(puzzlePath)
            with open(os.path.join(puzzlePath, "metadata.json"), "w") as mf:
                json.dump(metadata, mf)
            repo.git.add(puzzlePath)

        if repo.is_dirty() or len(repo.untracked_files) > 0:
            repo.git.add(update=True)
            repo.git.add(A=True)
            repo.git.commit("-m", "Postprodding all puzzles.")
            origin.push()
