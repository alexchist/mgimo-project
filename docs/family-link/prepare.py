"""Prepare an isolated practice folder; never run a model or overwrite a case."""
import argparse
from pathlib import Path
from shutil import copy2

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / 'evals/cases/family-link'


def copy(relative, destination, base=ROOT):
    destination.parent.mkdir(parents=True, exist_ok=True)
    copy2(base / relative, destination)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('step', choices=['start', 'update'])
    p.add_argument('folder', type=Path)
    args = p.parse_args()
    dest = args.folder.resolve()
    if dest == ROOT or ROOT in dest.parents:
        p.exit(2, 'Choose a NEW folder outside the repository.\n')
    if args.step == 'start':
        if dest.exists():
            p.exit(2, 'Folder already exists; nothing was replaced.\n')
        dest.mkdir(parents=True)
        # Only operational instructions enter the exercise, never the jury's worked answers.
        copy('WORKFLOW.md', dest / 'AGENTS.md')
        for name in ['BIBLE.md', 'CLAUDE.md', '.cursor/rules/strategist.mdc', '.cursorignore', 'tools/README.md']:
            copy(name, dest / name)
        # Runtime utilities and their local dictionaries, not tests, answers or generated fixtures.
        for src in sorted((ROOT / 'tools').iterdir()):
            if src.is_file() and not src.is_symlink() and src.suffix in {'.py', '.json'} and src.name != 'generate_fixtures.py':
                copy(src.relative_to(ROOT), dest / 'tools' / src.name)
        # Example clients and prepared test workspaces belong to the full repository.
        for name in ['adapters/claude/source-hook.example.json', 'adapters/mcp/cursor-mcp.example.json']:
            copy(name, dest / name)
        for area in ['skills', 'prompts', 'templates/project', 'knowledge']:
            for src in sorted((ROOT / area).rglob('*')):
                if src.is_file() and not src.is_symlink() and (src.name == '.gitkeep' or src.suffix in {'.md', '.csv', '.json'}):
                    copy(src.relative_to(ROOT), dest / src.relative_to(ROOT))
        (dest / 'README.md').write_text('# Семейное демо\n\nВ новом чате откройте AGENTS.md и передайте вопрос из request.txt.\n\nЕсли кейса ещё нет: `python3 tools/strategist.py init projects/family --slug family --title "Связь для близких"`.\n', encoding='utf-8')
    elif not (dest / 'projects/family/project.json').is_file():
        p.exit(2, 'No first-session family case here.\n')
    mat = dest / 'materials' / args.step
    if mat.exists() or (args.step == 'update' and (dest / 'update-request.txt').exists()):
        p.exit(2, 'This step is already present; no files changed.\n')
    mat.mkdir(parents=True)
    names = ['meeting.md', 'tariff.md', 'design.csv'] if args.step == 'start' else ['shadow.csv', 'note.md']
    for name in names:
        copy(name, mat / name, PACK / args.step)
    first = args.step == 'start'
    request = dest / ('request.txt' if first else 'update-request.txt')
    copy('docs/family-link/' + ('first.txt' if first else 'second.txt'), request)
    print(f'Open {dest} in your agent IDE. New chat: {request.name}')


if __name__ == '__main__':
    main()
