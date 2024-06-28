import cloup as click

from ofscraper.const.constants import DYNAMIC_OPTIONS, KEY_OPTIONS

no_cache_option = click.option(
    "-nc",
    "--no-cache",
    help="Disable cache and forces consecutive api scan",
    default=False,
    is_flag=True,
)  # Define individual options


no_api_cache_option = click.option(
    "-nca",
    "--no-api-cache",
    help="Forces consecutive api scan",
    default=False,
    is_flag=True,
)

key_mode_option = click.option(
    "-k",
    "--key-mode",
    help="Key mode override",
    default=None,
    type=click.Choice(KEY_OPTIONS),
)

dynamic_rules_option = click.option(
    "-dr",
    "--dynamic-rules",
    "--dynamic-rule",
    help="Dynamic signing",
    default=None,
    type=click.Choice(DYNAMIC_OPTIONS, case_sensitive=False),
    callback=lambda ctx, param, value: value.lower() if value else None,
)

update_profile_option = click.option(
    "-up",
    "--update-profile",
    help="Get up-to-date profile info instead of using cache",
    default=False,
    is_flag=True,
)

download_script_option = click.option(
    "-ds",
    "--download-script",
    "download_script",
    help="""
    \b
    runs a script post model download
    addional args sent to script username, model_id, media json ,and post json
    """,
)
