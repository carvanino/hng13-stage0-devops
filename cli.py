"""
A test script for cli
"""
import click


@click.group()
def cli():
    pass

@click.command()
@click.argument('name')
@click.option('--count', default=1, help='Number of greetings.')
def hello(name, count):
    """Simple program that greets NAME for a total of COUNT times."""
    for x in range(count):
        click.echo(f"Hello x:{x} {name}!")

if __name__ == '__main__':
    cli()