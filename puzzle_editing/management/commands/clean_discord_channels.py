# from collections import Counter
# import logging
# from operator import itemgetter
# import re
# from typing import Any

# import requests

# from django.core.management.base import BaseCommand
# from django.conf import settings

# from puzzle_editing import models as m
# from puzzle_editing import discord_integration as discord
# from puzzle_editing import status
# from puzzle_editing.discord import JsonDict

# _stats = '|'.join([re.escape(status.get_display(s)) for s in status.STATUSES])
# _cat_re = re.compile(rf"^(?P<status>{_stats})(-(?P<num>\d+))?$")

# _stat_order = {status.get_display(s): status.STATUSES.index(s)
#                for s in status.STATUSES}


# class DryRunError(Exception):
#     '''Indicates a dry run tried to write to the server.'''


# def sanitize_channel_name(name: str) -> str:
#     '''A rough approximation of discord channel sanitization.

#     The text is lowercased, spaces become hyphens, multiple hyphens are
#     collapsed, and certain special characters are removed.

#     This is to reduce false positives when we look at a puzzle's title and its
#     corresponding channel name to see if we need to push an update.
#     '''
#     name = name.lower().replace(" ", "-")
#     name = re.sub(r"-+", "-", name)
#     name = re.sub(r"[#!,()'\":?<>{}|[\]@$%^&*=+/\\;.]", "", name)
#     return name


# class CachingClient(discord.Client):
#     '''A discord client that caches things like the set of all channels.

#     Not useful for the site in general, because channels can change in other
#     ways, but e.g. they probably won't change *during one run* of a management
#     command (if they do, the command might break, but that's a small price to
#     pay for making a command much, much faster).
#     '''
#     chmap: dict[str, JsonDict]
#     dry_run: bool

#     def __init__(self, token, guild_id, dry_run=True, logger=None):
#         self.dry_run = dry_run
#         self.logger = logger or logging.getLogger("puzzle_editing.commands")
#         super().__init__(token, guild_id)
#         self.channels = super().get_channels_in_guild()
#         self.chmap = {ch['id']: ch for ch in self.channels}
#         self.roles = super().get_guild_roles()

#     def _debug(self, msg: str, *args, **kwargs):
#         if self.dry_run:
#             msg = 'DRY_RUN: ' + msg
#         self.logger.debug(msg, *args, **kwargs)

#     def _raw_request(
#             self,
#             method: str,
#             endpoint: str,
#             json: Any = None) -> requests.Response:
#         if self.dry_run and method.lower() != "get":
#             # We don't have a response to return in dry_run, so any caller
#             # should be checking dry_run itself instead of calling this.
#             raise DryRunError(f"{method}({endpoint!r}, {json!r})")
#         return super()._raw_request(method, endpoint, json)

#     def _request(self, method: str, endpoint: str, json: Any = None) -> Any:
#         if self.dry_run and method.lower() != "get":
#             # If we get here in a dry run, we can block the call, but we don't
#             # know what the caller is expecting, so we just return None and
#             # hope for the best.
#             self.logger.warning(
#                 "DRY_RUN: blocked %s(%r,%r) but can't fake output - fix "
#                 "calling fn if this breaks.", method, endpoint, json)
#             return None
#         self.logger.debug("%s(%r)", method, endpoint)
#         return super()._request(method, endpoint, json)

#     def get_channels_in_guild(self, typ: int = None) -> list[JsonDict]:
#         '''Get all channels in the guild (optionally of a specific type).'''
#         if typ is None:
#             return list(self.channels)
#         return [ch for ch in self.channels if ch['type'] == typ]

#     def get_channel(self, channel_id: str) -> JsonDict:
#         '''Get a specific channel'''
#         return self.chmap[channel_id]

#     def channel_exists(self, channel_id: str) -> bool:
#         return channel_id in self.chmap

#     def create_channel(self, name: str, typ: int) -> JsonDict:
#         '''Creates a channel in the guild
#         name (str): the channel name, 2-100 characters
#         type (int): the channel type; 0 for text, 1 for DM, 2 for voice,
#                     3 for group DM, 4 for category, 5 for news, 6 for store
#         '''
#         self._debug("Creating channel %s of type %i.", name, typ)
#         if self.dry_run:
#             newch = None
#             for ch in self.channels:
#                 if ch['type'] == typ:
#                     newch = ch.copy()
#                     break
#             if newch is None:
#                 raise DryRunError(f"Can't invent fake channel of type {typ} - "
#                                   "no example exists.")
#             ch = newch
#             ch['id'] = str(int(max(c['id'] for c in self.channels)) + 1)
#             ch['name'] = name
#             ch['position'] = max(c['position'] for c in self.channels) + 1
#         else:
#             ch = super().create_channel(name, typ)
#         self.chmap[ch['id']] = ch
#         self.channels = list(self.chmap.values())
#         return ch

#     def update_channel(self, channel_id: str, **updates) -> JsonDict:
#         '''Update a channel'''
#         curr = self.chmap[channel_id]
#         oldname = updates.get('name')
#         if 'name' in updates:
#             updates['name'] = sanitize_channel_name(oldname)
#         upstr = ''.join(f'{x}={y!r:.40}' for x, y in updates.items())
#         if all(updates[key] == curr.get(key) for key in updates):
#             return curr
#         if oldname:
#             updates['name'] = oldname
#         self._debug("Updating channel %s (%s)", curr['name'], upstr)
#         if self.dry_run:
#             ch = curr
#             ch.update(**updates)
#         else:
#             ch = super().update_channel(channel_id, **updates)
#         self.chmap[ch['id']] = ch
#         self.channels = list(self.chmap.values())
#         return ch

#     def delete_channel(self, channel_id: str) -> dict:
#         '''Delete a channel'''
#         ch = self.chmap.pop(channel_id)
#         self.channels = list(self.chmap.values())
#         self._debug("Deleting channel %s", ch['name'])
#         if self.dry_run:
#             return ch
#         return super().delete_channel(channel_id)

#     def get_guild_roles(self) -> list:
#         return self.roles


# class Command(BaseCommand):
#     help = """Clean up discord status channels."""

#     def __init__(self, *a, **kw):
#         super().__init__(*a, **kw)
#         self.logger = logging.getLogger("puzzle_editing.commands")
#         self.d = None
#         self.dry_run = True

#     def add_arguments(self, parser):
#         parser.add_argument(
#             '--dryrun',
#             action='store_true',
#             help="Don't actually changing anything (use --verbosity=3 to see "
#                  "what would change).")
#         parser.add_argument(
#             '--create-missing',
#             action='store_true',
#             help="Add channels to puzzles that lack them.")
#         parser.add_argument(
#             '--sync-puzzles',
#             action='store_true',
#             help="Sync each puzzle's title, permissions, and status category.")
#         parser.add_argument(
#             '--move-puzzles',
#             action='store_true',
#             help="Move each puzzle to the lowest available category for it")
#         parser.add_argument(
#             '--delete-channels',
#             action='store_true',
#             help="Delete empty status channels")
#         parser.add_argument(
#             '--sort-channels',
#             action='store_true',
#             help="Sort all status channels by status and suffix")
#         parser.add_argument(
#             '--all',
#             action='store_true',
#             help="Shorthand for setting all the modes")

#     def organize_puzzles(self, create: bool, sync: bool, move: bool):
#         '''Fix up puzzle channels in discord.

#         If create is True, create channels for puzzles that don't have them or
#         that have invalid channel_ids (e.g. if their channel was deleted).

#         If sync is True, fix each puzzle channel's name and permissions, and
#         move each puzzle channel to an appropriate category.

#         If move is True, also move each puzzle to the lowest appropriate
#         category with room (e.g. move puzzles from Testsolving-1 to Testsolving
#         if possible).
#         '''
#         puzzles = m.Puzzle.objects.all()
#         self.logger.info("Organizing %i Puzzles...", len(puzzles))
#         p: m.Puzzle
#         for p in puzzles:
#             if not self.d.channel_exists(p.discord_channel_id):
#                 # channel id is empty OR points to an id that doesn't exist
#                 self.logger.warning("Puzzle %i (%s) has bad channel id (%s)",
#                                     p.pk, p.name, p.discord_channel_id)
#                 if not create:
#                     self.logger.warning(
#                         "Refusing to fix without --create-mising")
#                     continue
#                 if self.dry_run:
#                     self.logger.warning("Refusing to fix in dryrun mode.")
#                     continue
#                 p.discord_channel_id = None
#             if not p.discord_channel_id:
#                 # Don't need to check create here - we'll already have bailed
#                 # if the channel wasn't right earlier.
#                 new_channel = self.d.create_channel(p.name, 0)
#                 p.discord_channel_id = new_channel['id']
#                 p.save()
#             elif sync:
#                 p.sync_discord_channel_title()
#             if sync:
#                 if p.sync_discord_status_category(cleanup=move):
#                     self.logger.warning(
#                         "Puzzle %i (%s) had wrong category.", p.pk, p.name)
#             if sync:
#                 p.sync_discord_channel_user_overrides()

#     def organize_categories(self, delete_empty: bool, sort_cats: bool):
#         '''Organize the status categories.

#         If delete_empty is True, status categories (i.e. any category whose
#         name is the display name of a status, optionally followed by -N for
#         some integer N) without channels in them will be deleted.

#         If sort_cats is True, status categories will be sorted, by status order
#         and then by number, so that e.g. Initial Idea will be first, followed
#         by Initial Idea-1, Initial Idea-2 etc. if those exist, then the same
#         for Awaiting Editor, etc.
#         '''
#         # Load channels and get categories and parents
#         channels = self.d.get_channels_in_guild()
#         cat_count = Counter()
#         cats = []
#         for c in channels:
#             if c['type'] == 4:
#                 match = _cat_re.match(c['name'])
#                 if match:
#                     stat = match.group('status')
#                     num = match.group('num') or 0
#                     num = int(num)
#                     c['puzzup_status'] = match.group('status')
#                     c['status_sort_key'] = (_stat_order[stat], num)
#                     cats.append(c)
#             elif c['parent_id']:
#                 cat_count[c['parent_id']] += 1
#         if delete_empty:
#             self.logger.info("Checking %i categories for emptiness.",
#                              len(cats))
#             for cat in list(cats):
#                 if cat['status_sort_key'][1] == 0:
#                     # Don't delete the base 'Inital Idea', etc.
#                     continue
#                 if not cat_count[cat['id']]:
#                     self.logger.info("Deleting empty category %s", cat['name'])
#                     self.d.delete_channel(cat['id'])
#                     cats.remove(cat)
#         if sort_cats:
#             cats.sort(key=itemgetter('status_sort_key'))
#             minpos = min(c['position'] for c in cats)
#             others = [c for c in self.d.get_channels_in_guild(4)
#                       if c['position'] >= minpos and c not in cats]
#             others.sort(key=itemgetter("position"))
#             self.logger.info("Rearranging %i status categories and %i "
#                              "post-status categories.", len(cats), len(others))
#             for i, c in enumerate(cats):
#                 self.d.update_channel(c['id'], position=minpos + i)
#             minpos += len(cats)
#             for i, c in enumerate(others):
#                 self.d.update_channel(c['id'], position=minpos + i)

#     def handle(self, *args, **options):
#         create_missing = options['create_missing'] or options['all']
#         sync_puzzles = options['sync_puzzles'] or options['all']
#         move_puzzles = options['move_puzzles'] or options['all']
#         delete_channels = options['delete_channels'] or options['all']
#         sort_channels = options['sort_channels'] or options['all']
#         self.dry_run = options['dryrun']
#         # Configure Logger
#         vb = options.get('verbosity', 1)
#         levels = {
#             0: logging.ERROR,
#             1: logging.WARN,
#             2: logging.INFO,
#             3: logging.DEBUG,
#         }
#         self.logger.setLevel(levels.get(vb, logging.DEBUG))
#         # Set up our client as the default
#         self.d = CachingClient(
#             settings.DISCORD_BOT_TOKEN,
#             settings.DISCORD_GUILD_ID,
#             dry_run=self.dry_run,
#             logger=self.logger)
#         discord.get_client.client = self.d
#         # Clean up each puzzle
#         if create_missing or sync_puzzles or move_puzzles:
#             self.organize_puzzles(create_missing, sync_puzzles, move_puzzles)
#         # Process categories
#         if delete_channels or sort_channels:
#             self.organize_categories(delete_channels, sort_channels)
