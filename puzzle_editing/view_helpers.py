from django import urls
from django.http import HttpRequest

from . import models as m


def external_puzzle_url(request: HttpRequest, puzzle: m.Puzzle) -> str:
    '''Get an external URL for a puzzle.'''
    pth = urls.reverse("puzzle", kwargs=dict(id=puzzle.id))
    return request.build_absolute_uri(pth)
