import cloup as click
from ofscraper.utils.args.bundles.manual import manual_args
@manual_args
@click.pass_context
def manual(ctx, *args, **kwargs):
    return ctx.params, ctx.info_name
