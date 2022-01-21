import json
import os
import re
import git
import shutil
import time
from zipfile import ZIP_DEFLATED
from zipfile import ZipFile

from django.conf import settings
from django.core import management
from django.core.management.base import CommandError

from puzzle_editing.models import Puzzle, PuzzlePostprod
import puzzle_editing.status as status


def export_data(export_hints=False, export_metadata=False):
    if not settings.DEBUG:
        if not os.path.exists(settings.HUNT_REPO) and settings.HUNT_REPO:
            management.call_command('setup_git')

    exported = []
    if export_metadata:
        exported.append("metadata")
    if export_hints:
        exported.append("hints")

    repo = git.Repo.init(settings.HUNT_REPO)

    # origin = repo.remotes.origin
    # origin.pull()
    # repo.git.checkout("main")

    branch_name = "{}_{}".format("".join(exported),int(time.time()))
    repo.git.checkout("-b", branch_name)

    if (
        repo.is_dirty()
        or len(repo.untracked_files) > 0
        or not repo.head.reference.name in [branch_name] # ["master", "main"]
    ):
        raise CommandError("Repository is in a broken state. [{} / {} / {}]".format(repo.is_dirty(), repo.untracked_files, repo.head.reference.name))

    puzzleFolder = os.path.join(settings.HUNT_REPO, "hunt/data/puzzle")

    puzzles = Puzzle.objects.filter(status__in=[
        status.NEEDS_POSTPROD,
        status.ACTIVELY_POSTPRODDING,
        status.POSTPROD_BLOCKED,
        status.POSTPROD_BLOCKED_ON_TECH,
        status.AWAITING_POSTPROD_APPROVAL,
        status.NEEDS_FACTCHECK,
        status.NEEDS_FINAL_REVISIONS,
        status.NEEDS_COPY_EDITS,
        status.NEEDS_HINTS,
        status.AWAITING_HINTS_APPROVAL,
        status.DONE,
    ])

    for puzzle in puzzles:
        if not (puzzle.has_postprod()):
            print("Creating postprod obj for {}.".format(puzzle.name))
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

        slug = puzzle.postprod.slug

        if not os.path.exists(puzzleFolder):
            os.makedirs(puzzleFolder)

        puzzlePath = os.path.join(puzzleFolder, slug)

        if not os.path.exists(puzzlePath):
            os.makedirs(puzzlePath)

        if export_metadata:
            metadatafile_path = os.path.join(puzzlePath, 'metadata.json')
            outdata = []
            try:
                outdata = puzzle.metadata
            except Exception as e:
                print(metadatafile_path, e)
                # sys.exit(1)

            if outdata and outdata['answer'] != "???":
                with open(metadatafile_path, 'w+') as metadatafile:
                    json.dump(outdata, metadatafile)

        if export_hints:
            hintfile_path = os.path.join(puzzlePath, 'hints.json')
            hintdata = []
            try:
                for hint in puzzle.hints.all():
                    hintdata.append([
                        hint.order,
                        hint.keywords.split(','),
                        hint.content,
                    ])
            except Exception as e:
                print(hintfile_path, e)
                # sys.exit(1)

            if hintdata:
                with open(hintfile_path, 'w+') as hintfile:
                    json.dump(hintdata, hintfile)

    if repo.is_dirty() or len(repo.untracked_files) > 0:
        repo.git.add(update=True)
        repo.git.add(A=True)
        repo.git.commit("-m", "Exported all {}".format(", ".join(exported)))
        if not settings.DEBUG:
            repo.git.push('--set-upstream', repo.remote().name, branch_name)

def get_latest_zip(pp):
    if not os.path.exists(settings.HUNT_REPO) and settings.HUNT_REPO:
        management.call_command('setup_git')
    try:
        repo = git.Repo.init(settings.HUNT_REPO)
    except BaseException:
        pp.slug = "THIS_URL_IS_FAKE_SINCE_YOU_UPLOADED_THIS_PUZZLE_ON_LOCAL"
        return

    if (
        repo.is_dirty()
        or len(repo.untracked_files) > 0
        or not repo.head.reference.name in ["master", "main"]
    ):
        raise Exception("Repository is in a broken state.")

    origin = repo.remotes.origin
    origin.pull()

    puzzleFolder = os.path.join(settings.HUNT_REPO, "hunt/data/puzzle")
    puzzlePath = os.path.join(puzzleFolder, pp.slug)
    zipPath = f"/tmp/puzzle{pp.puzzle.id}.zip"

    if os.path.exists(zipPath):
        os.remove(zipPath)

    with ZipFile(zipPath, "w", ZIP_DEFLATED) as zipHandle:
        for root, _, files in os.walk(puzzlePath):
            for file in files:
                if file != "metadata.json":
                    zipHandle.write(
                        os.path.join(root, file),
                        os.path.relpath(os.path.join(root, file), puzzlePath),
                    )

    return zipPath

def deploy_puzzle(pp, deploy_zip=True):
    if settings.DEBUG:
        return

    if not os.path.exists(settings.HUNT_REPO) and settings.HUNT_REPO:
        management.call_command('setup_git')
    try:
        repo = git.Repo.init(settings.HUNT_REPO)
    except BaseException:
        pp.slug = "THIS_URL_IS_FAKE_SINCE_YOU_UPLOADED_THIS_PUZZLE_ON_LOCAL"
        return

    if (
        repo.is_dirty()
        or len(repo.untracked_files) > 0
        or not repo.head.reference.name in ["master", "main"]
    ):
        print(repo.untracked_files)
        raise Exception("Repository is in a broken state. [{} / {} / {}]".format(repo.is_dirty(), len(repo.untracked_files), repo.head.reference.name))

    origin = repo.remotes.origin
    origin.pull()

    puzzleFolder = os.path.join(settings.HUNT_REPO, "hunt/data/puzzle")
    answers = pp.puzzle.answers.all()
    answer = "???"
    if answers:
        answer = ", ".join(a.answer for a in answers)
    metadata = pp.puzzle.metadata
    puzzlePath = os.path.join(puzzleFolder, pp.slug)
    if deploy_zip:
        if os.path.exists(puzzlePath):
            shutil.rmtree(puzzlePath)
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
        repo.git.commit("-m", "Postprodding '%s'." % (pp.slug))
        origin.push()
