# Report publication

## Sub-features

Text, JSON, XML, and HTML report files; quiet stdout; publication failure cleanup; POSIX permissions.

## How to get to it (user POV)

Run `messpy <directory> json python --reportfile <destination>`.

## Driving it with the parity helper

Run `python scripts/verify_state_machine_parity.py`. It removes each previous temporary report, invokes the CLI, and compares its status, streams, and complete file contents in four formats. Run `python -m unittest discover -s tests -p test_cli.py` for publication failure and permission cases.

## Gotchas

The differential cases cover successful writes. The CLI tests inject failures at the filesystem boundary to prove the old destination survives and staging files are removed. POSIX permission tests skip on Windows; parity is not evidence of Windows permission behavior.
