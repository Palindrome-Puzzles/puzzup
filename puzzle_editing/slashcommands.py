import datetime
import json

from django.http import JsonResponse, HttpResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from discord_interactions import verify_key
from puzzle_editing.models import Puzzle
import puzzle_editing.discord_integration as discord

from .discord import MsgPayload

from .view_helpers import external_puzzle_url


@csrf_exempt
def slashCommandHandler(request):
    if not verify_key(request.body, request.headers['X-Signature-Ed25519'], request.headers['X-Signature-Timestamp'], settings.DISCORD_APP_PUBLIC_KEY):
        return HttpResponse('invalid request signature', status=401)
    payload = json.loads(request.body)
    if payload['type'] == 1:
        # this is a ping
        return pingHandler()
    elif payload['type'] == 2:
        if payload['data']['name'] == 'up':
            if payload['data']['options'][0]['type'] == 1:
                if payload['data']['options'][0]['name'] == 'create':
                    return createPuzzleHandler(request, payload)
                elif payload['data']['options'][0]['name'] == 'archive':
                    return archiveChannelHandler(request, payload)
                elif payload['data']['options'][0]['name'] == 'info':
                    return puzzleInfoHandler(request, payload)
                elif payload['data']['options'][0]['name'] == 'url':
                    return puzzleLinkHandler(request, payload)
                else:
                    return genericHandler(payload)


def pingHandler():
    return JsonResponse({'type': 1})


def genericHandler(payload):
    return JsonResponse({'type': 4, 'data': {'content': json.dumps(payload)}})


def createPuzzleHandler(request: HttpRequest, payload: dict) -> HttpResponse:
    ch_id = payload['channel_id']
    msg = create_puzzle_for_channel(request, ch_id)
    if isinstance(msg, str):
        msg = dict(content=msg)
    return JsonResponse(dict(type=4, data=msg))


def create_puzzle_for_channel(request: HttpRequest, ch_id: str) -> MsgPayload:
    if not discord.enabled():
        return ":warning: Discord has been disabled."
    # Check for duplicates
    puzzles = list(Puzzle.objects.filter(discord_channel_id=ch_id))
    if len(puzzles) > 0:
        r = [":warning: This channel is already linked to:"]
        for p in puzzles:
            url = external_puzzle_url(request, p)
            r.append(f" • <{url}>: {p.codename or 'NO CODENAME'} ||{p.name}||")
        return '\n'.join(r)
    c = discord.get_client()
    tc = c.get_text_channel(ch_id)
    puzzle = Puzzle(
        name=tc.name.title().replace('-', ' '),
        description=f'Puzzle created from #{tc.name}',
        discord_channel_id=ch_id,
        status_mtime=datetime.datetime.utcnow().isoformat() + "Z"
    )
    puzzle.save()
    url = external_puzzle_url(request, puzzle)
    discord.sync_puzzle_channel(puzzle, tc, url=url)
    c.save_channel_to_cat(tc, puzzle.get_status_display())
    members_to_ping = set(c.get_message_authors_in_channel(tc.id))
    member_tags = [discord.tag_id(discid) for discid in members_to_ping]
    msg = (
        f":tada: **Puzzle #{puzzle.id}: {puzzle.name}** has been created.\n"
        "This channel will get locked down soon. To retain access, spoil "
        f"yourself on this puzzle at: <{url}>")
    if not member_tags:
        return msg
    msg += "\ncc :"
    space_left = 1999 - len(msg)
    tags_to_include = []
    total = 0
    for tag in member_tags:
        if len(tag) + total > space_left:
            break
        tags_to_include.append(tag)
        total += len(tag)
    return msg + ''.join(tags_to_include)


def archiveChannelHandler(request, payload):
    puzzle = Puzzle.objects.filter(discord_channel_id=payload['channel_id'])
    responseJson = {'type': 4}
    puzzles = [{'name': p.name, 'id': p.id, 'codename': p.codename,
                'summary': p.summary, 'description': p.description} for p in puzzle]
    if len(puzzles) > 0:
        responsetext = ":warning: This puzzle is already linked to the puzzle{} below (you cannot archive a linked channel):\n".format(
            '' if len(puzzles) == 1 else 's')
        responsetext += '\n'.join(['• <https://{}/puzzle/{}>: {} ||{}||'.format(
            request.META['HTTP_HOST'], p['id'], p['codename'] or 'NO CODENAME', p['name']) for p in puzzles])
        responseJson['data'] = {'content': responsetext}
    else:
        c = discord.get_client()
        ch = c.get_text_channel(payload['channel_id'])
        c.save_channel_to_cat(ch, "Archive")
        responsetext = "**This channel has been archived**"
    responseJson = {
        'type': 4,
        'data': {
            'content': responsetext
        }
    }
    return JsonResponse(responseJson)


def puzzleInfoHandler(request, payload):
    puzzle = Puzzle.objects.filter(discord_channel_id=payload['channel_id'])
    responseJson = {'type': 4}
    puzzles = [{'name': p.name, 'id': p.id, 'codename': p.codename,
                'summary': p.summary, 'description': p.description} for p in puzzle]
    responsetext = ''
    if len(puzzles) > 1:
        responsetext += ":warning: This puzzle is linked to multiple puzzles!\n"

    elif len(puzzles) > 0:
        responsetext += '\n'.join(['__{} {}__ <https://{}/puzzle/{}> '.format(p['codename']
                                                                              or 'NO CODENAME', p['name'], request.META['HTTP_HOST'], p['id']) for p in puzzles])

    else:
        responsetext += ":information_source: This channel is not linked to any puzzles"

    responseJson['data'] = {'content': responsetext}
    return JsonResponse(responseJson)


def puzzleLinkHandler(request, payload):
    puzzle = Puzzle.objects.filter(discord_channel_id=payload['channel_id'])
    responseJson = {'type': 4}
    puzzles = [{'name': p.name, 'id': p.id, 'codename': p.codename,
                'summary': p.summary, 'description': p.description} for p in puzzle]
    responsetext = ''
    if len(puzzles) > 1:
        responsetext += ":warning: This puzzle is linked to multiple puzzles!\n"

    elif len(puzzles) > 0:
        responsetext += '\n'.join(['<https://{}/puzzle/{}>'.format(
            request.META['HTTP_HOST'], p['id']) for p in puzzles])

    else:
        responsetext += ":information_source: This channel is not linked to any puzzles"

    responseJson['data'] = {'content': responsetext}
    return JsonResponse(responseJson)
