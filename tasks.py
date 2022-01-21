import os

from invoke import task

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings.dev")

HUNT_SLUG = "puzzup"

HEROKU_MANAGE = f"heroku run --app={HUNT_SLUG} python manage.py"

@task
def lint(c):
    c.run("pylint --disable=R,C,W0511 $(git ls-files '*.py')")


@task
def pytype(c):
    c.run("pytype $(git ls-files '*.py')")


@task
def run(c):
    c.run("./manage.py runserver 4004")


@task
def export_users(c):
    c.run(
        "./manage.py dumpdata --format=yaml puzzle_editing.user --indent 4 > puzzle_editing/fixtures/auth.yaml"
    )


@task
def export_users_from_prod(c):
    c.run(f"{HEROKU_MANAGE} dumpdata --format=yaml puzzle_editing.user --indent 4 > puzzle_editing/fixtures/auth.yaml")


@task
def export_prod(c):
    c.run(f"{HEROKU_MANAGE} dumpdata --format=yaml puzzle_editing --indent 4 > puzzle_editing/fixtures/data.yaml")


@task
def prod_shell(c):
    c.run(f"{HEROKU_MANAGE} shell")


@task
def count_channels(c):
    c.run(f"{HEROKU_MANAGE} shell -c 'from puzzle_editing.discord_integration import get_client;c=get_client();print(len(c.get_channels_in_guild()))'")


@task
def migrate(c):
    c.run("./manage.py migrate")


@task
def load_users(c):
    c.run("./manage.py loaddata auth")
    c.run("./manage.py loaddata groups")

@task
def load_data(c):
    c.run("./manage.py loaddata auth")
    c.run("./manage.py loaddata groups")
    c.run("./manage.py loaddata puzzles")


@task
def regen(c):
    """
    Rebuild database from seeds. This will *destroy* your local database, so use with caution.
    """
    c.run(f"dropdb {HUNT_SLUG}")
    c.run(f"createdb {HUNT_SLUG}")
    migrate(c)
    load_data(c)


@task
def shiva_the_destroyer(c):
    """
    Redo all migrations and load data from seeds. This will *destroy* your local database, so use with caution.
    """
    c.run(f"dropdb {HUNT_SLUG}")
    c.run(f"createdb {HUNT_SLUG}")
    c.run("rm -f puzzle_editing/migrations/*.py")
    c.run("./manage.py makemigrations puzzle_editing")
    migrate(c)
    load_data(c)


@task
def push(c):
    """
    Push to GitHub, which will automatically push to Heroku. Migration happens automatically.
    """
    c.run("git push origin master")


@task
def load_prod(c):
    """
    Load puzzle and text response data from fixtures on production.
    """
    c.run(f"{HEROKU_MANAGE} loaddata puzzles")


@task
def load_all_prod(c):
    """
    Load all data from fixtures on production.
    """
    c.run(f"{HEROKU_MANAGE} loaddata auth")
    c.run(f"{HEROKU_MANAGE} loaddata groups")
    c.run(f"{HEROKU_MANAGE} loaddata puzzles")


# @task
# def regen_prod(c):
#     """
#     COMPLETELY DESTROY PROD DATABASE WITH NO RECOURSE! DON'T DO IT!
#     """
#     c.run(f"heroku pg:reset --app={HUNT_SLUG} --confirm={HUNT_SLUG}")
#     c.run(f"{HEROKU_MANAGE} migrate")
#     c.run(f"{HEROKU_MANAGE} loaddata auth")
#     c.run(f"{HEROKU_MANAGE} loaddata groups")
#     c.run(f"{HEROKU_MANAGE} loaddata puzzles")
