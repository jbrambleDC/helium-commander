import dpath.util as dpath
import sys
import os
import click
import uuid
from . import writer
from requests.compat import urlsplit
from functools import update_wrapper, reduce
from importlib import import_module


def is_uuid(str):
    try:
        uuid.UUID(str)
        return True
    except ValueError:
        return False


def lookup_resource_id(list, id_rep, name_path=None, mac=False, **kwargs):
    if hasattr(list, '__call__'):
        list = list().get('data')
    _is_uuid = not mac and is_uuid(id_rep)
    id_rep_lower = id_rep.lower()
    id_rep_len = len(id_rep)
    name_path = name_path or "attributes/name"
    matches = []
    for entry in list:
        entry_id = entry.get('id')
        if _is_uuid:
            if entry_id == id_rep:
                return entry_id
        elif mac:
            try:
                entry_mac = dpath.get(entry, 'meta/mac')
                if entry_mac[-id_rep_len:].lower() == id_rep_lower:
                    matches.append(entry_id.encode('utf8'))
            except KeyError:
                pass

        else:
            short_id = shorten_id(entry_id)
            if short_id == id_rep:
                matches.append(entry_id.encode('utf8'))
            else:
                try:
                    entry_name = dpath.get(entry, name_path)
                    if entry_name[:id_rep_len].lower() == id_rep_lower:
                        matches.append(entry_id.encode('utf8'))
                except KeyError:
                    pass
    if len(matches) == 0:
        raise KeyError('Id: ' + id_rep.encode('utf8') + ' does not exist')
    elif len(matches) > 1:
        short_matches = [shorten_id(id) for id in matches]
        match_list = ' (' + ', '.join(short_matches) + ')'
        raise KeyError('Ambiguous id: ' + id_rep.encode('utf8') + match_list)

    return matches[0]


def shorten_id(str):
    return str.split('-')[0]


def shorten_json_id(json, **kwargs):
    # Ugh, reaching for global state isn't great but very convenient here
    _uuid = kwargs.get('uuid', False)
    try:
        root_context = click.get_current_context().find_root()
        shorten = not root_context.params.get('uuid', False)
    except RuntimeError:
        shorten = not _uuid
    json_id = json.get('id')
    return shorten_id(json_id) if shorten else json_id


def tabulate(result, map, **kwargs):
    if not map or not result:
        return result

    file = kwargs.pop('file', click.utils.get_text_stream('stdout'))
    with writer.for_format(output_format(**kwargs),
                           file, mapping=map, **kwargs) as _writer:
        _writer.write_entries(result)


def map_script_filenames(json):
    files = dpath.get(json, 'meta/scripts')
    return ', '.join(extract_script_filenames(files))


def extract_script_filenames(files):
    return [urlsplit(url).path.split('/')[-1] for url in files]


def output_format(default_format='tabular', **kwargs):
    override_format = kwargs.get('format')
    try:
        root_context = click.get_current_context().find_root()
        click_format = root_context.params.get('format')
    except RuntimeError:
        click_format = None
    return override_format or click_format or default_format


def sort_option(options):
    options = [
        click.option('--reverse', is_flag=True,
                     help='Sort in reverse order'),
        click.option('--sort', type=click.Choice(options),
                     help='How to sort the result')
    ]

    def wrapper(func):
        for option in reversed(options):
            func = option(func)
        return func
    return wrapper


class ResourceParamType(click.ParamType):
    name = 'resource'

    def __init__(self, nargs=-1, metavar='TEXT'):
        self.nargs = nargs
        self.metavar = metavar

    def get_metavar(self, param):
        metavar = self.metavar
        if self.nargs == -1:
            return '{0}[,{0},...]* | @filename'.format(metavar)
        else:
            return metavar

    def convert(self, value, param, ctx):
        def collect_resources(acc, resource_rep):
            if resource_rep.startswith('@'):
                for line in click.open_file(resource_rep[1:]):
                    acc.append(line.strip())
            else:
                acc.append(resource_rep)
            return acc
        nargs = self.nargs
        value = value.split(',') if isinstance(value, basestring) else value
        resources = reduce(collect_resources, value, [])
        if nargs > 0 and nargs != len(resources):
            self.fail('Expected {} resources, but got {}'.format(nargs, len(resources)))
        return resources

    def __repr__(self):
        'Resource(metavar={}, nargs={})'.fomat(self.metavar, self.nargs)


def update_resource_relationship(resources, find_item_id, **kwargs):
    """Constructs an updated relationship list.

    Takes the items in the relationship and items to be added in
    'added' or removed in 'remove' and returns a new list with the new
    list of ids or None if no difference was detected
    """
    def _extract_list(items):
        return items.split(',') if isinstance(items, basestring) else items

    item_ids = dpath.values(resources, "*/id")
    remove_items = kwargs.pop('remove', None)
    if remove_items:
        remove_items = _extract_list(remove_items)
        remove_items = [find_item_id(item, **kwargs) for item in remove_items]
        item_ids = set.difference(set(item_ids), set(remove_items))

    add_items = kwargs.pop('add', None)
    if add_items:
        add_items = _extract_list(add_items)
        add_items = [find_item_id(item, **kwargs) for item in add_items]
        item_ids = set.union(set(item_ids), set(add_items))

    if add_items or remove_items:
        if item_ids is None:
            item_ids = []
        return item_ids

    return None


CONTEXT_SETTINGS = dict(
    help_option_names=['-h', '--help']
)


def cli(version=None, package=None,  commands=None):
    class Loader(click.MultiCommand):
        def list_commands(self, ctx):
            commands.sort()
            return commands

        def get_command(self, ctx, name):
            try:
                command = import_module(package + "." + name)
                return command.cli
            except ImportError as e:
                click.secho(str(e), fg='red')
                return

    def decorator(f):
        @click.option('--uuid', is_flag=True,
                      help="Whether to display long identifiers")
        @click.option('--format',
                      type=click.Choice(['csv', 'json', 'tabular']),
                      default=None,
                      help="The output format (default 'tabular')")
        @click.version_option(version=version)
        @click.command(cls=Loader, context_settings=CONTEXT_SETTINGS)
        @click.pass_context
        def new_func(ctx, *args, **kwargs):
            ctx.invoke(f, ctx, *args, **kwargs)
        return update_wrapper(new_func, f)
    return decorator


def main(cli):
    def decorator():
        args = sys.argv[1:]
        try:
            cli.main(args=args, prog_name=None)
        except Exception as e:
            if os.environ.get("HELIUM_COMMANDER_DEBUG"):
                raise
            click.secho(str(e), fg='red')
            sys.exit(1)
    return decorator
