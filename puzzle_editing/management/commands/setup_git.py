import os
import shutil
import git
from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

class Command(BaseCommand):
    help = """Set up git repository, deleting any directory at HUNT_REPO"""

    def handle(self, *args, **options):
        if not ( settings.HUNT_REPO_URL and settings.HUNT_REPO ):
            print("Missing one of: {}, {}".format(settings.HUNT_REPO_URL, settings.HUNT_REPO))
            return

        if os.path.exists(settings.HUNT_REPO):
            shutil.rmtree(settings.HUNT_REPO)

        if not os.path.isfile(settings.SSH_KEY):
            with os.fdopen(os.open(os.path.expanduser(settings.SSH_KEY), os.O_WRONLY | os.O_CREAT, 0o600), 'w') as handle:
                handle.write(os.environ.get('BUILDPACK_SSH_KEY'))

            with open(os.path.expanduser("~/.ssh/config"), "a") as config:
                config.write("Host github.com\n")
                config.write("  StrictHostKeyChecking no\n")
                config.write("  UserKnownHostsFile /dev/null\n")
                config.write("  LogLevel ERROR\n")

        os.system("git config --global user.name \"Puzzup\"")
        os.system("git config --global user.email \"no-reply@lol.puzzup.lol\"")

        git_ssh_id_file = os.path.expanduser(settings.SSH_KEY)
        git_ssh_cmd = 'ssh -i %s' % git_ssh_id_file

        repo = git.Repo.clone_from(settings.HUNT_REPO_URL, settings.HUNT_REPO, env={"GIT_SSH_COMMAND": git_ssh_cmd })
        repo.remotes.origin.set_url(settings.HUNT_REPO_URL)
